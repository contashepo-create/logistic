# -*- coding: utf-8 -*-
"""القسم الخامس: التقارير الذكية الخمسة (فلاتر تاريخ + تصدير PDF/Excel + طباعة)."""
from __future__ import annotations

from datetime import date

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QHBoxLayout, QLabel, QTabWidget, QVBoxLayout, QWidget,
)

from ..core import calc, db, repo
from ..utils import exporter, fmt
from ..utils.fmt import EXPENSE_TYPES, VEHICLE_EXPENSES
from .pages_ops import FilterRow
from .widgets import DictCombo, ExportBar, PageFrame, PlainTable, TotalsBar
from .widgets import info


class ReportPage(QWidget):
    """أساس صفحات التقارير: إطار + فلاتر + جدول + شريط تصدير."""

    TITLE = ""
    SUBTITLE = ""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.frame = PageFrame(self.TITLE, self.SUBTITLE, show_add=False,
                               show_search=False)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(12, 12, 12, 12)
        outer.addWidget(self.frame)
        self.frame.export_bar.excelClicked.connect(lambda: self.do_export("excel"))
        self.frame.export_bar.pdfClicked.connect(lambda: self.do_export("pdf"))
        self.frame.export_bar.printClicked.connect(lambda: self.do_export("print"))
        self._export_table: PlainTable | None = None
        self._export_title_suffix = ""

    def _period(self) -> str:
        return f"الفترة: من {self.filter_row.range()[0]} إلى {self.filter_row.range()[1]}"

    def current_table(self) -> PlainTable:
        return self._export_table

    def summary_lines(self) -> list[tuple[str, str]] | None:
        return None

    def do_export(self, mode: str) -> None:
        table = self.current_table()
        if table is None:
            return
        conn = db.get_conn()
        headers, rows = table.export_data()
        title = self.TITLE + self._export_title_suffix
        if mode == "excel":
            exporter.export_excel(self, conn, title, headers, rows,
                                  default_name=f"{title}.xlsx",
                                  summary_lines=self.summary_lines())
        else:
            html = exporter.build_report_html(
                conn, title=title, subtitle=self._period(), headers=headers,
                rows=rows, summary_lines=self.summary_lines(), center_from=1)
            if mode == "pdf":
                exporter.export_pdf(self, html, f"{title}.pdf")
            else:
                exporter.print_html(self, html)


# ---------------------------------------------------------------------------
# 1) تقرير أرباح الفواتير والرحلات
# ---------------------------------------------------------------------------
class TripProfitsReportPage(ReportPage):
    TITLE = "تقرير أرباح الفواتير والرحلات"
    SUBTITLE = ("الإيرادات − المصاريف المباشرة وقت الفاتورة − المصاريف اللاحقة "
                "من سندات الدفع = صافي الربح الفعلي لكل رحلة")

    def __init__(self, parent=None):
        super().__init__(parent)
        self.filter_row = FilterRow()
        self.frame.add_layout_at(0, self.filter_row)
        self.customer_combo = DictCombo()
        self.customer_combo.load(repo.list_customers(db.get_conn()))
        self.filter_row.add_filter("العميل", self.customer_combo)
        self.filter_row.refresh_btn.clicked.connect(self.load)
        self.table = PlainTable([
            "رقم الفاتورة", "التاريخ", "العميل", "الرحلة (من ← إلى)", "السيارة",
            "السائق", "الإيراد", "مصاريف مباشرة", "مصاريف لاحقة (سندات)",
            "صافي الربح الفعلي"])
        self.frame.add_widget(self.table)
        self.totals = TotalsBar(["الإيرادات", "المصاريف المباشرة",
                                 "المصاريف اللاحقة", "صافي الأرباح الفعلية"])
        self.frame.add_widget(self.totals, stretch=0)
        self._export_table = self.table
        self._data: list[dict] = []
        self.load()

    def load(self) -> None:
        d_from, d_to = self.filter_row.range()
        cid = self.customer_combo.selected_id()
        self._data = calc.trip_profits_report(db.get_conn(), d_from, d_to, cid)
        rows = [[t["invoice"], t["date"], t["customer"], t["route"], t["vehicle"],
                 t["driver"], fmt.money(t["revenue"]), fmt.money(t["direct"]),
                 fmt.money(t["later"]), fmt.money(t["net"])] for t in self._data]
        totals_row = ["الإجمالي", "", "", "", "", "",
                      fmt.money(sum(t["revenue"] for t in self._data)),
                      fmt.money(sum(t["direct"] for t in self._data)),
                      fmt.money(sum(t["later"] for t in self._data)),
                      fmt.money(sum(t["net"] for t in self._data))]
        rows.append(totals_row)
        self.table.set_rows(rows, bold_last=True)
        self.totals.set_value("الإيرادات", sum(t["revenue"] for t in self._data))
        self.totals.set_value("المصاريف المباشرة", sum(t["direct"] for t in self._data))
        self.totals.set_value("المصاريف اللاحقة", sum(t["later"] for t in self._data))
        self.totals.set_value("صافي الأرباح الفعلية", sum(t["net"] for t in self._data))

    def summary_lines(self):
        d = self._data
        return [("عدد الرحلات", str(len(d))),
                ("إجمالي الإيرادات", fmt.money(sum(t["revenue"] for t in d))),
                ("إجمالي المصاريف المباشرة", fmt.money(sum(t["direct"] for t in d))),
                ("إجمالي المصاريف اللاحقة", fmt.money(sum(t["later"] for t in d))),
                ("صافي الأرباح الفعلية", fmt.money(sum(t["net"] for t in d)))]


