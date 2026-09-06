"""بوت تليجرام للتحكم عن بُعد في التطبيق.

الفرق الجوهري عن نسخة الويب: الويب يرسل إشعارات فقط (sendTelegramCode،
notifyAdmin) ولا يستقبل أوامراً. هنا البوت **يستقبل وينفّذ** — فالمالك
يتحكم في مفاتيح الميزات وفحص التحديث من هاتفه.

الأمان:
  • الرمز لا يُسجَّل في أي ملف أو سجل.
  • لا يُنفَّذ أمر إلا من chat_id المالك المسجَّل صراحةً.
  • كل استجابة تُهرَّب من وسوم HTML.
  • فشل الشبكة لا يُسقط التطبيق — يُبلَّغ عنه فقط.
"""

from __future__ import annotations

import json
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

API = "https://api.telegram.org/bot{token}/{method}"
TIMEOUT = 12
POLL_SECONDS = 3.0

HELP_TEXT = (
    "<b>أوامر بوت التحكم</b>\n"
    "/features — حالة الميزات\n"
    "/enable &lt;الميزة&gt; — تفعيل ميزة\n"
    "/disable &lt;الميزة&gt; — تعطيل ميزة\n"
    "/tax — حالة الفاتورة الضريبية\n"
    "/tax on|off — تفعيل/تعطيل الفاتورة الضريبية\n"
    "/update — فحص توفّر تحديث\n"
    "/status — حالة التطبيق\n"
    "/help — هذه الرسالة"
)


