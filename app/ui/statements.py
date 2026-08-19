# -*- coding: utf-8 -*-
"""كشوف الحساب المنفصلة: كشف عميل، كشف خزينة، كشف بنك — بفلاتر تاريخ وتصدير وطباعة."""
from __future__ import annotations

from datetime import date

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDateEdit, QDialog, QHBoxLayout, QLabel, QPushButton, QVBoxLayout,
)

from ..core import calc, db, repo
from ..utils import exporter, fmt
from .widgets import PlainTable, VDateEdit


class StatementDialog(QDialog):
    """شاشة كشف حساب عامة (من تاريخ / إلى تاريخ) مع تصدير وطباعة."""

    def __init__(self, title: str, owner_label: str, parent=None):
        super().__init__(parent)
        self.title = title
        self.owner_label = owner_label
        self.setWindowTitle(title)
        self.resize(960, 600)
        root = QVBoxLayout(self)
        root.setContentsMargins(14, 12, 14, 12)
        root.setSpacing(8)

        head = QHBoxLayout()
        name_lbl = QLabel(owner_label)
        name_lbl.setObjectName("sectionLabel")
        head.addWidget(name_lbl)
        head.addStretch(1)
        head.addWidget(QLabel("من تاريخ"))
        self.from_edit = VDateEdit()
        self.from_edit.set_iso(f"{date.today().year}-01-01")
        head.addWidget(self.from_edit)
        head.addWidget(QLabel("إلى تاريخ"))
        self.to_edit = VDateEdit()
        head.addWidget(self.to_edit)
        refresh_btn = QPushButton("🔄 عرض")
        refresh_btn.setObjectName("primary")
        refresh_btn.clicked.connect(self.load)
        head.addWidget(refresh_btn)
        root.addLayout(head)

        self.table = PlainTable(self.headers())
        root.addWidget(self.table, 1)

        self.summary = QLabel("")
        self.summary.setObjectName("sectionLabel")
        root.addWidget(self.summary)

        from .widgets import ExportBar
        bar = ExportBar()
        bar.excelClicked.connect(lambda: self.export("excel"))
        bar.pdfClicked.connect(lambda: self.export("pdf"))
        bar.printClicked.connect(lambda: self.export("print"))
        root.addWidget(bar)

        self.load()

    # تُعرَّف في الفئات الفرعية -------------------------------------------
    def headers(self) -> list[str]:
        raise NotImplementedError

    def load(self) -> None:
        raise NotImplementedError

    def export(self, mode: str) -> None:
        conn = db.get_conn()
        headers, rows = self.table.export_data()
        subtitle = f"{self.owner_label} | الفترة: من {self.from_edit.iso()} إلى {self.to_edit.iso()}"
        if mode == "excel":
            exporter.export_excel(self, conn, self.title, headers, rows,
                                  default_name=f"{self.title}.xlsx")
        else:
            html = exporter.build_report_html(
                conn, title=self.title, subtitle=subtitle, headers=headers, rows=rows,
                summary_lines=self._summary_lines(), center_from=1)
            if mode == "pdf":
                exporter.export_pdf(self, html, f"{self.title}.pdf")
            else:
                exporter.print_html(self, html)

    def _summary_lines(self) -> list[tuple[str, str]]:
        return []


class CustomerStatementDialog(StatementDialog):
    """كشف حساب عميل: الرصيد الافتتاحي + الفواتير − سندات القبض = الرصيد الحالي."""

    def __init__(self, customer_id: int, parent=None):
        self.customer_id = customer_id
        conn = db.get_conn()
        c = repo.get_customer(conn, customer_id)
        name = f"{c['code']} - {c['name']}" if c else "—"
        super().__init__(f"كشف حساب عميل: {name}", name, parent)

    def headers(self) -> list[str]:
        return ["التاريخ", "المستند", "البيان", "مدين (عليه)", "دائن (له)", "الرصيد"]

    def load(self) -> None:
        conn = db.get_conn()
        st = calc.customer_statement(conn, self.customer_id,
                                     self.from_edit.iso(), self.to_edit.iso())
        rows = [[r["date"], r["doc"], r["desc"], fmt.money(r["debit"]),
                 fmt.money(r["credit"]), fmt.money(r["balance"])] for r in st["rows"]]
        rows.append(["", "الإجمالي / الرصيد النهائي", "",
                     fmt.money(sum(r["debit"] for r in st["rows"])),
                     fmt.money(sum(r["credit"] for r in st["rows"])),
                     fmt.money(st["closing"])])
        self.table.set_rows(rows, bold_last=True)
        self._st = st
        self.summary.setText(
            f"الرصيد الافتتاحي: {fmt.money(st['opening'])}    "
            f"الرصيد الختامي (الحالي): {fmt.money(st['closing'])}")

    def _summary_lines(self) -> list[tuple[str, str]]:
        st = getattr(self, "_st", {})
        return [("العميل", self.owner_label),
                ("الرصيد الافتتاحي", fmt.money(st.get("opening", 0))),
                ("إجمالي الفواتير", fmt.money(sum(r["debit"] for r in st.get("rows", [])))),
                ("إجمالي التحصيل", fmt.money(sum(r["credit"] for r in st.get("rows", [])))),
                ("الرصيد الحالي", fmt.money(st.get("closing", 0)))]


class AccountStatementDialog(StatementDialog):
    """كشف حساب خزينة/بنك: كل حركات القبض والدفع والرواتب."""

    def __init__(self, kind: str, account_id: int, parent=None):
        self.kind = kind
        self.account_id = account_id
        conn = db.get_conn()
        a = repo.get_account(conn, kind, account_id)
        kind_label = "خزينة" if kind == "cashbox" else "بنك"
        name = f"{kind_label}: {a['code']} - {a['name']}" if a else "—"
        super().__init__(f"كشف حساب {kind_label}", name, parent)

    def headers(self) -> list[str]:
        return ["التاريخ", "المستند", "البيان", "وارد", "منصرف", "الرصيد"]

    def load(self) -> None:
        conn = db.get_conn()
        st = calc.account_statement(conn, self.kind, self.account_id,
                                    self.from_edit.iso(), self.to_edit.iso())
        rows = [[r["date"], r["doc"], r["desc"], fmt.money(r["in"]),
                 fmt.money(r["out"]), fmt.money(r["balance"])] for r in st["rows"]]
        rows.append(["", "الإجمالي / الرصيد النهائي", "",
                     fmt.money(sum(r["in"] for r in st["rows"])),
                     fmt.money(sum(r["out"] for r in st["rows"])),
                     fmt.money(st["closing"])])
        self.table.set_rows(rows, bold_last=True)
        self._st = st
        self.summary.setText(
            f"الرصيد الافتتاحي: {fmt.money(st['opening'])}    "
            f"الرصيد الختامي (الحالي): {fmt.money(st['closing'])}")

    def _summary_lines(self) -> list[tuple[str, str]]:
        st = getattr(self, "_st", {})
        return [("الحساب", self.owner_label),
                ("الرصيد الافتتاحي", fmt.money(st.get("opening", 0))),
                ("إجمالي الوارد", fmt.money(sum(r["in"] for r in st.get("rows", [])))),
                ("إجمالي المنصرف", fmt.money(sum(r["out"] for r in st.get("rows", [])))),
                ("الرصيد الحالي", fmt.money(st.get("closing", 0)))]
