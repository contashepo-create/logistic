# -*- coding: utf-8 -*-
"""النافذة الرئيسية: شريط تنقل جانبي (عربي RTL) + مكدس الصفحات + شريط الحالة."""
from __future__ import annotations

from datetime import date

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QHBoxLayout, QLabel, QListWidget, QListWidgetItem, QMainWindow, QMessageBox,
    QStackedWidget, QVBoxLayout, QWidget,
)

from .. import APP_TITLE, __version__
from ..core import db, repo
from ..core.rules import has_open_year
from .page_settings import SettingsPage
from .pages_master import CustomersPage, EmployeesPage, VehiclesPage, YearsPage
from .pages_ops import InvoicesPage, PaymentsPage, ReceiptsPage
from .pages_payroll import PayrollPage
from .pages_reports import (
    CustomerStatementReportPage, EmployeeStatementReportPage, PnlReportPage,
    TripProfitsReportPage, VehiclesReportPage,
)
from .pages_treasury import BanksPage, CashboxesPage

NAV_SECTIONS: list[tuple[str, list[tuple[str, type]]]] = [
    ("📁 البيانات الأساسية", [
        ("العملاء", CustomersPage),
        ("الموظفون والسائقون", EmployeesPage),
        ("السيارات", VehiclesPage),
        ("السنوات المالية", YearsPage),
    ]),
    ("🏦 الخزائن والبنوك", [
        ("الخزائن", CashboxesPage),
        ("البنوك", BanksPage),
    ]),
    ("🔄 العمليات اليومية", [
        ("فواتير النقل", InvoicesPage),
        ("سندات القبض", ReceiptsPage),
        ("سندات الدفع", PaymentsPage),
    ]),
    ("💰 الرواتب", [
        ("إدارة الرواتب", PayrollPage),
    ]),
    ("📊 التقارير الذكية", [
        ("أرباح الفواتير والرحلات", TripProfitsReportPage),
        ("كشف حساب عميل", CustomerStatementReportPage),
        ("كشف حساب موظف/سائق", EmployeeStatementReportPage),
        ("أداء السيارات", VehiclesReportPage),
        ("الأرباح والخسائر (P&L)", PnlReportPage),
    ]),
    ("⚙️ النظام", [
        ("الإعدادات", SettingsPage),
    ]),
]


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"{APP_TITLE} — v{__version__}")
        self.resize(1280, 780)

        central = QWidget()
        self.setCentralWidget(central)
        root = QHBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # شريط التنقل
        nav_widget = QWidget()
        nav_widget.setObjectName("nav")
        nav_widget.setFixedWidth(240)
        nav = QVBoxLayout(nav_widget)
        nav.setContentsMargins(8, 10, 8, 10)
        nav.setSpacing(2)
        brand = QLabel("🚛 النظام المحاسبي\nلشركة النقل")
        brand.setStyleSheet("color: white; font-size: 13pt; font-weight: bold; "
                            "padding: 8px 6px 14px 6px;")
        brand.setAlignment(Qt.AlignmentFlag.AlignCenter)
        nav.addWidget(brand)
        self.nav_list = QListWidget()
        self.nav_list.setObjectName("nav")
        self.stack = QStackedWidget()
        self._pages: list[tuple[str, QWidget]] = []
        for section, items in NAV_SECTIONS:
            hdr = QListWidgetItem(section)
            hdr.setFlags(Qt.ItemFlag.NoItemFlags)
            self.nav_list.addItem(hdr)
            for label, page_cls in items:
                item = QListWidgetItem(label)
                self.nav_list.addItem(item)
                try:
                    page = page_cls()
                    if hasattr(page, "build"):
                        page.build()
                except Exception as e:  # noqa: BLE001
                    page = QWidget()
                    err = QLabel(f"خطأ في تحميل الصفحة ({label}):\n{e}")
                    err.setWordWrap(True)
                    page.setLayout(QVBoxLayout())
                    page.layout().addWidget(err)
                self.stack.addWidget(page)
                self._pages.append((label, page))
                if hasattr(page, "changed"):
                    page.changed.connect(self.refresh_year_info)
        self.nav_list.currentRowChanged.connect(self._nav_changed)
        nav.addWidget(self.nav_list, 1)

        year_info = QLabel("")
        year_info.setStyleSheet("color:#8ba3bc; font-size:9pt; padding:6px")
        year_info.setWordWrap(True)
        nav.addWidget(year_info)
        self.year_info = year_info

        root.addWidget(nav_widget)
        root.addWidget(self.stack, 1)

        self.statusBar().showMessage(
            f"قاعدة البيانات: {db.db_path()}   |   الإصدار {__version__}")
        self.nav_list.setCurrentRow(1)
        QTimer.singleShot(0, self._first_run_check)
        self.refresh_year_info()

    # ------------------------------------------------------------------
    def _nav_changed(self, row: int) -> None:
        item = self.nav_list.item(row)
        if item is None or not (item.flags() & Qt.ItemFlag.ItemIsSelectable):
            return
        # أول صفحة قابلة للتحديد بعد العنوان
        page_index = self._page_index_for_row(row)
        if page_index is None:
            return
        self.stack.setCurrentIndex(page_index)
        page = self._pages[page_index][1]
        if hasattr(page, "refresh"):
            try:
                page.refresh()
            except Exception:  # noqa: BLE001
                pass

    def _page_index_for_row(self, row: int) -> int | None:
        idx = 0
        for _section, items in NAV_SECTIONS:
            row -= 1  # تخطي عنوان القسم
            for _label, _cls in items:
                if row == 0:
                    return idx
                row -= 1
                idx += 1
        return None

    # ------------------------------------------------------------------
    def refresh_year_info(self) -> None:
        conn = db.get_conn()
        years = repo.list_years(conn)
        open_list = [str(y["year"]) for y in years if y["status"] == "open"]
        text = "السنوات المفتوحة: " + ("، ".join(open_list) if open_list else "لا يوجد ⚠️")
        self.year_info.setText(text)

    def _first_run_check(self) -> None:
        conn = db.get_conn()
        if repo.list_years(conn):
            return
        ret = QMessageBox.question(
            self, "إنشاء السنة المالية",
            "لا توجد سنوات مالية مسجلة بعد.\n"
            f"هل تريد إنشاء السنة المالية {date.today().year} تلقائياً "
            "(من 01-01 إلى 31-12)؟\n\nبدون سنة مفتوحة لن يمكنك تسجيل أي حركة.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        if ret == QMessageBox.StandardButton.Yes:
            try:
                repo.save_year(conn, {"year": date.today().year,
                                      "date_from": f"{date.today().year}-01-01",
                                      "date_to": f"{date.today().year}-12-31",
                                      "notes": "أنشئت تلقائياً"})
                self.refresh_year_info()
                page = self._pages[self._page_index_for_row(1)][1]
                if hasattr(page, "refresh"):
                    page.refresh()
            except Exception as e:  # noqa: BLE001
                QMessageBox.warning(self, "خطأ", str(e))
