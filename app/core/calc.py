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

from .tax import round2
from ..utils import fmt

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
def _invoice_billable_sql() -> str:
    """قيمة النقلة + المصروفات التي يتحمّلها العميل (قبل الضريبة)."""
    return (
        "COALESCE((SELECT SUM(t.price) FROM invoice_trips t "
        "WHERE t.invoice_id = i.id), 0) "
        "+ COALESCE((SELECT SUM(e.amount) FROM trip_expenses e "
        "JOIN invoice_trips t2 ON t2.id = e.trip_id "
        "WHERE t2.invoice_id = i.id AND e.source = 'customer'), 0)"
    )


def customer_balance(conn, customer_id: int, before: str | None = None) -> float:
    """رصيد العميل = افتتاحي + فواتيره (شاملة الضريبة ومصروفه) − المقبوض ± الإشعارات.

    مطابق لـ customerBalance في نسخة الويب:
      • إجمالي الفاتورة على العميل = (قيمة النقلات + المصروفات التي يتحمّلها) × (1 + النسبة).
      • الإشعار المدين يزيد المديونية، والدائن يقللها.
      • before: يُحسب الرصيد حتى تاريخ قبله (لأغراض كشف الحساب).
    """
    opening = _scalar(
        conn, "SELECT opening_balance FROM customers WHERE id=?", (customer_id,)
    )
    inv_cond = "AND i.date < ?" if before else ""
    # مطابق حرفياً لـ customerBalance في الويب: sub + round2(sub × rate / 100)
    # (تقريب الضريبة لكل فاتورة على حدة قبل الجمع، لا الضرب في 1+النسبة)
    inv = _scalar(
        conn,
        f"SELECT COALESCE(SUM(x.total), 0) FROM ("
        f"  SELECT ({_invoice_billable_sql()}) "
        f"         + ROUND((({_invoice_billable_sql()}) * i.vat_rate) / 100.0, 2) "
        f"         AS total "
        f"  FROM invoices i WHERE i.customer_id = ? {inv_cond}"
        f") x",
        (customer_id, before) if before else (customer_id,),
    )
    rec_cond = "AND v.date < ?" if before else ""
    rec = _scalar(
        conn,
        f"SELECT COALESCE(SUM(v.amount),0) FROM receipt_vouchers v "
        f"WHERE v.voucher_type='customer' AND v.customer_id=? {rec_cond}",
        (customer_id, before) if before else (customer_id,),
    )
    note_cond = "AND date < ?" if before else ""
    notes = _rows(
        conn,
        f"SELECT note_type, amount, vat_rate FROM credit_debit_notes "
        f"WHERE customer_id = ? {note_cond}",
        (customer_id, before) if before else (customer_id,),
    )
    note_effect = sum(
        note_total(n["amount"], n["vat_rate"]) * (1 if n["note_type"] == "debit" else -1)
        for n in notes
    )
    return round2(opening + inv - rec + note_effect)


def note_total(amount, vat_rate) -> float:
    """إجمالي الإشعار شامل الضريبة."""
    amount = float(amount or 0)
    return round2(amount + round2((amount * float(vat_rate or 0)) / 100.0))


def customers_with_balance(conn) -> list[dict]:
    rows = _rows(conn, "SELECT * FROM customers ORDER BY code")
    return [dict(r, balance=round2(customer_balance(conn, r["id"]))) for r in rows]


# ---------------------------------------------------------------------------
# المشتريات والموردون (دورة المشتريات النقدية والآجلة)
# ---------------------------------------------------------------------------
def purchase_totals(items: list[dict], vat_included: bool = False) -> dict:
    """إجماليات فاتورة المشتريات.

    إن كانت الأسعار شاملة الضريبة يُستخرج الصافي بالقسمة على (1 + النسبة).
    مطابق لـ purchaseTotals في نسخة الويب.
    """
    net = 0.0
    vat = 0.0
    for it in items:
        gross = float(it.get("qty") or 0) * float(it.get("unit_price") or 0)
        rate = float(it.get("vat_rate") or 0) / 100.0
        if vat_included:
            base = gross / (1 + rate) if rate > -1 else gross
            net += base
            vat += gross - base
        else:
            net += gross
            vat += gross * rate
    net, vat = round2(net), round2(vat)
    return {"net": net, "vat": vat, "total": round2(net + vat)}


def purchase_items(conn, invoice_id: int) -> list[dict]:
    return [dict(r) for r in _rows(
        conn, "SELECT * FROM purchase_items WHERE invoice_id=? ORDER BY id",
        (invoice_id,))]


def purchase_net(conn, invoice_id: int, vat_included: bool = False) -> float:
    """صافي فاتورة مشتريات قبل الضريبة (يُستخدم في الأرباح والخسائر)."""
    return purchase_totals(purchase_items(conn, invoice_id), vat_included)["net"]


