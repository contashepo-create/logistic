# -*- coding: utf-8 -*-
"""
الأدوات المشتركة للواجهة: الجداول الذكية (CRUD)، أشرطة التصدير والطباعة،
حقول النماذج، نوافذ الإدخال، قوائم الاختيار، وبطاقات المؤشرات (KPI).

كل الأبعاد هنا مضبوطة بحيث لا تُقتطع الأزرار داخل الجداول أو أشرطة الأدوات:
  - عمود (العمليات) بعرض ثابت محسوب من عدد الأزرار.
  - ارتفاع صفوف مريح (44px) يتسع لأزرار 32px كاملة.
  - شريط الفلاتر يلتفّ تلقائياً (FlowLayout) بدل أن يغطي الأزرار.
"""
from __future__ import annotations

import sqlite3

from PySide6.QtCore import QDate, QRect, QSize, Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView, QComboBox, QDateEdit, QDialog, QDialogButtonBox,
    QFormLayout, QFrame, QHBoxLayout, QHeaderView, QLabel, QLineEdit,
    QMessageBox, QPushButton, QTableWidget, QTableWidgetItem,
    QVBoxLayout, QWidget,
)

from ..core import calc
from ..core.rules import RuleError
from ..utils import fmt
from ..utils.fmt import parse_float


def _token(key: str) -> str:
    """لون من رموز الثيم النشطة (يكيّف الأرقام/الألوان مع الفاتح والداكن)."""
    try:
        from .theme import token
        return token(key)
    except Exception:  # noqa: BLE001 — قيمة احتياطية لا تعطّل التشغيل
        return "#4f46e5"


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
# مخطط التفاف أفقي (FlowLayout): يمنع تغطية/قصّ الأزرار عند ضيق المساحة
# ---------------------------------------------------------------------------
from PySide6.QtWidgets import QLayout, QLayoutItem  # noqa: E402


def _app_is_rtl() -> bool:
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance()
    if app is None:
        return True
    return app.layoutDirection() == Qt.LayoutDirection.RightToLeft


