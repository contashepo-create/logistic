# -*- coding: utf-8 -*-
"""نوافذ العمليات اليومية: فاتورة النقل (رأس + نقلات + مصروفات + مرفقات)،
سندات القبض، سندات الدفع، وطباعة فاتورة العميل الرسمية."""
from __future__ import annotations

import base64
from pathlib import Path

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QAbstractItemView, QComboBox, QDialog, QFileDialog, QFormLayout, QGroupBox,
    QHBoxLayout, QHeaderView, QLabel, QLineEdit, QListWidget, QListWidgetItem,
    QPushButton, QStackedLayout, QTableWidget, QTableWidgetItem, QVBoxLayout,
    QWidget,
)

from ..core import calc, db, features, repo, tax
from ..core.rules import RuleError
from ..utils import exporter, fmt, invoice_templates
from ..utils.fmt import (
    EXPENSE_SOURCES, EXPENSE_SOURCE_HINTS, EXPENSE_TYPES, NOTE_TYPES,
    PAYMENT_TYPES, RECEIPT_TYPES, VEHICLE_EXPENSES
)
from .widgets import (
    AccountCombo, AmountEdit, DictCombo, FormDialog, TotalsBar, VDateEdit,
    _row_button, error_msg, warn,
)


def _text(s) -> str:
    return fmt.clean(s)


def _expense_amount(e: dict) -> float:
    """مبلغ المصروف: من amount إن وُجد، وإلا يُحسب من الكمية × قيمة الوحدة."""
    if e.get("amount"):
        return float(e.get("amount") or 0)
    return round(float(e.get("qty", 1) or 0) * float(e.get("unit_amount", 0) or 0), 2)


# ===========================================================================
# فاتورة النقل
# ===========================================================================
class TripDialog(FormDialog):
    """إضافة/تعديل نقلة داخل الفاتورة: عدد النقلات × سعر الوحدة + حاويات."""

    def __init__(self, parent=None, trip: dict | None = None):
        super().__init__(parent, "بيانات النقلة", width=560)
        conn = db.get_conn()
        self.vehicle_combo = DictCombo()
        self.vehicle_combo.load(repo.list_vehicles(conn))
        self.add_row("السيارة (اختياري)", self.vehicle_combo)
        self.driver_combo = DictCombo()
        self.driver_combo.load(repo.list_employees(conn, "driver"))
        self.add_row("السائق (اختياري)", self.driver_combo)
        self.from_edit = QLineEdit()
        self.from_edit.setPlaceholderText("مكان الانطلاق")
        self.add_row("من *", self.from_edit)
        self.to_edit = QLineEdit()
        self.to_edit.setPlaceholderText("مكان الوصول")
        self.add_row("إلى *", self.to_edit)
        self.qty_edit = AmountEdit(1)
        self.qty_edit.setPlaceholderText("1")
        self.qty_edit.textChanged.connect(self._recalc)
        self.add_row("عدد النقلات *", self.qty_edit)
        self.unit_price_edit = AmountEdit()
        self.unit_price_edit.textChanged.connect(self._recalc)
        self.add_row("سعر النقلة الواحدة *", self.unit_price_edit)
        self.total_label = QLabel("0.00")
        self.total_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.add_row("إجمالي السطر", self.total_label)
        self.containers_edit = QLineEdit()
        self.containers_edit.setPlaceholderText(
            "أرقام الحاويات مفصولة بفاصلة (بعدد النقلات كحد أقصى)")
        self.add_row("أرقام الحاويات", self.containers_edit)
        self.notes_edit = QLineEdit()
        self.add_row("ملاحظات", self.notes_edit)

        if trip:
            self.vehicle_combo.select(trip.get("vehicle_id"))
            self.driver_combo.select(trip.get("driver_id"))
            self.from_edit.setText(trip.get("from_loc", ""))
            self.to_edit.setText(trip.get("to_loc", ""))
            self.qty_edit.set_value(trip.get("qty", 1) or 1)
            self.unit_price_edit.set_value(trip.get("unit_price")
                                           or trip.get("price", 0))
            self.containers_edit.setText(", ".join(trip.get("container_numbers") or []))
            self.notes_edit.setText(trip.get("notes", ""))
        self._recalc()

    def _recalc(self) -> None:
        total = (float(self.qty_edit.value() or 0)
                 * float(self.unit_price_edit.value() or 0))
        self.total_label.setText(fmt.money(total))

    def data(self) -> dict:
        raw = self.containers_edit.text().replace("،", ",").split(",")
        containers = [c.strip() for c in raw if c.strip()]
        return {
            "vehicle_id": self.vehicle_combo.selected_id(),
            "driver_id": self.driver_combo.selected_id(),
            "from_loc": _text(self.from_edit.text()),
            "to_loc": _text(self.to_edit.text()),
            "qty": self.qty_edit.value(),
            "unit_price": self.unit_price_edit.value(),
            "price": round(self.qty_edit.value() * self.unit_price_edit.value(), 2),
            "container_numbers": containers,
            "notes": _text(self.notes_edit.text()),
            "expenses": [],
        }