# ---------------------------------------------------------------------------
# 2) كشف حساب عميل (تقرير)
# ---------------------------------------------------------------------------
class CustomerStatementReportPage(ReportPage):
    TITLE = "كشف حساب عميل"
    SUBTITLE = "الرصيد الافتتاحي + الفواتير − سندات القبض = الرصيد الحالي"

    def __init__(self, parent=None):
        super().__init__(parent)
        self.filter_row = FilterRow()
        self.frame.add_layout_at(0, self.filter_row)
        self.customer_combo = DictCombo()
        self.customer_combo.load(repo.list_customers(db.get_conn()))
        self.filter_row.add_filter("العميل", self.customer_combo)
        self.filter_row.refresh_btn.clicked.connect(self.load)
        self.table = PlainTable(
            ["التاريخ", "المستند", "البيان", "مدين (عليه)", "دائن (له)", "الرصيد"])
        self.frame.add_widget(self.table)
        self.totals = TotalsBar(["الرصيد الافتتاحي", "إجمالي الفواتير",
                                 "إجمالي التحصيل", "الرصيد الحالي"])
        self.frame.add_widget(self.totals, stretch=0)
        self._export_table = self.table
        self._st: dict = {}
        self.load()

    def load(self) -> None:
        cid = self.customer_combo.selected_id()
        if not cid:
            self.table.set_rows([])
            self._st = {}
            return
        self._st = calc.customer_statement(db.get_conn(), cid,
                                           *self.filter_row.range())
        rows = [[r["date"], r["doc"], r["desc"], fmt.money(r["debit"]),
                 fmt.money(r["credit"]), fmt.money(r["balance"])]
                for r in self._st["rows"]]
        rows.append(["", "الإجمالي / الرصيد النهائي", "",
                     fmt.money(sum(r["debit"] for r in self._st["rows"])),
                     fmt.money(sum(r["credit"] for r in self._st["rows"])),
                     fmt.money(self._st["closing"])])
        self.table.set_rows(rows, bold_last=True)
        self.totals.set_value("الرصيد الافتتاحي", self._st["opening"])
        self.totals.set_value("إجمالي الفواتير",
                              sum(r["debit"] for r in self._st["rows"]))
        self.totals.set_value("إجمالي التحصيل",
                              sum(r["credit"] for r in self._st["rows"]))
        self.totals.set_value("الرصيد الحالي", self._st["closing"])

    def summary_lines(self):
        if not self._st:
            return None
        return [("العميل", self.customer_combo.currentText()),
                ("الرصيد الافتتاحي", fmt.money(self._st["opening"])),
                ("إجمالي الفواتير",
                 fmt.money(sum(r["debit"] for r in self._st["rows"]))),
                ("إجمالي التحصيل",
                 fmt.money(sum(r["credit"] for r in self._st["rows"]))),
                ("الرصيد الحالي", fmt.money(self._st["closing"]))]


