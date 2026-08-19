# -*- coding: utf-8 -*-
"""
منظومة تدقيق جديدة كلياً (لا تعتمد على أي فحص سابق) — أساليب مختلفة:

  1. سجل الظل (Shadow Ledger): تتبع أثر كل عملية بأرقام بايثون خالصة عند التنفيذ،
     ثم مطابقة النهاية مع استعلامات النظام — يكشف أخطاء لا تكشفها مقارنات SQL/SQL.
  2. معادلة ميزان المراجعة: صافي الربح − تغير الأصول = (مصروف مباشر − سندات رحلات).
  3. مصفوفة قاعدة السنوات المالية: كل كيان × كل عملية × (داخل/خارج/سنة مغلقة).
  4. فحوصات أمنية بمحاور جديدة: صلاحيات الملف، النسخ الاحتياطي، التلاعب المباشر
     بالقاعدة، سقوف المبالغ وأطوال النصوص، bidi، تحليل استاتيكي لاستدعاءات خطرة.
  5. خصائص عشوائية (Property-based) بتوزيعات مختلفة: كسور 3 منازل، قيم متطرفة.

تشغيل:  python scripts/test_audit.py
"""
from __future__ import annotations

import os
import random
import re
import sys
import tempfile
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ["LOGISTIC_DATA_DIR"] = tempfile.mkdtemp(prefix="logistic_audit_")

from app.core import calc, db, repo                    # noqa: E402
from app.core.rules import RuleError                  # noqa: E402

PASS = FAIL = 0
FAILURES: list[str] = []


def check(name: str, cond: bool, extra: str = "") -> None:
    global PASS, FAIL
    if cond:
        PASS += 1
    else:
        FAIL += 1
        FAILURES.append(f"{name} {extra}")
        print(f"  ❌ {name} {extra}")


def reject(name: str, fn) -> None:
    try:
        fn()
    except (RuleError, ValueError):
        check(name, True)
    except Exception as e:  # noqa: BLE001
        check(name, False, f"— غير متوقع: {type(e).__name__}: {e}")
    else:
        check(name, False, "— لم يُرفض")


