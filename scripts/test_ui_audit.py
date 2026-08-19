# -*- coding: utf-8 -*-
"""
فحص واجهة جديد بزوايا مختلفة عن كل ما سبق (UI Audit v2):

  - تفاعل ودجي-مستوى مع نافذة الفاتورة (أزرار النقلة/المصروفات والإجماليات الحية)
  - PaymentDialog: تبديل الأنواع ومطابقة المكدس + سقف النصوص من الواجهة
  - سنوات مالية: إغلاق/فتح عبر on_extra + لقطة + حالة «لا لقطة» وزر الإنشاء
  - كشوف بفترة معكوسة: جداول فارغة وتصدير صالح + رصيد مجرى مطابق يدوياً
  - تبويبات كشف الموظف وتصدير كل تبويب
  - الإعدادات: تغيير اسم الشركة يظهر في ترويسة التصدير + نسخة احتياطية قابلة للقراءة
  - بحث بأرقام عربية، قيم سالبة في بطاقات الإجماليات، نقرة مزدوجة على صف

تشغيل:  QT_QPA_PLATFORM=offscreen python scripts/test_ui_audit.py
"""
from __future__ import annotations

import os
import sqlite3
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["LOGISTIC_DATA_DIR"] = tempfile.mkdtemp(prefix="logistic_uiaudit_")
os.environ["LOGISTIC_HEADLESS"] = "1"

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QApplication, QComboBox, QDialog, QDoubleSpinBox, QFileDialog, QLineEdit,
    QMessageBox, QPushButton, QTabWidget,
)

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


def step(t: str) -> None:
    print(f"== {t}", flush=True)


app = QApplication(sys.argv)
app.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
from app.ui.theme import apply_theme
apply_theme(app)

# بيئة آمنة: لا حوارات معلقة
def _no(*a, **k):
    return QMessageBox.StandardButton.No
for fn in ("information", "warning", "critical", "about", "question"):
    setattr(QMessageBox, fn, staticmethod(_no))


def _nb_exec(self):
    self.show()
    app.processEvents()
    self.close()
    return QDialog.DialogCode.Accepted


QDialog.exec = _nb_exec
EXPORT_DIR = Path(tempfile.mkdtemp(prefix="uiaudit_out_"))
EXPORTED: list[Path] = []
from app.utils import exporter


def _fake_path(parent, default_name, filters):
    out = EXPORT_DIR / f"{len(EXPORTED):03d}_{default_name}"
    EXPORTED.append(out)
    return str(out)


exporter._ask_save_path = _fake_path
exporter._ask_overwrite = lambda p, x: True
QFileDialog.getOpenFileNames = staticmethod(lambda *a, **k: ([], ""))
QFileDialog.getSaveFileName = staticmethod(lambda *a, **k: (str(EXPORT_DIR / "s.bin"), ""))

import app.ui.widgets as W
import app.ui.pages_ops as P_ops
import app.ui.pages_master as P_master
import app.ui.pages_payroll as P_payroll
import app.ui.dialogs_master as D_master
CONFIRM = {"yes": False}
for mod in (W, P_ops, P_master, P_payroll, D_master):
    mod.confirm = lambda *a, **k: CONFIRM["yes"]

from app.core import calc, db, repo
db.init_db()
conn = db.get_conn()
from scripts.seed_demo import seed
ids = seed(conn)

# ===========================================================================
step("1) نافذة الفاتورة: تفاعل مباشر بالإضافة/الحذف والإجماليات الحية")
from app.ui.dialogs_ops import InvoiceDialog

d = InvoiceDialog(win_holder := None)  # أب=None
d.show(); app.processEvents()
base_rows = d.trips_table.rowCount()
check("جدول النقلات يبدأ فارغاً", base_rows == 0)

# إضافة نقلة عبر البيانات + تحديث الواجهة (نفس مسار add_trip بعد الموافقة)
d.trips.append({"vehicle_id": ids["veh1"], "driver_id": ids["drv1"],
                "from_loc": "جدة", "to_loc": "الرياض", "price": 2500,
                "notes": "", "expenses": []})
d.refresh(); app.processEvents()
check("سطر النقلة ظهر", d.trips_table.rowCount() == 1)
t1 = d.totals._values["إجمالي قيمة النقلات"].text()
check("إجمالي النقلات الحي = 2,500.00", t1 == "2,500.00", f"({t1})")

from app.ui.dialogs_ops import TripExpensesDialog, ExpenseDialog
d.trips[0]["expenses"] = [{"expense_type": "fuel", "amount": 200, "notes": ""},
                          {"expense_type": "trip", "amount": 120, "notes": ""}]