# ---------------------------------------------------------------------------
# 3) كشف حساب موظف/سائق
# ---------------------------------------------------------------------------
class EmployeeStatementReportPage(ReportPage):
    TITLE = "كشف حساب موظف / سائق"
    SUBTITLE = "الرواتب المنصرفة تفصيلياً + سجل السلف وتسوياتها + بدلات التريب من الفواتير"

    def __init__(self, parent=None):
        super().__init__(parent)
        self.filter_row = FilterRow()
        self.frame.add_layout_at(0, self.filter_row)
        self.employee_combo = DictCombo()
        self.employee_combo.load(repo.list_employees(db.get_conn()))
        self.filter_row.add_filter("الموظف", self.employee_combo)
        self.filter_row.refresh_btn.clicked.connect(self.load)

        self.tabs = QTabWidget()
        # تبويب الرواتب
        self.salaries_table = PlainTable(
            ["رقم", "التاريخ", "عن شهر", "الأساسي", "إضافات", "خصم سلف",
             "خصومات أخرى", "الصافي"])
        self.tabs.addTab(self.salaries_table, "الرواتب المنصرفة")
        # تبويب السلف
        self.advances_table = PlainTable(
            ["رقم السلفة", "التاريخ", "القيمة", "المسدد", "المتبقي", "تفاصيل السداد"])
        self.tabs.addTab(self.advances_table, "سجل السلف")
        # تبويب بدلات التريب
        self.allow_table = PlainTable(
            ["الفاتورة", "التاريخ", "الرحلة", "سعر النقلة", "بدل التريب"])
        self.tabs.addTab(self.allow_table, "بدلات التريب من الفواتير")
        self.tabs.currentChanged.connect(self._tab_changed)
        self.frame.add_widget(self.tabs)

        self.totals = TotalsBar(["إجمالي الرواتب الصافية", "إجمالي السلف",
                                 "المتبقي من السلف", "إجمالي بدلات التريب"])
        self.frame.add_widget(self.totals, stretch=0)
        self._st: dict = {}
        self.load()

    def _tab_changed(self, _i) -> None:
        tables = {0: self.salaries_table, 1: self.advances_table,
                  2: self.allow_table}
        self._export_table = tables[self.tabs.currentIndex()]
        names = {0: " — الرواتب", 1: " — السلف", 2: " — بدلات التريب"}
        self._export_title_suffix = names[self.tabs.currentIndex()]

    def load(self) -> None:
        emp = self.employee_combo.selected_id()
        if not emp:
            for t in (self.salaries_table, self.advances_table, self.allow_table):
                t.set_rows([])
            self._st = {}
            return
        self._st = calc.employee_statement(db.get_conn(), emp,
                                           *self.filter_row.range())
        sal = self._st["salaries"]
        self.salaries_table.set_rows(
            [[calc.voucher_number_label("PAY", p["number"]), p["date"],
              fmt.period_label(p["period_year"], p["period_month"]),
              fmt.money(p["base_salary"]), fmt.money(p["additions"]),
              fmt.money(p["advance_deduction"]), fmt.money(p["other_deductions"]),
              fmt.money(p["net_salary"])] for p in sal])
        adv = self._st["advances"]
        self.advances_table.set_rows(
            [[calc.voucher_number_label("PV", a["number"]), a["date"],
              fmt.money(a["amount"]), fmt.money(a["settled"]),
              fmt.money(a["remaining"]),
              "؛ ".join(f"{s['pdate']}: {fmt.money(s['amount'])}"
                        for s in a["settlements"]) or "لم يُسدد بعد"]
             for a in adv])
        allow = self._st["allowances"]
        self.allow_table.set_rows(
            [[calc.invoice_number_label(a["inv_number"]), a["inv_date"], a["route"],
              fmt.money(a["price"]), fmt.money(a["trip_allowance"])] for a in allow])
        t = self._st["totals"]
        self.totals.set_value("إجمالي الرواتب الصافية", t["salaries_net"])
        self.totals.set_value("إجمالي السلف", t["advances_total"])
        self.totals.set_value("المتبقي من السلف", t["advances_remaining"])
        self.totals.set_value("إجمالي بدلات التريب", t["allowances_total"])
        self._tab_changed(self.tabs.currentIndex())

    def summary_lines(self):
        if not self._st:
            return None
        t = self._st["totals"]
        return [("الموظف", self.employee_combo.currentText()),
                ("إجمالي الرواتب الصافية", fmt.money(t["salaries_net"])),
                ("إجمالي السلف", fmt.money(t["advances_total"])),
                ("المتبقي من السلف", fmt.money(t["advances_remaining"])),
                ("إجمالي بدلات التريب", fmt.money(t["allowances_total"]))]