def purchase_invoice_totals(conn, invoice_id: int) -> dict:
    """إجماليات فاتورة مشتريات مع بنودها (تُقرأ من القاعدة لا من المدخلات)."""
    row = _q(conn, "SELECT * FROM purchase_invoices WHERE id=?", (invoice_id,))
    if not row:
        return {"net": 0.0, "vat": 0.0, "total": 0.0, "items": []}
    items = purchase_items(conn, invoice_id)
    totals = purchase_totals(items, bool(row["vat_included"]))
    totals["items"] = items
    return totals


def supplier_balance(conn, supplier_id: int, before: str | None = None) -> float:
    """رصيد المورّد: موجب = مستحق له علينا، سالب = دفعنا زيادة."""
    sup = _q(conn, "SELECT opening_balance FROM suppliers WHERE id=?", (supplier_id,))
    if not sup:
        return 0.0
    cond = "AND date < ?" if before else ""
    params = (supplier_id, before) if before else (supplier_id,)
    purchases = 0.0
    for row in _rows(
        conn,
        f"SELECT id, vat_included FROM purchase_invoices "
        f"WHERE supplier_id=? {cond}", params,
    ):
        purchases += purchase_totals(purchase_items(conn, row["id"]),
                                     bool(row["vat_included"]))["total"]
    paid = _scalar(
        conn,
        f"SELECT COALESCE(SUM(amount),0) FROM payment_vouchers "
        f"WHERE supplier_id=? {cond}", params,
    )
    return round2(float(sup["opening_balance"] or 0) + purchases - paid)


def suppliers_with_balance(conn) -> list[dict]:
    rows = _rows(conn, "SELECT * FROM suppliers ORDER BY code")
    return [dict(r, balance=supplier_balance(conn, r["id"])) for r in rows]


def supplier_statement(conn, supplier_id: int, d_from: str | None = None,
                       d_to: str | None = None) -> dict:
    """كشف حساب مورّد: افتتاحي + فواتير المشتريات − سندات الدفع = الرصيد."""
    sup = _q(conn, "SELECT * FROM suppliers WHERE id=?", (supplier_id,))
    if not sup:
        return {"opening": 0.0, "rows": [], "totals": {"credit": 0.0, "debit": 0.0,
                                                      "balance": 0.0}}
    opening = (supplier_balance(conn, supplier_id, before=d_from) if d_from
               else round2(float(sup["opening_balance"] or 0)))
    events: list[dict] = []
    inv_cond, inv_params = "", [supplier_id]
    if d_from:
        inv_cond += " AND date >= ?"
        inv_params.append(d_from)
    if d_to:
        inv_cond += " AND date <= ?"
        inv_params.append(d_to)
    for row in _rows(
        conn,
        f"SELECT id, number, date, supplier_ref, vat_included FROM purchase_invoices "
        f"WHERE supplier_id=? {inv_cond}", inv_params,
    ):
        total = purchase_totals(purchase_items(conn, row["id"]),
                                bool(row["vat_included"]))["total"]
        events.append({
            "date": row["date"], "doc": f"مشتريات #{row['number']}",
            "desc": (f"مرجع المورّد: {row['supplier_ref']}" if row["supplier_ref"]
                     else "فاتورة مشتريات"),
            "credit": total, "debit": 0.0, "kind": "purchase",
        })
    for row in _rows(
        conn,
        f"SELECT id, number, date, amount, description FROM payment_vouchers "
        f"WHERE supplier_id=? {inv_cond}", inv_params,
    ):
        events.append({
            "date": row["date"], "doc": f"سند دفع #{row['number']}",
            "desc": row["description"] or "سداد للمورّد",
            "credit": 0.0, "debit": round2(row["amount"]), "kind": "payment",
        })
    events.sort(key=lambda x: x["date"])
    running = round2(opening)
    rows = [{"date": d_from or "", "doc": "رصيد افتتاحي",
             "desc": ("المرحّل حتى بداية الفترة" if d_from else "الرصيد الافتتاحي للمورّد"),
             "credit": 0.0, "debit": 0.0, "balance": running, "kind": "opening"}]
    credit = debit = 0.0
    for e in events:
        running = round2(running + e["credit"] - e["debit"])
        credit += e["credit"]
        debit += e["debit"]
        rows.append({**e, "balance": running})
    return {
        "opening": round2(opening), "rows": rows, "closing": running,
        "totals": {"credit": round2(credit), "debit": round2(debit),
                   "balance": running},
    }