class ExpenseDialog(FormDialog):
    """مصروف نقلة: كمية × قيمة وحدة + مصدر التمويل وأثره المحاسبي."""

    def __init__(self, parent=None, expense: dict | None = None,
                 has_driver: bool = False):
        super().__init__(parent, "مصروف النقلة", width=520)
        conn = db.get_conn()
        self.type_combo = QComboBox()
        for key, label in EXPENSE_TYPES.items():
            self.type_combo.addItem(label, key)
        self.add_row("نوع المصروف *", self.type_combo)
        self.qty_edit = AmountEdit(1)
        self.qty_edit.textChanged.connect(self._recalc)
        self.add_row("الكمية *", self.qty_edit)
        self.unit_edit = AmountEdit()
        self.unit_edit.textChanged.connect(self._recalc)
        self.add_row("قيمة الوحدة *", self.unit_edit)
        self.total_label = QLabel("0.00")
        self.total_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.add_row("الإجمالي", self.total_label)

        self.source_combo = QComboBox()
        for key, label in EXPENSE_SOURCES.items():
            self.source_combo.addItem(label, key)
        self.source_combo.currentIndexChanged.connect(self._source_changed)
        self.add_row("مصدر التمويل *", self.source_combo)
        self.hint_label = QLabel("")
        self.hint_label.setWordWrap(True)
        self.hint_label.setStyleSheet("color:#6b7280; font-size:9pt")
        self.add_row("", self.hint_label)

        self.account_combo = AccountCombo()
        self.account_combo.load(conn)
        self.add_row("الخزينة / البنك المصروف منه *", self.account_combo)
        self.supplier_edit = QLineEdit()
        self.supplier_edit.setPlaceholderText("اسم المورد أو المحطة")
        self.add_row("اسم المورد (للآجل)", self.supplier_edit)
        if not has_driver:
            idx = self.source_combo.findData("driver")
            item = self.source_combo.model().item(idx)
            item.setEnabled(False)
        self.notes_edit = QLineEdit()
        self.add_row("بيان", self.notes_edit)

        if expense:
            idx = self.type_combo.findData(expense.get("expense_type", "other"))
            self.type_combo.setCurrentIndex(idx if idx >= 0 else 0)
            self.qty_edit.set_value(expense.get("qty", 1) or 1)
            self.unit_edit.set_value(expense.get("unit_amount")
                                     or expense.get("amount", 0))
            si = self.source_combo.findData(expense.get("source", "cash"))
            self.source_combo.setCurrentIndex(si if si >= 0 else 0)
            self.account_combo.select(expense.get("account_kind"),
                                      expense.get("account_id"))
            self.supplier_edit.setText(expense.get("supplier_name", "") or "")
            self.notes_edit.setText(expense.get("notes", ""))
        self._source_changed()
        self._recalc()

    def _recalc(self) -> None:
        total = float(self.qty_edit.value() or 0) * float(self.unit_edit.value() or 0)
        self.total_label.setText(fmt.money(total))

    def _source_changed(self) -> None:
        src = self.source_combo.currentData()
        self.hint_label.setText(EXPENSE_SOURCE_HINTS.get(src, ""))
        self.account_combo.setEnabled(src == "cash")
        self.supplier_edit.setEnabled(src == "supplier")

    def data(self) -> dict:
        src = self.source_combo.currentData()
        kind, acc = self.account_combo.current_account()
        return {
            "expense_type": self.type_combo.currentData(),
            "qty": self.qty_edit.value(),
            "unit_amount": self.unit_edit.value(),
            "amount": round(self.qty_edit.value() * self.unit_edit.value(), 2),
            "source": src,
            "account_kind": kind if src == "cash" else None,
            "account_id": acc if src == "cash" else None,
            "supplier_name": _text(self.supplier_edit.text()),
            "notes": _text(self.notes_edit.text()),
        }


class TripExpensesDialog(QDialog):
    """إدارة مصروفات نقلة (داخل محرر الفاتورة)."""

    def __init__(self, trip: dict, parent=None):
        super().__init__(parent)
        self.trip = trip
        self.setWindowTitle("مصروفات النقلة — "
                            f"{trip.get('from_loc', '')} ← {trip.get('to_loc', '')}")
        self.resize(560, 400)
        root = QVBoxLayout(self)
        root.setContentsMargins(12, 10, 12, 10)
        root.setSpacing(8)

        bar = QHBoxLayout()
        add_btn = QPushButton("➕ إضافة مصروف")
        add_btn.setObjectName("primary")
        add_btn.clicked.connect(self.add_expense)
        bar.addWidget(add_btn)
        bar.addStretch(1)
        root.addLayout(bar)

        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(
            ["النوع", "الكمية", "قيمة الوحدة", "الإجمالي", "مصدر التمويل", "العمليات"])
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        root.addWidget(self.table, 1)

        close_btn = QPushButton("تم")
        close_btn.clicked.connect(self.accept)
        root.addWidget(close_btn, 0, Qt.AlignmentFlag.AlignLeft)
        self.refresh()

    def refresh(self) -> None:
        expenses = self.trip.get("expenses", [])
        self.table.setRowCount(len(expenses))
        for r, e in enumerate(expenses):
            for c, val in enumerate([
                    EXPENSE_TYPES.get(e.get("expense_type"), "—"),
                    fmt.money(e.get("qty", 1)), fmt.money(e.get("unit_amount", 0)),
                    fmt.money(e.get("amount", 0)),
                    EXPENSE_SOURCES.get(e.get("source", "cash"), "—")]):
                item = QTableWidgetItem(str(val))
                item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                self.table.setItem(r, c, item)
            w = QWidget()
            lay = QHBoxLayout(w)
            lay.setContentsMargins(2, 1, 2, 1)
            lay.addStretch(1)
            lay.addWidget(_row_button("✏️", "تعديل", "rowBtn",
                                      lambda _=False, x=r: self.edit_expense(x)))
            lay.addWidget(_row_button("🗑️", "حذف", "rowBtnDanger",
                                      lambda _=False, x=r: self.del_expense(x)))
            self.table.setCellWidget(r, 5, w)

    def add_expense(self) -> None:
        dlg = ExpenseDialog(self, has_driver=bool(self.trip.get("driver_id")))
        if dlg.exec():
            self.trip.setdefault("expenses", []).append(dlg.data())
            self.refresh()

    def edit_expense(self, r: int) -> None:
        expenses = self.trip.get("expenses", [])
        if not (0 <= r < len(expenses)):
            return
        dlg = ExpenseDialog(self, expenses[r],
                            has_driver=bool(self.trip.get("driver_id")))
        if dlg.exec():
            expenses[r].update(dlg.data())
            self.refresh()

    def del_expense(self, r: int) -> None:
        expenses = self.trip.get("expenses", [])
        if 0 <= r < len(expenses):
            expenses.pop(r)
            self.refresh()


