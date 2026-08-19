# -*- coding: utf-8 -*-
"""صفحة إدارة الرواتب: إصدار رواتب السائقين والموظفين وسجلها."""
from __future__ import annotations

from ..core import calc, db, repo
from ..utils import fmt
from ..utils.fmt import EMP_TYPES
from .dialogs_payroll import PayrollDialog
from .pages_base import CrudPage
from .pages_ops import FilterRow
from .widgets import DataTable, DictCombo, TotalsBar, confirm, warn


class PayrollPage(CrudPage):
    TITLE = "إدارة الرواتب"
    SUBTITLE = "الصافي = الأساسي + الإضافات − خصم السلف − الخصومات الأخرى"
    ADD_TEXT = "➕ إصدار راتب"

    def build(self) -> "PayrollPage":
        self.filter_row = FilterRow()
        self.frame.add_layout_at(0, self.filter_row)
        self.employee_combo = DictCombo()
        self.employee_combo.load(repo.list_employees(db.get_conn()))
        self.filter_row.add_filter("الموظف", self.employee_combo)
        self.filter_row.refresh_btn.clicked.connect(self.refresh)

        self.set_table(DataTable(
            ["رقم الراتب", "تاريخ الصرف", "الموظف", "النوع", "عن شهر",
             "طريقة الصرف", "الأساسي", "الإضافات", "خصم السلف",
             "خصومات أخرى", "الصافي المنصرف"]))
        self.totals = TotalsBar(["إجمالي الرواتب المنصرفة (الصافي)"])
        self.frame.add_widget(self.totals, stretch=0)
        return self

    def fetch(self):
        d_from, d_to = self.filter_row.range()
        emp = self.employee_combo.selected_id()
        data = repo.list_payrolls(db.get_conn(), d_from, d_to, emp)
        rows = []
        for p in data:
            rows.append([
                calc.voucher_number_label("PAY", p["number"]), p["date"],
                p["employee_name"], EMP_TYPES.get(p["emp_type"], "—"),
                fmt.period_label(p["period_year"], p["period_month"]),
                p["account_name"] or "—",
                fmt.money(p["base_salary"]), fmt.money(p["additions"]),
                fmt.money(p["advance_deduction"]), fmt.money(p["other_deductions"]),
                fmt.money(p["net_salary"]),
            ])
        return [p["id"] for p in data], rows

    def refresh(self, *_a) -> None:
        super().refresh()
        _, rows = self.table.export_data()
        try:
            total = sum(float(r[10].replace(",", "")) for r in rows)
        except (ValueError, IndexError):
            total = 0.0
        self.totals.set_value("إجمالي الرواتب المنصرفة (الصافي)", total)

    def export_subtitle(self) -> str:
        d_from, d_to = self.filter_row.range()
        return f"الفترة: من {d_from} إلى {d_to}"

    def on_add(self) -> None:
        if PayrollDialog(self).exec():
            self.refresh()

    def on_view(self, rid) -> None:
        if PayrollDialog(self, rid, read_only=True).exec():
            self.refresh()

    def on_edit(self, rid) -> None:
        if PayrollDialog(self, rid).exec():
            self.refresh()

    def on_delete(self, rid) -> None:
        if not confirm(self, "هل أنت متأكد من حذف هذا الراتب؟\n"
                             "ستعود السلف المخصومة فيه إلى حالة غير مسددة.",
                       "حذف راتب"):
            return
        try:
            repo.delete_payroll(db.get_conn(), rid)
            self.refresh()
        except Exception as e:  # noqa: BLE001
            warn(self, str(e))
