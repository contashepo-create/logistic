# -*- coding: utf-8 -*-
"""
الأدوات المشتركة للواجهة: الجداول الذكية (CRUD)، أشرطة التصدير والطباعة،
حقول النماذج، نوافذ الإدخال، وقوائم الاختيار.
"""
from __future__ import annotations

import sqlite3

from PySide6.QtCore import QDate, Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView, QComboBox, QDateEdit, QDialog, QDialogButtonBox, QFormLayout,
    QHBoxLayout, QHeaderView, QLabel, QLineEdit, QListWidget, QMessageBox,
    QPushButton, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from ..core import calc, db
from ..core.rules import RuleError
from ..utils import exporter, fmt
from ..utils.fmt import normalize_digits, parse_float


# ---------------------------------------------------------------------------
# رسائل
# ---------------------------------------------------------------------------
def warn(parent, text: str, title: str = "تنبيه") -> None:
    QMessageBox.warning(parent, title, str(text))


def info(parent, text: str, title: str = "تم") -> None:
    QMessageBox.information(parent, title, str(text))


def confirm(parent, text: str, title: str = "تأكيد") -> bool:
    return QMessageBox.question(
        parent, title, text,
        QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        QMessageBox.StandardButton.No,
    ) == QMessageBox.StandardButton.Yes


def error_msg(parent, text: str, title: str = "خطأ") -> None:
    QMessageBox.critical(parent, title, str(text))


# ---------------------------------------------------------------------------
# حقول مخصصة
# ---------------------------------------------------------------------------
class VDateEdit(QDateEdit):
    """حقل تاريخ مع تقويم منبثق بصيغة سنة-شهر-يوم."""

    def __init__(self, date: QDate | None = None, parent=None):
        super().__init__(parent)
        self.setCalendarPopup(True)
        self.setDisplayFormat("yyyy-MM-dd")
        self.setDate(date or QDate.currentDate())

    def iso(self) -> str:
        return self.date().toString("yyyy-MM-dd")

    def set_iso(self, s: str) -> None:
        d = QDate.fromString(s, "yyyy-MM-dd")
        if d.isValid():
            self.setDate(d)


class AmountEdit(QLineEdit):
    """حقل مبلغ: يقبل الأرقام العربية وفواصل الآلاف."""

    def __init__(self, value: float = 0.0, parent=None):
        super().__init__(parent)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.set_value(value)
        self.setPlaceholderText("0.00")

    def value(self) -> float:
        try:
            return round(parse_float(self.text(), 0.0), 2)
        except ValueError:
            return 0.0

    def set_value(self, v: float) -> None:
        self.setText(f"{float(v or 0):.2f}")


class DictCombo(QComboBox):
    """قائمة معينة تعرض (كود - اسم) وتعيد المعرّف."""

    def __init__(self, placeholder: str = "— اختر —", parent=None):
        super().__init__(parent)
        self._ids: list = []
        self._placeholder = placeholder

    def load(self, rows, mapper=None) -> None:
        """rows: قائمة sqlite3.Row أو dicts تحتوي id + حقل عرض."""
        self.clear()
        self._ids = []
        self.addItem(self._placeholder, None)
        self._ids.append(None)
        for r in rows:
            label = mapper(r) if mapper else f"{r['code']} - {r['name']}"
            self._ids.append(r["id"])
            self.addItem(str(label), r["id"])
        self.setCurrentIndex(0)

    def selected_id(self):
        i = self.currentIndex()
        return self._ids[i] if 0 <= i < len(self._ids) else None

    def select(self, rid) -> None:
        if rid is None:
            self.setCurrentIndex(0)
            return
        if rid in self._ids:
            self.setCurrentIndex(self._ids.index(rid))


