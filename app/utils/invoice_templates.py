"""قوالب الفاتورة — ستة قوالب مطابقة لنسخة الويب.

الويب يملك PRINT_TEMPLATES بستة قوالب (modern/classic/compact/elegant/
logistics/thermal) مع accent لكل قالب. هنا نفس القوالب بنفس المعرّفات
والألوان، مبنية بـ HTML جدولي لأن Qt يطبع عبر QTextDocument (لا flex/grid).

كل قالب يستقبل نفس نموذج البيانات (dict) فلا يختلف المحتوى بين القوالب —
يختلف العرض فقط.
"""

from __future__ import annotations

PRINT_TEMPLATES: list[dict[str, str]] = [
    {"id": "modern", "name": "عصري (Modern)",
     "description": "تصميم تقني عصري ببطاقات معلومات وشريط ترويسة أنيق.",
     "accent": "#2563eb"},
    {"id": "classic", "name": "كلاسيكي (Classic)",
     "description": "قالب محاسبي رسمي بإطارات واضحة وجدول كامل الحدود.",
     "accent": "#1e293b"},
    {"id": "compact", "name": "مدمج (Compact)",
     "description": "قالب اقتصادي عالي الكفاءة يضغط المساحات في ورقة واحدة.",
     "accent": "#0d9488"},
    {"id": "elegant", "name": "فاخر (Elegant)",
     "description": "قالب راقٍ بخطوط دقيقة وزوايا ناعمة وهوية بصرية قوية.",
     "accent": "#7c3aed"},
    {"id": "logistics", "name": "تشغيلي للنقل (Logistics)",
     "description": "نسخة مكيّفة لقطاع النقل تعرض المسار والحاوية والكمية بوضوح.",
     "accent": "#b45309"},
    {"id": "thermal", "name": "إيصال حراري (80mm)",
     "description": "تصميم إيصال ضيق للطباعة السريعة مع إجماليات ورمز QR.",
     "accent": "#000000"},
]

TEMPLATE_IDS = tuple(t["id"] for t in PRINT_TEMPLATES)


def esc(value) -> str:
    return (str("" if value is None else value).replace("&", "&amp;")
            .replace("<", "&lt;").replace(">", "&gt;"))


def get_template(template_id: str) -> dict[str, str]:
    """القالب المطلوب، والافتراضي modern (كما في الويب)."""
    for t in PRINT_TEMPLATES:
        if t["id"] == template_id:
            return t
    return PRINT_TEMPLATES[0]


# ---------------------------------------------------------------------------
# مكوّنات مشتركة
# ---------------------------------------------------------------------------
def _seller_block(m: dict, accent: str) -> str:
    s = m["seller"]
    lines = [f"<div style='font-size:16pt;font-weight:900;color:{accent}'>"
             f"{esc(s.get('name', ''))}</div>"]
    for label, key in (("الرقم الضريبي", "tax_number"),
                       ("السجل التجاري", "commercial_reg"),
                       ("الرقم الموحد", "unified_number")):
        if s.get(key):
            lines.append(f"<div style='font-size:8.5pt'>{label}: {esc(s[key])}</div>")
    if s.get("address"):
        lines.append(f"<div style='font-size:8.5pt'>{esc(s['address'])}</div>")
    if s.get("phone"):
        lines.append(f"<div style='font-size:8.5pt'>{esc(s['phone'])}</div>")
    return "".join(lines)


def _buyer_block(m: dict, accent: str, boxed: bool = True) -> str:
    b = m["buyer"]
    rows = [f"<div style='font-size:8pt;color:{accent};font-weight:800'>بيانات المشتري</div>",
            f"<div style='font-size:11pt;font-weight:700'>{esc(b.get('name', ''))}</div>"]
    for label, key in (("الكود", "code"), ("الهاتف", "phone"),
                       ("الرقم الضريبي", "tax_number"), ("العنوان", "address")):
        if b.get(key):
            rows.append(f"<div style='font-size:8.5pt'>{label}: {esc(b[key])}</div>")
    body = "".join(rows)
    if not boxed:
        return body
    return (f"<table width='100%' cellpadding='0' cellspacing='0'><tr>"
            f"<td style='border:1px solid #e2e8f0;padding:7px 10px'>{body}</td>"
            f"</tr></table>")