# ---------------------------------------------------------------------------
# أعمار الديون (السداد يُخصم بأسلوب الأقدم أولاً FIFO)
# ---------------------------------------------------------------------------
def build_aging(invoices: list[dict], paid: float, as_of=None) -> dict:
    """توزيع المستحقات على شرائح عمرية بناءً على تاريخ كل فاتورة.

    مطابق لـ buildAging في نسخة الويب: 0-30 / 31-60 / 61-90 / أكثر من 90 يوماً.
    """
    from datetime import date as _date
    if as_of is None:
        as_of = _date.today()
    elif isinstance(as_of, str):
        as_of = _date.fromisoformat(as_of[:10])
    ordered = sorted(invoices, key=lambda x: str(x["date"]))
    remaining = float(paid or 0)
    buckets = {"current": 0.0, "d31_60": 0.0, "d61_90": 0.0, "over90": 0.0}
    for inv in ordered:
        due = float(inv["total"] or 0)
        if remaining > 0:
            used = min(remaining, due)
            due -= used
            remaining -= used
        if due <= 0:
            continue
        try:
            d = _date.fromisoformat(str(inv["date"])[:10])
        except ValueError:
            d = as_of
        age = (as_of - d).days
        if age <= 30:
            buckets["current"] += due
        elif age <= 60:
            buckets["d31_60"] += due
        elif age <= 90:
            buckets["d61_90"] += due
        else:
            buckets["over90"] += due
    total = sum(buckets.values())
    return {k: round2(v) for k, v in buckets.items()} | {"total": round2(total)}


def _aging_rows(conn, kind: str, as_of=None) -> list[dict]:
    """أعمار ديون الموردين (ما علينا لهم) أو العملاء (ما لنا عليهم)."""
    if kind == "supplier":
        masters = _rows(conn, "SELECT * FROM suppliers ORDER BY code")
        inv_sql = ("SELECT id, date, vat_included FROM purchase_invoices "
                   "WHERE supplier_id=? ORDER BY date")
        pay_sql = ("SELECT COALESCE(SUM(amount),0) FROM payment_vouchers "
                   "WHERE supplier_id=?")
    else:
        masters = _rows(conn, "SELECT * FROM customers ORDER BY code")
        inv_sql = "SELECT id, date, vat_rate FROM invoices WHERE customer_id=? ORDER BY date"
        pay_sql = ("SELECT COALESCE(SUM(amount),0) FROM receipt_vouchers "
                   "WHERE voucher_type='customer' AND customer_id=?")
    out = []
    for m in masters:
        docs: list[dict] = []
        opening = float(m["opening_balance"] or 0)
        if opening > 0:
            docs.append({"date": (m["created_at"] or "2000-01-01")[:10], "total": opening})
        for row in _rows(conn, inv_sql, (m["id"],)):
            if kind == "supplier":
                total = purchase_totals(purchase_items(conn, row["id"]),
                                        bool(row["vat_included"]))["total"]
            else:
                total = invoice_totals(conn, row["id"])["customer_total"]
            docs.append({"date": row["date"], "total": total})
        paid = float(_scalar(conn, pay_sql, (m["id"],)))
        # إشعارات العميل الدائنة تُقلل المستحق (المدينة تزيده)
        if kind == "customer":
            paid -= sum(
                note_total(n["amount"], n["vat_rate"])
                * (1 if n["note_type"] == "debit" else -1)
                for n in _rows(
                    conn,
                    "SELECT note_type, amount, vat_rate FROM credit_debit_notes "
                    "WHERE customer_id=?", (m["id"],)))
        buckets = build_aging(docs, paid, as_of)
        if buckets["total"] != 0:
            out.append({"id": m["id"], "code": m["code"], "name": m["name"], **buckets})
    out.sort(key=lambda x: -x["total"])
    return out


def suppliers_aging(conn, as_of=None) -> list[dict]:
    """تقرير أعمار ديون الموردين (ما علينا لهم)."""
    return _aging_rows(conn, "supplier", as_of)


def customers_aging(conn, as_of=None) -> list[dict]:
    """تقرير أعمار ديون العملاء (ما لنا عليهم)."""
    return _aging_rows(conn, "customer", as_of)


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
def _totals_from(vat_rate: float, trips_total: float, billable_total: float,
                 expenses_total: float, later: float) -> dict:
    """الإجماليات الموحّدة للفاتورة (مطابقة لـ totalsFrom في نسخة الويب).

    billable_total = مصروفات يتحمّلها العميل → تُضاف للإيراد وتدخل وعاء الضريبة.
    expenses_total = تكلفة مباشرة على الشركة.
    """
    revenue = round2(float(trips_total) + float(billable_total))
    expected = round2(revenue - float(expenses_total))
    vat_amount = round2((revenue * float(vat_rate or 0)) / 100.0)
    return {
        "trips_total": round2(trips_total),
        "billable_total": round2(billable_total),
        "expenses_total": round2(expenses_total),
        "expected_profit": expected,
        "later_payments": round2(later),
        "actual_profit": round2(expected - float(later)),
        "vat_rate": round2(vat_rate),
        "vat_amount": vat_amount,
        "customer_total": round2(revenue + vat_amount),
    }


