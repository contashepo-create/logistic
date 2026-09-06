# -*- coding: utf-8 -*-
"""
اختبار المطابقة المحاسبية مع نسخة الويب (logistics-web).

يغطي الأقسام التي أُضيفت لسطح المكتب لتطابق الويب:
  1) ضريبة القيمة المضافة + الحزمة الضريبية + زاتكا (QR / TLV / نوع الفاتورة)
  2) الموردون وفواتير المشتريات (نقدية وآجلة) + كشف حساب المورّد + أعمار الديون
  3) الإشعارات الدائنة والمدينة
  4) مصدر تمويل مصروف النقلة (نقداً / عهدة سائق / آجل مورد / على العميل)
  5) بنود الخصومات المُتتبَّعة وتسوياتها في المسيرات
  6) أنواع سندات الدفع الجديدة (مورّد / مشتريات / سحب مالك)
  7) منع الرصيد السالب
  8) ترحيل السنة المالية مع الأرصدة الافتتاحية

تشغيل:  python scripts/test_web_parity.py
"""
from __future__ import annotations

import base64
import os
import sys
import tempfile
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

os.environ["LOGISTIC_DATA_DIR"] = tempfile.mkdtemp(prefix="logistic_parity_")

from app.core import calc, db, repo, tax           # noqa: E402
from app.core.rules import RuleError               # noqa: E402

PASS = 0
FAILS: list[str] = []


def check(name: str, cond: bool, extra: str = "") -> None:
    global PASS
    if not cond:
        FAILS.append(name)
        print(f"❌ FAILED: {name} {extra}")
        return
    PASS += 1
    print(f"✅ {name} {extra}")


def eq(name: str, actual, expected) -> None:
    ok = abs(float(actual) - float(expected)) < 0.011
    check(name, ok, f"→ {actual} (المتوقع {expected})" if not ok else "")


def expect_error(name: str, fn) -> None:
    try:
        fn()
    except RuleError as e:
        check(name, True, f"— ({str(e)[:60]})")
        return
    except Exception as e:  # noqa: BLE001
        check(name, False, f"— خطأ غير متوقع: {e}")
        return
    check(name, False, "— لم يُرفض الإجراء!")


