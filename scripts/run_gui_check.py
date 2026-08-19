# -*- coding: utf-8 -*-
"""
اختبار الواجهة الرسومية الآلي (offscreen): بناء كل الصفحات والنوافذ،
التقاط لقطات شاشة، والتحقق الفعلي من تصدير Excel/PDF.

تشغيل:  QT_QPA_PLATFORM=offscreen python scripts/run_gui_check.py
"""
from __future__ import annotations

import os
import sys
import tempfile
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["LOGISTIC_DATA_DIR"] = tempfile.mkdtemp(prefix="logistic_gui_")
os.environ["LOGISTIC_HEADLESS"] = "1"  # تعطيل رسائل النجاح المنبثقة

ROOT = Path(__file__).resolve().parents[1]
SHOTS = ROOT / "screenshots"
SHOTS.mkdir(exist_ok=True)
TRACE = Path(tempfile.gettempdir()) / "gui_check_trace.log"
TRACE.write_text("", encoding="utf-8")

FAILS: list[str] = []


def mark(msg: str) -> None:
    with TRACE.open("a", encoding="utf-8") as f:
        f.write(msg + "\n")
        f.flush()
    print(msg, flush=True)


mark("بدء الاختبار")

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from app.core import db  # noqa: E402
from app.ui.theme import apply_theme  # noqa: E402

app = QApplication(sys.argv)
app.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
apply_theme(app)
mark("QApplication جاهزة")

db.init_db()
conn = db.get_conn()
from scripts.seed_demo import seed  # noqa: E402

ids = seed(conn)
mark("بيانات تجريبية جاهزة")

# توجيه مسارات التصدير إلى مجلد مؤقت (بدون حوارات ملفات)
from app.utils import exporter  # noqa: E402

OUT = Path(tempfile.mkdtemp(prefix="logistic_export_"))


def fake_save_path(parent, default_name, filters):
    return str(OUT / default_name)


exporter._ask_save_path = fake_save_path
exporter._ask_overwrite = lambda parent, path: True
exported: list[Path] = []


def shot(widget, name: str) -> None:
    try:
        pix = widget.grab()
        pix.save(str(SHOTS / f"{name}.png"))
        mark(f"📸 {name}.png")
    except Exception as e:  # noqa: BLE001
        FAILS.append(f"لقطة {name}: {e}")
        mark(f"❌ لقطة {name}: {e}")


def export_ok(path_str: str | None, label: str) -> bool:
    p = Path(path_str) if path_str else None
    if p and p.exists() and p.stat().st_size > 1000:
        exported.append(p)
        mark(f"✅ {label}: {p.name} ({p.stat().st_size} بايت)")
        return True
    FAILS.append(f"{label}: لم يُنشأ الملف")
    mark(f"❌ {label}: لم يُنشأ الملف")
    return False


# ---------------------------------------------------------------------------
mark("بناء النافذة الرئيسية")
from app.ui.main_window import MainWindow  # noqa: E402

win = MainWindow()
win.resize(1280, 780)
win.show()
app.processEvents()
mark("النافذة الرئيسية جاهزة")

selectable = []
for r in range(win.nav_list.count()):
    if win.nav_list.item(r).flags() & Qt.ItemFlag.ItemIsSelectable:
        selectable.append(r)

names = ["01_customers", "02_employees", "03_vehicles", "04_years",
         "05_cashboxes", "06_banks", "07_invoices", "08_receipts", "09_payments",
         "10_payroll", "11_report_trips", "12_report_customer",
         "13_report_employee", "14_report_vehicles", "15_report_pnl",
         "16_settings"]
mark(f"عدد الصفحات القابلة للتنقل: {len(selectable)}")
for r, name in zip(selectable, names):
    try:
        win.nav_list.setCurrentRow(r)
        app.processEvents()
        shot(win, name)
    except Exception as e:  # noqa: BLE001
        FAILS.append(f"صفحة {name}: {e}")
        mark(f"❌ صفحة {name}: {e}")

