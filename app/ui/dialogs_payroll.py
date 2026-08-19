# -*- coding: utf-8 -*-
"""قسم إدارة الرواتب: شاشة إصدار راتب مع السلفيات المتاحة والخصومات."""
from __future__ import annotations

from datetime import date

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView, QComboBox, QDialog, QDoubleSpinBox, QFormLayout, QGroupBox,
    QHBoxLayout, QHeaderView, QLabel, QLineEdit, QPlainTextEdit, QPushButton,
    QSpinBox, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from ..core import calc, db, repo
from ..core.rules import RuleError
from ..utils import fmt
from ..utils.fmt import MONTHS_AR
from .widgets import (
    AccountCombo, AmountEdit, DictCombo, VDateEdit, _row_button, error_msg, warn,
)


class PayrollDialog(QDialog):
    """إصدار/تعديل راتب: الأساسي + الإضافات − خصم السلف − خصومات أخرى = الصافي."""

    def __init__(self, parent=None, payroll_id: int | None = None,
                 read_only: bool = False):
        super().__init__(parent)
        self.payroll_id = payroll_id
        self.read_only = read_only
        self.setWindowTitle("إصدار راتب")
        self.resize(860, 640)
        conn = db.get_conn()

        root = QVBoxLayout(self)
        root.setContentsMargins(14, 12, 14, 12)
        root.setSpacing(10)

        head = QGroupBox("بيانات الراتب")
        hf = QFormLayout(head)
        hf.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        self.number_label = QLabel("تلقائي")
        hf.addRow("رقم الراتب", self.number_label)
        self.date_edit = VDateEdit()
        hf.addRow("تاريخ الصرف *", self.date_edit)
        self.employee_combo = DictCombo()
        self.employee_combo.load(repo.list_employees(conn))
        self.employee_combo.currentIndexChanged.connect(self._reload_advances)
        hf.addRow("الموظف / السائق *", self.employee_combo)
        pbox = QWidget()
        pl = QHBoxLayout(pbox)
        pl.setContentsMargins(0, 0, 0, 0)
        self.month_combo = QComboBox()
        for i, name in enumerate(MONTHS_AR, start=1):
            self.month_combo.addItem(name, i)
        self.year_spin = QSpinBox()
        self.year_spin.setRange(2000, 2200)
        self.year_spin.setValue(date.today().year)
        self.month_combo.setCurrentIndex(date.today().month - 1)
        pl.addWidget(QLabel("شهر"))
        pl.addWidget(self.month_combo)
        pl.addWidget(QLabel("سنة"))
        pl.addWidget(self.year_spin)
        hf.addRow("عن شهر *", pbox)
        self.account_combo = AccountCombo()
        self.account_combo.load(conn)
        hf.addRow("طريقة الصرف (من) *", self.account_combo)
        root.addWidget(head)

        money = QGroupBox("المستحقات والخصومات")
        mf = QFormLayout(money)
        mf.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        self.base_edit = AmountEdit()
        mf.addRow("الراتب الأساسي / المستحق *", self.base_edit)
        addbox = QWidget()
        al = QHBoxLayout(addbox)
        al.setContentsMargins(0, 0, 0, 0)
        self.additions_edit = AmountEdit()
        self.additions_note = QLineEdit()
        self.additions_note.setPlaceholderText("بيان الإضافات/المكافآت")
        al.addWidget(self.additions_edit, 1)
        al.addWidget(self.additions_note, 2)
        mf.addRow("إضافات / مكافآت", addbox)
        self.other_ded_edit = AmountEdit()
        mf.addRow("خصومات أخرى (غياب / جزاءات)", self.other_ded_edit)
        self.net_label = QLabel("0.00")
        self.net_label.setObjectName("totalValue")
        self.net_label.setStyleSheet("font-size:14pt; font-weight:bold; color:#1f4e79;")
        mf.addRow("صافي الراتب المنصرف (تلقائي)", self.net_label)
        self.notes_edit = QPlainTextEdit()
        self.notes_edit.setFixedHeight(50)
        mf.addRow("ملاحظات", self.notes_edit)
        root.addWidget(money)

        adv_box = QGroupBox("سجل السلفيات المتاحة (تلقائي) — حدد قيمة الخصم من كل سلفة")
        av = QVBoxLayout(adv_box)
        self.adv_table = QTableWidget(0, 6)
        self.adv_table.setHorizontalHeaderLabels(
            ["رقم السلفة", "تاريخها", "قيمتها", "المسدد سابقاً", "المتبقي", "الخصم الآن"])
        self.adv_table.verticalHeader().setVisible(False)
        self.adv_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.adv_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.adv_table.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.adv_table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.ResizeToContents)
        av.addWidget(self.adv_table)
        self.adv_total_label = QLabel("إجمالي خصم السلف: 0.00")
        self.adv_total_label.setObjectName("sectionLabel")
        av.addWidget(self.adv_total_label)
        root.addWidget(adv_box, 1)

        btns = QHBoxLayout()
        btns.addStretch(1)
        if read_only:
            close_btn = QPushButton("إغلاق")
            close_btn.clicked.connect(self.reject)
            btns.addWidget(close_btn)
        else:
            save_btn = QPushButton("💾 حفظ وصرف الراتب")
            save_btn.setObjectName("primary")
            save_btn.clicked.connect(self._try_save)
            cancel_btn = QPushButton("إلغاء")
            cancel_btn.clicked.connect(self.reject)
            btns.addWidget(save_btn)
            btns.addWidget(cancel_btn)
        root.addLayout(btns)

        for w in (self.base_edit, self.additions_edit, self.other_ded_edit):
            w.textChanged.connect(self._recalc)

        if payroll_id:
            self.load(conn, payroll_id)
        else:
            self._reload_advances()
        if read_only:
            self.lock()

    # ------------------------------------------------------------------
    def load(self, conn, payroll_id: int) -> None:
        p = repo.get_payroll(conn, payroll_id)
        if not p:
            return
        self.setWindowTitle(f"راتب رقم {calc.voucher_number_label('PAY', p['number'])}")
        self.number_label.setText(calc.voucher_number_label("PAY", p["number"]))
        self.date_edit.set_iso(p["date"])
        self.employee_combo.select(p["employee_id"])
        self.month_combo.setCurrentIndex(p["period_month"] - 1)
        self.year_spin.setValue(p["period_year"])
        self.account_combo.select(p["account_kind"], p["account_id"])
        self.base_edit.set_value(p["base_salary"])
        self.additions_edit.set_value(p["additions"])
        self.additions_note.setText(p["additions_note"] or "")
        self.other_ded_edit.set_value(p["other_deductions"])
        self.notes_edit.setPlainText(p["notes"] or "")
        self._reload_advances(preserved=settlement_map(p))

    def lock(self) -> None:
        for w in self.findChildren(QComboBox):
            w.setEnabled(False)
        for w in self.findChildren(QLineEdit):
            w.setReadOnly(True)
        self.date_edit.setEnabled(False)
        self.year_spin.setEnabled(False)
        self.base_edit.setReadOnly(True)
        self.additions_edit.setReadOnly(True)
        self.other_ded_edit.setReadOnly(True)
        self.notes_edit.setReadOnly(True)
        for r in range(self.adv_table.rowCount()):
            w = self.adv_table.cellWidget(r, 5)
            if w is None:
                continue
            if isinstance(w, QDoubleSpinBox):
                w.setEnabled(False)
            else:
                for sb in w.findChildren(QDoubleSpinBox):
                    sb.setEnabled(False)

    # ------------------------------------------------------------------
    def _reload_advances(self, *_args, preserved: dict | None = None) -> None:
        """تحميل سلف الموظف الحالية غير المسددة كلياً مع صناديق الخصم."""
        conn = db.get_conn()
        emp = self.employee_combo.selected_id()
        self.adv_table.setRowCount(0)
        self._adv_rows: list[dict] = []
        if not emp:
            self._recalc()
            return
        advances = repo.employee_advances(conn, emp, include_settled=False)
        preserved = preserved or {}
        for a in advances:
            r = len(self._adv_rows)
            self._adv_rows.append(a)
            self.adv_table.insertRow(r)
            vals = [calc.voucher_number_label("PV", a["number"]), a["date"],
                    fmt.money(a["amount"]), fmt.money(a["settled"]),
                    fmt.money(a["remaining"])]
            for c, v in enumerate(vals):
                item = QTableWidgetItem(str(v))
                item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                self.adv_table.setItem(r, c, item)
            sb = QDoubleSpinBox()
            sb.setRange(0.0, round(a["remaining"], 2))
            sb.setDecimals(2)
            sb.setSingleStep(50)
            sb.setAlignment(Qt.AlignmentFlag.AlignCenter)
            if a["id"] in preserved:
                sb.setValue(min(preserved[a["id"]], a["remaining"]))
            sb.valueChanged.connect(self._recalc)
            self.adv_table.setCellWidget(r, 5, sb)
        self._recalc()

    def _advance_deduction(self) -> float:
        total = 0.0
        for r in range(self.adv_table.rowCount()):
            w = self.adv_table.cellWidget(r, 5)
            if w is None:
                continue
            if isinstance(w, QDoubleSpinBox):
                total += w.value()
            else:
                for sb in w.findChildren(QDoubleSpinBox):
                    total += sb.value()
        return round(total, 2)

    def _recalc(self, *_args) -> None:
        net = (self.base_edit.value() + self.additions_edit.value()
               - self._advance_deduction() - self.other_ded_edit.value())
        self.net_label.setText(fmt.money(net))
        self.adv_total_label.setText(
            f"إجمالي خصم السلف: {fmt.money(self._advance_deduction())}")

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
        settlements = []
        for i, a in enumerate(getattr(self, "_adv_rows", [])):
            w = self.adv_table.cellWidget(i, 5)
            val = 0.0
            if isinstance(w, QDoubleSpinBox):
                val = round(w.value(), 2)
            elif w and w.findChildren(QDoubleSpinBox):
                val = round(w.findChildren(QDoubleSpinBox)[0].value(), 2)
            if val > 0:
                settlements.append((a["id"], val))
        data = {
            "date": self.date_edit.iso(),
            "employee_id": self.employee_combo.selected_id(),
            "period_year": self.year_spin.value(),
            "period_month": self.month_combo.currentData(),
            "account_kind": self.account_combo.current_account()[0],
            "account_id": self.account_combo.current_account()[1],
            "base_salary": self.base_edit.value(),
            "additions": self.additions_edit.value(),
            "additions_note": fmt.clean(self.additions_note.text()),
            "advance_deduction": self._advance_deduction(),
            "other_deductions": self.other_ded_edit.value(),
            "notes": self.notes_edit.toPlainText().strip(),
            "settlements": settlements,
        }
        repo.save_payroll(db.get_conn(), data, self.payroll_id)


def settlement_map(payroll: dict) -> dict[int, float]:
    """خريطة (معرّف السلفة -> المبلغ المخصوم) لراتب قائم."""
    return {s["payment_voucher_id"]: s["amount"] for s in payroll.get("settlements", [])}