class InvoiceDialog(QDialog):
    """شاشة إضافة/تعديل/عرض فاتورة نقل: الرأس + النقلات والمصروفات + المرفقات + الإجماليات."""

    def __init__(self, parent=None, invoice_id: int | None = None,
                 read_only: bool = False):
        super().__init__(parent)
        self.invoice_id = invoice_id
        self.read_only = read_only
        self.trips: list[dict] = []
        self.attachments: list[str] = []
        # الفاتورة لا تُعدَّل بعد الإصدار — تُعرض للقراءة والطباعة فقط
        self.read_only = read_only or bool(invoice_id)
        self.setWindowTitle("إصدار فاتورة نقل" if not invoice_id
                            else "فاتورة نقل (للعرض — لا تقبل التعديل)")
        self.resize(1020, 700)
        conn = db.get_conn()

        root = QVBoxLayout(self)
        root.setContentsMargins(14, 12, 14, 12)
        root.setSpacing(10)

        # --- رأس الفاتورة ---
        head = QGroupBox("رأس الفاتورة")
        hf = QFormLayout(head)
        hf.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        self.date_edit = VDateEdit()
        self.customer_combo = DictCombo()
        self.customer_combo.load(repo.list_customers(conn))
        self.number_label = QLabel("تلقائي")
        self.vat_edit = AmountEdit(repo.current_vat_rate(conn))
        self.vat_edit.textChanged.connect(self.refresh)
        hf.addRow("رقم الفاتورة", self.number_label)
        hf.addRow("التاريخ (داخل السنة المالية) *", self.date_edit)
        hf.addRow("العميل *", self.customer_combo)
        hf.addRow("نسبة ضريبة القيمة المضافة %", self.vat_edit)
        self.notes_edit = QLineEdit()
        hf.addRow("ملاحظات الفاتورة", self.notes_edit)
        root.addWidget(head)

        body = QHBoxLayout()
        body.setSpacing(10)

        # --- النقلات والمصروفات ---
        trips_box = QGroupBox("تفاصيل الفاتورة — النقلات والمصروفات")
        tv = QVBoxLayout(trips_box)
        tbar = QHBoxLayout()
        self.add_trip_btn = QPushButton("➕ إضافة نقلة")
        self.add_trip_btn.setObjectName("primary")
        self.add_trip_btn.clicked.connect(self.add_trip)
        tbar.addWidget(self.add_trip_btn)
        tbar.addStretch(1)
        tv.addLayout(tbar)

        self.trips_table = QTableWidget(0, 10)
        self.trips_table.setHorizontalHeaderLabels(
            ["م", "السيارة", "السائق", "من", "إلى", "العدد", "سعر الوحدة",
             "الإجمالي", "مصروفاتها", "العمليات"])
        self.trips_table.verticalHeader().setVisible(False)
        self.trips_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.trips_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.trips_table.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.trips_table.setAlternatingRowColors(True)
        for c in (3, 4):
            self.trips_table.horizontalHeader().setSectionResizeMode(
                c, QHeaderView.ResizeMode.Stretch)
        tv.addWidget(self.trips_table, 1)
        body.addWidget(trips_box, 5)

        # --- المرفقات ---
        att_box = QGroupBox("المرفقات (صور / عقود)")
        av = QVBoxLayout(att_box)
        self.att_list = QListWidget()
        self.att_list.setMaximumHeight(160)
        av.addWidget(self.att_list)
        abar = QHBoxLayout()
        self.att_add_btn = QPushButton("📎 إضافة")
        self.att_add_btn.clicked.connect(self.add_attachment)
        self.att_open_btn = QPushButton("👁️ فتح")
        self.att_open_btn.clicked.connect(self.open_attachment)
        self.att_del_btn = QPushButton("🗑️ حذف")
        self.att_del_btn.clicked.connect(self.remove_attachment)
        for b in (self.att_add_btn, self.att_open_btn, self.att_del_btn):
            abar.addWidget(b)
        av.addLayout(abar)
        av.addStretch(1)
        body.addWidget(att_box, 2)
        root.addLayout(body, 1)

        # --- الإجماليات ---
        self.totals = TotalsBar(["قيمة النقلات", "مصروف يتحمّله العميل",
                                 "التكلفة المباشرة", "الربح المتوقع",
                                 "ضريبة القيمة المضافة", "الإجمالي على العميل"])
        root.addWidget(self.totals)

        # --- أزرار الحفظ ---
        btns = QHBoxLayout()
        btns.addStretch(1)
        if self.read_only and invoice_id:
            print_btn = QPushButton("🖨️ طباعة فاتورة العميل")
            print_btn.setObjectName("primary")
            print_btn.clicked.connect(lambda: print_customer_invoice(self, self.invoice_id))
            btns.addWidget(print_btn)
            note_btn = QPushButton("🧾 إشعار دائن / مدين")
            note_btn.setToolTip("الفاتورة لا تُعدَّل بعد إصدارها — صحّحها بإشعار")
            note_btn.clicked.connect(self._issue_note)
            btns.addWidget(note_btn)
            close_btn = QPushButton("إغلاق")
            close_btn.clicked.connect(self.reject)
            btns.addWidget(close_btn)
        else:
            save_btn = QPushButton("💾 حفظ الفاتورة")
            save_btn.setObjectName("primary")
            save_btn.clicked.connect(self._try_save)
            cancel_btn = QPushButton("إلغاء")
            cancel_btn.clicked.connect(self.reject)
            btns.addWidget(save_btn)
            btns.addWidget(cancel_btn)
        root.addLayout(btns)

        if invoice_id:
            self.load_invoice(conn, invoice_id)
        if self.read_only:
            self.lock()

    def _issue_note(self) -> None:
        dlg = CreditDebitNoteDialog(self, invoice_id=self.invoice_id)
        if dlg.exec():
            self.accept()

    # ------------------------------------------------------------------
    def load_invoice(self, conn, invoice_id: int) -> None:
        d = calc.get_invoice_full(conn, invoice_id)
        if not d:
            return
        self.setWindowTitle(f"فاتورة نقل {calc.invoice_number_label(d['number'])}")
        self.number_label.setText(calc.invoice_number_label(d["number"]))
        self.date_edit.set_iso(d["date"])
        self.customer_combo.select(d["customer_id"])
        self.vat_edit.set_value(d.get("vat_rate", 15))
        self.notes_edit.setText(d.get("notes", "") or "")
        import json
        raw_att = d.get("attachments", [])
        if isinstance(raw_att, str):
            try:
                raw_att = json.loads(raw_att or "[]")
            except (ValueError, TypeError):
                raw_att = []
        self.attachments = list(raw_att) if isinstance(raw_att, list) else []
        self.trips = [dict(t) for t in d["trips"]]
        self.refresh()

    def lock(self) -> None:
        self.date_edit.setEnabled(False)
        self.customer_combo.setEnabled(False)
        self.vat_edit.setReadOnly(True)
        for w in (self.notes_edit,):
            w.setReadOnly(True)
        self.add_trip_btn.setEnabled(False)
        self.att_add_btn.setEnabled(False)
        self.att_del_btn.setEnabled(False)

    # ------------------------------------------------------------------
    def refresh(self) -> None:
        conn = db.get_conn()
        vehicles = {v["id"]: f"{v['code']} | {v['plate_number']}"
                    for v in repo.list_vehicles(conn)}
        drivers = {e["id"]: e["name"] for e in repo.list_employees(conn)}
        self.trips_table.setRowCount(len(self.trips))
        for r, t in enumerate(self.trips):
            exp_sum = sum(_expense_amount(e) for e in t.get("expenses", []))
            vals = [str(r + 1),
                    vehicles.get(t.get("vehicle_id"), "—"),
                    drivers.get(t.get("driver_id"), "—"),
                    t.get("from_loc", ""), t.get("to_loc", ""),
                    fmt.money(t.get("qty", 1)), fmt.money(t.get("unit_price", 0)),
                    fmt.money(t.get("price", 0)), fmt.money(exp_sum)]
            for c, v in enumerate(vals):
                item = QTableWidgetItem(str(v))
                item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                self.trips_table.setItem(r, c, item)
            w = QWidget()
            lay = QHBoxLayout(w)
            lay.setContentsMargins(2, 1, 2, 1)
            lay.setSpacing(3)
            lay.addStretch(1)
            lay.addWidget(_row_button(
                "💰", "مصروفات النقلة", "rowBtn",
                lambda _=False, x=r: self.edit_expenses(x)))
            lay.addWidget(_row_button(
                "✏️", "تعديل النقلة", "rowBtn",
                lambda _=False, x=r: self.edit_trip(x)))
            lay.addWidget(_row_button(
                "🗑️", "حذف النقلة", "rowBtnDanger",
                lambda _=False, x=r: self.remove_trip(x)))
            self.trips_table.setCellWidget(r, 9, w)

        self.att_list.clear()
        for rel in self.attachments:
            QListWidgetItem(Path(rel).name, self.att_list)

        trips_total = sum(float(t.get("price", 0) or 0) for t in self.trips)
        billable = sum(float(e.get("amount", 0) or 0) for t in self.trips
                       for e in t.get("expenses", [])
                       if (e.get("source") or "cash") == "customer")
        exp_total = sum(float(e.get("amount", 0) or 0) for t in self.trips
                        for e in t.get("expenses", [])
                        if (e.get("source") or "cash") != "customer")
        vat_rate = float(self.vat_edit.value() or 0)
        vat_amount = round((trips_total + billable) * vat_rate / 100.0, 2)
        self.totals.set_value("قيمة النقلات", trips_total)
        self.totals.set_value("مصروف يتحمّله العميل", billable)
        self.totals.set_value("التكلفة المباشرة", exp_total)
        self.totals.set_value("الربح المتوقع", trips_total + billable - exp_total)
        self.totals.set_value("ضريبة القيمة المضافة", vat_amount)
        self.totals.set_value("الإجمالي على العميل",
                              trips_total + billable + vat_amount)

    # ------------------------------------------------------------------
    def add_trip(self) -> None:
        dlg = TripDialog(self)
        if dlg.exec():
            self.trips.append(dlg.data())
            self.refresh()

    def edit_trip(self, r: int) -> None:
        if not (0 <= r < len(self.trips)):
            return
        dlg = TripDialog(self, self.trips[r])
        if dlg.exec():
            expenses = self.trips[r].get("expenses", [])
            self.trips[r].update(dlg.data())
            self.trips[r]["expenses"] = expenses
            self.refresh()

    def remove_trip(self, r: int) -> None:
        if 0 <= r < len(self.trips):
            self.trips.pop(r)
            self.refresh()

    def edit_expenses(self, r: int) -> None:
        if 0 <= r < len(self.trips):
            TripExpensesDialog(self.trips[r], self).exec()
            self.refresh()

    # ------------------------------------------------------------------
    def add_attachment(self) -> None:
        files, _ = QFileDialog.getOpenFileNames(
            self, "اختيار المرفقات", "",
            "الملفات (*.jpg *.jpeg *.png *.pdf *.doc *.docx *.xls *.xlsx *.txt)")
        for f in files:
            try:
                self.attachments.append(repo.store_attachment(f))
            except Exception as e:  # noqa: BLE001
                warn(self, f"تعذر نسخ الملف:\n{e}")
        self.refresh()

    def open_attachment(self) -> None:
        item = self.att_list.currentItem()
        if not item:
            return
        rel = self.attachments[self.att_list.currentRow()]
        path = db.data_dir() / rel
        if path.exists():
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))
        else:
            warn(self, "الملف غير موجود في مجلد البيانات.")

    def remove_attachment(self) -> None:
        r = self.att_list.currentRow()
        if 0 <= r < len(self.attachments):
            self.attachments.pop(r)
            self.refresh()

    # ------------------------------------------------------------------
    def _try_save(self) -> None:
        try:
            self.save()
        except (RuleError, ValueError) as e:
            warn(self, str(e))
            return
        except Exception as e:  # noqa: BLE001
            error_msg(self, str(e))
            return
        self.accept()

    def save(self) -> None:
        data = {
            "date": self.date_edit.iso(),
            "customer_id": self.customer_combo.selected_id(),
            "vat_rate": self.vat_edit.value(),
            "notes": self.notes_edit.text().strip(),
            "attachments": self.attachments,
            "trips": self.trips,
        }
        repo.save_invoice(db.get_conn(), data, None)


