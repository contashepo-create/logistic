# -*- coding: utf-8 -*-
"""صفحة إعدادات النظام: بيانات الشركة (ترويسة الطباعة) ومعلومات قاعدة البيانات."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QFormLayout, QGroupBox, QHBoxLayout, QLabel,
    QLineEdit, QPushButton, QVBoxLayout, QWidget,
)

from .. import APP_TITLE, __version__
from ..core import db, features, repo, tax, telegram_bot, updater
from ..utils import invoice_templates
from .widgets import PageFrame, info, warn


class SettingsPage(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.frame = PageFrame("إعدادات النظام",
                               "بيانات الشركة تظهر في ترويسة كل التقارير والفواتير",
                               show_add=False, show_search=False)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(self.frame)

        conn = db.get_conn()
        box = QGroupBox("بيانات الشركة")
        form = QFormLayout(box)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        self.name_edit = QLineEdit(repo.get_setting(conn, "company_name"))
        form.addRow("اسم الشركة", self.name_edit)
        self.phone_edit = QLineEdit(repo.get_setting(conn, "company_phone"))
        form.addRow("هاتف الشركة", self.phone_edit)
        self.address_edit = QLineEdit(repo.get_setting(conn, "company_address"))
        form.addRow("عنوان الشركة", self.address_edit)
        self.email_edit = QLineEdit(repo.get_setting(conn, "company_email"))
        form.addRow("البريد الإلكتروني", self.email_edit)
        self.currency_edit = QLineEdit(repo.get_setting(conn, "currency", "ر.س"))
        form.addRow("رمز العملة", self.currency_edit)
        self.note_edit = QLineEdit(repo.get_setting(
            conn, "vat_note", "الأسعار تشمل ضريبة القيمة المضافة"))
        form.addRow("عبارة أسفل الفواتير", self.note_edit)
        self.frame.add_widget(box, stretch=0)

        # --- الحزمة الضريبية للمنشأة (تظهر على الفاتورة ورمز زاتكا) ---
        tax_box = QGroupBox("البيانات الضريبية والعنوان الوطني (فاتورة زاتكا)")
        tf = QFormLayout(tax_box)
        tf.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        self.vat_rate_edit = QLineEdit(repo.get_setting(conn, "vat_rate", "15"))
        tf.addRow("نسبة ضريبة القيمة المضافة الافتراضية %", self.vat_rate_edit)
        self.tax_number_edit = QLineEdit(repo.get_setting(conn, "company_tax_number"))
        self.tax_number_edit.setPlaceholderText("15 رقماً يبدأ وينتهي بـ 3 — "
                                                "إلزامي لرمز زاتكا")
        tf.addRow("الرقم الضريبي للمنشأة", self.tax_number_edit)
        self.cr_edit = QLineEdit(repo.get_setting(conn, "company_commercial_reg"))
        self.cr_edit.setPlaceholderText("10 أرقام")
        tf.addRow("السجل التجاري", self.cr_edit)
        self.entity_combo = QComboBox()
        for key, label in tax.ENTITY_TYPES.items():
            self.entity_combo.addItem(label, key)
        i = self.entity_combo.findData(
            repo.get_setting(conn, "company_entity_type", "company"))
        self.entity_combo.setCurrentIndex(i if i >= 0 else 1)
        tf.addRow("نوع الكيان", self.entity_combo)
        self.status_combo = QComboBox()
        for key, label in tax.TAX_STATUSES.items():
            self.status_combo.addItem(label, key)
        i = self.status_combo.findData(
            repo.get_setting(conn, "company_tax_status", "taxable"))
        self.status_combo.setCurrentIndex(i if i >= 0 else 0)
        tf.addRow("الحالة الضريبية", self.status_combo)
        self.country_combo = QComboBox()
        for key, label in tax.COUNTRIES.items():
            self.country_combo.addItem(label, key)
        i = self.country_combo.findData(repo.get_setting(conn, "company_country", "SA"))
        self.country_combo.setCurrentIndex(i if i >= 0 else 0)
        tf.addRow("الدولة", self.country_combo)
        self.region_combo = QComboBox()
        self.region_combo.addItem("— اختر —", "")
        for region in tax.SA_REGIONS:
            self.region_combo.addItem(region, region)
        i = self.region_combo.findData(repo.get_setting(conn, "company_region"))
        self.region_combo.setCurrentIndex(i if i >= 0 else 0)
        tf.addRow("المنطقة", self.region_combo)
        self.city_edit = QLineEdit(repo.get_setting(conn, "company_city"))
        tf.addRow("المدينة", self.city_edit)
        self.district_edit = QLineEdit(repo.get_setting(conn, "company_district"))
        tf.addRow("الحي", self.district_edit)
        self.street_edit = QLineEdit(repo.get_setting(conn, "company_street"))
        tf.addRow("الشارع", self.street_edit)
        self.building_edit = QLineEdit(repo.get_setting(conn, "company_building_no"))
        self.building_edit.setPlaceholderText("4 أرقام")
        tf.addRow("رقم المبنى", self.building_edit)
        self.postal_edit = QLineEdit(repo.get_setting(conn, "company_postal_code"))
        self.postal_edit.setPlaceholderText("5 أرقام")
        tf.addRow("الرمز البريدي", self.postal_edit)
        self.additional_edit = QLineEdit(repo.get_setting(conn, "company_additional_no"))
        self.additional_edit.setPlaceholderText("4 أرقام")
        tf.addRow("الرقم الإضافي", self.additional_edit)
        self.zatca_label = QLabel("")
        self.zatca_label.setWordWrap(True)
        tf.addRow("حالة امتثال زاتكا", self.zatca_label)
        self.frame.add_widget(tax_box, stretch=0)
        self._refresh_zatca_status()
        self.tax_number_edit.textChanged.connect(self._refresh_zatca_status)

        # --- إعدادات الطباعة وقوالب الفواتير ---
        print_box = QGroupBox("الطباعة وقوالب الفواتير")
        pf = QFormLayout(print_box)
        pf.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        self.template_combo = QComboBox()
        for tpl in invoice_templates.PRINT_TEMPLATES:
            self.template_combo.addItem(tpl["name"], tpl["id"])
        idx = self.template_combo.findData(
            repo.get_setting(conn, "invoice_template", "modern"))
        self.template_combo.setCurrentIndex(idx if idx >= 0 else 0)
        self.template_combo.currentIndexChanged.connect(self._show_template_hint)
        pf.addRow("قالب الفاتورة", self.template_combo)
        self.paper_combo = QComboBox()
        for pid, label in (("A4", "A4 (21 × 29.7 سم)"), ("A5", "A5 (14.8 × 21 سم)"),
                           ("Letter", "Letter (21.6 × 27.9 سم)")):
            self.paper_combo.addItem(label, pid)
        i = self.paper_combo.findData(repo.get_setting(conn, "print_paper", "A4"))
        self.paper_combo.setCurrentIndex(i if i >= 0 else 0)
        pf.addRow("مقاس الورق", self.paper_combo)
        self.orient_combo = QComboBox()
        self.orient_combo.addItem("طولي (Portrait)", "portrait")
        self.orient_combo.addItem("عرضي (Landscape)", "landscape")
        i = self.orient_combo.findData(
            repo.get_setting(conn, "print_orientation", "portrait"))
        self.orient_combo.setCurrentIndex(i if i >= 0 else 0)
        pf.addRow("اتجاه الصفحة", self.orient_combo)
        self.margin_edit = QLineEdit(repo.get_setting(conn, "print_margin_mm", "12"))
        pf.addRow("الهامش (مم)", self.margin_edit)
        self.fontsize_edit = QLineEdit(repo.get_setting(conn, "print_font_size_pt", "10"))
        pf.addRow("حجم الخط (نقطة)", self.fontsize_edit)
        self.accent_edit = QLineEdit(
            repo.get_setting(conn, "print_accent_color", "#1f4e79"))
        self.accent_edit.setPlaceholderText("#1f4e79")
        pf.addRow("لون الهوية", self.accent_edit)
        self.template_hint = QLabel("")
        self.template_hint.setWordWrap(True)
        self.template_hint.setStyleSheet("color:#64748b;font-size:9pt")
        pf.addRow("", self.template_hint)
        self._show_template_hint()
        self.frame.add_widget(print_box, stretch=0)

        # --- الميزات القابلة للتحكم عن بُعد ---
        feat_box = QGroupBox("الميزات (تتحكم بها أيضاً من بوت التليجرام)")
        fv = QVBoxLayout(feat_box)
        self.feature_checks = {}
        for key in features.FEATURE_KEYS:
            label = features.FEATURE_LABELS[key]
            cb = QCheckBox(label["name"])
            cb.setChecked(features.has_feature(conn, key))
            fv.addWidget(cb)
            hint = QLabel(label["description"])
            hint.setWordWrap(True)
            hint.setStyleSheet("color:#64748b;font-size:9pt;padding-right:22px")
            fv.addWidget(hint)
            self.feature_checks[key] = cb
        note = QLabel("الفاتورة الضريبية معطّلة افتراضياً — لا تُفعَّل إلا بقرارك.")
        note.setStyleSheet("color:#92400e;font-size:9pt")
        fv.addWidget(note)
        self.frame.add_widget(feat_box, stretch=0)

        # --- بوت التليجرام للتحكم عن بُعد ---
        bot_box = QGroupBox("بوت التليجرام للتحكم عن بُعد")
        bf = QFormLayout(bot_box)
        bf.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        self.bot_token_edit = QLineEdit(repo.get_setting(conn, "telegram_bot_token"))
        self.bot_token_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.bot_token_edit.setPlaceholderText("رمز البوت من @BotFather — لا يُسجَّل في أي ملف")
        bf.addRow("رمز البوت", self.bot_token_edit)
        self.bot_chat_edit = QLineEdit(repo.get_setting(conn, "telegram_owner_chat_id"))
        self.bot_chat_edit.setPlaceholderText("معرّف محادثتك — لا يُنفَّذ أمر من غيره")
        bf.addRow("معرّف المالك (Chat ID)", self.bot_chat_edit)
        self.bot_status_label = QLabel("")
        self.bot_status_label.setWordWrap(True)
        bf.addRow("الحالة", self.bot_status_label)
        bot_btn = QPushButton("🤖 تشغيل البوت")
        bot_btn.clicked.connect(self.toggle_bot)
        bf.addRow("", bot_btn)
        self.frame.add_widget(bot_box, stretch=0)

        # --- التحديثات: فحص وإشعار بلا تثبيت تلقائي ---
        upd_box = QGroupBox("التحديثات")
        uv = QVBoxLayout(upd_box)
        uf = QFormLayout()
        uf.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        self.update_url_edit = QLineEdit(repo.get_setting(conn, "update_manifest_url"))
        self.update_url_edit.setPlaceholderText("https://…/manifest.json")
        uf.addRow("عنوان فحص التحديث", self.update_url_edit)
        uv.addLayout(uf)
        self.update_label = QLabel("")
        self.update_label.setWordWrap(True)
        uv.addWidget(self.update_label)
        self.update_btn = QPushButton("🔍 فحص التحديث الآن")
        self.update_btn.clicked.connect(self.check_update)
        uv.addWidget(self.update_btn)
        self.frame.add_widget(upd_box, stretch=0)

        save_btn = QPushButton("💾 حفظ الإعدادات")
        save_btn.setObjectName("primary")
        save_btn.clicked.connect(self.save)
        backup_btn = QPushButton("🛡️ نسخة احتياطية الآن")
        backup_btn.clicked.connect(self.backup_now)
        self.frame.body.addStretch(1)
        lay = QHBoxLayout()
        lay.addWidget(save_btn)
        lay.addWidget(backup_btn)
        lay.addStretch(1)
        self.frame.add_layout(lay)
        self.backup_label = QLabel("")
        self.frame.add_widget(self.backup_label, stretch=0)

        info_box = QGroupBox("معلومات النظام")
        il = QVBoxLayout(info_box)
        il.addWidget(QLabel(f"التطبيق: {APP_TITLE} — الإصدار {__version__}"))
        il.addWidget(QLabel(f"قاعدة البيانات: {db.db_path()}"))
        il.addWidget(QLabel(f"مجلد المرفقات: {db.attachments_dir()}"))
        il.addWidget(QLabel("النظام يعمل بدون اتصال بالإنترنت، والبيانات محلية بالكامل."))
        self.frame.add_widget(info_box, stretch=0)
        self.frame.body.addStretch(2)

    def _show_template_hint(self) -> None:
        """وصف القالب المختار (مطابق لوصف PRINT_TEMPLATES في الويب)."""
        tpl = invoice_templates.get_template(self.template_combo.currentData() or "modern")
        self.template_hint.setText(tpl["description"])

    def toggle_bot(self) -> None:
        """تشغيل/إيقاف بوت التليجرام بعد حفظ الإعدادات."""
        conn = db.get_conn()
        repo.set_setting(conn, "telegram_bot_token",
                         self.bot_token_edit.text().strip())
        repo.set_setting(conn, "telegram_owner_chat_id",
                         self.bot_chat_edit.text().strip())
        bot = telegram_bot.TelegramBot(db.get_conn)
        if not bot.enabled:
            self.bot_status_label.setText(
                "⛔ يحتاج رمز البوت ومعرّف المالك معاً.")
            return
        app = self.window()
        running = getattr(app, "telegram_bot", None)
        if running and running._thread and running._thread.is_alive():
            running.stop()
            self.bot_status_label.setText("⏹️ أُوقف البوت.")
            return
        if bot.start():
            if app is not None:
                app.telegram_bot = bot
            self.bot_status_label.setText(
                "▶️ البوت يعمل. أرسل /help للبوت لقائمة الأوامر.")
        else:
            self.bot_status_label.setText("⛔ تعذّر تشغيل البوت.")

    def check_update(self) -> None:
        """فحص توفّر تحديث — يُبلّغ فقط ولا يُنزّل ولا يُثبّت شيئاً."""
        conn = db.get_conn()
        repo.set_setting(conn, "update_manifest_url",
                         self.update_url_edit.text().strip())
        info_data = updater.check_for_update(conn)
        if info_data.get("error"):
            self.update_label.setText(
                f"تعذّر الفحص: {info_data['error']}")
            return
        if not info_data.get("available"):
            self.update_label.setText(
                f"✅ أنت على أحدث إصدار ({info_data['current']}).")
            return
        size = info_data.get("size") or 0
        size_txt = f" — {size / 1048576:.1f} م.ب" if size else ""
        self.update_label.setText(
            f"🔔 <b>يتوفر تحديث {info_data['latest']}</b>{size_txt}<br>"
            f"{info_data.get('notes', '')}<br>"
            f"<i>لن يُثبَّت تلقائياً — نزّله وثبّته بنفسك من العنوان المعطى.</i>")

    def backup_now(self) -> None:
        """نسخة احتياطية متناسقة إلى مجلد backups داخل مجلد البيانات."""
        try:
            from ..core.db import backup_database
            path = backup_database()
            self.backup_label.setText(f"آخر نسخة احتياطية: {path}")
            info(self, f"تم إنشاء نسخة احتياطية بنجاح:\n{path}")
        except Exception as e:  # noqa: BLE001
            warn(self, f"تعذر إنشاء النسخة الاحتياطية:\n{e}")

    def _refresh_zatca_status(self) -> None:
        """يعرض الحقول الإلزامية الناقصة لإصدار فاتورة زاتكا سليمة."""
        missing = tax.zatca_missing_fields(
            seller_name=self.name_edit.text().strip(),
            seller_vat=self.tax_number_edit.text().strip(),
            seller_address=self.address_edit.text().strip(),
            invoice_type="simplified", date="x")
        if missing:
            self.zatca_label.setText("⚠️ ناقص لرمز زاتكا: " + "، ".join(missing))
            self.zatca_label.setStyleSheet("color:#b45309")
        else:
            self.zatca_label.setText("✅ البيانات مكتملة لإصدار فاتورة زاتكا "
                                     "مع رمز الاستجابة السريعة.")
            self.zatca_label.setStyleSheet("color:#15803d")

    def save(self) -> None:
        conn = db.get_conn()
        # تحقّق الحزمة الضريبية قبل الحفظ (نفس قواعد نسخة الويب)
        profile = tax.normalize_tax_profile({
            "tax_number": self.tax_number_edit.text().strip(),
            "commercial_reg": self.cr_edit.text().strip(),
            "entity_type": self.entity_combo.currentData(),
            "tax_status": self.status_combo.currentData(),
            "country": self.country_combo.currentData(),
            "postal_code": self.postal_edit.text().strip(),
            "building_no": self.building_edit.text().strip(),
            "additional_no": self.additional_edit.text().strip(),
        })
        try:
            profile = tax.normalize_tax_profile(profile)
        except Exception as e:  # noqa: BLE001
            warn(self, str(e))
            return
        errors = tax.validate_tax_profile(profile)
        if errors:
            warn(self, "\n".join(errors))
            return
        try:
            vat_rate = max(0.0, min(100.0, float(self.vat_rate_edit.text() or 15)))
        except ValueError:
            warn(self, "نسبة ضريبة القيمة المضافة غير صالحة.")
            return
        values = {
            "company_name": self.name_edit.text().strip(),
            "company_phone": self.phone_edit.text().strip(),
            "company_address": self.address_edit.text().strip(),
            "company_email": self.email_edit.text().strip(),
            "currency": self.currency_edit.text().strip(),
            "vat_note": self.note_edit.text().strip(),
            "vat_rate": f"{vat_rate:g}",
            "company_tax_number": profile["tax_number"],
            "company_commercial_reg": profile["commercial_reg"],
            "company_entity_type": profile["entity_type"],
            "company_tax_status": profile["tax_status"],
            "company_country": profile["country"],
            "company_region": self.region_combo.currentData() or "",
            "company_city": self.city_edit.text().strip(),
            "company_district": self.district_edit.text().strip(),
            "company_street": self.street_edit.text().strip(),
            "company_building_no": profile["building_no"],
            "company_postal_code": profile["postal_code"],
            "company_additional_no": profile["additional_no"],
        }
        try:
            # التحقق المركزي في طبقة المستودع (مطابق لـ validateCompanyFields)
            repo.save_company_settings(conn, values)
        except Exception as e:  # noqa: BLE001
            warn(self, str(e))
            return
        # قالب الفاتورة وإعدادات الطباعة
        repo.set_setting(conn, "invoice_template",
                         self.template_combo.currentData() or "modern")
        repo.set_setting(conn, "print_paper", self.paper_combo.currentData() or "A4")
        repo.set_setting(conn, "print_orientation",
                         self.orient_combo.currentData() or "portrait")
        for setting_key, edit, default in (
                ("print_margin_mm", self.margin_edit, "12"),
                ("print_font_size_pt", self.fontsize_edit, "10"),
                ("print_accent_color", self.accent_edit, "#1f4e79")):
            value = edit.text().strip() or default
            repo.set_setting(conn, setting_key, value)
        # مفاتيح الميزات (الافتراضي معطّل — التفعيل قرار صريح)
        for key, cb in self.feature_checks.items():
            features.set_feature(conn, key, cb.isChecked())
        # بوت التليجرام وعنوان التحديث
        repo.set_setting(conn, "telegram_bot_token",
                         self.bot_token_edit.text().strip())
        repo.set_setting(conn, "telegram_owner_chat_id",
                         self.bot_chat_edit.text().strip())
        repo.set_setting(conn, "update_manifest_url",
                         self.update_url_edit.text().strip())
        self._refresh_zatca_status()
        info(self, "تم حفظ الإعدادات بنجاح.")
