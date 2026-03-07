from __future__ import annotations

import argparse
import os
import random
from datetime import datetime, timedelta, timezone

from bson import ObjectId
from pymongo import MongoClient


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def round2(value) -> float:
    try:
        return round(float(value or 0) + 1e-12, 2)
    except Exception:
        return 0.0


def _oid(value):
    return value if isinstance(value, ObjectId) else None


def discover_target_db(client: MongoClient, explicit_db_name: str | None) -> str:
    if explicit_db_name:
        return explicit_db_name

    candidates: list[str] = []
    for db_name in client.list_database_names():
        db = client[db_name]
        collections = set(db.list_collection_names())
        has_customers = "customers" in collections and db.customers.count_documents({}) > 0
        has_units = "units" in collections and db.units.count_documents({}) > 0
        has_parts = "parts" in collections and db.parts.count_documents({}) > 0
        if has_customers and has_units and has_parts:
            candidates.append(db_name)

    if not candidates:
        raise RuntimeError(
            "No suitable database found (requires non-empty customers/units/parts). Use --db-name."
        )

    if len(candidates) > 1:
        raise RuntimeError(
            "More than one DB is suitable: " + ", ".join(candidates) + ". Use --db-name to select target."
        )

    return candidates[0]


def random_created_at() -> datetime:
    now = utcnow()
    days_back = random.randint(0, 540)
    minutes_back = random.randint(0, 24 * 60 - 1)
    return now - timedelta(days=days_back, minutes=minutes_back)


def pick_rate_code(labor_rates_by_shop: dict[ObjectId, list[dict]], shop_id: ObjectId) -> str:
    rates = labor_rates_by_shop.get(shop_id) or []
    if not rates:
        return "standard"
    return str(random.choice(rates).get("code") or "standard").strip() or "standard"


def build_parts_rows(parts_pool: list[dict], max_count: int) -> tuple[list[dict], float, float]:
    if not parts_pool or max_count <= 0:
        return [], 0.0, 0.0

    take = random.randint(1, max_count)
    selected = random.sample(parts_pool, k=min(take, len(parts_pool)))

    rows = []
    parts_sale_total = 0.0
    parts_cost_total = 0.0

    for part in selected:
        qty = random.randint(1, 3)
        cost = round2(part.get("average_cost") or random.uniform(10.0, 200.0))
        markup = random.uniform(1.2, 2.0)
        price = round2(cost * markup)

        row = {
            "part_id": _oid(part.get("_id")),
            "part_number": str(part.get("part_number") or "").strip(),
            "description": str(part.get("description") or "").strip(),
            "qty": qty,
            "cost": cost,
            "price": price,
            "core_charge": 0.0,
            "misc_charge": 0.0,
            "misc_charge_description": "",
        }
        rows.append(row)

        parts_sale_total += qty * price
        parts_cost_total += qty * cost

    return rows, round2(parts_sale_total), round2(parts_cost_total)


def build_totals(labor: float, parts_sale: float, parts_cost: float) -> dict:
    shop_supply_total = round2(labor * random.uniform(0.0, 0.08))
    labor_total = round2(labor + shop_supply_total)
    parts_total = round2(parts_sale)
    grand_total = round2(labor_total + parts_total)

    block = {
        "labor": round2(labor),
        "labor_total": labor_total,
        "parts": parts_total,
        "parts_total": parts_total,
        "core_total": 0.0,
        "misc_total": 0.0,
        "cost_total": round2(parts_cost),
        "shop_supply_total": shop_supply_total,
        "labor_full_total": grand_total,
    }

    return {
        "labor": round2(labor),
        "labor_total": labor_total,
        "parts": parts_total,
        "parts_total": parts_total,
        "core_total": 0.0,
        "misc_total": 0.0,
        "cost_total": round2(parts_cost),
        "shop_supply_total": shop_supply_total,
        "grand_total": grand_total,
        "labors": [block],
    }


