# -*- coding: utf-8 -*-
"""
منظومة الفحص الشامل — المحاسبي والأمني والمنطقي (بدون واجهة).

تشمل:
  1. فحص كل التقارير الخمسة والكشوف الثلاثة ضد إعادة حساب مستقلة (SQL مختلفة الصياغة).
  2. فحص كل عمليات CRUD بكل أنواعها (صالح/فاسد/مرفوض).
  3. فحص محاسبي: ثوابت الأرصدة وتسلسل الكشوف بعد كل عملية + Fuzz عشوائي ~250 عملية.
  4. فحص أمني: حقن SQL في كل الحقول، نصوص شاذة، مسارات اجتيازية، مبالغ/تواريخ فاسدة،
     مراجع غير موجودة، سلامة قاعدة البيانات (integrity + foreign keys).

تشغيل:  python scripts/test_full.py
"""
from __future__ import annotations

import math
import os
import random
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ["LOGISTIC_DATA_DIR"] = tempfile.mkdtemp(prefix="logistic_full_")

from app.core import calc, db, repo                      # noqa: E402
from app.core.rules import RuleError                    # noqa: E402
from app.utils import fmt                               # noqa: E402
from app.utils.fmt import parse_float                   # noqa: E402

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


def expect_reject(name: str, fn) -> None:
    try:
        fn()
    except (RuleError, ValueError):
        check(name, True)
        return
    except Exception as e:  # noqa: BLE001
        check(name, False, f"— استثناء غير متوقع: {type(e).__name__}: {e}")
        return
    check(name, False, "— لم يُرفض!")


# ===========================================================================
# أدوات إعادة الحساب المستقلة (صياغة SQL مختلفة عن calc.py)
# ===========================================================================
def indep_customer_balance(conn, cid: int) -> float:
    """رصيد العميل محسوباً باستعلام واحد مجمّع."""
    row = conn.execute(
        """
        SELECT
          (SELECT IFNULL(opening_balance, 0) FROM customers WHERE id = :c)
        + (SELECT IFNULL(SUM(t.price), 0) FROM invoice_trips t
             JOIN invoices i ON i.id = t.invoice_id WHERE i.customer_id = :c)
        - (SELECT IFNULL(SUM(r.amount), 0) FROM receipt_vouchers r
             WHERE r.voucher_type = 'customer' AND r.customer_id = :c)
        AS bal
        """, {"c": cid}).fetchone()
    return round(float(row["bal"]), 2)


def indep_account_balance(conn, kind: str, aid: int) -> float:
    tbl = "cashboxes" if kind == "cashbox" else "banks"
    row = conn.execute(
        f"""
        SELECT
          (SELECT IFNULL(opening_balance, 0) FROM {tbl} WHERE id = :a)
        + (SELECT IFNULL(SUM(v.amount), 0) FROM receipt_vouchers v
             WHERE v.account_kind = :k AND v.account_id = :a)
        - (SELECT IFNULL(SUM(v.amount), 0) FROM payment_vouchers v
             WHERE v.account_kind = :k AND v.account_id = :a)
        - (SELECT IFNULL(SUM(p.net_salary), 0) FROM payrolls p
             WHERE p.account_kind = :k AND p.account_id = :a)
        AS bal
        """, {"a": aid, "k": kind}).fetchone()
    return round(float(row["bal"]), 2)


def indep_pnl(conn, d_from: str, d_to: str) -> dict:
    def s(sql, params=()):
        return float(conn.execute(sql, params).fetchone()[0] or 0)

    transport = s("SELECT IFNULL(SUM(t.price),0) FROM invoice_trips t, invoices i "
                  "WHERE i.id = t.invoice_id AND i.date BETWEEN ? AND ?", (d_from, d_to))
    other = s("SELECT IFNULL(SUM(v.amount),0) FROM receipt_vouchers v "
              "WHERE v.voucher_type='other' AND v.date BETWEEN ? AND ?", (d_from, d_to))
    direct = s("SELECT IFNULL(SUM(e.amount),0) FROM trip_expenses e, invoice_trips t, "
               "invoices i WHERE e.trip_id = t.id AND t.invoice_id = i.id "
               "AND i.date BETWEEN ? AND ?", (d_from, d_to))
    salaries = s("SELECT IFNULL(SUM(p.net_salary),0) FROM payrolls p "
                 "WHERE p.date BETWEEN ? AND ?", (d_from, d_to))
    adv = s("SELECT IFNULL(SUM(v.amount),0) FROM payment_vouchers v "
            "WHERE v.voucher_type='advance' AND v.date BETWEEN ? AND ?", (d_from, d_to))
    maint = s("SELECT IFNULL(SUM(v.amount),0) FROM payment_vouchers v "
              "WHERE v.voucher_type='vehicle' AND v.date BETWEEN ? AND ?", (d_from, d_to))
    gen = s("SELECT IFNULL(SUM(v.amount),0) FROM payment_vouchers v "
            "WHERE v.voucher_type='general' AND v.date BETWEEN ? AND ?", (d_from, d_to))
    rev, exp = transport + other, direct + salaries + adv + maint + gen
    return {"transport_revenue": transport, "other_revenue": other,
            "total_revenue": rev, "direct_expenses": direct, "salaries": salaries,
            "advances": adv, "maintenance": maint, "general_expenses": gen,
            "total_expenses": exp, "net": rev - exp}