def _meta_table(m: dict, accent: str) -> str:
    cells = [("رقم الفاتورة", m.get("invoice_number", "")),
             ("التاريخ", m.get("issue_date", ""))]
    if m.get("container_number"):
        cells.append(("رقم الحاوية", m["container_number"]))
    tds = "".join(
        f"<td style='border:1px solid #e2e8f0;padding:5px 8px'>"
        f"<span style='font-size:8pt;color:{accent};font-weight:800'>{esc(k)}</span><br>"
        f"<span style='font-size:10pt;font-weight:700'>{esc(v)}</span></td>"
        for k, v in cells)
    return (f"<table dir='rtl' width='100%' cellpadding='0' cellspacing='0'>"
            f"<tr>{tds}</tr></table>")


def _lines_table(m: dict, accent: str, dense: bool = False,
                 borders: bool = True, dark_head: bool = False) -> str:
    pad = "3px 4px" if dense else "5px 6px"
    size = "8pt" if dense else "9.5pt"
    border = "border='0.5'" if borders else "border='0'"
    head_bg = "#1e293b" if dark_head else accent
    heads = ("م", "البيان", "العدد", "سعر الوحدة", "الإجمالي")
    head = "".join(f"<td align='center' style='background:{head_bg};color:#fff;"
                   f"padding:{pad};font-size:{size};font-weight:800'>{esc(h)}</td>"
                   for h in heads)
    rows = []
    for i, ln in enumerate(m.get("lines") or [], start=1):
        bg = "#f8fafc" if i % 2 == 0 else "#ffffff"
        rows.append(
            f"<tr bgcolor='{bg}'>"
            f"<td align='center' style='padding:{pad};font-size:{size}'>{i}</td>"
            f"<td align='right' style='padding:{pad};font-size:{size}'>"
            f"{esc(ln.get('description', ''))}</td>"
            f"<td align='center' style='padding:{pad};font-size:{size}'>"
            f"{esc(ln.get('qty', ''))}</td>"
            f"<td align='center' style='padding:{pad};font-size:{size}'>"
            f"{esc(ln.get('unit_price', ''))}</td>"
            f"<td align='center' style='padding:{pad};font-size:{size};"
            f"font-weight:700'>{esc(ln.get('total', ''))}</td></tr>")
    return (f"<table dir='rtl' width='100%' {border} cellpadding='0' "
            f"cellspacing='0'><tr>{head}</tr>{''.join(rows)}</table>")


def _totals_block(m: dict, accent: str, dark: bool = False) -> str:
    cur = esc(m.get("currency", ""))
    fg = "#ffffff" if dark else "#0f172a"
    rows = [("الإجمالي قبل الضريبة", m.get("subtotal")),
            (f"ضريبة القيمة المضافة ({esc(m.get('vat_rate'))}%)", m.get("vat_amount"))]
    out = ["<table dir='rtl' width='100%' cellpadding='0' cellspacing='0'>"]
    for label, value in rows:
        out.append(
            f"<tr><td align='right' style='padding:3px 6px;font-size:9.5pt;"
            f"color:{fg}'>{esc(label)}</td>"
            f"<td align='left' style='padding:3px 6px;font-size:9.5pt;"
            f"color:{fg}'>{esc(value)} {cur}</td></tr>")
    out.append(
        f"<tr><td align='right' style='padding:6px;border-top:2px solid {accent};"
        f"font-size:11pt;font-weight:900;color:{fg}'>الإجمالي المستحق شامل الضريبة</td>"
        f"<td align='left' style='padding:6px;border-top:2px solid {accent};"
        f"font-size:11pt;font-weight:900;color:{accent}'>"
        f"{esc(m.get('total'))} {cur}</td></tr>")
    out.append("</table>")
    return "".join(out)