# ===========================================================================
def main() -> None:
    db.init_db()
    conn = db.get_conn()

    # ---------------- 0) الإعدادات والبيانات الأساسية ----------------
    repo.set_setting(conn, "company_name", "شركة الأفق للنقل")
    repo.set_setting(conn, "vat_rate", "15")
    repo.set_setting(conn, "company_tax_number", "300012345600003")
    repo.set_setting(conn, "company_address", "الرياض - حي العليا")
    year = date.today().year
    repo.save_year(conn, {"year": year, "date_from": f"{year}-01-01",
                          "date_to": f"{year}-12-31", "notes": ""})
    d = lambda day: f"{year}-{day}"  # noqa: E731

    cust = repo.save_customer(conn, {
        "name": "مؤسسة الخليج", "phone": "0555111222", "address": "الرياض",
        "opening_balance": 0, "tax_number": "310098765400003",
        "commercial_reg": "1010234567", "tax_status": "taxable",
        "country": "SA", "region": "الرياض", "city": "الرياض",
        "postal_code": "12271", "building_no": "4321"})
    eq("نسبة الضريبة المعتمدة", repo.current_vat_rate(conn), 15)

    expect_error("رفض رقم ضريبي غير صالح",
                 lambda: repo.save_customer(conn, {"name": "خطأ",
                                                   "tax_number": "12345"}))
    expect_error("رفض سجل تجاري غير صالح",
                 lambda: repo.save_customer(conn, {"name": "خطأ",
                                                   "commercial_reg": "12"}))

    driver = repo.save_employee(conn, {"name": "خالد السائق", "nationality": "سعودي",
                                       "phone": "0500000001", "emp_type": "driver",
                                       "base_salary": 4000, "notes": ""})
    check("الراتب الأساسي المسجّل للموظف",
          repo.get_employee(conn, driver)["base_salary"] == 4000)
    veh = repo.save_vehicle(conn, {"plate_number": "أ ب ج 999",
                                   "vehicle_type": "تريلة",
                                   "default_driver_id": driver, "notes": ""})
    cb = repo.save_account(conn, "cashbox", {"name": "الخزينة الرئيسية",
                                             "created_date": d("01-01"),
                                             "opening_balance": 100000, "notes": ""})
    bnk = repo.save_account(conn, "bank", {"name": "بنك الراجحي",
                                           "created_date": d("01-01"),
                                           "account_number": "1234567890",
                                           "iban": "SA00 8000 0000 6080 1016 7519",
                                           "opening_balance": 0, "notes": ""})

    # ---------------- 1) زاتكا ----------------
    qr = tax.build_zatca_qr("شركة الأفق للنقل", "300012345600003",
                            f"{year}-06-01T10:00:00Z", 1150.0, 150.0)
    tags = tax.parse_zatca_qr(qr)
    check("QR زاتكا: التاجات الخمسة",
          set(tags) == {1, 2, 3, 4, 5} and tags[1] == "شركة الأفق للنقل"
          and tags[2] == "300012345600003" and tags[4] == "1150.00"
          and tags[5] == "150.00")
    check("QR زاتكا: ترميز TLV صحيح",
          base64.b64decode(qr)[0:2] == bytes([1, len("شركة الأفق للنقل".encode())]))
    check("فاتورة ضريبية (B2B) لمنشأة خاضعة برقم ضريبي",
          tax.zatca_invoice_type({"tax_number": "310098765400003",
                                  "tax_status": "taxable"}) == "standard")
    check("فاتورة مبسّطة (B2C) لمن لا رقم ضريبي له",
          tax.zatca_invoice_type({"tax_number": "", "tax_status": "taxable"})
          == "simplified")
    check("حقول زاتكا الناقصة", "اسم البائع" in tax.zatca_missing_fields(
        seller_name="", seller_vat="bad", invoice_type="standard"))
    check("العنوان الوطني مصاغ بالترتيب المعتمد",
          "مبنى 4321" in tax.format_national_address(
              repo.get_customer(conn, cust)))

    # ---------------- 2) فاتورة نقل بمصادر تمويل مختلفة ----------------
    inv = repo.save_invoice(conn, {
        "date": d("02-10"), "customer_id": cust, "vat_rate": 15, "notes": "",
        "attachments": [],
        "trips": [{
            "vehicle_id": veh, "driver_id": driver, "from_loc": "الرياض",
            "to_loc": "جدة", "qty": 2, "unit_price": 5000,
            "container_numbers": ["MSKU1234567", "TCLU7654321"], "notes": "",
            "expenses": [
                # نقدي من الخزينة → سند دفع تلقائي
                {"expense_type": "fuel", "qty": 2, "unit_amount": 150,
                 "source": "cash", "account_kind": "cashbox", "account_id": cb,
                 "notes": "بنزين"},
                # من عهدة السائق → لا يحرّك خزينة
                {"expense_type": "trip", "qty": 1, "unit_amount": 400,
                 "source": "driver", "notes": "تريب"},
                # آجل على مورد → لا يحرّك خزينة
                {"expense_type": "card", "qty": 1, "unit_amount": 250,
                 "source": "supplier", "supplier_name": "محطة الشرق", "notes": "كارتة"},
                # يتحمّله العميل → إيراد وليس تكلفة
                {"expense_type": "other", "qty": 1, "unit_amount": 500,
                 "source": "customer", "notes": "رسوم دخول ميناء"},
            ]}]}
        )
    t = calc.invoice_totals(conn, inv)
    # النقلات 10000 + مصروف العميل 500 = 10500 وعاء الضريبة
    eq("إيراد الفاتورة قبل الضريبة (نقلات + مصروف العميل)", t["trips_total"]
       + t["billable_total"], 10500)
    eq("التكلفة المباشرة تستثني مصروف العميل", t["expenses_total"], 300 + 400 + 250)
    eq("ضريبة الفاتورة", t["vat_amount"], 1575)
    eq("إجمالي الفاتورة على العميل", t["customer_total"], 12075)
    eq("الربح المتوقع", t["expected_profit"], 10500 - 950)
    auto = conn.execute(
        "SELECT COUNT(*) FROM payment_vouchers WHERE source_expense_id IS NOT NULL"
    ).fetchone()[0]
    check("سند دفع تلقائي واحد فقط (للمصروف النقدي)", auto == 1)
    eq("الخزينة خُصم منها المصروف النقدي فقط", calc.account_balance(conn, "cashbox", cb),
       100000 - 300)
    eq("رصيد العميل", calc.customer_balance(conn, cust), 12075)

    expect_error("منع تكرار رقم حاوية داخل الفاتورة",
                 lambda: repo.save_invoice(conn, {
                     "date": d("02-11"), "customer_id": cust, "vat_rate": 15,
                     "trips": [{"from_loc": "أ", "to_loc": "ب", "qty": 2,
                                "unit_price": 100,
                                "container_numbers": ["X1", "X1"]}]}))
    expect_error("منع حاويات أكثر من عدد النقلات",
                 lambda: repo.save_invoice(conn, {
                     "date": d("02-11"), "customer_id": cust, "vat_rate": 15,
                     "trips": [{"from_loc": "أ", "to_loc": "ب", "qty": 1,
                                "unit_price": 100,
                                "container_numbers": ["X1", "X2"]}]}))
    expect_error("منع مصروف نقدي بلا جهة صرف",
                 lambda: repo.save_invoice(conn, {
                     "date": d("02-11"), "customer_id": cust, "vat_rate": 15,
                     "trips": [{"from_loc": "أ", "to_loc": "ب", "qty": 1,
                                "unit_price": 100,
                                "expenses": [{"expense_type": "fuel", "qty": 1,
                                              "unit_amount": 10, "source": "cash"}]}]}))

    # ---------------- 3) الموردون وفواتير المشتريات ----------------
    sup = repo.save_supplier(conn, {
        "name": "محطة الشرق للوقود", "name_en": "Alsharq Fuel",
        "phone": "0114445566", "email": "info@alsharq.sa",
        "contact_person": "أبو فهد", "address": "الرياض",
        "opening_balance": 2000, "payment_terms": 30,
        "tax_number": "300099988800003", "tax_status": "taxable",
        "country": "SA", "region": "الرياض", "city": "الرياض", "notes": ""})
    check("كود المورّد التلقائي", repo.get_supplier(conn, sup)["code"].startswith("SUP"))
    eq("رصيد المورّد الافتتاحي", calc.supplier_balance(conn, sup), 2000)

    # فاتورة آجلة: بنود بنسب ضريبة مختلفة
    pinv = repo.save_purchase_invoice(conn, {
        "date": d("03-01"), "purchase_type": "credit", "supplier_id": sup,
        "supplier_ref": "A-1001", "expense_category": "fuel",
        "vehicle_id": veh, "vat_rate": 15, "vat_included": False,
        "items": [{"item_name": "ديزل", "unit": "لتر", "qty": 100,
                   "unit_price": 10, "vat_rate": 15},
                  {"item_name": "خدمة معفاة", "unit": "مرة", "qty": 1,
                   "unit_price": 200, "vat_rate": 0}],
        "notes": ""})
    pt = calc.purchase_invoice_totals(conn, pinv)
    eq("صافي المشتريات قبل الضريبة", pt["net"], 1200)
    eq("ضريبة المشتريات (بند معفى ضمن نفس الفاتورة)", pt["vat"], 150)
    eq("إجمالي المشتريات شامل الضريبة", pt["total"], 1350)
    eq("رصيد المورّد بعد الفاتورة الآجلة", calc.supplier_balance(conn, sup), 3350)
    eq("الخزينة لم تتأثر بالفاتورة الآجلة", calc.account_balance(conn, "cashbox", cb),
       100000 - 300)

    # فاتورة نقدية بأسعار شاملة الضريبة → سند دفع تلقائي
    pinv_cash = repo.save_purchase_invoice(conn, {
        "date": d("03-05"), "purchase_type": "cash", "supplier_id": None,
        "expense_category": "maintenance", "vehicle_id": veh,
        "account_kind": "cashbox", "account_id": cb, "vat_rate": 15,
        "vat_included": True,
        "items": [{"item_name": "تغيير زيت", "unit": "مرة", "qty": 1,
                   "unit_price": 115, "vat_rate": 15}],
        "notes": ""})
    pt2 = calc.purchase_invoice_totals(conn, pinv_cash)
    eq("استخراج الصافي من سعر شامل الضريبة", pt2["net"], 100)
    eq("ضريبة سعر شامل", pt2["vat"], 15)
    eq("الخزينة بعد الشراء النقدي", calc.account_balance(conn, "cashbox", cb),
       100000 - 300 - 115)
    check("سند دفع تلقائي للشراء النقدي",
          conn.execute("SELECT COUNT(*) FROM payment_vouchers WHERE voucher_type='purchase'"
                       ).fetchone()[0] == 1)

    expect_error("منع فاتورة آجلة بلا مورّد",
                 lambda: repo.save_purchase_invoice(conn, {
                     "date": d("03-06"), "purchase_type": "credit",
                     "supplier_id": None, "expense_category": "fuel",
                     "items": [{"item_name": "x", "qty": 1, "unit_price": 10}]}))
    expect_error("منع فاتورة نقدية بلا جهة دفع",
                 lambda: repo.save_purchase_invoice(conn, {
                     "date": d("03-06"), "purchase_type": "cash",
                     "account_kind": None, "expense_category": "fuel",
                     "items": [{"item_name": "x", "qty": 1, "unit_price": 10}]}))
    expect_error("منع بند مصروف غير معروف",
                 lambda: repo.save_purchase_invoice(conn, {
                     "date": d("03-06"), "purchase_type": "cash",
                     "account_kind": "cashbox", "account_id": cb,
                     "expense_category": "unknown_cat",
                     "items": [{"item_name": "x", "qty": 1, "unit_price": 10}]}))

    # سداد للمورّد
    pay_sup = repo.save_payment(conn, {
        "date": d("04-01"), "account_kind": "cashbox", "account_id": cb,
        "voucher_type": "supplier", "supplier_id": sup,
        "purchase_invoice_id": pinv, "amount": 1350, "description": "سداد فاتورة"})
    eq("رصيد المورّد بعد السداد", calc.supplier_balance(conn, sup), 2000)
    sst = calc.supplier_statement(conn, sup, f"{year}-01-01", f"{year}-12-31")
    check("كشف حساب المورّد",
          sst["totals"]["credit"] == 1350 and sst["totals"]["debit"] == 1350
          and sst["closing"] == 2000 and len(sst["rows"]) == 3)

    # ---------------- 4) سحب المالك ----------------
    repo.save_payment(conn, {"date": d("04-05"), "account_kind": "cashbox",
                             "account_id": cb, "voucher_type": "owner",
                             "amount": 500, "description": ""})
    check("البيان الافتراضي لسحب المالك",
          conn.execute("SELECT description FROM payment_vouchers "
                       "ORDER BY id DESC LIMIT 1").fetchone()[0]
          == "سحب نقدي لصاحب المنشأة")

    # ---------------- 5) أعمار الديون ----------------
    sup2 = repo.save_supplier(conn, {"name": "ورشة الطريق", "opening_balance": 0})
    today = date.today()
    # 10 أيام (حتى 30) / 45 يوماً (31-60) / 75 يوماً (61-90)
    for days_ago, amount in ((10, 100), (45, 200), (75, 300)):
        repo.save_purchase_invoice(conn, {
            "date": (today - timedelta(days=days_ago)).isoformat(),
            "purchase_type": "credit", "supplier_id": sup2,
            "expense_category": "spare_parts", "vat_rate": 0, "vat_included": False,
            "items": [{"item_name": "قطعة", "qty": 1, "unit_price": amount,
                       "vat_rate": 0}]})
    aging = {r["id"]: r for r in calc.suppliers_aging(conn)}[sup2]
    check("أعمار الديون: توزيع الشرائح",
          aging["current"] == 100 and aging["d31_60"] == 200
          and aging["d61_90"] == 300 and aging["over90"] == 0
          and aging["total"] == 600)
    # السداد بأسلوب الأقدم أولاً (أقدم تاريخ فاتورة): 350 تسدد 300 (الأقدم،
    # عمرها 75 يوماً) ثم 50 من التي عمرها 45 يوماً، فتبقى 150 + 100.
    repo.save_payment(conn, {"date": today.isoformat(), "account_kind": "cashbox",
                             "account_id": cb, "voucher_type": "supplier",
                             "supplier_id": sup2, "amount": 350,
                             "description": "سداد جزئي"})
    aging2 = {r["id"]: r for r in calc.suppliers_aging(conn)}[sup2]
    check("أعمار الديون: السداد FIFO (الأقدم أولاً)",
          aging2["current"] == 100 and aging2["d31_60"] == 150
          and aging2["d61_90"] == 0 and aging2["over90"] == 0
          and aging2["total"] == 250)
    cust_aging = calc.customers_aging(conn)
    check("أعمار ديون العملاء تُحسب", isinstance(cust_aging, list))

    # ---------------- 6) بنود الخصومات المُتتبَّعة ----------------
    ded = repo.save_deduction(conn, {"date": d("03-10"), "employee_id": driver,
                                     "amount": 600, "reason": "مخالفة مرورية",
                                     "notes": ""})
    check("بند الخصم مفتوح", repo.list_deductions(conn)[0]["status"] == "open")
    advance = repo.save_payment(conn, {
        "date": d("03-12"), "account_kind": "cashbox", "account_id": cb,
        "voucher_type": "advance", "employee_id": driver, "quantity": 2,
        "unit_amount": 500, "description": "سلفة"})
    eq("سند دفع بكمية × قيمة وحدة", conn.execute(
        "SELECT amount, quantity, unit_amount FROM payment_vouchers WHERE id=?",
        (advance,)).fetchone()[0], 1000)

    pay = repo.save_payroll(conn, {
        "date": d("04-10"), "employee_id": driver, "period_year": year,
        "period_month": 3, "account_kind": "cashbox", "account_id": cb,
        "base_salary": 4000, "additions": 0, "other_deductions": 100,
        "settlements": [(advance, 500)],
        "deduction_settlements": [(ded, 400)], "notes": ""})
    row = repo.get_payroll(conn, pay)
    eq("الصافي = أساسي + إضافات − سلف − خصومات − أخرى", row["net_salary"],
       4000 - 500 - 400 - 100)
    eq("إجمالي خصم الخصومات في المسير", row["deduction_deduction"], 400)
    rem = calc.employee_deductions(conn, driver)[0]
    eq("المتبقي من بند الخصم", rem["remaining"], 200)
    check("حالة بند الخصم = جزئي", rem["status"] == "partial")
    eq("المتبقي من السلفة", repo.employee_advances(conn, driver)[0]["remaining"], 500)
    expect_error("منع خصم بند أكثر من المتبقي",
                 lambda: repo.save_payroll(conn, {
                     "date": d("05-10"), "employee_id": driver,
                     "period_year": year, "period_month": 4,
                     "account_kind": "cashbox", "account_id": cb,
                     "base_salary": 4000, "deduction_settlements": [(ded, 9999)]}))
    expect_error("منع تخفيض بند خصم أقل مما خُصم",
                 lambda: repo.save_deduction(conn, {
                     "date": d("03-10"), "employee_id": driver, "amount": 100,
                     "reason": "تعديل"}, ded))
    expect_error("منع حذف بند خصم عليه تسويات",
                 lambda: repo.delete_deduction(conn, ded))

    emp_st = calc.employee_statement(conn, driver)
    eq("كشف الموظف: إجمالي الخصومات", emp_st["totals"]["deductions_total"], 600)
    eq("كشف الموظف: المتبقي من الخصومات", emp_st["totals"]["deductions_remaining"], 200)
    eq("كشف الموظف: المقيّد على عهدة السائق", emp_st["totals"]["driver_owed_total"], 400)

    # ---------------- 7) منع الرصيد السالب ----------------
    bal = calc.account_balance(conn, "cashbox", cb)
    expect_error("منع صرف يفوق رصيد الخزينة",
                 lambda: repo.save_payment(conn, {
                     "date": d("05-15"), "account_kind": "cashbox",
                     "account_id": cb, "voucher_type": "general",
                     "amount": bal + 100000, "description": "تجاوز"}))
    expect_error("منع راتب يفوق رصيد الخزينة",
                 lambda: repo.save_payroll(conn, {
                     "date": d("05-15"), "employee_id": driver,
                     "period_year": year, "period_month": 5,
                     "account_kind": "cashbox", "account_id": cb,
                     "base_salary": 999999}))
    expect_error("منع شراء نقدي يفوق رصيد الخزينة",
                 lambda: repo.save_purchase_invoice(conn, {
                     "date": d("05-15"), "purchase_type": "cash",
                     "account_kind": "cashbox", "account_id": cb,
                     "expense_category": "fuel", "vat_rate": 0,
                     "items": [{"item_name": "x", "qty": 1, "unit_price": 9999999,
                                "vat_rate": 0}]}))

    # ---------------- 8) الإشعارات الدائنة والمدينة ----------------
    debit_note = repo.save_credit_debit_note(conn, {
        "note_type": "debit", "invoice_id": inv, "customer_id": cust,
        "date": d("05-20"), "amount": 1000, "vat_rate": 15,
        "reason": "رسوم إضافية"})
    eq("إشعار مدين شامل الضريبة", repo.get_credit_debit_note(conn, debit_note)["total"],
       1150)
    before = calc.customer_balance(conn, cust)
    credit_note = repo.save_credit_debit_note(conn, {
        "note_type": "credit", "invoice_id": inv, "customer_id": cust,
        "date": d("05-25"), "amount": 500, "vat_rate": 15,
        "reason": "خصم تجاري"})
    eq("إشعار دائن يقلل المديونية", calc.customer_balance(conn, cust),
       before - 575)
    expect_error("سبب الإشعار إلزامي",
                 lambda: repo.save_credit_debit_note(conn, {
                     "note_type": "debit", "invoice_id": inv, "customer_id": cust,
                     "date": d("05-26"), "amount": 10, "reason": "  "}))
    expect_error("تاريخ الإشعار لا يسبق الفاتورة",
                 lambda: repo.save_credit_debit_note(conn, {
                     "note_type": "debit", "invoice_id": inv, "customer_id": cust,
                     "date": d("01-01"), "amount": 10, "reason": "قديم"}))
    creditable = repo.list_creditable_invoice_trips(conn, inv)
    # النقلة: 2 × 5000 = 10000 + ضريبة 15% = 11500
    check("نقلات قابلة للإرجاع بضريبتها",
          creditable[0]["amount"] == 10000 and creditable[0]["vat_amount"] == 1500
          and creditable[0]["total"] == 11500
          and creditable[0]["already_credited"] is False)

    # ---------------- 9) الأرباح والخسائر الشامل ----------------
    pnl = calc.pnl_report(conn, f"{year}-01-01", f"{year}-12-31")
    # إيرادات النقلات 10000 + مصروف العميل 500 = 10500؛ إشعارات: مدين 1150 − دائن 575
    eq("P&L: إيراد النقلات قبل الضريبة", pnl["transport_revenue"], 10500)
    eq("P&L: ضريبة محصلة", pnl["vat_collected"], 1575)
    eq("P&L: صافي الإشعارات", pnl["notes_adjust"], 575)
    eq("P&L: إجمالي الإيرادات", pnl["total_revenue"], 10500 + 575)
    # 1200 (وقود) + 100 (صيانة) + 600 (قطع غيار — ثلاث فواتير ورشة الطريق)
    eq("P&L: مشتريات (صافي قبل الضريبة)", pnl["purchase_expenses"], 1900)
    eq("P&L: بنود المشتريات مصنفة (وقود)", pnl["purchase_fuel"], 1200)
    eq("P&L: بنود المشتريات مصنفة (قطع غيار)", pnl["purchase_spare_parts"], 600)
    eq("P&L: سحب المالك", pnl["owner_withdrawals"], 500)
    eq("P&L: إجمالي المصروفات", pnl["total_expenses"],
       950 + pnl["trip_payments"] + pnl["salaries"] + pnl["advances"]
       + pnl["maintenance"] + pnl["general_expenses"] + 1900 + 500)
    eq("P&L: الصافي", pnl["net"], pnl["total_revenue"] - pnl["total_expenses"])

    # ---------------- 10) تقرير السيارة مع المشتريات ----------------
    vr = calc.vehicle_report(conn, None, None, veh)[0]
    eq("تقرير السيارة: الإيراد", vr["revenue"], 10000)
    eq("تقرير السيارة: مشترياتها", vr["purchases"], 1300)
    eq("تقرير السيارة: الصافي", vr["net"],
       vr["revenue"] - vr["direct"] - vr["maintenance"] - vr["purchases"])

    # ---------------- 11) ترحيل السنة المالية ----------------
    expect_error("منع الترحيل قبل إغلاق السنة",
                 lambda: repo.rollover_year(conn, 1, year + 1,
                                            f"{year + 1}-01-01", f"{year + 1}-12-31"))
    repo.set_year_status(conn, 1, "closed")
    new_year = repo.rollover_year(conn, 1, year + 1,
                                  f"{year + 1}-01-01", f"{year + 1}-12-31")
    check("السنة المرحّلة مفتوحة", repo.get_year(conn, new_year)["status"] == "open")
    openings = {(o["entity_type"], o["entity_id"]): o["balance"]
                for o in repo.year_opening_balances(conn, new_year)}
    eq("الرصيد الافتتاحي المرحّل للعميل", openings[("customer", cust)],
       calc.customer_balance(conn, cust))
    eq("الرصيد الافتتاحي المرحّل للخزينة", openings[("cashbox", cb)],
       calc.account_balance(conn, "cashbox", cb))
    eq("الرصيد الافتتاحي المرحّل للمورّد", openings[("supplier", sup)],
       calc.supplier_balance(conn, sup))
    check("الرصيد الافتتاحي الأصلي للعميل لم يُعدَّل",
          repo.get_customer(conn, cust)["opening_balance"] == 0)
    expect_error("منع ترحيل سنة موجودة",
                 lambda: repo.rollover_year(conn, 1, year + 1,
                                            f"{year + 1}-01-01", f"{year + 1}-12-31"))

    # ---------------- 12) لقطة الإغلاق تشمل الموردين ----------------
    snap = repo.create_snapshot(conn, 1)
    check("لقطة الإغلاق تشمل الموردين",
          "suppliers" in snap and len(snap["suppliers"]) == 2
          and "vat_collected" in snap["pnl"])

    # ---------------- الخلاصة ----------------
    print()
    if FAILS:
        print(f"💥 فشل {len(FAILS)} فحصاً من {PASS + len(FAILS)}: "
              f"{'، '.join(FAILS)}")
        sys.exit(1)
    print(f"🎉 كل اختبارات المطابقة نجحت ({PASS} فحصاً). "
          f"قاعدة اختبار: {db.db_path()}")


if __name__ == "__main__":
    main()