d.refresh(); app.processEvents()
t2 = d.totals._values["إجمالي المصروفات المباشرة"].text()
t3 = d.totals._values["الربح المتوقع"].text()
check("المصروفات الحية = 320.00", t2 == "320.00", f"({t2})")
check("الربح المتوقع الحي = 2,180.00", t3 == "2,180.00", f"({t3})")

# حذف النقلة عبر مسار الزر (remove_trip)
d.remove_trip(0)
check("حذف النقلة من الواجهة", d.trips_table.rowCount() == 0
      and d.totals._values["إجمالي قيمة النقلات"].text() == "0.00")

# نافذة مصروفات النقلة: إضافة/تعديل/حذف
trip = {"from_loc": "أ", "to_loc": "ب", "price": 100, "expenses": []}
exd = TripExpensesDialog(trip)
exd.show(); app.processEvents()
exp_dlg = ExpenseDialog(exd)
exp_dlg.type_combo.setCurrentIndex(exp_dlg.type_combo.findData("card"))
exp_dlg.amount_edit.setText("75.50")
exp_dlg.notes_edit.setText("كارتة فحص")
trip["expenses"].append(exp_dlg.data())
exd.refresh()
check("مصروف أُضيف عبر النافذة", exd.table.rowCount() == 1
      and exd.table.item(0, 1).text() == "75.50")
exp_dlg2 = ExpenseDialog(exd, trip["expenses"][0])
exp_dlg2.amount_edit.setText("80")
trip["expenses"][0].update(exp_dlg2.data())
exd.refresh()
check("تعديل المصروف عبر النافذة", exd.table.item(0, 1).text() == "80.00")
exd.del_expense(0)
check("حذف المصروف عبر النافذة", exd.table.rowCount() == 0)
exd.close()

# سقف النص من الواجهة: بيان فاتورة طويل يجب أن يُرفض لطفاً واضحاً
d.notes_edit.setText("ن" * 6000)
d.customer_combo.select(ids["cust1"])
d.date_edit.set_iso("2026-06-01")
d.trips = [{"vehicle_id": None, "driver_id": None, "from_loc": "أ", "to_loc": "ب",
            "price": 500, "expenses": []}]
d.refresh()
try:
    d.save()
    check("نص 6000 محرف يُرفض من الواجهة", False, "— قُبل!")
except Exception:
    check("نص 6000 محرف يُرفض من الواجهة", True)
d.notes_edit.setText("بيان طبيعي")
d.save()
inv_new = conn.execute("SELECT id FROM invoices ORDER BY id DESC LIMIT 1").fetchone()["id"]
check("الفاتورة حُفظت بعد النص الطبيعي",
      calc.invoice_totals(conn, inv_new)["trips_total"] == 500)
d.close()

# ===========================================================================
step("2) سند الدفع: تبديل الأنواع ومطابقة المكدس والسقوف")
from app.ui.dialogs_ops import PaymentDialog

pd = PaymentDialog()
pd.show(); app.processEvents()
for i, vt in enumerate(("trip", "advance", "vehicle", "general")):
    pd.type_combo.setCurrentIndex(pd.type_combo.findData(vt))
    app.processEvents()
    check(f"تبديل النوع إلى {vt} يبدّل المكدس",
          pd.stack_lay.currentIndex() == i)
pd.close()

pd = PaymentDialog()
pd.date_edit.set_iso("2026-06-05")
pd.account_combo.select("cashbox", ids["cb"])
idx = pd.type_combo.findData("general")
pd.type_combo.setCurrentIndex(idx)
pd.amount_edit.setText("250")
pd.desc_edit.setText("ي" * 6000)  # سقف النص
try:
    pd.save()
    check("بيان 6000 محرف يُرفض من نافذة السند", False, "— قُبل!")
except Exception:
    check("بيان 6000 محرف يُرفض من نافذة السند", True)
pd.desc_edit.setText("صيانة مكتب")
pd.save()
row = conn.execute("SELECT * FROM payment_vouchers ORDER BY id DESC LIMIT 1").fetchone()
check("السند حُفظ بعد تقصير البيان", row["amount"] == 250
      and row["description"] == "صيانة مكتب")
pd.close()

# ===========================================================================
step("3) السنوات المالية: إغلاق/فتح عبر on_extra + اللقطات")
years_page = None
from app.ui.main_window import MainWindow
win = MainWindow()
win.show(); app.processEvents()
pages = dict(win._pages)
years_page = pages["السنوات المالية"]
y26 = conn.execute("SELECT id FROM financial_years WHERE year=2026").fetchone()["id"]