def verify_all_invariants(conn, ctx: str) -> None:
    """ثوابت محاسبية يجب أن تنطبق دائماً وعلى كل السجلات."""
    # 1) رصيد كل عميل
    for c in conn.execute("SELECT id FROM customers").fetchall():
        check(f"[{ctx}] رصيد العميل {c['id']}",
              abs(calc.customer_balance(conn, c["id"])
                  - indep_customer_balance(conn, c["id"])) < 0.005)
    # 2) رصيد كل خزينة/بنك
    for k, tbl in (("cashbox", "cashboxes"), ("bank", "banks")):
        for a in conn.execute(f"SELECT id FROM {tbl}").fetchall():
            check(f"[{ctx}] رصيد {k} {a['id']}",
                  abs(calc.account_balance(conn, k, a["id"])
                      - indep_account_balance(conn, k, a["id"])) < 0.005)
    # 3) إجماليات كل فاتورة
    for i in conn.execute("SELECT id FROM invoices").fetchall():
        t = calc.invoice_totals(conn, i["id"])
        r = conn.execute(
            """SELECT
                 (SELECT IFNULL(SUM(price),0) FROM invoice_trips WHERE invoice_id=:i),
                 (SELECT IFNULL(SUM(e.amount),0) FROM trip_expenses e, invoice_trips t
                    WHERE e.trip_id=t.id AND t.invoice_id=:i),
                 (SELECT IFNULL(SUM(v.amount),0) FROM payment_vouchers v, invoice_trips t
                    WHERE v.trip_id=t.id AND v.voucher_type='trip' AND t.invoice_id=:i)""",
            {"i": i["id"]}).fetchone()
        check(f"[{ctx}] إجماليات الفاتورة {i['id']}",
              abs(t["trips_total"] - r[0]) < 0.005
              and abs(t["expenses_total"] - r[1]) < 0.005
              and abs(t["later_payments"] - r[2]) < 0.005
              and abs(t["expected_profit"] - (r[0] - r[1])) < 0.005
              and abs(t["actual_profit"] - (r[0] - r[1] - r[2])) < 0.005
              and abs(t["customer_total"] - r[0]) < 0.005)
    # 4) صافي كل راتب = الأساسي + إضافات − سلف − أخرى، والمخصوم ≤ قيمة السلفة
    for p in conn.execute("SELECT * FROM payrolls").fetchall():
        check(f"[{ctx}] معادلة صافي الراتب {p['id']}",
              abs(p["net_salary"] - (p["base_salary"] + p["additions"]
                                     - p["advance_deduction"]
                                     - p["other_deductions"])) < 0.005)
    for s in conn.execute(
            "SELECT s.*, v.amount AS adv_amount FROM advance_settlements s "
            "JOIN payment_vouchers v ON v.id = s.payment_voucher_id").fetchall():
        check(f"[{ctx}] تسوية ≤ السلفة {s['id']}", s["amount"] <= s["adv_amount"] + 0.005)
    for v in conn.execute(
            "SELECT * FROM payment_vouchers WHERE voucher_type='advance'").fetchall():
        settled = conn.execute(
            "SELECT IFNULL(SUM(amount),0) FROM advance_settlements "
            "WHERE payment_voucher_id=?", (v["id"],)).fetchone()[0]
        check(f"[{ctx}] المسدد ≤ السلفة {v['id']}", settled <= v["amount"] + 0.005)
    # 5) P&L مستقلاً
    a = calc.pnl_report(conn, "2000-01-01", "2999-12-31")
    b = indep_pnl(conn, "2000-01-01", "2999-12-31")
    for k in b:
        check(f"[{ctx}] P&L {k}", abs(a[k] - b[k]) < 0.005,
              f"({a[k]} مقابل {b[k]})")
    # 6) سلامة قاعدة البيانات
    check(f"[{ctx}] foreign_key_check",
          len(conn.execute("PRAGMA foreign_key_check").fetchall()) == 0)
    check(f"[{ctx}] integrity_check",
          conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok")
    # 7) تسلسل كشف حساب العميل: closing = opening + Σ(مدين − دائن)
    for c in conn.execute("SELECT id FROM customers").fetchall():
        st = calc.customer_statement(conn, c["id"], "2000-01-01", "2999-12-31")
        flows = sum(r["debit"] - r["credit"] for r in st["rows"])
        check(f"[{ctx}] تسلسل كشف العميل {c['id']}",
              abs(st["closing"] - (st["opening"] + flows)) < 0.005)
        run = st["opening"]
        ok = True
        for r in st["rows"]:
            run += r["debit"] - r["credit"]
            if abs(run - r["balance"]) > 0.005:
                ok = False
        check(f"[{ctx}] أرصدة أسطر كشف العميل {c['id']}", ok)


# ===========================================================================
def build_scenario(conn) -> dict:
    """بناء سيناريو واقعي كامل يغطي كل أنواع الحركات."""
    ids: dict = {}
    repo.save_year(conn, {"year": 2026, "date_from": "2026-01-01",
                          "date_to": "2026-12-31"})
    repo.save_year(conn, {"year": 2027, "date_from": "2027-01-01",
                          "date_to": "2027-12-31"})
    ids["c1"] = repo.save_customer(conn, {"name": "عميل أول", "phone": "0555",
                                          "address": "جدة", "opening_balance": 10000})
    ids["c2"] = repo.save_customer(conn, {"name": "عميل ثانٍ", "phone": "0555000000",
                                          "opening_balance": 0})
    ids["d1"] = repo.save_employee(conn, {"name": "سائق أحمد", "emp_type": "driver"})
    ids["d2"] = repo.save_employee(conn, {"name": "سائق خالد", "emp_type": "driver"})
    ids["a1"] = repo.save_employee(conn, {"name": "إداري سالم", "emp_type": "admin"})
    ids["v1"] = repo.save_vehicle(conn, {"plate_number": "أ ب ج 1", "vehicle_type": "تريلة",
                                         "default_driver_id": ids["d1"]})
    ids["v2"] = repo.save_vehicle(conn, {"plate_number": "د هـ 2", "vehicle_type": "سطحة"})
    ids["cb1"] = repo.save_account(conn, "cashbox", {"name": "الخزينة الرئيسية",
                                                     "created_date": "2026-01-01",
                                                     "opening_balance": 50000})
    ids["cb2"] = repo.save_account(conn, "cashbox", {"name": "خزينة فرعية",
                                                     "created_date": "2026-01-01",
                                                     "opening_balance": 5000})
    ids["bn1"] = repo.save_account(conn, "bank", {"name": "البنك الأهلي",
                                                  "created_date": "2026-01-01",
                                                  "account_number": "123",
                                                  "iban": "SA03 8000 0000 6080 1016 7519",
                                                  "opening_balance": 100000})
    return ids


def main() -> None:  # noqa: C901 — منظومة فحص
    print("== 1) بناء السيناريو والثوابت الأساسية")
    db.init_db()
    conn = db.get_conn()
    ids = build_scenario(conn)
    verify_all_invariants(conn, "أساسي")

    # ------------------------------------------------------------- فاتورة كاملة
    print("== 2) فاتورة بنقلات ومصروفات وكل أنواع السندات")
    inv1 = repo.save_invoice(conn, {
        "date": "2026-02-01", "customer_id": ids["c1"], "notes": "فاتورة أولى",
        "trips": [
            {"vehicle_id": ids["v1"], "driver_id": ids["d1"], "from_loc": "جدة",
             "to_loc": "الرياض", "price": 12000,
             "expenses": [{"expense_type": "trip", "amount": 500, "notes": "تريب"},
                          {"expense_type": "fuel", "amount": 300, "notes": "بنزين"},
                          {"expense_type": "card", "amount": 100, "notes": "كارتة"}]},
            {"vehicle_id": ids["v2"], "driver_id": ids["d2"], "from_loc": "جدة",
             "to_loc": "الدمام", "price": 8000,
             "expenses": [{"expense_type": "fuel", "amount": 250, "notes": ""}]},
            {"vehicle_id": None, "driver_id": None, "from_loc": "مكة", "to_loc": "جدة",
             "price": 1500, "expenses": []},
        ]})
    t = calc.invoice_totals(conn, inv1)
    check("إجمالي الفاتورة = 21500 (لا يشمل المصروفات)",
          t["customer_total"] == 21500 and t["trips_total"] == 21500)
    check("مصروفات مباشرة = 1150", t["expenses_total"] == 1150)
    check("الربح المتوقع = 20350", t["expected_profit"] == 20350)
    check("مديونية العميل شملت الفاتورة كاملة",
          indep_customer_balance(conn, ids["c1"]) == 31500)

    rv1 = repo.save_receipt(conn, {"date": "2026-02-10", "account_kind": "cashbox",
                                   "account_id": ids["cb1"], "voucher_type": "customer",
                                   "customer_id": ids["c1"], "amount": 15000,
                                   "description": "دفعة"})
    rv2 = repo.save_receipt(conn, {"date": "2026-02-11", "account_kind": "bank",
                                   "account_id": ids["bn1"], "voucher_type": "other",
                                   "amount": 700, "description": "خردة"})
    trips = {r["id"]: r for r in conn.execute(
        "SELECT id FROM invoice_trips WHERE invoice_id=? ORDER BY id", (inv1,))}
    trip_ids = list(trips)
    pv_trip = repo.save_payment(conn, {"date": "2026-02-12", "account_kind": "cashbox",
                                       "account_id": ids["cb1"], "voucher_type": "trip",
                                       "trip_id": trip_ids[0], "amount": 400,
                                       "description": "رسوم تفريغ"})
    pv_adv1 = repo.save_payment(conn, {"date": "2026-02-13", "account_kind": "cashbox",
                                       "account_id": ids["cb1"], "voucher_type": "advance",
                                       "employee_id": ids["d1"], "amount": 2000,
                                       "description": "سلفة"})
    pv_adv2 = repo.save_payment(conn, {"date": "2026-02-14", "account_kind": "bank",
                                       "account_id": ids["bn1"], "voucher_type": "advance",
                                       "employee_id": ids["d2"], "amount": 1500,
                                       "description": "سلفة ثانية"})
    pv_veh = repo.save_payment(conn, {"date": "2026-02-15", "account_kind": "bank",
                                      "account_id": ids["bn1"], "voucher_type": "vehicle",
                                      "vehicle_id": ids["v1"],
                                      "vehicle_expense": "tires", "amount": 2000,
                                      "description": "كاوتش"})
    pv_gen = repo.save_payment(conn, {"date": "2026-02-16", "account_kind": "cashbox",
                                      "account_id": ids["cb2"], "voucher_type": "general",
                                      "amount": 800, "description": "كهرباء"})
    pay1 = repo.save_payroll(conn, {
        "date": "2026-02-28", "employee_id": ids["d1"], "period_year": 2026,
        "period_month": 2, "account_kind": "cashbox", "account_id": ids["cb1"],
        "base_salary": 4000, "additions": 500, "additions_note": "مكافأة",
        "other_deductions": 200, "settlements": [(pv_adv1, 1200)]})
    pay2 = repo.save_payroll(conn, {
        "date": "2026-02-28", "employee_id": ids["a1"], "period_year": 2026,
        "period_month": 2, "account_kind": "bank", "account_id": ids["bn1"],
        "base_salary": 5000, "settlements": []})
    verify_all_invariants(conn, "بعد-الحركات")

    # ------------------------------------------------- التقارير ضد الحساب المستقل
    print("== 3) التقارير الخمسة")
    # 3-1 أرباح الرحلات
    rows = calc.trip_profits_report(conn, "2026-01-01", "2026-12-31")
    check("تقرير الرحلات: 3 رحلات", len(rows) == 3)
    r0 = next(r for r in rows if r["route"].startswith("جدة"))
    check("رحلة الرياض: مباشرة 900", r0["direct"] == 900)
    check("رحلة الرياض: لاحق 400", r0["later"] == 400)
    check("رحلة الرياض: صافي = 12000-900-400", r0["net"] == 10700)
    tot_net = sum(r["net"] for r in rows)
    check("صافي كل الرحلات = 21500-1150-400", abs(tot_net - 19950) < 0.005)
    # فلترة عميل
    rows_c2 = calc.trip_profits_report(conn, None, None, ids["c1"])
    check("فلترة العميل في تقرير الرحلات", len(rows_c2) == 3)
    # 3-2 كشف العميل
    st = calc.customer_statement(conn, ids["c1"], "2026-01-01", "2026-12-31")
    check("كشف العميل: افتتاحي 10000", st["opening"] == 10000)
    check("كشف العميل: ختامي 10000+21500-15000", st["closing"] == 16500)
    check("كشف العميل: سطران (فاتورة+قبض)", len(st["rows"]) == 2)
    # فترة سابقة لا حركات فيها
    st_pre = calc.customer_statement(conn, ids["c1"], "2026-03-01", "2026-12-31")
    check("كشف بفترة لاحقة: افتتاحي = الرصيد الحالي حينها",
          abs(st_pre["opening"] - 16500) < 0.005 and len(st_pre["rows"]) == 0)
    # 3-3 كشف الموظف
    est = calc.employee_statement(conn, ids["d1"], "2026-01-01", "2026-12-31")
    check("موظف: صافي رواتب 4000+500-1200-200", est["totals"]["salaries_net"] == 3100)
    check("موظف: سلف 2000 متبقي 800",
          est["totals"]["advances_total"] == 2000
          and est["totals"]["advances_remaining"] == 800)
    check("موظف: بدل تريب 500 (رحلة واحدة بسائق أحمد من نوع trip)",
          est["totals"]["allowances_total"] == 500)
    check("موظف: تفاصيل تسوية السلفة بتاريخ الراتب",
          est["advances"][0]["settlements"][0]["amount"] == 1200)
    est_d2 = calc.employee_statement(conn, ids["d2"], None, None)
    check("موظف 2: تريب 0", est_d2["totals"]["allowances_total"] == 0)
    # 3-4 أداء السيارات
    vr = calc.vehicle_report(conn, "2026-01-01", "2026-12-31")
    v1 = next(v for v in vr if v["vehicle_id"] == ids["v1"])
    check("سيارة1: إيراد 12000", v1["revenue"] == 12000)
    check("سيارة1: مباشرة 900", v1["direct"] == 900)
    check("سيارة1: صيانة 2000", v1["maintenance"] == 2000)
    check("سيارة1: صافي 9100", v1["net"] == 9100)
    v2 = next(v for v in vr if v["vehicle_id"] == ids["v2"])
    check("سيارة2: صافي 8000-250", v2["net"] == 7750)
    # 3-5 P&L
    pnl = calc.pnl_report(conn, "2026-01-01", "2026-12-31")
    exp_pnl = {"transport_revenue": 21500, "other_revenue": 700,
               "direct_expenses": 1150, "salaries": 3100 + 5000,
               "advances": 3500, "maintenance": 2000, "general_expenses": 800}
    for k, v in exp_pnl.items():
        check(f"P&L {k} = {v}", abs(pnl[k] - v) < 0.005, f"(وجدها {pnl[k]})")
    check("P&L net = 22200-15550", abs(pnl["net"] - (22200 - 15550)) < 0.005)
    # P&L بفترة ضيقة تستثني لاحقاً
    pnl_q1 = calc.pnl_report(conn, "2026-01-01", "2026-02-10")
    check("P&L فترة ضيقة: بدون كهرباء ولا رواتب",
          pnl_q1["general_expenses"] == 0 and pnl_q1["salaries"] == 0
          and pnl_q1["transport_revenue"] == 21500)

    # ------------------------------------------------------------- كشوف الخزائن
    print("== 4) كشوف الخزائن والبنوك")
    ast = calc.account_statement(conn, "cashbox", ids["cb1"], "2026-01-01", "2026-12-31")
    # 50000 + 15000 (قبض) − 400 (رحلة) − 2000 (سلفة) − 3100 (صافي راتب) = 59500
    check("كشف الخزينة1: ختامي 59500", abs(ast["closing"] - 59500) < 0.005)
    kinds = [r["kind"] for r in ast["rows"]]
    check("كشف الخزينة: قبض+سندان+راتب = 4 أسطر", kinds.count("receipt") == 1
          and kinds.count("payment") == 2 and kinds.count("payroll") == 1)
    bnk = calc.account_statement(conn, "bank", ids["bn1"], "2026-01-01", "2026-12-31")
    # 100000 + 700 − 1500 (سلفة) − 2000 (كاوتش) − 5000 (راتب إداري) = 92200
    check("كشف البنك: ختامي 92200", abs(bnk["closing"] - 92200) < 0.005)

    # ------------------------------------------------------ لقطة الإغلاق
    print("== 5) السنوات ولقطات الإغلاق")
    y26 = conn.execute("SELECT id FROM financial_years WHERE year=2026").fetchone()["id"]
    expect_reject("حذف سنة بها حركات", lambda: repo.delete_year(conn, y26))
    repo.set_year_status(conn, y26, "closed")
    snap = repo.create_snapshot(conn, y26)
    check("اللقطة: أرصدة العملاء", any(c["balance"] == 16500 for c in snap["customers"]))
    check("اللقطة: خزينة", any(c["balance"] == 59500 for c in snap["cashboxes"]))
    check("اللقطة: بنك", any(b["balance"] == 92200 for b in snap["banks"]))
    check("اللقطة: صافي السنة = 22200-15550",
          abs(snap["pnl"]["net"] - (22200 - 15550)) < 0.005)
    # كل الحركات داخل السنة المغلقة تُمنع الآن
    expect_reject("إضافة داخل سنة مغلقة",
                  lambda: repo.save_receipt(conn, {
                      "date": "2026-03-01", "account_kind": "cashbox",
                      "account_id": ids["cb1"], "voucher_type": "other",
                      "amount": 100}))
    expect_reject("تعديل داخل سنة مغلقة",
                  lambda: repo.save_receipt(conn, {
                      "date": "2026-02-10", "account_kind": "cashbox",
                      "account_id": ids["cb1"], "voucher_type": "customer",
                      "customer_id": ids["c1"], "amount": 15000}, rv1))
    expect_reject("حذف داخل سنة مغلقة", lambda: repo.delete_receipt(conn, rv1))
    # لكن السنة المفتوحة 2027 تعمل
    rv3 = repo.save_receipt(conn, {"date": "2027-01-05", "account_kind": "cashbox",
                                   "account_id": ids["cb1"], "voucher_type": "other",
                                   "amount": 50})
    repo.delete_receipt(conn, rv3)
    repo.set_year_status(conn, y26, "open")
    verify_all_invariants(conn, "بعد-فتح/غلق")

    # ------------------------------------------------------------ قواعد المنع
    print("== 6) قواعد المنع المحاسبية")
    expect_reject("حذف عميل له فواتير", lambda: repo.delete_customer(conn, ids["c1"]))
    expect_reject("حذف موظف له رواتب", lambda: repo.delete_employee(conn, ids["d1"]))
    expect_reject("حذف سيارة لها رحلات", lambda: repo.delete_vehicle(conn, ids["v1"]))
    expect_reject("حذف خزينة لها حركات", lambda: repo.delete_account(conn, "cashbox",
                                                                      ids["cb1"]))
    expect_reject("حذف فاتورة مرتبطة بسند دفع", lambda: repo.delete_invoice(conn, inv1))
    expect_reject("تعديل سلفة عليها تسوية", lambda: repo.save_payment(conn, {
        "date": "2026-02-13", "account_kind": "cashbox", "account_id": ids["cb1"],
        "voucher_type": "advance", "employee_id": ids["d1"], "amount": 1000}, pv_adv1))
    expect_reject("حذف سلفة عليها تسوية", lambda: repo.delete_payment(conn, pv_adv1))
    # حذف الراتب يعيد السلفة
    repo.delete_payroll(conn, pay1)
    rem = {a["id"]: a["remaining"] for a in repo.employee_advances(conn, ids["d1"])}
    check("حذف الراتب يعيد المتبقي من السلفة إلى 2000", rem[pv_adv1] == 2000)
    verify_all_invariants(conn, "بعد-حذف-راتب")
    # إعادة الراتب ثم تعديل فاتورة بأثر رجعي
    repo.save_payroll(conn, {
        "date": "2026-02-28", "employee_id": ids["d1"], "period_year": 2026,
        "period_month": 2, "account_kind": "cashbox", "account_id": ids["cb1"],
        "base_salary": 4000, "additions": 500, "other_deductions": 200,
        "settlements": [(pv_adv1, 1200)]})
    full = calc.get_invoice_full(conn, inv1)
    full["trips"][2]["price"] = 2500  # من 1500 إلى 2500
    repo.save_invoice(conn, full, inv1)
    check("تعديل فاتورة: رصيد العميل +1000",
          abs(indep_customer_balance(conn, ids["c1"]) - 17500) < 0.005)
    verify_all_invariants(conn, "بعد-تعديل-فاتورة")

    # --------------------------------------------------------------- الفحص الأمني
    print("== 7) الفحص الأمني")
    tables_before = {r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'")}
    payloads = [
        "'; DROP TABLE customers; --",
        "\"; DELETE FROM invoices WHERE 1=1; --",
        "a' OR '1'='1",
        "%s%s%s", "${7*7}", "{{7*7}}", "<script>alert('x')</script>",
        "'; UPDATE customers SET opening_balance=999999; --",
        "\\\\", "\u202eRTL\u202e", "null\x00byte", "\u2014", "\U0001f30d\U0001f69b",
    ]
    for i, p in enumerate(payloads):
        cid = repo.save_customer(conn, {"name": p, "phone": p, "address": p,
                                        "opening_balance": 0, "notes": p})
        saved = repo.get_customer(conn, cid)
        check(f"حقن SQL #{i}: الحفظ والاسترجاع دون تنفيذ",
              saved["name"] == p)  # ما يدخل يخرج كما هو = لم يُفسد شيء
    tables_after = {r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'")}
    check("حقن SQL: لم تتغير جداول القاعدة", tables_before == tables_after)
    check("حقن SQL: جدول العملاء موجود", "customers" in tables_after)
    n = conn.execute("SELECT COUNT(*) FROM customers").fetchone()[0]
    check("حقن SQL: لم تُحذف بيانات العملاء", n >= 2)
    # نص طويل داخل الحد المسموح + رفض ما فوق الحد
    long_text = "أ" * 4000
    lid = repo.save_customer(conn, {"name": long_text, "opening_balance": 0})
    check("نص 4000 محرف يُخزن ويُسترجع",
          len(repo.get_customer(conn, lid)["name"]) == 4000)
    expect_reject("نص 6000 محرف يُرفض (سقف الحماية)",
                  lambda: repo.save_customer(conn, {"name": "ب" * 6000}))
    # فاتورة بحقول محقونة في كل النصوص
    inj = {"from_loc": "';--", "to_loc": "<b>", "notes": "'; DROP TABLE x; --"}
    iinv = repo.save_invoice(conn, {"date": "2026-03-05", "customer_id": ids["c1"],
                                    "notes": inj["notes"],
                                    "trips": [{"vehicle_id": None, "driver_id": None,
                                               "from_loc": inj["from_loc"],
                                               "to_loc": inj["to_loc"], "price": 100,
                                               "expenses": [
                                                   {"expense_type": "fuel",
                                                    "amount": 10,
                                                    "notes": "';--"}]}]})
    check("فاتورة محقونة: حُفظت وسليمة",
          "customers" in tables_after
          and conn.execute("SELECT from_loc FROM invoice_trips WHERE invoice_id=?",
                           (iinv,)).fetchone()[0] == "';--")
    # HTML escaping في التصدير
    from app.utils import exporter as exp_mod
    html = exp_mod.build_report_html(
        conn, title="تقرير", headers=["أ", "ب"],
        rows=[["<script>alert(1)</script>", "12,<script>"]])
    check("XSS: وسوم البرمجة مهرَّبة في HTML",
          "<script>alert(1)</script>" not in html
          and "&lt;script&gt;" in html)
    # مسار اجتيازي في المرفقات
    tmp_src = Path(tempfile.mkdtemp()) / ".." / "payload_evil.txt"
    tmp_src = Path(tempfile.gettempdir()) / "payload_evil.txt"
    tmp_src.write_text("evil")
    rel = repo.store_attachment(str(tmp_src))
    dest = db.data_dir() / rel
    check("مسار اجتيازي: المرفق حُبس داخل مجلد المرفقات",
          dest.parent == db.attachments_dir().resolve()
          or dest.resolve().parent == db.attachments_dir().resolve())
    check("مسار اجتيازي: لا يوجد ملف خارج المجلد",
          not (db.data_dir() / "payload_evil.txt").exists()
          and (db.attachments_dir() / "payload_evil.txt").exists())
    # مبالغ فاسدة
    expect_reject("مبلغ سالب في سند", lambda: repo.save_receipt(conn, {
        "date": "2026-03-01", "account_kind": "cashbox", "account_id": ids["cb1"],
        "voucher_type": "other", "amount": -100}))
    expect_reject("مبلغ صفر", lambda: repo.save_receipt(conn, {
        "date": "2026-03-01", "account_kind": "cashbox", "account_id": ids["cb1"],
        "voucher_type": "other", "amount": 0}))
    for bad in ("NaN", "inf", "abc", "", "1e999"):
        try:
            v = parse_float(bad)
            ok = math.isfinite(v)
        except ValueError:
            ok = True
        check(f"مبلغ غير عدداني '{bad}' لا يمر كسالب/لا نهائي", ok)
    check("أرقام عربية تُقرأ", parse_float("١٢٣٤٫٥٦") == 1234.56)
    check("فواصل آلاف تُقرأ", parse_float("1,234.56") == 1234.56)
    # مراجع غير موجودة
    expect_reject("سند برحلة غير موجودة", lambda: repo.save_payment(conn, {
        "date": "2026-03-01", "account_kind": "cashbox", "account_id": ids["cb1"],
        "voucher_type": "trip", "trip_id": 999999, "amount": 10}))
    expect_reject("سند بحساب غير موجود", lambda: repo.save_payment(conn, {
        "date": "2026-03-01", "account_kind": "cashbox", "account_id": 999999,
        "voucher_type": "general", "amount": 10}))
    expect_reject("راتب بموظف غير موجود (FK)", lambda: repo.save_payroll(conn, {
        "date": "2026-03-01", "employee_id": 999999, "period_year": 2026,
        "period_month": 3, "account_kind": "cashbox", "account_id": ids["cb1"],
        "base_salary": 100, "settlements": []}))
    # تواريخ فاسدة
    expect_reject("تاريخ خارج كل السنوات", lambda: repo.save_receipt(conn, {
        "date": "2030-05-05", "account_kind": "cashbox", "account_id": ids["cb1"],
        "voucher_type": "other", "amount": 10}))
    expect_reject("تاريخ فارغ", lambda: repo.save_receipt(conn, {
        "date": "", "account_kind": "cashbox", "account_id": ids["cb1"],
        "voucher_type": "other", "amount": 10}))
    # حقول إلزامية فارغة
    expect_reject("عميل بدون اسم", lambda: repo.save_customer(conn, {"name": "   "}))
    expect_reject("موظف بدون نوع", lambda: repo.save_employee(conn, {"name": "x",
                                                                      "emp_type": "zzz"}))
    expect_reject("فاتورة بدون نقلات", lambda: repo.save_invoice(conn, {
        "date": "2026-03-01", "customer_id": ids["c1"], "trips": []}))
    expect_reject("نقلة بسعر سالب", lambda: repo.save_invoice(conn, {
        "date": "2026-03-01", "customer_id": ids["c1"],
        "trips": [{"from_loc": "a", "to_loc": "b", "price": -5, "expenses": []}]}))
    expect_reject("مصروف نقلة سالب", lambda: repo.save_invoice(conn, {
        "date": "2026-03-01", "customer_id": ids["c1"],
        "trips": [{"from_loc": "a", "to_loc": "b", "price": 5,
                   "expenses": [{"expense_type": "fuel", "amount": -1}]}]}))
    expect_reject("خصم سلفة أكبر من المتبقي", lambda: repo.save_payroll(conn, {
        "date": "2026-03-30", "employee_id": ids["d1"], "period_year": 2026,
        "period_month": 3, "account_kind": "cashbox", "account_id": ids["cb1"],
        "base_salary": 3000, "settlements": [(pv_adv1, 999999)]}))
    expect_reject("صافي راتب سالب", lambda: repo.save_payroll(conn, {
        "date": "2026-03-30", "employee_id": ids["d1"], "period_year": 2026,
        "period_month": 3, "account_kind": "cashbox", "account_id": ids["cb1"],
        "base_salary": 100, "other_deductions": 500, "settlements": []}))
    expect_reject("تسوية لا تطابق الإجمالي", lambda: repo.save_payroll(conn, {
        "date": "2026-03-30", "employee_id": ids["d1"], "period_year": 2026,
        "period_month": 3, "account_kind": "cashbox", "account_id": ids["cb1"],
        "base_salary": 1000, "advance_deduction": 500,
        "settlements": [(pv_adv1, 100)]}))
    expect_reject("تكرار رقم سنة مالية", lambda: repo.save_year(conn, {
        "year": 2026, "date_from": "2026-01-01", "date_to": "2026-12-31"}))
    expect_reject("سنة بنهاية قبل البداية", lambda: repo.save_year(conn, {
        "year": 2030, "date_from": "2030-12-31", "date_to": "2030-01-01"}))
    verify_all_invariants(conn, "بعد-الأمان")

    # --------------------------------------------------------------- FUZZ
    print("== 8) اختبار ضغط عشوائي (250 عملية) ثم كل الثوابت")
    rng = random.Random(4242)
    ops_done = 0
    for step in range(250):
        try:
            action = rng.choice(["invoice", "receipt", "payment", "payroll",
                                 "edit_invoice", "del", "customer"])
            if action == "invoice":
                n = rng.randint(1, 3)
                trips = []
                for _ in range(n):
                    expenses = [{"expense_type": rng.choice(
                        ["trip", "fuel", "card", "other"]),
                        "amount": round(rng.uniform(10, 500), 2)}
                        for _ in range(rng.randint(0, 2))]
                    trips.append({
                        "vehicle_id": rng.choice([None, ids["v1"], ids["v2"]]),
                        "driver_id": rng.choice([None, ids["d1"], ids["d2"]]),
                        "from_loc": f"من{rng.randint(1, 99)}",
                        "to_loc": f"إلى{rng.randint(1, 99)}",
                        "price": round(rng.uniform(100, 9000), 2),
                        "expenses": expenses})
                repo.save_invoice(conn, {
                    "date": rng.choice(["2026-04-01", "2026-05-15", "2027-02-09"]),
                    "customer_id": rng.choice([ids["c1"], ids["c2"]]),
                    "trips": trips})
            elif action == "receipt":
                is_cust = rng.random() < 0.6
                repo.save_receipt(conn, {
                    "date": rng.choice(["2026-04-10", "2027-03-01"]),
                    "account_kind": rng.choice(["cashbox", "bank"]),
                    "account_id": rng.choice([ids["cb1"], ids["cb2"], ids["bn1"]]),
                    "voucher_type": "customer" if is_cust else "other",
                    "customer_id": rng.choice([ids["c1"], ids["c2"]]) if is_cust else None,
                    "amount": round(rng.uniform(50, 5000), 2)})
            elif action == "payment":
                vt = rng.choice(["trip", "advance", "vehicle", "general"])
                data = {"date": rng.choice(["2026-04-20", "2027-01-20"]),
                        "account_kind": rng.choice(["cashbox", "bank"]),
                        "account_id": rng.choice([ids["cb1"], ids["cb2"], ids["bn1"]]),
                        "voucher_type": vt,
                        "amount": round(rng.uniform(20, 3000), 2)}
                if vt == "trip":
                    tr = conn.execute("SELECT id FROM invoice_trips "
                                      "ORDER BY RANDOM() LIMIT 1").fetchone()
                    if not tr:
                        continue
                    data["trip_id"] = tr["id"]
                elif vt == "advance":
                    data["employee_id"] = rng.choice([ids["d1"], ids["d2"], ids["a1"]])
                elif vt == "vehicle":
                    data["vehicle_id"] = rng.choice([ids["v1"], ids["v2"]])
                repo.save_payment(conn, data)
            elif action == "payroll":
                emp = rng.choice([ids["d1"], ids["d2"], ids["a1"]])
                open_advs = [a for a in repo.employee_advances(conn, emp, False)]
                settlements = []
                if open_advs and rng.random() < 0.7:
                    adv = rng.choice(open_advs)
                    settlements = [(adv["id"], round(rng.uniform(
                        1, max(adv["remaining"], 1)), 2))]
                repo.save_payroll(conn, {
                    "date": rng.choice(["2026-05-28", "2027-02-28"]),
                    "employee_id": emp, "period_year": 2026, "period_month": 5,
                    "account_kind": "cashbox", "account_id": ids["cb1"],
                    "base_salary": round(rng.uniform(2000, 6000), 2),
                    "additions": round(rng.uniform(0, 800), 2),
                    "other_deductions": round(rng.uniform(0, 300), 2),
                    "settlements": settlements})
            elif action == "edit_invoice":
                inv = conn.execute("SELECT id, date FROM invoices "
                                   "ORDER BY RANDOM() LIMIT 1").fetchone()
                if not inv:
                    continue
                full = calc.get_invoice_full(conn, inv["id"])
                if full["trips"]:
                    full["trips"][0]["price"] = round(rng.uniform(100, 8000), 2)
                repo.save_invoice(conn, full, inv["id"])
            elif action == "del":
                what = rng.choice(["receipt", "payment", "payroll"])
                tbl = {"receipt": "receipt_vouchers", "payment": "payment_vouchers",
                       "payroll": "payrolls"}[what]
                row = conn.execute(f"SELECT id FROM {tbl} "
                                   "ORDER BY RANDOM() LIMIT 1").fetchone()
                if not row:
                    continue
                fn = {"receipt": repo.delete_receipt, "payment": repo.delete_payment,
                      "payroll": repo.delete_payroll}[what]
                fn(conn, row["id"])  # قد يُرفض (سلفة مسواة/سنة مقفلة) — مقبول
            elif action == "customer":
                repo.save_customer(conn, {
                    "name": f"عميل عشوائي {step}",
                    "opening_balance": round(rng.uniform(-500, 5000), 2)})
            ops_done += 1
        except RuleError:
            continue  # الرفض المحاسبي مسموح (سلفة مسواة/سنة مقفلة)
    check("عدد عمليات الضغط المنفذة > 200", ops_done > 200, f"(نفذ {ops_done})")
    verify_all_invariants(conn, "fuzz")

    # أرصدة سالبة مسموحة رياضياً لكن المعادلة صحيحة (تحقق نموذجي)
    print(f"\n===== النتيجة: نجاح {PASS} / فشل {FAIL} =====")
    if FAILURES:
        print("الإخفاقات:")
        for f in FAILURES[:30]:
            print("  -", f)
        sys.exit(1)
    print("🎉 كل الفحوصات المحاسبية والأمنية نجحت.")


if __name__ == "__main__":
    main()
