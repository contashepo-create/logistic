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

from . import db, calc
from .rules import (
    RuleError, ensure_date_in_open_year, ensure_movement_editable,
    ensure_positive, ensure_not_blank,
)

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


# ---------------------------------------------------------------------------
# السنوات المالية
# ---------------------------------------------------------------------------
def list_years(conn) -> list[sqlite3.Row]:
    return conn.execute("SELECT * FROM financial_years ORDER BY year DESC").fetchall()


def get_year(conn, year_id: int) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM financial_years WHERE id=?", (year_id,)).fetchone()


def save_year(conn, data: dict, year_id: int | None = None) -> int:
    year = int(data["year"])
    date_from, date_to = data["date_from"], data["date_to"]
    ensure_not_blank(str(year), "السنة")
    ensure_not_blank(date_from, "تاريخ البداية")
    ensure_not_blank(date_to, "تاريخ النهاية")
    if date_from >= date_to:
        raise RuleError("تاريخ بداية السنة يجب أن يكون قبل تاريخ نهايتها.")
    dup = conn.execute(
        "SELECT id FROM financial_years WHERE year=? AND id != ?",
        (year, year_id or -1),
    ).fetchone()
    if dup:
        raise RuleError(f"السنة المالية {year} مسجلة مسبقاً.")
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


def save_customer(conn, data: dict, customer_id: int | None = None) -> int:
    ensure_not_blank(data.get("name", ""), "اسم العميل")
    if customer_id:
        conn.execute(
            "UPDATE customers SET name=?, address=?, phone=?, opening_balance=?, notes=? "
            "WHERE id=?",
            (data["name"], data.get("address", ""), data.get("phone", ""),
             float(data.get("opening_balance", 0) or 0), data.get("notes", ""), customer_id),
        )
        conn.commit()
        return customer_id
    cur = conn.execute(
        "INSERT INTO customers(name, address, phone, opening_balance, notes) "
        "VALUES(?,?,?,?,?)",
        (data["name"], data.get("address", ""), data.get("phone", ""),
         float(data.get("opening_balance", 0) or 0), data.get("notes", "")),
    )
    cid = int(cur.lastrowid)
    _stamp_code(conn, "customers", cid, "CUST")
    conn.commit()
    return cid