def invoice_totals(conn, invoice_id: int) -> dict:
    """إجماليات الفاتورة: النقلات، مصروف العميل، التكلفة، الربح، الضريبة، الإجمالي.

    السندات المتولّدة تلقائياً من مصروفات الفاتورة (source_expense_id) مستبعدة
    من «المصاريف اللاحقة» وإلا احتُسب المصروف مرتين.
    """
    inv = _q(conn, "SELECT vat_rate FROM invoices WHERE id=?", (invoice_id,))
    vat_rate = inv["vat_rate"] if inv else 0.0

    trips = _rows(conn, "SELECT id, price FROM invoice_trips WHERE invoice_id=?",
                  (invoice_id,))
    trips_total = sum(float(t["price"] or 0) for t in trips)
    trip_ids = [t["id"] for t in trips]

    billable = 0.0
    expenses_total = 0.0
    later = 0.0
    if trip_ids:
        marks = ",".join("?" * len(trip_ids))
        for e in _rows(
            conn,
            f"SELECT amount, source FROM trip_expenses WHERE trip_id IN ({marks})",
            trip_ids,
        ):
            if (e["source"] or "cash") == "customer":
                billable += float(e["amount"] or 0)
            else:
                expenses_total += float(e["amount"] or 0)
        later = _scalar(
            conn,
            f"SELECT COALESCE(SUM(amount),0) FROM payment_vouchers "
            f"WHERE voucher_type='trip' AND source_expense_id IS NULL "
            f"AND trip_id IN ({marks})",
            trip_ids,
        )
    return _totals_from(vat_rate, trips_total, billable, expenses_total, later)


def trip_profit(conn, trip_id: int, p_from: str | None = None,
                p_to: str | None = None) -> dict:
    """ربح النقلة = (سعرها + مصروف يتحمله العميل) − تكلفتها − سندات الدفع اللاحقة.

    p_from/p_to: عند تحديدهما تُحتسب السندات اللاحقة داخل الفترة فقط
    (اتساقاً مع تقرير الأرباح والخسائر عن نفس الفترة).
    """
    base_price = _scalar(conn, "SELECT price FROM invoice_trips WHERE id=?", (trip_id,))
    billable = _scalar(
        conn,
        "SELECT COALESCE(SUM(amount),0) FROM trip_expenses "
        "WHERE trip_id=? AND source='customer'", (trip_id,),
    )
    direct = _scalar(
        conn,
        "SELECT COALESCE(SUM(amount),0) FROM trip_expenses "
        "WHERE trip_id=? AND source<>'customer'", (trip_id,),
    )
    price = round2(base_price + billable)
    cond, params = "", [trip_id]
    if p_from:
        cond += " AND date >= ?"
        params.append(p_from)
    if p_to:
        cond += " AND date <= ?"
        params.append(p_to)
    later = _scalar(
        conn,
        f"SELECT COALESCE(SUM(amount),0) FROM payment_vouchers "
        f"WHERE voucher_type='trip' AND source_expense_id IS NULL "
        f"AND trip_id=?{cond}",
        params,
    )
    return {"price": price, "direct": round2(direct), "later": round2(later),
            "net": round2(price - direct - later)}


def invoice_list(conn, d_from=None, d_to=None, customer_id=None) -> list[dict]:
    """قائمة الفواتير مع إجمالياتها وعدد نقلاتها وحالة الإشعار الدائن."""
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
        d["trips_count"] = int(_scalar(
            conn, "SELECT COUNT(*) FROM invoice_trips WHERE invoice_id=?", (d["id"],)))
        d["has_credit_note"] = bool(_scalar(
            conn,
            "SELECT COUNT(*) FROM credit_debit_notes n "
            "JOIN credit_note_trips l ON l.note_id=n.id "
            "JOIN invoice_trips t ON t.id=l.trip_id "
            "WHERE t.invoice_id=? AND n.note_type='credit'", (d["id"],)))
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
    try:
        _att = json.loads(d.get("attachments") or "[]")
        d["attachments"] = _att if isinstance(_att, list) else []
    except (ValueError, TypeError):
        d["attachments"] = []
    d["trips"] = []
    for t in _rows(
        conn,
        "SELECT * FROM invoice_trips WHERE invoice_id=? ORDER BY id", (invoice_id,)
    ):
        td = dict(t)
        # أرقام الحاويات مخزّنة كنص JSON — تُفكّ إلى قائمة حتى تصلح لإعادة الحفظ
        try:
            _cn = json.loads(td.get("container_numbers") or "[]")
            td["container_numbers"] = _cn if isinstance(_cn, list) else []
        except (ValueError, TypeError):
            td["container_numbers"] = []
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
    """كشف حساب عميل: افتتاحي + الفواتير − سندات القبض ± الإشعارات = الرصيد.

    مطابق لـ customerStatement في نسخة الويب (يشمل الإشعارات الدائنة والمدينة
    ويفرز الإجماليات: المفوتر، المحصّل، إشعارات مدين، إشعارات دائنة).
    """
    opening = round2(customer_balance(conn, customer_id, before=d_from))
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
            "credit": float(r["amount"] or 0), "kind": "receipt",
        })
    # إشعارات الدائن والمدين — مدين يزيد المستحق، دائن يحسمه
    for n in _rows(
        conn,
        "SELECT id, number, note_type, date, amount, vat_rate, reason "
        "FROM credit_debit_notes WHERE customer_id=? "
        "AND date >= ? AND date <= ? ORDER BY date, id",
        (customer_id, d_from, d_to),
    ):
        total = note_total(n["amount"], n["vat_rate"])
        is_debit = n["note_type"] == "debit"
        rows.append({
            "date": n["date"],
            "doc": (("إشعار مدين " if is_debit else "إشعار دائن ")
                    + voucher_number_label("DN" if is_debit else "CN", n["number"])),
            "desc": n["reason"] or ("مبلغ إضافي على العميل" if is_debit
                                    else "تخفيض أو حسم للعميل"),
            "debit": total if is_debit else 0.0,
            "credit": 0.0 if is_debit else total,
            "kind": "note_debit" if is_debit else "note_credit",
        })
    order = {"invoice": 0, "note_debit": 1, "note_credit": 1, "receipt": 2}
    rows.sort(key=lambda x: (x["date"], order.get(x["kind"], 3)))
    balance = opening
    for r in rows:
        balance = round2(balance + r["debit"] - r["credit"])
        r["balance"] = balance
    return {
        "opening": opening,
        "rows": rows,
        "closing": round2(balance),
        "invoiced": round2(sum(r["debit"] for r in rows if r["kind"] == "invoice")),
        "collected": round2(sum(r["credit"] for r in rows if r["kind"] == "receipt")),
        "notes_debit": round2(sum(r["debit"] for r in rows if r["kind"] == "note_debit")),
        "notes_credit": round2(sum(r["credit"] for r in rows if r["kind"] == "note_credit")),
    }


