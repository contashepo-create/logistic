# -*- coding: utf-8 -*-
"""
طبقة العمليات (CRUD) لكل كيانات النظام مع التحقق وقواعد النظام العامة.

كل دالة كتابة تتحقق من:
  - قاعدة السنوات المالية (لا حركات خارج السنة المفتوحة).
  - سلامة المراجع (منع حذف بيانات مرتبط بها حركات).
الأرصدة لا تُخزَّن؛ تُحسب لحظياً من الحركات => إعادة الاحتساب تلقائية بأثر رجعي.
"""
from __future__ import annotations

import json
import shutil
import sqlite3
from pathlib import Path

from . import calc, db, tax
from .rules import (
    RuleError, ensure_date_in_open_year, ensure_movement_editable,
    ensure_positive, ensure_not_blank, safe_financial_year
)
from .security import safe_text

# ---------------------------------------------------------------------------
# الإعدادات
# ---------------------------------------------------------------------------
def get_setting(conn, key: str, default: str = "") -> str:
    r = conn.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
    return r["value"] if r and r["value"] is not None else default


def set_setting(conn, key: str, value: str) -> None:
    conn.execute(
        "INSERT INTO settings(key, value) VALUES(?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        (key, str(value)),
    )
    conn.commit()


def company_info(conn) -> dict:
    return {k: get_setting(conn, k, v) for k, v in db.DEFAULT_SETTINGS.items()}


def current_vat_rate(conn) -> float:
    """نسبة ضريبة القيمة المضافة المعتمدة في الإعدادات (الافتراضي 15%)."""
    try:
        return max(0.0, min(100.0, float(get_setting(conn, "vat_rate", "15") or 15)))
    except (TypeError, ValueError):
        return 15.0


def _bounded(value, field: str, low: float, high: float,
             as_int: bool = False) -> float:
    """رقم ضمن نطاق محدد (يمنع القيم الفاسدة والضخمة)."""
    try:
        v = float(str(value).strip() if value not in (None, "") else "nan")
    except (TypeError, ValueError):
        raise RuleError(f"قيمة «{field}» غير صالحة.")
    if v != v or v in (float("inf"), float("-inf")):
        raise RuleError(f"قيمة «{field}» غير صالحة.")
    if v < low or v > high:
        raise RuleError(f"«{field}» يجب أن تكون بين {low} و {high}.")
    return int(round(v)) if as_int else round(v, 2)


def _round_money(value) -> float:
    return tax.round2(_m(value))


def _positive_id(value, field: str) -> int:
    try:
        v = int(str(value).strip())
    except (TypeError, ValueError):
        raise RuleError(f"معرّف «{field}» غير صالح.")
    if v <= 0:
        raise RuleError(f"اختر {field}.")
    return v


# ---------------------------------------------------------------------------
# أدوات مساعدة
# ---------------------------------------------------------------------------
def _next_number(conn, table: str) -> int:
    r = conn.execute(f"SELECT COALESCE(MAX(number), 0) + 1 AS n FROM {table}").fetchone()
    return int(r["n"])


def _stamp_code(conn, table: str, row_id: int, prefix: str) -> str:
    code = f"{prefix}-{row_id:04d}"
    conn.execute(f"UPDATE {table} SET code=? WHERE id=?", (code, row_id))
    return code


def _count(conn, sql: str, params=()) -> int:
    return int(conn.execute(sql, params).fetchone()[0])


def _m(x) -> float:
    """تقنية دفاعية: كل مبلغ يُخزَّن مقرباً لمنزلتين عشريتين وضمن سقف منطقي."""
    try:
        v = round(float(x or 0), 2)
    except (TypeError, ValueError):
        raise RuleError("قيمة مبلغ غير صالحة.")
    if abs(v) > 999_999_999_999.0:
        raise RuleError("المبلغ خارج النطاق المسموح (الحد 999,999,999,999).")
    return v


def _txt(value, field: str, max_len: int = 5000) -> str:
    """تحقق وتعقيم مركزي لكل نص قبل وصوله إلى قاعدة البيانات.

    يمنع: إغراق قاعدة البيانات (الطول)، محارف التحكم والاتجاهات الخفية،
    الأنماط الهجومية الصريحة (حقن SQL/HTML/قوالب/اجتياز مسارات).
    مطابق لـ `txt` في نسخة الويب.
    """
    return safe_text(value, field, max_len)


# ---------------------------------------------------------------------------
# السنوات المالية
# ---------------------------------------------------------------------------
def list_years(conn) -> list[sqlite3.Row]:
    return conn.execute("SELECT * FROM financial_years ORDER BY year DESC").fetchall()


def get_year(conn, year_id: int) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM financial_years WHERE id=?", (year_id,)).fetchone()


def save_year(conn, data: dict, year_id: int | None = None) -> int:
    ensure_not_blank(str(data.get("year", "")), "السنة")
    # تحقق الصيغة ووجود التاريخ فعلياً ومدة السنة (مطابقة لنسخة الويب)
    date_from, date_to, derived_year = safe_financial_year(
        data.get("date_from"), data.get("date_to"))
    try:
        year = int(data["year"])
    except (TypeError, ValueError):
        raise RuleError("السنة المالية يجب أن تكون رقماً صحيحاً.") from None
    if year != derived_year:
        raise RuleError(
            f"رقم السنة ({year}) لا يطابق سنة تاريخ البداية ({derived_year}).")
    dup = conn.execute(
        "SELECT id FROM financial_years WHERE year=? AND id != ?",
        (year, year_id or -1),
    ).fetchone()
    if dup:
        raise RuleError(f"السنة المالية {year} مسجلة مسبقاً.")
    overlap = conn.execute(
        "SELECT year FROM financial_years WHERE id != ? AND date_from <= ? AND date_to >= ?",
        (year_id or -1, date_to, date_from),
    ).fetchone()
    if overlap:
        raise RuleError(
            f"نطاق هذه السنة يتداخل مع السنة المالية {overlap['year']} المسجلة مسبقاً "
            "(التداخل يسبب احتساباً مزدوجاً في التقارير ولقطات الإغلاق).")
    if year_id:
        conn.execute(
            "UPDATE financial_years SET year=?, date_from=?, date_to=?, notes=? WHERE id=?",
            (year, date_from, date_to, data.get("notes", ""), year_id),
        )
        conn.commit()
        return year_id
    cur = conn.execute(
        "INSERT INTO financial_years(year, date_from, date_to, status, notes) "
        "VALUES(?,?,?,?,?)",
        (year, date_from, date_to, "open", data.get("notes", "")),
    )
    conn.commit()
    return int(cur.lastrowid)


def set_year_status(conn, year_id: int, status: str) -> None:
    if status not in ("open", "closed"):
        raise RuleError("حالة غير صالحة للسنة المالية.")
    conn.execute("UPDATE financial_years SET status=? WHERE id=?", (status, year_id))
    conn.commit()


def movements_count_in_range(conn, d_from: str, d_to: str) -> int:
    total = 0
    for table in ("invoices", "receipt_vouchers", "payment_vouchers", "payrolls"):
        total += _count(
            conn, f"SELECT COUNT(*) FROM {table} WHERE date >= ? AND date <= ?",
            (d_from, d_to),
        )
    return total


def delete_year(conn, year_id: int) -> None:
    y = get_year(conn, year_id)
    if not y:
        return
    n = movements_count_in_range(conn, y["date_from"], y["date_to"])
    if n:
        raise RuleError(
            f"لا يمكن حذف السنة {y['year']}: توجد {n} حركة مسجلة ضمن نطاقها.\n"
            "احذف الحركات أولاً أو أبقِ السنة للأرشفة."
        )
    conn.execute("DELETE FROM financial_years WHERE id=?", (year_id,))
    conn.commit()


def create_snapshot(conn, year_id: int) -> dict:
    """إنشاء/تحديث لقطة إغلاق السنة (أرصدة العملاء والخزائن والبنوك + أرباح السنة)."""
    data = calc.year_snapshot_data(conn, year_id)
    if not data:
        raise RuleError("السنة المالية غير موجودة.")
    conn.execute(
        "INSERT INTO year_snapshots(year_id, data) VALUES(?, ?) "
        "ON CONFLICT(year_id) DO UPDATE SET data=excluded.data, "
        "created_at=datetime('now','localtime')",
        (year_id, json.dumps(data, ensure_ascii=False)),
    )
    conn.commit()
    return data


def get_snapshot(conn, year_id: int) -> dict | None:
    r = conn.execute(
        "SELECT data FROM year_snapshots WHERE year_id=?", (year_id,)
    ).fetchone()
    return json.loads(r["data"]) if r else None


# ---------------------------------------------------------------------------
# العملاء
# ---------------------------------------------------------------------------
def list_customers(conn) -> list[sqlite3.Row]:
    return conn.execute("SELECT * FROM customers ORDER BY code").fetchall()


def get_customer(conn, customer_id: int) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM customers WHERE id=?", (customer_id,)).fetchone()


TAX_COLUMNS = (
    "tax_number", "commercial_reg", "entity_type", "tax_status", "country",
    "region", "city", "district", "street", "building_no", "postal_code",
    "additional_no",
)


def _tax_columns_sql(data: dict) -> str:
    return ", ".join(f"{c}=?" for c in TAX_COLUMNS)


def _tax_values(data: dict) -> list:
    return [data.get(c, "") for c in TAX_COLUMNS]


def save_customer(conn, data: dict, customer_id: int | None = None) -> int:
    """حفظ العميل مع الحزمة الضريبية والعنوان الوطني (مطابق لنسخة الويب)."""
    ensure_not_blank(data.get("name", ""), "اسم العميل")
    for k, label in (("name", "اسم العميل"), ("address", "العنوان"),
                     ("phone", "الهاتف"), ("notes", "الملاحظات")):
        data[k] = _txt(data.get(k, ""), label)
    # تطبيع الحزمة الضريبية + تحقّق شامل برسائل عربية
    normalized = tax.normalize_tax_profile({
        c: data.get(c, "") for c in TAX_COLUMNS})
    errors = tax.validate_tax_profile(normalized)
    if errors:
        raise RuleError("\n".join(errors))
    data.update(normalized)

    if customer_id:
        conn.execute(
            f"UPDATE customers SET name=?, address=?, phone=?, opening_balance=?, "
            f"notes=?, {_tax_columns_sql(data)} WHERE id=?",
            (data["name"], data.get("address", ""), data.get("phone", ""),
             _m(data.get("opening_balance", 0)), data.get("notes", ""),
             *_tax_values(data), customer_id),
        )
        conn.commit()
        return customer_id
    cur = conn.execute(
        f"INSERT INTO customers(name, address, phone, opening_balance, notes, "
        f"{', '.join(TAX_COLUMNS)}) VALUES(?,?,?,?,?{',?' * len(TAX_COLUMNS)})",
        (data["name"], data.get("address", ""), data.get("phone", ""),
         _m(data.get("opening_balance", 0)), data.get("notes", ""),
         *_tax_values(data)),
    )
    cid = int(cur.lastrowid)
    _stamp_code(conn, "customers", cid, "CUST")
    conn.commit()
    return cid


