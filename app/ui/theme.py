# -*- coding: utf-8 -*-
"""
نظام الثيم المرن للتطبيق (فاتح/داكن) بأسلوب لوحات التحكم الحديثة
(shadcn / Tailwind-style + لوحة معاينة جديدة).

الفكرة المعمارية:
  كل ألوان الواجهة تُدار من خلال "لوحة رموز" (palette) واحدة للوضع الفاتح
  وأخرى للوضع الداكن. يُبنى ملف الأنماط (QSS) مرّة من أي لوحة عبر دالة
  build_stylesheet()، وعند تبديل الوضع نُعيد تطبيق اللوحة + القصّة على
  QApplication فقط (بدون إعادة بناء صفحات) فتتلوّن الواجهة كلها فوراً،
  بما فيها الخطوط والأيقونات، في الحالتين.

  النمط البصري مستوحى من "التصميم الجديد":
    - داكن: خلفية كحلية عميقة، ألواح داكنة، نيلي/بنفسجي متدرّج،
      نصوص فاتحة وألوان حالة ساطعة.
    - فاتح: خلفية رمادية فاتحة، بطاقات بيضاء، النيلي الأساسي.
"""
from __future__ import annotations

import os
import tempfile

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont, QPalette
from PySide6.QtWidgets import QApplication

from ..utils.fonts import pick_font_family

# ===========================================================================
# لوحا الألوان (فاتح / داكن) — كل مفتاح يُستخدم في قالب QSS.
# ===========================================================================

_LIGHT: dict[str, str] = {
    # الخلفيات
    "BG":              "#f6f7fb",   # خلفية التطبيق
    "CARD":            "#ffffff",   # البطاقات/الصفحة/الشريط العلوي
    "SURFACE":         "#f8fafc",   # أسطح خفيفة (الفلاتر، حبيبات النوافذ)
    "BORDER":          "#e5e7eb",   # الحدود العامة
    "HOVER":           "#f3f4f6",   # تحويم الأزرار/القوائم
    "HOVER2":          "#eef0f4",
    "PRESSED":         "#f1f3f7",
    "SIDEBAR":         "#ffffff",   # الشريط الجانبي الأبيض
    "SIDEBAR_EDGE":    "#e5e7eb",
    "SIDEBAR_HOVER":   "#f3f4f6",
    # النصوص
    "TEXT":            "#111827",
    "TEXT_SOFT":       "#374151",
    "MUTED":           "#6b7280",
    "FAINT":           "#9ca3af",
    "ON_SIDEBAR":      "#374151",
    "ON_SIDEBAR_SEL":  "#4f46e5",
    # الأساسي (نيلي)
    "PRIMARY":         "#6366f1",
    "PRIMARY_HOVER":   "#7378f2",
    "PRIMARY_DEEP":    "#4f46e5",
    "PRIMARY_DEEP2":   "#4338ca",
    "PRIMARY_SOFT":    "#eef2ff",   # خلفية التحديد
    "PRIMARY_BORDER":  "#c7d2fe",
    "ACCENT_TEXT":     "#4f46e5",   # نص العناصر النشطة فوق الخلفيات الناعمة
    # حقول الإدخال
    "INPUT_BG":        "#ffffff",
    "INPUT_FOCUS_BG":  "#fdfdff",
    "DISABLED_BG":     "#f3f4f6",
    # الجداول
    "HEADER_BG":       "#fafbfc",
    "ALT_ROW":         "#fcfcfd",
    "ROW_HOVER":       "#f5f6ff",
    # حالة
    "DANGER":          "#e02424",
    "DANGER_SOFT":     "#fef2f2",
    "DANGER_BORDER":   "#fecaca",
    "SUCCESS":         "#0e9f6e",
    "SUCCESS_SOFT":    "#ecfdf5",
    "SUCCESS_BORDER":  "#a7f3d0",
    "SUCCESS_DEEP":    "#046c4e",
    "WARNING":         "#d97706",
    "WARNING_SOFT":    "#fffbeb",
    "WARNING_BORDER":  "#fde68a",
    "VIOLET":          "#7c3aed",
    "VIOLET_SOFT":     "#f5f3ff",
    "WARN_TEXT":       "#92400e",   # نصوص تنبيه (الإعدادات)
    # أشرطة التمرير
    "SCROLL":          "#d7dbe2",
    "SCROLL_HOVER":    "#b9bfc9",
    # ظلال / ثوابت
    "BTN_DIS_BG":      "#b1b5f5",
    "BTN_DIS_TEXT":    "#dfe3ff",
    "SELECT_BG":       "#6366f1",
    "SELECT_TEXT":     "#ffffff",
}

