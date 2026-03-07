from __future__ import annotations

import argparse
import os
import random
import string
from datetime import datetime, timezone

from bson import ObjectId
from pymongo import MongoClient

MAKES_MODELS: dict[str, list[str]] = {
    "Freightliner": ["Cascadia", "M2 106", "114SD"],
    "Kenworth": ["T680", "W990", "T880"],
    "Peterbilt": ["579", "567", "389"],
    "International": ["LT", "RH", "HV"],
    "Volvo": ["VNL", "VNR", "VHD"],
    "Mack": ["Anthem", "Pinnacle", "Granite"],
    "Hino": ["L6", "L7", "XL8"],
    "Isuzu": ["NPR", "NQR", "FTR"],
}

UNIT_TYPES = [
    "Truck",
    "Trailer",
    "Van",
    "Box Truck",
    "Dump Truck",
    "Service Truck",
]

VIN_ALPHABET = "ABCDEFGHJKLMNPRSTUVWXYZ0123456789"


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def discover_target_db(client: MongoClient, explicit_db_name: str | None) -> str:
    if explicit_db_name:
        return explicit_db_name

    candidates: list[str] = []
    for db_name in client.list_database_names():
        db = client[db_name]
        collections = set(db.list_collection_names())
        if "customers" in collections and db.customers.count_documents({}) > 0:
            candidates.append(db_name)

    if not candidates:
        raise RuntimeError("No suitable database found (requires non-empty 'customers'). Use --db-name.")

    if len(candidates) > 1:
        raise RuntimeError(
            "More than one DB is suitable: "
            + ", ".join(candidates)
            + ". Use --db-name to select target."
        )

    return candidates[0]


def _oid(value):
    return value if isinstance(value, ObjectId) else None


def random_vin(existing_vins: set[str]) -> str:
    while True:
        vin = "".join(random.choice(VIN_ALPHABET) for _ in range(17))
        if vin not in existing_vins:
            return vin


def random_year() -> int:
    return random.randint(1999, datetime.now(timezone.utc).year + 1)


def random_mileage() -> int:
    return random.randint(10_000, 900_000)