def delete_customer(conn, customer_id: int) -> None:
    n_inv = _count(conn, "SELECT COUNT(*) FROM invoices WHERE customer_id=?", (customer_id,))
    n_rec = _count(
        conn, "SELECT COUNT(*) FROM receipt_vouchers WHERE customer_id=?", (customer_id,))
    n_note = _count(
        conn, "SELECT COUNT(*) FROM credit_debit_notes WHERE customer_id=?", (customer_id,))
    if n_inv or n_rec or n_note:
        raise RuleError(
            "لا يمكن حذف العميل لوجود حركات مرتبطة به "
            f"({n_inv} فاتورة، {n_rec} سند قبض، {n_note} إشعار)."
        )
    conn.execute("DELETE FROM customers WHERE id=?", (customer_id,))
    conn.commit()


# ---------------------------------------------------------------------------
# الموظفون والسائقون
# ---------------------------------------------------------------------------
def list_employees(conn, emp_type: str | None = None) -> list[sqlite3.Row]:
    if emp_type:
        return conn.execute(
            "SELECT * FROM employees WHERE emp_type=? ORDER BY code", (emp_type,)
        ).fetchall()
    return conn.execute("SELECT * FROM employees ORDER BY code").fetchall()


def get_employee(conn, employee_id: int) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM employees WHERE id=?", (employee_id,)).fetchone()


def save_employee(conn, data: dict, employee_id: int | None = None) -> int:
    ensure_not_blank(data.get("name", ""), "اسم الموظف")
    for k, label in (("name", "الاسم"), ("nationality", "الجنسية"),
                     ("phone", "الهاتف"), ("notes", "الملاحظات")):
        data[k] = _txt(data.get(k, ""), label)
    if data.get("emp_type") not in ("driver", "admin"):
        raise RuleError("اختر نوع الموظف (سائق / إداري).")
    base_salary = _bounded(data.get("base_salary", 0), "الراتب الأساسي", 0, 1_000_000_000)
    if employee_id:
        old = get_employee(conn, employee_id)
        if old and old["emp_type"] != data["emp_type"]:
            linked = (_count(conn, "SELECT COUNT(*) FROM invoice_trips WHERE driver_id=?",
                             (employee_id,))
                      + _count(conn, "SELECT COUNT(*) FROM payrolls WHERE employee_id=?",
                               (employee_id,))
                      + _count(conn, "SELECT COUNT(*) FROM payment_vouchers WHERE employee_id=?",
                               (employee_id,))
                      + _count(conn, "SELECT COUNT(*) FROM vehicles WHERE default_driver_id=?",
                               (employee_id,)))
            if linked:
                raise RuleError("لا يمكن تغيير نوع الموظف لوجود حركات/سيارات مرتبطة به "
                                f"({linked} ارتباطاً).")
    vals = (data["name"], data.get("nationality", ""), data.get("phone", ""),
            data["emp_type"], base_salary, data.get("notes", ""))
    if employee_id:
        conn.execute(
            "UPDATE employees SET name=?, nationality=?, phone=?, emp_type=?, "
            "base_salary=?, notes=? WHERE id=?", (*vals, employee_id),
        )
        conn.commit()
        return employee_id
    cur = conn.execute(
        "INSERT INTO employees(name, nationality, phone, emp_type, base_salary, notes) "
        "VALUES(?,?,?,?,?,?)", vals,
    )
    eid = int(cur.lastrowid)
    _stamp_code(conn, "employees", eid, "EMP")
    conn.commit()
    return eid


def delete_employee(conn, employee_id: int) -> None:
    refs = (
        _count(conn, "SELECT COUNT(*) FROM payrolls WHERE employee_id=?", (employee_id,)),
        _count(conn, "SELECT COUNT(*) FROM payment_vouchers WHERE employee_id=?",
               (employee_id,)),
        _count(conn, "SELECT COUNT(*) FROM invoice_trips WHERE driver_id=?", (employee_id,)),
    )
    if any(refs):
        raise RuleError(
            "لا يمكن حذف الموظف لوجود حركات مرتبطة به "
            f"(رواتب: {refs[0]}، سلف: {refs[1]}، نقلات: {refs[2]})."
        )
    conn.execute("DELETE FROM employees WHERE id=?", (employee_id,))
    conn.commit()


# ---------------------------------------------------------------------------
# السيارات
# ---------------------------------------------------------------------------
def list_vehicles(conn) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT v.*, e.name AS driver_name FROM vehicles v "
        "LEFT JOIN employees e ON e.id=v.default_driver_id ORDER BY v.code"
    ).fetchall()


def get_vehicle(conn, vehicle_id: int) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM vehicles WHERE id=?", (vehicle_id,)).fetchone()


def save_vehicle(conn, data: dict, vehicle_id: int | None = None) -> int:
    ensure_not_blank(data.get("plate_number", ""), "رقم اللوحة")
    for k, label in (("plate_number", "رقم اللوحة"), ("vehicle_type", "النوع"),
                     ("notes", "الملاحظات")):
        data[k] = _txt(data.get(k, ""), label)
    drv = data.get("default_driver_id") or None
    if drv is not None:
        emp = get_employee(conn, drv)
        if emp is None or emp["emp_type"] != "driver":
            raise RuleError("السائق الافتراضي يجب أن يكون موظفاً من نوع (سائق).")
    vals = (data["plate_number"], data.get("vehicle_type", ""), drv)
    if vehicle_id:
        conn.execute(
            "UPDATE vehicles SET plate_number=?, vehicle_type=?, default_driver_id=? "
            "WHERE id=?", (*vals, vehicle_id),
        )
        conn.commit()
        return vehicle_id
    cur = conn.execute(
        "INSERT INTO vehicles(plate_number, vehicle_type, default_driver_id) "
        "VALUES(?,?,?)", vals,
    )
    vid = int(cur.lastrowid)
    _stamp_code(conn, "vehicles", vid, "VEH")
    conn.commit()
    return vid


def delete_vehicle(conn, vehicle_id: int) -> None:
    refs = (
        _count(conn, "SELECT COUNT(*) FROM invoice_trips WHERE vehicle_id=?", (vehicle_id,)),
        _count(conn, "SELECT COUNT(*) FROM payment_vouchers WHERE vehicle_id=?",
               (vehicle_id,)),
    )
    if any(refs):
        raise RuleError(
            f"لا يمكن حذف السيارة لوجود حركات مرتبطة بها "
            f"(نقلات: {refs[0]}، سندات صيانة: {refs[1]})."
        )
    conn.execute("DELETE FROM vehicles WHERE id=?", (vehicle_id,))
    conn.commit()


# ---------------------------------------------------------------------------
# الخزائن والبنوك
# ---------------------------------------------------------------------------
def list_accounts(conn, kind: str) -> list[sqlite3.Row]:
    return conn.execute(
        f"SELECT * FROM {calc.account_table(kind)} ORDER BY code"
    ).fetchall()


def get_account(conn, kind: str, account_id: int) -> sqlite3.Row | None:
    return conn.execute(
        f"SELECT * FROM {calc.account_table(kind)} WHERE id=?", (account_id,)
    ).fetchone()


def save_account(conn, kind: str, data: dict, account_id: int | None = None) -> int:
    tbl = calc.account_table(kind)
    prefix = "CB" if kind == "cashbox" else "BNK"
    ensure_not_blank(data.get("name", ""), "اسم " + calc.account_kind_label(kind))
    for k, label in (("name", "الاسم"), ("account_number", "رقم الحساب"),
                     ("iban", "الآيبان"), ("notes", "الملاحظات")):
        data[k] = _txt(data.get(k, ""), label)
    if kind == "bank":
        if account_id:
            conn.execute(
                "UPDATE banks SET name=?, created_date=?, account_number=?, iban=?, "
                "opening_balance=?, notes=? WHERE id=?",
                (data["name"], data["created_date"], data.get("account_number", ""),
                 data.get("iban", ""), _m(data.get("opening_balance", 0)),
                 data.get("notes", ""), account_id),
            )
            conn.commit()
            return account_id
        cur = conn.execute(
            "INSERT INTO banks(name, created_date, account_number, iban, opening_balance, "
            "notes) VALUES(?,?,?,?,?,?)",
            (data["name"], data["created_date"], data.get("account_number", ""),
             data.get("iban", ""), _m(data.get("opening_balance", 0)),
             data.get("notes", "")),
        )
    else:
        if account_id:
            conn.execute(
                "UPDATE cashboxes SET name=?, created_date=?, opening_balance=?, notes=? "
                "WHERE id=?",
                (data["name"], data["created_date"],
                 _m(data.get("opening_balance", 0)), data.get("notes", ""),
                 account_id),
            )
            conn.commit()
            return account_id
        cur = conn.execute(
            "INSERT INTO cashboxes(name, created_date, opening_balance, notes) "
            "VALUES(?,?,?,?)",
            (data["name"], data["created_date"],
             _m(data.get("opening_balance", 0)), data.get("notes", "")),
        )
    aid = int(cur.lastrowid)
    _stamp_code(conn, tbl, aid, prefix)
    conn.commit()
    return aid


def delete_account(conn, kind: str, account_id: int) -> None:
    refs = (
        _count(conn, "SELECT COUNT(*) FROM receipt_vouchers WHERE account_kind=? AND account_id=?",
               (kind, account_id)),
        _count(conn, "SELECT COUNT(*) FROM payment_vouchers WHERE account_kind=? AND account_id=?",
               (kind, account_id)),
        _count(conn, "SELECT COUNT(*) FROM payrolls WHERE account_kind=? AND account_id=?",
               (kind, account_id)),
    )
    if any(refs):
        raise RuleError(
            "لا يمكن الحذف لوجود حركات مرتبطة "
            f"(قبض: {refs[0]}، دفع: {refs[1]}، رواتب: {refs[2]})."
        )
    conn.execute(f"DELETE FROM {calc.account_table(kind)} WHERE id=?", (account_id,))
    conn.commit()


# ---------------------------------------------------------------------------
# فواتير النقل
# ---------------------------------------------------------------------------
def list_invoices_raw(conn) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT i.*, c.name AS customer_name FROM invoices i "
        "JOIN customers c ON c.id=i.customer_id ORDER BY i.date DESC, i.number DESC"
    ).fetchall()