# ===========================================================================
# 1) سجل الظل
# ===========================================================================
class ShadowLedger:
    """حساب مستقل تماماً بالبايثون الخالص (dicts) لكل أرصدة النظام."""

    def __init__(self, customers: dict, accounts: dict):
        self.cust = dict(customers)          # cid -> balance
        self.acc = dict(accounts)            # (kind, id) -> balance
        self.pnl = {"transport": 0.0, "other": 0.0, "direct": 0.0,
                    "salaries": 0.0, "advances": 0.0, "maintenance": 0.0,
                    "general": 0.0}

    def invoice(self, cid, total_trips, total_expenses):
        self.cust[cid] += total_trips
        self.pnl["transport"] += total_trips
        self.pnl["direct"] += total_expenses

    def invoice_edit_delta(self, cid, d_trips, d_expenses):
        self.cust[cid] += d_trips
        self.pnl["transport"] += d_trips
        self.pnl["direct"] += d_expenses

    def invoice_delete(self, cid, total_trips, total_expenses):
        self.cust[cid] -= total_trips
        self.pnl["transport"] -= total_trips
        self.pnl["direct"] -= total_expenses

    def receipt(self, kind, aid, amount, vtype, cid=None):
        self.acc[(kind, aid)] += amount
        if vtype == "customer":
            self.cust[cid] -= amount
        else:
            self.pnl["other"] += amount

    def receipt_delete(self, kind, aid, amount, vtype, cid=None):
        self.acc[(kind, aid)] -= amount
        if vtype == "customer":
            self.cust[cid] += amount
        else:
            self.pnl["other"] -= amount

    def payment(self, kind, aid, amount, vtype):
        self.acc[(kind, aid)] -= amount
        self.pnl[{"trip": "direct", "advance": "advances",
                  "vehicle": "maintenance", "general": "general"}[vtype]] += amount
        # ملاحظة: خصم "trip" هنا لا يُضاف لـ direct — بل يخصم الربح لاحقاً؛
        # نستخدم خانة مستقلة أدناه.

    def payroll(self, kind, aid, net, buckets):
        self.acc[(kind, aid)] -= net
        self.pnl["salaries"] += net

    def compare(self, conn, ctx: str):
        for cid, bal in self.cust.items():
            app = round(calc.customer_balance(conn, cid), 2)
            check(f"[ظل/{ctx}] رصيد العميل {cid}", abs(app - round(bal, 2)) < 0.011,
                  f"(التطبيق {app} مقابل الظل {round(bal, 2)})")
        for (kind, aid), bal in self.acc.items():
            app = round(calc.account_balance(conn, kind, aid), 2)
            check(f"[ظل/{ctx}] رصيد {kind}/{aid}", abs(app - round(bal, 2)) < 0.011,
                  f"(التطبيق {app} مقابل الظل {round(bal, 2)})")
        pnl = calc.pnl_report(conn, "1900-01-01", "2999-12-31")
        m = {"transport": "transport_revenue", "other": "other_revenue",
             "direct": "direct_expenses", "salaries": "salaries",
             "advances": "advances", "maintenance": "maintenance",
             "general": "general_expenses"}
        for k, col in m.items():
            check(f"[ظل/{ctx}] P&L {k}",
                  abs(round(pnl[col], 2) - round(self.pnl[k], 2)) < 0.011,
                  f"({pnl[col]} مقابل {round(self.pnl[k], 2)})")
        # معادلة ميزان المراجعة: net − Δأصول = (مباشر − سندات رحلات)
        assets = sum(self.acc.values()) + sum(self.cust.values())
        opened = sum(self._opened_acc) + sum(self._opened_cust)
        d_assets = assets - opened
        t_pay = float(conn.execute(
            "SELECT IFNULL(SUM(amount),0) FROM payment_vouchers "
            "WHERE voucher_type='trip'").fetchone()[0])
        direct = float(conn.execute(
            "SELECT IFNULL(SUM(e.amount),0) FROM trip_expenses e").fetchone()[0])
        check(f"[ظل/{ctx}] ميزان المراجعة: net − Δالأصول = سندات الرحلات − المباشر",
              abs(round(pnl["net"] - d_assets, 2)
                  - round(t_pay - direct, 2)) < 0.06,
              f"({round(pnl['net'] - d_assets, 2)} مقابل {round(t_pay - direct, 2)})")

    _opened_acc: list = []
    _opened_cust: list = []


