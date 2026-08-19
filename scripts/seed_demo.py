# -*- coding: utf-8 -*-
"""
تعبئة بيانات تجريبية واقعية لاستكشاف النظام.

تشغيل:  python scripts/seed_demo.py
(يعمل فقط إذا لم توجد سنوات مالية — لتجنب التكرار)
"""
from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core import calc, db, repo  # noqa: E402


def seed(conn) -> dict:
    y = date.today().year
    ids: dict = {}
    repo.save_year(conn, {"year": y, "date_from": f"{y}-01-01",
                          "date_to": f"{y}-12-31", "notes": "سنة تشغيلية"})
    ids["cust1"] = repo.save_customer(conn, {
        "name": "مؤسسة الرياض للإنشاءات", "phone": "0551112222",
        "address": "الرياض — حي الصناعية", "opening_balance": 15000,
        "notes": "عميل مشاريع"})
    ids["cust2"] = repo.save_customer(conn, {
        "name": "شركة مكة للمقاولات", "phone": "0563334444",
        "address": "مكة المكرمة", "opening_balance": 0, "notes": ""})
    ids["drv1"] = repo.save_employee(conn, {
        "name": "أحمد الغامدي", "nationality": "سعودي", "phone": "0501111111",
        "emp_type": "driver", "notes": ""})
    ids["drv2"] = repo.save_employee(conn, {
        "name": "خالد المصري", "nationality": "مصري", "phone": "0502222222",
        "emp_type": "driver", "notes": ""})
    ids["adm1"] = repo.save_employee(conn, {
        "name": "سالم الحربي", "nationality": "سعودي", "phone": "0503333333",
        "emp_type": "admin", "notes": "مسؤول حركة"})
    ids["veh1"] = repo.save_vehicle(conn, {
        "plate_number": "أ ب ج 1234", "vehicle_type": "تريلة",
        "default_driver_id": ids["drv1"], "notes": ""})
    ids["veh2"] = repo.save_vehicle(conn, {
        "plate_number": "د هـ و 5678", "vehicle_type": "سطحة",
        "default_driver_id": ids["drv2"], "notes": ""})
    ids["cb"] = repo.save_account(conn, "cashbox", {
        "name": "الخزينة الرئيسية", "created_date": f"{y}-01-01",
        "opening_balance": 20000, "notes": ""})
    ids["bnk"] = repo.save_account(conn, "bank", {
        "name": "بنك الراجحي — الجاري", "created_date": f"{y}-01-01",
        "account_number": "0021156688",
        "iban": "SA00 8000 0000 6080 1016 7519",
        "opening_balance": 80000, "notes": ""})

    d = (lambda m, day: f"{y}-{m:02d}-{day:02d}")
    inv1 = repo.save_invoice(conn, {
        "date": d(2, 10), "customer_id": ids["cust1"], "notes": "مشروع برج الملك",
        "attachments": [],
        "trips": [
            {"vehicle_id": ids["veh1"], "driver_id": ids["drv1"],
             "from_loc": "الرياض", "to_loc": "الدمام", "price": 4500, "notes": "",
             "expenses": [{"expense_type": "trip", "amount": 350, "notes": ""},
                          {"expense_type": "fuel", "amount": 260, "notes": ""},
                          {"expense_type": "card", "amount": 90, "notes": ""}]},
            {"vehicle_id": ids["veh2"], "driver_id": ids["drv2"],
             "from_loc": "الرياض", "to_loc": "القصيم", "price": 3000, "notes": "",
             "expenses": [{"expense_type": "trip", "amount": 250, "notes": ""},
                          {"expense_type": "fuel", "amount": 180, "notes": ""}]},
        ]})
    inv2 = repo.save_invoice(conn, {
        "date": d(3, 5), "customer_id": ids["cust2"], "notes": "",
        "attachments": [],
        "trips": [
            {"vehicle_id": ids["veh1"], "driver_id": ids["drv1"],
             "from_loc": "جدة", "to_loc": "مكة", "price": 1800, "notes": "",
             "expenses": [{"expense_type": "trip", "amount": 150, "notes": ""},
                          {"expense_type": "fuel", "amount": 100, "notes": ""}]},
        ]})
    repo.save_receipt(conn, {
        "date": d(2, 25), "account_kind": "cashbox", "account_id": ids["cb"],
        "voucher_type": "customer", "customer_id": ids["cust1"],
        "amount": 5000, "description": "دفعة تحت الحساب"})
    repo.save_receipt(conn, {
        "date": d(3, 12), "account_kind": "bank", "account_id": ids["bnk"],
        "voucher_type": "other", "customer_id": None,
        "amount": 750, "description": "بيع خردة سيارات"})
    trips = conn.execute(
        "SELECT id, invoice_id FROM invoice_trips WHERE invoice_id IN (?, ?) "
        "ORDER BY id", (inv1, inv2)).fetchall()
    repo.save_payment(conn, {
        "date": d(3, 1), "account_kind": "cashbox", "account_id": ids["cb"],
        "voucher_type": "trip", "trip_id": trips[0]["id"],
        "amount": 220, "description": "رسوم تفريغ بالدمام"})
    adv = repo.save_payment(conn, {
        "date": d(3, 3), "account_kind": "cashbox", "account_id": ids["cb"],
        "voucher_type": "advance", "employee_id": ids["drv1"],
        "amount": 1000, "description": "سلفة ظروف خاصة"})
    repo.save_payment(conn, {
        "date": d(3, 8), "account_kind": "bank", "account_id": ids["bnk"],
        "voucher_type": "vehicle", "vehicle_id": ids["veh1"],
        "vehicle_expense": "maintenance", "amount": 850,
        "description": "صيانة مكيف"})
    repo.save_payment(conn, {
        "date": d(3, 15), "account_kind": "cashbox", "account_id": ids["cb"],
        "voucher_type": "general", "amount": 1200,
        "description": "إيجار المكتب شهري"})
    repo.save_payroll(conn, {
        "date": d(3, 28), "employee_id": ids["drv1"], "period_year": y,
        "period_month": 3, "account_kind": "cashbox", "account_id": ids["cb"],
        "base_salary": 3500, "additions": 300, "additions_note": "مكافئة التزام",
        "other_deductions": 0, "settlements": [(adv, 400)],
        "notes": ""})
    repo.save_payroll(conn, {
        "date": d(3, 28), "employee_id": ids["drv2"], "period_year": y,
        "period_month": 3, "account_kind": "cashbox", "account_id": ids["cb"],
        "base_salary": 3200, "additions": 0, "other_deductions": 150,
        "settlements": [], "notes": "خصم يومي غياب"})
    ids["inv1"], ids["inv2"], ids["adv"] = inv1, inv2, adv
    return ids


def main() -> None:
    db.init_db()
    conn = db.get_conn()
    if repo.list_years(conn):
        print("توجد بيانات مسبقاً — لم يتم تنفيذ التعبئة (لتجنب التكرار).")
        print(f"قاعدة البيانات: {db.db_path()}")
        return
    seed(conn)
    print("✅ تمت تعبئة البيانات التجريبية بنجاح.")
    print(f"قاعدة البيانات: {db.db_path()}")


if __name__ == "__main__":
    main()