# ---------------------------------------------------------------------------
# طباعة فاتورة العميل الرسمية (بدون مصروفات وبدون أرباح داخلية)
# ---------------------------------------------------------------------------
def _zatca_qr_img_html(conn, d: dict) -> str:
    """صورة رمز QR المعتمد من زاتكا (Base64 داخل HTML الطباعة)."""
    info = repo.company_info(conn)
    payload = tax.build_zatca_qr(
        info.get("company_name", ""), info.get("company_tax_number", ""),
        f"{d['date']}T00:00:00Z", d["customer_total"], d["vat_amount"])
    png = tax.zatca_qr_png_bytes(payload)
    if not png:
        return ""
    b64 = base64.b64encode(png).decode("ascii")
    return (f"<img src='data:image/png;base64,{b64}' "
            f"style='width:110px;height:110px' alt='QR'>")


def build_invoice_model(conn, invoice_id: int) -> dict | None:
    """نموذج بيانات موحّد للفاتورة تستهلكه كل القوالب (مطابق لـ
    InvoiceTemplateModel في نسخة الويب)."""
    d = calc.get_invoice_full(conn, invoice_id)
    if not d:
        return None
    info = repo.company_info(conn)
    customer = d.get("customer") or {}
    tax_enabled = features.has_feature(conn, "tax_invoice")
    inv_type = (tax.zatca_invoice_type(customer) if tax_enabled else "simplified")
    type_label = tax.ZATCA_TYPE_LABEL[inv_type]
    cur = info.get("currency", "")

    seller_address = tax.format_national_address({
        "region": info.get("company_region"), "city": info.get("company_city"),
        "district": info.get("company_district"),
        "street": info.get("company_street"),
        "building_no": info.get("company_building_no"),
        "postal_code": info.get("company_postal_code"),
        "country": info.get("company_country")}) or info.get("company_address", "")
    buyer_address = tax.format_national_address(customer) or customer.get("address", "")

    # بنود الفاتورة: كل نقلة سطر + كل مصروف يتحمّله العميل سطر
    lines = []
    for t in d["trips"]:
        vehicle = "—"
        if t.get("vehicle_id"):
            v = repo.get_vehicle(conn, t["vehicle_id"])
            vehicle = v["plate_number"] if v else "—"
        driver = "—"
        if t.get("driver_id"):
            e = repo.get_employee(conn, t["employee_id"]) if False else repo.get_employee(conn, t["driver_id"])
            driver = e["name"] if e else "—"
        containers = t.get("container_numbers") or []
        if isinstance(containers, str):
            try:
                import json as _json
                containers = _json.loads(containers or "[]")
            except (ValueError, TypeError):
                containers = []
        desc = f"{t.get('from_loc', '')} ← {t.get('to_loc', '')}"
        extra = []
        if vehicle != "—":
            extra.append(f"السيارة: {vehicle}")
        if driver != "—":
            extra.append(f"السائق: {driver}")
        if containers:
            extra.append("حاويات: " + "، ".join(str(c) for c in containers))
        if extra:
            desc += "  (" + " | ".join(extra) + ")"
        lines.append({"description": desc, "qty": fmt.money(t.get("qty", 1)),
                      "unit_price": fmt.money(t.get("unit_price", t.get("price", 0))),
                      "total": fmt.money(t.get("price", 0))})
        for e in (t.get("expenses") or []):
            if (e.get("source") or "cash") != "customer":
                continue
            label = e.get("notes") or EXPENSE_TYPES.get(e.get("expense_type"), "أخرى")
            lines.append({"description": f"رسوم يتحمّلها العميل — {label}",
                          "qty": fmt.money(e.get("qty", 1)),
                          "unit_price": fmt.money(e.get("unit_amount", e.get("amount", 0))),
                          "total": fmt.money(e.get("amount", 0))})

    net = round(float(d["trips_total"]) + float(d["billable_total"]), 2)
    model = {
        "invoice_number": calc.invoice_number_label(d["number"]),
        "issue_date": str(d["date"]),
        "invoice_title_ar": type_label["ar"],
        "invoice_title_en": type_label["en"],
        "currency": cur,
        "container_number": d.get("container_number", ""),
        "seller": {"name": info.get("company_name", ""),
                   "tax_number": info.get("company_tax_number", ""),
                   "commercial_reg": info.get("company_commercial_reg", ""),
                   "unified_number": info.get("company_unified_number", ""),
                   "address": seller_address,
                   "phone": info.get("company_phone", "")},
        "buyer": {"name": customer.get("name", ""), "code": customer.get("code", ""),
                  "phone": customer.get("phone", ""),
                  # الرقم الضريبي للمشتري يظهر في الفاتورة الضريبية فقط
                  "tax_number": (customer.get("tax_number", "")
                                 if inv_type == "standard" else ""),
                  "address": buyer_address},
        "lines": lines,
        "subtotal": fmt.money(net),
        "vat_rate": fmt.money(d["vat_rate"]),
        "vat_amount": fmt.money(d["vat_amount"]),
        "total": fmt.money(d["customer_total"]),
        "amount_in_words": fmt.amount_to_arabic_words(d["customer_total"], cur or "ريال"),
        "notes": d.get("notes") or "",
        "footer_text": repo.get_setting(conn, "vat_note", ""),
        "warning": ("" if tax_enabled or float(d.get("vat_amount") or 0) <= 0
                    else features.TAX_INVOICE_WARNING),
        # رمز زاتكا جزء من ميزة الفاتورة الضريبية — لا يُطبع وهي معطّلة
        "qr_html": (_zatca_qr_img_html(conn, d) if tax_enabled else ""),
        "qr_caption": "رمز الاستجابة السريعة (ZATCA)",
    }
    return model


