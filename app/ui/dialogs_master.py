# -*- coding: utf-8 -*-
"""نوافذ البيانات الأساسية: عملاء، موظفون، سيارات، سنوات مالية، خزائن، بنوك، لقطة الإغلاق."""
from __future__ import annotations

from datetime import date

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox, QDialog, QLabel, QLineEdit, QPlainTextEdit, QPushButton,
    QSpinBox, QTabWidget, QVBoxLayout, QWidget,
)

from ..core import calc, db, repo
from ..utils import exporter, fmt
from ..utils.fmt import money as m
from .widgets import (
    AmountEdit, DictCombo, ExportBar, FormDialog, PlainTable, VDateEdit, info,
    warn,
)


def _text(s) -> str:
    return fmt.clean(s)


# ---------------------------------------------------------------------------
# العملاء
# ---------------------------------------------------------------------------
class CustomerDialog(FormDialog):
    def __init__(self, parent=None, customer_id: int | None = None,
                 read_only: bool = False):
        super().__init__(parent, "بيانات العميل", read_only, width=560)
        self.customer_id = customer_id
        conn = db.get_conn()
        self.name_edit = QLineEdit()
        self.add_row("اسم العميل *", self.name_edit)
        self.phone_edit = QLineEdit()
        self.phone_edit.setPlaceholderText("يُحفظ كنص للحفاظ على الأصفار والأكواد")
        self.add_row("رقم الهاتف", self.phone_edit)
        self.address_edit = QLineEdit()
        self.add_row("العنوان", self.address_edit)
        self.opening_edit = AmountEdit()
        self.add_row("الرصيد الافتتاحي", self.opening_edit)
        self.notes_edit = QPlainTextEdit()
        self.notes_edit.setFixedHeight(70)
        self.add_row("ملاحظات / بيانات إضافية", self.notes_edit)
        self.balance_label = QLabel("—")
        self.balance_label.setObjectName("totalValue")
        self.add_row("الرصيد الحالي (تلقائي)", self.balance_label)

        if customer_id:
            c = repo.get_customer(conn, customer_id)
            if c:
                self.setWindowTitle(f"بيانات العميل {c['code']}")
                self.name_edit.setText(c["name"])
                self.phone_edit.setText(c["phone"] or "")
                self.address_edit.setText(c["address"] or "")
                self.opening_edit.set_value(c["opening_balance"])
                self.notes_edit.setPlainText(c["notes"] or "")
                self.balance_label.setText(fmt.money(calc.customer_balance(conn, customer_id)))
        if read_only:
            self.lock_fields()

    def save(self) -> None:
        data = {
            "name": _text(self.name_edit.text()),
            "phone": _text(self.phone_edit.text()),
            "address": _text(self.address_edit.text()),
            "opening_balance": self.opening_edit.value(),
            "notes": self.notes_edit.toPlainText().strip(),
        }
        repo.save_customer(db.get_conn(), data, self.customer_id)


# ---------------------------------------------------------------------------
# الموظفون والسائقون
# ---------------------------------------------------------------------------
class EmployeeDialog(FormDialog):
    def __init__(self, parent=None, employee_id: int | None = None,
                 read_only: bool = False):
        super().__init__(parent, "بيانات الموظف", read_only, width=520)
        self.employee_id = employee_id
        self.name_edit = QLineEdit()
        self.add_row("الاسم *", self.name_edit)
        self.nationality_edit = QLineEdit()
        self.add_row("الجنسية", self.nationality_edit)
        self.phone_edit = QLineEdit()
        self.add_row("رقم الهاتف", self.phone_edit)
        self.type_combo = QComboBox()
        self.type_combo.addItem("— اختر النوع —", None)
        self.type_combo.addItem("سائق", "driver")
        self.type_combo.addItem("إداري", "admin")
        self.add_row("نوع الموظف *", self.type_combo)
        self.notes_edit = QPlainTextEdit()
        self.notes_edit.setFixedHeight(70)
        self.add_row("ملاحظات / بيانات إضافية", self.notes_edit)

        if employee_id:
            e = repo.get_employee(db.get_conn(), employee_id)
            if e:
                self.setWindowTitle(f"بيانات الموظف {e['code']}")
                self.name_edit.setText(e["name"])
                self.nationality_edit.setText(e["nationality"] or "")
                self.phone_edit.setText(e["phone"] or "")
                idx = self.type_combo.findData(e["emp_type"])
                self.type_combo.setCurrentIndex(idx if idx >= 0 else 0)
                self.notes_edit.setPlainText(e["notes"] or "")
        if read_only:
            self.lock_fields()

    def save(self) -> None:
        data = {
            "name": _text(self.name_edit.text()),
            "nationality": _text(self.nationality_edit.text()),
            "phone": _text(self.phone_edit.text()),
            "emp_type": self.type_combo.currentData(),
            "notes": self.notes_edit.toPlainText().strip(),
        }
        repo.save_employee(db.get_conn(), data, self.employee_id)


