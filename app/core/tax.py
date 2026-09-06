# -*- coding: utf-8 -*-
"""
الحزمة الضريبية وامتثال فاتورة زاتكا (هيئة الزكاة والضريبة والجمارك — السعودية).

مطابق منطقياً لـ src/lib/tax.ts و src/lib/zatca.ts في نسخة الويب:
  • تحقّق الرقم الضريبي (15 رقماً يبدأ وينتهي بـ 3) والسجل التجاري والعنوان الوطني.
  • رمز الاستجابة السريعة بصيغة TLV مُرمَّز Base64 (المرحلة الأولى للفوترة الإلكترونية).
  • تمييز الفاتورة الضريبية (B2B) عن المبسّطة (B2C).
"""
from __future__ import annotations

import base64
from datetime import datetime, timezone

from .rules import RuleError

# ---------------------------------------------------------------------------
# القوائم المرجعية
# ---------------------------------------------------------------------------
ENTITY_TYPES: dict[str, str] = {
    "establishment": "مؤسسة فردية",
    "company": "شركة",
    "individual": "فرد",
    "nonprofit": "جهة غير ربحية",
    "government": "جهة حكومية",
}

TAX_STATUSES: dict[str, str] = {
    "taxable": "خاضع لضريبة القيمة المضافة",
    "exempt": "معفى من الضريبة",
    "not_registered": "غير مسجّل ضريبياً",
}

SA_REGIONS: list[str] = [
    "الرياض", "مكة المكرمة", "المدينة المنورة", "القصيم", "الشرقية", "عسير",
    "تبوك", "حائل", "الحدود الشمالية", "جازان", "نجران", "الباحة", "الجوف",
]

COUNTRIES: dict[str, str] = {
    "SA": "المملكة العربية السعودية",
    "AE": "الإمارات العربية المتحدة",
    "KW": "الكويت",
    "QA": "قطر",
    "BH": "البحرين",
    "OM": "عُمان",
    "EG": "مصر",
    "OTHER": "دولة أخرى",
}

_AR_DIGITS = {"٠": "0", "١": "1", "٢": "2", "٣": "3", "٤": "4",
              "٥": "5", "٦": "6", "٧": "7", "٨": "8", "٩": "9",
              "۰": "0", "۱": "1", "۲": "2", "۳": "3", "۴": "4",
              "۵": "5", "۶": "6", "۷": "7", "۸": "8", "۹": "9"}

ADDRESS_FIELDS = ("region", "city", "district", "street", "additional_no",
                  "building_no", "postal_code")
TAX_FIELDS = ("tax_number", "commercial_reg", "postal_code", "building_no",
              "additional_no")
TAX_FIELD_LABELS = {
    "tax_number": "الرقم الضريبي", "commercial_reg": "السجل التجاري",
    "postal_code": "الرمز البريدي", "building_no": "رقم المبنى",
    "additional_no": "الرقم الإضافي", "region": "المنطقة", "city": "المدينة",
    "district": "الحي", "street": "الشارع",
}


# ---------------------------------------------------------------------------
# أدوات الأرقام والتحقّق
# ---------------------------------------------------------------------------
def digits_only(value) -> str:
    """تُبقي الأرقام الإنجليزية فقط (مع تحويل الأرقام العربية/الفارسية)."""
    out = []
    for ch in str(value or ""):
        out.append(_AR_DIGITS.get(ch, ch))
    return "".join(c for c in out if c.isdigit())


def is_valid_tax_number(value) -> bool:
    """الرقم الضريبي السعودي: 15 رقماً يبدأ وينتهي بـ 3."""
    d = digits_only(value)
    return len(d) == 15 and d.startswith("3") and d.endswith("3")


def is_valid_commercial_reg(value) -> bool:
    """رقم السجل التجاري: 10 أرقام."""
    return len(digits_only(value)) == 10


def is_valid_postal_code(value) -> bool:
    return len(digits_only(value)) == 5


def is_valid_building_no(value) -> bool:
    """رقم المبنى / الرقم الإضافي: 4 أرقام."""
    return len(digits_only(value)) == 4


# ---------------------------------------------------------------------------
# العنوان الوطني
# ---------------------------------------------------------------------------
def _get(a, key: str, default=""):
    """قراءة حقل من dict أو sqlite3.Row على حدٍّ سواء."""
    if a is None:
        return default
    if hasattr(a, "get"):
        return a.get(key, default)
    try:
        value = a[key]
    except (IndexError, KeyError, TypeError):
        return default
    return default if value is None else value


