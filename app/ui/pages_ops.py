# -*- coding: utf-8 -*-
"""صفحات العمليات اليومية: فواتير النقل، سندات القبض، سندات الدفع."""
from __future__ import annotations

from datetime import date

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox, QFrame, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget,
)

from ..core import calc, db, repo
from ..utils import fmt
from ..utils.fmt import PAYMENT_TYPES, RECEIPT_TYPES
from .dialogs_ops import (
    InvoiceDialog, PaymentDialog, ReceiptDialog, export_customer_invoice_pdf,
    print_customer_invoice,
)
from .pages_base import CrudPage
from .widgets import (
    DataTable, DictCombo, FlowLayout, TotalsBar, VDateEdit, add_shadow,
    confirm, warn,
)


class FilterRow(QWidget):
    """صف فلاتر موحد داخل بطاقة ناعمة يلتف تلقائياً — لا تُغطى الأزرار أبداً.

    من تاريخ / إلى تاريخ / فلاتر إضافية / زر عرض.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        card = QFrame()
        card.setObjectName("filterCard")
        self.card = card
        self._lay = FlowLayout(margin=0, spacing=10)
        card.setLayout(self._lay)
        card.setStyleSheet("#filterCard { padding: 10px 14px; }")
        add_shadow(card, blur=12, alpha=20, dy=1)
        outer.addWidget(card)

        self.from_edit = VDateEdit()
        self.from_edit.set_iso(f"{date.today().year}-01-01")
        self.to_edit = VDateEdit()
        self.refresh_btn = QPushButton("🔄  عرض")
        self.refresh_btn.setObjectName("primary")
        self.refresh_btn.setFixedHeight(36)
        self.refresh_btn.setCursor(Qt.CursorShape.PointingHandCursor)

        # ترتيب العناصر: [من تاريخ، إلى تاريخ، فلاتر إضافية...، زر العرض]
        self._pairs: list[QWidget] = [
            self._pair("من تاريخ", self.from_edit),
            self._pair("إلى تاريخ", self.to_edit),
        ]
        self._rebuild()

    # ------------------------------------------------------------------
    def _pair(self, label: str, widget: QWidget) -> QWidget:
        wrap = QWidget()
        h = QHBoxLayout(wrap)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(8)
        lab = QLabel(label)
        lab.setObjectName("filterLabel")
        h.addWidget(lab)
        h.addWidget(widget)
        return wrap

    def _rebuild(self) -> None:
        """إعادة ترتيب عناصر الفلتر مع بقاء زر العرض في النهاية."""
        while self._lay.count():
            item = self._lay.takeAt(0)
            if item and item.widget():
                item.widget().setParent(self.card)
        for pair in self._pairs:
            self._lay.add(pair)
        self._lay.add(self.refresh_btn)

    def add_filter(self, label: str, widget: QWidget) -> QWidget:
        """إضافة فلتر إضافي قبل زر العرض."""
        self._pairs.append(self._pair(label, widget))
        self._rebuild()
        return widget

    def add_combo(self, label: str, items: list[tuple],
                  placeholder: str = "الكل") -> QComboBox:
        combo = QComboBox()
        combo.setFixedHeight(34)
        combo.setMinimumWidth(150)
        combo.addItem(placeholder, None)
        for value, text in items:
            combo.addItem(text, value)
        return self.add_filter(label, combo)

    def range(self) -> tuple[str, str]:
        return self.from_edit.iso(), self.to_edit.iso()


# ---------------------------------------------------------------------------
# فواتير النقل
# ---------------------------------------------------------------------------
class InvoicesPage(CrudPage):
    TITLE = "فواتير النقل"
    SUBTITLE = "رأس الفاتورة + النقلات والمصروفات — الربح الفعلي يشمل مصاريف السندات اللاحقة"

    def build(self) -> "InvoicesPage":
        self.filter_row = FilterRow()
        self.frame.add_layout_at(0, self.filter_row)
        conn = db.get_conn()
        self.customer_combo = DictCombo()
        self.customer_combo.load(repo.list_customers(conn))
        self.filter_row.add_filter("العميل", self.customer_combo)
        self.filter_row.refresh_btn.clicked.connect(self.refresh)

        self.set_table(DataTable(
            ["رقم الفاتورة", "التاريخ", "العميل", "عدد النقلات", "إجمالي النقلات",
             "المصروفات المباشرة", "الربح المتوقع", "مصاريف لاحقة (سندات)",
             "الربح الفعلي"],
            extra=[("print", "🖨️", "طباعة فاتورة العميل"),
                   ("pdf", "📄", "حفظ فاتورة العميل PDF")],
        ))
        self.totals = TotalsBar(["إجمالي النقلات", "إجمالي المصروفات المباشرة",
                                 "إجمالي الأرباح الفعلية"])
        # بطاقات المؤشرات فوق الجدول (أسلوب لوحات التحكم الحديثة)
        self.frame.body.insertWidget(1, self.totals)
        return self

    def fetch(self):
        d_from, d_to = self.filter_row.range()
        cid = self.customer_combo.selected_id()
        data = calc.invoice_list(db.get_conn(), d_from, d_to, cid)
        rows = []
        for inv in data:
            rows.append([
                calc.invoice_number_label(inv["number"]), inv["date"],
                inv["customer_name"], int(self._trips_count(inv)),  # عدّاد
                fmt.money(inv["trips_total"]), fmt.money(inv["expenses_total"]),
                fmt.money(inv["expected_profit"]), fmt.money(inv["later_payments"]),
                fmt.money(inv["actual_profit"]),
            ])
        return [inv["id"] for inv in data], rows

    def _trips_count(self, inv) -> int:
        conn = db.get_conn()
        r = conn.execute("SELECT COUNT(*) AS c FROM invoice_trips WHERE invoice_id=?",
                         (inv["id"],)).fetchone()
        return r["c"]

    def refresh(self, *_a) -> None:
        super().refresh()
        headers, rows = self.table.export_data()
        if len(rows) >= 2:
            def col_sum(i):
                try:
                    return sum(float(r[i].replace(",", "")) for r in rows)
                except ValueError:
                    return 0.0
            self.totals.set_value("إجمالي النقلات", col_sum(4))
            self.totals.set_value("إجمالي المصروفات المباشرة", col_sum(5))
            self.totals.set_value("إجمالي الأرباح الفعلية", col_sum(8))

    def export_subtitle(self) -> str:
        d_from, d_to = self.filter_row.range()
        return f"الفترة: من {d_from} إلى {d_to}"

    def on_add(self) -> None:
        if InvoiceDialog(self).exec():
            self.refresh()

    def on_view(self, rid) -> None:
        if InvoiceDialog(self, rid, read_only=True).exec():
            self.refresh()

    def on_edit(self, rid) -> None:
        if InvoiceDialog(self, rid).exec():
            self.refresh()

    def on_delete(self, rid) -> None:
        if not confirm(self, "هل أنت متأكد من حذف هذه الفاتورة وكل نقلاتها؟",
                       "حذف فاتورة"):
            return
        try:
            repo.delete_invoice(db.get_conn(), rid)
            self.refresh()
        except Exception as e:  # noqa: BLE001
            warn(self, str(e))

    def on_extra(self, rid, key: str) -> None:
        if key == "print":
            print_customer_invoice(self, rid)
        elif key == "pdf":
            export_customer_invoice_pdf(self, rid)


# ---------------------------------------------------------------------------
# سندات القبض
# ---------------------------------------------------------------------------
class ReceiptsPage(CrudPage):
    TITLE = "سندات القبض"
    SUBTITLE = "تحصيل من العملاء (يقلل المديونية) أو إيرادات أخرى (تضاف للأرباح)"

    def build(self) -> "ReceiptsPage":
        self.filter_row = FilterRow()
        self.frame.add_layout_at(0, self.filter_row)
        self.type_combo = self.filter_row.add_combo(
            "النوع", [(k, v) for k, v in RECEIPT_TYPES.items()])
        self.filter_row.refresh_btn.clicked.connect(self.refresh)
        self.set_table(DataTable(
            ["رقم السند", "التاريخ", "النوع", "العميل / المصدر", "أودع في",
             "المبلغ", "البيان"]))
        self.totals = TotalsBar(["إجمالي المقبوضات", "تحصيل من عملاء", "إيرادات أخرى"])
        # بطاقات المؤشرات فوق الجدول (أسلوب لوحات التحكم الحديثة)
        self.frame.body.insertWidget(1, self.totals)
        return self

    def fetch(self):
        d_from, d_to = self.filter_row.range()
        vt = self.type_combo.currentData()
        data = repo.list_receipts(db.get_conn(), d_from, d_to, vt)
        rows = []
        for v in data:
            rows.append([
                calc.voucher_number_label("RV", v["number"]), v["date"],
                RECEIPT_TYPES.get(v["voucher_type"], "—"),
                v["customer_name"] or "—", v["account_name"] or "—",
                fmt.money(v["amount"]), v["description"] or "—",
            ])
        return [v["id"] for v in data], rows

    def refresh(self, *_a) -> None:
        super().refresh()
        _, rows = self.table.export_data()
        try:
            amounts = [float(r[5].replace(",", "")) for r in rows]
        except (ValueError, IndexError):
            amounts = []
        self.totals.set_value("إجمالي المقبوضات", sum(amounts))
        self.totals.set_value("تحصيل من عملاء",
                              sum(a for r, a in zip(rows, amounts) if r[2] == "تحصيل من عميل"))
        self.totals.set_value("إيرادات أخرى",
                              sum(a for r, a in zip(rows, amounts) if r[2] == "إيرادات أخرى"))

    def export_subtitle(self) -> str:
        d_from, d_to = self.filter_row.range()
        return f"الفترة: من {d_from} إلى {d_to}"

    def on_add(self) -> None:
        if ReceiptDialog(self).exec():
            self.refresh()

    def on_view(self, rid) -> None:
        if ReceiptDialog(self, rid, read_only=True).exec():
            self.refresh()

    def on_edit(self, rid) -> None:
        if ReceiptDialog(self, rid).exec():
            self.refresh()

    def on_delete(self, rid) -> None:
        if not confirm(self, "هل أنت متأكد من حذف سند القبض هذا؟", "حذف سند"):
            return
        try:
            repo.delete_receipt(db.get_conn(), rid)
            self.refresh()
        except Exception as e:  # noqa: BLE001
            warn(self, str(e))


# ---------------------------------------------------------------------------
# سندات الدفع
# ---------------------------------------------------------------------------
class PaymentsPage(CrudPage):
    TITLE = "سندات الدفع"
    SUBTITLE = ("مصروف رحلة / سلفة موظف / مصروف سيارة (صيانة وكاوتش) / مصروف عام")

    def build(self) -> "PaymentsPage":
        self.filter_row = FilterRow()
        self.frame.add_layout_at(0, self.filter_row)
        self.type_combo = self.filter_row.add_combo(
            "النوع", [(k, v) for k, v in PAYMENT_TYPES.items()])
        self.filter_row.refresh_btn.clicked.connect(self.refresh)
        self.set_table(DataTable(
            ["رقم السند", "التاريخ", "النوع", "التوجيه", "صرف من", "المبلغ", "البيان"]))
        self.totals = TotalsBar(["إجمالي المدفوعات"])
        # بطاقات المؤشرات فوق الجدول (أسلوب لوحات التحكم الحديثة)
        self.frame.body.insertWidget(1, self.totals)
        return self

    def fetch(self):
        d_from, d_to = self.filter_row.range()
        vt = self.type_combo.currentData()
        conn = db.get_conn()
        data = repo.list_payments(conn, d_from, d_to, vt)
        rows = []
        for v in data:
            if v["voucher_type"] == "trip":
                target = f"رحلة بفاتورة {calc.invoice_number_label(v['inv_number'] or 0)}" \
                         f" ({v['customer_name'] or '—'})"
            elif v["voucher_type"] == "advance":
                target = f"سلفة: {v['employee_name'] or '—'}"
            elif v["voucher_type"] == "vehicle":
                target = f"سيارة: {v['plate_number'] or '—'}"
            else:
                target = "مصروف عام"
            rows.append([
                calc.voucher_number_label("PV", v["number"]), v["date"],
                PAYMENT_TYPES.get(v["voucher_type"], "—"), target,
                v["account_name"] or "—", fmt.money(v["amount"]),
                v["description"] or "—",
            ])
        return [v["id"] for v in data], rows

    def refresh(self, *_a) -> None:
        super().refresh()
        _, rows = self.table.export_data()
        try:
            total = sum(float(r[5].replace(",", "")) for r in rows)
        except (ValueError, IndexError):
            total = 0.0
        self.totals.set_value("إجمالي المدفوعات", total)

    def export_subtitle(self) -> str:
        d_from, d_to = self.filter_row.range()
        return f"الفترة: من {d_from} إلى {d_to}"

    def on_add(self) -> None:
        if PaymentDialog(self).exec():
            self.refresh()

    def on_view(self, rid) -> None:
        if PaymentDialog(self, rid, read_only=True).exec():
            self.refresh()

    def on_edit(self, rid) -> None:
        if PaymentDialog(self, rid).exec():
            self.refresh()

    def on_delete(self, rid) -> None:
        if not confirm(self, "هل أنت متأكد من حذف سند الدفع هذا؟", "حذف سند"):
            return
        try:
            repo.delete_payment(db.get_conn(), rid)
            self.refresh()
        except Exception as e:  # noqa: BLE001
            warn(self, str(e))