def delete_customer(conn, customer_id: int) -> None:
    n_inv = _count(conn, "SELECT COUNT(*) FROM invoices WHERE customer_id=?", (customer_id,))
    n_rec = _count(
        conn, "SELECT COUNT(*) FROM receipt_vouchers WHERE customer_id=?", (customer_id,))
    if n_inv or n_rec:
        raise RuleError(
            "لا يمكن حذف العميل لوجود حركات مرتبطة به "
            f"({n_inv} فاتورة، {n_rec} سند قبض)."
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
    if data.get("emp_type") not in ("driver", "admin"):
        raise RuleError("اختر نوع الموظف (سائق / إداري).")
    vals = (data["name"], data.get("nationality", ""), data.get("phone", ""),
            data["emp_type"], data.get("notes", ""))
    if employee_id:
        conn.execute(
            "UPDATE employees SET name=?, nationality=?, phone=?, emp_type=?, notes=? "
            "WHERE id=?", (*vals, employee_id),
        )
        conn.commit()
        return employee_id
    cur = conn.execute(
        "INSERT INTO employees(name, nationality, phone, emp_type, notes) "
        "VALUES(?,?,?,?,?)", vals,
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
    vals = (data["plate_number"], data.get("vehicle_type", ""),
            data.get("default_driver_id") or None)
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
    if kind == "bank":
        if account_id:
            conn.execute(
                "UPDATE banks SET name=?, created_date=?, account_number=?, iban=?, "
                "opening_balance=?, notes=? WHERE id=?",
                (data["name"], data["created_date"], data.get("account_number", ""),
                 data.get("iban", ""), float(data.get("opening_balance", 0) or 0),
                 data.get("notes", ""), account_id),
            )
            conn.commit()
            return account_id
        cur = conn.execute(
            "INSERT INTO banks(name, created_date, account_number, iban, opening_balance, "
            "notes) VALUES(?,?,?,?,?,?)",
            (data["name"], data["created_date"], data.get("account_number", ""),
             data.get("iban", ""), float(data.get("opening_balance", 0) or 0),
             data.get("notes", "")),
        )
    else:
        if account_id:
            conn.execute(
                "UPDATE cashboxes SET name=?, created_date=?, opening_balance=?, notes=? "
                "WHERE id=?",
                (data["name"], data["created_date"],
                 float(data.get("opening_balance", 0) or 0), data.get("notes", ""),
                 account_id),
            )
            conn.commit()
            return account_id
        cur = conn.execute(
            "INSERT INTO cashboxes(name, created_date, opening_balance, notes) "
            "VALUES(?,?,?,?)",
            (data["name"], data["created_date"],
             float(data.get("opening_balance", 0) or 0), data.get("notes", "")),
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
    """حفظ الفاتورة مع نقلاتها ومصروفاتها (استبدال كامل للتفاصيل عند التعديل)."""
    date = data["date"]
    ensure_not_blank(date, "تاريخ الفاتورة")
    if not data.get("customer_id"):
        raise RuleError("اختر العميل.")
    trips = data.get("trips") or []
    if not trips:
        raise RuleError("أضف نقلة واحدة على الأقل للفاتورة.")
    for t in trips:
        if float(t.get("price", 0) or 0) <= 0:
            raise RuleError("سعر النقلة يجب أن يكون أكبر من صفر.")
        for e in t.get("expenses", []):
            if float(e.get("amount", 0) or 0) <= 0:
                raise RuleError("مبلغ مصروف النقلة يجب أن يكون أكبر من صفر.")

    if invoice_id:
        old = conn.execute("SELECT date FROM invoices WHERE id=?", (invoice_id,)).fetchone()
        if not old:
            raise RuleError("الفاتورة غير موجودة.")
        ensure_movement_editable(conn, old["date"], date)
        conn.execute(
            "UPDATE invoices SET date=?, customer_id=?, notes=?, attachments=? WHERE id=?",
            (date, data["customer_id"], data.get("notes", ""),
             json.dumps(data.get("attachments", []), ensure_ascii=False), invoice_id),
        )
    else:
        ensure_date_in_open_year(conn, date)
        number = _next_number(conn, "invoices")
        cur = conn.execute(
            "INSERT INTO invoices(number, date, customer_id, notes, attachments) "
            "VALUES(?,?,?,?,?)",
            (number, date, data["customer_id"], data.get("notes", ""),
             json.dumps(data.get("attachments", []), ensure_ascii=False)),
        )
        invoice_id = int(cur.lastrowid)

    # استبدال التفاصيل: حذف النقلات المحذوفة (بعد التأكد من عدم ارتباطها بسندات دفع)
    kept_trip_ids = {int(t["id"]) for t in trips if t.get("id")}
    for row in conn.execute(
        "SELECT id FROM invoice_trips WHERE invoice_id=?", (invoice_id,)
    ).fetchall():
        if row["id"] not in kept_trip_ids:
            linked = _count(
                conn, "SELECT COUNT(*) FROM payment_vouchers WHERE voucher_type='trip' "
                      "AND trip_id=?", (row["id"],))
            if linked:
                raise RuleError(
                    "لا يمكن حذف نقلة مرتبطة بسندات دفع (مصروف يخص الرحلة).\n"
                    "احذف السندات المرتبطة أولاً."
                )
            conn.execute("DELETE FROM invoice_trips WHERE id=?", (row["id"],))

    for t in trips:
        if t.get("id"):
            conn.execute(
                "UPDATE invoice_trips SET vehicle_id=?, driver_id=?, from_loc=?, to_loc=?, "
                "price=?, notes=? WHERE id=?",
                (t.get("vehicle_id") or None, t.get("driver_id") or None,
                 t.get("from_loc", ""), t.get("to_loc", ""),
                 float(t.get("price", 0) or 0), t.get("notes", ""), t["id"]),
            )
            trip_id = int(t["id"])
            conn.execute("DELETE FROM trip_expenses WHERE trip_id=?", (trip_id,))
        else:
            cur = conn.execute(
                "INSERT INTO invoice_trips(invoice_id, vehicle_id, driver_id, from_loc, "
                "to_loc, price, notes) VALUES(?,?,?,?,?,?,?)",
                (invoice_id, t.get("vehicle_id") or None, t.get("driver_id") or None,
                 t.get("from_loc", ""), t.get("to_loc", ""),
                 float(t.get("price", 0) or 0), t.get("notes", "")),
            )
            trip_id = int(cur.lastrowid)
        for e in t.get("expenses", []):
            if e.get("expense_type") not in ("trip", "fuel", "card", "other"):
                raise RuleError("نوع مصروف النقلة غير صالح.")
            conn.execute(
                "INSERT INTO trip_expenses(trip_id, expense_type, amount, notes) "
                "VALUES(?,?,?,?)",
                (trip_id, e["expense_type"], float(e.get("amount", 0) or 0),
                 e.get("notes", "")),
            )
    conn.commit()
    return invoice_id


def delete_invoice(conn, invoice_id: int) -> None:
    inv = conn.execute("SELECT * FROM invoices WHERE id=?", (invoice_id,)).fetchone()
    if not inv:
        return
    ensure_movement_editable(conn, inv["date"])
    linked = _count(
        conn,
        "SELECT COUNT(*) FROM payment_vouchers p JOIN invoice_trips t ON t.id=p.trip_id "
        "WHERE t.invoice_id=? AND p.voucher_type='trip'",
        (invoice_id,),
    )
    if linked:
        raise RuleError(
            "لا يمكن حذف الفاتورة: توجد سندات دفع (مصروفات رحلات) مرتبطة بنقلاتها.\n"
            "احذف السندات المرتبطة أولاً."
        )
    conn.execute("DELETE FROM invoices WHERE id=?", (invoice_id,))
    conn.commit()


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
    amount = float(data.get("amount", 0) or 0)
    ensure_not_blank(date, "تاريخ السند")
    ensure_positive(amount, "المبلغ")
    if data.get("voucher_type") not in ("customer", "other"):
        raise RuleError("اختر نوع السند.")
    if data["voucher_type"] == "customer" and not data.get("customer_id"):
        raise RuleError("اختر العميل المحصَّل منه.")
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


def _validate_payment(conn, data: dict) -> None:
    vt = data.get("voucher_type")
    if vt not in ("trip", "advance", "vehicle", "general"):
        raise RuleError("اختر نوع السند.")
    amount = float(data.get("amount", 0) or 0)
    ensure_positive(amount)
    if data.get("account_kind") not in ("cashbox", "bank") or not data.get("account_id"):
        raise RuleError("اختر جهة الصرف (خزينة أو بنك).")
    _ensure_account_exists(conn, data["account_kind"], data["account_id"])
    if vt == "trip" and not data.get("trip_id"):
        raise RuleError("اختر الرحلة (النقلة) التي يخصها المصروف.")
    if vt == "advance" and not data.get("employee_id"):
        raise RuleError("اختر الموظف/السائق للسلفة.")
    if vt == "vehicle" and not data.get("vehicle_id"):
        raise RuleError("اختر السيارة لمصروف الصيانة.")
    if data.get("trip_id"):
        t = conn.execute("SELECT id FROM invoice_trips WHERE id=?",
                         (data["trip_id"],)).fetchone()
        if not t:
            raise RuleError("الرحلة المحددة غير موجودة.")
    if vt == "advance" and get_employee(conn, data["employee_id"]) is None:
        raise RuleError("الموظف المحدد غير موجود.")
    if vt == "vehicle" and get_vehicle(conn, data["vehicle_id"]) is None:
        raise RuleError("السيارة المحددة غير موجودة.")


def save_payment(conn, data: dict, voucher_id: int | None = None) -> int:
    date = data["date"]
    ensure_not_blank(date, "تاريخ السند")
    _validate_payment(conn, data)

    if voucher_id:
        old = conn.execute("SELECT date, voucher_type, employee_id, amount "
                           "FROM payment_vouchers WHERE id=?", (voucher_id,)).fetchone()
        if not old:
            raise RuleError("السند غير موجود.")
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
        conn.execute(
            "UPDATE payment_vouchers SET date=?, account_kind=?, account_id=?, "
            "voucher_type=?, trip_id=?, employee_id=?, vehicle_id=?, vehicle_expense=?, "
            "amount=?, description=? WHERE id=?",
            (date, data["account_kind"], data["account_id"], data["voucher_type"],
             data.get("trip_id") if data["voucher_type"] == "trip" else None,
             data.get("employee_id") if data["voucher_type"] == "advance" else None,
             data.get("vehicle_id") if data["voucher_type"] == "vehicle" else None,
             data.get("vehicle_expense", "") if data["voucher_type"] == "vehicle" else "",
             float(data.get("amount", 0) or 0), data.get("description", ""), voucher_id),
        )
        conn.commit()
        return voucher_id

    ensure_date_in_open_year(conn, date)
    number = _next_number(conn, "payment_vouchers")
    cur = conn.execute(
        "INSERT INTO payment_vouchers(number, date, account_kind, account_id, voucher_type, "
        "trip_id, employee_id, vehicle_id, vehicle_expense, amount, description) "
        "VALUES(?,?,?,?,?,?,?,?,?,?,?)",
        (number, date, data["account_kind"], data["account_id"], data["voucher_type"],
         data.get("trip_id") if data["voucher_type"] == "trip" else None,
         data.get("employee_id") if data["voucher_type"] == "advance" else None,
         data.get("vehicle_id") if data["voucher_type"] == "vehicle" else None,
         data.get("vehicle_expense", "") if data["voucher_type"] == "vehicle" else "",
         float(data.get("amount", 0) or 0), data.get("description", "")),
    )
    conn.commit()
    return int(cur.lastrowid)


def delete_payment(conn, voucher_id: int) -> None:
    v = conn.execute("SELECT date, voucher_type FROM payment_vouchers WHERE id=?",
                     (voucher_id,)).fetchone()
    if not v:
        return
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
    """إصدار/تعديل راتب مع تسويات السلف (استبدال كامل للتسويات)."""
    date = data["date"]
    ensure_not_blank(date, "تاريخ الصرف")
    if not data.get("employee_id"):
        raise RuleError("اختر الموظف/السائق.")
    if get_employee(conn, data["employee_id"]) is None:
        raise RuleError("الموظف المحدد غير موجود.")
    if data.get("account_kind") not in ("cashbox", "bank") or not data.get("account_id"):
        raise RuleError("اختر جهة الصرف (خزينة أو بنك).")
    _ensure_account_exists(conn, data["account_kind"], data["account_id"])
    base = float(data.get("base_salary", 0) or 0)
    additions = float(data.get("additions", 0) or 0)
    other_ded = float(data.get("other_deductions", 0) or 0)
    ensure_positive(base, "الراتب الأساسي")
    if additions < 0 or other_ded < 0:
        raise RuleError("لا يمكن إدخال قيم سالبة في الإضافات أو الخصومات.")

    settlements = data.get("settlements") or []  # [(payment_voucher_id, amount)]
    total_settled = sum(a for _, a in settlements)
    adv_ded = data.get("advance_deduction")
    adv_ded = float(total_settled if adv_ded is None else (adv_ded or 0))
    if adv_ded < 0:
        raise RuleError("لا يمكن إدخال قيم سالبة في الإضافات أو الخصومات.")
    if abs(total_settled - adv_ded) > 0.01:
        raise RuleError("مجموع خصومات السلف الموزعة لا يطابق قيمة الخصم من السلف.")

    # التحقق من عدم تجاوز المتبقي من كل سلفة
    rem_map = {a["id"]: a["remaining"]
               for a in employee_advances(conn, data["employee_id"])}
    if payroll_id:  # عند التعديل: استثناء تسويات هذا الراتب نفسه من المتبقي
        for s in conn.execute(
            "SELECT payment_voucher_id, amount FROM advance_settlements WHERE payroll_id=?",
            (payroll_id,),
        ).fetchall():
            rem_map[s["payment_voucher_id"]] = (
                rem_map.get(s["payment_voucher_id"], 0) + s["amount"])

    for vid, amount in settlements:
        if amount <= 0:
            continue
        if vid not in rem_map:
            raise RuleError("سلفة غير موجودة أو لا تخص هذا الموظف.")
        if amount > rem_map[vid] + 0.01:
            raise RuleError("قيمة الخصم من إحدى السلف أكبر من المتبقي منها.")

    net = base + additions - adv_ded - other_ded
    if net < 0:
        raise RuleError("صافي الراتب سالب: راجع الإضافات والخصومات.")

    vals = (date, data["employee_id"], int(data["period_year"]), int(data["period_month"]),
            data["account_kind"], data["account_id"], base, additions,
            data.get("additions_note", ""), adv_ded, other_ded, net,
            data.get("notes", ""))
    if payroll_id:
        old = conn.execute("SELECT date FROM payrolls WHERE id=?", (payroll_id,)).fetchone()
        if not old:
            raise RuleError("الراتب غير موجود.")
        ensure_movement_editable(conn, old["date"], date)
        conn.execute(
            "UPDATE payrolls SET date=?, employee_id=?, period_year=?, period_month=?, "
            "account_kind=?, account_id=?, base_salary=?, additions=?, additions_note=?, "
            "advance_deduction=?, other_deductions=?, net_salary=?, notes=? WHERE id=?",
            (*vals, payroll_id),
        )
        conn.execute("DELETE FROM advance_settlements WHERE payroll_id=?", (payroll_id,))
    else:
        ensure_date_in_open_year(conn, date)
        number = _next_number(conn, "payrolls")
        cur = conn.execute(
            "INSERT INTO payrolls(number, date, employee_id, period_year, period_month, "
            "account_kind, account_id, base_salary, additions, additions_note, "
            "advance_deduction, other_deductions, net_salary, notes) "
            "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (number, *vals),
        )
        payroll_id = int(cur.lastrowid)
    for vid, amount in settlements:
        if amount > 0:
            conn.execute(
                "INSERT INTO advance_settlements(payment_voucher_id, payroll_id, amount) "
                "VALUES(?,?,?)", (vid, payroll_id, amount),
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
# المرفقات (تُخزَّن داخل مجلد البيانات وتُحفظ مساراتها في الفاتورة)
# ---------------------------------------------------------------------------
def store_attachment(src: str) -> str:
    """نسخ ملف مرفق إلى مجلد المرفقات (باسم فريد) وإرجاع المسار النسبي."""
    src_path = Path(src)
    folder = db.attachments_dir()
    folder.mkdir(parents=True, exist_ok=True)
    dest = folder / src_path.name
    i = 1
    while dest.exists():
        dest = folder / f"{src_path.stem}_{i}{src_path.suffix}"
        i += 1
    shutil.copy(str(src_path), str(dest))
    return str(dest.relative_to(db.data_dir()))