def format_national_address(a) -> str:
    """صياغة العنوان الوطني في سطر واحد بالترتيب المعتمد."""
    parts = [
        f"مبنى {_get(a, 'building_no')}" if _get(a, "building_no") else "",
        _get(a, "street"),
        f"حي {_get(a, 'district')}" if _get(a, "district") else "",
        _get(a, "city"),
        _get(a, "postal_code"),
        _get(a, "additional_no"),
        _get(a, "region"),
        (country_label(_get(a, "country"))
         if _get(a, "country") and _get(a, "country") != "SA" else ""),
    ]
    return "، ".join(str(p) for p in parts if str(p).strip())


def country_label(code) -> str:
    return COUNTRIES.get(str(code or ""), str(code or ""))


def entity_label(value) -> str:
    return ENTITY_TYPES.get(str(value or ""), str(value or ""))


def tax_status_label(value) -> str:
    return TAX_STATUSES.get(str(value or ""), str(value or ""))


# ---------------------------------------------------------------------------
# التحقّق الشامل والتطبيع
# ---------------------------------------------------------------------------
def validate_tax_profile(p: dict, require_tax_number: bool = False) -> list[str]:
    """قائمة أخطاء عربية جاهزة للعرض (فارغة = سليم)."""
    errors: list[str] = []

    def has(key: str) -> bool:
        return str(p.get(key) or "").strip() != ""

    if require_tax_number and p.get("tax_status") == "taxable" and not has("tax_number"):
        errors.append("الرقم الضريبي مطلوب للجهات الخاضعة لضريبة القيمة المضافة.")
    if has("tax_number") and not is_valid_tax_number(p["tax_number"]):
        errors.append("الرقم الضريبي يجب أن يكون 15 رقماً يبدأ وينتهي بالرقم 3.")
    if has("commercial_reg") and not is_valid_commercial_reg(p["commercial_reg"]):
        errors.append("رقم السجل التجاري يجب أن يكون 10 أرقام.")
    if has("postal_code") and not is_valid_postal_code(p["postal_code"]):
        errors.append("الرمز البريدي يجب أن يكون 5 أرقام.")
    if has("building_no") and not is_valid_building_no(p["building_no"]):
        errors.append("رقم المبنى يجب أن يكون 4 أرقام.")
    if has("additional_no") and not is_valid_building_no(p["additional_no"]):
        errors.append("الرقم الإضافي يجب أن يكون 4 أرقام.")
    if p.get("entity_type") and p["entity_type"] not in ENTITY_TYPES:
        errors.append("نوع الكيان غير صالح.")
    if p.get("tax_status") and p["tax_status"] not in TAX_STATUSES:
        errors.append("الحالة الضريبية غير صالحة.")
    if p.get("country") and p["country"] not in COUNTRIES:
        errors.append("الدولة غير صالحة.")
    return errors


def normalize_tax_profile(p: dict) -> dict:
    """تطبيع آمن قبل الحفظ: أرقام إنجليزية + قوائم سماح."""
    out = dict(p)
    for key in TAX_FIELDS:
        if out.get(key) in (None, ""):
            continue
        raw = str(out[key]).strip()
        if raw and any(c.isalpha() and c.isascii() for c in raw):
            raise RuleError(
                f"حقل «{TAX_FIELD_LABELS[key]}» يجب أن يحتوي على أرقام فقط.")
        out[key] = digits_only(raw)
    for key in ADDRESS_FIELDS:
        if out.get(key) is not None:
            out[key] = " ".join(str(out[key]).split())
    if out.get("entity_type") and out["entity_type"] not in ENTITY_TYPES:
        raise RuleError("نوع الكيان غير صالح.")
    if out.get("tax_status") and out["tax_status"] not in TAX_STATUSES:
        raise RuleError("الحالة الضريبية غير صالحة.")
    if out.get("country"):
        country = str(out["country"]).strip().upper()
        if country not in COUNTRIES:
            raise RuleError("الدولة غير صالحة.")
        out["country"] = country
    return out


def vat_of(amount: float, rate: float) -> float:
    """قيمة ضريبة القيمة المضافة لمبلغ قبل الضريبة."""
    return round2((float(amount or 0) * float(rate or 0)) / 100.0)


def with_vat(amount: float, rate: float) -> float:
    """الإجمالي شامل الضريبة."""
    return round2(float(amount or 0) + vat_of(amount, rate))


def net_of_vat(gross: float, rate: float) -> float:
    """استخراج الصافي من مبلغ شامل الضريبة."""
    rate = float(rate or 0) / 100.0
    return round2(float(gross or 0) / (1 + rate)) if rate > -1 else round2(gross)


def round2(value) -> float:
    """تقريب محاسبي لخانتين عشريتين."""
    return round(float(value or 0) + 1e-9, 2) if float(value or 0) >= 0 \
        else round(float(value or 0) - 1e-9, 2)


