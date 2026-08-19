# -*- coding: utf-8 -*-
"""
اختبار شامل لمنطق النظام (بدون واجهة): يشمل كل الأقسام والقواعد العامة.

تشغيل:  python scripts/smoke_test.py
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

os.environ["LOGISTIC_DATA_DIR"] = tempfile.mkdtemp(prefix="logistic_test_")

from app.core import calc, db, repo            # noqa: E402
from app.core.rules import RuleError           # noqa: E402

PASS = 0


def check(name: str, cond: bool, extra: str = "") -> None:
    global PASS
    if not cond:
        print(f"❌ FAILED: {name} {extra}")
        sys.exit(1)
    PASS += 1
    print(f"✅ {name} {extra}")


def expect_rule_error(name: str, fn) -> None:
    try:
        fn()
    except RuleError as e:
        check(name, True, f"— ({e})"[:70])
        return
    except Exception as e:  # noqa: BLE001
        check(name, False, f"— خطأ غير متوقع: {e}")
        return
    check(name, False, "— لم يُرفض الإجراء!")


def main() -> None:
    db.init_db()
    conn = db.get_conn()

    # ---------------- السنة المالية ----------------
    y2026 = repo.save_year(conn, {"year": 2026, "date_from": "2026-01-01",
                                  "date_to": "2026-12-31", "notes": ""})
    check("إنشاء سنة مالية 2026", repo.get_year(conn, y2026)["status"] == "open")
    expect_rule_error("منع تكرار السنة",
                      lambda: repo.save_year(conn, {"year": 2026,
                                                    "date_from": "2026-01-01",
                                                    "date_to": "2026-12-31"}))

    # ---------------- البيانات الأساسية ----------------
    cust = repo.save_customer(conn, {"name": "مؤسسة الرياض للتجارة",
                                     "phone": "0555000111", "address": "الرياض",
                                     "opening_balance": 5000, "notes": ""})
    driver = repo.save_employee(conn, {"name": "أحمد السائق", "nationality": "سعودي",
                                       "phone": "0500000001", "emp_type": "driver",
                                       "notes": ""})
    admin = repo.save_employee(conn, {"name": "سالم الإداري", "nationality": "مصري",
                                      "phone": "0500000002", "emp_type": "admin",
                                      "notes": ""})
    veh = repo.save_vehicle(conn, {"plate_number": "أ ب ج 123", "vehicle_type": "تريلة",
                                   "default_driver_id": driver, "notes": ""})
    cb = repo.save_account(conn, "cashbox", {"name": "الخزينة الرئيسية",
                                             "created_date": "2026-01-01",
                                             "opening_balance": 10000, "notes": ""})
    bnk = repo.save_account(conn, "bank", {"name": "بنك الراجحي",
                                           "created_date": "2026-01-01",
                                           "account_number": "1234567890",
                                           "iban": "SA00 8000 0000 6080 1016 7519",
                                           "opening_balance": 20000, "notes": ""})
    check("أكواد تلقائية", repo.get_customer(conn, cust)["code"].endswith("0001")
          and repo.get_account(conn, "bank", bnk)["code"].startswith("BNK"))

    # ---------------- فاتورة نقل ----------------
    expect_rule_error("منع فاتورة خارج السنة المفتوحة",
                      lambda: repo.save_invoice(conn, {
                          "date": "2025-12-31", "customer_id": cust,
                          "trips": [{"from_loc": "جدة", "to_loc": "مكة",
                                     "price": 100, "expenses": []}]}))
    inv = repo.save_invoice(conn, {
        "date": "2026-02-10", "customer_id": cust, "notes": "فاتورة تجريبية",
        "attachments": [],
        "trips": [
            {"vehicle_id": veh, "driver_id": driver, "from_loc": "جدة",
             "to_loc": "مكة", "price": 5000, "notes": "",
             "expenses": [
                 {"expense_type": "trip", "amount": 300, "notes": "تريب"},
                 {"expense_type": "fuel", "amount": 200, "notes": "بنزين"}]},
            {"vehicle_id": None, "driver_id": driver, "from_loc": "جدة",
             "to_loc": "الرياض", "price": 8000, "notes": "",
             "expenses": [{"expense_type": "card", "amount": 150, "notes": "كارتة"}]},
        ]})
    t = calc.invoice_totals(conn, inv)
    check("إجماليات الفاتورة", t["trips_total"] == 13000 and t["expenses_total"] == 650
          and t["expected_profit"] == 12350 and t["customer_total"] == 13000)
    check("رصيد العميل بعد الفاتورة",
          calc.customer_balance(conn, cust) == 18000)

    # ---------------- سندات القبض ----------------
    rv1 = repo.save_receipt(conn, {"date": "2026-02-20", "account_kind": "cashbox",
                                   "account_id": cb, "voucher_type": "customer",
                                   "customer_id": cust, "amount": 6000,
                                   "description": "دفعة أولى"})
    repo.save_receipt(conn, {"date": "2026-02-21", "account_kind": "bank",
                             "account_id": bnk, "voucher_type": "other",
                             "customer_id": None, "amount": 500,
                             "description": "بيع خردة"})
    check("رصيد العميل بعد التحصيل", calc.customer_balance(conn, cust) == 12000)
    check("رصيد الخزينة بعد القبض",
          calc.account_balance(conn, "cashbox", cb) == 16000)
    check("رصيد البنك بعد القبض", calc.account_balance(conn, "bank", bnk) == 20500)

    # ---------------- سندات الدفع ----------------
    trips = conn.execute("SELECT id FROM invoice_trips WHERE invoice_id=? "
                         "ORDER BY id", (inv,)).fetchall()
    trip1, trip2 = trips[0]["id"], trips[1]["id"]
    repo.save_payment(conn, {"date": "2026-02-22", "account_kind": "cashbox",
                             "account_id": cb, "voucher_type": "trip",
                             "trip_id": trip2, "amount": 400,
                             "description": "رسوم تفريغ"})
    adv = repo.save_payment(conn, {"date": "2026-03-01", "account_kind": "cashbox",
                                   "account_id": cb, "voucher_type": "advance",
                                   "employee_id": driver, "amount": 800,
                                   "description": "سلفة سائق"})
    repo.save_payment(conn, {"date": "2026-03-02", "account_kind": "bank",
                             "account_id": bnk, "voucher_type": "vehicle",
                             "vehicle_id": veh, "vehicle_expense": "maintenance",
                             "amount": 300, "description": "صيانة دورية"})
    repo.save_payment(conn, {"date": "2026-03-03", "account_kind": "cashbox",
                             "account_id": cb, "voucher_type": "general",
                             "amount": 200, "description": "كهرباء"})
    tp = calc.trip_profit(conn, trip2)
    check("ربح النقلة الفعلي (مع سند لاحق)", tp["net"] == 8000 - 150 - 400)
    check("رصيد الخزينة بعد الدفعات", calc.account_balance(conn, "cashbox", cb) == 14600)
    check("رصيد البنك بعد الدفعات", calc.account_balance(conn, "bank", bnk) == 20200)

    # ---------------- الرواتب ----------------
    pay = repo.save_payroll(conn, {
        "date": "2026-03-05", "employee_id": driver, "period_year": 2026,
        "period_month": 2, "account_kind": "cashbox", "account_id": cb,
        "base_salary": 3000, "additions": 200, "additions_note": "مكافأة",
        "other_deductions": 100, "notes": "",
        "settlements": [(adv, 500)]})
    p = repo.get_payroll(conn, pay)
    check("صافي الراتب", p["net_salary"] == 3000 + 200 - 500 - 100)
    check("رصيد الخزينة بعد الراتب", calc.account_balance(conn, "cashbox", cb) == 12000)
    advs = repo.employee_advances(conn, driver)
    check("المتبقي من السلفة بعد الخصم الجزئي", advs[0]["remaining"] == 300)
    expect_rule_error("منع خصم سلفة أكبر من المتبقي",
                      lambda: repo.save_payroll(conn, {
                          "date": "2026-03-10", "employee_id": driver,
                          "period_year": 2026, "period_month": 3,
                          "account_kind": "cashbox", "account_id": cb,
                          "base_salary": 1000, "additions": 0,
                          "other_deductions": 0,
                          "settlements": [(adv, 9999)], "advance_deduction": 9999}))
    expect_rule_error("منع تعديل سلفة عليها تسوية رواتب",
                      lambda: repo.save_payment(conn, {
                          "date": "2026-03-01", "account_kind": "cashbox",
                          "account_id": cb, "voucher_type": "advance",
                          "employee_id": driver, "amount": 700}, adv))

    # ---------------- كشوف الحساب والتقارير ----------------
    st = calc.customer_statement(conn, cust, "2026-01-01", "2026-12-31")
    check("كشف حساب العميل", st["opening"] == 5000 and st["closing"] == 12000
          and len(st["rows"]) == 2)
    ast = calc.account_statement(conn, "cashbox", cb, "2026-01-01", "2026-12-31")
    check("كشف حساب الخزينة", ast["opening"] == 10000 and ast["closing"] == 12000
          and len(ast["rows"]) == 5)  # سند قبض + 3 سندات دفع + راتب
    emp_st = calc.employee_statement(conn, driver, "2026-01-01", "2026-12-31")
    check("كشف حساب الموظف (رواتب/سلف/تريب)",
          emp_st["totals"]["salaries_net"] == 2600
          and emp_st["totals"]["advances_total"] == 800
          and emp_st["totals"]["advances_remaining"] == 300
          and emp_st["totals"]["allowances_total"] == 300)
    vr = calc.vehicle_report(conn, "2026-01-01", "2026-12-31", veh)
    check("تقرير أداء السيارة", vr[0]["revenue"] == 5000 and vr[0]["direct"] == 500
          and vr[0]["maintenance"] == 300 and vr[0]["net"] == 4200)
    pnl = calc.pnl_report(conn, "2026-01-01", "2026-12-31")
    check("P&L: الإيرادات", pnl["total_revenue"] == 13500)
    check("P&L: المصروفات", pnl["total_expenses"] == 650 + 2600 + 800 + 300 + 200)
    check("P&L: الصافي", pnl["net"] == 8950)

    # ---------------- التعديل وإعادة الاحتساب تلقائياً ----------------
    full = calc.get_invoice_full(conn, inv)
    full["trips"][0]["price"] = 5500
    repo.save_invoice(conn, full, inv)
    check("إعادة احتساب رصيد العميل بعد تعديل الفاتورة",
          calc.customer_balance(conn, cust) == 12500)
    check("إعادة احتساب أداء السيارة", calc.vehicle_report(
        conn, None, None, veh)[0]["revenue"] == 5500)

    # حذف نقلة مرتبطة بسند دفع => مرفوض
    full2 = calc.get_invoice_full(conn, inv)
    full2["trips"] = [full2["trips"][0]]
    expect_rule_error("منع حذف نقلة مرتبطة بسند دفع",
                      lambda: repo.save_invoice(conn, full2, inv))

    # حذف الراتب => عودة السلفة غير مسددة
    repo.delete_payroll(conn, pay)
    advs = repo.employee_advances(conn, driver)
    check("عودة السلفة بعد حذف الراتب",
          advs[0]["remaining"] == 800
          and calc.account_balance(conn, "cashbox", cb) == 14600)

    # ---------------- قاعدة السنوات على التعديل/الحذف ----------------
    expect_rule_error("منع تعديل حركة بتاريخ خارج السنة المفتوحة",
                      lambda: repo.save_receipt(conn, {
                          "date": "2027-01-05", "account_kind": "cashbox",
                          "account_id": cb, "voucher_type": "other",
                          "amount": 100}, rv1))
    repo.set_year_status(conn, y2026, "closed")
    snap = repo.create_snapshot(conn, y2026)
    # النقلات 13500 + إيرادات أخرى 500 − (مباشرة 650 + رواتب 0 (حُذف) + سلف 800
    # + صيانة 300 + عامة 200) = 12050
    check("لقطة الإغلاق", snap["year"] == 2026 and len(snap["customers"]) == 1
          and abs(snap["pnl"]["net"] - 12050) < 0.01)
    expect_rule_error("منع حذف حركة داخل سنة مغلقة",
                      lambda: repo.delete_receipt(conn, rv1))
    repo.set_year_status(conn, y2026, "open")
    repo.delete_receipt(conn, rv1)  # الآن ينجح
    check("حذف بعد إعادة فتح السنة",
          calc.customer_balance(conn, cust) == 18500)

    print(f"\n🎉 كل الاختبارات نجحت ({PASS} فحصاً). قاعدة اختبار: "
          f"{db.db_path()}")


if __name__ == "__main__":
    main()
