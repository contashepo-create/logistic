# -*- coding: utf-8 -*-
"""صفحات الخزائن والبنوك: مصدر الأموال الواردة والمنصرفة."""
from __future__ import annotations

from ..core import calc, db, repo
from ..utils import fmt
from .dialogs_master import AccountDialog
from .pages_base import CrudPage
from .statements import AccountStatementDialog
from .widgets import DataTable, confirm, warn


class AccountsPage(CrudPage):
    """صفحة عامة للخزائن أو البنوك (kind = cashbox / bank)."""
    KIND = "cashbox"

    def build(self) -> "AccountsPage":
        if self.KIND == "cashbox":
            self.TITLE = "الخزائن (صناديق النقد)"
            self.SUBTITLE = "مصدر الأموال النقدية — الرصيد يُحدَّث تلقائياً"
            headers = ["الرقم", "اسم الخزينة", "تاريخ الإنشاء",
                       "الرصيد الافتتاحي", "الرصيد الحالي"]
        else:
            self.TITLE = "البنوك"
            self.SUBTITLE = "الحسابات البنكية — الرصيد يُحدَّث تلقائياً"
            headers = ["رقم السجل", "اسم البنك", "تاريخ الإنشاء", "رقم الحساب",
                       "الآيبان (IBAN)", "الرصيد الافتتاحي", "الرصيد الحالي"]
        self.frame.title_label.setText(self.TITLE)
        self.frame.sub_label.setText(self.SUBTITLE)
        self.frame.sub_label.show()
        self.set_table(DataTable(
            headers, extra=[("statement", "📄", "كشف حساب " +
                            ("الخزينة" if self.KIND == "cashbox" else "البنك"))]))
        return self

    def fetch(self):
        conn = db.get_conn()
        data = calc.accounts_with_balance(conn, self.KIND)
        rows = []
        for a in data:
            base = [a["code"], a["name"], a["created_date"]]
            if self.KIND == "bank":
                base += [a["account_number"] or "—", a["iban"] or "—"]
            base += [fmt.money(a["opening_balance"]), fmt.money(a["balance"])]
            rows.append(base)
        return [a["id"] for a in data], rows

    def _dialog(self, rid=None, read_only=False) -> AccountDialog:
        return AccountDialog(self.KIND, self, rid, read_only)

    def on_add(self) -> None:
        if self._dialog().exec():
            self.refresh()

    def on_view(self, rid) -> None:
        if self._dialog(rid, read_only=True).exec():
            self.refresh()

    def on_edit(self, rid) -> None:
        if self._dialog(rid).exec():
            self.refresh()

    def on_delete(self, rid) -> None:
        name = calc.account_kind_label(self.KIND)
        if not confirm(self, f"هل أنت متأكد من حذف هذه {name}؟", f"حذف {name}"):
            return
        try:
            repo.delete_account(db.get_conn(), self.KIND, rid)
            self.refresh()
        except Exception as e:  # noqa: BLE001
            warn(self, str(e))

    def on_extra(self, rid, key: str) -> None:
        if key == "statement":
            AccountStatementDialog(self.KIND, rid, self).exec()


class CashboxesPage(AccountsPage):
    KIND = "cashbox"


class BanksPage(AccountsPage):
    KIND = "bank"