def save_invoice(conn, data: dict, invoice_id: int | None = None) -> int:
    """إصدار فاتورة نقل (رأس + نقلات + مصروفات + سندات تلقائية).

    مطابق لمنطق saveInvoice في نسخة الويب:
      • الفاتورة **لا تُعدَّل ولا تُحذف بعد الإصدار** — التصحيح بإشعار دائن/مدين.
      • لكل نقلة: عدد النقلات × سعر الوحدة + أرقام حاويات (بحد أقصى = العدد).
      • لكل مصروف: كمية × قيمة وحدة + مصدر تمويل (نقداً/عهدة سائق/آجل مورد/على العميل).
      • المصروف النقدي يُنشئ سند دفع تلقائي فوراً ويُخصم من الخزينة/البنك.
    """
    if invoice_id:
        raise RuleError(
            "الفاتورة الضريبية لا تقبل التعديل بعد إصدارها.\n"
            "أنشئ إشعاراً دائناً (مرتجع/خصم) أو إشعاراً مديناً (إضافة) للتصحيح."
        )
    date = data.get("date", "")
    ensure_not_blank(date, "تاريخ الفاتورة")
    customer_id = _positive_id(data.get("customer_id"), "العميل")
    if get_customer(conn, customer_id) is None:
        raise RuleError("العميل المحدد غير موجود.")
    trips = data.get("trips") or []
    if not trips:
        raise RuleError("أضف نقلة واحدة على الأقل للفاتورة.")
    if len(trips) > 1000:
        raise RuleError("عدد بنود النقل في الفاتورة أكبر من الحد المسموح.")
    notes = _txt(data.get("notes", ""), "ملاحظات الفاتورة")
    container_number = _txt(data.get("container_number", ""), "رقم الحاوية", 100)
    attachments = [_txt(a, "اسم المرفق", 180)
                   for a in (data.get("attachments") or []) if str(a).strip()][:10]
    vat_rate = (current_vat_rate(conn) if data.get("vat_rate") in (None, "")
                else _bounded(data["vat_rate"], "نسبة الضريبة", 0, 100))

    seen_containers: set[str] = set()
    for index, t in enumerate(trips, start=1):
        t["from_loc"] = _txt(t.get("from_loc", ""), "مكان الانطلاق", 200)
        t["to_loc"] = _txt(t.get("to_loc", ""), "مكان الوصول", 200)
        ensure_not_blank(t["from_loc"], "مكان الانطلاق")
        ensure_not_blank(t["to_loc"], "مكان الوصول")
        t["notes"] = _txt(t.get("notes", ""), "ملاحظات النقلة", 2000)
        t["vehicle_id"] = (t.get("vehicle_id") or None)
        t["driver_id"] = (t.get("driver_id") or None)
        qty = _bounded(t.get("qty", 1), f"عدد النقلات في السطر {index}", 1, 1_000_000, True)
        t["qty"] = qty
        raw_containers = t.get("container_numbers") or []
        if not isinstance(raw_containers, list):
            raise RuleError(f"أرقام حاويات النقلة {index} غير صالحة.")
        if len(raw_containers) > qty:
            raise RuleError(
                f"عدد أرقام الحاويات في النقلة {index} لا يجوز أن يتجاوز "
                f"عدد النقلات ({qty}).")
        cleaned: list[str] = []
        for ci, value in enumerate(raw_containers, start=1):
            container = _txt(value, f"رقم الحاوية {ci} في النقلة {index}", 100).strip()
            ensure_not_blank(container, f"رقم الحاوية {ci} في النقلة {index}")
            key = container.upper()
            if key in seen_containers:
                raise RuleError(f"رقم الحاوية «{container}» مكرر داخل الفاتورة.")
            seen_containers.add(key)
            cleaned.append(container)
        t["container_numbers"] = cleaned
        unit_price = _round_money(t.get("unit_price")
                                  or (_m(t.get("price", 0)) / qty if qty else 0))
        t["unit_price"] = unit_price
        t["price"] = tax.round2(qty * unit_price)
        if t["price"] <= 0:
            raise RuleError("سعر النقلة يجب أن يكون أكبر من صفر.")

        expenses = t.get("expenses") or []
        if len(expenses) > 1000:
            raise RuleError("عدد مصروفات النقلة أكبر من الحد المسموح.")
        for e in expenses:
            if e.get("expense_type") not in ("trip", "fuel", "card", "other"):
                raise RuleError("نوع مصروف النقلة غير صالح.")
            e["notes"] = _txt(e.get("notes", ""), "بيان المصروف", 2000)
            e["supplier_name"] = _txt(e.get("supplier_name", ""), "اسم المورد", 160)
            eq = _bounded(e.get("qty", 1), "كمية المصروف", 0.001, 1_000_000)
            e["qty"] = eq
            e["unit_amount"] = _round_money(
                e.get("unit_amount") or (_m(e.get("amount", 0)) / eq if eq else 0))
            e["amount"] = tax.round2(eq * e["unit_amount"])
            if e["amount"] <= 0:
                raise RuleError("مبلغ مصروف النقلة يجب أن يكون أكبر من صفر.")
            src = e.get("source") or "cash"
            if src not in ("cash", "driver", "supplier", "customer"):
                raise RuleError("مصدر تمويل المصروف غير صالح.")
            e["source"] = src
            if src == "cash":
                if e.get("account_kind") not in ("cashbox", "bank") or not e.get("account_id"):
                    raise RuleError("اختر الخزينة أو البنك الذي صُرف منه المصروف النقدي.")
                _ensure_account_exists(conn, e["account_kind"], e["account_id"])
            else:
                e["account_kind"] = None
                e["account_id"] = None
            if src == "driver" and not t.get("driver_id"):
                raise RuleError("حدّد السائق في النقلة قبل تسجيل مصروف من عهدته.")

    ensure_date_in_open_year(conn, date)

    # منع الرصيد السالب: مجموع المصروفات النقدية لكل جهة صرف
    needed: dict[tuple[str, int], float] = {}
    for t in trips:
        for e in t.get("expenses") or []:
            if e.get("source") != "cash":
                continue
            key = (e["account_kind"], int(e["account_id"]))
            needed[key] = tax.round2(needed.get(key, 0.0) + e["amount"])
    for (kind, acc_id), amount in needed.items():
        ensure_sufficient_funds(conn, kind, acc_id, amount)

    number = _next_number(conn, "invoices")
    cur = conn.execute(
        "INSERT INTO invoices(number, date, customer_id, vat_rate, notes, attachments, "
        "container_number) VALUES(?,?,?,?,?,?,?)",
        (number, date, customer_id, vat_rate, notes,
         json.dumps(attachments, ensure_ascii=False), container_number),
    )
    invoice_id = int(cur.lastrowid)
    try:
        for t in trips:
            tcur = conn.execute(
                "INSERT INTO invoice_trips(invoice_id, vehicle_id, driver_id, from_loc, "
                "to_loc, qty, unit_price, price, container_numbers, notes) "
                "VALUES(?,?,?,?,?,?,?,?,?,?)",
                (invoice_id, t.get("vehicle_id") or None, t.get("driver_id") or None,
                 t["from_loc"], t["to_loc"], t["qty"], t["unit_price"], t["price"],
                 json.dumps(t["container_numbers"], ensure_ascii=False), t["notes"]),
            )
            trip_id = int(tcur.lastrowid)
            for e in t.get("expenses") or []:
                ecur = conn.execute(
                    "INSERT INTO trip_expenses(trip_id, expense_type, qty, unit_amount, "
                    "amount, source, account_kind, account_id, supplier_name, notes) "
                    "VALUES(?,?,?,?,?,?,?,?,?,?)",
                    (trip_id, e["expense_type"], e["qty"], e["unit_amount"], e["amount"],
                     e["source"], e.get("account_kind"), e.get("account_id"),
                     e["supplier_name"], e["notes"]),
                )
                # سند دفع تلقائي للمصروف النقدي (يُستثنى من المصاريف اللاحقة)
                if e["source"] == "cash":
                    conn.execute(
                        "INSERT INTO payment_vouchers(number, date, account_kind, "
                        "account_id, voucher_type, trip_id, source_expense_id, quantity, "
                        "unit_amount, amount, description) "
                        "VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                        (_next_number(conn, "payment_vouchers"), date,
                         e["account_kind"], int(e["account_id"]), "trip", trip_id,
                         int(ecur.lastrowid), e["qty"], e["unit_amount"], e["amount"],
                         f"مصروف نقلة تلقائي — {e['notes'] or 'مصروف'}"),
                    )
    except Exception:
        conn.rollback()
        raise
    conn.commit()
    return invoice_id


def delete_invoice(conn, invoice_id: int) -> None:
    """لا تُحذف فاتورة ضريبية بعد إصدارها — التصحيح بالإشعارات."""
    raise RuleError(
        "لا يمكن حذف فاتورة ضريبية بعد إصدارها.\n"
        "استخدم إشعاراً دائناً (مرتجع نقلة أو خصم) أو إشعاراً مديناً للتصحيح."
    )


def current_account_balance(conn, kind: str, account_id: int,
                            exclude_payment_id: int | None = None,
                            exclude_payroll_id: int | None = None,
                            exclude_expense_ids: list[int] | None = None) -> float:
    """الرصيد الحالي لجهة نقدية، مع إمكانية استثناء حركات قيد التعديل."""
    tbl = calc.account_table(kind)
    bal = _m(_scalar(conn, f"SELECT opening_balance FROM {tbl} WHERE id=?", (account_id,)))
    bal += _scalar(
        conn, "SELECT COALESCE(SUM(amount),0) FROM receipt_vouchers "
              "WHERE account_kind=? AND account_id=?", (kind, account_id))
    for row in conn.execute(
        "SELECT id, amount, source_expense_id FROM payment_vouchers "
        "WHERE account_kind=? AND account_id=?", (kind, account_id),
    ):
        if exclude_payment_id and row["id"] == exclude_payment_id:
            continue
        if (exclude_expense_ids and row["source_expense_id"] is not None
                and row["source_expense_id"] in exclude_expense_ids):
            continue
        bal -= float(row["amount"] or 0)
    for row in conn.execute(
        "SELECT id, net_salary FROM payrolls WHERE account_kind=? AND account_id=?",
        (kind, account_id),
    ):
        if exclude_payroll_id and row["id"] == exclude_payroll_id:
            continue
        bal -= float(row["net_salary"] or 0)
    return tax.round2(bal)