def customer_allocations(conn, customer_id: int) -> dict:
    """تخصيص تحصيلات العميل على فواتيره بالأقدمية (FIFO).

    للعرض في كشف الحساب الموسّع: لكل فاتورة المسدَّد والمتبقي،
    والدفعات غير المخصَّصة (زيادة عن قيمة الفواتير).
    """
    invoices = []
    for r in _rows(
        conn,
        "SELECT id, number, date FROM invoices WHERE customer_id=? ORDER BY date, id",
        (customer_id,),
    ):
        invoices.append({
            "invoice_id": r["id"], "number": r["number"], "date": r["date"],
            "total": round2(invoice_totals(conn, r["id"])["customer_total"]),
            "paid": 0.0,
        })
    opening = float(_scalar(
        conn, "SELECT opening_balance FROM customers WHERE id=?", (customer_id,)))
    paid_total = float(_scalar(
        conn,
        "SELECT COALESCE(SUM(amount),0) FROM receipt_vouchers "
        "WHERE voucher_type='customer' AND customer_id=?", (customer_id,)))
    note_effect = sum(
        note_total(n["amount"], n["vat_rate"]) * (1 if n["note_type"] == "debit" else -1)
        for n in _rows(
            conn, "SELECT note_type, amount, vat_rate FROM credit_debit_notes "
                  "WHERE customer_id=?", (customer_id,)))
    remaining = max(0.0, paid_total + min(0.0, opening) - min(0.0, note_effect))
    by_receipt: list[dict] = []
    for inv in invoices:
        if remaining <= 0:
            break
        used = min(remaining, inv["total"])
        inv["paid"] = round2(used)
        remaining = round2(remaining - used)
        by_receipt.append({**inv, "remaining": round2(inv["total"] - used)})
    for inv in invoices:
        if inv["id"] not in {b["invoice_id"] for b in by_receipt}:
            by_receipt.append({**inv, "remaining": round2(inv["total"])})
    by_receipt.sort(key=lambda x: (x["date"], x["number"]))
    return {
        "by_invoice": by_receipt,
        "unallocated": round2(max(0.0, remaining)),
        "total": round2(sum(i["total"] for i in invoices)),
        "paid": round2(sum(i["paid"] for i in invoices)),
        "remaining": round2(sum(i["remaining"] for i in by_receipt)),
    }


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
        p = trip_profit(conn, r["id"], d_from, d_to)
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
def employee_deductions(conn, employee_id: int, include_settled: bool = True) -> list[dict]:
    """بنود الخصومات المسجلة على الموظف مع المسدَّد والمتبقي من كل بند."""
    out = []
    for r in _rows(
        conn,
        "SELECT * FROM employee_deductions WHERE employee_id=? ORDER BY date, id",
        (employee_id,),
    ):
        settled = round2(_scalar(
            conn,
            "SELECT COALESCE(SUM(amount),0) FROM deduction_settlements "
            "WHERE employee_deduction_id=?", (r["id"],)))
        remaining = round2(float(r["amount"] or 0) - settled)
        if not include_settled and remaining <= 0.009:
            continue
        out.append({**dict(r), "settled": settled, "remaining": remaining,
                    "status": ("closed" if remaining <= 0.009
                               else ("partial" if settled > 0 else "open"))})
    return out