# ---------------------------------------------------------------------------
# زاتكا — رمز الاستجابة السريعة
# ---------------------------------------------------------------------------
ZATCA_TYPE_LABEL = {
    "standard": {"ar": "فاتورة ضريبية", "en": "Tax Invoice"},
    "simplified": {"ar": "فاتورة ضريبية مبسّطة", "en": "Simplified Tax Invoice"},
}


def tlv(tag: int, value: str) -> bytes:
    """ترميز قيمة واحدة بصيغة TLV: [tag][length][value] بترميز UTF-8."""
    payload = str(value).encode("utf-8")
    if len(payload) > 255:
        raise RuleError("قيمة TLV أطول من 255 بايت.")
    return bytes([tag, len(payload)]) + payload


def zatca_amount(value) -> str:
    """تنسيق المبلغ برقمين عشريين كما تشترط زاتكا."""
    return f"{round2(value):.2f}"


def zatca_timestamp(when=None) -> str:
    """طابع زمني ISO 8601 (UTC) بلا أجزاء الميلي ثانية."""
    if when is None:
        when = datetime.now(timezone.utc)
    elif isinstance(when, str):
        try:
            when = datetime.fromisoformat(when)
        except ValueError:
            when = datetime.now(timezone.utc)
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    return when.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def build_zatca_qr(seller_name: str, vat_number: str, timestamp,
                   total_with_vat: float, vat_amount: float) -> str:
    """محتوى رمز QR المعتمد من زاتكا (سلسلة Base64).

    التاجات: 1 = اسم البائع، 2 = الرقم الضريبي، 3 = الطابع الزمني،
             4 = الإجمالي شامل الضريبة، 5 = مبلغ الضريبة.
    """
    payload = b"".join([
        tlv(1, str(seller_name or "").strip()),
        tlv(2, digits_only(vat_number)),
        tlv(3, zatca_timestamp(timestamp)),
        tlv(4, zatca_amount(total_with_vat)),
        tlv(5, zatca_amount(vat_amount)),
    ])
    return base64.b64encode(payload).decode("ascii")


def parse_zatca_qr(b64: str) -> dict[int, str]:
    """فكّ سلسلة QR إلى تاجاتها — للاختبار والتشخيص."""
    raw = base64.b64decode(b64)
    out: dict[int, str] = {}
    i = 0
    while i + 1 < len(raw):
        tag, length = raw[i], raw[i + 1]
        out[tag] = raw[i + 2:i + 2 + length].decode("utf-8")
        i += 2 + length
    return out


def zatca_invoice_type(buyer: dict | None) -> str:
    """ضريبية (B2B) إن كان المشتري منشأة خاضعة ولها رقم ضريبي، وإلا مبسّطة."""
    vat = digits_only((buyer or {}).get("tax_number"))
    taxable = ((buyer or {}).get("tax_status") or "taxable") == "taxable"
    return "standard" if len(vat) == 15 and taxable else "simplified"


def zatca_missing_fields(seller_name: str = "", seller_vat: str = "",
                         seller_address: str = "", buyer_name: str = "",
                         buyer_vat: str = "", invoice_type: str = "simplified",
                         date: str = "") -> list[str]:
    """الحقول الإلزامية الناقصة في فاتورة زاتكا (فارغة = مكتملة)."""
    missing: list[str] = []
    if not str(seller_name or "").strip():
        missing.append("اسم البائع")
    if len(digits_only(seller_vat)) != 15:
        missing.append("الرقم الضريبي للبائع (15 رقماً)")
    if not str(seller_address or "").strip():
        missing.append("عنوان البائع")
    if not str(date or "").strip():
        missing.append("تاريخ الإصدار")
    if invoice_type == "standard":
        if not str(buyer_name or "").strip():
            missing.append("اسم المشتري")
        if len(digits_only(buyer_vat)) != 15:
            missing.append("الرقم الضريبي للمشتري")
    return missing


def zatca_qr_png_bytes(payload: str, size: int = 220) -> bytes | None:
    """صورة QR بصيغة PNG (تُستخدم في الطباعة).

    تُعيد None إن لم تتوفّر مكتبتا qrcode و Pillow — الطباعة تعمل بلا رمز
    بدل أن تفشل الفاتورة كلها.
    """
    try:
        import io

        import qrcode  # type: ignore
        img = qrcode.make(payload, box_size=max(2, size // 25), border=1)
    except Exception:  # noqa: BLE001 — qrcode أو Pillow غير متوفرتين
        return None
    buf = io.BytesIO()
    try:
        img.save(buf, format="PNG")
    except Exception:  # noqa: BLE001
        return None
    return buf.getvalue()