def customer_invoice_html(conn, invoice_id: int) -> str:
    """فاتورة بالقالب المختار في إعدادات الطباعة."""
    model = build_invoice_model(conn, invoice_id)
    if not model:
        return ""
    template_id = repo.get_setting(conn, "invoice_template", "modern")
    return invoice_templates.render_invoice(model, template_id)




def print_customer_invoice(parent, invoice_id: int) -> None:
    html = customer_invoice_html(db.get_conn(), invoice_id)
    if html:
        exporter.print_html(parent, html)


def export_customer_invoice_pdf(parent, invoice_id: int) -> None:
    conn = db.get_conn()
    d = calc.get_invoice_full(conn, invoice_id)
    if not d:
        return
    html = customer_invoice_html(conn, invoice_id)
    exporter.export_pdf(parent, html,
                        f"فاتورة {calc.invoice_number_label(d['number'])}.pdf")


# ===========================================================================
# سندات القبض
# ===========================================================================
class ReceiptDialog(FormDialog):
    def __init__(self, parent=None, voucher_id: int | None = None,
                 read_only: bool = False):
        super().__init__(parent, "سند قبض", read_only, width=540)
        self.voucher_id = voucher_id
        conn = db.get_conn()
        self.number_label = QLabel("تلقائي")
        self.add_row("رقم السند", self.number_label)
        self.date_edit = VDateEdit()
        self.add_row("التاريخ *", self.date_edit)
        self.account_combo = AccountCombo()
        self.account_combo.load(conn)
        self.add_row("طريقة التحصيل (إيداع في) *", self.account_combo)
        self.type_combo = QComboBox()
        for key, label in RECEIPT_TYPES.items():
            self.type_combo.addItem(label, key)
        self.type_combo.currentIndexChanged.connect(self._type_changed)
        self.add_row("النوع *", self.type_combo)
        self.customer_combo = DictCombo()
        self.customer_combo.load(repo.list_customers(conn))
        self.add_row("العميل (عند التحصيل منه) *", self.customer_combo)
        self.amount_edit = AmountEdit()
        self.add_row("المبلغ *", self.amount_edit)
        self.desc_edit = QLineEdit()
        self.desc_edit.setPlaceholderText("خردة، إيراد متنوع، تحصيل دفعة...")
        self.add_row("البيان / ملاحظات", self.desc_edit)

        if voucher_id:
            v = conn.execute("SELECT * FROM receipt_vouchers WHERE id=?",
                             (voucher_id,)).fetchone()
            if v:
                self.number_label.setText(calc.voucher_number_label("RV", v["number"]))
                self.date_edit.set_iso(v["date"])
                self.account_combo.select(v["account_kind"], v["account_id"])
                idx = self.type_combo.findData(v["voucher_type"])
                self.type_combo.setCurrentIndex(idx if idx >= 0 else 0)
                self.customer_combo.select(v["customer_id"])
                self.amount_edit.set_value(v["amount"])
                self.desc_edit.setText(v["description"] or "")
        self._type_changed()
        if read_only:
            self.lock_fields()

    def _type_changed(self) -> None:
        is_customer = self.type_combo.currentData() == "customer"
        self.customer_combo.setEnabled(is_customer)
        self.desc_edit.setEnabled(not is_customer)

    def save(self) -> None:
        data = {
            "date": self.date_edit.iso(),
            "account_kind": self.account_combo.current_account()[0],
            "account_id": self.account_combo.current_account()[1],
            "voucher_type": self.type_combo.currentData(),
            "customer_id": self.customer_combo.selected_id(),
            "amount": self.amount_edit.value(),
            "description": _text(self.desc_edit.text()) if self.type_combo.currentData() == "other"
            else _text(self.desc_edit.text()),
        }
        repo.save_receipt(db.get_conn(), data, self.voucher_id)