def employee_statement(conn, employee_id: int, d_from=None, d_to=None) -> dict:
    """الرواتب + سجل السلف وتسوياتها + بنود الخصومات + بدلات التريب.

    مطابق لـ employeeStatement في نسخة الويب (يضيف قسم الخصومات المُتتبَّعة).
    """
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
        d = dict(r)
        d["settlements"] = [
            dict(x) for x in _rows(
                conn,
                "SELECT s.amount, s.payroll_id, p.date AS pdate, p.number AS pnum, "
                "p.period_year, p.period_month "
                "FROM advance_settlements s JOIN payrolls p ON p.id=s.payroll_id "
                "WHERE s.payroll_id=? ORDER BY p.date", (r["id"],))]
        d["deduction_settlements"] = [
            dict(x) for x in _rows(
                conn,
                "SELECT s.amount, s.employee_deduction_id, d.number AS dnum, "
                "d.date AS ddate, d.reason AS dreason "
                "FROM deduction_settlements s "
                "JOIN employee_deductions d ON d.id=s.employee_deduction_id "
                "WHERE s.payroll_id=? ORDER BY d.date", (r["id"],))]
        salaries.append(d)

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
            "settled": round2(settled),
            "remaining": round2(float(r["amount"] or 0) - settled),
            "settlements": [dict(x) for x in settlements],
        })

    # بنود الخصومات المُتتبَّعة وتسوياتها في المسيرات
    deductions = []
    for d in employee_deductions(conn, employee_id):
        if d_from and d["date"] < d_from:
            continue
        if d_to and d["date"] > d_to:
            continue
        d["settlements"] = [
            dict(x) for x in _rows(
                conn,
                "SELECT s.amount, s.payroll_id, p.date AS pdate, p.number AS pnum "
                "FROM deduction_settlements s JOIN payrolls p ON p.id=s.payroll_id "
                "WHERE s.employee_deduction_id=? ORDER BY p.date", (d["id"],))]
        deductions.append(d)

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
            "WHERE trip_id=? AND expense_type='trip' AND source<>'customer'",
            (r["id"],),
        )
        # مصروف من عهدة السائق = مبلغ مقيد عليه بلا تحريك خزينة
        driver_owed = _scalar(
            conn,
            "SELECT COALESCE(SUM(amount),0) FROM trip_expenses "
            "WHERE trip_id=? AND source='driver'",
            (r["id"],),
        )
        allowances.append({
            **dict(r), "trip_allowance": round2(trip_pay),
            "driver_owed": round2(driver_owed),
            "route": f"{r['from_loc'] or '—'} ← {r['to_loc'] or '—'}",
        })

    totals = {
        "salaries_net": round2(sum(s["net_salary"] for s in salaries)),
        "salaries_additions": round2(sum(s["additions"] for s in salaries)),
        "salaries_deductions": round2(
            sum(float(s.get("advance_deduction") or 0)
                + float(s.get("deduction_deduction") or 0)
                + float(s.get("other_deductions") or 0) for s in salaries)),
        "advances_total": round2(sum(a["amount"] for a in advances)),
        "advances_remaining": round2(sum(a["remaining"] for a in advances)),
        "deductions_total": round2(sum(d["amount"] for d in deductions)),
        "deductions_remaining": round2(sum(d["remaining"] for d in deductions)),
        "allowances_total": round2(sum(a["trip_allowance"] for a in allowances)),
        "driver_owed_total": round2(sum(a["driver_owed"] for a in allowances)),
    }
    return {"salaries": salaries, "advances": advances,
            "deductions": deductions, "allowances": allowances,
            "totals": totals}


def vehicle_report(conn, d_from=None, d_to=None, vehicle_id=None) -> list[dict]:
    """إيرادات السيارة − مصروفات رحلاتها − صيانتها − مشترياتها = صافي الربحية."""
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
        # مشتريات مرتبطة بالسيارة (صيانة/قطع/إطارات) — صافي قبل الضريبة
        purchases = 0.0
        for row in _rows(
            conn,
            f"SELECT id, vat_included FROM purchase_invoices "
            f"WHERE vehicle_id=? {pay_cond}",
            [v["id"]] + pay_params,
        ):
            purchases += purchase_net(conn, row["id"], bool(row["vat_included"]))
        out.append({
            "vehicle_id": v["id"], "code": v["code"], "plate": v["plate_number"],
            "vtype": v["vehicle_type"], "trips": int(trips_count),
            "revenue": round2(revenue), "direct": round2(direct),
            "maintenance": round2(maintenance), "purchases": round2(purchases),
            "net": round2(revenue - direct - maintenance - purchases),
        })
    return out


