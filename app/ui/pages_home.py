# -*- coding: utf-8 -*-
"""لوحة المعلومات (الرئيسية): نظرة سريعة على نشاط الشركة من البيانات الحقيقية.

تعرض بطاقات مؤشرات (KPI) محسوبة لحظياً من طبقة الحسابات، وأحدث الفواتير،
وأزرار إجراءات سريعة تنقّل إلى الصفحات الفعلية، وأشرطة عدّادات للأساسيات.
الألوان تُقرأ من رموز الثيم (theme) فتعمل في الوضعين الفاتح والداكن،
و refresh() تعيد احتساب القيم وإعادة تلوينها عند فتح الصفحة أو تبديل المظهر.
"""
from __future__ import annotations

from datetime import date

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import (
    QFrame, QGridLayout, QHBoxLayout, QHeaderView, QLabel, QPushButton,
    QScrollArea, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from ..core import calc, db, repo
from ..utils import fmt
from .theme import token


class DashboardPage(QWidget):
    """لوحة رئيسية موجزة ببيانات لحظية من قاعدة البيانات."""

    # للتنقّل إلى صفحات فعلية عند الضغط على إجراء سريع
    navigate_requested = Signal(str)

    TITLE = "لوحة المعلومات"
    SUBTITLE = "نظرة سريعة على نشاط الشركة"

    # بطاقات المؤشرات: (مفتاح، عنوان، أيقونة، رمز لون من الثيم)
    _KPIS = [
        ("rev",     "إيرادات النقل",   "🚛", "PRIMARY"),
        ("net",     "صافي الربح",      "📈", "SUCCESS"),
        ("invoices","فواتير النقل",    "🧾", "VIOLET"),
        ("owed",    "مستحق على العملاء", "👥", "WARNING"),
    ]

    # الإجراءات السريعة: (النص الظاهر، الصفحة الوجهة)
    _ACTIONS = [
        ("🧾 فاتورة نقل جديدة", "فواتير النقل"),
        ("📥 سند قبض جديد", "سندات القبض"),
        ("📤 سند دفع جديد", "سندات الدفع"),
        ("👥 عميل جديد", "العملاء"),
    ]

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("page")
        root = QVBoxLayout(self)
        root.setContentsMargins(22, 18, 22, 18)
        root.setSpacing(12)

        # ---------------- الترويسة ----------------
        head = QHBoxLayout()
        accent = QFrame()
        accent.setObjectName("titleAccent")
        accent.setFixedSize(6, 46)
        head.addWidget(accent, 0, Qt.AlignmentFlag.AlignVCenter)
        titles = QVBoxLayout()
        titles.setSpacing(2)
        t = QLabel(self.TITLE)
        t.setObjectName("pageTitle")
        titles.addWidget(t)
        self.sub_label = QLabel(self.SUBTITLE)
        self.sub_label.setObjectName("pageSub")
        titles.addWidget(self.sub_label)
        head.addLayout(titles, 1)
        head.addStretch(1)
        root.addLayout(head)

        # ---------------- حاوية قابلة للتمرير ----------------
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setStyleSheet(
            "QScrollArea { background: transparent; border: none; }")
        body = QWidget()
        body.setStyleSheet("background: transparent;")
        lay = QVBoxLayout(body)
        lay.setContentsMargins(0, 8, 0, 8)
        lay.setSpacing(14)
        scroll.setWidget(body)
        root.addWidget(scroll, 1)

        # ---------------- بطاقات المؤشرات (4) ----------------
        self._value_labels: list[tuple[QLabel, str]] = []
        grid = QGridLayout()
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(12)
        for i, (_key, caption, icon, color_key) in enumerate(self._KPIS):
            card = QFrame()
            card.setObjectName("kpiCard")
            card.setMinimumHeight(110)
            cv = QVBoxLayout(card)
            cv.setContentsMargins(16, 12, 16, 12)
            cv.setSpacing(4)
            top = QHBoxLayout()
            ic = QLabel(icon)
            ic.setStyleSheet("font-size: 20pt; background: transparent;")
            top.addWidget(ic)
            top.addStretch(1)
            cv.addLayout(top)
            cap = QLabel(caption)
            cap.setObjectName("kpiCaption")
            cv.addWidget(cap)
            val = QLabel("—")
            val.setStyleSheet(
                "font-size: 21pt; font-weight: bold; background: transparent;")
            cv.addWidget(val)
            self._value_labels.append((val, color_key))
            grid.addWidget(card, i // 2, i % 2)
        lay.addLayout(grid)

        # ---------------- أشرطة عدّادات (الأساسيات) ----------------
        self.counts_label = QLabel("")
        self.counts_label.setObjectName("chip")
        self.counts_label.setWordWrap(True)
        self.counts_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(self.counts_label)

        # ---------------- الإجراءات السريعة ----------------
        act_title = QLabel("⚡ إجراءات سريعة")
        act_title.setObjectName("sectionLabel")
        lay.addWidget(act_title)
        act_row = QHBoxLayout()
        act_row.setSpacing(10)
        for text, target in self._ACTIONS:
            b = QPushButton(text)
            b.setObjectName("primary")
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.clicked.connect(lambda _=False, t=target: self.navigate_requested.emit(t))
            act_row.addWidget(b)
        act_row.addStretch(1)
        lay.addLayout(act_row)

        # ---------------- أحدث الفواتير ----------------
        table_title = QLabel("📋 أحدث الفواتير")
        table_title.setObjectName("sectionLabel")
        lay.addWidget(table_title)

        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(
            ["رقم الفاتورة", "العميل", "النقلات", "الإجمالي", "التاريخ"])
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        self.table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Stretch)
        for c in (0, 2, 3, 4):
            self.table.horizontalHeader().setSectionResizeMode(
                c, QHeaderView.ResizeMode.ResizeToContents)
        self.table.setMaximumHeight(300)
        lay.addWidget(self.table)

        self.refresh()

    # ------------------------------------------------------------------
    def _period(self) -> tuple[str, str, str]:
        """فترة العرض: السنة المالية المفتوحة التي تحتوي اليوم، أو أول سنة
        مفتوحة، وإلا السنة الحالية من بدايتها حتى اليوم."""
        conn = db.get_conn()
        today = date.today().isoformat()
        years = repo.list_years(conn)
        open_years = [y for y in years if (y["status"] or "") == "open"]
        chosen = None
        for y in open_years:
            if (y["date_from"] or "") <= today <= (y["date_to"] or ""):
                chosen = y
                break
        if chosen is None and open_years:
            chosen = open_years[0]
        if chosen is not None:
            label = f"السنة المالية {chosen['year']}"
            return label, chosen["date_from"], chosen["date_to"]
        # لا توجد سنة: اعرض من بداية السنة الحالية حتى اليوم
        d_from = f"{date.today().year}-01-01"
        return f"من {d_from} حتى اليوم", d_from, today

    # ------------------------------------------------------------------
    def refresh(self, *_a) -> None:
        conn = db.get_conn()
        period_label, d_from, d_to = self._period()

        # --- بطاقات المؤشرات ---
        try:
            pnl = calc.pnl_report(conn, d_from, d_to)
        except Exception:  # noqa: BLE001
            pnl = {}
        try:
            inv_count = conn.execute(
                "SELECT COUNT(*) FROM invoices "
                "WHERE date>=? AND date<=?", (d_from, d_to)).fetchone()[0]
        except Exception:  # noqa: BLE001
            inv_count = 0
        try:
            owed = round(sum(max(0.0, float(c["balance"]))
                             for c in calc.customers_with_balance(conn)), 2)
        except Exception:  # noqa: BLE001
            owed = 0.0

        def val(key: str) -> float:
            return {
                "rev": float(pnl.get("transport_revenue", 0) or 0),
                "net": float(pnl.get("net", 0) or 0),
                "invoices": float(inv_count),
                "owed": float(owed),
            }[key]

        for (key, _cap, _ic, color_key), (label, _ck) in zip(
                self._KPIS, self._value_labels):
            v = val(key)
            label.setText(fmt.money(v) if key != "invoices"
                          else f"{int(v)} فاتورة")
            label.setStyleSheet(
                "font-size: 21pt; font-weight: bold; background: transparent; "
                f"color: {token(color_key)};")
        self.sub_label.setText(f"{self.SUBTITLE} — {period_label}")

        # --- أشرطة العدّادات ---
        try:
            n_cust = len(repo.list_customers(conn))
            n_supp = len(repo.list_suppliers(conn))
            n_veh = len(repo.list_vehicles(conn))
            n_emp = len(repo.list_employees(conn))
            cash = sum(1 for a in calc.all_accounts(conn) if a[0] == "cashbox")
            bank = sum(1 for a in calc.all_accounts(conn) if a[0] == "bank")
        except Exception:  # noqa: BLE001
            n_cust = n_supp = n_veh = n_emp = cash = bank = 0
        self.counts_label.setText(
            f"👥 العملاء {n_cust}   •   🏭 الموردون {n_supp}   •   "
            f"🚚 السيارات {n_veh}   •   🧑‍🔧 الموظفون {n_emp}   •   "
            f"💵 الخزائن {cash}   •   🏦 البنوك {bank}")

        # --- أحدث الفواتير (آخر 8) ---
        self._fill_invoices(conn)

    def _fill_invoices(self, conn) -> None:
        self.table.setRowCount(0)
        rows = conn.execute(
            "SELECT i.id, i.number, i.date, c.name AS customer_name, "
            "i.vat_rate "
            "FROM invoices i JOIN customers c ON c.id=i.customer_id "
            "ORDER BY i.date DESC, i.number DESC LIMIT 8").fetchall()
        from PySide6.QtGui import QColor
        primary = QColor(token("ACCENT_TEXT"))
        for r, row in enumerate(rows):
            self.table.insertRow(r)
            try:
                tot = calc.invoice_totals(conn, row["id"])
                total = fmt.money(tot.get("customer_total", 0))
            except Exception:  # noqa: BLE001
                total = "0.00"
            try:
                trips = conn.execute(
                    "SELECT COUNT(*) FROM invoice_trips "
                    "WHERE invoice_id=?", (row["id"],)).fetchone()[0]
            except Exception:  # noqa: BLE001
                trips = 0
            vals = [
                calc.invoice_number_label(row["number"]),
                row["customer_name"] or "—",
                str(trips),
                total,
                row["date"],
            ]
            for c, val in enumerate(vals):
                item = QTableWidgetItem(val)
                item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                if c == 0:
                    item.setForeground(primary)
                if c == 4:
                    f = QFont(item.font())
                    f.setBold(False)
                    item.setFont(f)
                self.table.setItem(r, c, item)
