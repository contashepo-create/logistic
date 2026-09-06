# -*- coding: utf-8 -*-
"""
القواعد العامة على مستوى النظام (Global System Rules).

أهمها: قاعدة السنوات المالية — لا يمكن إضافة/تعديل/حذف أي حركة
إلا إذا كان تاريخها (القديم والجديد) داخل نطاق سنة مالية "مفتوحة".
"""
from __future__ import annotations

import re
import sqlite3
from datetime import date as _date


class RuleError(Exception):
    """خطأ يرفضه النظام (يُعرض للمستخدم كرسالة تحذير)."""


# ---------------------------------------------------------------------------
# تحقق التواريخ (مطابقة لـ safeIsoDate / safeFinancialYear في نسخة الويب)
# ---------------------------------------------------------------------------
_ISO_RE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})$")


def safe_iso_date(value, label: str = "التاريخ") -> str:
    """يتحقق أن النص تاريخ ISO حقيقي موجود فعلاً.

    يرفض الصيغ الأخرى (31-12-2026) والتواريخ المستحيلة (2027-02-30).
    تاريخ غير صالح في نطاق سنة مالية يُفسد كل مقارنات BETWEEN في التقارير
    بصمت، لذا يُرفض عند الإدخال لا عند القراءة.
    """
    s = str(value if value is not None else "").strip()
    m = _ISO_RE.match(s)
    if not m:
        raise RuleError(f"حقل «{label}» يجب أن يكون تاريخاً صالحاً (سنة-شهر-يوم).")
    year, month, day = int(m.group(1)), int(m.group(2)), int(m.group(3))
    try:
        _date(year, month, day)
    except ValueError:
        raise RuleError(f"حقل «{label}» يجب أن يكون تاريخاً صالحاً (سنة-شهر-يوم).") from None
    if year < 1900 or year > 2200:
        raise RuleError(f"حقل «{label}» يجب أن يكون بين عامي 1900 و2200.")
    return s


def safe_financial_year(date_from, date_to) -> tuple[str, str, int]:
    """يتحقق من بداية/نهاية السنة المالية ومدة السنة (180–550 يوماً).

    المدة الدنيا تمنع سنوات قصيرة تُشتت الحركات، والعليا تمنع سنة تبتلع
    سنوات أخرى فتُسبب احتساباً مزدوجاً.
    """
    start = safe_iso_date(date_from, "بداية السنة المالية")
    end = safe_iso_date(date_to, "نهاية السنة المالية")
    days = (_date.fromisoformat(end) - _date.fromisoformat(start)).days + 1
    if days < 180 or days > 550:
        raise RuleError(
            "يجب أن تكون نهاية السنة المالية بعد بدايتها، "
            "وأن تكون مدتها بين 180 و550 يوماً.")
    return start, end, int(start[:4])


# ---------------------------------------------------------------------------
# قاعدة السنوات المالية
# ---------------------------------------------------------------------------
def date_in_open_year(conn: sqlite3.Connection, date_str: str) -> bool:
    """هل التاريخ يقع داخل نطاق سنة مالية مفتوحة؟"""
    safe_iso_date(date_str, "تاريخ الحركة")
    row = conn.execute(
        "SELECT COUNT(*) AS c FROM financial_years "
        "WHERE status = 'open' AND date_from <= ? AND date_to >= ?",
        (date_str, date_str),
    ).fetchone()
    return bool(row["c"])


def ensure_date_in_open_year(conn: sqlite3.Connection, date_str: str) -> None:
    """للحركات الجديدة: التاريخ يجب أن يكون داخل سنة مالية مفتوحة."""
    if not date_in_open_year(conn, date_str):
        raise RuleError(
            "لا يمكن تسجيل حركة بهذا التاريخ:\n"
            "التاريخ خارج نطاق أي سنة مالية مفتوحة.\n"
            "يرجى فتح سنة مالية تشمل هذا التاريخ أولاً (قسم السنوات المالية)."
        )


def ensure_movement_editable(conn: sqlite3.Connection, old_date: str,
                             new_date: str | None = None) -> None:
    """للتعديل/الحذف: التاريخ القديم (والجديد عند التعديل) داخل سنة مفتوحة."""
    if not date_in_open_year(conn, old_date):
        raise RuleError(
            "لا يمكن تعديل أو حذف حركة بتاريخ قديم خارج السنة المالية المفتوحة.\n"
            f"تاريخ الحركة: {old_date}"
        )
    if new_date is not None and new_date != old_date:
        ensure_date_in_open_year(conn, new_date)


# ---------------------------------------------------------------------------
# تحقق الأرقام والمبالغ
# ---------------------------------------------------------------------------
def ensure_positive(amount: float, field: str = "المبلغ") -> None:
    if amount is None or amount <= 0:
        raise RuleError(f"يجب إدخال {field} أكبر من صفر.")


def ensure_not_blank(value: str, field: str) -> None:
    if value is None or not str(value).strip():
        raise RuleError(f"يجب إدخال {field}.")
