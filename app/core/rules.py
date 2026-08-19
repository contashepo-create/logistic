# -*- coding: utf-8 -*-
"""
القواعد العامة على مستوى النظام (Global System Rules).

أهمها: قاعدة السنوات المالية — لا يمكن إضافة/تعديل/حذف أي حركة
إلا إذا كان تاريخها (القديم والجديد) داخل نطاق سنة مالية "مفتوحة".
"""
from __future__ import annotations

import sqlite3
from datetime import date as _date


class RuleError(Exception):
    """خطأ يرفضه النظام (يُعرض للمستخدم كرسالة تحذير)."""


# ---------------------------------------------------------------------------
# قاعدة السنوات المالية
# ---------------------------------------------------------------------------
def open_years(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM financial_years WHERE status = 'open' ORDER BY date_from"
    ).fetchall()


def date_in_open_year(conn: sqlite3.Connection, date_str: str) -> bool:
    """هل التاريخ يقع داخل نطاق سنة مالية مفتوحة؟"""
    try:
        _date.fromisoformat(date_str)
    except (TypeError, ValueError):
        raise RuleError("تاريخ غير صالح، يجب أن يكون بصيغة سنة-شهر-يوم.")
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


def has_open_year(conn: sqlite3.Connection) -> bool:
    return conn.execute(
        "SELECT COUNT(*) AS c FROM financial_years WHERE status='open'"
    ).fetchone()["c"] > 0


# ---------------------------------------------------------------------------
# تحقق الأرقام والمبالغ
# ---------------------------------------------------------------------------
def ensure_positive(amount: float, field: str = "المبلغ") -> None:
    if amount is None or amount <= 0:
        raise RuleError(f"يجب إدخال {field} أكبر من صفر.")


def ensure_not_blank(value: str, field: str) -> None:
    if value is None or not str(value).strip():
        raise RuleError(f"يجب إدخال {field}.")
