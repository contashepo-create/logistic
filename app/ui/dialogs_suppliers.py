# -*- coding: utf-8 -*-
"""نوافذ دورة الموردين: بيانات المورّد (بالحزمة الضريبية) وفاتورة المشتريات."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView, QCheckBox, QComboBox, QFormLayout, QGroupBox, QHBoxLayout,
    QHeaderView, QLabel, QLineEdit, QPushButton, QTableWidget, QTableWidgetItem,
    QVBoxLayout, QWidget,
)

from PySide6.QtWidgets import QDialog

from ..core import calc, db, repo, tax
from ..core.rules import RuleError
from ..utils import fmt
from ..utils.fmt import PURCHASE_EXPENSE_CATEGORIES
from .widgets import (
    AccountCombo, AmountEdit, DictCombo, FormDialog, VDateEdit, _row_button,
    install_row_actions, make_actions_widget, warn,
)


def _text(s) -> str:
    return fmt.clean(s)


# ===========================================================================
# المورّد
# ===========================================================================
class SupplierDialog(FormDialog):
    """بيانات المورّد: الاتصال + الرصيد الافتتاحي + الحزمة الضريبية والعنوان الوطني."""

    def __init__(self, parent=None, supplier_id: int | None = None,
                 read_only: bool = False):
        super().__init__(parent, "بيانات المورّد", read_only, width=680)
        self.supplier_id = supplier_id
        conn = db.get_conn()
        self.code_label = QLabel("تلقائي")
        self.add_row("كود المورّد", self.code_label)
        self.name_edit = QLineEdit()
        self.add_row("اسم المورّد *", self.name_edit)
        self.name_en_edit = QLineEdit()
        self.add_row("الاسم بالإنجليزية", self.name_en_edit)
        self.phone_edit = QLineEdit()
        self.add_row("رقم الهاتف", self.phone_edit)
        self.email_edit = QLineEdit()
        self.add_row("البريد الإلكتروني", self.email_edit)
        self.contact_edit = QLineEdit()
        self.add_row("الشخص المسؤول", self.contact_edit)
        self.address_edit = QLineEdit()
        self.add_row("العنوان", self.address_edit)
        self.opening_edit = AmountEdit()
        self.opening_edit.setToolTip("موجب = مستحق له علينا")
        self.add_row("الرصيد الافتتاحي", self.opening_edit)
        self.terms_edit = AmountEdit(0)
        self.add_row("مدة السداد (أيام)", self.terms_edit)
        self.balance_label = QLabel("0.00")
        self.balance_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.add_row("الرصيد الحالي (تلقائي)", self.balance_label)
        self.notes_edit = QLineEdit()
        self.add_row("ملاحظات", self.notes_edit)

        # --- الحزمة الضريبية والعنوان الوطني ---
        self.tax_number_edit = QLineEdit()
        self.tax_number_edit.setPlaceholderText("15 رقماً يبدأ وينتهي بـ 3")
        self.add_row("الرقم الضريبي", self.tax_number_edit)
        self.cr_edit = QLineEdit()
        self.cr_edit.setPlaceholderText("10 أرقام")
        self.add_row("السجل التجاري", self.cr_edit)
        self.entity_combo = QComboBox()
        for key, label in tax.ENTITY_TYPES.items():
            self.entity_combo.addItem(label, key)
        self.add_row("نوع الكيان", self.entity_combo)
        self.status_combo = QComboBox()
        for key, label in tax.TAX_STATUSES.items():
            self.status_combo.addItem(label, key)
        self.add_row("الحالة الضريبية", self.status_combo)
        self.country_combo = QComboBox()
        for key, label in tax.COUNTRIES.items():
            self.country_combo.addItem(label, key)
        self.add_row("الدولة", self.country_combo)
        self.region_combo = QComboBox()
        self.region_combo.addItem("— اختر —", "")
        for region in tax.SA_REGIONS:
            self.region_combo.addItem(region, region)
        self.add_row("المنطقة", self.region_combo)
        self.city_edit = QLineEdit()
        self.add_row("المدينة", self.city_edit)
        self.district_edit = QLineEdit()
        self.add_row("الحي", self.district_edit)
        self.street_edit = QLineEdit()
        self.add_row("الشارع", self.street_edit)
        self.building_edit = QLineEdit()
        self.building_edit.setPlaceholderText("4 أرقام")
        self.add_row("رقم المبنى", self.building_edit)
        self.postal_edit = QLineEdit()
        self.postal_edit.setPlaceholderText("5 أرقام")
        self.add_row("الرمز البريدي", self.postal_edit)
        self.additional_edit = QLineEdit()
        self.additional_edit.setPlaceholderText("4 أرقام")
        self.add_row("الرقم الإضافي", self.additional_edit)

        if supplier_id:
            row = repo.get_supplier(conn, supplier_id)
            if row:
                d = dict(row)
                self.code_label.setText(d["code"])
                self.name_edit.setText(d["name"])
                self.name_en_edit.setText(d.get("name_en") or "")
                self.phone_edit.setText(d.get("phone") or "")
                self.email_edit.setText(d.get("email") or "")
                self.contact_edit.setText(d.get("contact_person") or "")
                self.address_edit.setText(d.get("address") or "")
                self.opening_edit.set_value(d.get("opening_balance", 0))
                self.terms_edit.set_value(d.get("payment_terms", 0))
                self.notes_edit.setText(d.get("notes") or "")
                self.balance_label.setText(
                    fmt.money(calc.supplier_balance(conn, supplier_id)))
                self.tax_number_edit.setText(d.get("tax_number") or "")
                self.cr_edit.setText(d.get("commercial_reg") or "")
                for combo, value in ((self.entity_combo, d.get("entity_type")),
                                     (self.status_combo, d.get("tax_status")),
                                     (self.country_combo, d.get("country")),
                                     (self.region_combo, d.get("region"))):
                    i = combo.findData(value)
                    combo.setCurrentIndex(i if i >= 0 else 0)
                self.city_edit.setText(d.get("city") or "")
                self.district_edit.setText(d.get("district") or "")
                self.street_edit.setText(d.get("street") or "")
                self.building_edit.setText(d.get("building_no") or "")
                self.postal_edit.setText(d.get("postal_code") or "")
                self.additional_edit.setText(d.get("additional_no") or "")
        if read_only:
            self.lock_fields()

    def save(self) -> None:
        data = {
            "name": _text(self.name_edit.text()),
            "name_en": _text(self.name_en_edit.text()),
            "phone": _text(self.phone_edit.text()),
            "email": _text(self.email_edit.text()),
            "contact_person": _text(self.contact_edit.text()),
            "address": _text(self.address_edit.text()),
            "opening_balance": self.opening_edit.value(),
            "payment_terms": self.terms_edit.value(),
            "notes": _text(self.notes_edit.text()),
            "tax_number": _text(self.tax_number_edit.text()),
            "commercial_reg": _text(self.cr_edit.text()),
            "entity_type": self.entity_combo.currentData(),
            "tax_status": self.status_combo.currentData(),
            "country": self.country_combo.currentData(),
            "region": self.region_combo.currentData(),
            "city": _text(self.city_edit.text()),
            "district": _text(self.district_edit.text()),
            "street": _text(self.street_edit.text()),
            "building_no": _text(self.building_edit.text()),
            "postal_code": _text(self.postal_edit.text()),
            "additional_no": _text(self.additional_edit.text()),
        }
        repo.save_supplier(db.get_conn(), data, self.supplier_id)


# ===========================================================================
# فاتورة المشتريات (رأس + بنود)
# ===========================================================================
class PurchaseItemDialog(FormDialog):
    def __init__(self, parent=None, item: dict | None = None, default_vat: float = 15):
        super().__init__(parent, "بند مشتريات", width=480)
        self.name_edit = QLineEdit()
        self.add_row("اسم الصنف *", self.name_edit)
        self.unit_edit = QLineEdit()
        self.add_row("الوحدة", self.unit_edit)
        self.qty_edit = AmountEdit(1)
        self.qty_edit.textChanged.connect(self._recalc)
        self.add_row("الكمية *", self.qty_edit)
        self.price_edit = AmountEdit()
        self.price_edit.textChanged.connect(self._recalc)
        self.add_row("سعر الوحدة *", self.price_edit)
        self.vat_edit = AmountEdit(default_vat)
        self.vat_edit.setToolTip("تسمح ببنود معفاة داخل نفس الفاتورة")
        self.add_row("نسبة ضريبة البند %", self.vat_edit)
        self.total_label = QLabel("0.00")
        self.total_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.add_row("الإجمالي", self.total_label)
        self.notes_edit = QLineEdit()
        self.add_row("ملاحظات", self.notes_edit)
        if item:
            self.name_edit.setText(item.get("item_name", ""))
            self.unit_edit.setText(item.get("unit", ""))
            self.qty_edit.set_value(item.get("qty", 1))
            self.price_edit.set_value(item.get("unit_price", 0))
            self.vat_edit.set_value(item.get("vat_rate", default_vat))
            self.notes_edit.setText(item.get("notes", ""))
        self._recalc()

    def _recalc(self) -> None:
        self.total_label.setText(
            fmt.money(float(self.qty_edit.value() or 0)
                      * float(self.price_edit.value() or 0)))

    def data(self) -> dict:
        return {
            "item_name": _text(self.name_edit.text()),
            "unit": _text(self.unit_edit.text()),
            "qty": self.qty_edit.value(),
            "unit_price": self.price_edit.value(),
            "vat_rate": self.vat_edit.value(),
            "notes": _text(self.notes_edit.text()),
        }


class PurchaseInvoiceDialog(QDialog):
    """فاتورة مشتريات: نقدية (سند دفع تلقائي) أو آجلة (على حساب المورّد)."""

    def __init__(self, parent=None, invoice_id: int | None = None,
                 read_only: bool = False):
        super().__init__(parent)
        self.invoice_id = invoice_id
        self.read_only = read_only
        self.items: list[dict] = []
        conn = db.get_conn()
        self.setWindowTitle("فاتورة مشتريات" if not invoice_id else "فاتورة مشتريات (عرض)")
        self.resize(900, 620)
        root = QVBoxLayout(self)
        root.setContentsMargins(14, 12, 14, 12)
        root.setSpacing(10)

        head = QGroupBox("رأس الفاتورة")
        hf = QFormLayout(head)
        hf.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        self.number_label = QLabel("تلقائي")
        self.date_edit = VDateEdit()
        self.type_combo = QComboBox()
        self.type_combo.addItem("آجلة (على حساب المورّد)", "credit")
        self.type_combo.addItem("نقدية (تُدفع فوراً)", "cash")
        self.type_combo.currentIndexChanged.connect(self._type_changed)
        self.supplier_combo = DictCombo()
        self.supplier_combo.load(repo.list_suppliers(conn))
        self.account_combo = AccountCombo()
        self.account_combo.load(conn)
        self.ref_edit = QLineEdit()
        self.ref_edit.setPlaceholderText("رقم فاتورة المورّد")
        self.category_combo = QComboBox()
        for key, label in PURCHASE_EXPENSE_CATEGORIES.items():
            self.category_combo.addItem(label, key)
        self.vehicle_combo = DictCombo()
        self.vehicle_combo.load(repo.list_vehicles(conn),
                                mapper=lambda r: f"{r['code']} - {r['plate_number']}")
        self.vat_edit = AmountEdit(15)
        self.included_check = QCheckBox("الأسعار شاملة الضريبة")
        self.included_check.toggled.connect(self.refresh)
        self.notes_edit = QLineEdit()
        hf.addRow("رقم الفاتورة", self.number_label)
        hf.addRow("التاريخ *", self.date_edit)
        hf.addRow("نوع الفاتورة *", self.type_combo)
        hf.addRow("المورّد (للآجلة) *", self.supplier_combo)
        hf.addRow("جهة الدفع (للنقدية) *", self.account_combo)
        hf.addRow("مرجع المورّد", self.ref_edit)
        hf.addRow("بند المصروف في الأرباح والخسائر *", self.category_combo)
        hf.addRow("السيارة (اختياري)", self.vehicle_combo)
        hf.addRow("نسبة الضريبة الافتراضية %", self.vat_edit)
        hf.addRow("", self.included_check)
        hf.addRow("ملاحظات", self.notes_edit)
        root.addWidget(head)

        items_box = QGroupBox("بنود الفاتورة")
        iv = QVBoxLayout(items_box)
        bar = QHBoxLayout()
        self.add_btn = QPushButton("➕ إضافة بند")
        self.add_btn.setObjectName("primary")
        self.add_btn.clicked.connect(self.add_item)
        bar.addWidget(self.add_btn)
        bar.addStretch(1)
        iv.addLayout(bar)
        self.table = QTableWidget(0, 7)
        self.table.setHorizontalHeaderLabels(
            ["الصنف", "الوحدة", "الكمية", "سعر الوحدة", "ضريبة البند %",
             "الإجمالي", "العمليات"])
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeMode.Stretch)
        # عمود العمليات بعرض محسوب (زر أو زرين حسب الوضع)
        install_row_actions(self.table, 6, n_buttons=2)
        iv.addWidget(self.table, 1)
        root.addWidget(items_box, 1)

        from .widgets import TotalsBar
        self.totals = TotalsBar(["الإجمالي قبل الضريبة", "ضريبة القيمة المضافة",
                                 "الإجمالي شامل الضريبة"])
        root.addWidget(self.totals)

        btns = QHBoxLayout()
        btns.addStretch(1)
        if read_only:
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
            self._load(conn, invoice_id)
        self._type_changed()
        self.refresh()
        if read_only:
            self._lock()

    # ------------------------------------------------------------------
    def _load(self, conn, invoice_id: int) -> None:
        d = repo.get_purchase_invoice(conn, invoice_id)
        if not d:
            return
        self.setWindowTitle(f"فاتورة مشتريات #{d['number']}")
        self.number_label.setText(f"#{d['number']}")
        self.date_edit.set_iso(d["date"])
        i = self.type_combo.findData(d["purchase_type"])
        self.type_combo.setCurrentIndex(i if i >= 0 else 0)
        self.supplier_combo.select(d["supplier_id"])
        self.account_combo.select(d["account_kind"], d["account_id"])
        self.ref_edit.setText(d.get("supplier_ref") or "")
        ci = self.category_combo.findData(d["expense_category"])
        self.category_combo.setCurrentIndex(ci if ci >= 0 else 0)
        self.vehicle_combo.select(d["vehicle_id"])
        self.vat_edit.set_value(d["vat_rate"])
        self.included_check.setChecked(bool(d["vat_included"]))
        self.notes_edit.setText(d.get("notes") or "")
        self.items = [dict(it) for it in d["items"]]

    def _lock(self) -> None:
        for w in (self.date_edit, self.type_combo, self.supplier_combo,
                  self.account_combo, self.ref_edit, self.category_combo,
                  self.vehicle_combo, self.vat_edit, self.included_check):
            w.setEnabled(False)
        self.notes_edit.setReadOnly(True)
        self.add_btn.setEnabled(False)

    def _type_changed(self) -> None:
        is_cash = self.type_combo.currentData() == "cash"
        self.supplier_combo.setEnabled(not is_cash)
        self.account_combo.setEnabled(is_cash)

    # ------------------------------------------------------------------
    def refresh(self) -> None:
        self.table.setRowCount(len(self.items))
        for r, it in enumerate(self.items):
            self.table.setRowHeight(r, 44)
            gross = float(it.get("qty", 0) or 0) * float(it.get("unit_price", 0) or 0)
            vals = [it.get("item_name", ""), it.get("unit", "") or "—",
                    fmt.money(it.get("qty", 1)), fmt.money(it.get("unit_price", 0)),
                    fmt.money(it.get("vat_rate", 0)), fmt.money(gross)]
            for c, v in enumerate(vals):
                item = QTableWidgetItem(str(v))
                item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                self.table.setItem(r, c, item)
            buttons = []
            if not self.read_only:
                buttons.append(_row_button(
                    "✏", "تعديل", "rowBtnEdit",
                    lambda _=False, x=r: self.edit_item(x)))
                buttons.append(_row_button(
                    "🗑", "حذف", "rowBtnDanger",
                    lambda _=False, x=r: self.del_item(x)))
            self.table.setCellWidget(r, 6, make_actions_widget(buttons))
        totals = calc.purchase_totals(self.items, self.included_check.isChecked())
        self.totals.set_value("الإجمالي قبل الضريبة", totals["net"])
        self.totals.set_value("ضريبة القيمة المضافة", totals["vat"])
        self.totals.set_value("الإجمالي شامل الضريبة", totals["total"])

    def add_item(self) -> None:
        dlg = PurchaseItemDialog(self, default_vat=self.vat_edit.value())
        if dlg.exec():
            self.items.append(dlg.data())
            self.refresh()

    def edit_item(self, r: int) -> None:
        if not (0 <= r < len(self.items)):
            return
        dlg = PurchaseItemDialog(self, self.items[r], self.vat_edit.value())
        if dlg.exec():
            self.items[r].update(dlg.data())
            self.refresh()

    def del_item(self, r: int) -> None:
        if 0 <= r < len(self.items):
            self.items.pop(r)
            self.refresh()

    # ------------------------------------------------------------------
    def _try_save(self) -> None:
        try:
            kind, acc = self.account_combo.current_account()
            repo.save_purchase_invoice(db.get_conn(), {
                "date": self.date_edit.iso(),
                "purchase_type": self.type_combo.currentData(),
                "supplier_id": self.supplier_combo.selected_id(),
                "supplier_ref": _text(self.ref_edit.text()),
                "expense_category": self.category_combo.currentData(),
                "vehicle_id": self.vehicle_combo.selected_id(),
                "account_kind": kind,
                "account_id": acc,
                "vat_rate": self.vat_edit.value(),
                "vat_included": self.included_check.isChecked(),
                "notes": _text(self.notes_edit.text()),
                "items": self.items,
            }, self.invoice_id)
        except (RuleError, ValueError) as e:
            warn(self, str(e))
            return
        self.accept()
