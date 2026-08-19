# -*- coding: utf-8 -*-
"""
طبقة قاعدة البيانات (SQLite): الاتصال، إنشاء الجداول، الإعدادات العامة.

مسار قاعدة البيانات:
  - يمكن تحديده بمتغير البيئة LOGISTIC_DATA_DIR (مفيد للاختبارات).
  - الافتراضي: <المجلد الشخصي>/.logistic/data/logistic.db
"""
from __future__ import annotations

import os
import sqlite3
from pathlib import Path

APP_DIR_NAME = "logistic"

_conn: sqlite3.Connection | None = None


def data_dir() -> Path:
    """مجلد بيانات التطبيق (قاعدة البيانات + المرفقات)."""
    override = os.environ.get("LOGISTIC_DATA_DIR")
    if override:
        p = Path(override)
    else:
        p = Path.home() / f".{APP_DIR_NAME}" / "data"
    p.mkdir(parents=True, exist_ok=True)
    return p


def db_path() -> Path:
    return data_dir() / "logistic.db"


def attachments_dir() -> Path:
    p = data_dir() / "attachments"
    p.mkdir(parents=True, exist_ok=True)
    return p


def get_conn() -> sqlite3.Connection:
    """إرجاع اتصال موحّد (Singleton) مع تفعيل المفاتيح الأجنبية.

    تحصين: ملف القاعدة بصلاحية 600 ومجلد المرفقات 700 (قراءة/كتابة للمالك فقط).
    """
    global _conn
    if _conn is None:
        _conn = sqlite3.connect(str(db_path()), check_same_thread=False)
        _conn.row_factory = sqlite3.Row
        _conn.execute("PRAGMA foreign_keys = ON")
        try:
            import os as _os
            _os.chmod(db_path(), 0o600)
            _os.chmod(data_dir(), 0o700)
        except OSError:
            pass
    return _conn


def backup_database(dest_dir: Path | None = None) -> Path:
    """نسخة احتياطية متناسقة (sqlite backup API) باسم مميز بالوقت."""
    import shutil as _sh
    from datetime import datetime as _dt
    src = get_conn()
    bdir = dest_dir or (data_dir() / "backups")
    bdir.mkdir(parents=True, exist_ok=True)
    stamp = _dt.now().strftime("%Y%m%d_%H%M%S")
    dest_path = bdir / f"logistic_backup_{stamp}.db"
    dst = sqlite3.connect(str(dest_path))
    with dst:
        src.backup(dst)
    dst.close()
    return dest_path


def close_conn() -> None:
    global _conn
    if _conn is not None:
        _conn.commit()
        _conn.close()
        _conn = None


