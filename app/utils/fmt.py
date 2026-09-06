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
    "supplier": "سداد لمورّد",
    "purchase": "دفع فاتورة مشتريات نقدية",
    "owner": "سحب نقدي لصاحب المنشأة",
    "general": "مصروف عام",
}

# مصدر تمويل مصروف النقلة وأثره المحاسبي (مطابق لنسخة الويب)
EXPENSE_SOURCES = {
    "cash": "نقداً من خزينة/بنك",
    "driver": "من عهدة السائق",
    "supplier": "آجل على مورد",
    "customer": "يتحمّله العميل",
}

EXPENSE_SOURCE_HINTS = {
    "cash": "يُنشأ سند دفع تلقائي ويُخصم فوراً من رصيد الخزينة/البنك.",
    "driver": "يُقيَّد على حساب السائق (يُخصم من عهدته/مستحقاته) بلا تحريك خزينة.",
    "supplier": "التزام آجل على المورد يُسدَّد لاحقاً بسند دفع يدوي.",
    "customer": "لا يُعد تكلفة — يُضاف على الفاتورة ويزيد المستحق على العميل.",
}

# بنود المصروفات التي تظهر مستقلة في تقرير الأرباح والخسائر
PURCHASE_EXPENSE_CATEGORIES = {
    "fuel": "وقود وزيوت",
    "maintenance": "صيانة وإصلاح",
    "spare_parts": "قطع غيار",
    "tires": "إطارات وكاوتش",
    "rent": "إيجارات",
    "utilities": "كهرباء ومياه وخدمات",
    "communications": "اتصالات وإنترنت",
    "insurance": "تأمين",
    "government_fees": "رسوم حكومية وتراخيص",
    "office": "مصروفات مكتبية",
    "hospitality": "ضيافة ونظافة",
    "professional_fees": "أتعاب مهنية",
    "other": "مشتريات ومصروفات أخرى",
}

NOTE_TYPES = {
    "credit": "إشعار دائن (مرتجع/خصم)",
    "debit": "إشعار مدين (إضافة)",
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


def month_name(month: int) -> str:
    return MONTHS_AR[month - 1] if 1 <= month <= 12 else str(month)


def period_label(year: int, month: int) -> str:
    return f"{month_name(month)} {year}"


def clean(text) -> str:
    """تنظيف نص للإدخال (إزالة الفراغات الزائدة)."""
    return re.sub(r"\s+", " ", str(text or "")).strip()

# ---------------------------------------------------------------------------
# التفقيط (المبلغ كتابةً) — مطابق لـ format.ts في نسخة الويب
# ---------------------------------------------------------------------------
_ONES = ["", "واحد", "اثنان", "ثلاثة", "أربعة", "خمسة", "ستة", "سبعة", "ثمانية",
         "تسعة", "عشرة", "أحد عشر", "اثنا عشر", "ثلاثة عشر", "أربعة عشر",
         "خمسة عشر", "ستة عشر", "سبعة عشر", "ثمانية عشر", "تسعة عشر"]
_TENS = ["", "", "عشرون", "ثلاثون", "أربعون", "خمسون", "ستون", "سبعون", "ثمانون",
         "تسعون"]
_HUNDREDS = ["", "مائة", "مائتان", "ثلاثمائة", "أربعمائة", "خمسمائة", "ستمائة",
             "سبعمائة", "ثمانمائة", "تسعمائة"]


def _below_1000(n: int) -> str:
    parts: list[str] = []
    h, rest = divmod(n, 100)
    if h:
        parts.append(_HUNDREDS[h])
    if rest:
        if rest < 20:
            parts.append(_ONES[rest])
        else:
            u, t = rest % 10, rest // 10
            parts.append(f"{_ONES[u]} و{_TENS[t]}" if u else _TENS[t])
    return " و".join(parts)


def _group_word(count: int, forms: tuple[str, str, str, str]) -> str:
    """forms = (مفرد، مثنى، جمع 3–10، تمييز 11+)."""
    if count == 1:
        return forms[0]
    if count == 2:
        return forms[1]
    return f"{_below_1000(count)} {forms[2] if 3 <= count <= 10 else forms[3]}"


def number_to_arabic_words(value: float) -> str:
    n = int(abs(float(value or 0)))
    if n == 0:
        return "صفر"
    chunks = [
        (n // 1_000_000_000, ("مليار", "ملياران", "مليارات", "مليار")),
        ((n % 1_000_000_000) // 1_000_000, ("مليون", "مليونان", "ملايين", "مليون")),
        ((n % 1_000_000) // 1000, ("ألف", "ألفان", "آلاف", "ألفاً")),
    ]
    words = [_group_word(c, f) for c, f in chunks if c]
    tail = n % 1000
    if tail:
        words.append(_below_1000(tail))
    return " و".join(words)


def amount_to_arabic_words(amount: float, currency: str = "ريال",
                           fraction: str = "هللة") -> str:
    negative = (amount or 0) < 0
    rounded = round(abs(float(amount or 0)) + 1e-9, 2)
    whole = int(rounded)
    cents = int(round((rounded - whole) * 100))
    out = f"{number_to_arabic_words(whole)} {currency}"
    if cents:
        out += f" و{number_to_arabic_words(cents)} {fraction}"
    out += " فقط لا غير"
    return f"سالب {out}" if negative else out


# ---------------------------------------------------------------------------
# جانب الرصيد (مطابق لـ balanceSide / balanceText)
# ---------------------------------------------------------------------------
def balance_side(value: float) -> str:
    v = round(float(value or 0), 2)
    return "debit" if v > 0 else ("credit" if v < 0 else "zero")


def balance_text(value: float) -> str:
    v = abs(round(float(value or 0), 2))
    side = balance_side(value)
    if side == "zero":
        return f"{money(0)} (مسدَّد)"
    return f"{money(v)} ({'عليه' if side == 'debit' else 'له'})"