# ---------------------------------------------------------------------------
mark("اختبار النوافذ الحوارية")
from app.ui.dialogs_ops import InvoiceDialog, PaymentDialog, ReceiptDialog  # noqa: E402
from app.ui.dialogs_payroll import PayrollDialog  # noqa: E402
from app.ui.statements import (  # noqa: E402
    AccountStatementDialog, CustomerStatementDialog,
)
from app.ui.dialogs_master import SnapshotDialog  # noqa: E402


def try_dialog(make, name: str, w=1000, h=640) -> None:
    try:
        dlg = make()
        dlg.resize(w, h)
        dlg.show()
        app.processEvents()
        shot(dlg, name)
        dlg.close()
        dlg.deleteLater()
    except Exception as e:  # noqa: BLE001
        FAILS.append(f"نافذة {name}: {e}\n{traceback.format_exc()}")
        mark(f"❌ نافذة {name}: {e}")


try_dialog(lambda: InvoiceDialog(win, ids["inv1"], read_only=True), "17_invoice_view")
try_dialog(lambda: InvoiceDialog(win), "18_invoice_new")
try_dialog(lambda: ReceiptDialog(win), "19_receipt_new")
try_dialog(lambda: PaymentDialog(win), "20_payment_new")
try_dialog(lambda: PayrollDialog(win), "21_payroll_new")
try_dialog(lambda: CustomerStatementDialog(ids["cust1"], win), "22_customer_statement")
try_dialog(lambda: AccountStatementDialog("cashbox", ids["cb"], win), "23_cashbox_statement")

# ---------------------------------------------------------------------------
mark("اختبار تصدير Excel و PDF فعلياً")
try:
    from app.core import calc
    from app.utils.fmt import money as m

    pnl = calc.pnl_report(conn, "1900-01-01", "2999-12-31")
    headers = ["البيان", "القيمة"]
    rows = [["إجمالي الإيرادات", m(pnl["total_revenue"])],
            ["إجمالي المصروفات", m(pnl["total_expenses"])],
            ["صافي الربح / الخسارة", m(pnl["net"])]]
    html = exporter.build_report_html(conn, title="تقرير الأرباح والخسائر",
                                      subtitle="فترة تجريبية", headers=headers,
                                      rows=rows)
    export_ok(exporter.export_excel(win, conn, "تقرير أرباح", headers, rows,
                                    default_name="pnl_check.xlsx"),
              "Excel")
    export_ok(exporter.export_pdf(win, html, "pnl_check.pdf"), "PDF")

    from app.ui.dialogs_ops import customer_invoice_html
    inv_html = customer_invoice_html(conn, ids["inv1"])
    export_ok(exporter.export_pdf(win, inv_html, "invoice_check.pdf"),
              "PDF فاتورة العميل")
except Exception as e:  # noqa: BLE001
    FAILS.append(f"تصدير: {e}\n{traceback.format_exc()}")
    mark(f"❌ تصدير: {e}")

# ---------------------------------------------------------------------------
mark("اختبار لقطة إغلاق السنة")
try:
    from app.core import repo

    yid = repo.list_years(conn)[0]["id"]
    repo.set_year_status(conn, yid, "closed")
    repo.create_snapshot(conn, yid)
    try_dialog(lambda: SnapshotDialog(yid, win), "24_year_snapshot", 880, 560)
    repo.set_year_status(conn, yid, "open")
except Exception as e:  # noqa: BLE001
    FAILS.append(f"لقطة السنة: {e}\n{traceback.format_exc()}")
    mark(f"❌ لقطة السنة: {e}")

mark("=" * 50)
if FAILS:
    mark("❌ إخفاقات:\n  - " + "\n  - ".join(FAILS))
    sys.exit(1)
mark(f"🎉 اختبار الواجهة نجح بالكامل — اللقطات في {SHOTS}")