# ===========================================================================
# سندات الدفع
# ===========================================================================
class PaymentDialog(FormDialog):
    """سند دفع بأحد التوجيهات السبعة (مطابق لنسخة الويب)."""

    def __init__(self, parent=None, voucher_id: int | None = None,
                 read_only: bool = False):
        super().__init__(parent, "سند دفع", read_only, width=660)
        self.voucher_id = voucher_id
        conn = db.get_conn()
        self.number_label = QLabel("تلقائي")
        self.add_row("رقم السند", self.number_label)
        self.date_edit = VDateEdit()
        self.add_row("التاريخ *", self.date_edit)
        self.account_combo = AccountCombo()
        self.account_combo.load(conn)
        self.add_row("طريقة الدفع (صرف من) *", self.account_combo)
        self.type_combo = QComboBox()
        for key, label in PAYMENT_TYPES.items():
            self.type_combo.addItem(label, key)
        self.type_combo.currentIndexChanged.connect(self._type_changed)
        self.add_row("النوع والتوجيه *", self.type_combo)

        # صفوف التوجيه حسب النوع
        self.stack = QWidget()
        self.stack_lay = QStackedLayout(self.stack)
        # 1) مصروف يخص رحلة
        p_trip = QWidget()
        f1 = QFormLayout(p_trip)
        self.trip_combo = DictCombo()
        self.trip_combo.load(calc.trips_options(conn), mapper=lambda r: r["label"])
        f1.addRow("الرحلة (رقم الفاتورة والنقلة) *", self.trip_combo)
        # 2) سلفة موظف
        p_adv = QWidget()
        f2 = QFormLayout(p_adv)
        self.employee_combo = DictCombo()
        self.employee_combo.load(repo.list_employees(conn))
        f2.addRow("الموظف / السائق *", self.employee_combo)
        # 3) مصروف لسيارة
        p_veh = QWidget()
        f3 = QFormLayout(p_veh)
        self.vehicle_combo = DictCombo()
        self.vehicle_combo.load(repo.list_vehicles(conn),
                                mapper=lambda r: f"{r['code']} - {r['plate_number']}")
        f3.addRow("السيارة *", self.vehicle_combo)
        self.vehexp_combo = QComboBox()
        for key, label in VEHICLE_EXPENSES.items():
            self.vehexp_combo.addItem(label, key)
        f3.addRow("نوع المصروف *", self.vehexp_combo)
        # 4) سداد لمورّد
        p_sup = QWidget()
        f4 = QFormLayout(p_sup)
        self.supplier_combo = DictCombo()
        self.supplier_combo.load(repo.list_suppliers(conn))
        self.supplier_combo.currentIndexChanged.connect(self._load_supplier_invoices)
        f4.addRow("المورّد *", self.supplier_combo)
        self.purchase_combo = DictCombo("— غير محدد —")
        f4.addRow("فاتورة المشتريات (اختياري)", self.purchase_combo)
        # 5) دفع فاتورة مشتريات نقدية
        p_pur = QWidget()
        f5 = QFormLayout(p_pur)
        f5.addRow(QLabel("يُنشأ هذا السند تلقائياً عند حفظ فاتورة مشتريات نقدية."))
        # 6) سحب نقدي لصاحب المنشأة
        p_own = QWidget()
        f6 = QFormLayout(p_own)
        f6.addRow(QLabel("مسحوبات المالك تُخصم من الأرباح كبند مستقل في "
                         "تقرير الأرباح والخسائر."))
        # 7) مصروف عام
        p_gen = QWidget()
        f7 = QFormLayout(p_gen)
        f7.addRow(QLabel("مثال: إيجار، كهرباء، رواتب إدارية غير مسجلة... "
                         "(يُخصم من الربح العام)"))
        self._pages = {"trip": p_trip, "advance": p_adv, "vehicle": p_veh,
                       "supplier": p_sup, "purchase": p_pur, "owner": p_own,
                       "general": p_gen}
        for key in PAYMENT_TYPES:
            self.stack_lay.addWidget(self._pages[key])
        self.add_row("التوجيه", self.stack)

        self.qty_edit = AmountEdit(1)
        self.qty_edit.textChanged.connect(self._recalc)
        self.add_row("الكمية *", self.qty_edit)
        self.unit_edit = AmountEdit()
        self.unit_edit.textChanged.connect(self._recalc)
        self.add_row("قيمة الوحدة *", self.unit_edit)
        self.total_label = QLabel("0.00")
        self.total_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.add_row("إجمالي السند", self.total_label)
        self.desc_edit = QLineEdit()
        self.add_row("البيان / ملاحظات", self.desc_edit)

        if voucher_id:
            v = conn.execute("SELECT * FROM payment_vouchers WHERE id=?",
                             (voucher_id,)).fetchone()
            if v:
                self.number_label.setText(calc.voucher_number_label("PV", v["number"]))
                self.date_edit.set_iso(v["date"])
                self.account_combo.select(v["account_kind"], v["account_id"])
                idx = self.type_combo.findData(v["voucher_type"])
                self.type_combo.setCurrentIndex(idx if idx >= 0 else 0)
                self.trip_combo.select(v["trip_id"])
                self.employee_combo.select(v["employee_id"])
                self.vehicle_combo.select(v["vehicle_id"])
                self.supplier_combo.select(v["supplier_id"])
                self._load_supplier_invoices()
                self.purchase_combo.select(v["purchase_invoice_id"])
                vi = self.vehexp_combo.findData(v["vehicle_expense"] or "maintenance")
                self.vehexp_combo.setCurrentIndex(vi if vi >= 0 else 0)
                self.qty_edit.set_value(v["quantity"] or 1)
                self.unit_edit.set_value(v["unit_amount"] or v["amount"])
                self.desc_edit.setText(v["description"] or "")
        self._type_changed()
        self._recalc()
        if read_only:
            self.lock_fields()
            self.type_combo.setEnabled(True)
            self.stack.setEnabled(True)
            self.stack_lay.setCurrentWidget(self._pages[self.type_combo.currentData()])

    # ------------------------------------------------------------------
    def _load_supplier_invoices(self) -> None:
        conn = db.get_conn()
        sid = self.supplier_combo.selected_id()
        rows = repo.list_purchase_invoices(conn, supplier_id=sid) if sid else []
        self.purchase_combo.load(
            rows, mapper=lambda r: f"#{r['number']} | {r['date']} | "
                                   f"{fmt.money(r['total'])} | {r['supplier_ref'] or '—'}")

    def _recalc(self) -> None:
        total = float(self.qty_edit.value() or 0) * float(self.unit_edit.value() or 0)
        self.total_label.setText(fmt.money(total))

    def _type_changed(self) -> None:
        key = self.type_combo.currentData() or "general"
        self.stack_lay.setCurrentWidget(self._pages[key])

    def save(self) -> None:
        vt = self.type_combo.currentData()
        data = {
            "date": self.date_edit.iso(),
            "account_kind": self.account_combo.current_account()[0],
            "account_id": self.account_combo.current_account()[1],
            "voucher_type": vt,
            "trip_id": self.trip_combo.selected_id() if vt == "trip" else None,
            "employee_id": self.employee_combo.selected_id() if vt == "advance" else None,
            "vehicle_id": self.vehicle_combo.selected_id() if vt == "vehicle" else None,
            "vehicle_expense": self.vehexp_combo.currentData() if vt == "vehicle" else "",
            "supplier_id": self.supplier_combo.selected_id() if vt == "supplier" else None,
            "purchase_invoice_id": (self.purchase_combo.selected_id()
                                    if vt == "supplier" else None),
            "quantity": self.qty_edit.value(),
            "unit_amount": self.unit_edit.value(),
            "amount": round(self.qty_edit.value() * self.unit_edit.value(), 2),
            "description": _text(self.desc_edit.text()),
        }
        repo.save_payment(db.get_conn(), data, self.voucher_id)


