# -*- coding: utf-8 -*-
"""اختيار عائلة الخط الافتراضية مع دعم العربية على أي نظام تشغيل."""
from __future__ import annotations

CANDIDATES = ["Segoe UI", "Tahoma", "Noto Sans Arabic", "Noto Naskh Arabic",
              "FiraGO", "Arial", "DejaVu Sans"]

_resolved: str | None = None


def pick_font_family() -> str:
    """أول عائلة خطوط متوفرة تدعم واجهة عربية (تفضيل Segoe UI على ويندوز)."""
    global _resolved
    if _resolved:
        return _resolved
    try:
        from PySide6.QtGui import QFontDatabase
        families = set(QFontDatabase.families())
        for fam in CANDIDATES:
            if fam in families:
                _resolved = fam
                return fam
        for fam in families:  # أي خط عربي آخر
            if "Arabic" in fam or "Kufi" in fam or "Naskh" in fam:
                _resolved = fam
                return fam
        _resolved = "SansSerif"
    except Exception:  # noqa: BLE001 — خارج بيئة Qt
        _resolved = "Segoe UI"
    return _resolved