# ---------------------------------------------------------------------------
# تقرير 5: الأرباح والخسائر الشامل
# ---------------------------------------------------------------------------
def pnl_report(conn, d_from=None, d_to=None) -> dict:
    """الأرباح والخسائر الشامل — مطابق لبندٍ ببندٍ لـ pnlReport في نسخة الويب.

    الإيرادات = إيرادات النقلات (قبل الضريبة) + المصروفات التي يتحمّلها العميل
                 + الإيرادات الأخرى ± الإشعارات الدائنة/المدينة.
    المصروفات = مباشرة + سندات رحلات يدوية + رواتب + سلف + صيانة + عامة
                + مشتريات (بكل تصنيفاتها) + مسحوبات المالك.
    الضريبة المحصَّلة تُعرض معلومةً منفصلة (vat_collected) ولا تدخل الإيراد.
    """
    def period(table: str = "") -> str:
        prefix = f"{table}." if table else ""
        c = ""
        if d_from:
            c += f" AND {prefix}date >= ?"
        if d_to:
            c += f" AND {prefix}date <= ?"
        return c

    def period_cols() -> list:
        p = []
        if d_from:
            p.append(d_from)
        if d_to:
            p.append(d_to)
        return p

    # إيرادات النقلات (قبل الضريبة) + ضريبة القيمة المضافة المحصلة في الفترة
    transport = 0.0
    vat_collected = 0.0
    direct = 0.0
    invoices = _rows(
        conn,
        f"SELECT id, vat_rate FROM invoices i WHERE 1=1 {period('i')}",
        period_cols(),
    )
    if invoices:
        vat_map = {r["id"]: float(r["vat_rate"] or 0) for r in invoices}
        inv_ids = list(vat_map)
        marks = ",".join("?" * len(inv_ids))
        sub_by_inv: dict[int, float] = dict.fromkeys(inv_ids, 0.0)
        for t in _rows(
            conn,
            f"SELECT invoice_id, price FROM invoice_trips WHERE invoice_id IN ({marks})",
            inv_ids,
        ):
            sub_by_inv[t["invoice_id"]] += float(t["price"] or 0)
        # المصروف الذي يتحمّله العميل إيراد إضافي (يدخل وعاء الضريبة)
        for e in _rows(
            conn,
            f"SELECT t.invoice_id, e.amount, e.source FROM trip_expenses e "
            f"JOIN invoice_trips t ON t.id = e.trip_id WHERE t.invoice_id IN ({marks})",
            inv_ids,
        ):
            if (e["source"] or "cash") == "customer":
                sub_by_inv[e["invoice_id"]] += float(e["amount"] or 0)
            else:
                direct += float(e["amount"] or 0)
        for iid, sub in sub_by_inv.items():
            transport += sub
            vat_collected += round2((sub * vat_map[iid]) / 100.0)

    other_rev = _scalar(
        conn,
        f"SELECT COALESCE(SUM(amount),0) FROM receipt_vouchers "
        f"WHERE voucher_type='other' AND 1=1 {period('receipt_vouchers')}",
        period_cols(),
    )
    salaries = _scalar(
        conn,
        f"SELECT COALESCE(SUM(net_salary),0) FROM payrolls "
        f"WHERE 1=1 {period('payrolls')}",
        period_cols(),
    )

    def payments(voucher_type: str) -> float:
        return _scalar(
            conn,
            f"SELECT COALESCE(SUM(amount),0) FROM payment_vouchers "
            f"WHERE voucher_type=? AND source_expense_id IS NULL "
            f"AND 1=1 {period('payment_vouchers')}",
            [voucher_type] + period_cols(),
        )

    advances = payments("advance")
    maintenance = payments("vehicle")
    general = payments("general")
    owner_withdrawals = payments("owner")
    # سندات الرحلات اليدوية فقط — التلقائية محتسبة ضمن المصروف المباشر أعلاه
    trip_payments = _scalar(
        conn,
        f"SELECT COALESCE(SUM(amount),0) FROM payment_vouchers "
        f"WHERE voucher_type='trip' AND source_expense_id IS NULL "
        f"AND 1=1 {period('payment_vouchers')}",
        period_cols(),
    )

    # فواتير المشتريات تُثبت كمصروف عند تاريخ الفاتورة (نقدية كانت أو آجلة)
    from ..utils.fmt import PURCHASE_EXPENSE_CATEGORIES
    purchase_by_category = {k: 0.0 for k in PURCHASE_EXPENSE_CATEGORIES}
    for row in _rows(
        conn,
        f"SELECT id, expense_category, vat_included FROM purchase_invoices "
        f"WHERE 1=1 {period('purchase_invoices')}",
        period_cols(),
    ):
        key = row["expense_category"] or "other"
        if key not in purchase_by_category:
            key = "other"
        purchase_by_category[key] = round2(
            purchase_by_category[key]
            + purchase_net(conn, row["id"], bool(row["vat_included"])))
    purchase_expenses = round2(sum(purchase_by_category.values()))

    # إشعارات المدين والدائن: مدين = إيراد إضافي، دائن = حسم/تخفيض إيراد
    notes_debit = notes_credit = 0.0
    for n in _rows(
        conn,
        f"SELECT note_type, amount, vat_rate FROM credit_debit_notes "
        f"WHERE 1=1 {period('credit_debit_notes')}",
        period_cols(),
    ):
        total = note_total(n["amount"], n["vat_rate"])
        if n["note_type"] == "debit":
            notes_debit += total
        else:
            notes_credit += total
    note_net = round2(notes_debit - notes_credit)

    total_rev = round2(transport + other_rev + note_net)
    total_exp = round2(direct + trip_payments + salaries + advances + maintenance
                       + general + purchase_expenses + owner_withdrawals)
    out = {
        "transport_revenue": round2(transport),
        "other_revenue": round2(other_rev),
        "credit_notes_adjust": round2(-notes_credit),
        "debit_notes_adjust": round2(notes_debit),
        "notes_adjust": note_net,
        "total_revenue": total_rev,
        "direct_expenses": round2(direct),
        "trip_payments": round2(trip_payments),
        "salaries": round2(salaries),
        "advances": round2(advances),
        "maintenance": round2(maintenance),
        "general_expenses": round2(general),
        "purchase_expenses": purchase_expenses,
        "owner_withdrawals": round2(owner_withdrawals),
        "total_expenses": total_exp,
        "net": round2(total_rev - total_exp),
        "vat_collected": round2(vat_collected),
    }
    for key, value in purchase_by_category.items():
        out[f"purchase_{key}"] = round2(value)
    return out


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
         "balance": round2(account_balance(conn, "bank", r["id"]))}
        for r in _rows(conn, "SELECT * FROM banks ORDER BY code")
    ]
    suppliers = [
        {"code": r["code"], "name": r["name"],
         "balance": round2(supplier_balance(conn, r["id"]))}
        for r in _rows(conn, "SELECT * FROM suppliers ORDER BY code")
    ]
    return {
        "created_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "year": y["year"], "date_from": y["date_from"], "date_to": y["date_to"],
        "customers": customers, "cashboxes": cashboxes, "banks": banks,
        "suppliers": suppliers,
        "pnl": {k: round(v, 2) for k, v in pnl.items()},
    }