def ensure_sufficient_funds(conn, kind: str, account_id: int, outflow: float,
                            exclude_payment_id: int | None = None,
                            exclude_payroll_id: int | None = None,
                            exclude_expense_ids: list[int] | None = None) -> None:
    """يرفض أي حركة صرف تجعل رصيد الخزينة/البنك سالباً (مطابق لنسخة الويب)."""
    amount = tax.round2(outflow)
    if amount <= 0:
        return
    _ensure_account_exists(conn, kind, account_id)
    balance = current_account_balance(
        conn, kind, account_id, exclude_payment_id, exclude_payroll_id,
        exclude_expense_ids)
    if amount > balance + 0.0001:
        from ..utils.fmt import money
        label = "الخزينة" if kind == "cashbox" else "البنك"
        raise RuleError(
            f"الرصيد لا يكفي: {label} «{calc.account_name(conn, kind, account_id)}» "
            f"رصيده {money(balance)} والمطلوب صرفه {money(amount)}.\n"
            "لا يُسمح بجعل الرصيد سالباً — سجّل إيداعاً أولاً أو اختر جهة صرف أخرى."
        )


def _scalar(conn, sql: str, params=()) -> float:
    r = conn.execute(sql, params).fetchone()
    return float(r[0]) if r and r[0] is not None else 0.0


def _ensure_account_exists(conn, kind: str, account_id) -> None:
    """التأكد أن الخزينة/البنك المشار إليه موجود فعلاً (منع مراجع وهمية)."""
    if get_account(conn, kind, account_id) is None:
        raise RuleError(
            f"جهة {'الخزينة' if kind == 'cashbox' else 'البنك'} المحددة غير موجودة.")


# ---------------------------------------------------------------------------
# سندات القبض
# ---------------------------------------------------------------------------
def list_receipts(conn, d_from=None, d_to=None, voucher_type=None) -> list[sqlite3.Row]:
    sql = ("SELECT v.*, c.name AS customer_name, "
           "CASE WHEN v.account_kind='cashbox' THEN cb.name ELSE b.name END AS account_name "
           "FROM receipt_vouchers v "
           "LEFT JOIN customers c ON c.id=v.customer_id "
           "LEFT JOIN cashboxes cb ON cb.id=v.account_id AND v.account_kind='cashbox' "
           "LEFT JOIN banks b ON b.id=v.account_id AND v.account_kind='bank' WHERE 1=1")
    params: list = []
    if d_from:
        sql += " AND v.date >= ?"
        params.append(d_from)
    if d_to:
        sql += " AND v.date <= ?"
        params.append(d_to)
    if voucher_type:
        sql += " AND v.voucher_type=?"
        params.append(voucher_type)
    sql += " ORDER BY v.date DESC, v.number DESC"
    return conn.execute(sql, params).fetchall()


def save_receipt(conn, data: dict, voucher_id: int | None = None) -> int:
    date = data["date"]
    amount = _m(data.get("amount", 0))
    ensure_not_blank(date, "تاريخ السند")
    ensure_positive(amount, "المبلغ")
    if data.get("voucher_type") not in ("customer", "other"):
        raise RuleError("اختر نوع السند.")
    if data["voucher_type"] == "customer" and not data.get("customer_id"):
        raise RuleError("اختر العميل المحصَّل منه.")
    data["description"] = _txt(data.get("description", ""), "البيان")
    if data.get("account_kind") not in ("cashbox", "bank") or not data.get("account_id"):
        raise RuleError("اختر جهة الإيداع (خزينة أو بنك).")
    _ensure_account_exists(conn, data["account_kind"], data["account_id"])
    if data.get("voucher_type") == "other":
        customer_id = None
    else:
        if get_customer(conn, data["customer_id"]) is None:
            raise RuleError("العميل المحدد غير موجود.")
        customer_id = data["customer_id"]
    vals = (date, data["account_kind"], data["account_id"], data["voucher_type"],
            customer_id, amount, data.get("description", ""))
    if voucher_id:
        old = conn.execute("SELECT date FROM receipt_vouchers WHERE id=?",
                           (voucher_id,)).fetchone()
        if not old:
            raise RuleError("السند غير موجود.")
        ensure_movement_editable(conn, old["date"], date)
        conn.execute(
            "UPDATE receipt_vouchers SET date=?, account_kind=?, account_id=?, "
            "voucher_type=?, customer_id=?, amount=?, description=? WHERE id=?",
            (*vals, voucher_id),
        )
        conn.commit()
        return voucher_id
    ensure_date_in_open_year(conn, date)
    number = _next_number(conn, "receipt_vouchers")
    cur = conn.execute(
        "INSERT INTO receipt_vouchers(number, date, account_kind, account_id, "
        "voucher_type, customer_id, amount, description) VALUES(?,?,?,?,?,?,?,?)",
        (number, *vals),
    )
    conn.commit()
    return int(cur.lastrowid)


def delete_receipt(conn, voucher_id: int) -> None:
    v = conn.execute("SELECT date FROM receipt_vouchers WHERE id=?",
                     (voucher_id,)).fetchone()
    if not v:
        return
    ensure_movement_editable(conn, v["date"])
    conn.execute("DELETE FROM receipt_vouchers WHERE id=?", (voucher_id,))
    conn.commit()


# ---------------------------------------------------------------------------
# سندات الدفع
# ---------------------------------------------------------------------------
def list_payments(conn, d_from=None, d_to=None, voucher_type=None) -> list[sqlite3.Row]:
    sql = ("SELECT v.*, e.name AS employee_name, vh.plate_number, "
           "c.name AS customer_name, i.number AS inv_number, "
           "CASE WHEN v.account_kind='cashbox' THEN cb.name ELSE b.name END AS account_name "
           "FROM payment_vouchers v "
           "LEFT JOIN employees e ON e.id=v.employee_id "
           "LEFT JOIN vehicles vh ON vh.id=v.vehicle_id "
           "LEFT JOIN invoice_trips t ON t.id=v.trip_id "
           "LEFT JOIN invoices i ON i.id=t.invoice_id "
           "LEFT JOIN customers c ON c.id=i.customer_id "
           "LEFT JOIN cashboxes cb ON cb.id=v.account_id AND v.account_kind='cashbox' "
           "LEFT JOIN banks b ON b.id=v.account_id AND v.account_kind='bank' WHERE 1=1")
    params: list = []
    if d_from:
        sql += " AND v.date >= ?"
        params.append(d_from)
    if d_to:
        sql += " AND v.date <= ?"
        params.append(d_to)
    if voucher_type:
        sql += " AND v.voucher_type=?"
        params.append(voucher_type)
    sql += " ORDER BY v.date DESC, v.number DESC"
    return conn.execute(sql, params).fetchall()


PAYMENT_VOUCHER_TYPES = ("trip", "advance", "vehicle", "general",
                         "supplier", "purchase", "owner")


def _validate_payment(conn, data: dict) -> None:
    vt = data.get("voucher_type")
    if vt not in PAYMENT_VOUCHER_TYPES:
        raise RuleError("اختر نوع السند.")
    amount = _m(data.get("amount", 0))
    ensure_positive(amount)
    if data.get("account_kind") not in ("cashbox", "bank") or not data.get("account_id"):
        raise RuleError("اختر جهة الصرف (خزينة أو بنك).")
    _ensure_account_exists(conn, data["account_kind"], data["account_id"])
    data["description"] = _txt(data.get("description", ""), "البيان")
    if vt == "trip" and not data.get("trip_id"):
        raise RuleError("اختر الرحلة (النقلة) التي يخصها المصروف.")
    if vt == "advance" and not data.get("employee_id"):
        raise RuleError("اختر الموظف/السائق للسلفة.")
    if vt == "vehicle" and not data.get("vehicle_id"):
        raise RuleError("اختر السيارة لمصروف الصيانة.")
    if vt == "supplier" and not data.get("supplier_id"):
        raise RuleError("اختر المورّد المُسدَّد له.")
    if data.get("trip_id"):
        t = conn.execute("SELECT id FROM invoice_trips WHERE id=?",
                         (data["trip_id"],)).fetchone()
        if not t:
            raise RuleError("الرحلة المحددة غير موجودة.")
    if vt == "advance" and get_employee(conn, data["employee_id"]) is None:
        raise RuleError("الموظف المحدد غير موجود.")
    if vt == "vehicle" and get_vehicle(conn, data["vehicle_id"]) is None:
        raise RuleError("السيارة المحددة غير موجودة.")
    if vt == "supplier":
        if get_supplier(conn, data["supplier_id"]) is None:
            raise RuleError("المورّد المحدد غير موجود.")
        if data.get("purchase_invoice_id"):
            row = conn.execute(
                "SELECT id, supplier_id FROM purchase_invoices WHERE id=?",
                (data["purchase_invoice_id"],)).fetchone()
            if not row:
                raise RuleError("فاتورة المشتريات المحددة غير موجودة.")
            if row["supplier_id"] != data["supplier_id"]:
                raise RuleError("فاتورة المشتريات لا تخص المورّد المحدد.")


def _payment_columns(data: dict) -> dict:
    """تطبيع أعمدة السند: كل توجيه يملأ مرجعه فقط (كما في نسخة الويب)."""
    vt = data["voucher_type"]
    description = data.get("description", "")
    if vt == "owner" and not str(description).strip():
        description = "سحب نقدي لصاحب المنشأة"
    return {
        "date": data["date"],
        "account_kind": data["account_kind"],
        "account_id": data["account_id"],
        "voucher_type": vt,
        "trip_id": data.get("trip_id") if vt == "trip" else None,
        "employee_id": data.get("employee_id") if vt == "advance" else None,
        "vehicle_id": data.get("vehicle_id") if vt == "vehicle" else None,
        "vehicle_expense": (_txt(data.get("vehicle_expense", ""), "نوع مصروف السيارة", 160)
                            if vt == "vehicle" else ""),
        "supplier_id": data.get("supplier_id") if vt == "supplier" else None,
        "purchase_invoice_id": (data.get("purchase_invoice_id")
                                if vt == "supplier" else None),
        "quantity": data.get("quantity", 1),
        "unit_amount": data.get("unit_amount", 0),
        "amount": data.get("amount", 0),
        "description": description,
    }


