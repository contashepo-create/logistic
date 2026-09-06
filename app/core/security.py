# -*- coding: utf-8 -*-
"""
طبقة الأمان وتعقيم المدخلات (مطابقة لـ src/lib/security.ts في نسخة الويب).

الجزء المنقول هو ما يخص سلامة البيانات في تطبيق محلي:
  - نزع محارف التحكم والاتجاهات الخفية (تشويش/انتحال عرض).
  - رفض الأنماط الهجومية الصريحة (حقن SQL/HTML/قوالب/اجتياز مسارات).
  - تعقيم النص (لا وسوم HTML ولا كيانات مموّهة).
  - تحييد حقن صيغ Excel عند التصدير.

ما لم يُنقل عن قصد: تسجيل الدخول وكلمات المرور ورموز التذاكر
(تخص منصة SaaS ولا معنى لها في تطبيق محلي).
"""
from __future__ import annotations

import re

from .rules import RuleError

# محارف تحكم + محارف اتجاه خفية (تُستخدم لانتحال عرض النص) + BOM
_CONTROL_RE = re.compile(
    "[\u0000-\u0008\u000b\u000c\u000e-\u001f\u007f"
    "\u200b-\u200f\u202a-\u202e\u2066-\u2069\ufeff]")

_TAG_RE = re.compile(r"<[^>]*>")
_ENTITY_RE = re.compile(r"&#?[a-z0-9]{2,8};", re.IGNORECASE)

ATTACK_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"<\s*script\b", re.IGNORECASE),
    re.compile(r"javascript\s*:", re.IGNORECASE),
    re.compile(r"on(?:error|load|click|mouseover|focus)\s*=", re.IGNORECASE),
    re.compile(r"\b(?:union\s+select|select\s+.+\s+from\s+|insert\s+into\s+|"
               r"update\s+\w+\s+set\s+|delete\s+from\s+|drop\s+table|"
               r"truncate\s+table|alter\s+table)\b", re.IGNORECASE),
    re.compile(r"(?:--\s|/\*|\*/|;\s*shutdown|xp_cmdshell|pg_sleep\s*\("
               r"|benchmark\s*\()", re.IGNORECASE),
    re.compile(r"\$\{.*\}|\{\{.*\}\}"),          # قوالب/تعبيرات
    re.compile(r"\bdata:text/html\b", re.IGNORECASE),
    re.compile(r"(?:\.\./){2,}"),                # اجتياز مسارات
]

# محارف تبدأ بها صيغة Excel/CSV فتُنفَّذ عند فتح الملف
FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r")


def strip_control_chars(s: str) -> str:
    """ينزع محارف التحكم والاتجاهات الخفية."""
    return _CONTROL_RE.sub("", str(s if s is not None else ""))


def sanitize_text(value, max_len: int = 1000) -> str:
    """يعقّم نصاً: بلا وسوم HTML ولا كيانات مموّهة ولا مسافات مضخّمة."""
    s = strip_control_chars(value if isinstance(value, str) else str(value or ""))
    s = _TAG_RE.sub(" ", s)              # لا وسوم HTML إطلاقاً
    s = _ENTITY_RE.sub(" ", s)           # لا كيانات HTML مموّهة
    s = s.replace("\r\n", "\n")
    s = re.sub(r"[ \t]{3,}", "  ", s)
    s = re.sub(r"\n{4,}", "\n\n\n", s)
    return s.strip()[:max_len]


def looks_malicious(value) -> bool:
    """هل يحتوي النص على نمط هجومي صريح؟"""
    s = str(value if value is not None else "")
    return any(p.search(s) for p in ATTACK_PATTERNS)


def safe_field(value, label: str, max_len: int = 500, min_len: int = 0,
               required: bool = False) -> str:
    """تحقق وتعقيم مركزي لكل نص قبل وصوله إلى قاعدة البيانات."""
    raw = value if isinstance(value, str) else ("" if value is None else str(value))
    if len(raw) > max_len:
        raise RuleError(f"حقل «{label}» طويل جداً (الحد {max_len} محرفاً).")
    if looks_malicious(raw):
        raise RuleError(f"المحتوى المُدخل في «{label}» غير مسموح به.")
    s = sanitize_text(raw, max_len)
    if required and not s:
        raise RuleError(f"حقل «{label}» مطلوب.")
    if s and len(s) < min_len:
        raise RuleError(f"حقل «{label}» قصير جداً ({min_len} حرفاً على الأقل).")
    return s


def safe_text(value, label: str, max_len: int = 5000) -> str:
    """معادل `txt` في نسخة الويب — يُستخدم لكل حقول النصوص."""
    try:
        return safe_field(value, label, max_len)
    except RuleError:
        raise
    except Exception as e:  # noqa: BLE001
        raise RuleError(f"قيمة حقل {label} غير صالحة.") from e


def neutralize_formula(value):
    """يحيّد حقن صيغ Excel/CSV.

    اسم عميل مثل ``=cmd|' /C calc'!A0`` يُنفَّذ في Excel عند فتح الملف
    المصدَّر، لذا يُسبق بمحرف اقتباس أحادي يفقده معنى الصيغة.
    """
    if not isinstance(value, str) or not value:
        return value
    if value.startswith(FORMULA_PREFIXES):
        return "'" + value
    return value
