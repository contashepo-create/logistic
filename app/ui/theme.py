# -*- coding: utf-8 -*-
"""
ثيم التطبيق الحديث بأسلوب لوحات تحكم React (shadcn/Tailwind-style):
شريط جانبي أبيض نظيف، لون أساسي نيلي (Indigo)، خلفية رمادية فاتحة،
بطاقات بيضاء بحواف دائرية كبيرة وحدود ناعمة، جداول بلا خطوط شبكية عمياء.

الرموز اللونية (Design Tokens):
  PRIMARY  #6366f1  نيلي حيوي (أزرار/تحديد/روابط)
  BG       #f6f7fb  خلفية التطبيق
  CARD     #ffffff  البطاقات
  SIDEBAR  #ffffff  الشريط الجانبي الأبيض بفاصل ناعم
"""
from __future__ import annotations

import os
import tempfile

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont, QPalette
from PySide6.QtWidgets import QApplication

from ..utils.fonts import pick_font_family

# ---------------------------------------------------------------------------
# الرموز اللونية
# ---------------------------------------------------------------------------
PRIMARY = "#6366f1"          # النيلي الأساسي
PRIMARY_DARK = "#4f46e5"     # عند الضغط / النصوص فوق الخلفيات الناعمة
PRIMARY_DEEP = "#4338ca"     # تدرّج غامق
PRIMARY_SOFT = "#eef2ff"     # خلفية نيلية ناعمة (تحديد، عناصر نشطة)
BORDER_STRONG = "#c7d2fe"    # حدود نيلية للعناصر المحددة

BG = "#f6f7fb"               # خلفية الصفحة
CARD = "#ffffff"             # خلفية البطاقات
SURFACE = "#f8fafc"          # سطح خفيف
BORDER = "#e5e7eb"           # الحدود العامة

TEXT = "#111827"             # النص الأساسي
TEXT_SOFT = "#374151"        # نص ثانوي
MUTED = "#6b7280"            # نص خافت
FAINT = "#9ca3af"            # نص أخفت (عناوين الأقسام)

DANGER = "#e02424"           # أحمر (حذف / سالب)
DANGER_SOFT = "#fef2f2"
DANGER_BORDER = "#fecaca"
SUCCESS = "#0e9f6e"          # أخضر (موجب / حفظ)
SUCCESS_SOFT = "#ecfdf5"
SUCCESS_DEEP = "#046c4e"
WARNING = "#d97706"          # كهرماني (تعديل)
WARNING_SOFT = "#fffbeb"
VIOLET = "#7c3aed"           # بنفسجي (كشوف / أدوات)
VIOLET_SOFT = "#f5f3ff"

SIDEBAR = "#ffffff"          # الشريط الجانبي الأبيض
SIDEBAR_EDGE = "#e5e7eb"     # خط الفاصل
ON_SIDEBAR = "#374151"       # نص عناصر الشريط

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

/* ================= الشريط الجانبي (أبيض نظيف) ================= */
QFrame#sidebar {{
    background: {SIDEBAR};
    border: none; border-left: 1px solid {BORDER};
}}
QLabel#brandName  {{ color: {TEXT}; font-size: 12.5pt; font-weight: bold;
                     background: transparent; }}
QLabel#brandSub   {{ color: {MUTED}; font-size: 8.5pt; background: transparent; }}
QLabel#brandBadge {{
    background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                                stop:0 #6366f1, stop:1 #818cf8);
    color: white; border-radius: 12px; font-size: 15pt;
}}
QFrame#navSeparator {{ background: #f3f4f6; border: none; max-height: 1px; }}

QListWidget#nav {{
    background: transparent; border: none; font-size: 10.5pt; outline: 0;
    padding: 2px;
}}
QListWidget#nav::item {{
    color: {ON_SIDEBAR}; padding: 10px 14px; margin: 2px 6px;
    border-radius: 10px;
}}
QListWidget#nav::item:hover {{ background: #f3f4f6; color: {TEXT}; }}
QListWidget#nav::item:selected {{
    background: {PRIMARY_SOFT}; color: {PRIMARY_DARK}; font-weight: bold;
    border-left: none;
}}
QListWidget#nav::item:disabled {{
    color: {FAINT}; font-weight: bold; font-size: 8.5pt;
    background: transparent; margin: 12px 6px 2px 6px; padding: 2px 8px;
}}

