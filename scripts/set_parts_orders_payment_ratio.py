from __future__ import annotations

import argparse
import os
import random
from datetime import datetime, timezone

from pymongo import MongoClient


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def round2(value: float) -> float:
    try:
        return round(float(value or 0) + 1e-12, 2)
    except Exception:
        return 0.0


def parse_int(value, default: int = 0) -> int:
    try:
        return int(value)
    except Exception:
        return default


def parse_float(value, default: float = 0.0) -> float:
    try:
        return float(value)
    except Exception:
        return default


def discover_target_db(client: MongoClient, explicit_db_name: str | None) -> str:
    if explicit_db_name:
        return explicit_db_name

    candidates: list[str] = []
    for db_name in client.list_database_names():
        db = client[db_name]
        collections = set(db.list_collection_names())
        if "parts_orders" in collections and db.parts_orders.count_documents({}) > 0:
            candidates.append(db_name)

    if not candidates:
        raise RuntimeError("No database with non-empty 'parts_orders' collection found. Use --db-name.")

    if len(candidates) > 1:
        raise RuntimeError(
            "More than one DB has non-empty 'parts_orders': "
            + ", ".join(candidates)
            + ". Use --db-name to select target."
        )

    return candidates[0]


def order_total_amount(order_doc: dict) -> float:
    items_amount = 0.0
    for item in (order_doc.get("items") or []):
        if not isinstance(item, dict):
            continue
        qty = max(0, parse_int(item.get("quantity"), default=0))
        price = max(0.0, parse_float(item.get("price"), default=0.0))
        items_amount += qty * price

    non_inventory_amount = 0.0
    for line in (order_doc.get("non_inventory_amounts") or []):
        if not isinstance(line, dict):
            continue
        non_inventory_amount += max(0.0, parse_float(line.get("amount"), default=0.0))

    return round2(items_amount + non_inventory_amount)