_DARK: dict[str, str] = {
    "BG":              "#0a0e17",
    "CARD":            "#111a2a",
    "SURFACE":         "#151f31",
    "BORDER":          "#253047",
    "HOVER":           "#1d2940",
    "HOVER2":          "#1f2b42",
    "PRESSED":         "#141d30",
    "SIDEBAR":         "#0c1322",
    "SIDEBAR_EDGE":    "#1c2738",
    "SIDEBAR_HOVER":   "#1a2332",
    "TEXT":            "#e9eef8",
    "TEXT_SOFT":       "#c3ccdb",
    "MUTED":           "#8a94a7",
    "FAINT":           "#5f6b81",
    "ON_SIDEBAR":      "#c6cfdd",
    "ON_SIDEBAR_SEL":  "#a5b4fc",
    "PRIMARY":         "#6b74f0",
    "PRIMARY_HOVER":   "#7b83f4",
    "PRIMARY_DEEP":    "#818cf8",
    "PRIMARY_DEEP2":   "#a5b4fc",
    "PRIMARY_SOFT":    "#1c2547",
    "PRIMARY_BORDER":  "#3b4a86",
    "ACCENT_TEXT":     "#a5b4fc",
    "INPUT_BG":        "#0d1526",
    "INPUT_FOCUS_BG":  "#0c1424",
    "DISABLED_BG":     "#1b2540",
    "HEADER_BG":       "#0e1728",
    "ALT_ROW":         "#0d1526",
    "ROW_HOVER":       "#182341",
    "DANGER":          "#f87171",
    "DANGER_SOFT":     "rgba(248,113,113,0.12)",
    "DANGER_BORDER":   "rgba(248,113,113,0.35)",
    "SUCCESS":         "#34d399",
    "SUCCESS_SOFT":    "rgba(52,211,153,0.12)",
    "SUCCESS_BORDER":  "rgba(52,211,153,0.35)",
    "SUCCESS_DEEP":    "#6ee7b7",
    "WARNING":         "#fbbf24",
    "WARNING_SOFT":    "rgba(251,191,36,0.12)",
    "WARNING_BORDER":  "rgba(251,191,36,0.3)",
    "VIOLET":          "#a78bfa",
    "VIOLET_SOFT":     "rgba(167,139,250,0.14)",
    "WARN_TEXT":       "#fcd34d",
    "SCROLL":          "#2b3a52",
    "SCROLL_HOVER":    "#3a4e6e",
    "BTN_DIS_BG":      "#2a3158",
    "BTN_DIS_TEXT":    "#6f78ad",
    "SELECT_BG":       "#6366f1",
    "SELECT_TEXT":     "#ffffff",
}

_PALETTES: dict[str, dict[str, str]] = {"light": _LIGHT, "dark": _DARK}

# الوضع النشط حالياً (يُدار عبر set_dark / apply_theme).
_active_mode: str = "light"


def palettes() -> dict[str, dict[str, str]]:
    return _PALETTES


def mode() -> str:
    """'dark' أو 'light' حسب الوضع النشط حالياً."""
    return _active_mode


def is_dark() -> bool:
    return _active_mode == "dark"


def palette() -> dict[str, str]:
    """لوحة الألوان الخاصة بالوضع النشط."""
    return _PALETTES[_active_mode]