def build_work_order_doc(
    *,
    customer: dict,
    unit: dict,
    parts_pool: list[dict],
    wo_number: int,
    labor_rates_by_shop: dict[ObjectId, list[dict]],
) -> dict:
    customer_id = _oid(customer.get("_id"))
    unit_id = _oid(unit.get("_id"))
    shop_id = _oid(customer.get("shop_id"))
    tenant_id = _oid(customer.get("tenant_id"))
    user_id = _oid(customer.get("updated_by")) or _oid(customer.get("created_by"))

    if not customer_id:
        raise RuntimeError("Invalid customer _id")
    if not unit_id:
        raise RuntimeError(f"Customer {customer_id}: selected unit has invalid _id")
    if not shop_id:
        raise RuntimeError(f"Customer {customer_id}: invalid shop_id")
    if not tenant_id:
        raise RuntimeError(f"Customer {customer_id}: invalid tenant_id")
    if not user_id:
        raise RuntimeError(f"Customer {customer_id}: missing created_by/updated_by")

    parts_rows, parts_sale_total, parts_cost_total = build_parts_rows(parts_pool, max_count=3)
    labor_amount = round2(random.uniform(65.0, 950.0))
    totals = build_totals(labor_amount, parts_sale_total, parts_cost_total)

    rate_code = pick_rate_code(labor_rates_by_shop, shop_id)
    labor_hours = round2(random.uniform(0.5, 8.0))

    labors = [
        {
            "labor": {
                "description": random.choice(
                    [
                        "General inspection",
                        "Engine diagnostics",
                        "Brake service",
                        "Electrical troubleshooting",
                        "PM service",
                        "Cooling system repair",
                    ]
                ),
                "hours": str(labor_hours),
                "rate_code": rate_code,
                "labor_full_total": totals.get("grand_total", 0),
                "assigned_mechanics": [],
            },
            "parts": parts_rows,
        }
    ]

    created_at = random_created_at()
    status = "paid" if random.random() < 0.28 else "open"

    return {
        "shop_id": shop_id,
        "tenant_id": tenant_id,
        "wo_number": int(wo_number),
        "customer_id": customer_id,
        "unit_id": unit_id,
        "status": status,
        "labors": labors,
        "totals": totals,
        "inventory_deducted": False,
        "inventory_deductions": [],
        "is_active": True,
        "created_at": created_at,
        "updated_at": created_at,
        "created_by": user_id,
        "updated_by": user_id,
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Seed random work orders using real customers, units, and parts."
    )
    parser.add_argument("--count", type=int, default=50000, help="How many work orders to insert.")
    parser.add_argument("--db-name", type=str, default=None, help="Target Mongo database name.")
    parser.add_argument("--batch-size", type=int, default=1000, help="Insert batch size.")
    parser.add_argument("--dry-run", action="store_true", help="Do not insert, only print plan.")
    args = parser.parse_args()

    if args.count <= 0:
        raise SystemExit("--count must be > 0")
    if args.batch_size <= 0:
        raise SystemExit("--batch-size must be > 0")

    mongo_uri = os.environ.get("MONGO_URI", "mongodb://127.0.0.1:27017")
    client = MongoClient(mongo_uri, serverSelectionTimeoutMS=5000)
    client.admin.command("ping")

    db_name = discover_target_db(client, args.db_name)
    db = client[db_name]

    customers = list(
        db.customers.find(
            {"is_active": {"$ne": False}},
            {
                "_id": 1,
                "shop_id": 1,
                "tenant_id": 1,
                "created_by": 1,
                "updated_by": 1,
            },
        )
    )
    if not customers:
        raise RuntimeError("No active customers found")

    customer_ids = [c.get("_id") for c in customers if _oid(c.get("_id"))]
    units = list(
        db.units.find(
            {"customer_id": {"$in": customer_ids}, "is_active": True},
            {"_id": 1, "customer_id": 1, "shop_id": 1},
        )
    )
    if not units:
        raise RuntimeError("No active units found for active customers")

    units_by_customer: dict[ObjectId, list[dict]] = {}
    for u in units:
        cid = _oid(u.get("customer_id"))
        if not cid:
            continue
        units_by_customer.setdefault(cid, []).append(u)

    eligible_customers = [c for c in customers if _oid(c.get("_id")) in units_by_customer]
    if not eligible_customers:
        raise RuntimeError("No customers with active units found")

    shop_ids = sorted(
        {c.get("shop_id") for c in eligible_customers if _oid(c.get("shop_id"))},
        key=lambda x: str(x),
    )

    parts_by_shop: dict[ObjectId, list[dict]] = {}
    labor_rates_by_shop: dict[ObjectId, list[dict]] = {}
    wo_next_number_by_shop: dict[ObjectId, int] = {}

    for shop_id in shop_ids:
        parts = list(
            db.parts.find(
                {"shop_id": shop_id, "is_active": True},
                {"_id": 1, "part_number": 1, "description": 1, "average_cost": 1},
            )
        )
        if not parts:
            raise RuntimeError(f"No active parts for shop_id={shop_id}")
        parts_by_shop[shop_id] = parts

        labor_rates_by_shop[shop_id] = list(
            db.labor_rates.find(
                {"shop_id": shop_id, "is_active": True},
                {"_id": 1, "code": 1, "name": 1, "hourly_rate": 1},
            )
        )

        max_row = list(
            db.work_orders.find(
                {"shop_id": shop_id},
                {"wo_number": 1},
            )
            .sort([("wo_number", -1)])
            .limit(1)
        )
        if max_row and isinstance(max_row[0].get("wo_number"), int):
            wo_next_number_by_shop[shop_id] = int(max_row[0]["wo_number"]) + 1
        else:
            wo_next_number_by_shop[shop_id] = 1000

    docs_buffer: list[dict] = []
    inserted_total = 0
    generated_total = 0
    max_inserted_wo_number_by_shop: dict[ObjectId, int] = {}

    for _ in range(args.count):
        customer = random.choice(eligible_customers)
        customer_id = _oid(customer.get("_id"))
        if not customer_id:
            continue

        shop_id = _oid(customer.get("shop_id"))
        if not shop_id:
            continue

        unit = random.choice(units_by_customer[customer_id])
        wo_number = wo_next_number_by_shop[shop_id]
        wo_next_number_by_shop[shop_id] = wo_number + 1

        doc = build_work_order_doc(
            customer=customer,
            unit=unit,
            parts_pool=parts_by_shop[shop_id],
            wo_number=wo_number,
            labor_rates_by_shop=labor_rates_by_shop,
        )
        docs_buffer.append(doc)
        generated_total += 1
        max_inserted_wo_number_by_shop[shop_id] = max(
            wo_number,
            max_inserted_wo_number_by_shop.get(shop_id, wo_number),
        )

        if not args.dry_run and len(docs_buffer) >= args.batch_size:
            result = db.work_orders.insert_many(docs_buffer, ordered=False)
            inserted_total += len(result.inserted_ids)
            docs_buffer = []

    if args.dry_run:
        print(f"Target DB: {db_name}")
        print(f"Eligible customers: {len(eligible_customers)}")
        print(f"Shops involved: {len(shop_ids)}")
        print(f"Will insert work orders: {generated_total}")
        print("Dry run complete. No records inserted.")
        return

    if docs_buffer:
        result = db.work_orders.insert_many(docs_buffer, ordered=False)
        inserted_total += len(result.inserted_ids)

    # Keep counter in sync so future UI-created work orders continue numbering from latest.
    for shop_id, max_wo_number in max_inserted_wo_number_by_shop.items():
        desired_seq = max(1, int(max_wo_number) - 1000 + 1)
        db.counters.update_one(
            {"_id": f"wo_number_{shop_id}"},
            {
                "$setOnInsert": {"initial_value": 1000},
                "$max": {"seq": desired_seq},
                "$set": {"updated_at": utcnow()},
            },
            upsert=True,
        )

    print(f"Target DB: {db_name}")
    print(f"Eligible customers: {len(eligible_customers)}")
    print(f"Shops involved: {len(shop_ids)}")
    print(f"Requested inserts: {args.count}")
    print(f"Inserted records: {inserted_total}")


if __name__ == "__main__":
    main()