def pick_partial_amount(total_amount: float) -> float:
    total = round2(total_amount)
    if total <= 0.01:
        return 0.0

    ratio = random.uniform(0.2, 0.8)
    amount = round2(total * ratio)

    if amount <= 0:
        amount = 0.01
    if amount >= total:
        amount = round2(total - 0.01)
    if amount <= 0:
        return 0.0

    return amount


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Set parts orders payment distribution (paid/partially paid/unpaid)."
    )
    parser.add_argument("--ratio-paid", type=float, default=0.25, help="Target paid ratio (default 0.25)")
    parser.add_argument("--ratio-partial", type=float, default=0.25, help="Target partial ratio (default 0.25)")
    parser.add_argument("--db-name", type=str, default=None, help="Target Mongo database name")
    parser.add_argument("--seed", type=int, default=None, help="Random seed")
    parser.add_argument("--dry-run", action="store_true", help="Only print plan, do not update")
    args = parser.parse_args()

    if args.ratio_paid < 0 or args.ratio_partial < 0:
        raise SystemExit("Ratios must be >= 0")
    if args.ratio_paid + args.ratio_partial > 1:
        raise SystemExit("ratio-paid + ratio-partial cannot exceed 1")

    if args.seed is not None:
        random.seed(args.seed)

    mongo_uri = os.environ.get("MONGO_URI", "mongodb://127.0.0.1:27017")
    client = MongoClient(mongo_uri, serverSelectionTimeoutMS=5000)
    client.admin.command("ping")

    db_name = discover_target_db(client, args.db_name)
    db = client[db_name]

    active_orders = list(
        db.parts_orders.find(
            {"is_active": {"$ne": False}},
            {
                "_id": 1,
                "shop_id": 1,
                "tenant_id": 1,
                "items": 1,
                "non_inventory_amounts": 1,
                "created_by": 1,
                "updated_by": 1,
            },
        )
    )

    if not active_orders:
        print(f"Target DB: {db_name}")
        print("No active parts orders found. Nothing to update.")
        return

    order_meta = []
    for order in active_orders:
        total = order_total_amount(order)
        order_meta.append(
            {
                "_id": order.get("_id"),
                "shop_id": order.get("shop_id"),
                "tenant_id": order.get("tenant_id"),
                "created_by": order.get("created_by") or order.get("updated_by"),
                "total": total,
            }
        )

    payable_orders = [x for x in order_meta if x.get("total", 0) > 0]
    partial_pool = [x for x in payable_orders if x.get("total", 0) > 0.01]

    payable_count = len(payable_orders)
    target_paid = int(round(payable_count * args.ratio_paid))
    target_partial = int(round(payable_count * args.ratio_partial))

    if target_partial > len(partial_pool):
        target_partial = len(partial_pool)

    partial_selected = random.sample(partial_pool, target_partial) if target_partial > 0 else []
    partial_ids = {x["_id"] for x in partial_selected}

    paid_pool = [x for x in payable_orders if x.get("_id") not in partial_ids]
    if target_paid > len(paid_pool):
        target_paid = len(paid_pool)
    paid_selected = random.sample(paid_pool, target_paid) if target_paid > 0 else []
    paid_ids = {x["_id"] for x in paid_selected}

    now = utcnow()

    planned_payments = []
    for row in paid_selected:
        total = round2(row.get("total", 0.0))
        if total <= 0:
            continue
        planned_payments.append(
            {
                "parts_order_id": row["_id"],
                "shop_id": row.get("shop_id"),
                "tenant_id": row.get("tenant_id"),
                "amount": total,
                "payment_method": random.choice(["cash", "card", "bank_transfer", "check"]),
                "notes": "[seed] full payment",
                "is_active": True,
                "created_at": now,
                "created_by": row.get("created_by"),
            }
        )

    realized_partial_count = 0
    for row in partial_selected:
        total = round2(row.get("total", 0.0))
        amount = pick_partial_amount(total)
        if amount <= 0:
            continue
        planned_payments.append(
            {
                "parts_order_id": row["_id"],
                "shop_id": row.get("shop_id"),
                "tenant_id": row.get("tenant_id"),
                "amount": amount,
                "payment_method": random.choice(["cash", "card", "bank_transfer", "check"]),
                "notes": "[seed] partial payment",
                "is_active": True,
                "created_at": now,
                "created_by": row.get("created_by"),
            }
        )
        realized_partial_count += 1

    paid_amount_by_order = {}
    for p in planned_payments:
        oid = p.get("parts_order_id")
        paid_amount_by_order[oid] = round2(paid_amount_by_order.get(oid, 0.0) + parse_float(p.get("amount"), 0.0))

    print(f"Target DB: {db_name}")
    print(f"Active parts orders: {len(active_orders)}")
    print(f"Payable parts orders (total > 0): {payable_count}")
    print(f"Requested ratios -> paid: {args.ratio_paid:.2%}, partial: {args.ratio_partial:.2%}")
    print(f"Planned paid orders: {len(paid_ids)}")
    print(f"Planned partial orders: {realized_partial_count}")
    print(f"Planned unpaid orders: {payable_count - len(paid_ids) - realized_partial_count}")

    if args.dry_run:
        print("Dry run complete. No records updated.")
        return

    active_order_ids = [x.get("_id") for x in order_meta if x.get("_id") is not None]
    if active_order_ids:
        db.parts_order_payments.update_many(
            {"parts_order_id": {"$in": active_order_ids}, "is_active": True},
            {"$set": {"is_active": False, "updated_at": now}},
        )

    if planned_payments:
        db.parts_order_payments.insert_many(planned_payments, ordered=False)

    modified_orders = 0
    for row in order_meta:
        oid = row.get("_id")
        if oid is None:
            continue

        total = round2(row.get("total", 0.0))
        paid_amount = round2(paid_amount_by_order.get(oid, 0.0))
        remaining = round2(max(0.0, total - paid_amount))

        if total <= 0:
            payment_status = "paid"
        elif oid in paid_ids:
            payment_status = "paid"
        elif paid_amount > 0:
            payment_status = "partially_paid"
        else:
            payment_status = "unpaid"

        result = db.parts_orders.update_one(
            {"_id": oid},
            {
                "$set": {
                    "payment_status": payment_status,
                    "paid_amount": float(paid_amount),
                    "remaining_balance": float(remaining),
                    "updated_at": now,
                }
            },
        )
        modified_orders += int(result.modified_count or 0)

    final_counts = {
        "paid": db.parts_orders.count_documents({"is_active": {"$ne": False}, "payment_status": "paid"}),
        "partially_paid": db.parts_orders.count_documents({"is_active": {"$ne": False}, "payment_status": "partially_paid"}),
        "unpaid": db.parts_orders.count_documents({"is_active": {"$ne": False}, "payment_status": "unpaid"}),
    }

    print(f"Inserted payments: {len(planned_payments)}")
    print(f"Orders modified: {modified_orders}")
    print(
        "Final active order payment_status -> "
        f"paid: {final_counts['paid']}, "
        f"partially_paid: {final_counts['partially_paid']}, "
        f"unpaid: {final_counts['unpaid']}"
    )


if __name__ == "__main__":
    main()