def save_payment(conn, data: dict, voucher_id: int | None = None) -> int:
    """سند دفع بأحد التوجيهات السبعة، بكمية × قيمة وحدة، ومنع الرصيد السالب."""
    date = data.get("date", "")
    ensure_not_blank(date, "تاريخ السند")
    data["date"] = date

    # توافق رجعي: الاستدعاءات التي ترسل amount فقط تُعامل كوحدة واحدة
    quantity = _bounded(data.get("quantity", 1), "كمية المصروف", 0.001, 1_000_000)
    fallback_amount = _round_money(data.get("amount", 0))
    unit_amount = _round_money(data.get("unit_amount")
                               or (fallback_amount / quantity if quantity else 0))
    if unit_amount <= 0:
        raise RuleError("قيمة وحدة المصروف يجب أن تكون أكبر من صفر.")
    data.update({"quantity": quantity, "unit_amount": unit_amount,
                 "amount": tax.round2(quantity * unit_amount)})
    _validate_payment(conn, data)
    row = _payment_columns(data)

    if voucher_id:
        old = conn.execute("SELECT date, voucher_type, employee_id, amount "
                           "FROM payment_vouchers WHERE id=?", (voucher_id,)).fetchone()
        if not old:
            raise RuleError("السند غير موجود.")
        # سند متولّد تلقائياً من فاتورة: يُعدَّل من الفاتورة نفسها لا هنا
        auto = conn.execute(
            "SELECT source_expense_id FROM payment_vouchers WHERE id=?",
            (voucher_id,)).fetchone()
        if auto and auto["source_expense_id"] is not None:
            raise RuleError(
                "هذا السند متولّد تلقائياً من مصروف نقدي داخل فاتورة نقل.\n"
                "لا يُعدَّل منفرداً — راجعه من فاتورته.")
        # سلفة عليها تسويات في الرواتب: منع التعديل حفاظاً على الدقة المحاسبية
        if old["voucher_type"] == "advance":
            settled = _count(
                conn, "SELECT COUNT(*) FROM advance_settlements WHERE payment_voucher_id=?",
                (voucher_id,))
            if settled:
                raise RuleError(
                    "لا يمكن تعديل سلفة تم خصم جزء/كل منها في مسير رواتب.\n"
                    "احذف الرواتب المرتبطة بها أولاً ثم عدّل السلفة."
                )
        ensure_movement_editable(conn, old["date"], date)
        ensure_sufficient_funds(conn, row["account_kind"], row["account_id"],
                                row["amount"], exclude_payment_id=voucher_id)
        conn.execute(
            "UPDATE payment_vouchers SET date=?, account_kind=?, account_id=?, "
            "voucher_type=?, trip_id=?, employee_id=?, vehicle_id=?, vehicle_expense=?, "
            "supplier_id=?, purchase_invoice_id=?, quantity=?, unit_amount=?, "
            "amount=?, description=? WHERE id=?",
            (row["date"], row["account_kind"], row["account_id"], row["voucher_type"],
             row["trip_id"], row["employee_id"], row["vehicle_id"], row["vehicle_expense"],
             row["supplier_id"], row["purchase_invoice_id"], row["quantity"],
             row["unit_amount"], row["amount"], row["description"], voucher_id),
        )
        conn.commit()
        return voucher_id

    ensure_date_in_open_year(conn, date)
    ensure_sufficient_funds(conn, row["account_kind"], row["account_id"], row["amount"])
    number = _next_number(conn, "payment_vouchers")
    cur = conn.execute(
        "INSERT INTO payment_vouchers(number, date, account_kind, account_id, voucher_type, "
        "trip_id, employee_id, vehicle_id, vehicle_expense, supplier_id, "
        "purchase_invoice_id, quantity, unit_amount, amount, description) "
        "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (number, row["date"], row["account_kind"], row["account_id"], row["voucher_type"],
         row["trip_id"], row["employee_id"], row["vehicle_id"], row["vehicle_expense"],
         row["supplier_id"], row["purchase_invoice_id"], row["quantity"],
         row["unit_amount"], row["amount"], row["description"]),
    )
    conn.commit()
    return int(cur.lastrowid)


def delete_payment(conn, voucher_id: int) -> None:
    v = conn.execute("SELECT date, voucher_type, source_expense_id "
                     "FROM payment_vouchers WHERE id=?", (voucher_id,)).fetchone()
    if not v:
        return
    if v["source_expense_id"] is not None:
        raise RuleError(
            "هذا السند متولّد تلقائياً من مصروف نقدي داخل فاتورة نقل.\n"
            "لا يُحذف منفرداً — راجعه من فاتورته.")
    if v["voucher_type"] == "advance":
        settled = _count(
            conn, "SELECT COUNT(*) FROM advance_settlements WHERE payment_voucher_id=?",
            (voucher_id,))
        if settled:
            raise RuleError(
                "لا يمكن حذف سلفة تم خصمها في مسير رواتب.\n"
                "احذف الرواتب المرتبطة بها أولاً."
            )
    ensure_movement_editable(conn, v["date"])
    conn.execute("DELETE FROM payment_vouchers WHERE id=?", (voucher_id,))
    conn.commit()


# ---------------------------------------------------------------------------
# السلف
# ---------------------------------------------------------------------------
def employee_advances(conn, employee_id: int, include_settled: bool = True) -> list[dict]:
    """سلف الموظف مع المسدد والمتبقي من كل سلفة."""
    out = []
    for r in conn.execute(
        "SELECT * FROM payment_vouchers WHERE voucher_type='advance' AND employee_id=? "
        "ORDER BY date, id", (employee_id,),
    ).fetchall():
        settled = calc._scalar(
            conn, "SELECT COALESCE(SUM(amount),0) FROM advance_settlements "
                  "WHERE payment_voucher_id=?", (r["id"],))
        rem = r["amount"] - settled
        if not include_settled and rem <= 0.009:
            continue
        out.append({**dict(r), "settled": settled, "remaining": rem})
    return out


# ---------------------------------------------------------------------------
# الرواتب
# ---------------------------------------------------------------------------
def list_payrolls(conn, d_from=None, d_to=None, employee_id=None) -> list[sqlite3.Row]:
    sql = ("SELECT p.*, e.name AS employee_name, e.emp_type, "
           "CASE WHEN p.account_kind='cashbox' THEN cb.name ELSE b.name END AS account_name "
           "FROM payrolls p JOIN employees e ON e.id=p.employee_id "
           "LEFT JOIN cashboxes cb ON cb.id=p.account_id AND p.account_kind='cashbox' "
           "LEFT JOIN banks b ON b.id=p.account_id AND p.account_kind='bank' WHERE 1=1")
    params: list = []
    if d_from:
        sql += " AND p.date >= ?"
        params.append(d_from)
    if d_to:
        sql += " AND p.date <= ?"
        params.append(d_to)
    if employee_id:
        sql += " AND p.employee_id=?"
        params.append(employee_id)
    sql += " ORDER BY p.date DESC, p.number DESC"
    return conn.execute(sql, params).fetchall()


def get_payroll(conn, payroll_id: int) -> dict:
    p = conn.execute("SELECT * FROM payrolls WHERE id=?", (payroll_id,)).fetchone()
    if not p:
        return {}
    d = dict(p)
    d["settlements"] = [dict(r) for r in conn.execute(
        "SELECT s.*, v.number AS voucher_number, v.date AS voucher_date "
        "FROM advance_settlements s JOIN payment_vouchers v ON v.id=s.payment_voucher_id "
        "WHERE s.payroll_id=?", (payroll_id,)).fetchall()]
    return d


def save_payroll(conn, data: dict, payroll_id: int | None = None) -> int:
    """إصدار/تعديل راتب مع تسويات السلف **وتسويات بنود الخصومات**.

    مطابق لـ savePayroll في نسخة الويب:
      الصافي = الأساسي + الإضافات − خصم السلف − خصم الخصومات − خصومات أخرى.
    """
    date = data.get("date", "")
    ensure_not_blank(date, "تاريخ الصرف")
    data["date"] = date
    employee_id = _positive_id(data.get("employee_id"), "الموظف/السائق")
    if get_employee(conn, employee_id) is None:
        raise RuleError("الموظف المحدد غير موجود.")
    if data.get("account_kind") not in ("cashbox", "bank") or not data.get("account_id"):
        raise RuleError("اختر جهة الصرف (خزينة أو بنك).")
    account_id = _positive_id(data.get("account_id"), "جهة الصرف")
    _ensure_account_exists(conn, data["account_kind"], account_id)
    base = _round_money(data.get("base_salary", 0))
    additions = _round_money(data.get("additions", 0))
    other_ded = _round_money(data.get("other_deductions", 0))
    ensure_positive(base, "الراتب الأساسي")
    p_month = _bounded(data.get("period_month"), "شهر الراتب", 1, 12, True)
    p_year = _bounded(data.get("period_year"), "سنة الراتب", 1900, 2200, True)
    if additions < 0 or other_ded < 0:
        raise RuleError("لا يمكن إدخال قيم سالبة في الإضافات أو الخصومات.")

    # ---- تسويات السلف (كلي/جزئي) ----
    settlements = []
    for item in (data.get("settlements") or []):
        if isinstance(item, (list, tuple)):
            settlements.append((_positive_id(item[0], "معرّف السلفة"),
                                _round_money(item[1])))
        else:
            settlements.append((_positive_id(item.get("payment_voucher_id"), "معرّف السلفة"),
                                _round_money(item.get("amount"))))
    total_settled = tax.round2(sum(a for _, a in settlements))
    adv_ded = data.get("advance_deduction")
    adv_ded = _round_money(total_settled if adv_ded is None else adv_ded)
    if adv_ded < 0:
        raise RuleError("لا يمكن إدخال قيم سالبة في الإضافات أو الخصومات.")
    if abs(total_settled - adv_ded) > 0.01:
        raise RuleError("مجموع خصومات السلف الموزعة لا يطابق قيمة الخصم من السلف.")

    # ---- تسويات بنود الخصومات (نفس المنطق على employee_deductions) ----
    deduction_settlements = []
    for item in (data.get("deduction_settlements") or []):
        if isinstance(item, (list, tuple)):
            deduction_settlements.append(
                (_positive_id(item[0], "معرّف بند الخصم"), _round_money(item[1])))
        else:
            deduction_settlements.append((
                _positive_id(item.get("employee_deduction_id"), "معرّف بند الخصم"),
                _round_money(item.get("amount"))))
    ded_settled = tax.round2(sum(a for _, a in deduction_settlements))
    ded_ded = data.get("deduction_deduction")
    ded_ded = _round_money(ded_settled if ded_ded is None else ded_ded)
    if abs(ded_settled - ded_ded) > 0.01:
        raise RuleError("مجموع خصومات الخصومات الموزعة لا يطابق إجمالي خصم الخصومات.")

    rem_map = {a["id"]: a["remaining"]
               for a in employee_advances(conn, employee_id)}
    ded_rem_map = {d["id"]: d["remaining"]
                   for d in calc.employee_deductions(conn, employee_id)}
    if payroll_id:  # عند التعديل: استثناء تسويات هذا الراتب نفسه من المتبقي
        for s in conn.execute(
            "SELECT payment_voucher_id, amount FROM advance_settlements WHERE payroll_id=?",
            (payroll_id,),
        ).fetchall():
            rem_map[s["payment_voucher_id"]] = tax.round2(
                rem_map.get(s["payment_voucher_id"], 0) + s["amount"])
        for s in conn.execute(
            "SELECT employee_deduction_id, amount FROM deduction_settlements "
            "WHERE payroll_id=?", (payroll_id,),
        ).fetchall():
            ded_rem_map[s["employee_deduction_id"]] = tax.round2(
                ded_rem_map.get(s["employee_deduction_id"], 0) + s["amount"])

    for vid, amount in settlements:
        if amount <= 0:
            continue
        if vid not in rem_map:
            raise RuleError("سلفة غير موجودة أو لا تخص هذا الموظف.")
        if amount > rem_map[vid] + 0.01:
            raise RuleError("قيمة الخصم من إحدى السلف أكبر من المتبقي منها.")
    for did, amount in deduction_settlements:
        if amount <= 0:
            continue
        if did not in ded_rem_map:
            raise RuleError("بند خصم غير موجود أو لا يخص هذا الموظف.")
        if amount > ded_rem_map[did] + 0.01:
            raise RuleError("قيمة الخصم من أحد بنود الخصومات أكبر من المتبقي منه.")

    net = tax.round2(base + additions - adv_ded - ded_ded - other_ded)
    if net < 0:
        raise RuleError("صافي الراتب سالب: راجع الإضافات والخصومات.")

    if payroll_id:
        old = conn.execute("SELECT date FROM payrolls WHERE id=?", (payroll_id,)).fetchone()
        if not old:
            raise RuleError("الراتب غير موجود.")
        ensure_movement_editable(conn, old["date"], date)
    else:
        ensure_date_in_open_year(conn, date)
    ensure_sufficient_funds(conn, data["account_kind"], account_id, net,
                            exclude_payroll_id=payroll_id)

    vals = (date, employee_id, p_year, p_month,
            data["account_kind"], account_id, base, additions,
            _txt(data.get("additions_note", ""), "بيان الإضافات"),
            adv_ded, other_ded, ded_ded, net, _txt(data.get("notes", ""), "الملاحظات"))
    if payroll_id:
        conn.execute(
            "UPDATE payrolls SET date=?, employee_id=?, period_year=?, period_month=?, "
            "account_kind=?, account_id=?, base_salary=?, additions=?, additions_note=?, "
            "advance_deduction=?, other_deductions=?, deduction_deduction=?, "
            "net_salary=?, notes=? WHERE id=?",
            (*vals, payroll_id),
        )
        conn.execute("DELETE FROM advance_settlements WHERE payroll_id=?", (payroll_id,))
        conn.execute("DELETE FROM deduction_settlements WHERE payroll_id=?", (payroll_id,))
    else:
        number = _next_number(conn, "payrolls")
        cur = conn.execute(
            "INSERT INTO payrolls(number, date, employee_id, period_year, period_month, "
            "account_kind, account_id, base_salary, additions, additions_note, "
            "advance_deduction, other_deductions, deduction_deduction, net_salary, notes) "
            "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (number, *vals),
        )
        payroll_id = int(cur.lastrowid)
    for vid, amount in settlements:
        if amount > 0:
            conn.execute(
                "INSERT INTO advance_settlements(payment_voucher_id, payroll_id, amount) "
                "VALUES(?,?,?)", (vid, payroll_id, amount),
            )
    for did, amount in deduction_settlements:
        if amount > 0:
            conn.execute(
                "INSERT INTO deduction_settlements(employee_deduction_id, payroll_id, "
                "amount) VALUES(?,?,?)", (did, payroll_id, amount),
            )
    conn.commit()
    return payroll_id