def make_unit_doc(
    *,
    customer: dict,
    idx_for_customer: int,
    existing_unit_numbers: set[str],
    existing_vins: set[str],
    fallback_user_id: ObjectId,
) -> dict:
    make = random.choice(list(MAKES_MODELS.keys()))
    model = random.choice(MAKES_MODELS[make])

    customer_id = _oid(customer.get("_id"))
    shop_id = _oid(customer.get("shop_id"))
    tenant_id = _oid(customer.get("tenant_id"))
    user_id = _oid(customer.get("updated_by")) or _oid(customer.get("created_by")) or fallback_user_id

    if not customer_id:
        raise RuntimeError("Customer has invalid _id")
    if not shop_id:
        raise RuntimeError(f"Customer {customer_id} has invalid shop_id")
    if not tenant_id:
        raise RuntimeError(f"Customer {customer_id} has invalid tenant_id")
    if not user_id:
        raise RuntimeError(f"Customer {customer_id} has invalid created_by/updated_by")

    while True:
        unit_number = f"U-{str(customer_id)[-6:]}-{idx_for_customer:03d}"
        if unit_number not in existing_unit_numbers:
            break
        idx_for_customer += 1

    vin = random_vin(existing_vins)
    now = utcnow()

    return {
        "customer_id": customer_id,
        "vin": vin,
        "unit_number": unit_number,
        "make": make,
        "model": model,
        "year": random_year(),
        "type": random.choice(UNIT_TYPES),
        "mileage": random_mileage(),
        "shop_id": shop_id,
        "tenant_id": tenant_id,
        "is_active": True,
        "created_at": now,
        "updated_at": now,
        "created_by": user_id,
        "updated_by": user_id,
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Seed units for each customer with strict field types and ObjectId references."
    )
    parser.add_argument(
        "--per-customer",
        type=int,
        default=50,
        help="Target number of units per customer.",
    )
    parser.add_argument(
        "--mode",
        type=str,
        choices=["ensure", "add"],
        default="ensure",
        help="ensure: reach target count per customer; add: add N units to each customer.",
    )
    parser.add_argument("--db-name", type=str, default=None, help="Target Mongo database name.")
    parser.add_argument("--include-inactive", action="store_true", help="Include inactive customers.")
    parser.add_argument("--dry-run", action="store_true", help="Do not insert, only print plan.")
    args = parser.parse_args()

    if args.per_customer <= 0:
        raise SystemExit("--per-customer must be > 0")

    mongo_uri = os.environ.get("MONGO_URI", "mongodb://127.0.0.1:27017")
    client = MongoClient(mongo_uri, serverSelectionTimeoutMS=5000)
    client.admin.command("ping")

    db_name = discover_target_db(client, args.db_name)
    db = client[db_name]

    sample = db.customers.find_one({"is_active": True}) or db.customers.find_one({})
    if not sample:
        raise RuntimeError("No customers found in target DB")

    fallback_user_id = _oid(sample.get("updated_by")) or _oid(sample.get("created_by"))
    if not fallback_user_id:
        raise RuntimeError("Cannot derive fallback user_id from sample customer")

    customer_query = {}
    if not args.include_inactive:
        customer_query["is_active"] = {"$ne": False}

    customers = list(
        db.customers.find(
            customer_query,
            {
                "_id": 1,
                "shop_id": 1,
                "tenant_id": 1,
                "created_by": 1,
                "updated_by": 1,
                "is_active": 1,
            },
        )
    )

    if not customers:
        raise RuntimeError("No customers matched filter")

    customer_ids = [c.get("_id") for c in customers if _oid(c.get("_id"))]
    existing_units = list(
        db.units.find(
            {
                "customer_id": {"$in": customer_ids},
                "is_active": True,
            },
            {"_id": 1, "customer_id": 1, "unit_number": 1, "vin": 1},
        )
    )

    units_by_customer: dict[ObjectId, int] = {cid: 0 for cid in customer_ids}
    for u in existing_units:
        cid = _oid(u.get("customer_id"))
        if cid in units_by_customer:
            units_by_customer[cid] += 1

    existing_unit_numbers = {
        str(u.get("unit_number")).strip()
        for u in existing_units
        if str(u.get("unit_number") or "").strip()
    }
    existing_vins = {
        str(u.get("vin")).strip().upper()
        for u in existing_units
        if str(u.get("vin") or "").strip()
    }

    docs: list[dict] = []
    planned_total = 0

    for c in customers:
        cid = _oid(c.get("_id"))
        if not cid:
            continue

        existing_count = units_by_customer.get(cid, 0)
        if args.mode == "add":
            to_add = args.per_customer
            start_idx = existing_count + 1
        else:
            to_add = max(0, args.per_customer - existing_count)
            start_idx = existing_count + 1

        for i in range(to_add):
            doc = make_unit_doc(
                customer=c,
                idx_for_customer=start_idx + i,
                existing_unit_numbers=existing_unit_numbers,
                existing_vins=existing_vins,
                fallback_user_id=fallback_user_id,
            )
            docs.append(doc)
            planned_total += 1
            existing_unit_numbers.add(str(doc["unit_number"]))
            existing_vins.add(str(doc["vin"]).upper())

    print(f"Target DB: {db_name}")
    print(f"Customers matched: {len(customers)}")
    print(f"Mode: {args.mode}")
    print(f"Per customer: {args.per_customer}")
    print(f"Will insert units: {planned_total}")

    if args.dry_run:
        print("Dry run complete. No records inserted.")
        return

    if not docs:
        print("Nothing to insert.")
        return

    result = db.units.insert_many(docs, ordered=False)
    print(f"Inserted records: {len(result.inserted_ids)}")


if __name__ == "__main__":
    main()
