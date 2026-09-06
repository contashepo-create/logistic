# -*- coding: utf-8 -*-
"""
ثيم التطبيق الحديث: نظام ألوان احترافي + ورقة أنماط QSS بأسلوب لوحات
التحكم الحديثة (Design System موحّد لكل مكوّنات الواجهة).

لوحة الألوان (مستوحاة من أنظمة التصميم الحديثة):
  - أساسي أزرق نابض        PRIMARY   #2563eb
  - خلفية رمادية فاتحة      BG        #eef1f6
  - بطاقات بيضاء            CARD      #ffffff
  - شريط جانبي كحلي داكن    SIDEBAR   #0d1b2e
  - نص داكن / نص خافت       TEXT / MUTED
  - ألوان حالة: أخضر / أحمر / كهرماني / بنفسجي
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont, QPalette
from PySide6.QtWidgets import QApplication

from ..utils.fonts import pick_font_family

# ---------------------------------------------------------------------------
# الرموز اللونية (Design Tokens)
# ---------------------------------------------------------------------------
PRIMARY = "#2563eb"          # الأزرق الأساسي (أزرق نابض حديث)
PRIMARY_DARK = "#1e4fc4"     # عند الضغط
PRIMARY_DEEP = "#1b3a8f"     # تدرّج غامق
PRIMARY_SOFT = "#eaf1fe"     # خلفية زرقاء ناعمة
BORDER_STRONG = "#c4d7f7"    # حدود زرقاء للعناصر المحددة

BG = "#eef1f6"               # خلفية الصفحة
CARD = "#ffffff"             # خلفية البطاقات
SURFACE = "#f8fafc"          # سطح خفيف داخل البطاقات
BORDER = "#e3e8ef"           # الحدود العامة

TEXT = "#101828"             # النص الأساسي
TEXT_SOFT = "#475467"        # نص ثانوي
MUTED = "#8493a8"            # نص خافت

DANGER = "#d92d20"           # أحمر (حذف / أرصدة سالبة)
DANGER_SOFT = "#fef3f2"
DANGER_BORDER = "#fecdca"
SUCCESS = "#12b76a"          # أخضر (تحقق / أرصدة موجبة)
SUCCESS_SOFT = "#ecfdf3"
WARNING = "#dc6803"          # كهرماني (تحرير / تنبيه)
WARNING_SOFT = "#fffaeb"
VIOLET = "#7a5af8"           # بنفسجي (كشوف / أدوات)
VIOLET_SOFT = "#f4f3ff"

SIDEBAR = "#0d1b2e"          # الشريط الجانبي الكحلي
SIDEBAR_EDGE = "#16273f"     # خط فاصل داخل الشريط
ON_SIDEBAR = "#c3cfdf"       # نص عناصر الشريط

# ---------------------------------------------------------------------------
# ورقة الأنماط الموحّدة
# ---------------------------------------------------------------------------
STYLE = f"""
* {{
    font-family: 'FiraGO', 'Segoe UI', 'Tahoma', 'Noto Sans Arabic', sans-serif;
    outline: none;
}}
QMainWindow, QDialog {{ background: {BG}; }}

/* ================= البطاقات والصفحات ================= */
QWidget#page {{
    background: {CARD};
    border: 1px solid {BORDER};
    border-radius: 16px;
}}

/* ================= الشريط الجانبي ================= */
QFrame#sidebar {{
    background: qlineargradient(y1:0, y2:1, stop:0 #0d1b2e, stop:1 #10233d);
    border: none;
}}
QLabel#brandName  {{ color: #ffffff; font-size: 13pt; font-weight: bold; background: transparent; }}
QLabel#brandSub   {{ color: #7d93b5; font-size: 8.5pt; background: transparent; }}
QLabel#brandBadge {{
    background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                                stop:0 #2563eb, stop:1 #4f8bff);
    color: white; border-radius: 12px; font-size: 15pt;
}}
QFrame#navSeparator {{ background: {SIDEBAR_EDGE}; border: none; max-height: 1px; }}

QListWidget#nav {{
    background: transparent; border: none; font-size: 10.5pt; outline: 0;
    padding: 4px 2px;
}}
QListWidget#nav::item {{
    color: {ON_SIDEBAR}; padding: 10px 14px; margin: 2px 8px;
    border-radius: 10px;
}}
QListWidget#nav::item:hover {{ background: rgba(255, 255, 255, 0.07); }}
QListWidget#nav::item:selected {{
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                                stop:0 #2563eb, stop:1 #3f7af5);
    color: white; font-weight: bold;
}}
QListWidget#nav::item:disabled {{
    color: #647d9d; font-weight: bold; font-size: 8.5pt;
    background: transparent; margin: 12px 8px 2px 8px; padding: 2px 6px;
}}

