# -*- coding: utf-8 -*-
"""أدوات التنسيق: الأرقام العربية، المبالغ، التواريخ، أسماء الشهور."""
from __future__ import annotations

import math
import re

ARABIC_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩", "0123456789")
PERSIAN_DIGITS = str.maketrans("۰۱۲۳۴۵۶۷۸۹", "0123456789")

MONTHS_AR = [
    "يناير", "فبراير", "مارس", "أبريل", "مايو", "يونيو",
    "يوليو", "أغسطس", "سبتمبر", "أكتوبر", "نوفمبر", "ديسمبر",
]

EXPENSE_TYPES = {  # أنواع مصروف النقلة
    "trip": "تريب",
    "fuel": "بنزين",
    "card": "كارتة",
    "other": "أخرى",
}

PAYMENT_TYPES = {
    "trip": "مصروف يخص رحلة",
    "advance": "سلفة موظف/سائق",
    "vehicle": "مصروف لسيارة",
    "general": "مصروف عام",
}

VEHICLE_EXPENSES = {
    "maintenance": "صيانة",
    "tires": "كاوتش",
    "other": "أخرى",
}

RECEIPT_TYPES = {
    "customer": "تحصيل من عميل",
    "other": "إيرادات أخرى",
}

EMP_TYPES = {
    "driver": "سائق",
    "admin": "إداري",
}


def normalize_digits(text: str) -> str:
    """تحويل الأرقام العربية/الفارسية إلى أرقام إنجليزية."""
    if text is None:
        return ""
    return str(text).translate(ARABIC_DIGITS).translate(PERSIAN_DIGITS)


def parse_float(text, default: float = 0.0) -> float:
    """قراءة رقم من نص (يتقبل فواصل الآلاف والأرقام العربية) — يرفض NaN/inf."""
    if text is None:
        return default
    s = normalize_digits(str(text)).replace(",", "").replace("،", "").strip()
    if not s:
        return default
    s = s.replace("٫", ".")  # فاصلة عشرية عربية
    try:
        v = float(s)
    except ValueError:
        raise ValueError(f"قيمة رقمية غير صالحة: {text}")
    if not math.isfinite(v):
        raise ValueError(f"قيمة رقمية غير صالحة (غير منتهية): {text}")
    return v


def money(x) -> str:
    """تنسيق مبلغ بمنزلتين عشريتين وفواصل آلاف."""
    try:
        v = float(x or 0)
    except (TypeError, ValueError):
        v = 0.0
    return f"{v:,.2f}"


def today_iso() -> str:
    from datetime import date
    return date.today().isoformat()


def month_name(month: int) -> str:
    return MONTHS_AR[month - 1] if 1 <= month <= 12 else str(month)


def period_label(year: int, month: int) -> str:
    return f"{month_name(month)} {year}"


def clean(text) -> str:
    """تنظيف نص للإدخال (إزالة الفراغات الزائدة)."""
    return re.sub(r"\s+", " ", str(text or "")).strip()