# ---------------------------------------------------------------------------
# 4) تقرير أداء السيارات
# ---------------------------------------------------------------------------
class VehiclesReportPage(ReportPage):
    TITLE = "تقرير أداء السيارات"
    SUBTITLE = "إيرادات السيارة من الفواتير − مصروفات رحلاتها − صيانتها من سندات الدفع"

    def __init__(self, parent=None):
        super().__init__(parent)
        self.filter_row = FilterRow()
        self.frame.add_layout_at(0, self.filter_row)
        self.vehicle_combo = DictCombo()
        self.vehicle_combo.load(repo.list_vehicles(db.get_conn()),
                               mapper=lambda r: f"{r['code']} - {r['plate_number']}")
        self.filter_row.add_filter("السيارة", self.vehicle_combo)
        self.filter_row.refresh_btn.clicked.connect(self.load)
        self.table = PlainTable(
            ["الكود", "رقم اللوحة", "النوع", "عدد النقلات", "الإيرادات",
             "مصروفات مباشرة", "صيانة (سندات دفع)", "صافي ربحية السيارة"])
        self.frame.add_widget(self.table)
        self.totals = TotalsBar(["الإيرادات", "المصروفات المباشرة",
                                 "الصيانة", "صافي الربحية"])
        self.frame.add_widget(self.totals, stretch=0)
        self._export_table = self.table
        self._data: list[dict] = []
        self.load()

    def load(self) -> None:
        d_from, d_to = self.filter_row.range()
        vid = self.vehicle_combo.selected_id()
        self._data = calc.vehicle_report(db.get_conn(), d_from, d_to, vid)
        rows = [[v["code"], v["plate"], v["vtype"] or "—", v["trips"],
                 fmt.money(v["revenue"]), fmt.money(v["direct"]),
                 fmt.money(v["maintenance"]), fmt.money(v["net"])]
                for v in self._data]
        if rows:
            rows.append(["الإجمالي", "", "",
                         sum(v["trips"] for v in self._data),
                         fmt.money(sum(v["revenue"] for v in self._data)),
                         fmt.money(sum(v["direct"] for v in self._data)),
                         fmt.money(sum(v["maintenance"] for v in self._data)),
                         fmt.money(sum(v["net"] for v in self._data))])
        self.table.set_rows(rows, bold_last=True)
        for label, key in [("الإيرادات", "revenue"), ("المصروفات المباشرة", "direct"),
                           ("الصيانة", "maintenance"), ("صافي الربحية", "net")]:
            self.totals.set_value(label, sum(v[key] for v in self._data))

    def summary_lines(self):
        d = self._data
        return [("عدد السيارات", str(len(d))),
                ("إجمالي الإيرادات", fmt.money(sum(v["revenue"] for v in d))),
                ("إجمالي المصروفات المباشرة", fmt.money(sum(v["direct"] for v in d))),
                ("إجمالي الصيانة", fmt.money(sum(v["maintenance"] for v in d))),
                ("صافي الربحية", fmt.money(sum(v["net"] for v in d)))]


# ---------------------------------------------------------------------------
# 5) تقرير الأرباح والخسائر الشامل (P&L)
# ---------------------------------------------------------------------------
class PnlReportPage(ReportPage):
    TITLE = "تقرير الأرباح والخسائر الشامل (P&L)"
    SUBTITLE = ("(إيرادات النقلات + الإيرادات الأخرى) − (المصروفات المباشرة + "
                "الرواتب الصافية + السلفيات + الصيانة + المصاريف العامة)")

    def __init__(self, parent=None):
        super().__init__(parent)
        self.filter_row = FilterRow()
        self.frame.add_layout_at(0, self.filter_row)
        self.filter_row.refresh_btn.clicked.connect(self.load)
        self.table = PlainTable(["البيان", "القيمة"])
        self.table.horizontalHeader().setStretchLastSection(True)
        self.frame.add_widget(self.table)
        self.totals = TotalsBar(["إجمالي الإيرادات", "إجمالي المصروفات",
                                 "صافي الربح / الخسارة"])
        self.frame.add_widget(self.totals, stretch=0)
        self._export_table = self.table
        self._data: dict = {}
        self.load()

    def load(self) -> None:
        d_from, d_to = self.filter_row.range()
        self._data = calc.pnl_report(db.get_conn(), d_from, d_to)
        d = self._data
        rows = [
            ["إيرادات النقلات", fmt.money(d["transport_revenue"])],
            ["الإيرادات الأخرى (خردة / متنوع)", fmt.money(d["other_revenue"])],
            ["إجمالي الإيرادات", fmt.money(d["total_revenue"])],
            ["مصروفات النقلات المباشرة (تريب/بنزين/كارتة)",
             fmt.money(d["direct_expenses"])],
            ["الرواتب الصافية المنصرفة", fmt.money(d["salaries"])],
            ["إجمالي السلفيات المسجلة", fmt.money(d["advances"])],
            ["مصاريف الصيانة (سندات السيارات)", fmt.money(d["maintenance"])],
            ["المصاريف العامة (إيجار / كهرباء ...)", fmt.money(d["general_expenses"])],
            ["إجمالي المصروفات", fmt.money(d["total_expenses"])],
            ["صافي الربح / (الخسارة) للفترة", fmt.money(d["net"])],
        ]
        self.table.set_rows(rows, bold_last=True)
        self.totals.set_value("إجمالي الإيرادات", d["total_revenue"])
        self.totals.set_value("إجمالي المصروفات", d["total_expenses"])
        self.totals.set_value("صافي الربح / الخسارة", d["net"])

    def summary_lines(self):
        d = self._data
        if not d:
            return None
        return [("إجمالي الإيرادات", fmt.money(d["total_revenue"])),
                ("إجمالي المصروفات", fmt.money(d["total_expenses"])),
                ("صافي الربح / الخسارة", fmt.money(d["net"]))]