# ---------------------------------------------------------------------------
# السيارات
# ---------------------------------------------------------------------------
class VehicleDialog(FormDialog):
    def __init__(self, parent=None, vehicle_id: int | None = None,
                 read_only: bool = False):
        super().__init__(parent, "بيانات السيارة", read_only, width=520)
        self.vehicle_id = vehicle_id
        conn = db.get_conn()
        self.plate_edit = QLineEdit()
        self.add_row("رقم اللوحة *", self.plate_edit)
        self.type_edit = QLineEdit()
        self.type_edit.setPlaceholderText("مثال: سطحة / قلاب / تريلة")
        self.add_row("النوع", self.type_edit)
        self.driver_combo = DictCombo()
        self.driver_combo.load(repo.list_employees(conn, "driver"))
        self.add_row("السائق الافتراضي (اختياري)", self.driver_combo)
        self.notes_edit = QPlainTextEdit()
        self.notes_edit.setFixedHeight(60)
        self.add_row("ملاحظات", self.notes_edit)

        if vehicle_id:
            v = repo.get_vehicle(conn, vehicle_id)
            if v:
                self.setWindowTitle(f"بيانات السيارة {v['code']}")
                self.plate_edit.setText(v["plate_number"] or "")
                self.type_edit.setText(v["vehicle_type"] or "")
                self.driver_combo.select(v["default_driver_id"])
                self.notes_edit.setPlainText(v["notes"] or "")
        if read_only:
            self.lock_fields()

    def save(self) -> None:
        data = {
            "plate_number": _text(self.plate_edit.text()),
            "vehicle_type": _text(self.type_edit.text()),
            "default_driver_id": self.driver_combo.selected_id(),
            "notes": self.notes_edit.toPlainText().strip(),
        }
        repo.save_vehicle(db.get_conn(), data, self.vehicle_id)


# ---------------------------------------------------------------------------
# السنوات المالية
# ---------------------------------------------------------------------------
class YearDialog(FormDialog):
    def __init__(self, parent=None, year_id: int | None = None,
                 read_only: bool = False):
        super().__init__(parent, "السنة المالية", read_only, width=480)
        self.year_id = year_id
        self.year_spin = QSpinBox()
        self.year_spin.setRange(2000, 2200)
        self.year_spin.setValue(date.today().year)
        self.add_row("السنة *", self.year_spin)
        self.from_edit = VDateEdit()
        self.add_row("من تاريخ *", self.from_edit)
        self.to_edit = VDateEdit()
        self.add_row("إلى تاريخ *", self.to_edit)
        self.status_label = QLabel("")
        self.add_row("الحالة", self.status_label)
        self.notes_edit = QPlainTextEdit()
        self.notes_edit.setFixedHeight(60)
        self.add_row("ملاحظات", self.notes_edit)

        if year_id:
            y = repo.get_year(db.get_conn(), year_id)
            if y:
                self.setWindowTitle(f"السنة المالية {y['year']}")
                self.year_spin.setValue(y["year"])
                self.from_edit.set_iso(y["date_from"])
                self.to_edit.set_iso(y["date_to"])
                self.status_label.setText("مفتوحة ✅" if y["status"] == "open"
                                          else "مغلقة 🔒")
                self.notes_edit.setPlainText(y["notes"] or "")
        else:
            y = date.today().year
            self.from_edit.set_iso(f"{y}-01-01")
            self.to_edit.set_iso(f"{y}-12-31")
        if read_only:
            self.lock_fields()

    def save(self) -> None:
        data = {
            "year": self.year_spin.value(),
            "date_from": self.from_edit.iso(),
            "date_to": self.to_edit.iso(),
            "notes": self.notes_edit.toPlainText().strip(),
        }
        repo.save_year(db.get_conn(), data, self.year_id)