def token(key: str, default: str = "") -> str:
    """إرجاع لون رمز معيّن من اللوحة النشطة (لمن يحتاج قيمة في الكود)."""
    return _PALETTES[_active_mode].get(key, default)


# ===========================================================================
# قالب الأنماط — يُبنى من لوحة عبر استبدال الرموز @KEY (كي لا يتعارض مع
# أقواس QSS).
# ===========================================================================
_STYLE_TEMPLATE = r"""
* {
    font-family: '@FONT';
    outline: none;
}
QMainWindow, QDialog { background: @BG; color: @TEXT; }
QToolTip { background: @CARD; color: @TEXT; border: 1px solid @BORDER;
           border-radius: 6px; padding: 4px 8px; }

/* ================= البطاقات والصفحات ================= */
QWidget#page {
    background: @CARD;
    border: 1px solid @BORDER;
    border-radius: 16px;
}

/* ================= الشريط الجانبي ================= */
QFrame#sidebar {
    background: @SIDEBAR;
    border: none; border-left: 1px solid @SIDEBAR_EDGE;
}
QLabel#brandName  { color: @TEXT; font-size: 12.5pt; font-weight: bold;
                     background: transparent; }
QLabel#brandSub   { color: @MUTED; font-size: 8.5pt; background: transparent; }
QLabel#brandBadge {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                                stop:0 #6366f1, stop:1 #818cf8);
    color: white; border-radius: 12px; font-size: 15pt;
}
QFrame#navSeparator { background: @SURFACE; border: none; max-height: 1px; }

QListWidget#nav {
    background: transparent; border: none; font-size: 10.5pt; outline: 0;
    padding: 2px;
}
QListWidget#nav::item {
    color: @ON_SIDEBAR; padding: 10px 14px; margin: 2px 6px;
    border-radius: 10px;
}
QListWidget#nav::item:hover { background: @SIDEBAR_HOVER; color: @TEXT; }
QListWidget#nav::item:selected {
    background: @PRIMARY_SOFT; color: @ON_SIDEBAR_SEL; font-weight: bold;
    border: none;
}
QListWidget#nav::item:disabled {
    color: @FAINT; font-weight: bold; font-size: 8.5pt;
    background: transparent; margin: 12px 6px 2px 6px; padding: 2px 8px;
}

QFrame#navFooter {
    background: @SURFACE;
    border: 1px solid @BORDER;
    border-radius: 12px;
}
QLabel#navFooterTitle { color: @MUTED; font-size: 8.5pt; background: transparent; }
QLabel#navFooterValue { color: @TEXT; font-size: 10pt; font-weight: bold;
                          background: transparent; }

/* زر تبديل المظهر */
QPushButton#themeToggle {
    background: @CARD; border: 1px solid @BORDER; border-radius: 10px;
    padding: 9px 14px; font-size: 10pt; font-weight: 600; color: @TEXT_SOFT;
    text-align: left;
}
QPushButton#themeToggle:hover { background: @SURFACE; border-color: @PRIMARY_BORDER; }

/* ================= الشريط العلوي ================= */
QFrame#topbar {
    background: @CARD;
    border: none; border-bottom: 1px solid @BORDER;
}
QLabel#topbarTitle { color: @TEXT; font-size: 13pt; font-weight: bold; }
QLabel#chip {
    background: @SURFACE; color: @TEXT_SOFT;
    border: 1px solid @BORDER; border-radius: 13px; padding: 5px 14px;
}
QLabel#chipAccent {
    background: @PRIMARY_SOFT; color: @ACCENT_TEXT;
    border: 1px solid @PRIMARY_BORDER; border-radius: 13px; padding: 5px 14px;
    font-weight: bold;
}

/* ================= ترويسة الصفحة ================= */
QFrame#titleAccent {
    background: qlineargradient(y1:0, y2:1, stop:0 #818cf8, stop:1 #6366f1);
    border-radius: 3px; max-width: 6px;
}
QLabel#pageTitle { font-size: 16pt; font-weight: bold; color: @TEXT; }
QLabel#pageSub   { color: @MUTED; font-size: 10pt; }
QLabel#sectionLabel {
    font-weight: bold; color: @TEXT_SOFT; font-size: 10.5pt;
    background: transparent;
}

/* نصوص مساعدة / حالة تتكيّف مع الوضعين */
QLabel#mutedText { color: @MUTED; font-size: 9pt; }
QLabel#noteWarn  { color: @WARN_TEXT; font-size: 9pt; }
QLabel#textOk    { color: @SUCCESS; font-weight: bold; }
QLabel#textWarn  { color: @WARNING; font-weight: bold; }
QLabel#netValue  { font-size: 14pt; font-weight: bold; color: @ACCENT_TEXT; }

/* ================= الأزرار ================= */
QPushButton {
    background: @CARD; border: 1px solid @BORDER; border-radius: 10px;
    padding: 8px 16px; font-size: 10.5pt; color: @TEXT_SOFT;
}
QPushButton:hover { background: @SURFACE; border-color: @SCROLL_HOVER; }
QPushButton:pressed { background: @PRESSED; }
QPushButton:disabled { color: @FAINT; background: @DISABLED_BG; border-color: @BORDER; }

QPushButton#primary {
    background: qlineargradient(y1:0, y2:1, stop:0 @PRIMARY_HOVER, stop:1 @PRIMARY);
    color: white; border: none; font-weight: bold; padding: 9px 20px;
}
QPushButton#primary:hover {
    background: qlineargradient(y1:0, y2:1, stop:0 @PRIMARY_DEEP2, stop:1 @PRIMARY_HOVER);
}
QPushButton#primary:pressed { background: @PRIMARY_DEEP; }
QPushButton#primary:disabled { color: @BTN_DIS_TEXT; background: @BTN_DIS_BG; }

QPushButton#danger {
    background: @DANGER_SOFT; color: @DANGER;
    border: 1px solid @DANGER_BORDER; border-radius: 10px; padding: 8px 18px;
}
QPushButton#danger:hover { background: @DANGER_SOFT; }

QPushButton#success {
    background: @SUCCESS_SOFT; color: @SUCCESS_DEEP;
    border: 1px solid @SUCCESS_BORDER; border-radius: 10px; padding: 8px 18px;
}
QPushButton#success:hover { background: @SUCCESS_SOFT; }

/* --- أزرار العمليات داخل الجداول (حبوب أيقونية ملوّنة) --- */
QPushButton#rowBtn, QPushButton#rowBtnEdit, QPushButton#rowBtnExtra,
QPushButton#rowBtnPrint, QPushButton#rowBtnMoney, QPushButton#rowBtnDanger {
    border: none; border-radius: 8px; font-size: 10.5pt; padding: 4px;
}
QPushButton#rowBtn      { background: @PRIMARY_SOFT; color: @ACCENT_TEXT; }
QPushButton#rowBtn:hover { background: @PRIMARY_BORDER; color: @TEXT; }
QPushButton#rowBtnEdit { background: @WARNING_SOFT; color: @WARNING; }
QPushButton#rowBtnEdit:hover { background: @WARNING_BORDER; }
QPushButton#rowBtnExtra { background: @VIOLET_SOFT; color: @VIOLET; }
QPushButton#rowBtnExtra:hover { background: @PRIMARY_BORDER; }
QPushButton#rowBtnPrint { background: @SURFACE; color: @TEXT_SOFT;
                           border: 1px solid @BORDER; }
QPushButton#rowBtnPrint:hover { background: @HOVER2; }
QPushButton#rowBtnMoney { background: @SUCCESS_SOFT; color: @SUCCESS_DEEP; }
QPushButton#rowBtnMoney:hover { background: @SUCCESS_BORDER; }
QPushButton#rowBtnDanger { background: @DANGER_SOFT; color: @DANGER; }
QPushButton#rowBtnDanger:hover { background: @DANGER_BORDER; }

/* --- مجموعة أدوات التصدير --- */
QFrame#exportGroup {
    background: @SURFACE; border: 1px solid @BORDER;
    border-radius: 12px; padding: 3px;
}
QPushButton#btnExcel { background: transparent; border: none; border-radius: 9px;
                        padding: 7px 14px; color: @SUCCESS; font-weight: 600; }
QPushButton#btnExcel:hover { background: @SUCCESS_SOFT; }
QPushButton#btnPdf   { background: transparent; border: none; border-radius: 9px;
                        padding: 7px 14px; color: @DANGER; font-weight: 600; }
QPushButton#btnPdf:hover { background: @DANGER_SOFT; }
QPushButton#btnPrint { background: transparent; border: none; border-radius: 9px;
                        padding: 7px 14px; color: @TEXT_SOFT; font-weight: 600; }
QPushButton#btnPrint:hover { background: @HOVER; }

/* ================= حقول الإدخال ================= */
QLineEdit, QComboBox, QDateEdit, QTimeEdit, QSpinBox, QDoubleSpinBox, QTextEdit,
QPlainTextEdit {
    border: 1px solid @BORDER; border-radius: 10px; padding: 7px 10px;
    background: @INPUT_BG; font-size: 10.5pt; color: @TEXT;
    selection-background-color: @SELECT_BG; selection-color: @SELECT_TEXT;
}
QLineEdit:hover, QComboBox:hover, QDateEdit:hover, QSpinBox:hover,
QDoubleSpinBox:hover, QTextEdit:hover, QPlainTextEdit:hover {
    border-color: @SCROLL_HOVER;
}
QLineEdit:focus, QComboBox:focus, QDateEdit:focus, QTimeEdit:focus,
QSpinBox:focus, QDoubleSpinBox:focus, QTextEdit:focus, QPlainTextEdit:focus {
    border: 1px solid @PRIMARY; background: @INPUT_FOCUS_BG;
}
QLineEdit:disabled, QComboBox:disabled, QDateEdit:disabled,
QSpinBox:disabled, QDoubleSpinBox:disabled {
    color: @FAINT; background: @DISABLED_BG;
}
QComboBox::drop-down { width: 28px; border: none; }
QComboBox QAbstractItemView {
    background: @INPUT_BG; border: 1px solid @BORDER;
    border-radius: 12px; padding: 4px;
    selection-background-color: @PRIMARY_SOFT; selection-color: @ACCENT_TEXT;
    outline: 0;
}
QComboBox QAbstractItemView::item { padding: 7px 10px; border-radius: 8px;
                                     color: @TEXT; }
QDateEdit::drop-down { width: 26px; border: none; }
QTextEdit { line-height: 1.45; }
QDateTimeEdit { border: 1px solid @BORDER; border-radius: 10px;
                padding: 7px 10px; background: @INPUT_BG; color: @TEXT; }

/* ================= الجداول (بلا خطوط شبكية عمياء) ================= */
QTableWidget, QTableView {
    border: none; border-radius: 12px;
    background: @CARD; alternate-background-color: @ALT_ROW;
    gridline-color: transparent; font-size: 10.5pt; color: @TEXT;
    selection-background-color: @PRIMARY_SOFT; selection-color: @TEXT;
}
QTableWidget::item, QTableView::item {
    padding: 6px 10px; border-bottom: 1px solid @BORDER;
}
QTableWidget::item:hover, QTableView::item:hover { background: @ROW_HOVER; }
QTableWidget::item:selected, QTableView::item:selected {
    background: @PRIMARY_SOFT; color: @TEXT;
}
QHeaderView { background: transparent; border: none; }
QHeaderView::section {
    background: @HEADER_BG; color: @MUTED; font-weight: bold;
    font-size: 10pt; padding: 11px 8px; border: none;
    border-bottom: 2px solid @BORDER;
}
QTableCornerButton::section { background: @HEADER_BG; border: none;
                               border-bottom: 2px solid @BORDER; }

/* ================= التبويبات ================= */
QTabWidget::pane {
    border: 1px solid @BORDER; border-radius: 12px; background: @CARD; top: -1px;
}
QTabBar::tab {
    background: transparent; color: @TEXT_SOFT; padding: 9px 20px;
    font-size: 10.5pt; margin: 3px 2px; border-radius: 9px;
}
QTabBar::tab:hover { background: @HOVER; }
QTabBar::tab:selected {
    background: @PRIMARY_SOFT; color: @ACCENT_TEXT; font-weight: bold;
    border: none; border-bottom: 2px solid @PRIMARY;
}

/* ================= المجموعات (GroupBox) ================= */
QGroupBox {
    background: @CARD; border: 1px solid @BORDER; border-radius: 14px;
    margin-top: 16px; font-weight: bold; color: @TEXT_SOFT; font-size: 11pt;
}
QGroupBox::title {
    subcontrol-origin: margin; right: 16px; padding: 0 8px;
    color: @ACCENT_TEXT;
}

/* ================= أشرطة التمرير ================= */
QScrollBar:vertical { background: transparent; width: 10px; margin: 2px; }
QScrollBar::handle:vertical {
    background: @SCROLL; border-radius: 5px; min-height: 32px;
}
QScrollBar::handle:vertical:hover { background: @SCROLL_HOVER; }
QScrollBar::add-line, QScrollBar::sub-line { height: 0; width: 0; }
QScrollBar::add-page, QScrollBar::sub-page { background: transparent; }
QScrollBar:horizontal { background: transparent; height: 10px; margin: 2px; }
QScrollBar::handle:horizontal {
    background: @SCROLL; border-radius: 5px; min-width: 32px;
}
QScrollBar::handle:horizontal:hover { background: @SCROLL_HOVER; }

/* ================= بطاقات الفلاتر والمؤشرات ================= */
QFrame#filterCard {
    background: @SURFACE; border: 1px solid @BORDER;
    border-radius: 12px;
}
QLabel#filterLabel { color: @TEXT_SOFT; font-size: 9.5pt; background: transparent; }

QFrame#kpiCard {
    background: @CARD; border: 1px solid @BORDER; border-radius: 14px;
}
QLabel#kpiCaption {
    color: @MUTED; font-size: 9.5pt; font-weight: bold; background: transparent;
}
QLabel#kpiValue { font-size: 14pt; font-weight: bold; background: transparent; }

/* ================= الحواريات ================= */
QLabel#dialogTitle { font-size: 14pt; font-weight: bold; color: @TEXT; }
QLabel#dialogHint  { color: @MUTED; font-size: 9.5pt; }
QLabel#totalValue { font-size: 13pt; font-weight: bold; color: @ACCENT_TEXT; }
QLabel#totalValueNeg { font-size: 13pt; font-weight: bold; color: @DANGER; }

QMessageBox { background: @CARD; }
QMessageBox QLabel { color: @TEXT; font-size: 11pt; min-width: 280px; }

QStatusBar { background: @CARD; color: @MUTED; border-top: 1px solid @BORDER; }

QMenu {
    background: @CARD; border: 1px solid @BORDER; border-radius: 10px; padding: 4px;
}
QMenu::item { padding: 8px 22px; border-radius: 8px; color: @TEXT_SOFT; }
QMenu::item:selected { background: @PRIMARY_SOFT; color: @ACCENT_TEXT; }

QCheckBox { color: @TEXT_SOFT; font-size: 10.5pt; spacing: 8px; }
QCheckBox::indicator {
    width: 18px; height: 18px; border: 1px solid @SCROLL_HOVER; border-radius: 5px;
    background: @INPUT_BG;
}
QCheckBox::indicator:checked {
    background: @PRIMARY; border-color: @PRIMARY;
    image: url(@CHECK);
}
QCheckBox::indicator:hover { border-color: @PRIMARY; }

QSpinBox::up-button, QDoubleSpinBox::up-button,
QSpinBox::down-button, QDoubleSpinBox::down-button {
    background: transparent; border: none; width: 18px;
}
QSpinBox::up-button:hover, QDoubleSpinBox::up-button:hover,
QSpinBox::down-button:hover, QDoubleSpinBox::down-button:hover {
    background: @HOVER2; border-radius: 4px;
}
"""