class FlowLayout(QLayout):
    """شريط أدوات يلتف لسطر جديد تلقائياً بدل قصّ العناصر أو تغطيتها.

    يُستخدم لأشرطة الفلاتر حتى تظهر كل الحقول والأزرار كاملة مهما كان
    عرض النافذة (المشكلة القديمة: أزرار مغطاة بسبب التقسيم الخاطئ).
    """

    def __init__(self, parent: QWidget | None = None, margin: int = 0,
                 spacing: int = 8):
        super().__init__(parent)
        self._items: list[QLayoutItem] = []
        self.setContentsMargins(margin, margin, margin, margin)
        self.setSpacing(spacing)

    # -- واجهة QLayout -------------------------------------------------------
    def addItem(self, item) -> None:
        self._items.append(item)

    def add(self, w: QWidget) -> None:
        self.addWidget(w)

    def count(self) -> int:
        return len(self._items)

    def itemAt(self, i: int):
        return self._items[i] if 0 <= i < len(self._items) else None

    def takeAt(self, i: int):
        return self._items.pop(i) if 0 <= i < len(self._items) else None

    def expandingDirections(self):
        return Qt.Orientations(Qt.Orientation(0))

    def hasHeightForWidth(self) -> bool:
        return True

    def heightForWidth(self, w: int) -> int:
        return self._do_layout(QRect(0, 0, w, 0), test_only=True)

    def setGeometry(self, rect) -> None:
        super().setGeometry(rect)
        self._do_layout(rect, test_only=False)

    def sizeHint(self) -> QSize:
        return self.minimumSize()

    def minimumSize(self) -> QSize:
        size = QSize()
        for item in self._items:
            size = size.expandedTo(item.minimumSize())
        m = self.contentsMargins()
        size += QSize(m.left() + m.right(), m.top() + m.bottom())
        return size

    # -- التوزيع (يدعم RTL: الرصف من اليمين إلى اليسار) ----------------------
    def _do_layout(self, rect: QRect, test_only: bool) -> int:
        m = self.contentsMargins()
        rtl = _app_is_rtl()
        left, top, right, bottom = m.left(), m.top(), m.right(), m.bottom()
        x_start = rect.right() - right if rtl else rect.left() + left
        x_limit = rect.left() + left if rtl else rect.right() - right
        x, y, line_h = x_start, rect.top() + top, 0
        spacing = self.spacing()
        for item in self._items:
            hint = item.sizeHint()
            item_x = (x - hint.width()) if rtl else x
            next_x = (x - hint.width() - spacing) if rtl else (x + hint.width() + spacing)
            wrapped = False
            if rtl and next_x < x_limit and x < x_start:
                wrapped = True
            if not rtl and next_x - spacing > x_limit + 1 and x > x_start:
                wrapped = True
            if wrapped:
                x = x_start
                y += line_h + spacing
                line_h = 0
                item_x = x_start
                next_x = (x - hint.width() - spacing) if rtl else (x + hint.width() + spacing)
                item_x = (x_start - hint.width()) if rtl else x_start
            if not test_only:
                item.setGeometry(QRect(item_x, y, hint.width(), hint.height()))
            x = next_x
            line_h = max(line_h, hint.height())
        return y + line_h - rect.top() + bottom


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
        self.setMinimumWidth(118)
        self.setFixedHeight(34)

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
        self.setFixedHeight(34)
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
        self.setMinimumWidth(150)
        self.setFixedHeight(34)

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
        self.setMinimumWidth(170)
        self.setFixedHeight(34)

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
# عرض الزر الأيقوني داخل الجداول (بكسل)
ROW_BTN_W, ROW_BTN_H = 34, 30
# هوامش خلية العمليات + التباعد بين الأزرار
ROW_CELL_PAD, ROW_BTN_GAP = 14, 6


def row_actions_width(n_buttons: int) -> int:
    """عرض عمود (العمليات) المحسوب بحيث تظهر كل الأزرار كاملة بلا قصّ."""
    return ROW_CELL_PAD + n_buttons * ROW_BTN_W + max(0, n_buttons - 1) * ROW_BTN_GAP


def _row_button(text: str, tooltip: str, obj: str, callback) -> QPushButton:
    b = QPushButton(text)
    b.setObjectName(obj)
    b.setToolTip(tooltip)
    b.setFixedSize(ROW_BTN_W, ROW_BTN_H)
    b.setCursor(Qt.CursorShape.PointingHandCursor)
    b.clicked.connect(callback)
    return b


def install_row_actions(table: QTableWidget, column: int, n_buttons: int,
                        scroll: bool = False) -> None:
    """تثبيت عمود العمليات بعرض محسوب + ارتفاع صفوف يتسع للأزرار.

    هذه هي المعالجة الجذرية لمشكلة (الأزرار لا تظهر بشكل كامل) — كان العمود
    يتمدد عشوائياً وتُقتطع الأزرار، الآن لكل جدول عرض ثابت مضبوط.
    """
    header = table.horizontalHeader()
    if column < table.columnCount():
        header.setSectionResizeMode(column, QHeaderView.ResizeMode.Fixed)
        table.setColumnWidth(column, row_actions_width(n_buttons))
    table.verticalHeader().setDefaultSectionSize(44)
    table.setTextElideMode(Qt.TextElideMode.ElideMiddle)