# ----------------------------------------------------------------------------
# المخطط الكامل لقاعدة البيانات
# ----------------------------------------------------------------------------
SCHEMA = """
CREATE TABLE IF NOT EXISTS settings (
    key   TEXT PRIMARY KEY,
    value TEXT
);

-- السنوات المالية
CREATE TABLE IF NOT EXISTS financial_years (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    year      INTEGER NOT NULL UNIQUE,
    date_from TEXT NOT NULL,
    date_to   TEXT NOT NULL,
    status    TEXT NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'closed')),
    notes     TEXT DEFAULT ''
);

-- العملاء
CREATE TABLE IF NOT EXISTS customers (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    code             TEXT NOT NULL DEFAULT '',
    name             TEXT NOT NULL,
    address          TEXT DEFAULT '',
    phone            TEXT DEFAULT '',
    opening_balance  REAL NOT NULL DEFAULT 0,
    notes            TEXT DEFAULT '',
    created_at       TEXT DEFAULT (datetime('now', 'localtime'))
);

-- الموظفون والسائقون
CREATE TABLE IF NOT EXISTS employees (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    code        TEXT NOT NULL DEFAULT '',
    name        TEXT NOT NULL,
    nationality TEXT DEFAULT '',
    phone       TEXT DEFAULT '',
    emp_type    TEXT NOT NULL DEFAULT 'driver' CHECK (emp_type IN ('driver', 'admin')),
    notes       TEXT DEFAULT '',
    created_at  TEXT DEFAULT (datetime('now', 'localtime'))
);

-- السيارات
CREATE TABLE IF NOT EXISTS vehicles (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    code              TEXT NOT NULL DEFAULT '',
    plate_number      TEXT NOT NULL DEFAULT '',
    vehicle_type      TEXT DEFAULT '',
    default_driver_id INTEGER REFERENCES employees(id) ON DELETE SET NULL,
    notes             TEXT DEFAULT '',
    created_at        TEXT DEFAULT (datetime('now', 'localtime'))
);

-- الخزائن
CREATE TABLE IF NOT EXISTS cashboxes (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    code            TEXT NOT NULL DEFAULT '',
    name            TEXT NOT NULL,
    created_date    TEXT NOT NULL,
    opening_balance REAL NOT NULL DEFAULT 0,
    notes           TEXT DEFAULT '',
    created_at      TEXT DEFAULT (datetime('now', 'localtime'))
);

-- البنوك
CREATE TABLE IF NOT EXISTS banks (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    code            TEXT NOT NULL DEFAULT '',
    name            TEXT NOT NULL,
    created_date    TEXT NOT NULL,
    account_number  TEXT DEFAULT '',
    iban            TEXT DEFAULT '',
    opening_balance REAL NOT NULL DEFAULT 0,
    notes           TEXT DEFAULT '',
    created_at      TEXT DEFAULT (datetime('now', 'localtime'))
);

-- فواتير النقل (الرأس)
CREATE TABLE IF NOT EXISTS invoices (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    number       INTEGER NOT NULL,
    date         TEXT NOT NULL,
    customer_id  INTEGER NOT NULL REFERENCES customers(id),
    notes        TEXT DEFAULT '',
    attachments  TEXT DEFAULT '[]',
    created_at   TEXT DEFAULT (datetime('now', 'localtime'))
);

-- نقلات الفاتورة (التفاصيل)
CREATE TABLE IF NOT EXISTS invoice_trips (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    invoice_id INTEGER NOT NULL REFERENCES invoices(id) ON DELETE CASCADE,
    vehicle_id INTEGER REFERENCES vehicles(id) ON DELETE SET NULL,
    driver_id  INTEGER REFERENCES employees(id) ON DELETE SET NULL,
    from_loc   TEXT DEFAULT '',
    to_loc     TEXT DEFAULT '',
    price      REAL NOT NULL DEFAULT 0,
    notes      TEXT DEFAULT ''
);

-- مصروفات النقلة المباشرة (تريب / بنزين / كارتة / أخرى)
CREATE TABLE IF NOT EXISTS trip_expenses (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    trip_id      INTEGER NOT NULL REFERENCES invoice_trips(id) ON DELETE CASCADE,
    expense_type TEXT NOT NULL DEFAULT 'other'
                 CHECK (expense_type IN ('trip', 'fuel', 'card', 'other')),
    amount       REAL NOT NULL DEFAULT 0,
    notes        TEXT DEFAULT ''
);

-- سندات القبض
CREATE TABLE IF NOT EXISTS receipt_vouchers (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    number       INTEGER NOT NULL,
    date         TEXT NOT NULL,
    account_kind TEXT NOT NULL CHECK (account_kind IN ('cashbox', 'bank')),
    account_id   INTEGER NOT NULL,
    voucher_type TEXT NOT NULL CHECK (voucher_type IN ('customer', 'other')),
    customer_id  INTEGER REFERENCES customers(id) ON DELETE SET NULL,
    amount       REAL NOT NULL DEFAULT 0,
    description  TEXT DEFAULT '',
    created_at   TEXT DEFAULT (datetime('now', 'localtime'))
);

-- سندات الدفع
CREATE TABLE IF NOT EXISTS payment_vouchers (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    number              INTEGER NOT NULL,
    date                TEXT NOT NULL,
    account_kind        TEXT NOT NULL CHECK (account_kind IN ('cashbox', 'bank')),
    account_id          INTEGER NOT NULL,
    voucher_type        TEXT NOT NULL
                        CHECK (voucher_type IN ('trip', 'advance', 'vehicle', 'general')),
    trip_id             INTEGER REFERENCES invoice_trips(id) ON DELETE SET NULL,
    employee_id         INTEGER REFERENCES employees(id) ON DELETE SET NULL,
    vehicle_id          INTEGER REFERENCES vehicles(id) ON DELETE SET NULL,
    vehicle_expense     TEXT DEFAULT '',
    amount              REAL NOT NULL DEFAULT 0,
    description         TEXT DEFAULT '',
    created_at          TEXT DEFAULT (datetime('now', 'localtime'))
);

-- الرواتب
CREATE TABLE IF NOT EXISTS payrolls (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    number            INTEGER NOT NULL,
    date              TEXT NOT NULL,
    employee_id       INTEGER NOT NULL REFERENCES employees(id),
    period_year       INTEGER NOT NULL,
    period_month      INTEGER NOT NULL,
    account_kind      TEXT NOT NULL CHECK (account_kind IN ('cashbox', 'bank')),
    account_id        INTEGER NOT NULL,
    base_salary       REAL NOT NULL DEFAULT 0,
    additions         REAL NOT NULL DEFAULT 0,
    additions_note    TEXT DEFAULT '',
    advance_deduction REAL NOT NULL DEFAULT 0,
    other_deductions  REAL NOT NULL DEFAULT 0,
    net_salary        REAL NOT NULL DEFAULT 0,
    notes             TEXT DEFAULT '',
    created_at        TEXT DEFAULT (datetime('now', 'localtime'))
);

-- تسويات السلف (خصم جزء/كامل من السلفة عند صرف الراتب)
CREATE TABLE IF NOT EXISTS advance_settlements (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    payment_voucher_id INTEGER NOT NULL REFERENCES payment_vouchers(id) ON DELETE CASCADE,
    payroll_id         INTEGER NOT NULL REFERENCES payrolls(id) ON DELETE CASCADE,
    amount             REAL NOT NULL DEFAULT 0
);

-- لقطات إغلاق السنوات المالية
CREATE TABLE IF NOT EXISTS year_snapshots (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    year_id    INTEGER NOT NULL UNIQUE REFERENCES financial_years(id) ON DELETE CASCADE,
    created_at TEXT DEFAULT (datetime('now', 'localtime')),
    data       TEXT NOT NULL DEFAULT '{}'
);

CREATE INDEX IF NOT EXISTS idx_trips_invoice ON invoice_trips(invoice_id);
CREATE INDEX IF NOT EXISTS idx_expenses_trip ON trip_expenses(trip_id);
CREATE INDEX IF NOT EXISTS idx_invoices_customer ON invoices(customer_id);
CREATE INDEX IF NOT EXISTS idx_invoices_date ON invoices(date);
CREATE INDEX IF NOT EXISTS idx_receipts_customer ON receipt_vouchers(customer_id);
CREATE INDEX IF NOT EXISTS idx_payments_trip ON payment_vouchers(trip_id);
CREATE INDEX IF NOT EXISTS idx_settlements_payroll ON advance_settlements(payroll_id);
CREATE INDEX IF NOT EXISTS idx_settlements_voucher ON advance_settlements(payment_voucher_id);
"""

DEFAULT_SETTINGS = {
    "company_name": "شركة النقل للخدمات اللوجستية",
    "company_phone": "",
    "company_address": "",
    "company_vat_note": "فاتورة نقل غير خاضعة لضريبة القيمة المضافة (ZATCA)",
    "currency": "ر.س",
}


def init_db() -> None:
    """إنشاء الجداول (إن لم تكن موجودة) + الإعدادات الافتراضية."""
    conn = get_conn()
    conn.executescript(SCHEMA)
    for key, value in DEFAULT_SETTINGS.items():
        conn.execute(
            "INSERT INTO settings(key, value) VALUES(?, ?) "
            "ON CONFLICT(key) DO NOTHING",
            (key, value),
        )
    conn.commit()
