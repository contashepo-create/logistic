# -*- coding: utf-8 -*-
"""صفحة إعدادات النظام: بيانات الشركة (ترويسة الطباعة) ومعلومات قاعدة البيانات."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFormLayout, QGroupBox, QHBoxLayout, QLabel, QLineEdit, QPlainTextEdit,
    QPushButton, QVBoxLayout, QWidget,
)

from .. import APP_TITLE, __version__
from ..core import db, repo
from .widgets import PageFrame, VDateEdit, info, warn


class SettingsPage(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.frame = PageFrame("إعدادات النظام",
                               "بيانات الشركة تظهر في ترويسة كل التقارير والفواتير",
                               show_add=False, show_search=False)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(12, 12, 12, 12)
        outer.addWidget(self.frame)

        box = QGroupBox("بيانات الشركة")
        form = QFormLayout(box)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        conn = db.get_conn()
        self.name_edit = QLineEdit(repo.get_setting(conn, "company_name"))
        form.addRow("اسم الشركة", self.name_edit)
        self.phone_edit = QLineEdit(repo.get_setting(conn, "company_phone"))
        form.addRow("هاتف الشركة", self.phone_edit)
        self.address_edit = QLineEdit(repo.get_setting(conn, "company_address"))
        form.addRow("عنوان الشركة", self.address_edit)
        self.currency_edit = QLineEdit(repo.get_setting(conn, "currency", "ر.س"))
        form.addRow("رمز العملة", self.currency_edit)
        self.vat_edit = QLineEdit(repo.get_setting(
            conn, "company_vat_note",
            "فاتورة نقل غير خاضعة لضريبة القيمة المضافة (ZATCA)"))
        form.addRow("عبارة أسفل الفواتير", self.vat_edit)
        self.frame.add_widget(box, stretch=0)

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

    def save(self) -> None:
        conn = db.get_conn()
        for key, edit in (("company_name", self.name_edit),
                          ("company_phone", self.phone_edit),
                          ("company_address", self.address_edit),
                          ("currency", self.currency_edit),
                          ("company_vat_note", self.vat_edit)):
            repo.set_setting(conn, key, edit.text().strip())
        info(self, "تم حفظ الإعدادات بنجاح.")