def make_actions_widget(buttons: list[QPushButton]) -> QWidget:
    """حاوية أزرار العمليات: موسّطة وغير قابلة للقصّ داخل خلية الجدول."""
    w = QWidget()
    lay = QHBoxLayout(w)
    lay.setContentsMargins(0, 2, 0, 2)
    lay.setSpacing(ROW_BTN_GAP)
    lay.addStretch(1)
    for b in buttons:
        lay.addWidget(b)
    lay.addStretch(1)
    return w


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
        header.setSectionsMovable(False)
        header.setDefaultAlignment(Qt.AlignmentFlag.AlignCenter)
        header.setStretchLastSection(False)
        n_data = len(self._headers)
        for c in range(n_data):
            header.setSectionResizeMode(c, QHeaderView.ResizeMode.ResizeToContents)
        # آخر عمود بيانات يتمدد ليملأ العرض المتاح (شكل متوازن)
        if n_data:
            header.setSectionResizeMode(n_data - 1, QHeaderView.ResizeMode.Stretch)
        # عمود العمليات: عرض ثابت محسوب — الأزرار كاملة دائماً
        if self._actions or self._extra:
            n_buttons = len(self._actions) + len(self._extra)
            install_row_actions(self, n_data, n_buttons)
        self.doubleClicked.connect(self._on_double)

    # -- تعبئة البيانات ------------------------------------------------------
    def set_rows(self, ids: list, rows: list[list]) -> None:
        self._ids = list(ids)
        self._rows = [list(r) for r in rows]
        self.setRowCount(len(rows))
        for r, row in enumerate(rows):
            self.setRowHeight(r, 44)
            for c, val in enumerate(row):
                item = QTableWidgetItem(str(val))
                item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                self.setItem(r, c, item)
            if self._actions or self._extra:
                self.setCellWidget(r, len(self._headers), self._actions_widget(ids[r]))
        if self._ids:
            self.selectRow(0)

    def _actions_widget(self, rid) -> QWidget:
        buttons: list[QPushButton] = []
        if "view" in self._actions:
            buttons.append(_row_button(
                "👁", "عرض", "rowBtn",
                lambda _=False, x=rid: self.viewRequested.emit(x)))
        if "edit" in self._actions:
            buttons.append(_row_button(
                "✏", "تعديل", "rowBtnEdit",
                lambda _=False, x=rid: self.editRequested.emit(x)))
        for key, text, tip in self._extra:
            variant = "rowBtnPrint" if "🖨" in text else "rowBtnExtra"
            buttons.append(_row_button(
                text, tip, variant,
                lambda _=False, x=rid, k=key: self.extraRequested.emit(x, k)))
        if "delete" in self._actions:
            buttons.append(_row_button(
                "🗑", "حذف", "rowBtnDanger",
                lambda _=False, x=rid: self.deleteRequested.emit(x)))
        return make_actions_widget(buttons)

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
        self.setWordWrap(False)
        header = self.horizontalHeader()
        header.setSectionsMovable(False)
        header.setDefaultAlignment(Qt.AlignmentFlag.AlignCenter)
        header.setStretchLastSection(True)
        for c in range(len(headers)):
            header.setSectionResizeMode(c, QHeaderView.ResizeMode.ResizeToContents)
        self.verticalHeader().setDefaultSectionSize(42)

    def set_rows(self, rows: list[list], bold_last: bool = False) -> None:
        self.setRowCount(len(rows))
        for r, row in enumerate(rows):
            self.setRowHeight(r, 42)
            is_last_bold = bold_last and r == len(rows) - 1
            for c, val in enumerate(row):
                item = QTableWidgetItem(str(val))
                item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                f = item.font()
                f.setBold(is_last_bold)
                item.setFont(f)
                self.setItem(r, c, item)
        if bold_last and rows:
            # صف الإجمالي يتلوّن حسب الوضع البصري (فاتح/داكن) بدل الأبيض الثابت.
            from PySide6.QtGui import QColor
            from .theme import token as _t
            bg = QColor(_t("CARD"))
            for c in range(self.columnCount()):
                it = self.item(self.rowCount() - 1, c)
                if it is not None:
                    it.setBackground(bg)

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
    """أزرار (Excel / PDF / طباعة) الموحدة لكل الشاشات — داخل مجموعة أنيقة."""
    excelClicked = Signal()
    pdfClicked = Signal()
    printClicked = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        group = QFrame()
        group.setObjectName("exportGroup")
        lay = QHBoxLayout(group)
        lay.setContentsMargins(4, 3, 4, 3)
        lay.setSpacing(2)
        b = QPushButton("📊 Excel")
        b.setObjectName("btnExcel")
        b.setToolTip("تصدير إلى ملف Excel")
        b.setCursor(Qt.CursorShape.PointingHandCursor)
        b.clicked.connect(self.excelClicked.emit)
        lay.addWidget(b)
        b = QPushButton("📄 PDF")
        b.setObjectName("btnPdf")
        b.setToolTip("تصدير إلى PDF")
        b.setCursor(Qt.CursorShape.PointingHandCursor)
        b.clicked.connect(self.pdfClicked.emit)
        lay.addWidget(b)
        b = QPushButton("🖨️ طباعة")
        b.setObjectName("btnPrint")
        b.setToolTip("طباعة بتنسيق احترافي")
        b.setCursor(Qt.CursorShape.PointingHandCursor)
        b.clicked.connect(self.printClicked.emit)
        lay.addWidget(b)

        outer = QHBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(group)


