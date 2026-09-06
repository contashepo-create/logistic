# -*- coding: utf-8 -*-
"""النافذة الرئيسية: شريط تنقل جانبي حديث (عربي RTL) + شريط علوي +
مكدس الصفحات + شريط الحالة."""
from __future__ import annotations

from datetime import date

from PySide6.QtCore import QSize, Qt, QTimer
from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QListWidget, QListWidgetItem, QMainWindow,
    QMessageBox, QStackedWidget, QVBoxLayout, QWidget,
)

from .. import APP_TITLE, __version__
from ..core import telegram_bot, db, repo
from .page_settings import SettingsPage
from .pages_master import CustomersPage, EmployeesPage, VehiclesPage, YearsPage
from .pages_ops import InvoicesPage, PaymentsPage, ReceiptsPage
from .pages_payroll import PayrollPage
from .pages_reports import (
    AgingReportPage, CustomerStatementReportPage, EmployeeStatementReportPage,
    PnlReportPage, SupplierStatementReportPage, TripProfitsReportPage,
    VehiclesReportPage,
)
from .pages_suppliers import (
    AdvancesPage, DeductionsPage, NotesPage, PurchasesPage, SuppliersPage,
)
from .pages_treasury import BanksPage, CashboxesPage

# أيقونة كل صفحة في الشريط الجانبي
NAV_ICONS = {
    "العملاء": "👥",
    "الموردون": "🏭",
    "الموظفون والسائقون": "🧑‍🔧",
    "السيارات": "🚚",
    "السنوات المالية": "🗓️",
    "الخزائن": "💵",
    "البنوك": "🏦",
    "فواتير النقل": "🧾",
    "فواتير المشتريات": "📦",
    "سندات القبض": "📥",
    "سندات الدفع": "📤",
    "إشعارات مدين/دائن": "🔁",
    "إدارة الرواتب": "💼",
    "متابعة السلفيات": "⏳",
    "الخصومات": "✂️",
    "أرباح الفواتير والرحلات": "📈",
    "كشف حساب عميل": "📄",
    "كشف حساب مورّد": "🧾",
    "أعمار الديون": "⏰",
    "كشف حساب موظف/سائق": "👤",
    "أداء السيارات": "🚛",
    "الأرباح والخسائر (P&L)": "📊",
    "الإعدادات": "⚙️",
}

NAV_SECTIONS: list[tuple[str, list[tuple[str, type]]]] = [
    ("البيانات الأساسية", [
        ("العملاء", CustomersPage),
        ("الموردون", SuppliersPage),
        ("الموظفون والسائقون", EmployeesPage),
        ("السيارات", VehiclesPage),
        ("السنوات المالية", YearsPage),
    ]),
    ("الخزائن والبنوك", [
        ("الخزائن", CashboxesPage),
        ("البنوك", BanksPage),
    ]),
    ("العمليات اليومية", [
        ("فواتير النقل", InvoicesPage),
        ("فواتير المشتريات", PurchasesPage),
        ("سندات القبض", ReceiptsPage),
        ("سندات الدفع", PaymentsPage),
        ("إشعارات مدين/دائن", NotesPage),
    ]),
    ("الرواتب", [
        ("إدارة الرواتب", PayrollPage),
        ("متابعة السلفيات", AdvancesPage),
        ("الخصومات", DeductionsPage),
    ]),
    ("التقارير الذكية", [
        ("أرباح الفواتير والرحلات", TripProfitsReportPage),
        ("كشف حساب عميل", CustomerStatementReportPage),
        ("كشف حساب مورّد", SupplierStatementReportPage),
        ("أعمار الديون", AgingReportPage),
        ("كشف حساب موظف/سائق", EmployeeStatementReportPage),
        ("أداء السيارات", VehiclesReportPage),
        ("الأرباح والخسائر (P&L)", PnlReportPage),
    ]),
    ("النظام", [
        ("الإعدادات", SettingsPage),
    ]),
]