def _esc(text) -> str:
    return (str(text).replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;"))


class TelegramBot:
    """بوت تليجرام يعمل في خيط خلفي بالاستطلاع الطويل."""

    def __init__(self, get_conn, log=None):
        self._get_conn = get_conn
        self._log = log or (lambda msg: None)
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._offset = 0
        self.last_error = ""

    # ------------------------------------------------------------------ إعداد
    @property
    def token(self) -> str:
        from . import repo
        return repo.get_setting(self._get_conn(), "telegram_bot_token", "").strip()

    @property
    def owner_chat_id(self) -> str:
        from . import repo
        return repo.get_setting(self._get_conn(), "telegram_owner_chat_id", "").strip()

    @property
    def enabled(self) -> bool:
        return bool(self.token and self.owner_chat_id)

    # ------------------------------------------------------------------- شبكة
    def _call(self, method: str, payload: dict | None = None) -> dict:
        if not self.token:
            raise RuntimeError("رمز البوت غير مُعد.")
        url = API.format(token=self.token, method=method)
        data = json.dumps(payload or {}).encode("utf-8")
        req = urllib.request.Request(
            url, data=data, headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            return json.loads(resp.read().decode("utf-8"))

    def send(self, text: str, chat_id: str | None = None) -> bool:
        """إرسال رسالة (HTML). تُرجع False عند الفشل بدل رفع استثناء."""
        target = chat_id or self.owner_chat_id
        if not (self.token and target):
            return False
        try:
            out = self._call("sendMessage", {
                "chat_id": target, "text": text, "parse_mode": "HTML"})
            return bool(out.get("ok"))
        except (urllib.error.URLError, OSError, ValueError, RuntimeError) as exc:
            self.last_error = str(exc)
            self._log(f"تعذّر إرسال رسالة تليجرام: {exc}")
            return False

    def _fetch_updates(self) -> list[dict]:
        out = self._call("getUpdates", {
            "offset": self._offset, "timeout": 25,
            "allowed_updates": ["message"]})
        return out.get("result") or [] if out.get("ok") else []

    # ----------------------------------------------------------------- أوامر
    def handle_command(self, text: str) -> str:
        """تنفيذ أمر وإرجاع نص الرد (HTML)."""
        from . import features, repo, updater
        conn = self._get_conn()
        parts = (text or "").strip().split()
        cmd = parts[0].lower().split("@")[0] if parts else ""
        arg = parts[1].lower() if len(parts) > 1 else ""

        if cmd == "/help":
            return HELP_TEXT

        if cmd == "/features":
            lines = ["<b>حالة الميزات</b>"]
            for key, on in features.feature_states(conn).items():
                label = features.FEATURE_LABELS[key]["name"]
                lines.append(f"{'✅' if on else '⛔'} {_esc(label)}: "
                             f"{'مفعّلة' if on else 'معطّلة'}")
            return "\n".join(lines)

        if cmd in ("/enable", "/disable"):
            if not features.is_known_feature(arg):
                known = "، ".join(features.FEATURE_KEYS)
                return f"ميزة غير معروفة. المتاح: {_esc(known)}"
            features.set_feature(conn, arg, cmd == "/enable")
            label = features.FEATURE_LABELS[arg]["name"]
            state = "مفعّلة ✅" if cmd == "/enable" else "معطّلة ⛔"
            return f"{_esc(label)}: {state}"

        if cmd == "/tax":
            if not arg:
                on = features.has_feature(conn, "tax_invoice")
                label = features.FEATURE_LABELS["tax_invoice"]["name"]
                return (f"{_esc(label)}: {'مفعّلة ✅' if on else 'معطّلة ⛔'}\n"
                        f"للتحكم: <code>/tax on</code> أو <code>/tax off</code>")
            if arg in ("on", "1", "true", "نعم"):
                features.set_feature(conn, "tax_invoice", True)
                return "الفاتورة الضريبية: مفعّلة ✅"
            if arg in ("off", "0", "false", "لا"):
                features.set_feature(conn, "tax_invoice", False)
                return "الفاتورة الضريبية: معطّلة ⛔"
            return "استخدم <code>/tax on</code> أو <code>/tax off</code>."

        if cmd == "/update":
            info = updater.check_for_update(conn)
            if info.get("error"):
                return f"تعذّر فحص التحديث: {_esc(info['error'])}"
            if not info.get("available"):
                return f"أنت على أحدث إصدار ({_esc(info.get('current', '?'))})."
            return (f"<b>يتوفر تحديث</b> {_esc(info['latest'])}\n"
                    f"{_esc(info.get('notes', ''))}\n"
                    f"لن يُثبَّت تلقائياً — ثبّته من صفحة الإعدادات.")

        if cmd == "/status":
            year = conn.execute(
                "SELECT year, status FROM financial_years "
                "ORDER BY year DESC LIMIT 1").fetchone()
            y = f"{year['year']} ({year['status']})" if year else "—"
            feats = features.feature_states(conn)
            tax_on = "مفعّلة" if feats.get("tax_invoice") else "معطّلة"
            company = repo.get_setting(conn, "company_name", "—")
            return (f"<b>حالة التطبيق</b>\n"
                    f"الشركة: {_esc(company)}\n"
                    f"السنة المالية: {_esc(y)}\n"
                    f"الفاتورة الضريبية: {tax_on}\n"
                    f"الإصدار: {_esc(updater.current_version(conn))}")

        return f"أمر غير معروف.\n{HELP_TEXT}"

    def _process(self, update: dict) -> None:
        msg = update.get("message") or {}
        chat_id = str((msg.get("chat") or {}).get("id") or "")
        text = msg.get("text") or ""
        # لا يُنفَّذ أي أمر من غير المالك المسجَّل
        if chat_id != self.owner_chat_id:
            self._log(f"تُجاهل أمر من chat_id غير مصرّح: {chat_id}")
            return
        if not text.startswith("/"):
            return
        try:
            reply = self.handle_command(text)
        except Exception as exc:  # noqa: BLE001
            reply = f"حدث خطأ: {_esc(exc)}"
        self.send(reply, chat_id)

    # ------------------------------------------------------------ دورة العمل
    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                for upd in self._fetch_updates():
                    self._offset = max(self._offset,
                                       int(upd.get("update_id", 0)) + 1)
                    self._process(upd)
                self.last_error = ""
            except (urllib.error.URLError, OSError, ValueError) as exc:
                self.last_error = str(exc)
                self._stop.wait(5.0)

    def start(self) -> bool:
        if self._thread and self._thread.is_alive():
            return True
        if not self.enabled:
            return False
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, daemon=True,
                                        name="telegram-bot")
        self._thread.start()
        return True

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=2)
        self._thread = None
