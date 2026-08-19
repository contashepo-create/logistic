# -*- coding: utf-8 -*-
"""صفحات البيانات الأساسية: العملاء، الموظفون، السيارات، السنوات المالية."""
from __future__ import annotations

from PySide6.QtWidgets import QWidget

from ..core import calc, db, repo
from ..utils import fmt
from .dialogs_master import (
    AccountDialog, CustomerDialog, EmployeeDialog, SnapshotDialog, VehicleDialog,
    YearDialog,
)
from .pages_base import CrudPage
from .widgets import DataTable, confirm, info, warn
from .statements import CustomerStatementDialog


# ---------------------------------------------------------------------------
# العملاء
# ---------------------------------------------------------------------------
class CustomersPage(CrudPage):
    TITLE = "جدول العملاء"
    SUBTITLE = "أرصدة العملاء تُحدَّث تلقائياً من الفواتير وسندات القبض"

    def build(self) -> "CustomersPage":
        self.set_table(DataTable(
            ["الكود", "اسم العميل", "رقم الهاتف", "العنوان",
             "الرصيد الافتتاحي", "الرصيد الحالي"],
            extra=[("statement", "📄", "كشف حساب العميل")],
        ))
        return self

    def fetch(self):
        rows = []
        data = calc.customers_with_balance(db.get_conn())
        for c in data:
            rows.append([c["code"], c["name"], c["phone"] or "—", c["address"] or "—",
                         fmt.money(c["opening_balance"]),
                         fmt.money(c["balance"])])
        return [c["id"] for c in data], rows

    def on_add(self) -> None:
        if CustomerDialog(self).exec():
            self.refresh()

    def on_view(self, rid) -> None:
        if CustomerDialog(self, rid, read_only=True).exec():
            self.refresh()

    def on_edit(self, rid) -> None:
        if CustomerDialog(self, rid).exec():
            self.refresh()

    def on_delete(self, rid) -> None:
        if not confirm(self, "هل أنت متأكد من حذف هذا العميل؟", "حذف عميل"):
            return
        try:
            repo.delete_customer(db.get_conn(), rid)
            self.refresh()
        except Exception as e:  # noqa: BLE001
            warn(self, str(e))

    def on_extra(self, key: str, rid) -> None:
        if key == "statement":
            CustomerStatementDialog(rid, self).exec()


# ---------------------------------------------------------------------------
# الموظفون والسائقون
# ---------------------------------------------------------------------------
class EmployeesPage(CrudPage):
    TITLE = "جدول الموظفين والسائقين"
    SUBTITLE = "سجل الموظفين (سائقين وإداريين)"

    def build(self) -> "EmployeesPage":
        self.set_table(DataTable(
            ["الكود", "الاسم", "الجنسية", "رقم الهاتف", "النوع", "ملاحظات"]))
        return self

    def fetch(self):
        rows = []
        data = repo.list_employees(db.get_conn())
        for e in data:
            rows.append([e["code"], e["name"], e["nationality"] or "—",
                         e["phone"] or "—",
                         fmt.EMP_TYPES.get(e["emp_type"], e["emp_type"]),
                         (e["notes"] or "—")[:40]])
        return [e["id"] for e in data], rows

    def on_add(self) -> None:
        if EmployeeDialog(self).exec():
            self.refresh()

    def on_view(self, rid) -> None:
        if EmployeeDialog(self, rid, read_only=True).exec():
            self.refresh()

    def on_edit(self, rid) -> None:
        if EmployeeDialog(self, rid).exec():
            self.refresh()

    def on_delete(self, rid) -> None:
        if not confirm(self, "هل أنت متأكد من حذف هذا الموظف؟", "حذف موظف"):
            return
        try:
            repo.delete_employee(db.get_conn(), rid)
            self.refresh()
        except Exception as e:  # noqa: BLE001
            warn(self, str(e))


