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


def _count_auto_vouchers(conn) -> int:
    return int(conn.execute(
        "SELECT COUNT(*) FROM payment_vouchers WHERE source_expense_id IS NOT NULL"
    ).fetchone()[0])


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
        "attachments": [], "vat_rate": 15,
        "trips": [
            {"vehicle_id": veh, "driver_id": driver, "from_loc": "جدة",
             "to_loc": "مكة", "qty": 5, "unit_price": 1000,
             "container_numbers": ["CONT1", "CONT2"], "notes": "",
             "expenses": [
                 {"expense_type": "trip", "qty": 1, "unit_amount": 300,
                  "source": "cash", "account_kind": "cashbox", "account_id": cb,
                  "notes": "تريب"},
                 {"expense_type": "fuel", "qty": 2, "unit_amount": 100,
                  "source": "cash", "account_kind": "cashbox", "account_id": cb,
                  "notes": "بنزين"}]},
            {"vehicle_id": None, "driver_id": driver, "from_loc": "جدة",
             "to_loc": "الرياض", "qty": 1, "unit_price": 8000, "notes": "",
             "expenses": [{"expense_type": "card", "qty": 1, "unit_amount": 150,
                           "source": "cash", "account_kind": "cashbox",
                           "account_id": cb, "notes": "كارتة"}]},
        ]})
    t = calc.invoice_totals(conn, inv)
    check("إجماليات الفاتورة", t["trips_total"] == 13000 and t["expenses_total"] == 650
          and t["expected_profit"] == 12350)
    check("ضريبة القيمة المضافة على الفاتورة",
          t["vat_amount"] == 1950 and t["customer_total"] == 14950)
    check("رصيد العميل بعد الفاتورة (شامل الضريبة)",
          calc.customer_balance(conn, cust) == 19950)
    check("سندات الدفع التلقائية من المصروفات النقدية",
          _count_auto_vouchers(conn) == 3
          and calc.account_balance(conn, "cashbox", cb) == 9350)

    # ---------------- سندات القبض ----------------
    rv1 = repo.save_receipt(conn, {"date": "2026-02-20", "account_kind": "cashbox",
                                   "account_id": cb, "voucher_type": "customer",
                                   "customer_id": cust, "amount": 6000,
                                   "description": "دفعة أولى"})
    repo.save_receipt(conn, {"date": "2026-02-21", "account_kind": "bank",
                             "account_id": bnk, "voucher_type": "other",
                             "customer_id": None, "amount": 500,
                             "description": "بيع خردة"})
    check("رصيد العميل بعد التحصيل", calc.customer_balance(conn, cust) == 13950)
    check("رصيد الخزينة بعد القبض",
          calc.account_balance(conn, "cashbox", cb) == 15350)
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
    # السند التلقائي (150) مستثنى من المصاريف اللاحقة حتى لا يُحتسب مرتين
    check("ربح النقلة الفعلي (مع سند لاحق)", tp["net"] == 8000 - 150 - 400)
    check("رصيد الخزينة بعد الدفعات", calc.account_balance(conn, "cashbox", cb) == 13950)
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
    check("رصيد الخزينة بعد الراتب", calc.account_balance(conn, "cashbox", cb) == 11350)
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
    check("كشف حساب العميل", st["opening"] == 5000 and st["closing"] == 13950
          and st["invoiced"] == 14950 and st["collected"] == 6000
          and len(st["rows"]) == 2)
    ast = calc.account_statement(conn, "cashbox", cb, "2026-01-01", "2026-12-31")
    check("كشف حساب الخزينة", ast["opening"] == 10000 and ast["closing"] == 11350
          and len(ast["rows"]) == 8)  # قبض + 3 تلقائية + 3 يدوية + راتب
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
    check("P&L: ضريبة محصلة معلومة منفصلة", pnl["vat_collected"] == 1950)
    check("P&L: المصروفات", pnl["total_expenses"] == 650 + 400 + 2600 + 800 + 300 + 200)
    check("P&L: الصافي", pnl["net"] == 8550)

    # ---------------- عدم تعديل الفاتورة بعد الإصدار ----------------
    full = calc.get_invoice_full(conn, inv)
    full["trips"][0]["unit_price"] = 1100
    expect_rule_error("منع تعديل فاتورة بعد إصدارها",
                      lambda: repo.save_invoice(conn, full, inv))
    expect_rule_error("منع حذف فاتورة بعد إصدارها",
                      lambda: repo.delete_invoice(conn, inv))

    # منع جعل رصيد الخزينة سالباً
    expect_rule_error("منع صرف يفوق رصيد الخزينة",
                      lambda: repo.save_payment(conn, {
                          "date": "2026-03-04", "account_kind": "cashbox",
                          "account_id": cb, "voucher_type": "general",
                          "amount": 999999, "description": "صرف مبالغ"}))

    # حذف الراتب => عودة السلفة غير مسددة
    repo.delete_payroll(conn, pay)
    advs = repo.employee_advances(conn, driver)
    check("عودة السلفة بعد حذف الراتب",
          advs[0]["remaining"] == 800
          and calc.account_balance(conn, "cashbox", cb) == 13950)

    # ---------------- قاعدة السنوات على التعديل/الحذف ----------------
    expect_rule_error("منع تعديل حركة بتاريخ خارج السنة المفتوحة",
                      lambda: repo.save_receipt(conn, {
                          "date": "2027-01-05", "account_kind": "cashbox",
                          "account_id": cb, "voucher_type": "other",
                          "amount": 100}, rv1))
    repo.set_year_status(conn, y2026, "closed")
    snap = repo.create_snapshot(conn, y2026)
    # الإيرادات 13500 − (مباشرة 650 + رحلات يدوية 400 + رواتب 0 (حُذف)
    # + سلف 800 + صيانة 300 + عامة 200) = 11150
    check("لقطة الإغلاق", snap["year"] == 2026 and len(snap["customers"]) == 1
          and abs(snap["pnl"]["net"] - 11150) < 0.01)
    expect_rule_error("منع حذف حركة داخل سنة مغلقة",
                      lambda: repo.delete_receipt(conn, rv1))
    repo.set_year_status(conn, y2026, "open")
    repo.delete_receipt(conn, rv1)  # الآن ينجح
    check("حذف بعد إعادة فتح السنة",
          calc.customer_balance(conn, cust) == 19950)

    # ---------------- إشعار دائن بمرتجع نقلة (بديل التعديل) ----------------
    trips2 = conn.execute("SELECT id FROM invoice_trips WHERE invoice_id=? "
                          "ORDER BY id", (inv,)).fetchall()
    note_id = repo.save_credit_debit_note(conn, {
        "note_type": "credit", "invoice_id": inv, "customer_id": cust,
        "date": "2026-04-01", "trip_ids": [trips2[1]["id"]],
        "reason": "مرتجع نقلة الرياض"})
    check("إشعار دائن بمرتجع نقلة (8000 + ضريبة 1200)",
          repo.get_credit_debit_note(conn, note_id)["total"] == 9200
          and calc.customer_balance(conn, cust) == 10750)
    expect_rule_error("منع إرجاع نفس النقلة مرتين",
                      lambda: repo.save_credit_debit_note(conn, {
                          "note_type": "credit", "invoice_id": inv,
                          "customer_id": cust, "date": "2026-04-02",
                          "trip_ids": [trips2[1]["id"]], "reason": "تكرار"}))

    print(f"\n🎉 كل الاختبارات نجحت ({PASS} فحصاً). قاعدة اختبار: "
          f"{db.db_path()}")


if __name__ == "__main__":
    main()