def _checkmark_png() -> str:
    """توليد علامة ✓ بيضاء صغيرة لصناديق الاختيار المحددة."""
    from PySide6.QtCore import QSize
    from PySide6.QtGui import QImage, QPainter, QPen

    img = QImage(QSize(18, 18), QImage.Format.Format_ARGB32)
    img.fill(Qt.GlobalColor.transparent)
    p = QPainter(img)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    pen = QPen(QColor("#ffffff"), 3)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    p.setPen(pen)
    p.drawLine(4, 9, 8, 13)
    p.drawLine(8, 13, 14, 5)
    p.end()
    path = os.path.join(tempfile.gettempdir(), "logistic_checkmark.png")
    img.save(path)
    return path


def build_stylesheet(pal: dict[str, str]) -> str:
    """بناء ملف الأنماط من لوحة ألوان معيّنة."""
    from ..utils.fonts import pick_font_family
    family = pick_font_family()
    css = _STYLE_TEMPLATE.replace("@FONT", family)
    try:
        css = css.replace("@CHECK", _checkmark_png().replace("\\", "/"))
    except Exception:  # noqa: BLE001
        css = css.replace("image: url(@CHECK);", "image: url(none);")
    for key, value in pal.items():
        css = css.replace("@" + key, value)
    # أي رمز متبقٍّ بلا قيمة (أمان) يُستبدل بلون محايد
    return css