class AccountCombo(QComboBox):
    """قائمة موحدة للخزائن والبنوك."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._accounts: list[tuple[str, int, str, str]] = []

    def load(self, conn: sqlite3.Connection) -> None:
        self.clear()
        self._accounts = calc.all_accounts(conn)
        self.addItem("— اختر الخزينة أو البنك —", None)
        for i, (kind, aid, label, _code) in enumerate(self._accounts):
            self.addItem(label, (kind, aid))

    def current_account(self) -> tuple[str | None, int | None]:
        data = self.currentData()
        return data if data else (None, None)

    def select(self, kind: str, aid: int) -> None:
        for i in range(self.count()):
            if self.itemData(i) == (kind, aid):
                self.setCurrentIndex(i)
                return


# ---------------------------------------------------------------------------
# الأزرار الصفية والجدول الذكي
# ---------------------------------------------------------------------------
def _row_button(text: str, tooltip: str, obj: str, callback) -> QPushButton:
    b = QPushButton(text)
    b.setObjectName(obj)
    b.setToolTip(tooltip)
    b.setFixedHeight(26)
    b.setCursor(Qt.CursorShape.PointingHandCursor)
    b.clicked.connect(callback)
    return b


class DataTable(QTableWidget):
    """جدول CRUD: أعمدة بيانات + عمود (العمليات) بأزرار عرض/تعديل/حذف وأزرار إضافية.

    إشارات:
      viewRequested(int) / editRequested(int) / deleteRequested(int)
      extraRequested(int, str)  -> (المعرّف، مفتاح الزر الإضافي)
    """
    viewRequested = Signal(int)
    editRequested = Signal(int)
    deleteRequested = Signal(int)
    extraRequested = Signal(int, str)

    def __init__(self, headers: list[str], actions=("view", "edit", "delete"),
                 extra: list[tuple[str, str, str]] | None = None, parent=None):
        super().__init__(parent)
        self._headers = list(headers)
        self._actions = list(actions)
        self._extra = list(extra or [])  # [(key, نص الزر, tooltip)]
        self._ids: list = []
        self._rows: list[list] = []
        cols = list(headers)
        if self._actions or self._extra:
            cols.append("العمليات")
        self.setColumnCount(len(cols))
        self.setHorizontalHeaderLabels(cols)
        self.verticalHeader().setVisible(False)
        self.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.setAlternatingRowColors(True)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setWordWrap(False)
        header = self.horizontalHeader()
        for c in range(len(cols) - 1):
            header.setSectionResizeMode(c, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(len(cols) - 1, QHeaderView.ResizeMode.Stretch)
        self.doubleClicked.connect(self._on_double)

    # -- تعبئة البيانات ------------------------------------------------------
    def set_rows(self, ids: list, rows: list[list]) -> None:
        self._ids = list(ids)
        self._rows = [list(r) for r in rows]
        self.setRowCount(len(rows))
        for r, row in enumerate(rows):
            for c, val in enumerate(row):
                item = QTableWidgetItem(str(val))
                item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                self.setItem(r, c, item)
            if self._actions or self._extra:
                self.setCellWidget(r, len(self._headers), self._actions_widget(ids[r]))
        if self._ids:
            self.selectRow(0)

    def _actions_widget(self, rid) -> QWidget:
        w = QWidget()
        lay = QHBoxLayout(w)
        lay.setContentsMargins(2, 1, 2, 1)
        lay.setSpacing(3)
        lay.addStretch(1)
        if "view" in self._actions:
            lay.addWidget(_row_button("👁️", "عرض", "rowBtn",
                                      lambda _=False, x=rid: self.viewRequested.emit(x)))
        if "edit" in self._actions:
            lay.addWidget(_row_button("✏️", "تعديل", "rowBtn",
                                      lambda _=False, x=rid: self.editRequested.emit(x)))
        for key, text, tip in self._extra:
            lay.addWidget(_row_button(
                text, tip, "rowBtn",
                lambda _=False, x=rid, k=key: self.extraRequested.emit(x, k)))
        if "delete" in self._actions:
            lay.addWidget(_row_button("🗑️", "حذف", "rowBtnDanger",
                                      lambda _=False, x=rid: self.deleteRequested.emit(x)))
        return w

    def _on_double(self, index) -> None:
        rid = self._ids[index.row()] if index.row() < len(self._ids) else None
        if rid is not None and "view" in self._actions:
            self.viewRequested.emit(rid)

    # -- الوصول للبيانات -----------------------------------------------------
    def current_id(self):
        r = self.currentRow()
        return self._ids[r] if 0 <= r < len(self._ids) else None

    def export_data(self) -> tuple[list[str], list[list]]:
        """(الترويسات، الصفوف) بدون عمود العمليات — للتصدير والطباعة."""
        return list(self._headers), [list(r) for r in self._rows]


class PlainTable(QTableWidget):
    """جدول عرض بسيط (تقارير) قابل للتصدير."""

    def __init__(self, headers: list[str], parent=None):
        super().__init__(0, len(headers), parent)
        self._headers = list(headers)
        self.setHorizontalHeaderLabels(headers)
        self.verticalHeader().setVisible(False)
        self.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.setAlternatingRowColors(True)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        header = self.horizontalHeader()
        for c in range(len(headers)):
            header.setSectionResizeMode(c, QHeaderView.ResizeMode.ResizeToContents)

    def set_rows(self, rows: list[list], bold_last: bool = False) -> None:
        self.setRowCount(len(rows))
        for r, row in enumerate(rows):
            is_last_bold = bold_last and r == len(rows) - 1
            for c, val in enumerate(row):
                item = QTableWidgetItem(str(val))
                item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                f = item.font()
                f.setBold(is_last_bold)
                item.setFont(f)
                self.setItem(r, c, item)

    def export_data(self) -> tuple[list[str], list[list]]:
        rows = []
        for r in range(self.rowCount()):
            rows.append([self.item(r, c).text() if self.item(r, c) else ""
                         for c in range(self.columnCount())])
        return list(self._headers), rows


# ---------------------------------------------------------------------------
# شريط التصدير / الطباعة + إطار الصفحة
# ---------------------------------------------------------------------------
class ExportBar(QWidget):
    """أزرار (Excel / PDF / طباعة) الموحدة لكل الشاشات."""
    excelClicked = Signal()
    pdfClicked = Signal()
    printClicked = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(6)
        b = QPushButton("📊 Excel")
        b.setToolTip("تصدير إلى ملف Excel")
        b.clicked.connect(self.excelClicked.emit)
        lay.addWidget(b)
        b = QPushButton("📄 PDF")
        b.setToolTip("تصدير إلى ملف PDF")
        b.clicked.connect(self.pdfClicked.emit)
        lay.addWidget(b)
        b = QPushButton("🖨️ طباعة")
        b.setToolTip("طباعة بتنسيق احترافي")
        b.clicked.connect(self.printClicked.emit)
        lay.addWidget(b)


class PageFrame(QWidget):
    """إطار صفحة موحد: عنوان + وصف + شريط أدوات (إضافة/بحث/تصدير)."""

    def __init__(self, title: str, subtitle: str = "", add_text: str = "➕ إضافة",
                 show_add: bool = True, show_search: bool = True, parent=None):
        super().__init__(parent)
        self.setObjectName("page")
        root = QVBoxLayout(self)
        root.setContentsMargins(18, 14, 18, 14)
        root.setSpacing(10)

        head = QVBoxLayout()
        head.setSpacing(2)
        t = QLabel(title)
        t.setObjectName("pageTitle")
        head.addWidget(t)
        self.title_label = t
        s = QLabel(subtitle)
        s.setObjectName("pageSub")
        if subtitle:
            head.addWidget(s)
        else:
            s.hide()
        self.sub_label = s
        root.addLayout(head)

        bar = QHBoxLayout()
        bar.setSpacing(8)
        self.add_btn: QPushButton | None = None
        if show_add:
            self.add_btn = QPushButton(add_text)
            self.add_btn.setObjectName("primary")
            self.add_btn.setCursor(Qt.CursorShape.PointingHandCursor)
            bar.addWidget(self.add_btn)
        self.search_edit: QLineEdit | None = None
        if show_search:
            self.search_edit = QLineEdit()
            self.search_edit.setPlaceholderText("🔍 بحث سريع...")
            self.search_edit.setClearButtonEnabled(True)
            self.search_edit.setMaximumWidth(260)
            bar.addWidget(self.search_edit)
        bar.addStretch(1)
        self.export_bar = ExportBar()
        bar.addWidget(self.export_bar)
        root.addLayout(bar)

        self.body = QVBoxLayout()
        root.addLayout(self.body, 1)

    def add_widget(self, w: QWidget, stretch: int = 1) -> None:
        self.body.addWidget(w, stretch)

    def add_layout(self, lay) -> None:
        self.body.addLayout(lay)

    def add_layout_at(self, index: int, lay) -> None:
        """إدراج عنصر (ودج أو مخطط) في موضع محدد من جسم الصفحة."""
        from PySide6.QtWidgets import QLayout
        if isinstance(lay, QLayout):
            self.body.insertLayout(index, lay)
        else:
            self.body.insertWidget(index, lay)


# ---------------------------------------------------------------------------
# شريط الإجماليات (بطاقات)
# ---------------------------------------------------------------------------
class TotalsBar(QWidget):
    """بطاقات إجماليات أسفل الشاشة."""

    def __init__(self, labels: list[str], parent=None):
        super().__init__(parent)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(10)
        self._values: dict[str, QLabel] = {}
        for text in labels:
            box = QVBoxLayout()
            box.setSpacing(0)
            card = QLabel(text)
            card.setObjectName("totalCard")
            card.setAlignment(Qt.AlignmentFlag.AlignCenter)
            value = QLabel("0.00")
            value.setObjectName("totalValue")
            value.setAlignment(Qt.AlignmentFlag.AlignCenter)
            value.setStyleSheet("background:#f0f5fa; border:1px solid #d7dde5;"
                                "border-radius:8px; padding:2px 14px 8px 14px;")
            box.addWidget(card, 0, Qt.AlignmentFlag.AlignTop)
            box.addWidget(value, 0, Qt.AlignmentFlag.AlignTop)
            wrap = QWidget()
            wrap.setLayout(box)
            lay.addWidget(wrap, 1)
            self._values[text] = value

    def set_value(self, label: str, value, money: bool = True) -> None:
        v = self._values.get(label)
        if v is None:
            return
        text = fmt.money(value) if money else str(value)
        v.setText(text)
        try:
            v.setObjectName("totalValueNeg" if float(value or 0) < 0 else "totalValue")
        except (TypeError, ValueError):
            v.setObjectName("totalValue")
        v.setStyleSheet(
            ("background:#fdeef0; border:1px solid #e3b6bb;" if v.objectName() == "totalValueNeg"
             else "background:#f0f5fa; border:1px solid #d7dde5;") +
            "border-radius:8px; padding:2px 14px 8px 14px;" +
            ("color:#b02a37;" if v.objectName() == "totalValueNeg"
             else "color:#1f4e79;") + "font-size:13pt; font-weight:bold;")


# ---------------------------------------------------------------------------
# نافذة نموذج موحدة (إضافة/تعديل/عرض)
# ---------------------------------------------------------------------------
class FormDialog(QDialog):
    """نافذة إدخال: نموذج يمين + أزرار حفظ/إلغاء. تدعم وضع القراءة فقط."""

    def __init__(self, parent=None, title: str = "", read_only: bool = False,
                 width: int = 520):
        super().__init__(parent)
        self.read_only = read_only
        self.setWindowTitle(title)
        self.setMinimumWidth(width)
        self.setSizeGripEnabled(True)
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 14, 16, 12)
        root.setSpacing(10)

        self.form = QFormLayout()
        self.form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        self.form.setFieldGrowthPolicy(
            QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        root.addLayout(self.form, 1)

        self.buttons = QDialogButtonBox()
        if read_only:
            self.buttons.addButton("إغلاق", QDialogButtonBox.ButtonRole.RejectRole)
        else:
            save = self.buttons.addButton("💾 حفظ", QDialogButtonBox.ButtonRole.AcceptRole)
            save.setObjectName("primary")
            self.buttons.addButton("إلغاء", QDialogButtonBox.ButtonRole.RejectRole)
        self.buttons.accepted.connect(self._try_save)
        self.buttons.rejected.connect(self.reject)
        root.addWidget(self.buttons)

    def add_row(self, label: str, widget: QWidget) -> QWidget:
        self.form.addRow(label, widget)
        return widget

    def _try_save(self) -> None:
        if self.read_only:
            self.accept()
            return
        try:
            self.save()
        except (RuleError, ValueError) as e:
            warn(self, str(e))
            return
        except Exception as e:  # noqa: BLE001
            error_msg(self, str(e))
            return
        self.accept()

    # تُعاد تعريفها في النوافذ الفرعية
    def save(self) -> None:  # pragma: no cover - abstract
        raise NotImplementedError

    def lock_fields(self) -> None:
        """تعطيل كل الحقول (وضع العرض)."""
        for w in self.findChildren(QLineEdit):
            w.setReadOnly(True)
        for w in self.findChildren(QComboBox):
            w.setEnabled(False)
        for w in self.findChildren(QDateEdit):
            w.setEnabled(False)
        for w in self.findChildren(QPushButton):
            w.setEnabled(False)


# ---------------------------------------------------------------------------
# أدوات تصدير مختصرة
# ---------------------------------------------------------------------------
def do_export_excel(widget: QWidget, conn: sqlite3.Connection, title: str,
                    headers: list[str], rows: list[list],
                    summary_lines: list[tuple[str, str]] | None = None) -> None:
    exporter.export_excel(widget, conn, title, headers, rows,
                          default_name=f"{title}.xlsx", summary_lines=summary_lines)


def build_export_html(conn: sqlite3.Connection, title: str, subtitle: str,
                      headers: list[str], rows: list[list],
                      summary_lines: list[tuple[str, str]] | None = None,
                      center_from: int = 1) -> str:
    return exporter.build_report_html(
        conn, title=title, subtitle=subtitle, headers=headers, rows=rows,
        summary_lines=summary_lines, center_from=center_from)
