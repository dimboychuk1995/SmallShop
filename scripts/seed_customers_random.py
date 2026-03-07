from __future__ import annotations

import argparse
import os
import random
from datetime import datetime, timezone

from bson import ObjectId
from pymongo import MongoClient

COMPANY_PREFIXES = [
    "Global",
    "North",
    "Prime",
    "Summit",
    "City",
    "Metro",
    "Rapid",
    "United",
    "Pioneer",
    "Blue",
    "Red",
    "Evergreen",
]

COMPANY_SUFFIXES = [
    "Logistics",
    "Trucking",
    "Builders",
    "Services",
    "Transport",
    "Motors",
    "Equipment",
    "Supply",
    "Group",
    "Solutions",
]

FIRST_NAMES = [
    "Oleh",
    "Ihor",
    "Andriy",
    "Maksym",
    "Denys",
    "Roman",
    "Taras",
    "Nazar",
    "Yurii",
    "Dmytro",
]

LAST_NAMES = [
    "Marchak",
    "Shevchenko",
    "Kovalenko",
    "Bondarenko",
    "Tkachenko",
    "Kravets",
    "Melnyk",
    "Boyko",
    "Koval",
    "Sydorenko",
]

STREETS = [
    "East Dunde",
    "Main Street",
    "Industrial Road",
    "Oak Avenue",
    "Pine Street",
    "Market Road",
    "Riverside Drive",
    "Sunset Boulevard",
    "Lakeview Road",
    "Central Avenue",
]


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def discover_target_db(client: MongoClient, explicit_db_name: str | None) -> str:
    if explicit_db_name:
        return explicit_db_name

    candidates: list[str] = []
    for db_name in client.list_database_names():
        db = client[db_name]
        collections = set(db.list_collection_names())
        has_parts_data = "parts" in collections and db.parts.count_documents({}) > 0
        has_customers_data = "customers" in collections and db.customers.count_documents({}) > 0
        if has_parts_data or has_customers_data:
            candidates.append(db_name)

    if not candidates:
        raise RuntimeError(
            "No suitable database found (requires non-empty 'parts' or 'customers'). Use --db-name."
        )

    if len(candidates) > 1:
        raise RuntimeError(
            "More than one DB is suitable: "
            + ", ".join(candidates)
            + ". Use --db-name to select target."
        )

    return candidates[0]


def _oid(value):
    if isinstance(value, ObjectId):
        return value
    return None


def get_context_ids(db):
    sample = db.customers.find_one({"is_active": True}) or db.customers.find_one({})
    if not sample:
        sample = db.parts.find_one({"is_active": True}) or db.parts.find_one({})

    if not sample:
        raise RuntimeError("No sample document found in customers/parts to derive shop/tenant/user IDs")

    shop_id = _oid(sample.get("shop_id"))
    tenant_id = _oid(sample.get("tenant_id"))
    user_id = _oid(sample.get("updated_by")) or _oid(sample.get("created_by"))

    if not shop_id:
        raise RuntimeError("Sample document has invalid shop_id")
    if not tenant_id:
        raise RuntimeError("Sample document has invalid tenant_id")
    if not user_id:
        raise RuntimeError("Sample document has invalid created_by/updated_by")

    return shop_id, tenant_id, user_id


def get_default_labor_rate_id(db, shop_id: ObjectId) -> ObjectId:
    doc = db.labor_rates.find_one(
        {"shop_id": shop_id, "is_active": True, "code": "standard"},
        {"_id": 1},
    )
    if not doc:
        doc = db.labor_rates.find_one(
            {"shop_id": shop_id, "is_active": True},
            {"_id": 1},
            sort=[("name", 1)],
        )
    if not doc or not isinstance(doc.get("_id"), ObjectId):
        raise RuntimeError("No active labor_rates found for this shop")
    return doc["_id"]


def random_phone() -> str:
    return f"{random.randint(200, 999)}-{random.randint(100, 999)}-{random.randint(1000, 9999)}"


def random_company_name(existing_companies: set[str]) -> str:
    while True:
        base = f"{random.choice(COMPANY_PREFIXES)} {random.choice(COMPANY_SUFFIXES)}"
        if base not in existing_companies:
            return base

        suffix = random.randint(2, 999)
        candidate = f"{base} {suffix}"
        if candidate not in existing_companies:
            return candidate


def slugify(value: str) -> str:
    out = []
    prev_dash = False
    for ch in value.lower():
        if ch.isalnum():
            out.append(ch)
            prev_dash = False
        else:
            if not prev_dash:
                out.append("-")
                prev_dash = True
    return "".join(out).strip("-")


def make_random_doc(*, existing_companies: set[str], shop_id: ObjectId, tenant_id: ObjectId, user_id: ObjectId, default_labor_rate_id: ObjectId) -> dict:
    company_name = random_company_name(existing_companies)
    first_name = random.choice(FIRST_NAMES)
    last_name = random.choice(LAST_NAMES)

    domain = slugify(company_name)
    now = utcnow()

    return {
        "company_name": company_name,
        "first_name": first_name,
        "last_name": last_name,
        "phone": random_phone(),
        "email": f"info@{domain}.com",
        "address": f"{random.randint(100, 9999)} {random.choice(STREETS)}",
        "default_labor_rate": default_labor_rate_id,
        "is_active": True,
        "created_at": now,
        "updated_at": now,
        "created_by": user_id,
        "updated_by": user_id,
        "deactivated_at": None,
        "deactivated_by": None,
        "shop_id": shop_id,
        "tenant_id": tenant_id,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed random customers into shop customers collection.")
    parser.add_argument("--count", type=int, default=200, help="How many customer records to insert.")
    parser.add_argument("--db-name", type=str, default=None, help="Target Mongo database name.")
    parser.add_argument("--dry-run", action="store_true", help="Do not insert, only print plan.")
    args = parser.parse_args()

    if args.count <= 0:
        raise SystemExit("--count must be > 0")

    mongo_uri = os.environ.get("MONGO_URI", "mongodb://127.0.0.1:27017")
    client = MongoClient(mongo_uri, serverSelectionTimeoutMS=5000)
    client.admin.command("ping")

    db_name = discover_target_db(client, args.db_name)
    db = client[db_name]

    shop_id, tenant_id, user_id = get_context_ids(db)
    default_labor_rate_id = get_default_labor_rate_id(db, shop_id)

    existing_companies = {
        (x.get("company_name") or "").strip()
        for x in db.customers.find({}, {"company_name": 1})
        if (x.get("company_name") or "").strip()
    }

    docs: list[dict] = []
    for _ in range(args.count):
        doc = make_random_doc(
            existing_companies=existing_companies,
            shop_id=shop_id,
            tenant_id=tenant_id,
            user_id=user_id,
            default_labor_rate_id=default_labor_rate_id,
        )
        docs.append(doc)
        existing_companies.add(doc["company_name"])

    print(f"Target DB: {db_name}")
    print(f"Will insert: {len(docs)}")
    print(f"Using shop_id={shop_id}, tenant_id={tenant_id}, user_id={user_id}")

    if args.dry_run:
        print("Dry run complete. No records inserted.")
        return

    result = db.customers.insert_many(docs, ordered=False)
    print(f"Inserted records: {len(result.inserted_ids)}")


if __name__ == "__main__":
    main()