def delete_payroll(conn, payroll_id: int) -> None:
    p = conn.execute("SELECT date FROM payrolls WHERE id=?", (payroll_id,)).fetchone()
    if not p:
        return
    ensure_movement_editable(conn, p["date"])
    conn.execute("DELETE FROM payrolls WHERE id=?", (payroll_id,))  # التسويات تُحذف تلقائياً
    conn.commit()


# ---------------------------------------------------------------------------
# الموردون
# ---------------------------------------------------------------------------
SUPPLIER_TEXT_FIELDS = (
    ("name", "اسم المورّد"), ("name_en", "الاسم بالإنجليزية"), ("phone", "الهاتف"),
    ("email", "البريد الإلكتروني"), ("contact_person", "الشخص المسؤول"),
    ("address", "العنوان"), ("notes", "الملاحظات"),
)


def list_suppliers(conn) -> list[sqlite3.Row]:
    return conn.execute("SELECT * FROM suppliers ORDER BY code").fetchall()


def get_supplier(conn, supplier_id) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM suppliers WHERE id=?", (supplier_id,)).fetchone()


def save_supplier(conn, data: dict, supplier_id: int | None = None) -> int:
    """حفظ مورّد مع الحزمة الضريبية والعنوان الوطني (مطابق لنسخة الويب)."""
    ensure_not_blank(data.get("name", ""), "اسم المورّد")
    for key, label in SUPPLIER_TEXT_FIELDS:
        data[key] = _txt(data.get(key, ""), label)
    normalized = tax.normalize_tax_profile({c: data.get(c, "") for c in TAX_COLUMNS})
    errors = tax.validate_tax_profile(normalized)
    if errors:
        raise RuleError("\n".join(errors))
    data.update(normalized)
    payment_terms = _bounded(data.get("payment_terms", 0), "مدة السداد بالأيام",
                             0, 3650, True)

    if supplier_id:
        conn.execute(
            f"UPDATE suppliers SET name=?, name_en=?, phone=?, email=?, contact_person=?, "
            f"address=?, opening_balance=?, notes=?, payment_terms=?, "
            f"{_tax_columns_sql(data)} WHERE id=?",
            (data["name"], data["name_en"], data["phone"], data["email"],
             data["contact_person"], data["address"],
             _m(data.get("opening_balance", 0)), data["notes"], payment_terms,
             *_tax_values(data), supplier_id),
        )
        conn.commit()
        return supplier_id
    cur = conn.execute(
        f"INSERT INTO suppliers(name, name_en, phone, email, contact_person, address, "
        f"opening_balance, notes, payment_terms, {', '.join(TAX_COLUMNS)}) "
        f"VALUES(?,?,?,?,?,?,?,?,?{',?' * len(TAX_COLUMNS)})",
        (data["name"], data["name_en"], data["phone"], data["email"],
         data["contact_person"], data["address"], _m(data.get("opening_balance", 0)),
         data["notes"], payment_terms, *_tax_values(data)),
    )
    sid = int(cur.lastrowid)
    _stamp_code(conn, "suppliers", sid, "SUP")
    conn.commit()
    return sid


def delete_supplier(conn, supplier_id: int) -> None:
    n_inv = _count(conn, "SELECT COUNT(*) FROM purchase_invoices WHERE supplier_id=?",
                   (supplier_id,))
    n_pay = _count(conn, "SELECT COUNT(*) FROM payment_vouchers WHERE supplier_id=?",
                   (supplier_id,))
    if n_inv or n_pay:
        raise RuleError(
            "لا يمكن حذف المورّد لوجود حركات مرتبطة به "
            f"({n_inv} فاتورة مشتريات، {n_pay} سند دفع)."
        )
    conn.execute("DELETE FROM suppliers WHERE id=?", (supplier_id,))
    conn.commit()


# ---------------------------------------------------------------------------
# فواتير المشتريات (نقدية تُدفع فوراً / آجلة تُرحَّل على المورّد)
# ---------------------------------------------------------------------------
def list_purchase_invoices(conn, d_from=None, d_to=None, supplier_id=None) -> list[dict]:
    sql = ("SELECT p.*, s.name AS supplier_name, s.code AS supplier_code, "
           "v.plate_number FROM purchase_invoices p "
           "LEFT JOIN suppliers s ON s.id=p.supplier_id "
           "LEFT JOIN vehicles v ON v.id=p.vehicle_id WHERE 1=1")
    params: list = []
    if d_from:
        sql += " AND p.date >= ?"
        params.append(d_from)
    if d_to:
        sql += " AND p.date <= ?"
        params.append(d_to)
    if supplier_id:
        sql += " AND p.supplier_id=?"
        params.append(supplier_id)
    sql += " ORDER BY p.date DESC, p.number DESC"
    out = []
    for r in conn.execute(sql, params).fetchall():
        d = dict(r)
        d.update(calc.purchase_invoice_totals(conn, d["id"]))
        d.pop("items", None)  # البنود تُجلب عند فتح الفاتورة فقط
        d["account_name"] = (calc.account_name(conn, d["account_kind"], d["account_id"])
                             if d["account_kind"] else "—")
        out.append(d)
    return out


def get_purchase_invoice(conn, invoice_id: int) -> dict | None:
    row = conn.execute("SELECT * FROM purchase_invoices WHERE id=?",
                       (invoice_id,)).fetchone()
    if not row:
        return None
    d = dict(row)
    d["items"] = calc.purchase_items(conn, invoice_id)
    d.update(calc.purchase_totals(d["items"], bool(d["vat_included"])))
    return d