SIDEBAR_WIDTH = 268


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"{APP_TITLE} — v{__version__}")
        self.resize(1360, 800)

        central = QWidget()
        self.setCentralWidget(central)
        root = QHBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ================= الشريط الجانبي =================
        nav_widget = QFrame()
        nav_widget.setObjectName("sidebar")
        nav_widget.setFixedWidth(SIDEBAR_WIDTH)
        nav = QVBoxLayout(nav_widget)
        nav.setContentsMargins(14, 16, 14, 14)
        nav.setSpacing(10)

        # الهوية (الشعار + الاسم)
        brand = QHBoxLayout()
        brand.setSpacing(10)
        badge = QLabel("🚚")
        badge.setObjectName("brandBadge")
        badge.setFixedSize(44, 44)
        badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        brand.addWidget(badge)
        brand_texts = QVBoxLayout()
        brand_texts.setSpacing(0)
        bname = QLabel("النظام المحاسبي")
        bname.setObjectName("brandName")
        bsub = QLabel(f"لشركة النقل  •  v{__version__}")
        bsub.setObjectName("brandSub")
        brand_texts.addWidget(bname)
        brand_texts.addWidget(bsub)
        brand.addLayout(brand_texts, 1)
        nav.addLayout(brand)

        sep = QFrame()
        sep.setObjectName("navSeparator")
        sep.setFixedHeight(1)
        nav.addWidget(sep)

        self.nav_list = QListWidget()
        self.nav_list.setObjectName("nav")
        self.nav_list.setVerticalScrollMode(
            QListWidget.ScrollMode.ScrollPerPixel)
        self.nav_list.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.stack = QStackedWidget()
        self._pages: list[tuple[str, QWidget]] = []
        for section, items in NAV_SECTIONS:
            hdr = QListWidgetItem("  " + section)
            hdr.setFlags(Qt.ItemFlag.NoItemFlags)
            hdr.setSizeHint(QSize(SIDEBAR_WIDTH, 26))
            self.nav_list.addItem(hdr)
            for label, page_cls in items:
                icon = NAV_ICONS.get(label, "•")
                item = QListWidgetItem(f"{icon}   {label}")
                item.setSizeHint(QSize(SIDEBAR_WIDTH, 40))
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

        # بطاقة حالة السنة المالية أسفل الشريط
        footer = QFrame()
        footer.setObjectName("navFooter")
        flay = QVBoxLayout(footer)
        flay.setContentsMargins(14, 10, 14, 10)
        flay.setSpacing(2)
        ftitle = QLabel("السنوات المالية المفتوحة")
        ftitle.setObjectName("navFooterTitle")
        self.year_info = QLabel("—")
        self.year_info.setObjectName("navFooterValue")
        self.year_info.setWordWrap(True)
        flay.addWidget(ftitle)
        flay.addWidget(self.year_info)
        nav.addWidget(footer)

        root.addWidget(nav_widget)

        # ================= منطقة المحتوى =================
        content = QVBoxLayout()
        content.setContentsMargins(0, 0, 0, 0)
        content.setSpacing(0)

        # الشريط العلوي: عنوان الصفحة الحالية + شرائح معلومات
        topbar = QFrame()
        topbar.setObjectName("topbar")
        topbar.setFixedHeight(62)
        tlay = QHBoxLayout(topbar)
        tlay.setContentsMargins(24, 8, 24, 8)
        tlay.setSpacing(10)
        self.topbar_icon = QLabel("👥")
        self.topbar_icon.setStyleSheet("font-size: 14pt; background: transparent;")
        self.topbar_title = QLabel("العملاء")
        self.topbar_title.setObjectName("topbarTitle")
        tlay.addWidget(self.topbar_icon)
        tlay.addWidget(self.topbar_title)
        tlay.addStretch(1)
        date_chip = QLabel("📅  " + date.today().strftime("%Y-%m-%d"))
        date_chip.setObjectName("chip")
        tlay.addWidget(date_chip)
        self.year_chip = QLabel("")
        self.year_chip.setObjectName("chipAccent")
        tlay.addWidget(self.year_chip)
        content.addWidget(topbar)

        # حاشية حول الصفحات لتتنفس على الخلفية
        pages_wrap = QWidget()
        pages_wrap.setStyleSheet("background: transparent;")
        pw = QHBoxLayout(pages_wrap)
        pw.setContentsMargins(18, 16, 18, 14)
        pw.addWidget(self.stack, 1)
        content.addWidget(pages_wrap, 1)

        root_widget = QWidget()
        root_widget.setLayout(content)
        root.addWidget(root_widget, 1)

        self.statusBar().showMessage(
            f"قاعدة البيانات: {db.db_path()}   |   الإصدار {__version__}")
        self.nav_list.setCurrentRow(1)
        QTimer.singleShot(0, self._first_run_check)
        self.refresh_year_info()

        # بوت التليجرام: يعمل تلقائياً إن كان مُعدّاً (رمز + معرّف المالك)،
        # ويُوقَف عند إغلاق التطبيق. الفشل لا يمنع فتح التطبيق.
        self.telegram_bot = None
        try:
            bot = telegram_bot.TelegramBot(db.get_conn)
            if bot.start():
                self.telegram_bot = bot
        except Exception:  # noqa: BLE001
            self.telegram_bot = None

    def closeEvent(self, event) -> None:
        """إيقاف خيط البوت قبل الإغلاق حتى لا يبقى معلقاً."""
        if self.telegram_bot is not None:
            try:
                self.telegram_bot.stop()
            except Exception:  # noqa: BLE001
                pass
        super().closeEvent(event)

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
        label, page = self._pages[page_index]
        icon = NAV_ICONS.get(label, "")
        self.topbar_icon.setText(icon)
        self.topbar_title.setText(label)
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
        text = "، ".join(open_list) if open_list else "لا توجد ⚠️"
        self.year_info.setText(text)
        self.year_chip.setText("🗓️  سنة مفتوحة: " + (open_list[0] if open_list else "—"))

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
