# -*- coding: utf-8 -*-
"""صفحات دورة الموردين والرواتب المُضافة لتطابق نسخة الويب:
الموردون، فواتير المشتريات، الإشعارات الدائنة/المدينة، متابعة السلفيات، الخصومات."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog, QLabel, QPushButton, QVBoxLayout

from ..core import calc, db, repo
from ..utils import fmt
from ..utils.fmt import NOTE_TYPES, PURCHASE_EXPENSE_CATEGORIES
from .dialogs_ops import CreditDebitNoteDialog, PaymentDialog
from .dialogs_suppliers import PurchaseInvoiceDialog, SupplierDialog
from .pages_base import CrudPage
from .statements import SupplierStatementDialog
from .widgets import (
    AmountEdit, DataTable, DictCombo, FormDialog, PlainTable, VDateEdit,
    confirm, warn,
)

from PySide6.QtWidgets import QLineEdit


# ---------------------------------------------------------------------------
# الموردون
# ---------------------------------------------------------------------------
class SuppliersPage(CrudPage):
    TITLE = "جدول الموردين"
    SUBTITLE = ("الرصيد = الافتتاحي + فواتير المشتريات شاملة الضريبة − المسدَّد "
                "(موجب = مستحق له علينا)")

    def build(self) -> "SuppliersPage":
        self.set_table(DataTable(
            ["الكود", "اسم المورّد", "الهاتف", "الشخص المسؤول", "مدة السداد",
             "الرصيد الافتتاحي", "الرصيد الحالي"],
            extra=[("statement", "📄", "كشف حساب المورّد")],
        ))
        return self

    def fetch(self):
        rows = []
        data = calc.suppliers_with_balance(db.get_conn())
        for s in data:
            rows.append([s["code"], s["name"], s["phone"] or "—",
                         s["contact_person"] or "—",
                         f"{int(s['payment_terms'] or 0)} يوم",
                         fmt.money(s["opening_balance"]), fmt.money(s["balance"])])
        return [s["id"] for s in data], rows

    def on_add(self) -> None:
        if SupplierDialog(self).exec():
            self.refresh()

    def on_view(self, rid) -> None:
        if SupplierDialog(self, rid, read_only=True).exec():
            self.refresh()

    def on_edit(self, rid) -> None:
        if SupplierDialog(self, rid).exec():
            self.refresh()

    def on_delete(self, rid) -> None:
        if not confirm(self, "هل أنت متأكد من حذف هذا المورّد؟", "حذف مورّد"):
            return
        try:
            repo.delete_supplier(db.get_conn(), rid)
            self.refresh()
        except Exception as e:  # noqa: BLE001
            warn(self, str(e))

    def on_extra(self, rid, key: str) -> None:
        if key == "statement":
            SupplierStatementDialog(rid, self).exec()


# ---------------------------------------------------------------------------
# فواتير المشتريات
# ---------------------------------------------------------------------------
class PurchasesPage(CrudPage):
    TITLE = "فواتير المشتريات"
    SUBTITLE = ("النقدية تُدفع فوراً بسند تلقائي، والآجلة تُرحَّل على حساب المورّد. "
                "المصروف يُثبت في الأرباح والخسائر عند تاريخ الفاتورة.")

    def build(self) -> "PurchasesPage":
        self.set_table(DataTable(
            ["الرقم", "التاريخ", "النوع", "المورّد", "بند المصروف",
             "قبل الضريبة", "الضريبة", "الإجمالي", "جهة الدفع"]))
        return self

    def fetch(self):
        rows = []
        data = repo.list_purchase_invoices(db.get_conn())
        for d in data:
            rows.append([
                f"#{d['number']}", d["date"],
                "نقدية" if d["purchase_type"] == "cash" else "آجلة",
                d.get("supplier_name") or "— (نقدية)",
                PURCHASE_EXPENSE_CATEGORIES.get(d["expense_category"],
                                                d["expense_category"]),
                fmt.money(d["net"]), fmt.money(d["vat"]), fmt.money(d["total"]),
                d.get("account_name") or "—"])
        return [d["id"] for d in data], rows

    def on_add(self) -> None:
        if PurchaseInvoiceDialog(self).exec():
            self.refresh()

    def on_view(self, rid) -> None:
        if PurchaseInvoiceDialog(self, rid, read_only=True).exec():
            self.refresh()

    def on_edit(self, rid) -> None:
        if PurchaseInvoiceDialog(self, rid).exec():
            self.refresh()

    def on_delete(self, rid) -> None:
        if not confirm(self, "هل أنت متأكد من حذف فاتورة المشتريات "
                             "(وسند الدفع التلقائي المرتبط بها)؟", "حذف فاتورة"):
            return
        try:
            repo.delete_purchase_invoice(db.get_conn(), rid)
            self.refresh()
        except Exception as e:  # noqa: BLE001
            warn(self, str(e))


# ---------------------------------------------------------------------------
# الإشعارات الدائنة والمدينة
# ---------------------------------------------------------------------------
class NotesPage(CrudPage):
    TITLE = "الإشعارات الدائنة والمدينة"
    SUBTITLE = ("الفاتورة لا تُعدَّل بعد إصدارها — التصحيح بإشعار دائن "
                "(مرتجع/خصم) أو إشعار مدين (إضافة).")
    ADD_TEXT = "➕ إشعار جديد"

    def build(self) -> "NotesPage":
        self.set_table(DataTable(
            ["الرقم", "التاريخ", "النوع", "الفاتورة", "العميل",
             "قبل الضريبة", "الضريبة %", "الإجمالي", "السبب"],
            actions=("view", "delete"),
        ))
        return self

    def fetch(self):
        rows = []
        data = repo.list_credit_debit_notes(db.get_conn())
        for n in data:
            is_debit = n["note_type"] == "debit"
            rows.append([
                f"{'DN' if is_debit else 'CN'}-{n['number']:05d}",
                n["date"], NOTE_TYPES.get(n["note_type"], n["note_type"]),
                f"#{n['invoice_number']}", n["customer_name"],
                fmt.money(n["amount"]), fmt.money(n["vat_rate"]),
                fmt.money(n["total"]), n["reason"]])
        return [n["id"] for n in data], rows

    def on_add(self) -> None:
        if CreditDebitNoteDialog(self).exec():
            self.refresh()

    def on_view(self, rid) -> None:
        n = repo.get_credit_debit_note(db.get_conn(), rid)
        if not n:
            return
        from .widgets import info
        labels = [f"{t}" for t in (n.get("trip_ids") or [])]
        info(self,
             f"النوع: {NOTE_TYPES.get(n['note_type'], n['note_type'])}\n"
             f"التاريخ: {n['date']}\n"
             f"المبلغ قبل الضريبة: {fmt.money(n['amount'])}\n"
             f"نسبة الضريبة: {fmt.money(n['vat_rate'])}%\n"
             f"الإجمالي: {fmt.money(n['total'])}\n"
             f"السبب: {n['reason']}"
             + (f"\nالنقلات المرتجعة: {len(labels)}" if labels else ""),
             "تفاصيل الإشعار")

    def on_delete(self, rid) -> None:
        if not confirm(self, "هل أنت متأكد من حذف الإشعار؟ "
                             "سيعود رصيد العميل لما كان عليه.", "حذف إشعار"):
            return
        try:
            repo.delete_credit_debit_note(db.get_conn(), rid)
            self.refresh()
        except Exception as e:  # noqa: BLE001
            warn(self, str(e))


# ---------------------------------------------------------------------------
# متابعة السلفيات
# ---------------------------------------------------------------------------
class AdvancesPage(CrudPage):
    TITLE = "متابعة السلفيات"
    SUBTITLE = ("كل سلفة موظف/سائق مع المسدَّد منها في المسيرات والمتبقي. "
                "لا يمكن تعديل سلفة عليها تسويات.")
    ADD_TEXT = "➕ سلفة جديدة"

    def build(self) -> "AdvancesPage":
        self.set_table(DataTable(
            ["رقم السند", "التاريخ", "الموظف/السائق", "جهة الصرف", "قيمة السلفة",
             "المسدَّد", "المتبقي", "الحالة", "البيان"],
            actions=("view", "edit", "delete"),
        ))
        return self

    def fetch(self):
        conn = db.get_conn()
        rows, ids = [], []
        employees = {e["id"]: e["name"] for e in repo.list_employees(conn)}
        for v in conn.execute(
            "SELECT * FROM payment_vouchers WHERE voucher_type='advance' "
            "ORDER BY date DESC, number DESC"
        ):
            settled = float(conn.execute(
                "SELECT COALESCE(SUM(amount),0) FROM advance_settlements "
                "WHERE payment_voucher_id=?", (v["id"],)).fetchone()[0])
            remaining = round(float(v["amount"] or 0) - settled, 2)
            ids.append(v["id"])
            rows.append([
                calc.voucher_number_label("PV", v["number"]), v["date"],
                employees.get(v["employee_id"], "—"),
                calc.account_name(conn, v["account_kind"], v["account_id"]),
                fmt.money(v["amount"]), fmt.money(settled), fmt.money(remaining),
                "مسددة" if remaining <= 0.009 else (
                    "جزئية" if settled > 0 else "قائمة"),
                v["description"] or "—"])
        return ids, rows

    def on_add(self) -> None:
        dlg = PaymentDialog(self)
        if dlg.exec():
            self.refresh()

    def on_view(self, rid) -> None:
        row = next((r for r in calc.advance_archive(db.get_conn())
                    if r["id"] == rid), None)
        if row is None:
            return
        ArchiveDetailDialog(self, "تفصيل تسويات السلفة", row,
                            "قيمة السلفة").exec()

    def on_edit(self, rid) -> None:
        if PaymentDialog(self, rid).exec():
            self.refresh()

    def on_delete(self, rid) -> None:
        if not confirm(self, "هل أنت متأكد من حذف السلفة؟", "حذف سلفة"):
            return
        try:
            repo.delete_payment(db.get_conn(), rid)
            self.refresh()
        except Exception as e:  # noqa: BLE001
            warn(self, str(e))


# ---------------------------------------------------------------------------
# الخصومات
# ---------------------------------------------------------------------------
class ArchiveDetailDialog(QDialog):
    """تفصيل تسويات سلفة أو خصم: أي مسيرة سدّدت كم ومتى."""

    def __init__(self, parent, title: str, row: dict, amount_label: str):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        self.resize(560, 420)
        root = QVBoxLayout(self)
        head = QLabel(
            f"<b>{amount_label}:</b> {fmt.money(row.get('amount') or 0)}"
            f" &nbsp;|&nbsp; <b>المسدَّد:</b> {fmt.money(row.get('settled') or 0)}"
            f" &nbsp;|&nbsp; <b>المتبقي:</b> {fmt.money(row.get('remaining') or 0)}"
            f" &nbsp;|&nbsp; <b>الحالة:</b> "
            f"{{'settled': 'مسدَّد', 'partial': 'جزئي', 'open': 'قائم'}}"
            f"[row.get('status', 'open')]")
        head.setTextFormat(Qt.TextFormat.RichText)
        head.setWordWrap(True)
        root.addWidget(head)
        table = PlainTable(["المسيرة", "تاريخها", "الفترة", "المبلغ المسدَّد"])
        rows = [[f"مسيرة {st['payroll_number']}" if st["payroll_number"] else "—",
                 st["payroll_date"] or "—", st["period_label"],
                 fmt.money(st["amount"])]
                for st in (row.get("settlements") or [])]
        table.set_rows(rows or [["—", "—", "لا توجد تسويات بعد", "—"]])
        root.addWidget(table, 1)
        btn = QPushButton("إغلاق")
        btn.clicked.connect(self.accept)
        root.addWidget(btn)


class DeductionDialog(FormDialog):
    def __init__(self, parent=None, deduction_id: int | None = None,
                 read_only: bool = False):
        super().__init__(parent, "بند خصم على موظف/سائق", read_only, width=560)
        self.deduction_id = deduction_id
        conn = db.get_conn()
        self.number_label = QLineEdit("تلقائي")
        self.number_label.setReadOnly(True)
        self.add_row("رقم البند", self.number_label)
        self.date_edit = VDateEdit()
        self.add_row("التاريخ *", self.date_edit)
        self.employee_combo = DictCombo()
        self.employee_combo.load(repo.list_employees(conn))
        self.add_row("الموظف / السائق *", self.employee_combo)
        self.amount_edit = AmountEdit()
        self.add_row("مبلغ الخصم *", self.amount_edit)
        self.reason_edit = QLineEdit()
        self.reason_edit.setPlaceholderText("مثال: مخالفة مرورية، عهدة، تلفيات")
        self.add_row("سبب الخصم *", self.reason_edit)
        self.notes_edit = QLineEdit()
        self.add_row("ملاحظات", self.notes_edit)
        self.remaining_label = QLineEdit("")
        self.remaining_label.setReadOnly(True)
        self.add_row("المسدَّد / المتبقي", self.remaining_label)

        if deduction_id:
            d = repo.get_deduction(conn, deduction_id)
            if d:
                self.number_label.setText(f"DED-{d['number']:05d}")
                self.date_edit.set_iso(d["date"])
                self.employee_combo.select(d["employee_id"])
                self.amount_edit.set_value(d["amount"])
                self.reason_edit.setText(d["reason"] or "")
                self.notes_edit.setText(d["notes"] or "")
                settled = float(conn.execute(
                    "SELECT COALESCE(SUM(amount),0) FROM deduction_settlements "
                    "WHERE employee_deduction_id=?", (deduction_id,)).fetchone()[0])
                self.remaining_label.setText(
                    f"مسدَّد {fmt.money(settled)} | متبقٍ "
                    f"{fmt.money(float(d['amount'] or 0) - settled)}")
        if read_only:
            self.lock_fields()

    def save(self) -> None:
        repo.save_deduction(db.get_conn(), {
            "date": self.date_edit.iso(),
            "employee_id": self.employee_combo.selected_id(),
            "amount": self.amount_edit.value(),
            "reason": fmt.clean(self.reason_edit.text()),
            "notes": fmt.clean(self.notes_edit.text()),
        }, self.deduction_id)


class DeductionsPage(CrudPage):
    TITLE = "الخصومات"
    SUBTITLE = ("بنود خصم مُتتبَّعة على الموظف/السائق تُقتطع كلياً أو جزئياً "
                "من مسيرات الرواتب.")

    def build(self) -> "DeductionsPage":
        self.set_table(DataTable(
            ["الرقم", "التاريخ", "الموظف/السائق", "السبب", "المبلغ",
             "المسدَّد", "المتبقي", "الحالة"]))
        return self

    def fetch(self):
        rows = []
        data = repo.list_deductions(db.get_conn())
        status = {"open": "قائمة", "partial": "جزئية", "closed": "مسددة"}
        for d in data:
            rows.append([f"DED-{d['number']:05d}", d["date"], d["employee_name"],
                         d["reason"], fmt.money(d["amount"]),
                         fmt.money(d["settled"]), fmt.money(d["remaining"]),
                         status.get(d["status"], d["status"])])
        return [d["id"] for d in data], rows

    def on_add(self) -> None:
        if DeductionDialog(self).exec():
            self.refresh()

    def on_view(self, rid) -> None:
        row = next((r for r in calc.deduction_archive(db.get_conn())
                    if r["id"] == rid), None)
        if row is None:
            return
        ArchiveDetailDialog(self, "تفصيل تسويات الخصم", row,
                            "قيمة الخصم").exec()

    def on_edit(self, rid) -> None:
        if DeductionDialog(self, rid).exec():
            self.refresh()

    def on_delete(self, rid) -> None:
        if not confirm(self, "هل أنت متأكد من حذف بند الخصم؟", "حذف بند خصم"):
            return
        try:
            repo.delete_deduction(db.get_conn(), rid)
            self.refresh()
        except Exception as e:  # noqa: BLE001
            warn(self, str(e))