class PageFrame(QWidget):
    """إطار صفحة موحد: ترويسة بعنوان بارز + شريط أدوات (إضافة/بحث/تصدير)."""

    def __init__(self, title: str, subtitle: str = "", add_text: str = "➕ إضافة",
                 show_add: bool = True, show_search: bool = True, parent=None):
        super().__init__(parent)
        self.setObjectName("page")
        root = QVBoxLayout(self)
        root.setContentsMargins(22, 18, 22, 18)
        root.setSpacing(12)

        # الترويسة: شريط لوني + عنوان ووصف
        head = QHBoxLayout()
        head.setSpacing(12)
        accent = QFrame()
        accent.setObjectName("titleAccent")
        accent.setFixedSize(6, 46)
        head.addWidget(accent, 0, Qt.AlignmentFlag.AlignVCenter)
        titles = QVBoxLayout()
        titles.setSpacing(2)
        t = QLabel(title)
        t.setObjectName("pageTitle")
        titles.addWidget(t)
        self.title_label = t
        s = QLabel(subtitle)
        s.setObjectName("pageSub")
        if subtitle:
            titles.addWidget(s)
        else:
            s.hide()
        self.sub_label = s
        head.addLayout(titles, 1)
        root.addLayout(head)

        # شريط الأدوات: إضافة + بحث ... تصدير
        bar = QHBoxLayout()
        bar.setSpacing(10)
        self.add_btn: QPushButton | None = None
        if show_add:
            self.add_btn = QPushButton(add_text)
            self.add_btn.setObjectName("primary")
            self.add_btn.setCursor(Qt.CursorShape.PointingHandCursor)
            self.add_btn.setFixedHeight(40)
            bar.addWidget(self.add_btn)
        self.search_edit: QLineEdit | None = None
        if show_search:
            self.search_edit = QLineEdit()
            self.search_edit.setPlaceholderText("🔍  بحث سريع في الجدول...")
            self.search_edit.setClearButtonEnabled(True)
            self.search_edit.setFixedHeight(40)
            self.search_edit.setMinimumWidth(170)
            self.search_edit.setMaximumWidth(300)
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
# شريط الإجماليات — بطاقات مؤشرات (KPI) حديثة
# ---------------------------------------------------------------------------
# ألوان الأرقام تُقرأ من رموز الثيم (theme) لا كقيم ثابتة، فتتكيّف تلقائياً
# مع الوضعين الفاتح/الداكن (مفاتيح من لوحة الألوان النشطة).
KPI_ACCENT_KEYS = ["PRIMARY", "SUCCESS", "VIOLET", "WARNING", "DANGER"]


