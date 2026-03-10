from __future__ import annotations

import os
from pymongo import MongoClient


def round2(value: float) -> float:
    try:
        return round(float(value or 0) + 1e-12, 2)
    except Exception:
        return 0.0


def main() -> None:
    mongo_uri = os.environ.get("MONGO_URI", "mongodb://127.0.0.1:27017")
    db_name = os.environ.get("DB_NAME", "shop_lts-repair_lts-repair_d2063f")

    client = MongoClient(mongo_uri, serverSelectionTimeoutMS=5000)
    client.admin.command("ping")
    db = client[db_name]

    orders = list(
        db.parts_orders.find(
            {"is_active": True},
            {"_id": 1, "payment_status": 1, "items": 1, "non_inventory_amounts": 1},
        )
    )

    bad_paid_no_payment = []
    bad_status = []
    paid_with_payment = 0

    for order in orders:
        oid = order.get("_id")
        total_amount = 0.0

        for item in (order.get("items") or []):
            if not isinstance(item, dict):
                continue
            qty = max(0, int(float(item.get("quantity") or 0)))
            price = max(0.0, float(item.get("price") or 0))
            total_amount += qty * price

        for line in (order.get("non_inventory_amounts") or []):
            if not isinstance(line, dict):
                continue
            total_amount += max(0.0, float(line.get("amount") or 0))

        total_amount = round2(total_amount)

        payments = list(
            db.parts_order_payments.find(
                {"parts_order_id": oid, "is_active": True},
                {"amount": 1},
            )
        )
        paid_amount = round2(sum(round2(p.get("amount") or 0) for p in payments))
        has_payment = len(payments) > 0

        if total_amount <= 0:
            expected = "paid"
        elif paid_amount <= 0:
            expected = "unpaid"
        elif paid_amount + 0.01 >= total_amount:
            expected = "paid"
        else:
            expected = "partially_paid"

        status = str(order.get("payment_status") or "")
        if status != expected:
            bad_status.append((str(oid), status, expected, total_amount, paid_amount, len(payments)))

        if status == "paid" and total_amount > 0 and not has_payment:
            bad_paid_no_payment.append((str(oid), total_amount, paid_amount))

        if status == "paid" and has_payment:
            paid_with_payment += 1

    print("db", db_name)
    print("orders_total", len(orders))
    print("paid_no_payment_count", len(bad_paid_no_payment))
    print("status_mismatch_count", len(bad_status))
    print("paid_with_payment_count", paid_with_payment)
    print("sample_status_mismatch", bad_status[:5])
    print("sample_paid_no_payment", bad_paid_no_payment[:5])


if __name__ == "__main__":
    main()