QFrame#navFooter {{
    background: rgba(255, 255, 255, 0.05);
    border: 1px solid rgba(255, 255, 255, 0.08);
    border-radius: 12px;
}}
QLabel#navFooterTitle {{ color: #7d93b5; font-size: 8.5pt; background: transparent; }}
QLabel#navFooterValue {{ color: #e6edf6; font-size: 10pt; font-weight: bold;
                          background: transparent; }}

/* ================= الشريط العلوي ================= */
QFrame#topbar {{
    background: {CARD};
    border: none; border-bottom: 1px solid {BORDER};
}}
QLabel#topbarTitle {{ color: {TEXT}; font-size: 13pt; font-weight: bold; }}
QLabel#chip {{
    background: {SURFACE}; color: {TEXT_SOFT};
    border: 1px solid {BORDER}; border-radius: 13px; padding: 5px 14px;
}}
QLabel#chipAccent {{
    background: {PRIMARY_SOFT}; color: {PRIMARY_DARK};
    border: 1px solid {BORDER_STRONG}; border-radius: 13px; padding: 5px 14px;
    font-weight: bold;
}}

/* ================= ترويسة الصفحة ================= */
QFrame#titleAccent {{
    background: qlineargradient(y1:0, y2:1, stop:0 #2563eb, stop:1 #67a1ff);
    border-radius: 3px; max-width: 6px;
}}
QLabel#pageTitle {{ font-size: 16pt; font-weight: bold; color: {TEXT}; }}
QLabel#pageSub   {{ color: {MUTED}; font-size: 10pt; }}
QLabel#sectionLabel {{
    font-weight: bold; color: {TEXT_SOFT}; font-size: 10.5pt;
    background: transparent;
}}

/* ================= الأزرار ================= */
QPushButton {{
    background: {CARD}; border: 1px solid {BORDER}; border-radius: 10px;
    padding: 8px 16px; font-size: 10.5pt; color: {TEXT_SOFT};
}}
QPushButton:hover {{ background: {SURFACE}; border-color: #cfd8e3; }}
QPushButton:pressed {{ background: #eef2f7; }}
QPushButton:disabled {{ color: {MUTED}; background: #f2f4f7; border-color: {BORDER}; }}

QPushButton#primary {{
    background: qlineargradient(y1:0, y2:1, stop:0 #2f6ef0, stop:1 #2563eb);
    color: white; border: none; font-weight: bold; padding: 9px 20px;
}}
QPushButton#primary:hover {{
    background: qlineargradient(y1:0, y2:1, stop:0 #4a80f3, stop:1 #2f6ef0);
}}
QPushButton#primary:pressed {{ background: {PRIMARY_DARK}; }}
QPushButton#primary:disabled {{ color: #d6e2fb; background: #9db8ea; }}

QPushButton#danger {{
    background: {DANGER_SOFT}; color: {DANGER};
    border: 1px solid {DANGER_BORDER}; border-radius: 10px; padding: 8px 18px;
}}
QPushButton#danger:hover {{ background: #fde4e2; }}

QPushButton#success {{
    background: {SUCCESS_SOFT}; color: #037947;
    border: 1px solid #a9e5c7; border-radius: 10px; padding: 8px 18px;
}}
QPushButton#success:hover {{ background: #d6f5e4; }}

/* --- أزرار العمليات داخل الجداول (أيقونية ملونة) --- */
QPushButton#rowBtn, QPushButton#rowBtnEdit, QPushButton#rowBtnExtra,
QPushButton#rowBtnPrint, QPushButton#rowBtnMoney, QPushButton#rowBtnDanger {{
    border: none; border-radius: 8px; font-size: 10.5pt; padding: 4px;
}}
QPushButton#rowBtn      {{ background: {PRIMARY_SOFT}; color: {PRIMARY_DARK}; }}
QPushButton#rowBtn:hover {{ background: #d8e6fd; }}
QPushButton#rowBtnEdit {{ background: {WARNING_SOFT}; color: {WARNING}; }}
QPushButton#rowBtnEdit:hover {{ background: #fdf0cf; }}
QPushButton#rowBtnExtra {{ background: {VIOLET_SOFT}; color: {VIOLET}; }}
QPushButton#rowBtnExtra:hover {{ background: #e9e5ff; }}
QPushButton#rowBtnPrint {{ background: {SURFACE}; color: {TEXT_SOFT};
                           border: 1px solid {BORDER}; }}
QPushButton#rowBtnPrint:hover {{ background: #e9edf3; }}
QPushButton#rowBtnMoney {{ background: {SUCCESS_SOFT}; color: #037947; }}
QPushButton#rowBtnMoney:hover {{ background: #d6f5e4; }}
QPushButton#rowBtnDanger {{ background: {DANGER_SOFT}; color: {DANGER}; }}
QPushButton#rowBtnDanger:hover {{ background: #fde4e2; }}