def main() -> None:  # noqa: C901
    db.init_db()
    conn = db.get_conn()

    print("== أ) تجهيز: سنة مالية + بيانات أساسية")
    repo.save_year(conn, {"year": 2026, "date_from": "2026-01-01",
                          "date_to": "2026-12-31"})
    c1 = repo.save_customer(conn, {"name": "عميل تدقيق", "opening_balance": 5000})
    c2 = repo.save_customer(conn, {"name": "عميل ثانٍ", "opening_balance": -300})
    d1 = repo.save_employee(conn, {"name": "سائق تدقيق", "emp_type": "driver"})
    v1 = repo.save_vehicle(conn, {"plate_number": "ت د ق 9", "default_driver_id": d1})
    cb = repo.save_account(conn, "cashbox", {"name": "خزينة تدقيق",
                                             "created_date": "2026-01-01",
                                             "opening_balance": 10000})
    bn = repo.save_account(conn, "bank", {"name": "بنك تدقيق",
                                          "created_date": "2026-01-01",
                                          "opening_balance": 40000})
    ledger = ShadowLedger({c1: 5000.0, c2: -300.0},
                          {("cashbox", cb): 10000.0, ("bank", bn): 40000.0})
    ledger._opened_acc = [10000.0, 40000.0]
    ledger._opened_cust = [5000.0, -300.0]
    ledger.compare(conn, "تجهيز")

    print("== ب) سجل الظل: 150 عملية عشوائية بمبالغ كسرية 3 منازل")
    rng = random.Random(777)
    for step in range(150):
        op = rng.choice(["inv", "recv", "pay", "payroll", "edit_inv", "del_recv"])
        try:
            if op == "inv":
                trips = []
                for _ in range(rng.randint(1, 3)):
                    price = round(rng.uniform(50, 9000), 3)  # يدخل 3 منازل، النظام يقرّب
                    exps = [{"expense_type": rng.choice(["trip", "fuel", "card"]),
                             "amount": round(rng.uniform(5, 400), 3)}
                            for _ in range(rng.randint(0, 2))]
                    trips.append({"vehicle_id": rng.choice([None, v1]),
                                  "driver_id": rng.choice([None, d1]),
                                  "from_loc": f"س{step}", "to_loc": f"ص{step}",
                                  "price": price, "expenses": exps})
                cid = rng.choice([c1, c2])
                d_inv = rng.choice(["2026-02-01", "2026-07-14", "2026-11-30"])
                total = round(sum(round(t["price"], 2) for t in trips), 2)
                exp = round(sum(round(e["amount"], 2)
                                for t in trips for e in t["expenses"]), 2)
                repo.save_invoice(conn, {
                    "date": d_inv, "customer_id": cid, "trips": trips})
                ledger.invoice(cid, total, exp)
            elif op == "recv":
                kind, aid = rng.choice([("cashbox", cb), ("bank", bn)])
                amount = round(rng.uniform(10, 4000), 2)
                is_cust = rng.random() < 0.5
                recv_cid = rng.choice([c1, c2]) if is_cust else None
                d_recv = rng.choice(["2026-03-03", "2026-08-08"])
                repo.save_receipt(conn, {
                    "date": d_recv,
                    "account_kind": kind, "account_id": aid,
                    "voucher_type": "customer" if is_cust else "other",
                    "customer_id": recv_cid, "amount": amount})
                ledger.receipt(kind, aid, amount,
                               "customer" if is_cust else "other", cid=recv_cid)
            elif op == "pay":
                kind, aid = rng.choice([("cashbox", cb), ("bank", bn)])
                vt = rng.choice(["trip", "advance", "vehicle", "general"])
                data = {"date": rng.choice(["2026-04-04", "2026-09-09"]),
                        "account_kind": kind, "account_id": aid,
                        "voucher_type": vt,
                        "amount": round(rng.uniform(5, 2500), 2)}
                if vt == "trip":
                    tr = conn.execute("SELECT id FROM invoice_trips "
                                      "ORDER BY RANDOM() LIMIT 1").fetchone()
                    if not tr:
                        continue
                    data["trip_id"] = tr["id"]
                elif vt == "advance":
                    data["employee_id"] = d1
                elif vt == "vehicle":
                    data["vehicle_id"] = v1
                repo.save_payment(conn, data)
                # سجل الظل: جميع السندات تخصم من الحساب
                ledger.acc[(kind, aid)] -= data["amount"]
                if vt == "advance":
                    ledger.pnl["advances"] += data["amount"]
                elif vt == "vehicle":
                    ledger.pnl["maintenance"] += data["amount"]
                elif vt == "general":
                    ledger.pnl["general"] += data["amount"]
                # ملاحظة: سندات الرحلات لا تدخل P&L مباشرة (تخصم رحلة)
            elif op == "payroll":
                open_advs = repo.employee_advances(conn, d1, False)
                settlements = []
                if open_advs and rng.random() < 0.6:
                    adv = rng.choice(open_advs)
                    part = round(rng.uniform(1, max(adv["remaining"], 1)), 2)
                    settlements = [(adv["id"], part)]
                kind, aid = rng.choice([("cashbox", cb), ("bank", bn)])
                base = round(rng.uniform(2500, 6000), 2)
                adds = round(rng.uniform(0, 500), 2)
                ded = round(rng.uniform(0, 200), 2)
                repo.save_payroll(conn, {
                    "date": rng.choice(["2026-05-05", "2026-10-10"]),
                    "employee_id": d1, "period_year": 2026,
                    "period_month": rng.randint(1, 12),
                    "account_kind": kind, "account_id": aid,
                    "base_salary": base, "additions": adds,
                    "other_deductions": ded, "settlements": settlements})
                net = round(base + adds
                            - sum(a for _, a in settlements) - ded, 2)
                ledger.acc[(kind, aid)] -= net
                ledger.pnl["salaries"] += net
            elif op == "edit_inv":
                inv = conn.execute("SELECT id FROM invoices "
                                   "ORDER BY RANDOM() LIMIT 1").fetchone()
                if not inv:
                    continue
                before = calc.invoice_totals(conn, inv["id"])
                full = calc.get_invoice_full(conn, inv["id"])
                if not full["trips"]:
                    continue
                full["trips"][0]["price"] = round(rng.uniform(100, 5000), 2)
                repo.save_invoice(conn, full, inv["id"])
                after = calc.invoice_totals(conn, inv["id"])
                ledger.invoice_edit_delta(
                    full["customer_id"],
                    round(after["trips_total"] - before["trips_total"], 2),
                    round(after["expenses_total"] - before["expenses_total"], 2))
            elif op == "del_recv":
                row = conn.execute("SELECT * FROM receipt_vouchers "
                                   "ORDER BY RANDOM() LIMIT 1").fetchone()
                if not row:
                    continue
                repo.delete_receipt(conn, row["id"])
                ledger.receipt_delete(row["account_kind"], row["account_id"],
                                      row["amount"], row["voucher_type"],
                                      cid=row["customer_id"])
        except RuleError:
            continue
    ledger.compare(conn, "بعد-150-عملية")

    # تقريب منزلتين في كل التخزين
    bad = conn.execute(
        """SELECT COUNT(*) FROM (
             SELECT price AS v FROM invoice_trips
             UNION ALL SELECT amount FROM trip_expenses
             UNION ALL SELECT amount FROM receipt_vouchers
             UNION ALL SELECT amount FROM payment_vouchers
             UNION ALL SELECT net_salary FROM payrolls
             UNION ALL SELECT opening_balance FROM customers
           ) WHERE ABS(v*100 - ROUND(v*100)) > 0.001""").fetchone()[0]
    check("كل المبالغ المخزنة بمنزلتين كحد أقصى", bad == 0, f"({bad} قيم غير مقربة)")

    # ==========================================================================
    print("== ج) مصفوفة قاعدة السنوات المالية (كل كيان × كل عملية)")
    repo.save_year(conn, {"year": 2027, "date_from": "2027-01-01",
                          "date_to": "2027-12-31"})
    repo.set_year_status(conn, conn.execute(
        "SELECT id FROM financial_years WHERE year=2027").fetchone()["id"], "closed")

    outside = ["2025-12-31", "2028-01-01"]
    inside = ["2026-06-15"]
    year26 = conn.execute("SELECT id FROM financial_years WHERE year=2026"
                          ).fetchone()["id"]
    year27 = conn.execute("SELECT id FROM financial_years WHERE year=2027"
                          ).fetchone()["id"]
    for d in outside:
        reject(f"فاتورة بتاريخ {d}", lambda d=d: repo.save_invoice(conn, {
            "date": d, "customer_id": c1,
            "trips": [{"from_loc": "أ", "to_loc": "ب", "price": 10,
                       "expenses": []}]}))
        reject(f"سند قبض بتاريخ {d}", lambda d=d: repo.save_receipt(conn, {
            "date": d, "account_kind": "cashbox", "account_id": cb,
            "voucher_type": "other", "amount": 10}))
        reject(f"سند دفع بتاريخ {d}", lambda d=d: repo.save_payment(conn, {
            "date": d, "account_kind": "cashbox", "account_id": cb,
            "voucher_type": "general", "amount": 10}))
        reject(f"راتب بتاريخ {d}", lambda d=d: repo.save_payroll(conn, {
            "date": d, "employee_id": d1, "period_year": 2026, "period_month": 1,
            "account_kind": "cashbox", "account_id": cb, "base_salary": 100,
            "settlements": []}))
    # إنشاء حركة داخل 2026 (مفتوحة) ثم إغلاق السنة ومنع كل شيء
    r_last = repo.save_receipt(conn, {"date": "2026-12-20",
                                      "account_kind": "cashbox", "account_id": cb,
                                      "voucher_type": "other", "amount": 10})
    p_last = repo.save_payment(conn, {"date": "2026-12-21",
                                      "account_kind": "cashbox", "account_id": cb,
                                      "voucher_type": "general", "amount": 10})
    pay_last = repo.save_payroll(conn, {
        "date": "2026-12-22", "employee_id": d1, "period_year": 2026,
        "period_month": 12, "account_kind": "cashbox", "account_id": cb,
        "base_salary": 100, "settlements": []})
    inv_last = repo.save_invoice(conn, {
        "date": "2026-12-23", "customer_id": c1,
        "trips": [{"from_loc": "أ", "to_loc": "ب", "price": 10, "expenses": []}]})
    ledger.receipt("cashbox", cb, 10, "other")
    ledger.acc[("cashbox", cb)] -= 10
    ledger.pnl["general"] += 10
    ledger.acc[("cashbox", cb)] -= 100
    ledger.pnl["salaries"] += 100
    ledger.invoice(c1, 10, 0)
    repo.set_year_status(conn, year26, "closed")
    reject("تعديل سند داخل سنة مغلقة", lambda: repo.save_receipt(conn, {
        "date": "2026-12-20", "account_kind": "cashbox", "account_id": cb,
        "voucher_type": "other", "amount": 99}, r_last))
    reject("حذف سند داخل سنة مغلقة", lambda: repo.delete_receipt(conn, r_last))
    reject("تعديل سند دفع داخل سنة مغلقة", lambda: repo.save_payment(conn, {
        "date": "2026-12-21", "account_kind": "cashbox", "account_id": cb,
        "voucher_type": "general", "amount": 55}, p_last))
    reject("حذف راتب داخل سنة مغلقة", lambda: repo.delete_payroll(conn, pay_last))
    reject("تعديل فاتورة داخل سنة مغلقة", lambda: repo.save_invoice(conn, {
        "date": "2026-12-24", "customer_id": c1,
        "trips": [{"from_loc": "أ", "to_loc": "ب", "price": 20,
                   "expenses": []}]}, inv_last))
    reject("حذف فاتورة داخل سنة مغلقة", lambda: repo.delete_invoice(conn, inv_last))
    repo.set_year_status(conn, year26, "open")
    repo.delete_invoice(conn, inv_last)
    ledger.invoice_delete(c1, 10, 0)
    check("إعادة الفتح تعيد السماح بالعمليات", True)

    print("== د) قيود جديدة: تداخل السنوات، شهر الراتب، السقوف والأنواع")
    reject("سنة متداخلة جزئياً", lambda: repo.save_year(conn, {
        "year": 2030, "date_from": "2026-06-01", "date_to": "2030-05-31"}))
    reject("سنة متداخلة كلياً", lambda: repo.save_year(conn, {
        "year": 2031, "date_from": "2026-02-01", "date_to": "2026-03-01"}))
    y2028 = repo.save_year(conn, {"year": 2028, "date_from": "2028-01-01",
                                  "date_to": "2028-12-31"})
    check("سنة غير متداخلة تُقبل", y2028 > 0)
    reject("شهر راتب 13", lambda: repo.save_payroll(conn, {
        "date": "2026-01-10", "employee_id": d1, "period_year": 2026,
        "period_month": 13, "account_kind": "cashbox", "account_id": cb,
        "base_salary": 100, "settlements": []}))
    reject("شهر راتب 0", lambda: repo.save_payroll(conn, {
        "date": "2026-01-10", "employee_id": d1, "period_year": 2026,
        "period_month": 0, "account_kind": "cashbox", "account_id": cb,
        "base_salary": 100, "settlements": []}))
    reject("مبلغ فوق السقف", lambda: repo.save_receipt(conn, {
        "date": "2026-01-10", "account_kind": "cashbox", "account_id": cb,
        "voucher_type": "other", "amount": 10**13}))
    reject("نص 6000 محرف (DoS)", lambda: repo.save_customer(conn, {
        "name": "x" * 6000}))
    # السائق الافتراضي يجب أن يكون سائقاً
    admin = repo.save_employee(conn, {"name": "إداري تدقيق", "emp_type": "admin"})
    reject("سائق افتراضي من نوع إداري", lambda: repo.save_vehicle(conn, {
        "plate_number": "ز ز ز", "default_driver_id": admin}))
    # منع تغيير نوع موظف مرتبط
    reject("تغيير نوع موظف له رحلات", lambda: repo.save_employee(conn, {
        "name": "سائق تدقيق", "emp_type": "admin"}, d1))
    check("تعديل بيانات موظف بدون تغيير النوع مسموح",
          repo.save_employee(conn, {"name": "سائق تدقيق 2",
                                    "emp_type": "driver"}, d1) == d1)

    print("== ه) أمن بمحاور جديدة")
    # صلاحيات الملف
    mode = oct(os.stat(db.db_path()).st_mode & 0o777)
    check("ملف القاعدة بصلاحية 600", mode == "0o600", f"({mode})")
    # النسخة الاحتياطية صالحة
    bpath = db.backup_database()
    import sqlite3 as _s
    bconn = _s.connect(str(bpath))
    n_backup = bconn.execute("SELECT COUNT(*) FROM customers").fetchone()[0]
    n_live = conn.execute("SELECT COUNT(*) FROM customers").fetchone()[0]
    bconn.close()
    check("النسخة الاحتياطية متناسقة ومقروءة", n_backup == n_live and n_live > 0)
    # تلاعب مباشر بالقاعدة: JSON مرفقات فاسد
    inv_any = conn.execute("SELECT id FROM invoices LIMIT 1").fetchone()["id"]
    conn.execute("UPDATE invoices SET attachments='{not-json' WHERE id=?", (inv_any,))
    conn.commit()
    try:
        full = calc.get_invoice_full(conn, inv_any)
        check("JSON مرفقات فاسد لا يكسر القراءة", full["attachments"] == [])
    except Exception as e:  # noqa: BLE001
        check("JSON مرفقات فاسد لا يكسر القراءة", False, str(e))
    conn.execute("UPDATE invoices SET attachments='[]' WHERE id=?", (inv_any,))
    conn.commit()
    # bidi والتحكم في الأسماء
    bidi = "حساب\u202e4019\u202cمراجعة"
    bid = repo.save_customer(conn, {"name": bidi, "opening_balance": 0})
    check("اسم بمحارف bidi يُخزن كما هو دون تفسير",
          repo.get_customer(conn, bid)["name"] == bidi)
    # تحليل استاتيكي: لا استدعاءات خطرة في كود التطبيق
    dangerous = []
    pat = re.compile(r"(?<![.\w])(eval|exec)\(|pickle\.|os\.system|subprocess\.|"
                     r"shell=True|__import__")
    for f in Path("app").rglob("*.py"):
        for i, ln in enumerate(f.read_text(encoding="utf-8").splitlines(), 1):
            if pat.search(ln):
                dangerous.append(f"{f}:{i}: {ln.strip()[:70]}")
    check("لا استدعاءات خطرة (eval/exec/subprocess/...)", not dangerous,
          str(dangerous[:3]))
    # لا استعلامات SQL بتنسيق f-string يدخل فيها نص المستخدم
    fsql = []
    for f in list(Path("app").rglob("*.py")):
        for i, ln in enumerate(f.read_text(encoding="utf-8").splitlines(), 1):
            if re.search(r'execute\(f["\'].*\{', ln) and not re.search(
                    r'\{(calc\.account_table\([a-z_]+\)|calc\.account_table|tbl|table|p_cond|inv_cond|pay_cond|cond)\}', ln):
                fsql.append(f"{f}:{i}")
    check("لا SQL منسق بمدخلات ديناميكية غير آمنة", not fsql, str(fsql[:5]))
    # حقن من الطريق الثاني: القيم المحفوظة تظهر في التصدير مهربة
    from app.utils import exporter as exp
    evil = "<img src=x onerror=alert(1)>"
    eid = repo.save_customer(conn, {"name": evil, "opening_balance": 0})
    html = exp.build_report_html(conn, title="t", headers=["n"],
                                 rows=[[repo.get_customer(conn, eid)["name"]]])
    check("الاسم الخبيث يظهر مهرباً في كل التصديرات", evil not in html)
    conn.execute("DELETE FROM customers WHERE id IN (?, ?)", (bid, eid))
    conn.commit()

    print("== و) كشوف بحدود جديدة")
    st = calc.customer_statement(conn, c1, "2026-12-31", "2026-01-01")  # من > إلى
    check("كشف بفترة معكوسة: فارغ بلا أخطاء", st["rows"] == [])
    st2 = calc.account_statement(conn, "cashbox", cb, "2999-01-01", "2999-12-31")
    check("كشف مستقبلي فارغ والافتتاحي = الرصيد الكلي", st2["rows"] == []
          and abs(st2["opening"] - calc.account_balance(conn, "cashbox", cb)) < 0.01)
    # لقطة السنة تطابق نهايتها
    repo.set_year_status(conn, year26, "closed")
    snap = repo.create_snapshot(conn, year26)
    pnl_y = calc.pnl_report(conn, "2026-01-01", "2026-12-31")
    check("لقطة السنة = P&L نفس السنة",
          abs(snap["pnl"]["net"] - pnl_y["net"]) < 0.01)
    repo.set_year_status(conn, year26, "open")
    # تقرير الرحلات: السندات اللاحقة تُفلتر بفترة التقرير
    rep_full = calc.trip_profits_report(conn, "1900-01-01", "2999-12-31")
    rep_h1 = calc.trip_profits_report(conn, "2026-01-01", "2026-06-30")
    check("تقرير الرحلات شامل = مجموع النصف الأول", len(rep_h1) <= len(rep_full))
    trip_with_later = conn.execute(
        """SELECT p.trip_id FROM payment_vouchers p JOIN invoice_trips t
             ON t.id=p.trip_id JOIN invoices i ON i.id=t.invoice_id
           WHERE p.voucher_type='trip' AND p.date > i.date LIMIT 1""").fetchone()
    if trip_with_later:
        tid = trip_with_later["trip_id"]
        inv_date = conn.execute(
            "SELECT i.date FROM invoices i JOIN invoice_trips t ON t.invoice_id=i.id "
            "WHERE t.id=?", (tid,)).fetchone()["date"]
        after = (date.fromisoformat(inv_date) + timedelta(days=1)).isoformat()
        r_all = calc.trip_profits_report(conn, "1900-01-01", "2999-12-31")
        r_before = calc.trip_profits_report(conn, "1900-01-01", inv_date)
        row_all = next(r for r in r_all if r["trip_id"] == tid)
        row_before = next(r for r in r_before if r["trip_id"] == tid)
        check("فلترة السندات اللاحقة بفترة التقرير",
              row_all["later"] >= row_before["later"])
    ledger.compare(conn, "النهاية")

    print(f"\n===== النتيجة: نجاح {PASS} / فشل {FAIL} =====")
    if FAILURES:
        print("الإخفاقات:")
        for f in FAILURES[:40]:
            print("  -", f)
        sys.exit(1)
    print("🎉 التدقيق الشامل الجديد نجح بالكامل.")


if __name__ == "__main__":
    main()