def save_purchase_invoice(conn, data: dict, invoice_id: int | None = None) -> int:
    """فاتورة مشتريات: رأس + بنود + (سند دفع تلقائي إن كانت نقدية).

    المصروف يُثبت في الأرباح والخسائر عند تاريخ الفاتورة سواء كانت نقدية أو آجلة.
    """
    from ..utils.fmt import PURCHASE_EXPENSE_CATEGORIES
    date = data.get("date", "")
    ensure_not_blank(date, "تاريخ فاتورة المشتريات")
    purchase_type = data.get("purchase_type")
    if purchase_type not in ("credit", "cash"):
        raise RuleError("اختر نوع فاتورة المشتريات (آجلة / نقدية).")
    category = data.get("expense_category") or "other"
    if category not in PURCHASE_EXPENSE_CATEGORIES:
        raise RuleError("اختر بند المصروف في الأرباح والخسائر.")
    supplier_id = (_positive_id(data.get("supplier_id"), "المورّد")
                   if purchase_type == "credit" else None)
    if supplier_id and get_supplier(conn, supplier_id) is None:
        raise RuleError("المورّد المحدد غير موجود.")
    vehicle_id = (_positive_id(data.get("vehicle_id"), "السيارة")
                  if data.get("vehicle_id") else None)
    if vehicle_id and get_vehicle(conn, vehicle_id) is None:
        raise RuleError("السيارة المحددة غير موجودة.")
    account_kind = account_id = None
    if purchase_type == "cash":
        if data.get("account_kind") not in ("cashbox", "bank"):
            raise RuleError("اختر الخزينة أو البنك للدفع المباشر.")
        account_kind = data["account_kind"]
        account_id = _positive_id(data.get("account_id"), "جهة الدفع")
        _ensure_account_exists(conn, account_kind, account_id)

    raw_items = data.get("items") or []
    if not raw_items:
        raise RuleError("أضف بنداً واحداً على الأقل للفاتورة.")
    if len(raw_items) > 1000:
        raise RuleError("عدد بنود فاتورة المشتريات أكبر من الحد المسموح.")
    vat_rate = _bounded(data.get("vat_rate", 15), "نسبة الضريبة", 0, 100)
    vat_included = bool(data.get("vat_included"))
    items = []
    for it in raw_items:
        name = _txt(it.get("item_name", ""), "اسم الصنف", 160)
        ensure_not_blank(name, "اسم الصنف")
        qty = _bounded(it.get("qty", 1), "الكمية", 0.001, 1_000_000)
        unit_price = _round_money(it.get("unit_price", 0))
        if unit_price < 0:
            raise RuleError("سعر الوحدة لا يمكن أن يكون سالباً.")
        items.append({
            "item_name": name,
            "unit": _txt(it.get("unit", ""), "الوحدة", 30),
            "qty": qty,
            "unit_price": unit_price,
            "vat_rate": _bounded(it.get("vat_rate", vat_rate), "نسبة ضريبة البند", 0, 100),
            "notes": _txt(it.get("notes", ""), "ملاحظات البند", 500),
        })
    totals = calc.purchase_totals(items, vat_included)
    if totals["total"] <= 0:
        raise RuleError("إجمالي فاتورة المشتريات يجب أن يكون أكبر من صفر.")

    if invoice_id:
        old = conn.execute("SELECT date FROM purchase_invoices WHERE id=?",
                           (invoice_id,)).fetchone()
        if not old:
            raise RuleError("فاتورة المشتريات غير موجودة.")
        ensure_movement_editable(conn, old["date"], date)
        old_voucher = conn.execute(
            "SELECT id FROM payment_vouchers WHERE purchase_invoice_id=?",
            (invoice_id,)).fetchone()
        if old_voucher:
            conn.execute("DELETE FROM payment_vouchers WHERE id=?",
                         (old_voucher["id"],))
    else:
        ensure_date_in_open_year(conn, date)

    if purchase_type == "cash":
        ensure_sufficient_funds(conn, account_kind, account_id, totals["total"],
                                exclude_payment_id=(
                                    conn.execute(
                                        "SELECT id FROM payment_vouchers "
                                        "WHERE purchase_invoice_id=?",
                                        (invoice_id,)).fetchone() or {"id": None})["id"]
                                if invoice_id else None)

    vals = (date, purchase_type, supplier_id,
            _txt(data.get("supplier_ref", ""), "مرجع المورّد", 80), category,
            vehicle_id, account_kind, account_id, vat_rate, int(vat_included),
            _txt(data.get("notes", ""), "ملاحظات فاتورة المشتريات", 1000))
    try:
        if invoice_id:
            conn.execute(
                "UPDATE purchase_invoices SET date=?, purchase_type=?, supplier_id=?, "
                "supplier_ref=?, expense_category=?, vehicle_id=?, account_kind=?, "
                "account_id=?, vat_rate=?, vat_included=?, notes=? WHERE id=?",
                (*vals, invoice_id),
            )
            conn.execute("DELETE FROM purchase_items WHERE invoice_id=?", (invoice_id,))
        else:
            number = _next_number(conn, "purchase_invoices")
            cur = conn.execute(
                "INSERT INTO purchase_invoices(number, date, purchase_type, supplier_id, "
                "supplier_ref, expense_category, vehicle_id, account_kind, account_id, "
                "vat_rate, vat_included, notes) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                (number, *vals),
            )
            invoice_id = int(cur.lastrowid)
        for it in items:
            conn.execute(
                "INSERT INTO purchase_items(invoice_id, item_name, unit, qty, unit_price, "
                "vat_rate, notes) VALUES(?,?,?,?,?,?,?)",
                (invoice_id, it["item_name"], it["unit"], it["qty"], it["unit_price"],
                 it["vat_rate"], it["notes"]),
            )
        # الشراء النقدي: سند دفع تلقائي (نوع purchase) لا يُحتسب مرتين في الأرباح
        if purchase_type == "cash":
            conn.execute(
                "INSERT INTO payment_vouchers(number, date, account_kind, account_id, "
                "voucher_type, purchase_invoice_id, quantity, unit_amount, amount, "
                "description) VALUES(?,?,?,?,?,?,?,?,?,?)",
                (_next_number(conn, "payment_vouchers"), date, account_kind, account_id,
                 "purchase", invoice_id, 1, totals["total"], totals["total"],
                 f"دفع فاتورة مشتريات #{invoice_id} نقداً"),
            )
    except Exception:
        conn.rollback()
        raise
    conn.commit()
    return invoice_id


def delete_purchase_invoice(conn, invoice_id: int) -> None:
    row = conn.execute("SELECT date FROM purchase_invoices WHERE id=?",
                       (invoice_id,)).fetchone()
    if not row:
        return
    ensure_movement_editable(conn, row["date"])
    conn.execute("DELETE FROM payment_vouchers WHERE purchase_invoice_id=?",
                 (invoice_id,))
    conn.execute("DELETE FROM purchase_invoices WHERE id=?", (invoice_id,))
    conn.commit()


# ---------------------------------------------------------------------------
# الإشعارات الدائنة والمدينة (بديل تعديل الفاتورة بعد إصدارها)
# ---------------------------------------------------------------------------
def list_creditable_invoice_trips(conn, invoice_id: int) -> list[dict]:
    """نقلات الفاتورة وقيمة كل نقلة وضريبتها وحالة إصدار مرتجع سابق لها."""
    inv = conn.execute("SELECT id, vat_rate FROM invoices WHERE id=?",
                       (invoice_id,)).fetchone()
    if not inv:
        raise RuleError("الفاتورة المرتبطة غير موجودة.")
    credited = {r["trip_id"] for r in conn.execute(
        "SELECT trip_id FROM credit_note_trips")}
    vat_rate = float(inv["vat_rate"] or 0)
    out = []
    for trip in conn.execute(
        "SELECT id, from_loc, to_loc, qty, unit_price, price FROM invoice_trips "
        "WHERE invoice_id=? ORDER BY id", (invoice_id,),
    ):
        amount = tax.round2(trip["price"])
        vat_amount = tax.round2((amount * vat_rate) / 100.0)
        out.append({
            "id": trip["id"], "from_loc": trip["from_loc"] or "",
            "to_loc": trip["to_loc"] or "", "qty": float(trip["qty"] or 1),
            "unit_price": float(trip["unit_price"] or amount), "amount": amount,
            "vat_amount": vat_amount, "total": tax.round2(amount + vat_amount),
            "already_credited": trip["id"] in credited,
        })
    return out


def save_credit_debit_note(conn, data: dict) -> int:
    """إصدار إشعار دائن (مرتجع نقلات أو مبلغ) أو إشعار مدين."""
    note_type = data.get("note_type")
    if note_type not in ("credit", "debit"):
        raise RuleError("نوع الإشعار غير صالح.")
    invoice_id = _positive_id(data.get("invoice_id"), "الفاتورة")
    customer_id = _positive_id(data.get("customer_id"), "العميل")
    reason = _txt(data.get("reason", ""), "سبب الإشعار")
    ensure_not_blank(reason, "سبب الإشعار إلزامي للمراجعة المحاسبية")
    note_date = data.get("date", "")
    ensure_not_blank(note_date, "تاريخ الإشعار")
    inv = conn.execute("SELECT customer_id, date FROM invoices WHERE id=?",
                       (invoice_id,)).fetchone()
    if not inv:
        raise RuleError("الفاتورة المرتبطة غير موجودة.")
    if int(inv["customer_id"]) != customer_id:
        raise RuleError("العميل المحدد لا يطابق عميل الفاتورة.")
    if note_date < str(inv["date"]):
        raise RuleError("تاريخ الإشعار لا يجوز أن يسبق تاريخ الفاتورة.")
    ensure_date_in_open_year(conn, note_date)

    vat_rate = float(conn.execute(
        "SELECT vat_rate FROM invoices WHERE id=?", (invoice_id,)).fetchone()["vat_rate"] or 0)

    # مرتجع نقلة: المبلغ والضريبة يُقرآن من أسعار النقلات لا من الواجهة
    trip_ids = data.get("trip_ids")
    if note_type == "credit" and trip_ids is not None:
        if not isinstance(trip_ids, list) or not trip_ids:
            raise RuleError("اختر نقلة واحدة على الأقل لإصدار الإشعار الدائن.")
        trip_ids = [_positive_id(t, "النقلة") for t in trip_ids]
        if len(set(trip_ids)) != len(trip_ids):
            raise RuleError("قائمة النقلات المختارة تحتوي على تكرار.")
        amount = 0.0
        for tid in trip_ids:
            row = conn.execute(
                "SELECT t.id, t.invoice_id, t.price FROM invoice_trips t "
                "WHERE t.id=?", (tid,)).fetchone()
            if not row:
                raise RuleError("النقلة المحددة غير موجودة.")
            if int(row["invoice_id"]) != invoice_id:
                raise RuleError("إحدى النقلات المختارة لا تخص هذه الفاتورة.")
            if conn.execute("SELECT id FROM credit_note_trips WHERE trip_id=?",
                            (tid,)).fetchone():
                raise RuleError("سبق إصدار إشعار دائن لإحدى النقلات المختارة.")
            amount += float(row["price"] or 0)
        amount = tax.round2(amount)
        ensure_positive(amount, "مبلغ الإشعار")
    else:
        amount = _round_money(data.get("amount", 0))
        ensure_positive(amount, "مبلغ الإشعار")
        vat_rate = _bounded(data.get("vat_rate", vat_rate), "نسبة الضريبة", 0, 100)

    number = _next_number(conn, "credit_debit_notes")
    cur = conn.execute(
        "INSERT INTO credit_debit_notes(number, note_type, invoice_id, customer_id, "
        "date, amount, vat_rate, reason) VALUES(?,?,?,?,?,?,?,?)",
        (number, note_type, invoice_id, customer_id, note_date, amount, vat_rate, reason),
    )
    note_id = int(cur.lastrowid)
    if note_type == "credit" and trip_ids:
        for tid in trip_ids:
            conn.execute(
                "INSERT INTO credit_note_trips(note_id, trip_id) VALUES(?,?)",
                (note_id, tid),
            )
    conn.commit()
    return note_id