/* --- مجموعة أدوات التصدير --- */
QFrame#exportGroup {{
    background: {SURFACE}; border: 1px solid {BORDER};
    border-radius: 12px; padding: 3px;
}}
QPushButton#btnExcel {{ background: transparent; border: none; border-radius: 9px;
                        padding: 7px 14px; color: #039b5e; font-weight: 600; }}
QPushButton#btnExcel:hover {{ background: #dcf5e9; }}
QPushButton#btnPdf   {{ background: transparent; border: none; border-radius: 9px;
                        padding: 7px 14px; color: {DANGER}; font-weight: 600; }}
QPushButton#btnPdf:hover {{ background: #fde6e4; }}
QPushButton#btnPrint {{ background: transparent; border: none; border-radius: 9px;
                        padding: 7px 14px; color: {TEXT_SOFT}; font-weight: 600; }}
QPushButton#btnPrint:hover {{ background: #e9edf3; }}

/* ================= حقول الإدخال ================= */
QLineEdit, QComboBox, QDateEdit, QTimeEdit, QSpinBox, QDoubleSpinBox, QTextEdit,
QPlainTextEdit {{
    border: 1px solid {BORDER}; border-radius: 10px; padding: 7px 10px;
    background: white; font-size: 10.5pt; color: {TEXT};
    selection-background-color: {PRIMARY}; selection-color: white;
}}
QLineEdit:hover, QComboBox:hover, QDateEdit:hover, QSpinBox:hover,
QDoubleSpinBox:hover, QTextEdit:hover, QPlainTextEdit:hover {{
    border-color: #cfd8e3;
}}
QLineEdit:focus, QComboBox:focus, QDateEdit:focus, QTimeEdit:focus,
QSpinBox:focus, QDoubleSpinBox:focus, QTextEdit:focus, QPlainTextEdit:focus {{
    border: 1px solid {PRIMARY}; background: #fdfeff;
}}
QLineEdit:disabled, QComboBox:disabled, QDateEdit:disabled,
QSpinBox:disabled, QDoubleSpinBox:disabled {{
    color: {MUTED}; background: #f4f6f9;
}}
QComboBox::drop-down {{ width: 28px; border: none; }}
QComboBox QAbstractItemView {{
    background: white; border: 1px solid {BORDER};
    border-radius: 12px; padding: 4px;
    selection-background-color: {PRIMARY_SOFT}; selection-color: {PRIMARY_DARK};
    outline: 0;
}}
QComboBox QAbstractItemView::item {{ padding: 7px 10px; border-radius: 8px; }}
QDateEdit::drop-down {{ width: 26px; border: none; }}

QTextEdit {{ line-height: 1.45; }}

/* ================= الجداول ================= */
QTableWidget, QTableView {{
    border: 1px solid {BORDER}; border-radius: 12px;
    background: white; alternate-background-color: #fafbfd;
    gridline-color: #f0f3f8; font-size: 10.5pt; color: {TEXT};
    selection-background-color: {PRIMARY_SOFT}; selection-color: {TEXT};
}}
QTableWidget::item, QTableView::item {{
    padding: 6px 10px; border-bottom: 1px solid #f2f5f9;
}}
QTableWidget::item:selected, QTableView::item:selected {{
    background: {PRIMARY_SOFT}; color: {TEXT};
}}
QHeaderView {{ background: transparent; border: none; }}
QHeaderView::section {{
    background: {SURFACE}; color: {TEXT_SOFT}; font-weight: bold;
    font-size: 10pt; padding: 11px 8px; border: none;
    border-bottom: 2px solid {BORDER};
}}
QTableCornerButton::section {{
    background: {SURFACE}; border: none;
    border-bottom: 2px solid {BORDER};
}}
QTableView QTableCornerButton::section {{ background: {SURFACE}; }}