QFrame#navFooter {{
    background: {SURFACE};
    border: 1px solid {BORDER};
    border-radius: 12px;
}}
QLabel#navFooterTitle {{ color: {MUTED}; font-size: 8.5pt; background: transparent; }}
QLabel#navFooterValue {{ color: {TEXT}; font-size: 10pt; font-weight: bold;
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
    background: qlineargradient(y1:0, y2:1, stop:0 #818cf8, stop:1 #6366f1);
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
QPushButton:hover {{ background: {SURFACE}; border-color: #d1d5db; }}
QPushButton:pressed {{ background: #f1f3f7; }}
QPushButton:disabled {{ color: {FAINT}; background: #f3f4f6; border-color: {BORDER}; }}

QPushButton#primary {{
    background: qlineargradient(y1:0, y2:1, stop:0 #7378f2, stop:1 #6366f1);
    color: white; border: none; font-weight: bold; padding: 9px 20px;
}}
QPushButton#primary:hover {{
    background: qlineargradient(y1:0, y2:1, stop:0 #8286f4, stop:1 #7378f2);
}}
QPushButton#primary:pressed {{ background: {PRIMARY_DARK}; }}
QPushButton#primary:disabled {{ color: #dfe3ff; background: #b1b5f5; }}

QPushButton#danger {{
    background: {DANGER_SOFT}; color: {DANGER};
    border: 1px solid {DANGER_BORDER}; border-radius: 10px; padding: 8px 18px;
}}
QPushButton#danger:hover {{ background: #fee2e2; }}

QPushButton#success {{
    background: {SUCCESS_SOFT}; color: {SUCCESS_DEEP};
    border: 1px solid #a7f3d0; border-radius: 10px; padding: 8px 18px;
}}
QPushButton#success:hover {{ background: #d1fae5; }}

/* --- أزرار العمليات داخل الجداول (حبوب أيقونية ملوّنة) --- */
QPushButton#rowBtn, QPushButton#rowBtnEdit, QPushButton#rowBtnExtra,
QPushButton#rowBtnPrint, QPushButton#rowBtnMoney, QPushButton#rowBtnDanger {{
    border: none; border-radius: 8px; font-size: 10.5pt; padding: 4px;
}}
QPushButton#rowBtn      {{ background: {PRIMARY_SOFT}; color: {PRIMARY_DARK}; }}
QPushButton#rowBtn:hover {{ background: #e0e7ff; }}
QPushButton#rowBtnEdit {{ background: {WARNING_SOFT}; color: {WARNING}; }}
QPushButton#rowBtnEdit:hover {{ background: #fef3c7; }}
QPushButton#rowBtnExtra {{ background: {VIOLET_SOFT}; color: {VIOLET}; }}
QPushButton#rowBtnExtra:hover {{ background: #ede9fe; }}
QPushButton#rowBtnPrint {{ background: {SURFACE}; color: {TEXT_SOFT};
                           border: 1px solid {BORDER}; }}
QPushButton#rowBtnPrint:hover {{ background: #eef0f4; }}
QPushButton#rowBtnMoney {{ background: {SUCCESS_SOFT}; color: {SUCCESS_DEEP}; }}
QPushButton#rowBtnMoney:hover {{ background: #d1fae5; }}
QPushButton#rowBtnDanger {{ background: {DANGER_SOFT}; color: {DANGER}; }}
QPushButton#rowBtnDanger:hover {{ background: #fee2e2; }}

/* --- مجموعة أدوات التصدير --- */
QFrame#exportGroup {{
    background: {SURFACE}; border: 1px solid {BORDER};
    border-radius: 12px; padding: 3px;
}}
QPushButton#btnExcel {{ background: transparent; border: none; border-radius: 9px;
                        padding: 7px 14px; color: {SUCCESS}; font-weight: 600; }}
QPushButton#btnExcel:hover {{ background: #d1fae5; }}
QPushButton#btnPdf   {{ background: transparent; border: none; border-radius: 9px;
                        padding: 7px 14px; color: {DANGER}; font-weight: 600; }}
QPushButton#btnPdf:hover {{ background: #fee2e2; }}
QPushButton#btnPrint {{ background: transparent; border: none; border-radius: 9px;
                        padding: 7px 14px; color: {TEXT_SOFT}; font-weight: 600; }}