def list_credit_debit_notes(conn, d_from=None, d_to=None,
                            note_type=None) -> list[dict]:
    sql = ("SELECT n.*, i.number AS invoice_number, c.name AS customer_name, "
           "c.code AS customer_code FROM credit_debit_notes n "
           "JOIN invoices i ON i.id=n.invoice_id "
           "JOIN customers c ON c.id=n.customer_id WHERE 1=1")
    params: list = []
    if d_from:
        sql += " AND n.date >= ?"
        params.append(d_from)
    if d_to:
        sql += " AND n.date <= ?"
        params.append(d_to)
    if note_type:
        sql += " AND n.note_type=?"
        params.append(note_type)
    sql += " ORDER BY n.date DESC, n.number DESC"
    out = []
    for r in conn.execute(sql, params).fetchall():
        d = dict(r)
        d["total"] = calc.note_total(d["amount"], d["vat_rate"])
        d["trip_labels"] = [
            f"{t['from_loc'] or '—'} ← {t['to_loc'] or '—'}"
            for t in conn.execute(
                "SELECT t.from_loc, t.to_loc FROM credit_note_trips l "
                "JOIN invoice_trips t ON t.id=l.trip_id WHERE l.note_id=?", (d["id"],))]
        out.append(d)
    return out


def list_credit_debit_notes_for_invoice(conn, invoice_id: int) -> list[dict]:
    return [n for n in list_credit_debit_notes(conn)
            if n["invoice_id"] == invoice_id]


def get_credit_debit_note(conn, note_id: int) -> dict | None:
    row = conn.execute("SELECT * FROM credit_debit_notes WHERE id=?",
                       (note_id,)).fetchone()
    if not row:
        return None
    d = dict(row)
    d["total"] = calc.note_total(d["amount"], d["vat_rate"])
    d["trip_ids"] = [r["trip_id"] for r in conn.execute(
        "SELECT trip_id FROM credit_note_trips WHERE note_id=?", (note_id,))]
    return d


def delete_credit_debit_note(conn, note_id: int) -> None:
    row = conn.execute("SELECT date FROM credit_debit_notes WHERE id=?",
                       (note_id,)).fetchone()
    if not row:
        return
    ensure_movement_editable(conn, row["date"])
    conn.execute("DELETE FROM credit_debit_notes WHERE id=?", (note_id,))
    conn.commit()


# ---------------------------------------------------------------------------
# بنود الخصومات المُتتبَّعة على الموظف/السائق
# ---------------------------------------------------------------------------
def list_deductions(conn, d_from=None, d_to=None, employee_id=None) -> list[dict]:
    sql = ("SELECT d.*, e.name AS employee_name, e.code AS employee_code "
           "FROM employee_deductions d JOIN employees e ON e.id=d.employee_id WHERE 1=1")
    params: list = []
    if d_from:
        sql += " AND d.date >= ?"
        params.append(d_from)
    if d_to:
        sql += " AND d.date <= ?"
        params.append(d_to)
    if employee_id:
        sql += " AND d.employee_id=?"
        params.append(employee_id)
    sql += " ORDER BY d.date DESC, d.number DESC"
    out = []
    for r in conn.execute(sql, params).fetchall():
        d = dict(r)
        settled = tax.round2(_scalar(
            conn, "SELECT COALESCE(SUM(amount),0) FROM deduction_settlements "
                  "WHERE employee_deduction_id=?", (d["id"],)))
        d["settled"] = settled
        d["remaining"] = tax.round2(float(d["amount"] or 0) - settled)
        d["status"] = ("closed" if d["remaining"] <= 0.009
                       else ("partial" if settled > 0 else "open"))
        out.append(d)
    return out


def get_deduction(conn, deduction_id: int) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM employee_deductions WHERE id=?",
                        (deduction_id,)).fetchone()


def save_deduction(conn, data: dict, deduction_id: int | None = None) -> int:
    date = data.get("date", "")
    ensure_not_blank(date, "تاريخ بند الخصم")
    employee_id = _positive_id(data.get("employee_id"), "الموظف/السائق")
    if get_employee(conn, employee_id) is None:
        raise RuleError("الموظف المحدد غير موجود.")
    amount = _round_money(data.get("amount", 0))
    ensure_positive(amount, "مبلغ الخصم")
    reason = _txt(data.get("reason", ""), "سبب الخصم")
    ensure_not_blank(reason, "سبب الخصم")
    notes = _txt(data.get("notes", ""), "الملاحظات")

    if deduction_id:
        old = conn.execute("SELECT date FROM employee_deductions WHERE id=?",
                           (deduction_id,)).fetchone()
        if not old:
            raise RuleError("بند الخصم غير موجود.")
        settled = tax.round2(_scalar(
            conn, "SELECT COALESCE(SUM(amount),0) FROM deduction_settlements "
                  "WHERE employee_deduction_id=?", (deduction_id,)))
        if amount < settled - 0.01:
            raise RuleError(
                "لا يمكن تخفيض بند الخصم أقل مما خُصم منه فعلياً في المسيرات "
                f"({settled}).")
        ensure_movement_editable(conn, old["date"], date)
        conn.execute(
            "UPDATE employee_deductions SET date=?, employee_id=?, amount=?, reason=?, "
            "notes=? WHERE id=?",
            (date, employee_id, amount, reason, notes, deduction_id),
        )
        conn.commit()
        return deduction_id

    ensure_date_in_open_year(conn, date)
    number = _next_number(conn, "employee_deductions")
    cur = conn.execute(
        "INSERT INTO employee_deductions(number, date, employee_id, amount, reason, notes) "
        "VALUES(?,?,?,?,?,?)",
        (number, date, employee_id, amount, reason, notes),
    )
    conn.commit()
    return int(cur.lastrowid)


def delete_deduction(conn, deduction_id: int) -> None:
    row = conn.execute("SELECT date FROM employee_deductions WHERE id=?",
                       (deduction_id,)).fetchone()
    if not row:
        return
    settled = _count(conn, "SELECT COUNT(*) FROM deduction_settlements "
                           "WHERE employee_deduction_id=?", (deduction_id,))
    if settled:
        raise RuleError(
            "لا يمكن حذف بند خصم خُصم جزء/كله في مسير رواتب.\n"
            "احذف المسيرات المرتبطة به أولاً."
        )
    ensure_movement_editable(conn, row["date"])
    conn.execute("DELETE FROM employee_deductions WHERE id=?", (deduction_id,))
    conn.commit()


# ---------------------------------------------------------------------------
# ترحيل السنة المالية
# ---------------------------------------------------------------------------
def year_opening_balances(conn, year_id: int) -> list[dict]:
    return [dict(r) for r in conn.execute(
        "SELECT * FROM year_opening_balances WHERE year_id=? ORDER BY entity_type, "
        "entity_id", (year_id,))]


def rollover_year(conn, year_id: int, next_year: int, date_from: str,
                  date_to: str) -> int:
    """إقفال سنة وترحيلها: سنة جديدة مفتوحة + أرصدة افتتاحية مستقلة.

    مطابق لـ create_next_financial_year في نسخة الويب:
      • السنة السابقة يجب أن تكون مغلقة.
      • الأرصدة تُحفظ في year_opening_balances دون تعديل opening_balance الأصلي
        ودون تكرار الحركات.
    """
    clean_next = _bounded(next_year, "السنة التالية", 1900, 2200, True)
    ensure_not_blank(date_from, "تاريخ بداية السنة التالية")
    ensure_not_blank(date_to, "تاريخ نهاية السنة التالية")
    if date_from >= date_to or str(date_from)[:4] != str(clean_next):
        raise RuleError("نطاق السنة المالية التالية غير صالح.")
    y = get_year(conn, year_id)
    if not y:
        raise RuleError("السنة المالية غير موجودة.")
    if y["status"] != "closed":
        raise RuleError("يجب إغلاق السنة السابقة أولاً.")
    if conn.execute("SELECT id FROM financial_years WHERE year=?",
                    (clean_next,)).fetchone():
        raise RuleError("السنة الجديدة موجودة مسبقاً.")

    cur = conn.execute(
        "INSERT INTO financial_years(year, date_from, date_to, status, notes) "
        "VALUES(?,?,?,'open','تم الترحيل من السنة السابقة')",
        (clean_next, date_from, date_to),
    )
    new_id = int(cur.lastrowid)
    pairs = (
        ("customer", "SELECT id FROM customers ORDER BY code",
         lambda rid: calc.customer_balance(conn, rid)),
        ("cashbox", "SELECT id FROM cashboxes ORDER BY code",
         lambda rid: calc.account_balance(conn, "cashbox", rid)),
        ("bank", "SELECT id FROM banks ORDER BY code",
         lambda rid: calc.account_balance(conn, "bank", rid)),
        ("supplier", "SELECT id FROM suppliers ORDER BY code",
         lambda rid: calc.supplier_balance(conn, rid)),
    )
    for entity_type, sql, balance_fn in pairs:
        for row in conn.execute(sql).fetchall():
            conn.execute(
                "INSERT INTO year_opening_balances(year_id, entity_type, entity_id, "
                "balance) VALUES(?,?,?,?)",
                (new_id, entity_type, row["id"], tax.round2(balance_fn(row["id"]))),
            )
    conn.commit()
    return new_id


# ---------------------------------------------------------------------------
# المرفقات (تُخزَّن داخل مجلد البيانات وتُحفظ مساراتها في الفاتورة)
# ---------------------------------------------------------------------------
def store_attachment(src: str) -> str:
    """نسخ ملف مرفق إلى مجلد المرفقات (باسم فريد) وإرجاع المسار النسبي.

    الاسم المأخوذ هو اسم الملف وحده بلا أي جزء مساري، فلا يمكن للمرفق
    أن يُكتب خارج مجلد المرفقات.
    """
    src_path = Path(src)
    name = src_path.name
    if not name or name in (".", ".."):
        raise RuleError("اسم المرفق غير صالح.")
    if not src_path.is_file():
        raise RuleError("المرفق المحدد ليس ملفاً موجوداً.")
    if src_path.stat().st_size > 25 * 1024 * 1024:
        raise RuleError("حجم المرفق أكبر من 25 ميجابايت.")
    folder = db.attachments_dir()
    folder.mkdir(parents=True, exist_ok=True)
    dest = folder / name
    i = 1
    while dest.exists():
        dest = folder / f"{src_path.stem}_{i}{src_path.suffix}"
        i += 1
    shutil.copy(str(src_path), str(dest))
    rel = str(dest.relative_to(db.data_dir()))
    # تأكيد أخير أن الوجهة لم تخرج من مجلد المرفقات
    if not dest.resolve().is_relative_to(folder.resolve()):
        raise RuleError("مسار المرفق غير صالح.")
    return rel