# ---------------------------------------------------------------------------
# أرشيف السلفيات والخصومات مع تفصيل تسوياتها
# (مطابق لـ advanceArchive / deductionArchive في نسخة الويب)
# ---------------------------------------------------------------------------
def _archive(conn, source_sql: str, params: tuple, amount_key: str,
             settle_sql: str) -> list[dict]:
    out: list[dict] = []
    for row in _rows(conn, source_sql, params):
        d = dict(row)
        settlements = []
        for st in _rows(conn, settle_sql, (d["id"],)):
            settlements.append({
                "payroll_id": st["payroll_id"],
                "payroll_number": int(st["number"] or 0),
                "payroll_date": st["date"] or "",
                "period_year": int(st["period_year"] or 0),
                "period_month": int(st["period_month"] or 0),
                "period_label": (fmt.period_label(int(st["period_year"]),
                                                  int(st["period_month"]))
                                 if st["period_year"] else "—"),
                "amount": float(st["amount"] or 0),
            })
        settlements.sort(key=lambda x: x["payroll_date"])
        settled = round2(sum(x["amount"] for x in settlements))
        d["settlements"] = settlements
        d["settled"] = settled
        d["remaining"] = round2(float(d.get(amount_key) or 0) - settled)
        d["status"] = ("settled" if d["remaining"] <= 0.009
                       else ("partial" if settled > 0 else "open"))
        out.append(d)
    return out


def advance_archive(conn, employee_id: int | None = None) -> list[dict]:
    """كل سلف الموظف (أو الكل) مع تفصيل أي مسيرة سدّدت كم ومتى."""
    sql = ("SELECT * FROM payment_vouchers WHERE voucher_type='advance' ")
    params: tuple = ()
    if employee_id:
        sql += "AND employee_id=? "
        params = (employee_id,)
    sql += "ORDER BY date, id"
    return _archive(
        conn, sql, params, "amount",
        "SELECT s.amount, s.payroll_id, p.number, p.date, p.period_year, "
        "p.period_month FROM advance_settlements s "
        "LEFT JOIN payrolls p ON p.id = s.payroll_id "
        "WHERE s.payment_voucher_id=? ORDER BY s.payroll_id")


def deduction_archive(conn, employee_id: int | None = None) -> list[dict]:
    """كل خصومات الموظف (أو الكل) مع تفصيل تسوياتها في المسيرات."""
    sql = "SELECT * FROM employee_deductions WHERE 1=1 "
    params: tuple = ()
    if employee_id:
        sql += "AND employee_id=? "
        params = (employee_id,)
    sql += "ORDER BY date, id"
    return _archive(
        conn, sql, params, "amount",
        "SELECT s.amount, s.payroll_id, p.number, p.date, p.period_year, "
        "p.period_month FROM deduction_settlements s "
        "LEFT JOIN payrolls p ON p.id = s.payroll_id "
        "WHERE s.employee_deduction_id=? ORDER BY s.payroll_id")


def _archive_totals(rows: list[dict]) -> dict:
    return {
        "total": round2(sum(float(r.get("amount") or 0) for r in rows)),
        "settled": round2(sum(float(r.get("settled") or 0) for r in rows)),
        "remaining": round2(sum(float(r.get("remaining") or 0) for r in rows)),
        "open_count": sum(1 for r in rows if r.get("status") != "settled"),
    }


def advance_archive_totals(rows: list[dict]) -> dict:
    return _archive_totals(rows)


def deduction_archive_totals(rows: list[dict]) -> dict:
    return _archive_totals(rows)
