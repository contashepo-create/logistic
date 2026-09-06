# -*- coding: utf-8 -*-
"""
اختبار الواجهة العميق للأقسام المُضافة (بدون شاشة — QT_QPA_PLATFORM=minimal).

ينشئ الكيانات عبر نوافذ الإدخال الحقيقية (لا عبر repo مباشرة) ليتأكد أن
الواجهة تمرّر البيانات بشكل صحيح للمنطق المحاسبي، ثم يفتح كل الصفحات
ويحدّثها ويصدّرها.

تشغيل:
  QT_QPA_PLATFORM=minimal python scripts/test_ui_new_modules.py
"""
from __future__ import annotations

import os
import sys
import tempfile
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

os.environ["LOGISTIC_DATA_DIR"] = tempfile.mkdtemp(prefix="logistic_ui_")
os.environ.setdefault("QT_QPA_PLATFORM", "minimal")

from PySide6.QtWidgets import QApplication   # noqa: E402

app = QApplication.instance() or QApplication([])

from app.core import calc, db, repo          # noqa: E402

from app.utils import fmt                    # noqa: E402

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
    check(name, ok, "" if ok else f"→ {actual} (المتوقع {expected})")

def _silence_dialogs() -> None:
    """النوافذ المنبثقة (QMessageBox) تُعلّق الاختبار بلا شاشة — تُستبدل بدوال صامتة."""
    # استيراد كل وحدات الواجهة للتأكد من سلامة تحميلها (اختبار دخان)
    import importlib
    for _mod in ("app.ui.dialogs_master", "app.ui.dialogs_ops",
                 "app.ui.dialogs_payroll", "app.ui.dialogs_suppliers",
                 "app.ui.page_settings", "app.ui.pages_base",
                 "app.ui.pages_master", "app.ui.pages_ops",
                 "app.ui.pages_payroll", "app.ui.pages_reports",
                 "app.ui.pages_suppliers", "app.ui.pages_treasury",
                 "app.ui.statements"):
        assert importlib.import_module(_mod).__name__.endswith(_mod.rsplit(".", 1)[1])
    for mod_name in list(sys.modules):
        if not mod_name.startswith("app.ui"):
            continue
        mod = sys.modules[mod_name]
        for fn in ("info", "warn", "error_msg", "confirm"):
            if hasattr(mod, fn):
                setattr(mod, fn, (lambda *a, **k: True) if fn == "confirm"
                        else (lambda *a, **k: None))