# ---------------------------------------------------------------------------
# السيارات
# ---------------------------------------------------------------------------
class VehiclesPage(CrudPage):
    TITLE = "جدول السيارات"
    SUBTITLE = "سيارات الشركة مع السائق الافتراضي لكل سيارة"

    def build(self) -> "VehiclesPage":
        self.set_table(DataTable(
            ["الكود", "رقم اللوحة", "النوع", "السائق الافتراضي"]))
        return self

    def fetch(self):
        rows = []
        data = repo.list_vehicles(db.get_conn())
        for v in data:
            rows.append([v["code"], v["plate_number"], v["vehicle_type"] or "—",
                         v["driver_name"] or "—"])
        return [v["id"] for v in data], rows

    def on_add(self) -> None:
        if VehicleDialog(self).exec():
            self.refresh()

    def on_view(self, rid) -> None:
        if VehicleDialog(self, rid, read_only=True).exec():
            self.refresh()

    def on_edit(self, rid) -> None:
        if VehicleDialog(self, rid).exec():
            self.refresh()

    def on_delete(self, rid) -> None:
        if not confirm(self, "هل أنت متأكد من حذف هذه السيارة؟", "حذف سيارة"):
            return
        try:
            repo.delete_vehicle(db.get_conn(), rid)
            self.refresh()
        except Exception as e:  # noqa: BLE001
            warn(self, str(e))


# ---------------------------------------------------------------------------
# السنوات المالية
# ---------------------------------------------------------------------------
class YearsPage(CrudPage):
    TITLE = "جدول السنوات المالية"
    SUBTITLE = "لا يمكن تسجيل/تعديل/حذف أي حركة خارج نطاق سنة مالية مفتوحة"

    def build(self) -> "YearsPage":
        self.set_table(DataTable(
            ["السنة", "من تاريخ", "إلى تاريخ", "الحالة", "عدد الحركات", "لقطات الإغلاق"],
            extra=[("snapshot", "🖼️", "لقطة الإغلاق Snapshot"),
                   ("toggle", "🔐", "إغلاق / فتح السنة")],
        ))
        return self

    def fetch(self):
        conn = db.get_conn()
        rows = []
        data = repo.list_years(conn)
        for y in data:
            n = repo.movements_count_in_range(conn, y["date_from"], y["date_to"])
            has_snap = repo.get_snapshot(conn, y["id"]) is not None
            rows.append([y["year"], y["date_from"], y["date_to"],
                         "مفتوحة ✅" if y["status"] == "open" else "مغلقة 🔒",
                         n, "يوجد 🖼️" if has_snap else "لا يوجد"])
        return [y["id"] for y in data], rows

    def on_add(self) -> None:
        if YearDialog(self).exec():
            self.refresh()

    def on_view(self, rid) -> None:
        if YearDialog(self, rid, read_only=True).exec():
            self.refresh()

    def on_edit(self, rid) -> None:
        if YearDialog(self, rid).exec():
            self.refresh()

    def on_delete(self, rid) -> None:
        if not confirm(self, "هل أنت متأكد من حذف هذه السنة المالية؟", "حذف سنة مالية"):
            return
        try:
            repo.delete_year(db.get_conn(), rid)
            self.refresh()
        except Exception as e:  # noqa: BLE001
            warn(self, str(e))

    def on_extra(self, rid, key: str) -> None:
        conn = db.get_conn()
        if key == "snapshot":
            y = repo.get_year(conn, rid)
            if y and y["status"] == "open":
                info(self, "لقطة الإغلاق متاحة للسنوات المغلقة فقط.\n"
                           "أغلق السنة أولاً لإنشاء اللقطة.")
                return
            dlg = SnapshotDialog(rid, self)
            dlg.exec()
            self.refresh()
        elif key == "toggle":
            y = repo.get_year(conn, rid)
            if not y:
                return
            if y["status"] == "open":
                if not confirm(self,
                               f"إغلاق السنة {y['year']}؟\n"
                               "لن يمكن بعد الإغلاق تسجيل أو تعديل حركات داخل نطاقها،\n"
                               "وستُنشأ لقطة إغلاق (Snapshot) بالأرصدة والأرباح.",
                               "إغلاق سنة مالية"):
                    return
                try:
                    repo.set_year_status(conn, rid, "closed")
                    repo.create_snapshot(conn, rid)
                    info(self, f"تم إغلاق سنة {y['year']} وإنشاء لقطة الإغلاق بنجاح.")
                    self.refresh()
                except Exception as e:  # noqa: BLE001
                    warn(self, str(e))
            else:
                if not confirm(self, f"إعادة فتح السنة {y['year']}؟",
                               "فتح سنة مالية"):
                    return
                try:
                    repo.set_year_status(conn, rid, "open")
                    self.refresh()
                except Exception as e:  # noqa: BLE001
                    warn(self, str(e))