def add_shadow(widget, blur: int = 16, alpha: int = 30, dy: int = 2) -> None:
    """ظل ناعم حول البطاقات (QSS لا يدعم box-shadow في كيوت)."""
    from PySide6.QtGui import QColor
    from PySide6.QtWidgets import QGraphicsDropShadowEffect

    eff = QGraphicsDropShadowEffect(widget)
    eff.setBlurRadius(blur)
    eff.setOffset(0, dy)
    eff.setColor(QColor(17, 24, 39, alpha))
    widget.setGraphicsEffect(eff)


class TotalsBar(QWidget):
    """بطاقات إجماليات (KPI): عنوان صغير خافت + قيمة كبيرة بارزة + ظل ناعم."""

    def __init__(self, labels: list[str], parent=None):
        super().__init__(parent)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 2, 0, 2)
        lay.setSpacing(12)
        self._values: dict[str, QLabel] = {}
        self._accents: dict[str, str] = {}
        for i, text in enumerate(labels):
            card = QFrame()
            card.setObjectName("kpiCard")
            add_shadow(card, blur=14, alpha=26, dy=2)
            box = QVBoxLayout(card)
            box.setContentsMargins(14, 10, 14, 10)
            box.setSpacing(4)
            caption = QLabel(text)
            caption.setObjectName("kpiCaption")
            caption.setAlignment(Qt.AlignmentFlag.AlignCenter)
            caption.setWordWrap(True)
            value = QLabel("0.00")
            value.setObjectName("kpiValue")
            value.setAlignment(Qt.AlignmentFlag.AlignCenter)
            key = KPI_ACCENT_KEYS[i % len(KPI_ACCENT_KEYS)]
            value.setStyleSheet(f"color:{_token(key)}; "
                                "font-size:15pt; font-weight:bold;")
            box.addWidget(caption)
            box.addWidget(value)
            lay.addWidget(card, 1)
            self._values[text] = value
            self._accents[text] = key

    def set_value(self, label: str, value, money: bool = True) -> None:
        v = self._values.get(label)
        if v is None:
            return
        text = fmt.money(value) if money else str(value)
        v.setText(text)
        key = self._accents.get(label, "PRIMARY")
        try:
            negative = float(value or 0) < 0
        except (TypeError, ValueError):
            negative = False
        if negative:
            key = "DANGER"
        v.setStyleSheet(f"color:{_token(key)}; "
                        "font-size:15pt; font-weight:bold;")


# ---------------------------------------------------------------------------
# نافذة نموذج موحدة (إضافة/تعديل/عرض)
# ---------------------------------------------------------------------------
class FormDialog(QDialog):
    """نافذة إدخال: ترويسة أنيقة + نموذج يمين + أزرار حفظ/إلغاء."""

    def __init__(self, parent=None, title: str = "", read_only: bool = False,
                 width: int = 540):
        super().__init__(parent)
        self.read_only = read_only
        self.setWindowTitle(title)
        self.setMinimumWidth(width)
        self.setSizeGripEnabled(True)
        root = QVBoxLayout(self)
        root.setContentsMargins(20, 16, 20, 16)
        root.setSpacing(12)

        head = QHBoxLayout()
        head.setSpacing(10)
        accent = QFrame()
        accent.setObjectName("titleAccent")
        accent.setFixedSize(5, 34)
        head.addWidget(accent, 0, Qt.AlignmentFlag.AlignVCenter)
        t = QLabel(title)
        t.setObjectName("dialogTitle")
        head.addWidget(t, 1)
        root.addLayout(head)

        self.form = QFormLayout()
        self.form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        self.form.setFieldGrowthPolicy(
            QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        self.form.setHorizontalSpacing(14)
        self.form.setVerticalSpacing(10)
        root.addLayout(self.form, 1)

        self.buttons = QDialogButtonBox()
        if read_only:
            self.buttons.addButton("إغلاق", QDialogButtonBox.ButtonRole.RejectRole)
        else:
            save = self.buttons.addButton("💾 حفظ",
                                          QDialogButtonBox.ButtonRole.AcceptRole)
            save.setObjectName("primary")
            save.setMinimumHeight(38)
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
