# -*- coding: utf-8 -*-
"""الصفحة الأساسية المشتركة: جدول CRUD + شريط أدوات (إضافة/بحث/تصدير/طباعة)."""
from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QVBoxLayout, QWidget

from ..core import db
from ..utils import exporter, fmt
from ..utils.fmt import normalize_digits
from .widgets import DataTable, PageFrame


class CrudPage(QWidget):
    """صفحة قائمة عامة: تُعرَّف fetch + أحداث الأزرار في الفئات الفرعية.

    تلتزم بالقواعد العامة: أزرار (عرض/تعديل/حذف) لكل حركة، تصدير Excel/PDF،
    وطباعة احترافية، وإشارة changed لإعادة تحميل الأرصدة بعد أي تعديل.
    """
    TITLE = ""
    SUBTITLE = ""
    ADD_TEXT = "➕ إضافة"
    changed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.frame = PageFrame(self.TITLE, self.SUBTITLE, self.ADD_TEXT)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(12, 12, 12, 12)
        outer.addWidget(self.frame)
        if self.frame.add_btn:
            self.frame.add_btn.clicked.connect(self.on_add)
        if self.frame.search_edit:
            self.frame.search_edit.textChanged.connect(self.refresh)
        self.frame.export_bar.excelClicked.connect(lambda: self.do_export("excel"))
        self.frame.export_bar.pdfClicked.connect(lambda: self.do_export("pdf"))
        self.frame.export_bar.printClicked.connect(lambda: self.do_export("print"))
        self.table: DataTable | None = None

    # ------------------------------------------------------------------
    def set_table(self, table: DataTable) -> None:
        self.table = table
        self.frame.add_widget(table)
        table.viewRequested.connect(self._safe(self.on_view))
        table.editRequested.connect(self._safe(self.on_edit))
        table.deleteRequested.connect(self._safe(self.on_delete))
        table.extraRequested.connect(
            lambda rid, key: self._safe2(self.on_extra)(rid, key))

    def _safe(self, fn):
        def wrapper(rid):
            fn(rid)
            self.changed.emit()
        return wrapper

    def _safe2(self, fn):
        def wrapper(rid, key):
            fn(rid, key)   # الأزرار الإضافية (كشوف/طباعة) لا تغير البيانات
        return wrapper

    # ------------------------------------------------------------------
    # افتراضيات تُعاد تعريفها
    def fetch(self) -> tuple[list, list[list]]:
        return [], []

    def on_add(self) -> None:  # pragma: no cover
        pass

    def on_view(self, rid) -> None:  # pragma: no cover
        pass

    def on_edit(self, rid) -> None:  # pragma: no cover
        pass

    def on_delete(self, rid) -> None:  # pragma: no cover
        pass

    def on_extra(self, rid, key: str) -> None:  # pragma: no cover
        pass

    def matches(self, text: str, row: list) -> bool:
        joined = normalize_digits(" ".join(str(c) for c in row))
        return normalize_digits(text) in joined

    def export_subtitle(self) -> str:
        return ""

    def export_summary(self) -> list[tuple[str, str]] | None:
        return None

    # ------------------------------------------------------------------
    def refresh(self, *_a) -> None:
        if self.table is None:
            return
        try:
            ids, rows = self.fetch()
        except Exception:  # noqa: BLE001
            ids, rows = [], []
        text = (self.frame.search_edit.text().strip()
                if self.frame.search_edit else "")
        if text:
            pairs = [(i, r) for i, r in zip(ids, rows) if self.matches(text, r)]
            ids = [p[0] for p in pairs]
            rows = [p[1] for p in pairs]
        self.table.set_rows(ids, rows)

    # ------------------------------------------------------------------
    def do_export(self, mode: str) -> None:
        if self.table is None:
            return
        conn = db.get_conn()
        headers, rows = self.table.export_data()
        title = self.TITLE
        subtitle = self.export_subtitle()
        if mode == "excel":
            exporter.export_excel(self, conn, title, headers, rows,
                                  default_name=f"{title}.xlsx",
                                  summary_lines=self.export_summary())
        else:
            html = exporter.build_report_html(
                conn, title=title, subtitle=subtitle, headers=headers, rows=rows,
                summary_lines=self.export_summary(), center_from=1)
            if mode == "pdf":
                exporter.export_pdf(self, html, f"{title}.pdf")
            else:
                exporter.print_html(self, html)