# ---------------------------------------------------------------------------
# الخزائن والبنوك
# ---------------------------------------------------------------------------
class AccountDialog(FormDialog):
    def __init__(self, kind: str, parent=None, account_id: int | None = None,
                 read_only: bool = False):
        title = "بيانات الخزينة" if kind == "cashbox" else "بيانات البنك"
        super().__init__(parent, title, read_only, width=520)
        self.kind = kind
        self.account_id = account_id
        conn = db.get_conn()
        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText(
            "مثال: الخزينة الرئيسية" if kind == "cashbox" else "مثال: بنك الراجحي")
        self.add_row("الاسم *", self.name_edit)
        self.date_edit = VDateEdit()
        self.add_row("تاريخ الإنشاء *", self.date_edit)
        if kind == "bank":
            self.accnum_edit = QLineEdit()
            self.add_row("رقم الحساب", self.accnum_edit)
            self.iban_edit = QLineEdit()
            self.add_row("الآيبان (IBAN)", self.iban_edit)
        self.opening_edit = AmountEdit()
        self.add_row("الرصيد الافتتاحي", self.opening_edit)
        self.notes_edit = QPlainTextEdit()
        self.notes_edit.setFixedHeight(60)
        self.add_row("ملاحظات", self.notes_edit)
        self.balance_label = QLabel("—")
        self.balance_label.setObjectName("totalValue")
        self.add_row("الرصيد الحالي (تلقائي)", self.balance_label)

        if account_id:
            a = repo.get_account(conn, kind, account_id)
            if a:
                self.setWindowTitle(f"{title} — {a['code']}")
                self.name_edit.setText(a["name"])
                self.date_edit.set_iso(a["created_date"])
                if kind == "bank":
                    self.accnum_edit.setText(a["account_number"] or "")
                    self.iban_edit.setText(a["iban"] or "")
                self.opening_edit.set_value(a["opening_balance"])
                self.notes_edit.setPlainText(a["notes"] or "")
                self.balance_label.setText(
                    fmt.money(calc.account_balance(conn, kind, account_id)))
        if read_only:
            self.lock_fields()

    def save(self) -> None:
        data = {
            "name": _text(self.name_edit.text()),
            "created_date": self.date_edit.iso(),
            "opening_balance": self.opening_edit.value(),
            "notes": self.notes_edit.toPlainText().strip(),
        }
        if self.kind == "bank":
            data["account_number"] = _text(self.accnum_edit.text())
            data["iban"] = _text(self.iban_edit.text())
        repo.save_account(db.get_conn(), self.kind, data, self.account_id)