def _footer_block(m: dict, accent: str) -> str:
    out = []
    words = m.get("amount_in_words")
    if words:
        out.append(f"<table width='100%' cellpadding='0' cellspacing='0'><tr>"
                   f"<td style='border:1px solid {accent};padding:7px 10px'>"
                   f"<div style='font-size:8pt;color:{accent};font-weight:800'>"
                   f"المبلغ كتابةً</div>"
                   f"<div style='font-size:10pt'>{esc(words)}</div></td></tr></table>")
    if m.get("qr_html"):
        out.append(f"<table width='100%' cellpadding='0' cellspacing='0'><tr>"
                   f"<td align='right' style='font-size:8pt;padding-top:6px'>"
                   f"{esc(m.get('qr_caption') or 'رمز الاستجابة السريعة (ZATCA)')}"
                   f"<br>{m['qr_html']}</td></tr></table>")
    if m.get("notes"):
        out.append(f"<div style='font-size:8.5pt;padding-top:6px'>"
                   f"<b style='color:{accent}'>ملاحظات:</b> {esc(m['notes'])}</div>")
    if m.get("footer_text"):
        out.append(f"<div align='center' style='font-size:8pt;color:#64748b;"
                   f"padding-top:8px'>{esc(m['footer_text'])}</div>")
    if m.get("warning"):
        out.append(f"<div align='center' style='font-size:8pt;color:#92400e;"
                   f"padding-top:6px'>{esc(m['warning'])}</div>")
    return "".join(out)


# ---------------------------------------------------------------------------
# القوالب الستة
# ---------------------------------------------------------------------------
def render_modern(m: dict, accent: str) -> str:
    return "".join([
        f"<table dir='rtl' width='100%' cellpadding='0' cellspacing='0'>"
        f"<tr><td style='background:{accent};color:#fff;padding:10px 14px'>"
        f"<div style='font-size:15pt;font-weight:900'>{esc(m['invoice_title_ar'])}"
        f" / {esc(m['invoice_title_en'])}</div></td></tr></table>",
        "<br>", _seller_block(m, accent), "<br>",
        _meta_table(m, accent), "<br>", _buyer_block(m, accent), "<br>",
        _lines_table(m, accent), "<br>", _totals_block(m, accent),
        _footer_block(m, accent)])


def render_classic(m: dict, accent: str) -> str:
    return "".join([
        f"<div align='center' style='font-size:16pt;font-weight:900;"
        f"color:{accent}'>{esc(m['seller'].get('name', ''))}</div>",
        f"<div align='center' style='font-size:12pt;border-bottom:2px solid {accent};"
        f"padding-bottom:5px'>{esc(m['invoice_title_ar'])} / "
        f"{esc(m['invoice_title_en'])}</div><br>",
        _meta_table(m, accent), "<br>", _buyer_block(m, accent), "<br>",
        _lines_table(m, accent, borders=True), "<br>", _totals_block(m, accent),
        _footer_block(m, accent)])


def render_compact(m: dict, accent: str) -> str:
    return "".join([
        f"<table dir='rtl' width='100%'><tr>"
        f"<td align='right' style='font-size:12pt;font-weight:900;color:{accent}'>"
        f"{esc(m['seller'].get('name', ''))}</td>"
        f"<td align='left' style='font-size:10pt;font-weight:800'>"
        f"{esc(m['invoice_title_ar'])} — {esc(m.get('invoice_number', ''))}</td>"
        f"</tr></table><hr>",
        _buyer_block(m, accent, boxed=False),
        _lines_table(m, accent, dense=True),
        _totals_block(m, accent), _footer_block(m, accent)])


