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

-- العملاء (مع الحزمة الضريبية والعنوان الوطني — مطابقة لنسخة الويب)
CREATE TABLE IF NOT EXISTS customers (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    code             TEXT NOT NULL DEFAULT '',
    name             TEXT NOT NULL,
    address          TEXT DEFAULT '',
    phone            TEXT DEFAULT '',
    opening_balance  REAL NOT NULL DEFAULT 0,
    notes            TEXT DEFAULT '',
    tax_number       TEXT DEFAULT '',
    commercial_reg   TEXT DEFAULT '',
    entity_type      TEXT DEFAULT 'company',
    tax_status       TEXT DEFAULT 'taxable',
    country          TEXT DEFAULT 'SA',
    region           TEXT DEFAULT '',
    city             TEXT DEFAULT '',
    district         TEXT DEFAULT '',
    street           TEXT DEFAULT '',
    building_no      TEXT DEFAULT '',
    postal_code      TEXT DEFAULT '',
    additional_no    TEXT DEFAULT '',
    created_at       TEXT DEFAULT (datetime('now', 'localtime'))
);

-- الموردون (دورة المشتريات الآجلة والنقدية)
CREATE TABLE IF NOT EXISTS suppliers (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    code             TEXT NOT NULL DEFAULT '',
    name             TEXT NOT NULL,
    name_en          TEXT DEFAULT '',
    phone            TEXT DEFAULT '',
    email            TEXT DEFAULT '',
    contact_person   TEXT DEFAULT '',
    address          TEXT DEFAULT '',
    opening_balance  REAL NOT NULL DEFAULT 0,   -- موجب = مستحق له علينا
    notes            TEXT DEFAULT '',
    tax_number       TEXT DEFAULT '',
    commercial_reg   TEXT DEFAULT '',
    entity_type      TEXT DEFAULT 'company',
    tax_status       TEXT DEFAULT 'taxable',
    country          TEXT DEFAULT 'SA',
    region           TEXT DEFAULT '',
    city             TEXT DEFAULT '',
    district         TEXT DEFAULT '',
    street           TEXT DEFAULT '',
    building_no      TEXT DEFAULT '',
    postal_code      TEXT DEFAULT '',
    additional_no    TEXT DEFAULT '',
    payment_terms    INTEGER NOT NULL DEFAULT 0,
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
    base_salary REAL NOT NULL DEFAULT 0,
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

-- فواتير النقل (الرأس) — بنسبة ضريبة لكل فاتورة
CREATE TABLE IF NOT EXISTS invoices (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    number           INTEGER NOT NULL,
    date             TEXT NOT NULL,
    customer_id      INTEGER NOT NULL REFERENCES customers(id),
    vat_rate         REAL NOT NULL DEFAULT 15,
    notes            TEXT DEFAULT '',
    attachments      TEXT DEFAULT '[]',
    container_number TEXT DEFAULT '',
    created_at       TEXT DEFAULT (datetime('now', 'localtime'))
);

-- نقلات الفاتورة (التفاصيل): عدد النقلات × سعر الوحدة + أرقام الحاويات
CREATE TABLE IF NOT EXISTS invoice_trips (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    invoice_id        INTEGER NOT NULL REFERENCES invoices(id) ON DELETE CASCADE,
    vehicle_id        INTEGER REFERENCES vehicles(id) ON DELETE SET NULL,
    driver_id         INTEGER REFERENCES employees(id) ON DELETE SET NULL,
    from_loc          TEXT DEFAULT '',
    to_loc            TEXT DEFAULT '',
    qty               REAL NOT NULL DEFAULT 1,
    unit_price        REAL NOT NULL DEFAULT 0,
    price             REAL NOT NULL DEFAULT 0,
    container_numbers TEXT NOT NULL DEFAULT '[]',
    notes             TEXT DEFAULT ''
);

-- مصروفات النقلة المباشرة (تريب / بنزين / كارتة / أخرى) + مصدر التمويل
CREATE TABLE IF NOT EXISTS trip_expenses (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    trip_id       INTEGER NOT NULL REFERENCES invoice_trips(id) ON DELETE CASCADE,
    expense_type  TEXT NOT NULL DEFAULT 'other'
                  CHECK (expense_type IN ('trip', 'fuel', 'card', 'other')),
    qty           REAL NOT NULL DEFAULT 1,
    unit_amount   REAL NOT NULL DEFAULT 0,
    amount        REAL NOT NULL DEFAULT 0,
    source        TEXT NOT NULL DEFAULT 'cash'
                  CHECK (source IN ('cash', 'driver', 'supplier', 'customer')),
    account_kind  TEXT CHECK (account_kind IS NULL OR account_kind IN ('cashbox', 'bank')),
    account_id    INTEGER,
    supplier_name TEXT DEFAULT '',
    notes         TEXT DEFAULT ''
);

-- فواتير المشتريات (رأس): نقدية تُدفع فوراً أو آجلة تُرحَّل على المورّد
CREATE TABLE IF NOT EXISTS purchase_invoices (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    number        INTEGER NOT NULL,
    date          TEXT NOT NULL,
    purchase_type TEXT NOT NULL DEFAULT 'credit' CHECK (purchase_type IN ('credit', 'cash')),
    supplier_id   INTEGER REFERENCES suppliers(id) ON DELETE SET NULL,
    supplier_ref  TEXT DEFAULT '',
    expense_category TEXT NOT NULL DEFAULT 'other',
    vehicle_id    INTEGER REFERENCES vehicles(id) ON DELETE SET NULL,
    account_kind  TEXT CHECK (account_kind IS NULL OR account_kind IN ('cashbox', 'bank')),
    account_id    INTEGER,
    vat_rate      REAL NOT NULL DEFAULT 15,
    vat_included  INTEGER NOT NULL DEFAULT 0,
    notes         TEXT DEFAULT '',
    created_at    TEXT DEFAULT (datetime('now', 'localtime'))
);

-- بنود فاتورة المشتريات (نسبة ضريبة لكل بند تسمح ببنود معفاة)
CREATE TABLE IF NOT EXISTS purchase_items (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    invoice_id INTEGER NOT NULL REFERENCES purchase_invoices(id) ON DELETE CASCADE,
    item_name  TEXT NOT NULL DEFAULT '',
    unit       TEXT DEFAULT '',
    qty        REAL NOT NULL DEFAULT 1,
    unit_price REAL NOT NULL DEFAULT 0,
    vat_rate   REAL NOT NULL DEFAULT 15,
    notes      TEXT DEFAULT ''
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

-- سندات الدفع (سبعة توجيهات كما في نسخة الويب)
CREATE TABLE IF NOT EXISTS payment_vouchers (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    number              INTEGER NOT NULL,
    date                TEXT NOT NULL,
    account_kind        TEXT NOT NULL CHECK (account_kind IN ('cashbox', 'bank')),
    account_id          INTEGER NOT NULL,
    voucher_type        TEXT NOT NULL
                        CHECK (voucher_type IN ('trip', 'advance', 'vehicle', 'general',
                                                'supplier', 'purchase', 'owner')),
    trip_id             INTEGER REFERENCES invoice_trips(id) ON DELETE SET NULL,
    employee_id         INTEGER REFERENCES employees(id) ON DELETE SET NULL,
    vehicle_id          INTEGER REFERENCES vehicles(id) ON DELETE SET NULL,
    vehicle_expense     TEXT DEFAULT '',
    supplier_id         INTEGER REFERENCES suppliers(id) ON DELETE SET NULL,
    purchase_invoice_id INTEGER REFERENCES purchase_invoices(id) ON DELETE SET NULL,
    source_expense_id   INTEGER REFERENCES trip_expenses(id) ON DELETE SET NULL,
    quantity            REAL NOT NULL DEFAULT 1,
    unit_amount         REAL NOT NULL DEFAULT 0,
    amount              REAL NOT NULL DEFAULT 0,
    description         TEXT DEFAULT '',
    created_at          TEXT DEFAULT (datetime('now', 'localtime'))
);

-- الإشعارات الدائنة والمدينة (بديل تعديل الفاتورة بعد إصدارها)
CREATE TABLE IF NOT EXISTS credit_debit_notes (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    number      INTEGER NOT NULL,
    note_type   TEXT NOT NULL CHECK (note_type IN ('credit', 'debit')),
    invoice_id  INTEGER NOT NULL REFERENCES invoices(id),
    customer_id INTEGER NOT NULL REFERENCES customers(id),
    date        TEXT NOT NULL,
    amount      REAL NOT NULL DEFAULT 0 CHECK (amount > 0),
    vat_rate    REAL NOT NULL DEFAULT 15,
    reason      TEXT NOT NULL DEFAULT '',
    created_at  TEXT DEFAULT (datetime('now', 'localtime'))
);

-- ربط الإشعار الدائن بالنقلات المرتجعة (يمنع إرجاع النقلة مرتين)
CREATE TABLE IF NOT EXISTS credit_note_trips (
    id      INTEGER PRIMARY KEY AUTOINCREMENT,
    note_id INTEGER NOT NULL REFERENCES credit_debit_notes(id) ON DELETE CASCADE,
    trip_id INTEGER NOT NULL UNIQUE REFERENCES invoice_trips(id) ON DELETE CASCADE
);

-- الرواتب
CREATE TABLE IF NOT EXISTS payrolls (
    id                   INTEGER PRIMARY KEY AUTOINCREMENT,
    number               INTEGER NOT NULL,
    date                 TEXT NOT NULL,
    employee_id          INTEGER NOT NULL REFERENCES employees(id),
    period_year          INTEGER NOT NULL,
    period_month         INTEGER NOT NULL,
    account_kind         TEXT NOT NULL CHECK (account_kind IN ('cashbox', 'bank')),
    account_id           INTEGER NOT NULL,
    base_salary          REAL NOT NULL DEFAULT 0,
    additions            REAL NOT NULL DEFAULT 0,
    additions_note       TEXT DEFAULT '',
    advance_deduction    REAL NOT NULL DEFAULT 0,
    other_deductions     REAL NOT NULL DEFAULT 0,
    deduction_deduction  REAL NOT NULL DEFAULT 0,
    net_salary           REAL NOT NULL DEFAULT 0,
    notes                TEXT DEFAULT '',
    created_at           TEXT DEFAULT (datetime('now', 'localtime'))
);

-- تسويات السلف (خصم جزء/كامل من السلفة عند صرف الراتب)
CREATE TABLE IF NOT EXISTS advance_settlements (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    payment_voucher_id INTEGER NOT NULL REFERENCES payment_vouchers(id) ON DELETE CASCADE,
    payroll_id         INTEGER NOT NULL REFERENCES payrolls(id) ON DELETE CASCADE,
    amount             REAL NOT NULL DEFAULT 0
);

-- بنود الخصومات المُتتبَّعة على الموظف/السائق
CREATE TABLE IF NOT EXISTS employee_deductions (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    number      INTEGER NOT NULL,
    date        TEXT NOT NULL,
    employee_id INTEGER NOT NULL REFERENCES employees(id),
    amount      REAL NOT NULL DEFAULT 0 CHECK (amount > 0),
    reason      TEXT NOT NULL DEFAULT '',
    notes       TEXT DEFAULT '',
    created_at  TEXT DEFAULT (datetime('now', 'localtime'))
);

-- تسويات بنود الخصومات في المسيرات
CREATE TABLE IF NOT EXISTS deduction_settlements (
    id                    INTEGER PRIMARY KEY AUTOINCREMENT,
    employee_deduction_id INTEGER NOT NULL REFERENCES employee_deductions(id) ON DELETE CASCADE,
    payroll_id            INTEGER NOT NULL REFERENCES payrolls(id) ON DELETE CASCADE,
    amount                REAL NOT NULL DEFAULT 0
);

-- الأرصدة الافتتاحية المرحّلة عند إنشاء سنة مالية جديدة
CREATE TABLE IF NOT EXISTS year_opening_balances (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    year_id     INTEGER NOT NULL REFERENCES financial_years(id) ON DELETE CASCADE,
    entity_type TEXT NOT NULL CHECK (entity_type IN ('customer', 'cashbox', 'bank', 'supplier')),
    entity_id   INTEGER NOT NULL,
    balance     REAL NOT NULL DEFAULT 0,
    UNIQUE (year_id, entity_type, entity_id)
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
CREATE INDEX IF NOT EXISTS idx_pitems_invoice ON purchase_items(invoice_id);
CREATE INDEX IF NOT EXISTS idx_pinv_supplier ON purchase_invoices(supplier_id);
CREATE INDEX IF NOT EXISTS idx_pinv_date ON purchase_invoices(date);
CREATE INDEX IF NOT EXISTS idx_notes_customer_date ON credit_debit_notes(customer_id, date);
CREATE INDEX IF NOT EXISTS idx_deductions_employee ON employee_deductions(employee_id);
CREATE INDEX IF NOT EXISTS idx_dedset_payroll ON deduction_settlements(payroll_id);
"""


# فهارس على أعمدة تُضاف بالترحيل — تُنفَّذ بعد إضافة الأعمدة حتى لا تفشل
# على قاعدة بيانات قديمة لا تملك العمود بعد.
SCHEMA_POST = """
CREATE INDEX IF NOT EXISTS idx_payments_supplier ON payment_vouchers(supplier_id);
CREATE INDEX IF NOT EXISTS idx_payments_purchase ON payment_vouchers(purchase_invoice_id);
CREATE INDEX IF NOT EXISTS idx_expenses_source ON trip_expenses(source);
"""

DEFAULT_SETTINGS = {
    "company_name": "شركة النقل للخدمات اللوجستية",
    "company_phone": "",
    "company_address": "",
    "company_email": "",
    # الحزمة الضريبية للمنشأة (مطابقة لنسخة الويب)
    "company_tax_number": "",
    "company_commercial_reg": "",
    "company_entity_type": "company",
    "company_tax_status": "taxable",
    "company_country": "SA",
    "company_region": "",
    "company_city": "",
    "company_district": "",
    "company_street": "",
    "company_building_no": "",
    "company_postal_code": "",
    "company_additional_no": "",
    "vat_rate": "15",
    "vat_note": "الأسعار تشمل ضريبة القيمة المضافة",
    "currency": "ر.س",
}


# ----------------------------------------------------------------------------
# الترحيل التصاعدي لقواعد البيانات القائمة (آمن التكرار)
#
# CREATE TABLE IF NOT EXISTS لا يضيف أعمدة لجدول موجود؛ لذلك تُضاف الأعمدة
# الجديدة بـ ALTER TABLE، ويُعاد بناء الجداول التي تغيّرت قيود CHECK فيها.
# ----------------------------------------------------------------------------
COLUMN_MIGRATIONS: list[tuple[str, str, str]] = [
    ("customers", "tax_number", "TEXT DEFAULT ''"),
    ("customers", "commercial_reg", "TEXT DEFAULT ''"),
    ("customers", "entity_type", "TEXT DEFAULT 'company'"),
    ("customers", "tax_status", "TEXT DEFAULT 'taxable'"),
    ("customers", "country", "TEXT DEFAULT 'SA'"),
    ("customers", "region", "TEXT DEFAULT ''"),
    ("customers", "city", "TEXT DEFAULT ''"),
    ("customers", "district", "TEXT DEFAULT ''"),
    ("customers", "street", "TEXT DEFAULT ''"),
    ("customers", "building_no", "TEXT DEFAULT ''"),
    ("customers", "postal_code", "TEXT DEFAULT ''"),
    ("customers", "additional_no", "TEXT DEFAULT ''"),
    ("employees", "base_salary", "REAL NOT NULL DEFAULT 0"),
    ("invoices", "vat_rate", "REAL NOT NULL DEFAULT 15"),
    ("invoices", "container_number", "TEXT DEFAULT ''"),
    ("invoice_trips", "qty", "REAL NOT NULL DEFAULT 1"),
    ("invoice_trips", "unit_price", "REAL NOT NULL DEFAULT 0"),
    ("invoice_trips", "container_numbers", "TEXT NOT NULL DEFAULT '[]'"),
    ("trip_expenses", "qty", "REAL NOT NULL DEFAULT 1"),
    ("trip_expenses", "unit_amount", "REAL NOT NULL DEFAULT 0"),
    ("trip_expenses", "source", "TEXT NOT NULL DEFAULT 'cash'"),
    ("trip_expenses", "account_kind", "TEXT"),
    ("trip_expenses", "account_id", "INTEGER"),
    ("trip_expenses", "supplier_name", "TEXT DEFAULT ''"),
    ("payment_vouchers", "supplier_id", "INTEGER"),
    ("payment_vouchers", "purchase_invoice_id", "INTEGER"),
    ("payment_vouchers", "source_expense_id", "INTEGER"),
    ("payment_vouchers", "quantity", "REAL NOT NULL DEFAULT 1"),
    ("payment_vouchers", "unit_amount", "REAL NOT NULL DEFAULT 0"),
    ("payrolls", "deduction_deduction", "REAL NOT NULL DEFAULT 0"),
    # بيانات التواصل والائتمان (مطابقة لنسخة الويب)
    ("customers", "name_en", "TEXT DEFAULT ''"),
    ("customers", "email", "TEXT DEFAULT ''"),
    ("customers", "contact_person", "TEXT DEFAULT ''"),
    ("customers", "credit_limit", "REAL NOT NULL DEFAULT 0"),
    ("customers", "payment_terms", "INTEGER NOT NULL DEFAULT 0"),
    ("suppliers", "name_en", "TEXT DEFAULT ''"),
    ("suppliers", "email", "TEXT DEFAULT ''"),
    ("suppliers", "contact_person", "TEXT DEFAULT ''"),
    ("suppliers", "address", "TEXT DEFAULT ''"),
]


def _table_columns(conn: sqlite3.Connection, table: str) -> set[str]:
    return {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}


def _table_sql(conn: sqlite3.Connection, table: str) -> str:
    r = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name=?", (table,)
    ).fetchone()
    return r[0] if r and r[0] else ""


def _migrate_columns(conn: sqlite3.Connection) -> None:
    """إضافة الأعمدة الجديدة للجداول القائمة."""
    for table, column, declaration in COLUMN_MIGRATIONS:
        if not _table_sql(conn, table):
            continue
        if column in _table_columns(conn, table):
            continue
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {declaration}")


def _migrate_payment_voucher_types(conn: sqlite3.Connection) -> None:
    """إعادة بناء سندات الدفع إن كان قيد CHECK قديماً (بلا الأنواع الجديدة).

    SQLite لا تسمح بتعديل قيد CHECK؛ الحل الآمن = جدول جديد + نقل + إعادة تسمية.
    """
    sql = _table_sql(conn, "payment_vouchers")
    if not sql or "'owner'" in sql:
        return
    conn.execute("PRAGMA foreign_keys = OFF")
    try:
        conn.execute("DROP TABLE IF EXISTS payment_vouchers_new")
        conn.execute(
            """CREATE TABLE payment_vouchers_new (
                id                  INTEGER PRIMARY KEY AUTOINCREMENT,
                number              INTEGER NOT NULL,
                date                TEXT NOT NULL,
                account_kind        TEXT NOT NULL CHECK (account_kind IN ('cashbox', 'bank')),
                account_id          INTEGER NOT NULL,
                voucher_type        TEXT NOT NULL
                                    CHECK (voucher_type IN ('trip', 'advance', 'vehicle',
                                        'general', 'supplier', 'purchase', 'owner')),
                trip_id             INTEGER,
                employee_id         INTEGER,
                vehicle_id          INTEGER,
                vehicle_expense     TEXT DEFAULT '',
                supplier_id         INTEGER,
                purchase_invoice_id INTEGER,
                source_expense_id   INTEGER,
                quantity            REAL NOT NULL DEFAULT 1,
                unit_amount         REAL NOT NULL DEFAULT 0,
                amount              REAL NOT NULL DEFAULT 0,
                description         TEXT DEFAULT '',
                created_at          TEXT DEFAULT (datetime('now', 'localtime'))
            )"""
        )
        old = _table_columns(conn, "payment_vouchers")
        cols = [c for c in (
            "id", "number", "date", "account_kind", "account_id", "voucher_type",
            "trip_id", "employee_id", "vehicle_id", "vehicle_expense",
            "supplier_id", "purchase_invoice_id", "source_expense_id",
            "quantity", "unit_amount", "amount", "description", "created_at",
        ) if c in old]
        joiner = ", ".join(cols)
        conn.execute(
            f"INSERT INTO payment_vouchers_new ({joiner}) SELECT {joiner} FROM payment_vouchers"
        )
        conn.execute("DROP TABLE payment_vouchers")
        conn.execute("ALTER TABLE payment_vouchers_new RENAME TO payment_vouchers")
    finally:
        conn.execute("PRAGMA foreign_keys = ON")


def _migrate_legacy_amounts(conn: sqlite3.Connection) -> None:
    """تعبئة qty/unit_price من الإجمالي القديم حتى لا تنكسر التقارير.

    البيانات المسجّلة قبل إضافة الكميّات تملك price/amount إجماليين؛
    تُعامل كوحدة واحدة بسعرها الكامل.
    """
    conn.execute(
        "UPDATE invoice_trips SET unit_price = price "
        "WHERE (unit_price IS NULL OR unit_price = 0) AND price > 0"
    )
    conn.execute(
        "UPDATE trip_expenses SET unit_amount = amount "
        "WHERE (unit_amount IS NULL OR unit_amount = 0) AND amount > 0"
    )
    conn.execute(
        "UPDATE payment_vouchers SET unit_amount = amount "
        "WHERE (unit_amount IS NULL OR unit_amount = 0) AND amount > 0"
    )


def migrate(conn: sqlite3.Connection) -> None:
    """كل خطوات الترحيل بترتيب آمن."""
    conn.executescript(SCHEMA)
    _migrate_columns(conn)
    _migrate_payment_voucher_types(conn)
    _migrate_legacy_amounts(conn)
    conn.executescript(SCHEMA_POST)
    conn.commit()


def init_db() -> None:
    """إنشاء الجداول (إن لم تكن موجودة) + الترحيل + الإعدادات الافتراضية."""
    conn = get_conn()
    migrate(conn)
    for key, value in DEFAULT_SETTINGS.items():
        conn.execute(
            "INSERT INTO settings(key, value) VALUES(?, ?) "
            "ON CONFLICT(key) DO NOTHING",
            (key, value),
        )
    conn.commit()
