from __future__ import annotations

import argparse
import os
import random
from datetime import datetime, timezone

from bson import ObjectId
from pymongo import MongoClient

VENDOR_PREFIXES = [
    "Atlas",
    "Summit",
    "Northstar",
    "Prime",
    "Metro",
    "Pioneer",
    "Canyon",
    "Redwood",
    "Granite",
    "Velocity",
    "Harbor",
    "Everest",
]

VENDOR_SUFFIXES = [
    "Auto Supply",
    "Parts Co",
    "Industrial",
    "Distribution",
    "Motors",
    "Components",
    "Wholesale",
    "Fleet Services",
    "Trading",
    "Equipment",
]

FIRST_NAMES = [
    "Alex",
    "Jordan",
    "Taylor",
    "Morgan",
    "Riley",
    "Casey",
    "Drew",
    "Avery",
    "Parker",
    "Quinn",
]

LAST_NAMES = [
    "Miller",
    "Davis",
    "Wilson",
    "Moore",
    "Taylor",
    "Anderson",
    "Thomas",
    "Jackson",
    "White",
    "Harris",
]

STREETS = [
    "Main St",
    "Industrial Ave",
    "Commerce Rd",
    "Broadway",
    "Market St",
    "Oak Dr",
    "Maple Ave",
    "Riverside Blvd",
    "Sunset Rd",
    "East Rd",
]

NOTES = [
    "-",
    "Fast delivery",
    "Bulk discount available",
    "OEM preferred",
    "Call before pickup",
    "Weekend delivery possible",
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
        has_vendors_data = "vendors" in collections and db.vendors.count_documents({}) > 0
        if has_parts_data or has_vendors_data:
            candidates.append(db_name)

    if not candidates:
        raise RuntimeError(
            "No suitable database found (requires non-empty 'parts' or 'vendors'). Use --db-name."
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
    sample = db.vendors.find_one({"is_active": True}) or db.vendors.find_one({})
    if not sample:
        sample = db.parts.find_one({"is_active": True}) or db.parts.find_one({})

    if not sample:
        raise RuntimeError("No sample document found in vendors/parts to derive shop/tenant/user IDs")

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


def random_phone() -> str:
    return f"{random.randint(200, 999)}-{random.randint(100, 999)}-{random.randint(1000, 9999)}"


def slugify(value: str) -> str:
    return "".join(ch.lower() if ch.isalnum() else "-" for ch in value).strip("-").replace("--", "-")


def random_vendor_name(existing_names: set[str]) -> str:
    while True:
        base = f"{random.choice(VENDOR_PREFIXES)} {random.choice(VENDOR_SUFFIXES)}"
        if base not in existing_names:
            return base

        suffix = random.randint(2, 999)
        candidate = f"{base} {suffix}"
        if candidate not in existing_names:
            return candidate


def make_random_doc(*, existing_names: set[str], shop_id: ObjectId, tenant_id: ObjectId, user_id: ObjectId) -> dict:
    name = random_vendor_name(existing_names)
    contact_first = random.choice(FIRST_NAMES)
    contact_last = random.choice(LAST_NAMES)

    slug = slugify(name)
    email = f"info@{slug}.com"
    website = f"{slug}.com"

    address = f"{random.randint(100, 9999)} {random.choice(STREETS)}"
    now = utcnow()

    return {
        "name": name,
        "phone": random_phone(),
        "email": email,
        "website": website,
        "address": address,
        "primary_contact_first_name": contact_first,
        "primary_contact_last_name": contact_last,
        "notes": random.choice(NOTES),
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
    parser = argparse.ArgumentParser(description="Seed random vendors into shop vendors collection.")
    parser.add_argument("--count", type=int, default=100, help="How many vendor records to insert.")
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

    existing_names = {
        (x.get("name") or "").strip()
        for x in db.vendors.find({}, {"name": 1})
        if (x.get("name") or "").strip()
    }

    docs: list[dict] = []
    for _ in range(args.count):
        doc = make_random_doc(
            existing_names=existing_names,
            shop_id=shop_id,
            tenant_id=tenant_id,
            user_id=user_id,
        )
        docs.append(doc)
        existing_names.add(doc["name"])

    print(f"Target DB: {db_name}")
    print(f"Will insert: {len(docs)}")
    print(f"Using shop_id={shop_id}, tenant_id={tenant_id}, user_id={user_id}")

    if args.dry_run:
        print("Dry run complete. No records inserted.")
        return

    result = db.vendors.insert_many(docs, ordered=False)
    print(f"Inserted records: {len(result.inserted_ids)}")


if __name__ == "__main__":
    main()