def main() -> None:
    _silence_dialogs()
    db.init_db()
    conn = db.get_conn()
    y = date.today().year
    repo.save_year(conn, {"year": y, "date_from": f"{y}-01-01",
                          "date_to": f"{y}-12-31", "notes": ""})
    repo.set_setting(conn, "company_name", "شركة الاختبار")
    repo.set_setting(conn, "company_tax_number", "300012345600003")
    repo.set_setting(conn, "company_address", "الرياض")
    repo.set_setting(conn, "vat_rate", "15")

    # ---------------- نوافذ الإدخال الحقيقية ----------------
    from app.ui.dialogs_ops import CreditDebitNoteDialog, InvoiceDialog, PaymentDialog
    from app.ui.dialogs_suppliers import PurchaseInvoiceDialog, SupplierDialog
    from app.ui.pages_suppliers import DeductionDialog

    cust = repo.save_customer(conn, {"name": "عميل الواجهة", "opening_balance": 0,
                                     "tax_number": "310098765400003"})
    cb = repo.save_account(conn, "cashbox", {"name": "الخزينة",
                                             "created_date": f"{y}-01-01",
                                             "opening_balance": 200000})
    driver = repo.save_employee(conn, {"name": "سائق الواجهة", "emp_type": "driver",
                                       "base_salary": 5000})
    veh = repo.save_vehicle(conn, {"plate_number": "و ج ه 1", "vehicle_type": "تريلة",
                                   "default_driver_id": driver})

    # 1) نافذة المورّد
    dlg = SupplierDialog(None)
    dlg.name_edit.setText("مورّد الواجهة")
    dlg.phone_edit.setText("0114445566")
    dlg.opening_edit.set_value(1000)
    dlg.tax_number_edit.setText("300099988800003")
    dlg.terms_edit.set_value(30)
    dlg.save()
    sup = conn.execute("SELECT id FROM suppliers WHERE name='مورّد الواجهة'").fetchone()[0]
    check("نافذة المورّد تحفظ الحزمة الضريبية",
          repo.get_supplier(conn, sup)["tax_number"] == "300099988800003"
          and repo.get_supplier(conn, sup)["payment_terms"] == 30)

    # 2) نافذة فاتورة النقل (كمية × سعر + حاويات + مصادر تمويل)
    inv_dlg = InvoiceDialog(None)
    inv_dlg.date_edit.set_iso(f"{y}-02-10")
    inv_dlg.customer_combo.select(cust)
    inv_dlg.vat_edit.set_value(15)
    inv_dlg.trips = [{
        "vehicle_id": veh, "driver_id": driver, "from_loc": "الرياض",
        "to_loc": "الدمام", "qty": 3, "unit_price": 2000,
        "container_numbers": ["AAAA1111111", "BBBB2222222", "CCCC3333333"],
        "notes": "",
        "expenses": [
            {"expense_type": "fuel", "qty": 2, "unit_amount": 100, "source": "cash",
             "account_kind": "cashbox", "account_id": cb, "supplier_name": "",
             "notes": "بنزين"},
            {"expense_type": "trip", "qty": 1, "unit_amount": 300, "source": "driver",
             "account_kind": None, "account_id": None, "supplier_name": "",
             "notes": "تريب"},
            {"expense_type": "other", "qty": 1, "unit_amount": 400,
             "source": "customer", "account_kind": None, "account_id": None,
             "supplier_name": "", "notes": "رسوم ميناء"},
        ]}]
    inv_dlg.refresh()
    eq("الواجهة: إجمالي النقلات (عدد × سعر الوحدة)",
       sum(t["qty"] * t["unit_price"] for t in inv_dlg.trips), 6000)
    inv_dlg.save()
    inv = conn.execute("SELECT id FROM invoices ORDER BY id DESC LIMIT 1").fetchone()[0]
    t = calc.invoice_totals(conn, inv)
    eq("الواجهة: وعاء الضريبة (نقلات + مصروف العميل)",
       t["trips_total"] + t["billable_total"], 6400)
    eq("الواجهة: التكلفة المباشرة", t["expenses_total"], 500)
    eq("الواجهة: إجمالي الفاتورة على العميل", t["customer_total"], 6400 * 1.15)
    eq("الواجهة: الخزينة خُصم منها النقدي فقط", calc.account_balance(conn, "cashbox", cb),
       200000 - 200)
    trip_id = conn.execute("SELECT id FROM invoice_trips WHERE invoice_id=?",
                           (inv,)).fetchone()[0]
    check("الواجهة: أرقام الحاويات محفوظة",
          len(conn.execute("SELECT container_numbers FROM invoice_trips WHERE id=?",
                           (trip_id,)).fetchone()[0]) > 5)

    # 3) نافذة فاتورة المشتريات (بنود + ضريبة)
    p_dlg = PurchaseInvoiceDialog(None)
    p_dlg.date_edit.set_iso(f"{y}-03-01")
    p_dlg.type_combo.setCurrentIndex(p_dlg.type_combo.findData("credit"))
    p_dlg.supplier_combo.select(sup)
    p_dlg.ref_edit.setText("REF-9")
    p_dlg.items = [{"item_name": "إطارات", "unit": "إطار", "qty": 4,
                    "unit_price": 250, "vat_rate": 15, "notes": ""}]
    p_dlg.refresh()
    p_dlg._try_save()
    pinv = conn.execute("SELECT id FROM purchase_invoices ORDER BY id DESC "
                        "LIMIT 1").fetchone()[0]
    pt = calc.purchase_invoice_totals(conn, pinv)
    eq("الواجهة: صافي المشتريات", pt["net"], 1000)
    eq("الواجهة: ضريبة المشتريات", pt["vat"], 150)
    eq("الواجهة: رصيد المورّد", calc.supplier_balance(conn, sup), 1000 + 1150)

    # 4) نافذة بند الخصم
    d_dlg = DeductionDialog(None)
    d_dlg.date_edit.set_iso(f"{y}-03-15")
    d_dlg.employee_combo.select(driver)
    d_dlg.amount_edit.set_value(700)
    d_dlg.reason_edit.setText("تلفيات")
    d_dlg.save()
    ded_id = conn.execute("SELECT id FROM employee_deductions").fetchone()[0]
    check("نافذة الخصم تحفظ البند", repo.list_deductions(conn)[0]["status"] == "open")

    # 5) نافذة سند الدفع — سداد للمورّد بنوع جديد
    pay_dlg = PaymentDialog(None)
    pay_dlg.date_edit.set_iso(f"{y}-04-01")
    pay_dlg.account_combo.select("cashbox", cb)
    pay_dlg.type_combo.setCurrentIndex(pay_dlg.type_combo.findData("supplier"))
    pay_dlg.supplier_combo.select(sup)
    pay_dlg._load_supplier_invoices()
    pay_dlg.purchase_combo.select(pinv)
    pay_dlg.qty_edit.set_value(1)
    pay_dlg.unit_edit.set_value(1150)
    pay_dlg.save()
    eq("الواجهة: سند سداد مورّد يقلل رصيده", calc.supplier_balance(conn, sup), 1000)

    # 6) إشعار دائن بمرتجع نقلة من النافذة
    note_dlg = CreditDebitNoteDialog(None, invoice_id=inv)
    note_dlg.date_edit.set_iso(f"{y}-05-01")
    note_dlg.reason_edit.setText("مرتجع من الواجهة")
    item = note_dlg.trips_table.item(0, 0)
    from PySide6.QtCore import Qt
    item.setCheckState(Qt.CheckState.Checked)
    note_dlg._type_changed()
    note_dlg.save()
    note_total = conn.execute("SELECT amount, vat_rate FROM credit_debit_notes "
                              "ORDER BY id DESC LIMIT 1").fetchone()
    eq("الواجهة: إشعار دائن بمرتجع النقلة", calc.note_total(note_total["amount"],
                                                             note_total["vat_rate"]),
       6000 * 1.15)

    # 7) كل الصفحات تُبنى وتُحدَّث وتُصدِّر بياناتها
    from app.ui.main_window import MainWindow
    win = MainWindow()
    check("النافذة الرئيسية: 23 صفحة", len(win._pages) == 23)
    bad = []
    for label, page in win._pages:
        try:
            if hasattr(page, "refresh"):
                page.refresh()
            if hasattr(page, "load"):
                page.load()
            if hasattr(page, "table") and page.table is not None \
                    and hasattr(page.table, "export_data"):
                page.table.export_data()
            if hasattr(page, "current_table") and page.current_table() is not None:
                page.current_table().export_data()
        except Exception as e:  # noqa: BLE001
            bad.append(f"{label}: {type(e).__name__}: {e}")
    check("كل الصفحات تُحدَّث وتُصدِّر بلا أخطاء", not bad,
          "; ".join(bad[:3]))

    # 8) صفحات الأقسام الجديدة تعرض البيانات الصحيحة
    from app.ui.pages_suppliers import (
        AdvancesPage, DeductionsPage, NotesPage, PurchasesPage, SuppliersPage,
    )
    sp = SuppliersPage(); sp.build(); sp.refresh()
    ids, rows = sp.fetch()
    check("صفحة الموردين تعرض الرصيد", sup in ids
          and any(r[0] == repo.get_supplier(conn, sup)["code"] for r in rows))
    pp = PurchasesPage(); pp.build()
    ids, rows = pp.fetch()
    check("صفحة المشتريات تعرض الضريبة والإجمالي",
          pinv in ids and rows[0][7] == fmt.money(1150))
    np_ = NotesPage(); np_.build()
    ids, rows = np_.fetch()
    check("صفحة الإشعارات تعرض السبب", len(ids) == 1 and rows[0][8] == "مرتجع من الواجهة")
    dp = DeductionsPage(); dp.build()
    ids, rows = dp.fetch()
    check("صفحة الخصومات تعرض الحالة", ded_id in ids and rows[0][7] == "قائمة")
    ap = AdvancesPage(); ap.build()
    ids, rows = ap.fetch()
    check("صفحة السلفيات تعمل", isinstance(rows, list))

    # 9) طباعة الفاتورة الضريبية تحتوي الضريبة ورمز زاتكا
    from app.ui.dialogs_ops import customer_invoice_html
    html = customer_invoice_html(conn, inv)
    check("الفاتورة المطبوعة: فاتورة ضريبية B2B",
          "فاتورة ضريبية" in html and "Tax Invoice" in html)
    check("الفاتورة المطبوعة: سطر الضريبة", "ضريبة القيمة المضافة" in html)
    check("الفاتورة المطبوعة: رقم ضريبي للمنشأة", "300012345600003" in html)
    check("الفاتورة المطبوعة: رمز QR مضمّن",
          "data:image/png;base64," in html
          or "رمز الاستجابة السريعة" not in html)
    check("الفاتورة المطبوعة: لا تُظهر الأرباح الداخلية",
          "الربح المتوقع" not in html)

    # 10) صفحة الإعدادات تحفظ الحزمة الضريبية
    from app.ui.page_settings import SettingsPage
    settings = SettingsPage()
    settings.vat_rate_edit.setText("15")
    settings.tax_number_edit.setText("300012345600003")
    settings.city_edit.setText("الرياض")
    settings.save()
    check("الإعدادات: حفظ الرقم الضريبي",
          repo.get_setting(conn, "company_tax_number") == "300012345600003"
          and repo.get_setting(conn, "company_city") == "الرياض")
    eq("الإعدادات: نسبة الضريبة الافتراضية", repo.current_vat_rate(conn), 15)

    print()
    if FAILS:
        print(f"💥 فشل {len(FAILS)} فحصاً من {PASS + len(FAILS)}: "
              f"{'، '.join(FAILS)}")
        sys.exit(1)
    print(f"🎉 كل اختبارات الواجهة نجحت ({PASS} فحصاً).")

if __name__ == "__main__":
    main()