# ---------------------------------------------------------------------------
# لقطة الإغلاق (Snapshot)
# ---------------------------------------------------------------------------
class SnapshotDialog(QDialog):
    """عرض لقطة إغلاق السنة: أرصدة العملاء والخزائن والبنوك وأرباح السنة."""

    def __init__(self, year_id: int, parent=None):
        super().__init__(parent)
        conn = db.get_conn()
        y = repo.get_year(conn, year_id)
        self.year = dict(y) if y else {}
        self.setWindowTitle(f"لقطة إغلاق سنة {self.year.get('year', '')}")
        self.resize(880, 560)
        self.snap = repo.get_snapshot(conn, year_id)

        root = QVBoxLayout(self)
        root.setContentsMargins(14, 12, 14, 12)
        root.setSpacing(10)

        if not self.snap:
            lbl = QLabel("لا توجد لقطة محفوظة لهذه السنة.\n"
                         "يمكن إنشاء لقطة الآن بالضغط على الزر أدناه.")
            lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            root.addWidget(lbl, 1)
            btn = QPushButton("🖼️ إنشاء لقطة الإغلاق الآن")
            btn.setObjectName("primary")
            btn.clicked.connect(lambda: self._create(year_id))
            root.addWidget(btn, 0, Qt.AlignmentFlag.AlignCenter)
            return

        info_lbl = QLabel(
            f"السنة المالية {self.snap['year']} — من {self.snap['date_from']} "
            f"إلى {self.snap['date_to']}   |   تاريخ اللقطة: {self.snap['created_at']}")
        info_lbl.setObjectName("sectionLabel")
        root.addWidget(info_lbl)

        tabs = QTabWidget()
        cust_table = PlainTable(["الكود", "اسم العميل", "الرصيد لحظة الإغلاق"])
        cust_table.set_rows([[c["code"], c["name"], m(c["balance"])]
                             for c in self.snap["customers"]])
        tabs.addTab(cust_table, "أرصدة العملاء")

        acc_table = PlainTable(["الجهة", "الكود", "الاسم", "الرصيد لحظة الإغلاق"])
        rows = [["خزينة", c["code"], c["name"], m(c["balance"])]
                for c in self.snap["cashboxes"]]
        rows += [["بنك", b["code"], b["name"], m(b["balance"])]
                 for b in self.snap["banks"]]
        acc_table.set_rows(rows)
        tabs.addTab(acc_table, "أرصدة الخزائن والبنوك")

        pnl = self.snap["pnl"]
        pnl_table = PlainTable(["البيان", "القيمة"])
        pnl_table.set_rows([
            ["إيرادات النقلات", m(pnl["transport_revenue"])],
            ["الإيرادات الأخرى", m(pnl["other_revenue"])],
            ["إجمالي الإيرادات", m(pnl["total_revenue"])],
            ["مصروفات النقلات المباشرة", m(pnl["direct_expenses"])],
            ["الرواتب المنصرفة", m(pnl["salaries"])],
            ["إجمالي السلفيات", m(pnl["advances"])],
            ["مصاريف الصيانة", m(pnl["maintenance"])],
            ["المصاريف العامة", m(pnl["general_expenses"])],
            ["إجمالي المصروفات", m(pnl["total_expenses"])],
            ["صافي ربح / خسارة السنة", m(pnl["net"])],
        ])
        tabs.addTab(pnl_table, "أرباح السنة (P&L)")
        root.addWidget(tabs, 1)

        bar = ExportBar()
        bar.excelClicked.connect(lambda: self._export_tab(tabs, "excel"))
        bar.pdfClicked.connect(lambda: self._export_tab(tabs, "pdf"))
        bar.printClicked.connect(lambda: self._export_tab(tabs, "print"))
        root.addWidget(bar)

    def _create(self, year_id: int) -> None:
        try:
            self.snap = repo.create_snapshot(db.get_conn(), year_id)
            info(self, "تم إنشاء لقطة الإغلاق بنجاح.")
            self.done(QDialog.DialogCode.Accepted)
        except Exception as e:  # noqa: BLE001
            warn(self, str(e))

    def _export_tab(self, tabs: QTabWidget, mode: str) -> None:
        conn = db.get_conn()
        table = tabs.currentWidget().findChild(PlainTable)
        if table is None:
            return
        names = ["أرصدة العملاء", "أرصدة الخزائن والبنوك", "أرباح السنة"]
        title = f"لقطة إغلاق سنة {self.year.get('year', '')} — {names[tabs.currentIndex()]}"
        headers, rows = table.export_data()
        if mode == "excel":
            exporter.export_excel(self, conn, title, headers, rows,
                                  default_name=f"{title}.xlsx")
        else:
            html = exporter.build_report_html(conn, title=title, headers=headers,
                                              rows=rows, center_from=1)
            if mode == "pdf":
                exporter.export_pdf(self, html, f"{title}.pdf")
            else:
                exporter.print_html(self, html)