QPushButton#btnPrint:hover {{ background: #eef0f4; }}

/* ================= حقول الإدخال ================= */
QLineEdit, QComboBox, QDateEdit, QTimeEdit, QSpinBox, QDoubleSpinBox, QTextEdit,
QPlainTextEdit {{
    border: 1px solid {BORDER}; border-radius: 10px; padding: 7px 10px;
    background: white; font-size: 10.5pt; color: {TEXT};
    selection-background-color: {PRIMARY}; selection-color: white;
}}
QLineEdit:hover, QComboBox:hover, QDateEdit:hover, QSpinBox:hover,
QDoubleSpinBox:hover, QTextEdit:hover, QPlainTextEdit:hover {{
    border-color: #d1d5db;
}}
QLineEdit:focus, QComboBox:focus, QDateEdit:focus, QTimeEdit:focus,
QSpinBox:focus, QDoubleSpinBox:focus, QTextEdit:focus, QPlainTextEdit:focus {{
    border: 1px solid {PRIMARY}; background: #fdfdff;
}}
QLineEdit:disabled, QComboBox:disabled, QDateEdit:disabled,
QSpinBox:disabled, QDoubleSpinBox:disabled {{
    color: {FAINT}; background: #f5f6f8;
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

/* ================= الجداول (بلا خطوط شبكية عمياء) ================= */
QTableWidget, QTableView {{
    border: none; border-radius: 12px;
    background: white; alternate-background-color: #fcfcfd;
    gridline-color: transparent; font-size: 10.5pt; color: {TEXT};
    selection-background-color: {PRIMARY_SOFT}; selection-color: {TEXT};
}}
QTableWidget::item, QTableView::item {{
    padding: 6px 10px; border-bottom: 1px solid #f1f3f7;
}}
QTableWidget::item:hover, QTableView::item:hover {{ background: #f5f6ff; }}
QTableWidget::item:selected, QTableView::item:selected {{
    background: {PRIMARY_SOFT}; color: {TEXT};
}}
QHeaderView {{ background: transparent; border: none; }}
QHeaderView::section {{
    background: #fafbfc; color: {MUTED}; font-weight: bold;
    font-size: 10pt; padding: 11px 8px; border: none;
    border-bottom: 2px solid {BORDER};
}}
QTableCornerButton::section {{ background: #fafbfc; border: none;
                               border-bottom: 2px solid {BORDER}; }}

/* ================= التبويبات ================= */
QTabWidget::pane {{
    border: 1px solid {BORDER}; border-radius: 12px; background: white; top: -1px;
}}
QTabBar::tab {{
    background: transparent; color: {TEXT_SOFT}; padding: 9px 20px;
    font-size: 10.5pt; margin: 3px 2px; border-radius: 9px;
}}
QTabBar::tab:hover {{ background: #f3f4f6; }}
QTabBar::tab:selected {{
    background: {PRIMARY_SOFT}; color: {PRIMARY_DARK}; font-weight: bold;
    border: none; border-bottom: 2px solid {PRIMARY};
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
    background: #d7dbe2; border-radius: 5px; min-height: 32px;
}}
QScrollBar::handle:vertical:hover {{ background: #b9bfc9; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; width: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}
QScrollBar:horizontal {{ background: transparent; height: 10px; margin: 2px; }}
QScrollBar::handle:horizontal {{
    background: #d7dbe2; border-radius: 5px; min-width: 32px;
}}
QScrollBar::handle:horizontal:hover {{ background: #b9bfc9; }}

/* ================= بطاقات الفلاتر والمؤشرات ================= */
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

QStatusBar {{ background: {CARD}; color: {MUTED}; border-top: 1px solid {BORDER}; }}

QMenu {{
    background: white; border: 1px solid {BORDER}; border-radius: 10px; padding: 4px;
}}
QMenu::item {{ padding: 8px 22px; border-radius: 8px; color: {TEXT_SOFT}; }}
QMenu::item:selected {{ background: {PRIMARY_SOFT}; color: {PRIMARY_DARK}; }}

QCheckBox {{ color: {TEXT_SOFT}; font-size: 10.5pt; spacing: 8px; }}
QCheckBox::indicator {{
    width: 18px; height: 18px; border: 1px solid #d1d5db; border-radius: 5px;
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
