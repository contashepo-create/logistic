"""مفاتيح الميزات القابلة للتحكم عن بُعد.

مطابق لـ features.ts في نسخة الويب: قائمة مفاتيح ثابتة، وافتراضي آمن
دائماً **معطّل** — فلا تُفعَّل ميزة مدفوعة/حساسة إلا بقرار صريح من المالك.

الفرق عن الويب: الويب يتحكم بها المطوّر من لوحة الإدارة، وهنا يتحكم بها
المالك من بوت التليجرام أو من صفحة الإعدادات.
"""

from __future__ import annotations

FEATURE_KEYS = (
    "tax_invoice",      # إصدار فاتورة ضريبية (B2B) برمز زاتكا
    "additional_user",  # مستخدم إضافي على بيانات الشركة نفسها
)

FEATURE_LABELS: dict[str, dict[str, str]] = {
    "tax_invoice": {
        "name": "الفاتورة الضريبية",
        "description": "خصائص الفاتورة الضريبية والتحقق وطباعة رمز QR.",
    },
    "additional_user": {
        "name": "المستخدم الإضافي",
        "description": "حساب إضافي واحد يعمل على بيانات الشركة نفسها.",
    },
}

# تحذير مطابق لـ TAX_INVOICE_WARNING في نسخة الويب
TAX_INVOICE_WARNING = (
    "تنبيه: هذه الفاتورة تحسب قيمة الضريبة، لكنها لا تطابق معايير "
    "هيئة الزكاة والضريبة والجمارك (زاتكا)."
)

_SETTING_PREFIX = "feature_"


def is_known_feature(key: str) -> bool:
    return key in FEATURE_KEYS


def has_feature(conn, key: str) -> bool:
    """هل الميزة مفعّلة؟ الافتراضي الآمن دائماً False (كما في الويب)."""
    if not is_known_feature(key):
        return False
    from . import repo
    raw = repo.get_setting(conn, f"{_SETTING_PREFIX}{key}", "")
    return raw.strip().lower() in ("1", "true", "on", "yes", "نعم")


def set_feature(conn, key: str, enabled: bool) -> bool:
    """تفعيل/تعطيل ميزة. ترفع خطأً إن كان المفتاح غير معروف."""
    from .rules import RuleError
    from . import repo
    if not is_known_feature(key):
        raise RuleError(f"ميزة غير معروفة: {key}")
    repo.set_setting(conn, f"{_SETTING_PREFIX}{key}", "1" if enabled else "0")
    return bool(enabled)


def feature_states(conn) -> dict[str, bool]:
    """حالة كل الميزات (للعرض في صفحة الإعدادات أو رد البوت)."""
    return {k: has_feature(conn, k) for k in FEATURE_KEYS}
