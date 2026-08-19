# -*- coding: utf-8 -*-
"""
محرك الحسابات: الأرصدة اللحظية، كشوف الحساب، التقارير الذكية، ولقطات الإغلاق.

الرصيد دائماً يُحسب من الحركات (وليس مخزّناً)؛ لذلك أي إضافة/تعديل/حذف
لأي حركة يعيد احتساب كل الأرصدة تلقائياً وبأثر رجعي (Auto-Recalculation).
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime

from . import db

# ---------------------------------------------------------------------------
# أدوات مساعدة
# ---------------------------------------------------------------------------
def _q(conn: sqlite3.Connection, sql: str, params=()) -> sqlite3.Row | None:
    return conn.execute(sql, params).fetchone()


def _rows(conn: sqlite3.Connection, sql: str, params=()) -> list[sqlite3.Row]:
    return conn.execute(sql, params).fetchall()


def _scalar(conn: sqlite3.Connection, sql: str, params=()) -> float:
    r = conn.execute(sql, params).fetchone()
    return float(r[0]) if r and r[0] is not None else 0.0


# ---------------------------------------------------------------------------
# أرصدة العملاء
# ---------------------------------------------------------------------------
def customer_balance(conn, customer_id: int, before: str | None = None) -> float:
    """رصيد العميل = الرصيد الافتتاحي + إجمالي فواتيره − سندات القبض منه.

    before: إن حُدِّد يُحسب الرصيد حتى تاريخ قبله (لأغراض كشف الحساب).
    """
    opening = _scalar(
        conn, "SELECT opening_balance FROM customers WHERE id=?", (customer_id,)
    )
    inv_cond = "AND i.date < ?" if before else ""
    inv = _scalar(
        conn,
        f"SELECT COALESCE(SUM(t.price),0) FROM invoice_trips t "
        f"JOIN invoices i ON i.id=t.invoice_id WHERE i.customer_id=? {inv_cond}",
        (customer_id, before) if before else (customer_id,),
    )
    rec_cond = "AND v.date < ?" if before else ""
    rec = _scalar(
        conn,
        f"SELECT COALESCE(SUM(v.amount),0) FROM receipt_vouchers v "
        f"WHERE v.voucher_type='customer' AND v.customer_id=? {rec_cond}",
        (customer_id, before) if before else (customer_id,),
    )
    return opening + inv - rec


def customers_with_balance(conn) -> list[dict]:
    rows = _rows(conn, "SELECT * FROM customers ORDER BY code")
    return [dict(r, balance=customer_balance(conn, r["id"])) for r in rows]


# ---------------------------------------------------------------------------
# أرصدة الخزائن والبنوك
# ---------------------------------------------------------------------------
def account_table(kind: str) -> str:
    return "cashboxes" if kind == "cashbox" else "banks"


def account_kind_label(kind: str) -> str:
    return "خزينة" if kind == "cashbox" else "بنك"


def account_balance(conn, kind: str, account_id: int, before: str | None = None) -> float:
    """الرصيد = افتتاحي + سندات القبض − سندات الدفع − الرواتب المنصرفة."""
    tbl = account_table(kind)
    opening = _scalar(conn, f"SELECT opening_balance FROM {tbl} WHERE id=?", (account_id,))
    cond = "AND date < ?" if before else ""
    rec = _scalar(
        conn,
        f"SELECT COALESCE(SUM(amount),0) FROM receipt_vouchers "
        f"WHERE account_kind=? AND account_id=? {cond}",
        (kind, account_id, before) if before else (kind, account_id),
    )
    pay = _scalar(
        conn,
        f"SELECT COALESCE(SUM(amount),0) FROM payment_vouchers "
        f"WHERE account_kind=? AND account_id=? {cond}",
        (kind, account_id, before) if before else (kind, account_id),
    )
    sal = _scalar(
        conn,
        f"SELECT COALESCE(SUM(net_salary),0) FROM payrolls "
        f"WHERE account_kind=? AND account_id=? {cond}",
        (kind, account_id, before) if before else (kind, account_id),
    )
    return opening + rec - pay - sal


def account_name(conn, kind: str, account_id: int) -> str:
    r = _q(conn, f"SELECT name FROM {account_table(kind)} WHERE id=?", (account_id,))
    return r["name"] if r else "—"


def accounts_with_balance(conn, kind: str) -> list[dict]:
    tbl = account_table(kind)
    rows = _rows(conn, f"SELECT * FROM {tbl} ORDER BY code")
    return [dict(r, balance=account_balance(conn, kind, r["id"])) for r in rows]


def all_accounts(conn) -> list[tuple[str, int, str, str]]:
    """قائمة موحدة لكل الخزائن والبنوك للاختيار في السندات والرواتب."""
    out = []
    for r in _rows(conn, "SELECT id, code, name FROM cashboxes ORDER BY code"):
        out.append(("cashbox", r["id"], f"خزينة: {r['name']}", r["code"]))
    for r in _rows(conn, "SELECT id, code, name FROM banks ORDER BY code"):
        out.append(("bank", r["id"], f"بنك: {r['name']}", r["code"]))
    return out


# ---------------------------------------------------------------------------
# حسابات الفواتير والرحلات
# ---------------------------------------------------------------------------
def invoice_totals(conn, invoice_id: int) -> dict:
    """إجماليات الفاتورة: قيمة النقلات، المصروفات المباشرة، الربح المتوقع/الفعلي."""
    trips_total = _scalar(
        conn,
        "SELECT COALESCE(SUM(price),0) FROM invoice_trips WHERE invoice_id=?",
        (invoice_id,),
    )
    expenses_total = _scalar(
        conn,
        "SELECT COALESCE(SUM(e.amount),0) FROM trip_expenses e "
        "JOIN invoice_trips t ON t.id=e.trip_id WHERE t.invoice_id=?",
        (invoice_id,),
    )
    later_payments = _scalar(
        conn,
        "SELECT COALESCE(SUM(p.amount),0) FROM payment_vouchers p "
        "JOIN invoice_trips t ON t.id=p.trip_id "
        "WHERE t.invoice_id=? AND p.voucher_type='trip'",
        (invoice_id,),
    )
    expected = trips_total - expenses_total
    return {
        "trips_total": trips_total,
        "expenses_total": expenses_total,
        "expected_profit": expected,
        "later_payments": later_payments,
        "actual_profit": expected - later_payments,
        # إجمالي الفاتورة على العميل = قيمة النقلات فقط (المصروفات داخلية)
        "customer_total": trips_total,
    }


def trip_profit(conn, trip_id: int) -> dict:
    """ربح النقلة = سعرها − مصروفاتها المباشرة − سندات الدفع اللاحقة عليها."""
    price = _scalar(conn, "SELECT price FROM invoice_trips WHERE id=?", (trip_id,))
    direct = _scalar(
        conn, "SELECT COALESCE(SUM(amount),0) FROM trip_expenses WHERE trip_id=?",
        (trip_id,),
    )
    later = _scalar(
        conn,
        "SELECT COALESCE(SUM(amount),0) FROM payment_vouchers "
        "WHERE voucher_type='trip' AND trip_id=?",
        (trip_id,),
    )
    return {"price": price, "direct": direct, "later": later, "net": price - direct - later}


def invoice_list(conn, d_from=None, d_to=None, customer_id=None) -> list[dict]:
    sql = ("SELECT i.*, c.name AS customer_name, c.code AS customer_code "
           "FROM invoices i JOIN customers c ON c.id=i.customer_id WHERE 1=1")
    params: list = []
    if d_from:
        sql += " AND i.date >= ?"
        params.append(d_from)
    if d_to:
        sql += " AND i.date <= ?"
        params.append(d_to)
    if customer_id:
        sql += " AND i.customer_id=?"
        params.append(customer_id)
    sql += " ORDER BY i.date DESC, i.number DESC"
    out = []
    for r in _rows(conn, sql, params):
        d = dict(r)
        d.update(invoice_totals(conn, d["id"]))
        out.append(d)
    return out


def invoice_number_label(n: int) -> str:
    return f"INV-{n:05d}"


def voucher_number_label(prefix: str, n: int) -> str:
    return f"{prefix}-{n:05d}"


def get_invoice_full(conn, invoice_id: int) -> dict:
    """الفاتورة كاملة (الرأس + النقلات + مصروفات كل نقلة)."""
    inv = _q(conn, "SELECT * FROM invoices WHERE id=?", (invoice_id,))
    if not inv:
        return {}
    d = dict(inv)
    d["customer"] = dict(_q(conn, "SELECT * FROM customers WHERE id=?", (d["customer_id"],)))
    d["trips"] = []
    for t in _rows(
        conn,
        "SELECT * FROM invoice_trips WHERE invoice_id=? ORDER BY id", (invoice_id,)
    ):
        td = dict(t)
        td["expenses"] = [dict(e) for e in _rows(
            conn, "SELECT * FROM trip_expenses WHERE trip_id=? ORDER BY id", (t["id"],)
        )]
        d["trips"].append(td)
    d.update(invoice_totals(conn, invoice_id))
    return d


def trips_options(conn) -> list[dict]:
    """قائمة اختيار الرحلات (النقلات) لربط سندات الدفع بها."""
    rows = _rows(
        conn,
        "SELECT t.id, t.from_loc, t.to_loc, i.number AS inv_number, i.date AS inv_date, "
        "v.plate_number, e.name AS driver_name, c.name AS customer_name "
        "FROM invoice_trips t "
        "JOIN invoices i ON i.id=t.invoice_id "
        "JOIN customers c ON c.id=i.customer_id "
        "LEFT JOIN vehicles v ON v.id=t.vehicle_id "
        "LEFT JOIN employees e ON e.id=t.driver_id "
        "ORDER BY i.date DESC, i.number DESC, t.id",
    )
    out = []
    for r in rows:
        label = (f"{invoice_number_label(r['inv_number'])} | {r['inv_date']} | "
                 f"{r['customer_name']} | {r['from_loc'] or '—'} ← {r['to_loc'] or '—'}"
                 f" | {r['plate_number'] or '—'} | {r['driver_name'] or '—'}")
        out.append({"id": r["id"], "label": label})
    return out


# ---------------------------------------------------------------------------
# كشوف الحساب
# ---------------------------------------------------------------------------
def customer_statement(conn, customer_id: int, d_from: str, d_to: str) -> dict:
    """كشف حساب عميل: الرصيد الافتتاحي + الفواتير − سندات القبض = الرصيد الحالي."""
    opening = customer_balance(conn, customer_id, before=d_from)
    rows: list[dict] = []
    inv = _rows(
        conn,
        "SELECT id, number, date FROM invoices WHERE customer_id=? "
        "AND date >= ? AND date <= ? ORDER BY date, id",
        (customer_id, d_from, d_to),
    )
    for r in inv:
        totals = invoice_totals(conn, r["id"])
        rows.append({
            "date": r["date"], "doc": f"فاتورة نقل {invoice_number_label(r['number'])}",
            "desc": "نقلات مسجلة على العميل", "debit": totals["customer_total"],
            "credit": 0.0, "kind": "invoice",
        })
    rec = _rows(
        conn,
        "SELECT id, number, date, amount, description FROM receipt_vouchers "
        "WHERE voucher_type='customer' AND customer_id=? "
        "AND date >= ? AND date <= ? ORDER BY date, id",
        (customer_id, d_from, d_to),
    )
    for r in rec:
        rows.append({
            "date": r["date"], "doc": f"سند قبض {voucher_number_label('RV', r['number'])}",
            "desc": r["description"] or "تحصيل من العميل", "debit": 0.0,
            "credit": r["amount"], "kind": "receipt",
        })
    rows.sort(key=lambda x: (x["date"], 0 if x["kind"] == "invoice" else 1))
    balance = opening
    for r in rows:
        balance += r["debit"] - r["credit"]
        r["balance"] = balance
    return {"opening": opening, "rows": rows, "closing": balance}


def account_statement(conn, kind: str, account_id: int, d_from: str, d_to: str) -> dict:
    """كشف حساب خزينة/بنك: كل حركات القبض والدفع والرواتب."""
    opening = account_balance(conn, kind, account_id, before=d_from)
    rows: list[dict] = []
    rec = _rows(
        conn,
        "SELECT v.id, v.number, v.date, v.amount, v.description, v.voucher_type, "
        "c.name AS customer_name FROM receipt_vouchers v "
        "LEFT JOIN customers c ON c.id=v.customer_id "
        "WHERE v.account_kind=? AND v.account_id=? AND v.date>=? AND v.date<=? "
        "ORDER BY v.date, v.id",
        (kind, account_id, d_from, d_to),
    )
    for r in rec:
        desc = ("تحصيل من العميل: " + r["customer_name"]) if r["voucher_type"] == "customer" \
            else ("إيرادات أخرى: " + (r["description"] or "—"))
        rows.append({
            "date": r["date"], "doc": f"سند قبض {voucher_number_label('RV', r['number'])}",
            "desc": desc, "in": r["amount"], "out": 0.0,
            "balance": 0.0, "kind": "receipt",
        })
    pay = _rows(
        conn,
        "SELECT * FROM payment_vouchers WHERE account_kind=? AND account_id=? "
        "AND date>=? AND date<=? ORDER BY date, id",
        (kind, account_id, d_from, d_to),
    )
    from ..utils.fmt import PAYMENT_TYPES
    for r in pay:
        rows.append({
            "date": r["date"], "doc": f"سند دفع {voucher_number_label('PV', r['number'])}",
            "desc": PAYMENT_TYPES.get(r["voucher_type"], r["voucher_type"]) +
                    (" — " + r["description"] if r["description"] else ""),
            "in": 0.0, "out": r["amount"], "balance": 0.0, "kind": "payment",
        })
    sal = _rows(
        conn,
        "SELECT p.*, e.name AS emp_name FROM payrolls p "
        "JOIN employees e ON e.id=p.employee_id "
        "WHERE p.account_kind=? AND p.account_id=? AND p.date>=? AND p.date<=? "
        "ORDER BY p.date, p.id",
        (kind, account_id, d_from, d_to),
    )
    from ..utils.fmt import period_label
    for r in sal:
        rows.append({
            "date": r["date"], "doc": f"راتب {voucher_number_label('PAY', r['number'])}",
            "desc": f"راتب {r['emp_name']} عن {period_label(r['period_year'], r['period_month'])}",
            "in": 0.0, "out": r["net_salary"], "balance": 0.0, "kind": "payroll",
        })
    rows.sort(key=lambda x: (x["date"], {"receipt": 0, "payment": 1, "payroll": 2}[x["kind"]]))
    balance = opening
    for r in rows:
        balance += r["in"] - r["out"]
        r["balance"] = balance
    return {"opening": opening, "rows": rows, "closing": balance}


# ---------------------------------------------------------------------------
# تقرير 1: أرباح الفواتير والرحلات
# ---------------------------------------------------------------------------
def trip_profits_report(conn, d_from=None, d_to=None, customer_id=None) -> list[dict]:
    """كل نقلة: الإيراد، المصروف المباشر، المصروف اللاحق من سندات الدفع، الربح الفعلي."""
    sql = ("SELECT t.*, i.number AS inv_number, i.date AS inv_date, "
           "c.name AS customer_name, v.plate_number, e.name AS driver_name "
           "FROM invoice_trips t "
           "JOIN invoices i ON i.id=t.invoice_id "
           "JOIN customers c ON c.id=i.customer_id "
           "LEFT JOIN vehicles v ON v.id=t.vehicle_id "
           "LEFT JOIN employees e ON e.id=t.driver_id WHERE 1=1")
    params: list = []
    if d_from:
        sql += " AND i.date >= ?"
        params.append(d_from)
    if d_to:
        sql += " AND i.date <= ?"
        params.append(d_to)
    if customer_id:
        sql += " AND i.customer_id=?"
        params.append(customer_id)
    sql += " ORDER BY i.date, i.number, t.id"
    out = []
    for r in _rows(conn, sql, params):
        p = trip_profit(conn, r["id"])
        out.append({
            "trip_id": r["id"],
            "invoice": invoice_number_label(r["inv_number"]),
            "date": r["inv_date"],
            "customer": r["customer_name"],
            "route": f"{r['from_loc'] or '—'} ← {r['to_loc'] or '—'}",
            "vehicle": r["plate_number"] or "—",
            "driver": r["driver_name"] or "—",
            "revenue": p["price"],
            "direct": p["direct"],
            "later": p["later"],
            "net": p["net"],
        })
    return out


# ---------------------------------------------------------------------------
# تقرير 3: كشف حساب موظف/سائق
# ---------------------------------------------------------------------------
def employee_statement(conn, employee_id: int, d_from=None, d_to=None) -> dict:
    """الرواتب المنصرفة + سجل السلف وتسوياتها + بدلات التريب من الفواتير."""
    cond, params = "", []
    if d_from:
        cond += " AND date >= ?"
        params.append(d_from)
    if d_to:
        cond += " AND date <= ?"
        params.append(d_to)

    salaries = []
    for r in _rows(
        conn,
        f"SELECT * FROM payrolls WHERE employee_id=? {cond} ORDER BY date, id",
        [employee_id] + params,
    ):
        salaries.append(dict(r))

    advances = []
    for r in _rows(
        conn,
        f"SELECT * FROM payment_vouchers WHERE voucher_type='advance' AND employee_id=? "
        f"{cond} ORDER BY date, id",
        [employee_id] + params,
    ):
        settled = _scalar(
            conn,
            "SELECT COALESCE(SUM(amount),0) FROM advance_settlements "
            "WHERE payment_voucher_id=?",
            (r["id"],),
        )
        settlements = _rows(
            conn,
            "SELECT s.amount, s.payroll_id, p.date AS pdate, p.number AS pnum "
            "FROM advance_settlements s JOIN payrolls p ON p.id=s.payroll_id "
            "WHERE s.payment_voucher_id=? ORDER BY p.date",
            (r["id"],),
        )
        advances.append({
            **dict(r),
            "settled": settled,
            "remaining": r["amount"] - settled,
            "settlements": [dict(s) for s in settlements],
        })

    allowances = []
    a_cond, a_params = "", []
    if d_from:
        a_cond += " AND i.date >= ?"
        a_params.append(d_from)
    if d_to:
        a_cond += " AND i.date <= ?"
        a_params.append(d_to)
    for r in _rows(
        conn,
        f"SELECT t.id, t.from_loc, t.to_loc, t.price, i.number AS inv_number, i.date AS inv_date "
        f"FROM invoice_trips t JOIN invoices i ON i.id=t.invoice_id "
        f"WHERE t.driver_id=? {a_cond} ORDER BY i.date, t.id",
        [employee_id] + a_params,
    ):
        trip_pay = _scalar(
            conn,
            "SELECT COALESCE(SUM(amount),0) FROM trip_expenses "
            "WHERE trip_id=? AND expense_type='trip'",
            (r["id"],),
        )
        allowances.append({
            **dict(r), "trip_allowance": trip_pay,
            "route": f"{r['from_loc'] or '—'} ← {r['to_loc'] or '—'}",
        })

    totals = {
        "salaries_net": sum(s["net_salary"] for s in salaries),
        "salaries_additions": sum(s["additions"] for s in salaries),
        "salaries_deductions": sum(s["advance_deduction"] + s["other_deductions"]
                                   for s in salaries),
        "advances_total": sum(a["amount"] for a in advances),
        "advances_remaining": sum(a["remaining"] for a in advances),
        "allowances_total": sum(a["trip_allowance"] for a in allowances),
    }
    return {"salaries": salaries, "advances": advances, "allowances": allowances,
            "totals": totals}


# ---------------------------------------------------------------------------
# تقرير 4: أداء السيارات
# ---------------------------------------------------------------------------
def vehicle_report(conn, d_from=None, d_to=None, vehicle_id=None) -> list[dict]:
    """إيرادات السيارة من الفواتير − مصروفات رحلاتها − صيانتها من سندات الدفع."""
    inv_cond, inv_params, pay_cond, pay_params = "", [], "", []
    if d_from:
        inv_cond += " AND i.date >= ?"
        inv_params.append(d_from)
        pay_cond += " AND date >= ?"
        pay_params.append(d_from)
    if d_to:
        inv_cond += " AND i.date <= ?"
        inv_params.append(d_to)
        pay_cond += " AND date <= ?"
        pay_params.append(d_to)
    if vehicle_id:
        inv_cond += " AND t.vehicle_id=?"
        inv_params.append(vehicle_id)
    vehicles = _rows(conn, "SELECT * FROM vehicles ORDER BY code")
    out = []
    for v in vehicles:
        if vehicle_id and v["id"] != vehicle_id:
            continue
        inv_p = [v["id"]] + inv_params
        revenue = _scalar(
            conn,
            f"SELECT COALESCE(SUM(t.price),0) FROM invoice_trips t "
            f"JOIN invoices i ON i.id=t.invoice_id WHERE t.vehicle_id=? {inv_cond}",
            inv_p,
        )
        trips_count = _scalar(
            conn,
            f"SELECT COUNT(*) FROM invoice_trips t "
            f"JOIN invoices i ON i.id=t.invoice_id WHERE t.vehicle_id=? {inv_cond}",
            inv_p,
        )
        direct = _scalar(
            conn,
            f"SELECT COALESCE(SUM(e.amount),0) FROM trip_expenses e "
            f"JOIN invoice_trips t ON t.id=e.trip_id "
            f"JOIN invoices i ON i.id=t.invoice_id WHERE t.vehicle_id=? {inv_cond}",
            inv_p,
        )
        maintenance = _scalar(
            conn,
            f"SELECT COALESCE(SUM(amount),0) FROM payment_vouchers "
            f"WHERE voucher_type='vehicle' AND vehicle_id=? {pay_cond}",
            [v["id"]] + pay_params,
        )
        out.append({
            "vehicle_id": v["id"], "code": v["code"], "plate": v["plate_number"],
            "vtype": v["vehicle_type"], "trips": int(trips_count),
            "revenue": revenue, "direct": direct, "maintenance": maintenance,
            "net": revenue - direct - maintenance,
        })
    return out


# ---------------------------------------------------------------------------
# تقرير 5: الأرباح والخسائر الشامل
# ---------------------------------------------------------------------------
def pnl_report(conn, d_from=None, d_to=None) -> dict:
    """(إيرادات النقلات + إيرادات أخرى) − (مباشرة + رواتب + سلف + صيانة + عامة)."""
    def period(table: str, date_col: str = "date") -> str:
        c = ""
        if d_from:
            c += f" AND {table}.{date_col} >= ?"
        if d_to:
            c += f" AND {table}.{date_col} <= ?"
        return c

    def period_cols() -> list:
        p = []
        if d_from:
            p.append(d_from)
        if d_to:
            p.append(d_to)
        return p

    transport = _scalar(
        conn,
        f"SELECT COALESCE(SUM(t.price),0) FROM invoice_trips t "
        f"JOIN invoices i ON i.id=t.invoice_id WHERE 1=1 {period('i', 'date')}",
        period_cols(),
    )
    other_rev = _scalar(
        conn,
        f"SELECT COALESCE(SUM(amount),0) FROM receipt_vouchers "
        f"WHERE voucher_type='other' AND 1=1 {period('receipt_vouchers')}",
        period_cols(),
    )
    direct = _scalar(
        conn,
        f"SELECT COALESCE(SUM(e.amount),0) FROM trip_expenses e "
        f"JOIN invoice_trips t ON t.id=e.trip_id "
        f"JOIN invoices i ON i.id=t.invoice_id WHERE 1=1 {period('i', 'date')}",
        period_cols(),
    )
    salaries = _scalar(
        conn,
        f"SELECT COALESCE(SUM(net_salary),0) FROM payrolls WHERE 1=1 {period('payrolls')}",
        period_cols(),
    )
    advances = _scalar(
        conn,
        f"SELECT COALESCE(SUM(amount),0) FROM payment_vouchers "
        f"WHERE voucher_type='advance' AND 1=1 {period('payment_vouchers')}",
        period_cols(),
    )
    maintenance = _scalar(
        conn,
        f"SELECT COALESCE(SUM(amount),0) FROM payment_vouchers "
        f"WHERE voucher_type='vehicle' AND 1=1 {period('payment_vouchers')}",
        period_cols(),
    )
    general = _scalar(
        conn,
        f"SELECT COALESCE(SUM(amount),0) FROM payment_vouchers "
        f"WHERE voucher_type='general' AND 1=1 {period('payment_vouchers')}",
        period_cols(),
    )
    total_rev = transport + other_rev
    total_exp = direct + salaries + advances + maintenance + general
    return {
        "transport_revenue": transport,
        "other_revenue": other_rev,
        "total_revenue": total_rev,
        "direct_expenses": direct,
        "salaries": salaries,
        "advances": advances,
        "maintenance": maintenance,
        "general_expenses": general,
        "total_expenses": total_exp,
        "net": total_rev - total_exp,
    }


# ---------------------------------------------------------------------------
# لقطة إغلاق السنة المالية (Snapshot)
# ---------------------------------------------------------------------------
def year_snapshot_data(conn, year_id: int) -> dict:
    y = _q(conn, "SELECT * FROM financial_years WHERE id=?", (year_id,))
    if not y:
        return {}
    pnl = pnl_report(conn, y["date_from"], y["date_to"])
    customers = [
        {"code": r["code"], "name": r["name"],
         "balance": round(customer_balance(conn, r["id"]), 2)}
        for r in _rows(conn, "SELECT * FROM customers ORDER BY code")
    ]
    cashboxes = [
        {"code": r["code"], "name": r["name"],
         "balance": round(account_balance(conn, "cashbox", r["id"]), 2)}
        for r in _rows(conn, "SELECT * FROM cashboxes ORDER BY code")
    ]
    banks = [
        {"code": r["code"], "name": r["name"],
         "balance": round(account_balance(conn, "bank", r["id"]), 2)}
        for r in _rows(conn, "SELECT * FROM banks ORDER BY code")
    ]
    return {
        "created_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "year": y["year"], "date_from": y["date_from"], "date_to": y["date_to"],
        "customers": customers, "cashboxes": cashboxes, "banks": banks,
        "pnl": {k: round(v, 2) for k, v in pnl.items()},
    }
