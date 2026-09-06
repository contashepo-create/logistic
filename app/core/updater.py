"""فحص التحديثات وإتاحتها للمستخدم — بلا تثبيت تلقائي.

السياسة (كما طلب المالك):
  1. التطبيق **يفحص** وجود إصدار جديد من عنوان ملف وصف يضبطه المالك.
  2. إن وُجد، تظهر لافتة في صفحة الإعدادات: رقم الإصدار + ملاحظات + حجم.
  3. **لا يُنزَّل ولا يُثبَّت أي شيء إلا بنقرة صريحة من المستخدم.**
  4. بعد التنزيل يُتحقَّق من البصمة (SHA-256) قبل أي تنفيذ.
  5. فشل الشبكة صامت: لا يُزعج المستخدم ولا يُسقط التطبيق.

الفرق عن نسخة الويب: الويب يُنشَر من الخادم فلا يحتاج هذه الآلية؛ تطبيق
سطح المكتب مثبَّت عند العميل فيحتاج تحكّماً صريحاً في التحديث.
"""

from __future__ import annotations

import hashlib
import json
import urllib.error
import urllib.request

APP_VERSION = "1.0.0"
MANIFEST_KEY = "update_manifest_url"
TIMEOUT = 12


def current_version(conn=None) -> str:
    """الإصدار المثبَّت. يُقرأ من الإعدادات إن ضُبط، وإلا من الثابت."""
    if conn is None:
        return APP_VERSION
    from . import repo
    return repo.get_setting(conn, "app_version", "").strip() or APP_VERSION


def manifest_url(conn) -> str:
    from . import repo
    return repo.get_setting(conn, MANIFEST_KEY, "").strip()


def _fetch_json(url: str) -> dict:
    req = urllib.request.Request(url, headers={"User-Agent": f"logistic/{APP_VERSION}"})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _parse_version(text: str) -> tuple[int, ...]:
    out = []
    for part in str(text).strip().split("."):
        digits = "".join(ch for ch in part if ch.isdigit())
        out.append(int(digits) if digits else 0)
    return tuple(out) or (0,)


def is_newer(candidate: str, installed: str) -> bool:
    """مقارنة إصدارات رقمية آمنة (تتعامل مع نصوص غير رقمية)."""
    return _parse_version(candidate) > _parse_version(installed)


def check_for_update(conn) -> dict:
    """فحص توفّر تحديث. لا يُنزِّل شيئاً.

    يُرجع: {available, current, latest, notes, url, sha256, size, error}
    """
    current = current_version(conn)
    result = {"available": False, "current": current, "latest": current,
              "notes": "", "url": "", "sha256": "", "size": 0, "error": ""}
    url = manifest_url(conn)
    if not url:
        result["error"] = "لم يُضبط عنوان فحص التحديث."
        return result
    if not url.lower().startswith(("https://", "http://")):
        result["error"] = "عنوان التحديث يجب أن يبدأ بـ https://"
        return result
    try:
        data = _fetch_json(url)
    except (urllib.error.URLError, OSError, ValueError) as exc:
        result["error"] = str(exc)
        return result
    latest = str(data.get("version") or "").strip()
    result.update({
        "latest": latest or current,
        "notes": str(data.get("notes") or "")[:2000],
        "url": str(data.get("url") or ""),
        "sha256": str(data.get("sha256") or "").strip().lower(),
        "size": int(data.get("size") or 0),
    })
    result["available"] = bool(latest) and is_newer(latest, current)
    return result


def sha256_of(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def verify_download(path: str, expected_sha256: str) -> tuple[bool, str]:
    """التحقق من بصمة الملف المنزَّل قبل أي تنفيذ."""
    if not expected_sha256:
        return False, "لا توجد بصمة متوقعة للتحقق منها."
    actual = sha256_of(path)
    if actual != expected_sha256.strip().lower():
        return False, f"البصمة غير مطابقة (المحسوبة {actual[:16]}…)."
    return True, "البصمة مطابقة."