# ===========================================================================
# إشعار دائن / مدين (بديل تعديل الفاتورة بعد إصدارها)
# ===========================================================================
class CreditDebitNoteDialog(FormDialog):
    """إشعار دائن (مرتجع نقلة أو خصم) أو إشعار مدين (إضافة على العميل)."""

    def __init__(self, parent=None, invoice_id: int | None = None):
        super().__init__(parent, "إشعار دائن / مدين", width=700)
        conn = db.get_conn()
        self.invoice_combo = DictCombo()
        self.invoice_combo.load(repo.list_invoices_raw(conn),
                                mapper=lambda r: f"#{r['number']} | {r['date']} | "
                                                 f"{r['customer_name']}")
        self.invoice_combo.currentIndexChanged.connect(self._load_trips)
        self.add_row("الفاتورة المرتبطة *", self.invoice_combo)
        self.type_combo = QComboBox()
        for key, label in NOTE_TYPES.items():
            self.type_combo.addItem(label, key)
        self.type_combo.currentIndexChanged.connect(self._type_changed)
        self.add_row("نوع الإشعار *", self.type_combo)
        self.date_edit = VDateEdit()
        self.add_row("التاريخ *", self.date_edit)
        self.reason_edit = QLineEdit()
        self.reason_edit.setPlaceholderText("إلزامي للمراجعة المحاسبية")
        self.add_row("سبب الإشعار *", self.reason_edit)

        self.trips_table = QTableWidget(0, 5)
        self.trips_table.setHorizontalHeaderLabels(
            ["✔", "من", "إلى", "القيمة", "شامل الضريبة"])
        self.trips_table.verticalHeader().setVisible(False)
        self.trips_table.setColumnWidth(0, 40)
        self.trips_table.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows)
        self.trips_table.setEditTriggers(
            QAbstractItemView.EditTrigger.NoEditTriggers)
        self.trips_label = QLabel("مرتجع نقلات: علّم النقلات المرتجعة")
        self.add_row(self.trips_label, self.trips_table)

        self.amount_edit = AmountEdit()
        self.add_row("مبلغ الإشعار (قبل الضريبة) *", self.amount_edit)
        self.vat_edit = AmountEdit(15)
        self.add_row("نسبة الضريبة %", self.vat_edit)

        if invoice_id:
            self.invoice_combo.select(invoice_id)
        self._load_trips()
        self._type_changed()

    # ------------------------------------------------------------------
    def _invoice_id(self):
        return self.invoice_combo.selected_id()

    def _load_trips(self) -> None:
        conn = db.get_conn()
        iid = self._invoice_id()
        self._trips = []
        if not iid:
            self.trips_table.setRowCount(0)
            return
        try:
            self._trips = repo.list_creditable_invoice_trips(conn, iid)
        except RuleError:
            self._trips = []
        self.trips_table.setRowCount(len(self._trips))
        for r, t in enumerate(self._trips):
            flag = QTableWidgetItem("")
            flag.setFlags(flag.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            flag.setCheckState(Qt.CheckState.Unchecked)
            if t["already_credited"]:
                flag.setFlags(flag.flags() & ~Qt.ItemFlag.ItemIsEnabled)
                flag.setToolTip("سبق إصدار إشعار دائن لهذه النقلة")
            self.trips_table.setItem(r, 0, flag)
            self.trips_table.setItem(r, 1, QTableWidgetItem(t["from_loc"] or "—"))
            self.trips_table.setItem(r, 2, QTableWidgetItem(t["to_loc"] or "—"))
            self.trips_table.setItem(r, 3, QTableWidgetItem(fmt.money(t["amount"])))
            self.trips_table.setItem(r, 4, QTableWidgetItem(fmt.money(t["total"])))
            if t["already_credited"]:
                for c in range(1, 5):
                    item = self.trips_table.item(r, c)
                    if item:
                        item.setText(f"{item.text()} (مرتجعة)")
        self._type_changed()

    def _type_changed(self) -> None:
        is_credit = self.type_combo.currentData() == "credit"
        has_trips = bool(getattr(self, "_trips", []))
        # الإشعار الدائن بمرتجع نقلات لا يحتاج مبلغاً يدوياً
        self.trips_table.setEnabled(is_credit and has_trips)
        self.trips_label.setVisible(is_credit)
        self.amount_edit.setEnabled(not (is_credit and has_trips))
        self.vat_edit.setEnabled(not (is_credit and has_trips))
        if is_credit and has_trips:
            total = sum(t["amount"] for t in self._trips
                        if self._checked(self._trips.index(t)))
            self.amount_edit.set_value(total)
        iid = self._invoice_id()
        if iid:
            conn = db.get_conn()
            inv = conn.execute("SELECT vat_rate FROM invoices WHERE id=?",
                               (iid,)).fetchone()
            if inv:
                self.vat_edit.set_value(inv["vat_rate"])

    def _checked(self, r: int) -> bool:
        item = self.trips_table.item(r, 0)
        return bool(item and item.checkState() == Qt.CheckState.Checked)

    def _selected_trip_ids(self) -> list[int]:
        return [t["id"] for r, t in enumerate(self._trips) if self._checked(r)]

    def save(self) -> None:
        conn = db.get_conn()
        iid = self._invoice_id()
        if not iid:
            raise RuleError("اختر الفاتورة المرتبطة.")
        customer_id = conn.execute(
            "SELECT customer_id FROM invoices WHERE id=?", (iid,)).fetchone()[0]
        data = {
            "note_type": self.type_combo.currentData(),
            "invoice_id": iid,
            "customer_id": customer_id,
            "date": self.date_edit.iso(),
            "reason": _text(self.reason_edit.text()),
            "amount": self.amount_edit.value(),
            "vat_rate": self.vat_edit.value(),
        }
        if self.trips_table.isEnabled():
            data["trip_ids"] = self._selected_trip_ids()
        repo.save_credit_debit_note(conn, data)
