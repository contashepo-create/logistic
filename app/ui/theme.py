# -*- coding: utf-8 -*-
"""ثيم التطبيق: الخطوط والألوان وورقة الأنماط QSS."""
from __future__ import annotations

from PySide6.QtGui import QColor, QFont, QPalette
from PySide6.QtWidgets import QApplication

from ..utils.fonts import pick_font_family

PRIMARY = "#1f4e79"
PRIMARY_LIGHT = "#2e6da4"
BG = "#f4f6f9"
CARD = "#ffffff"
BORDER = "#d7dde5"
DANGER = "#b02a37"
SUCCESS = "#1e7d43"

STYLE = f"""
* {{ font-family: 'Segoe UI', 'Tahoma', 'Noto Kufi Arabic', sans-serif; }}
QMainWindow, QDialog {{ background: {BG}; }}
QWidget#page {{ background: {CARD}; border: 1px solid {BORDER};
               border-radius: 10px; }}
QLabel#pageTitle {{ font-size: 17pt; font-weight: bold; color: {PRIMARY}; }}
QLabel#pageSub {{ color: #64748b; font-size: 10.5pt; }}
QLabel#sectionLabel {{ font-weight: bold; color: {PRIMARY}; font-size: 11.5pt; }}

QPushButton {{
    background: #ffffff; border: 1px solid {BORDER}; border-radius: 6px;
    padding: 6px 14px; font-size: 10.5pt; color: #22303e;
}}
QPushButton:hover {{ background: #eef3f9; border-color: {PRIMARY_LIGHT}; }}
QPushButton:disabled {{ color: #9aa6b2; background: #f1f3f6; }}

QPushButton#primary {{
    background: {PRIMARY}; color: white; border: none; font-weight: bold;
    padding: 8px 18px;
}}
QPushButton#primary:hover {{ background: {PRIMARY_LIGHT}; }}
QPushButton#danger {{ background: transparent; color: {DANGER};
                      border: 1px solid {DANGER}; border-radius: 6px; padding: 6px 14px;}}
QPushButton#danger:hover {{ background: #f8e7e9; }}
QPushButton#rowBtn {{
    background: transparent; border: 1px solid {BORDER}; border-radius: 5px;
    padding: 1px 7px; font-size: 10pt;
}}
QPushButton#rowBtn:hover {{ background: #eef3f9; }}
QPushButton#rowBtnDanger {{ background: transparent; color: {DANGER};
    border: 1px solid #e3b6bb; border-radius: 5px; padding: 1px 7px; font-size: 10pt; }}
QPushButton#rowBtnDanger:hover {{ background: #f8e7e9; }}

QLineEdit, QComboBox, QDateEdit, QSpinBox, QDoubleSpinBox, QTextEdit {{
    border: 1px solid {BORDER}; border-radius: 6px; padding: 5px 8px;
    background: white; font-size: 10.5pt; selection-background-color: {PRIMARY_LIGHT};
}}
QLineEdit:focus, QComboBox:focus, QDateEdit:focus, QSpinBox:focus,
QDoubleSpinBox:focus, QTextEdit:focus {{ border: 1px solid {PRIMARY_LIGHT}; }}
QComboBox::drop-down {{ width: 26px; }}
QComboBox QAbstractItemView {{
    background: white; border: 1px solid {BORDER};
    selection-background-color: #dce8f5; selection-color: #22303e;
}}
QTextEdit {{ line-height: 1.4; }}

QTableWidget {{
    border: 1px solid {BORDER}; border-radius: 8px; gridline-color: #e6ebf1;
    selection-background-color: #dce8f5; selection-color: #22303e;
    alternate-background-color: #f7fafd; font-size: 10.5pt;
}}
QHeaderView::section {{
    background: {PRIMARY}; color: white; font-weight: bold; font-size: 10.5pt;
    padding: 7px 6px; border: none; border-left: 1px solid #35618c;
}}
QTableWidget::item {{ padding: 4px 8px; }}

QListWidget#nav {{ background: #16293d; border: none; font-size: 11.5pt; outline: 0; }}
QListWidget#nav::item {{ color: #c9d6e3; padding: 9px 16px; margin: 1px 6px;
                          border-radius: 6px; }}
QListWidget#nav::item:selected {{ background: {PRIMARY}; color: white; font-weight: bold; }}
QListWidget#nav::item:hover {{ background: #23405c; }}
QListWidget#nav::item:disabled {{ color: #7f93a8; font-weight: bold; }}

QTabWidget::pane {{ border: 1px solid {BORDER}; border-radius: 8px; background: white; }}
QTabBar::tab {{
    background: #e9eef4; color: #3c4a5a; padding: 7px 20px; font-size: 10.5pt;
    border-top-left-radius: 6px; border-top-right-radius: 6px; margin-left: 3px;
}}
QTabBar::tab:selected {{ background: white; color: {PRIMARY}; font-weight: bold;
                         border: 1px solid {BORDER}; border-bottom: none; }}

QGroupBox {{
    border: 1px solid {BORDER}; border-radius: 8px; margin-top: 12px;
    font-weight: bold; color: {PRIMARY};
}}
QGroupBox::title {{ subcontrol-origin: margin; right: 12px; padding: 0 6px; }}

QScrollBar:vertical {{ background: transparent; width: 11px; margin: 2px; }}
QScrollBar::handle:vertical {{ background: #c3cedb; border-radius: 5px; min-height: 30px; }}
QScrollBar::handle:vertical:hover {{ background: {PRIMARY_LIGHT}; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; width: 0; }}
QScrollBar:horizontal {{ background: transparent; height: 11px; margin: 2px; }}
QScrollBar::handle:horizontal {{ background: #c3cedb; border-radius: 5px; min-width: 30px; }}

QStatusBar {{ background: #eef1f5; color: #5a6b7d; }}
QLabel#totalCard {{
    background: #f0f5fa; border: 1px solid {BORDER}; border-radius: 8px;
    padding: 8px 14px; font-size: 11pt;
}}
QLabel#totalValue {{ font-size: 13pt; font-weight: bold; color: {PRIMARY}; }}
QLabel#totalValueNeg {{ font-size: 13pt; font-weight: bold; color: {DANGER}; }}
"""


def apply_theme(app: QApplication) -> None:
    app.setLayoutDirection(app.layoutDirection())
    family = pick_font_family()
    font = QFont(family, 10)
    font.setStyleHint(QFont.StyleHint.SansSerif)
    app.setFont(font)
    pal = app.palette()
    pal.setColor(QPalette.ColorRole.Window, QColor(BG))
    pal.setColor(QPalette.ColorRole.WindowText, QColor("#1d2a38"))
    app.setPalette(pal)
    app.setStyleSheet(STYLE)
