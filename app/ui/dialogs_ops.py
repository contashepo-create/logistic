# -*- coding: utf-8 -*-
"""نوافذ العمليات اليومية: فاتورة النقل (رأس + نقلات + مصروفات + مرفقات)،
سندات القبض، سندات الدفع، وطباعة فاتورة العميل الرسمية."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QAbstractItemView, QComboBox, QDialog, QFileDialog, QFormLayout, QGroupBox,
    QHBoxLayout, QHeaderView, QLabel, QLineEdit, QListWidget, QListWidgetItem,
    QPushButton, QStackedLayout, QTableWidget, QTableWidgetItem, QVBoxLayout,
    QWidget,
)

from ..core import calc, db, repo
from ..core.rules import RuleError
from ..utils import exporter, fmt
from ..utils.fmt import EXPENSE_TYPES, PAYMENT_TYPES, RECEIPT_TYPES, VEHICLE_EXPENSES
from .widgets import (
    AccountCombo, AmountEdit, DictCombo, FormDialog, TotalsBar, VDateEdit,
    _row_button, error_msg, warn,
)


def _text(s) -> str:
    return fmt.clean(s)


# ===========================================================================
# فاتورة النقل
# ===========================================================================
class TripDialog(FormDialog):
    """إضافة/تعديل نقلة داخل الفاتورة."""

    def __init__(self, parent=None, trip: dict | None = None):
        super().__init__(parent, "بيانات النقلة", width=520)
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
        self.price_edit = AmountEdit()
        self.add_row("سعر النقلة للعميل *", self.price_edit)
        self.notes_edit = QLineEdit()
        self.add_row("ملاحظات", self.notes_edit)

        if trip:
            self.vehicle_combo.select(trip.get("vehicle_id"))
            self.driver_combo.select(trip.get("driver_id"))
            self.from_edit.setText(trip.get("from_loc", ""))
            self.to_edit.setText(trip.get("to_loc", ""))
            self.price_edit.set_value(trip.get("price", 0))
            self.notes_edit.setText(trip.get("notes", ""))

    def data(self) -> dict:
        return {
            "vehicle_id": self.vehicle_combo.selected_id(),
            "driver_id": self.driver_combo.selected_id(),
            "from_loc": _text(self.from_edit.text()),
            "to_loc": _text(self.to_edit.text()),
            "price": self.price_edit.value(),
            "notes": _text(self.notes_edit.text()),
            "expenses": [],
        }


class ExpenseDialog(FormDialog):
    """إضافة مصروف لنقلة (تريب / بنزين / كارتة / أخرى)."""

    def __init__(self, parent=None, expense: dict | None = None):
        super().__init__(parent, "مصروف النقلة", width=440)
        self.type_combo = QComboBox()
        for key, label in EXPENSE_TYPES.items():
            self.type_combo.addItem(label, key)
        self.add_row("نوع المصروف *", self.type_combo)
        self.amount_edit = AmountEdit()
        self.add_row("المبلغ *", self.amount_edit)
        self.notes_edit = QLineEdit()
        self.add_row("بيان", self.notes_edit)
        if expense:
            idx = self.type_combo.findData(expense.get("expense_type", "other"))
            self.type_combo.setCurrentIndex(idx if idx >= 0 else 0)
            self.amount_edit.set_value(expense.get("amount", 0))
            self.notes_edit.setText(expense.get("notes", ""))

    def data(self) -> dict:
        return {
            "expense_type": self.type_combo.currentData(),
            "amount": self.amount_edit.value(),
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

        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["النوع", "المبلغ", "البيان", "العمليات"])
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.table.horizontalHeader().setSectionResizeMode(
            2, QHeaderView.ResizeMode.Stretch)
        root.addWidget(self.table, 1)

        close_btn = QPushButton("تم")
        close_btn.clicked.connect(self.accept)
        root.addWidget(close_btn, 0, Qt.AlignmentFlag.AlignLeft)
        self.refresh()

    def refresh(self) -> None:
        expenses = self.trip.get("expenses", [])
        self.table.setRowCount(len(expenses))
        for r, e in enumerate(expenses):
            for c, val in enumerate([EXPENSE_TYPES.get(e["expense_type"], "—"),
                                     fmt.money(e["amount"]), e.get("notes", "")]):
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
            self.table.setCellWidget(r, 3, w)

    def add_expense(self) -> None:
        dlg = ExpenseDialog(self)
        if dlg.exec():
            self.trip.setdefault("expenses", []).append(dlg.data())
            self.refresh()

    def edit_expense(self, r: int) -> None:
        expenses = self.trip.get("expenses", [])
        if not (0 <= r < len(expenses)):
            return
        dlg = ExpenseDialog(self, expenses[r])
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
        self.setWindowTitle("فاتورة نقل" if not invoice_id else "تعديل فاتورة نقل")
        self.resize(1020, 680)
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
        self.notes_edit = QLineEdit()
        self.number_label = QLabel("تلقائي")
        hf.addRow("رقم الفاتورة", self.number_label)
        hf.addRow("التاريخ (داخل السنة المالية) *", self.date_edit)
        hf.addRow("العميل *", self.customer_combo)
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

        self.trips_table = QTableWidget(0, 8)
        self.trips_table.setHorizontalHeaderLabels(
            ["م", "السيارة", "السائق", "من", "إلى", "السعر للعميل",
             "مصروفاتها", "العمليات"])
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
        self.totals = TotalsBar(["إجمالي قيمة النقلات", "إجمالي المصروفات المباشرة",
                                 "الربح المتوقع"])
        root.addWidget(self.totals)

        # --- أزرار الحفظ ---
        btns = QHBoxLayout()
        btns.addStretch(1)
        if read_only:
            print_btn = QPushButton("🖨️ طباعة فاتورة العميل")
            print_btn.setObjectName("primary")
            print_btn.clicked.connect(lambda: print_customer_invoice(self, self.invoice_id))
            btns.addWidget(print_btn)
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
        if read_only:
            self.lock()

    # ------------------------------------------------------------------
    def load_invoice(self, conn, invoice_id: int) -> None:
        d = calc.get_invoice_full(conn, invoice_id)
        if not d:
            return
        self.setWindowTitle(f"فاتورة نقل {calc.invoice_number_label(d['number'])}")
        self.number_label.setText(calc.invoice_number_label(d["number"]))
        self.date_edit.set_iso(d["date"])
        self.customer_combo.select(d["customer_id"])
        self.notes_edit.setText(d.get("notes", "") or "")
        import json
        self.attachments = list(json.loads(d.get("attachments", "[]") or []))
        self.trips = [dict(t) for t in d["trips"]]
        self.refresh()

    def lock(self) -> None:
        self.date_edit.setEnabled(False)
        self.customer_combo.setEnabled(False)
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
            exp_sum = sum(e["amount"] for e in t.get("expenses", []))
            vals = [str(r + 1),
                    vehicles.get(t.get("vehicle_id"), "—"),
                    drivers.get(t.get("driver_id"), "—"),
                    t.get("from_loc", ""), t.get("to_loc", ""),
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
            self.trips_table.setCellWidget(r, 7, w)

        self.att_list.clear()
        for rel in self.attachments:
            QListWidgetItem(Path(rel).name, self.att_list)

        trips_total = sum(t.get("price", 0) for t in self.trips)
        exp_total = sum(e["amount"] for t in self.trips for e in t.get("expenses", []))
        self.totals.set_value("إجمالي قيمة النقلات", trips_total)
        self.totals.set_value("إجمالي المصروفات المباشرة", exp_total)
        self.totals.set_value("الربح المتوقع", trips_total - exp_total)

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
            "notes": self.notes_edit.text().strip(),
            "attachments": self.attachments,
            "trips": self.trips,
        }
        repo.save_invoice(db.get_conn(), data, self.invoice_id)


# ---------------------------------------------------------------------------
# طباعة فاتورة العميل الرسمية (بدون مصروفات وبدون أرباح داخلية)
# ---------------------------------------------------------------------------
def customer_invoice_html(conn, invoice_id: int) -> str:
    d = calc.get_invoice_full(conn, invoice_id)
    if not d:
        return ""
    info = repo.company_info(conn)
    cur = info.get("currency", "")
    rows_html = []
    for i, t in enumerate(d["trips"], start=1):
        vehicle = "—"
        if t.get("vehicle_id"):
            v = repo.get_vehicle(conn, t["vehicle_id"])
            vehicle = v["plate_number"] if v else "—"
        driver = "—"
        if t.get("driver_id"):
            e = repo.get_employee(conn, t["driver_id"])
            driver = e["name"] if e else "—"
        rows_html.append(
            f"<tr><td align='center'>{i}</td>"
            f"<td align='center'>{exporter._esc(t.get('from_loc') or '—')}</td>"
            f"<td align='center'>{exporter._esc(t.get('to_loc') or '—')}</td>"
            f"<td align='center'>{exporter._esc(vehicle)}</td>"
            f"<td align='center'>{exporter._esc(driver)}</td>"
            f"<td align='center'>{fmt.money(t.get('price', 0))}</td></tr>")
    total = d["customer_total"]
    parts = [
        f"<div align='center'><b style='font-size:18pt'>"
        f"{exporter._esc(info['company_name'])}</b></div>",
    ]
    contact = " | ".join(x for x in (info.get("company_phone"),
                                     info.get("company_address")) if x)
    if contact:
        parts.append(f"<div align='center'>{exporter._esc(contact)}</div>")
    parts += [
        "<hr>",
        f"<div align='center' style='font-size:15pt'><b>فاتورة نقل</b></div>",
        "<table dir='rtl' width='100%' cellspacing='6' style='font-size:11pt'>"
        f"<tr><td align='right'><b>رقم الفاتورة:</b> "
        f"{calc.invoice_number_label(d['number'])}</td>"
        f"<td align='left'><b>التاريخ:</b> {d['date']}</td></tr>"
        f"<tr><td align='right'><b>العميل:</b> "
        f"{exporter._esc(d['customer']['name'])} ({d['customer']['code']})</td>"
        f"<td align='left'><b>الهاتف:</b> "
        f"{exporter._esc(d['customer'].get('phone') or '—')}</td></tr></table>",
        "<table dir='rtl' width='100%' border='0.5' cellspacing='0' "
        "cellpadding='5' style='font-size:10.5pt'>",
        "<tr bgcolor='#1f4e79'><td align='center'><b><font color='white'>م</font></b></td>"
        "<td align='center'><b><font color='white'>من</font></b></td>"
        "<td align='center'><b><font color='white'>إلى</font></b></td>"
        "<td align='center'><b><font color='white'>السيارة</font></b></td>"
        "<td align='center'><b><font color='white'>السائق</font></b></td>"
        "<td align='center'><b><font color='white'>السعر</font></b></td></tr>",
        *rows_html,
        f"<tr bgcolor='#e9f0f8'><td colspan='5' align='center'>"
        f"<b>الإجمالي المستحق {exporter._esc(cur)}</b></td>"
        f"<td align='center'><b>{fmt.money(total)}</b></td></tr>",
        "</table>",
    ]
    if d.get("notes"):
        parts.append(f"<div align='right' style='font-size:10pt'><b>ملاحظات:</b> "
                     f"{exporter._esc(d['notes'])}</div>")
    note = repo.get_setting(conn, "company_vat_note", "")
    if note:
        parts.append(f"<br><div align='center' style='font-size:9.5pt'>"
                     f"{exporter._esc(note)}</div>")
    return "".join(parts)


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
    def __init__(self, parent=None, voucher_id: int | None = None,
                 read_only: bool = False):
        super().__init__(parent, "سند دفع", read_only, width=620)
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
        self.type_combo.currentIndexChanged.connect(
            lambda _: self.stack.setCurrentIndex(self.type_combo.currentIndex()))
        self.add_row("النوع والتوجيه *", self.type_combo)

        # صفوف التوجيه حسب النوع
        self.stack = QWidget()
        self.stack_lay = QStackedLayout(self.stack)
        # 1) مصروف يخص رحلة
        p_trip = QWidget()
        f1 = QFormLayout(p_trip)
        self.trip_combo = DictCombo()
        self.trip_combo.load(calc.trips_options(conn),
                             mapper=lambda r: r["label"])
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
        # 4) مصروف عام
        p_gen = QWidget()
        f4 = QFormLayout(p_gen)
        f4.addRow(QLabel("مثال: إيجار، كهرباء، رواتب إدارية غير مسجلة... "
                         "(يُخصم من الربح العام)"))
        for p in (p_trip, p_adv, p_veh, p_gen):
            self.stack_lay.addWidget(p)
        self.add_row("التوجيه", self.stack)

        self.amount_edit = AmountEdit()
        self.add_row("المبلغ *", self.amount_edit)
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
                vi = self.vehexp_combo.findData(v["vehicle_expense"] or "maintenance")
                self.vehexp_combo.setCurrentIndex(vi if vi >= 0 else 0)
                self.amount_edit.set_value(v["amount"])
                self.desc_edit.setText(v["description"] or "")
        if read_only:
            self.lock_fields()
            self.stack.setEnabled(True)
            self._lock_stack()
            self.type_combo.setEnabled(True)

    def _lock_stack(self) -> None:
        idx = self.type_combo.currentIndex()
        self.stack_lay.setCurrentIndex(idx)

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
            "amount": self.amount_edit.value(),
            "description": _text(self.desc_edit.text()),
        }
        repo.save_payment(db.get_conn(), data, self.voucher_id)