def render_elegant(m: dict, accent: str) -> str:
    return "".join([
        f"<div align='center' style='font-size:9pt;color:{accent};"
        f"letter-spacing:2px'>{esc(m['invoice_title_en'].upper())}</div>",
        f"<div align='center' style='font-size:17pt;font-weight:300;"
        f"color:{accent}'>{esc(m['seller'].get('name', ''))}</div>",
        f"<div align='center' style='font-size:10pt'>{esc(m['invoice_title_ar'])}</div><br>",
        _meta_table(m, accent), "<br>", _buyer_block(m, accent), "<br>",
        _lines_table(m, accent, borders=False), "<br>", _totals_block(m, accent),
        _footer_block(m, accent)])


def render_logistics(m: dict, accent: str) -> str:
    return "".join([
        f"<table dir='rtl' width='100%' cellpadding='0' cellspacing='0'><tr>"
        f"<td style='background:#1e293b;color:#fff;padding:9px 12px'>"
        f"<span style='font-size:14pt;font-weight:900'>"
        f"{esc(m['seller'].get('name', ''))}</span><br>"
        f"<span style='font-size:8.5pt'>{esc(m['invoice_title_ar'])} — "
        f"{esc(m.get('invoice_number', ''))}</span></td>"
        f"<td align='left' style='background:{accent};color:#fff;padding:9px 12px;"
        f"font-size:8.5pt'>قطاع النقل والخدمات اللوجستية</td></tr></table><br>",
        _meta_table(m, accent), "<br>", _buyer_block(m, accent), "<br>",
        _lines_table(m, accent, dark_head=True), "<br>", _totals_block(m, accent),
        _footer_block(m, accent)])


def render_thermal(m: dict, accent: str) -> str:
    lines = [f"<div align='center' style='font-size:10pt;font-weight:900'>"
             f"{esc(m['seller'].get('name', ''))}</div>",
             f"<div align='center' style='font-size:8pt'>"
             f"{esc(m['invoice_title_ar'])}</div>",
             f"<div align='center' style='font-size:8pt'>رقم "
             f"{esc(m.get('invoice_number', ''))} — {esc(m.get('issue_date', ''))}</div>",
             "<hr>"]
    for ln in m.get("lines") or []:
        lines.append(f"<div style='font-size:8pt'>{esc(ln.get('description', ''))}</div>")
        lines.append(f"<div align='left' style='font-size:8pt'>"
                     f"{esc(ln.get('qty', ''))} × {esc(ln.get('unit_price', ''))} "
                     f"= {esc(ln.get('total', ''))}</div>")
    lines.append("<hr>")
    for label, value in (("قبل الضريبة", m.get("subtotal")),
                         (f"ضريبة {esc(m.get('vat_rate'))}%", m.get("vat_amount")),
                         ("الإجمالي", m.get("total"))):
        lines.append(f"<table width='100%'><tr>"
                     f"<td align='right' style='font-size:8pt'>{esc(label)}</td>"
                     f"<td align='left' style='font-size:8pt'>{esc(value)} "
                     f"{esc(m.get('currency', ''))}</td></tr></table>")
    if m.get("qr_html"):
        lines.append(f"<div align='center'>{m['qr_html']}</div>")
    if m.get("amount_in_words"):
        lines.append(f"<div align='center' style='font-size:7.5pt'>"
                     f"{esc(m['amount_in_words'])}</div>")
    if m.get("footer_text"):
        lines.append(f"<div align='center' style='font-size:7.5pt'>"
                     f"{esc(m['footer_text'])}</div>")
    return "".join(lines)


_RENDERERS = {
    "modern": render_modern, "classic": render_classic, "compact": render_compact,
    "elegant": render_elegant, "logistics": render_logistics,
    "thermal": render_thermal,
}


def render_invoice(model: dict, template_id: str = "modern") -> str:
    """عرض نموذج الفاتورة بالقالب المطلوب."""
    tpl = get_template(template_id)
    return _RENDERERS[tpl["id"]](model, tpl["accent"])
