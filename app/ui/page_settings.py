# -*- coding: utf-8 -*-
"""صفحة إعدادات النظام: بيانات الشركة (ترويسة الطباعة) ومعلومات قاعدة البيانات."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox, QFormLayout, QGroupBox, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QVBoxLayout, QWidget,
)

from .. import APP_TITLE, __version__
from ..core import db, repo, tax
from .widgets import PageFrame, info, warn


class SettingsPage(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.frame = PageFrame("إعدادات النظام",
                               "بيانات الشركة تظهر في ترويسة كل التقارير والفواتير",
                               show_add=False, show_search=False)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(12, 12, 12, 12)
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
        for key, value in values.items():
            repo.set_setting(conn, key, value)
        self._refresh_zatca_status()
        info(self, "تم حفظ الإعدادات بنجاح.")