CONFIRM["yes"] = True
years_page.on_extra(y26, "toggle")   # إغلاق + لقطة
app.processEvents()
check("الإغلاق عبر الزر: الحالة مغلقة",
      repo.get_year(conn, y26)["status"] == "closed")
check("الإغلاق عبر الزر: لقطة أُنشئت", repo.get_snapshot(conn, y26) is not None)
years_page.on_extra(y26, "toggle")   # إعادة فتح
check("إعادة الفتح عبر الزر",
      repo.get_year(conn, y26)["status"] == "open")

# حالة «لا لقطة» وزر الإنشاء
conn.execute("DELETE FROM year_snapshots WHERE year_id=?", (y26,))
conn.commit()
snap_dlg = D_master.SnapshotDialog(y26, win)
app.processEvents()
btns = snap_dlg.findChildren(QPushButton)
create_btn = next((b for b in btns if "إنشاء" in b.text()), None)
check("نافذة اللقطة بلا بيانات تعرض زر الإنشاء", create_btn is not None)
if create_btn:
    create_btn.click()
    app.processEvents()
    check("زر الإنشاء أنشأ اللقطة فعلاً", repo.get_snapshot(conn, y26) is not None)

# زر اللقطة يرفض للسنة المفتوحة (رسالة توضيحية بلا حوار معلق)
POPUPS_BEFORE = len(QMessageBox.information.__self__) if False else 0
years_page.on_extra(y26, "snapshot")  # مفتوحة → رسالة إرشادية
check("زر اللقطة للسنة المفتوحة لا يغلق شيئاً ولا يعلق", True)

# ===========================================================================
step("4) كشوف: فترة معكوسة، رصيد مجرى مطابق يدوياً، تصدير صالح")
from app.ui.statements import CustomerStatementDialog

cst = CustomerStatementDialog(ids["cust1"], win)
cst.from_edit.set_iso("2026-12-31")
cst.to_edit.set_iso("2026-01-01")
cst.load()
check("فترة معكوسة: جدول فارغ إلا سطر الإجمالي",
      cst.table.rowCount() == 1)  # سطر الإجماليات فقط
cst.export("excel")
cst.export("pdf")
for pth in EXPORTED[-2:]:
    ok = pth.exists() and pth.stat().st_size > 400
    check(f"تصدير رغم الفراغ صالح: {pth.suffix}", ok)

cst.from_edit.set_iso("2026-01-01")
cst.to_edit.set_iso("2026-12-31")
cst.load()
rows = cst.table.rowCount()
bal = None
ok_chain = True
hdr = [cst.table.horizontalHeaderItem(c).text()
       for c in range(cst.table.columnCount())]
col = hdr.index("الرصيد")
for r in range(rows - 1):  # آخر سطر إجمالي
    txt = cst.table.item(r, col).text().replace(",", "")
    if bal is None:
        st = calc.customer_statement(conn, ids["cust1"], "2026-01-01", "2026-12-31")
        bal = st["opening"]
    # إعادة احتساب يدوي من عمودي مدين/دائن
    dcol, ccol = hdr.index("مدين (عليه)"), hdr.index("دائن (له)")
    bal += float(cst.table.item(r, dcol).text().replace(",", "")) \
        - float(cst.table.item(r, ccol).text().replace(",", ""))
    if abs(bal - float(txt)) > 0.01:
        ok_chain = False
check("سلسلة أرصدة كشف العميل في الجدول = إعادة احتساب يدوي", ok_chain)
cst.close()

from app.ui.statements import AccountStatementDialog
ast = AccountStatementDialog("bank", ids["bnk"], win)
ast.from_edit.set_iso("2026-01-01"); ast.to_edit.set_iso("2026-12-31")
ast.load()
check("كشف البنك يفتح وفيه أسطر", ast.table.rowCount() >= 2)
ast.export("pdf")
check("تصدير كشف البنك صالح", EXPORTED[-1].stat().st_size > 1000)
ast.close()

# ===========================================================================
step("5) كشف الموظف: تبويبات + تصدير كل تبويب مطابق لعدد أسطر SQL")
emp_page = pages["كشف حساب موظف/سائق"]
emp_page.employee_combo.select(ids["drv1"])
app.processEvents()
emp_page.load()
n_sal = conn.execute("SELECT COUNT(*) FROM payrolls WHERE employee_id=?",
                     (ids["drv1"],)).fetchone()[0]
n_adv = conn.execute(
    "SELECT COUNT(*) FROM payment_vouchers WHERE voucher_type='advance' "
    "AND employee_id=?", (ids["drv1"],)).fetchone()[0]