/* ================= التبويبات ================= */
QTabWidget::pane {{
    border: 1px solid {BORDER}; border-radius: 12px; background: white; top: -1px;
}}
QTabBar::tab {{
    background: transparent; color: {TEXT_SOFT}; padding: 9px 20px;
    font-size: 10.5pt; margin: 3px 2px; border-radius: 9px;
}}
QTabBar::tab:hover {{ background: #e9edf3; }}
QTabBar::tab:selected {{
    background: white; color: {PRIMARY_DARK}; font-weight: bold;
    border: 1px solid {BORDER}; border-bottom: 2px solid {PRIMARY};
}}

/* ================= المجموعات (GroupBox) ================= */
QGroupBox {{
    background: white; border: 1px solid {BORDER}; border-radius: 14px;
    margin-top: 16px; font-weight: bold; color: {TEXT_SOFT}; font-size: 11pt;
}}
QGroupBox::title {{
    subcontrol-origin: margin; right: 16px; padding: 0 8px;
    color: {PRIMARY_DARK};
}}

/* ================= أشرطة التمرير ================= */
QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
QScrollBar::handle:vertical {{
    background: #c6cfdc; border-radius: 5px; min-height: 32px;
}}
QScrollBar::handle:vertical:hover {{ background: #a9b6c6; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; width: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}
QScrollBar:horizontal {{ background: transparent; height: 10px; margin: 2px; }}
QScrollBar::handle:horizontal {{
    background: #c6cfdc; border-radius: 5px; min-width: 32px;
}}
QScrollBar::handle:horizontal:hover {{ background: #a9b6c6; }}

/* ================= شرائح الفلاتر والبطاقات التحليلية ================= */
QFrame#filterCard {{
    background: {SURFACE}; border: 1px solid {BORDER};
    border-radius: 12px;
}}
QLabel#filterLabel {{ color: {TEXT_SOFT}; font-size: 9.5pt; background: transparent; }}

QFrame#kpiCard {{
    background: white; border: 1px solid {BORDER}; border-radius: 14px;
}}
QLabel#kpiCaption {{
    color: {MUTED}; font-size: 9.5pt; font-weight: bold; background: transparent;
}}
QLabel#kpiValue {{ font-size: 14pt; font-weight: bold; background: transparent; }}

/* ================= الحواريات ================= */
QLabel#dialogTitle {{ font-size: 14pt; font-weight: bold; color: {TEXT}; }}
QLabel#dialogHint  {{ color: {MUTED}; font-size: 9.5pt; }}
QLabel#totalValue {{ font-size: 13pt; font-weight: bold; color: {PRIMARY_DARK}; }}
QLabel#totalValueNeg {{ font-size: 13pt; font-weight: bold; color: {DANGER}; }}

QMessageBox {{ background: white; }}
QMessageBox QLabel {{ color: {TEXT}; font-size: 11pt; min-width: 280px; }}

QStatusBar {{
    background: {CARD}; color: {MUTED};
    border-top: 1px solid {BORDER};
}}
QToolBar {{ background: {CARD}; border-bottom: 1px solid {BORDER}; }}

QMenu {{
    background: white; border: 1px solid {BORDER}; border-radius: 10px; padding: 4px;
}}
QMenu::item {{ padding: 8px 22px; border-radius: 8px; color: {TEXT_SOFT}; }}
QMenu::item:selected {{ background: {PRIMARY_SOFT}; color: {PRIMARY_DARK}; }}

QCheckBox {{ color: {TEXT_SOFT}; font-size: 10.5pt; spacing: 8px; }}
QCheckBox::indicator {{
    width: 18px; height: 18px; border: 1px solid {BORDER}; border-radius: 5px;
    background: white;
}}
QCheckBox::indicator:checked {{
    background: {PRIMARY}; border-color: {PRIMARY};
    image: url(none);
}}
QCheckBox::indicator:hover {{ border-color: {PRIMARY}; }}

QSpinBox::up-button, QDoubleSpinBox::up-button,
QSpinBox::down-button, QDoubleSpinBox::down-button {{
    background: transparent; border: none; width: 18px;
}}
QSpinBox::up-button:hover, QDoubleSpinBox::up-button:hover,
QSpinBox::down-button:hover, QDoubleSpinBox::down-button:hover {{
    background: {SURFACE}; border-radius: 4px;
}}
"""


def _make_checkmark_png() -> str:
    """توليد علامة ✓ بيضاء صغيرة لصناديق الاختيار (تُرسم وقت التشغيل)."""
    import os
    import tempfile

    from PySide6.QtCore import QSize
    from PySide6.QtGui import QColor, QImage, QPainter, QPen

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


def apply_theme(app: QApplication) -> None:
    app.setLayoutDirection(app.layoutDirection())
    family = pick_font_family()
    font = QFont(family, 10)
    font.setStyleHint(QFont.StyleHint.SansSerif)
    app.setFont(font)
    pal = app.palette()
    pal.setColor(QPalette.ColorRole.Window, QColor(BG))
    pal.setColor(QPalette.ColorRole.WindowText, QColor(TEXT))
    pal.setColor(QPalette.ColorRole.Base, QColor(CARD))
    pal.setColor(QPalette.ColorRole.Text, QColor(TEXT))
    pal.setColor(QPalette.ColorRole.Highlight, QColor(PRIMARY))
    pal.setColor(QPalette.ColorRole.HighlightedText, QColor("#ffffff"))
    app.setPalette(pal)
    # حقن علامة ✓ في صناديق الاختيار المحددة
    try:
        check_img = _make_checkmark_png().replace("\\", "/")
        style = STYLE.replace(
            "image: url(none);", f"image: url({check_img});")
        app.setStyleSheet(style)
    except Exception:  # noqa: BLE001 — لا تمنع بدء التطبيق لأجل علامة
        app.setStyleSheet(STYLE)