def _apply_palette(app: QApplication, pal: dict[str, str]) -> None:
    """تطبيق لوحة الألوان على التطبيق: اللوحة + ملف الأنماط."""
    font = QFont(pick_font_family(), 10)
    font.setStyleHint(QFont.StyleHint.SansSerif)
    app.setFont(font)
    qpal = app.palette()
    qpal.setColor(QPalette.ColorRole.Window, QColor(pal["BG"]))
    qpal.setColor(QPalette.ColorRole.WindowText, QColor(pal["TEXT"]))
    qpal.setColor(QPalette.ColorRole.Base, QColor(pal["INPUT_BG"]))
    qpal.setColor(QPalette.ColorRole.AlternateBase, QColor(pal["ALT_ROW"]))
    qpal.setColor(QPalette.ColorRole.Text, QColor(pal["TEXT"]))
    qpal.setColor(QPalette.ColorRole.Button, QColor(pal["CARD"]))
    qpal.setColor(QPalette.ColorRole.ButtonText, QColor(pal["TEXT"]))
    qpal.setColor(QPalette.ColorRole.Highlight, QColor(pal["PRIMARY"]))
    qpal.setColor(QPalette.ColorRole.HighlightedText, QColor(pal["SELECT_TEXT"]))
    qpal.setColor(QPalette.ColorRole.ToolTipBase, QColor(pal["CARD"]))
    qpal.setColor(QPalette.ColorRole.ToolTipText, QColor(pal["TEXT"]))
    qpal.setColor(QPalette.ColorRole.PlaceholderText, QColor(pal["FAINT"]))
    app.setPalette(qpal)
    app.setStyleSheet(build_stylesheet(pal))


def apply_theme(app: QApplication, dark: bool = False) -> None:
    """تطبيق الثيم على التطبيق. الافتراضي فاتح للحفاظ على السلوك السابق.

    dark=True يطبّق الوضع الداكن الجديد.
    """
    global _active_mode
    _active_mode = "dark" if dark else "light"
    _apply_palette(app, _PALETTES[_active_mode])


def set_dark(app: QApplication, dark: bool) -> None:
    """تبديل الوضع (فاتح/داكن) وإعادة تلوين الواجهة كلها فوراً."""
    apply_theme(app, dark=bool(dark))


def toggle_theme(app: QApplication) -> bool:
    """عكس الوضع الحالي وإعادة تلوين الواجهة. يُرجع الوضع الجديد (داكن؟)."""
    apply_theme(app, dark=not _active_mode == "dark")
    return _active_mode == "dark"