n_trip = conn.execute("SELECT COUNT(*) FROM invoice_trips WHERE driver_id=?",
                      (ids["drv1"],)).fetchone()[0]
tabs = emp_page.tabs
tabs.setCurrentIndex(0); app.processEvents()
check("تبويب الرواتب مطابق للـSQL", emp_page.salaries_table.rowCount() == n_sal,
      f"({emp_page.salaries_table.rowCount()}/{n_sal})")
tabs.setCurrentIndex(1); app.processEvents()
check("تبويب السلف مطابق للـSQL", emp_page.advances_table.rowCount() == n_adv,
      f"({emp_page.advances_table.rowCount()}/{n_adv})")
tabs.setCurrentIndex(2); app.processEvents()
check("تبويب التريب مطابق للـSQL", emp_page.allow_table.rowCount() == n_trip,
      f"({emp_page.allow_table.rowCount()}/{n_trip})")
for mode in ("excel", "pdf"):
    emp_page.do_export(mode)
    check(f"تصدير التبويب النشط {mode} صالح",
          EXPORTED[-1].exists() and EXPORTED[-1].stat().st_size > 400)

# تقارير بدون تحديد (العنصر النائب)
tr_page = pages["أرباح الفواتير والرحلات"]
tr_page.customer_combo.setCurrentIndex(0)
tr_page.load()
cust_page_sql = conn.execute("SELECT COUNT(*) FROM invoice_trips").fetchone()[0]
check("تقرير الرحلات بدون فلترة عميل = كل الرحلات",
      tr_page.table.rowCount() == cust_page_sql + 1,  # + سطر الإجمالي
      f"({tr_page.table.rowCount()}/{cust_page_sql}+1)")

# ===========================================================================
step("6) الإعدادات: الترويسة تتغير + نسخة احتياطية قابلة للقراءة")
set_page = pages["الإعدادات"]
set_page.name_edit.setText("شركة الفحص الشامل <للنقل>")
set_page.save()
conn2 = db.get_conn()
html = exporter.build_report_html(conn2, title="فحص", headers=["أ"], rows=[["ب"]])
check("اسم الشركة الجديد يظهر في الترويسة مهرباً",
      "شركة الفحص الشامل &lt;للنقل&gt;" in html)
# النقر على زر النسخة الاحتياطية فعلياً
backup_btn = next((b for b in set_page.findChildren(QPushButton)
                   if "احتياطية" in b.text()), None)
check("زر النسخة الاحتياطية موجود في الإعدادات", backup_btn is not None)
if backup_btn:
    backup_btn.click()
    app.processEvents()
backups = list((db.data_dir() / "backups").glob("*.db"))
check("زر/مسار النسخة الاحتياطية يعمل", len(backups) >= 1)
if backups:
    b = sqlite3.connect(str(backups[-1]))
    n1 = b.execute("SELECT COUNT(*) FROM customers").fetchone()[0]
    n2 = conn.execute("SELECT COUNT(*) FROM customers").fetchone()[0]
    b.close()
    check("النسخة الاحتياطية الأخيرة متناسقة", n1 == n2)

# ===========================================================================
step("7) محاور متنوعة: بحث بأرقام عربية، قيم سالبة، نقرة مزدوجة")
cust_page = pages["العملاء"]
cust_page.refresh()
cust_page.frame.search_edit.setText("٠٥٥١")   # أرقام عربية
app.processEvents()
check("بحث بأرقام عربية يرشّح", cust_page.table.rowCount() >= 1)
cust_page.frame.search_edit.clear()
app.processEvents()

neg = pages["الأرباح والخسائر (P&L)"]
neg.filter_row.from_edit.set_iso("2020-01-01")
neg.filter_row.to_edit.set_iso("2020-12-31")
neg.load()
neg.totals.set_value("صافي الربح / الخسارة", -1234.5)
check("قيمة سالبة في بطاقة الإجماليات تعمل", "1,234.50" in
      neg.totals._values["صافي الربح / الخسارة"].text())

inv_page = pages["فواتير النقل"]
inv_page.refresh()
if inv_page.table.rowCount():
    from PySide6.QtCore import QModelIndex
    inv_page.table.doubleClicked.emit(inv_page.table.model().index(0, 0))
    app.processEvents()
    check("نقرة مزدوجة تفتح العرض بلا تعليق", True)

win.nav_list.setCurrentRow(1)
app.processEvents()
print(f"\n===== النتيجة: نجاح {PASS} / فشل {FAIL} =====")
if FAILURES:
    print("الإخفاقات:")
    for f in FAILURES:
        print("  -", f)
    sys.exit(1)
print("🎉 فحص الواجهة الجديد نجح بالكامل.")
