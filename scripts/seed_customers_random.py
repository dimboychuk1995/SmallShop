from __future__ import annotations

import argparse
import os
import random
import string
from datetime import UTC, datetime

from bson import ObjectId
from dotenv import load_dotenv
from pymongo import MongoClient


def utcnow() -> datetime:
    return datetime.now(UTC)


def random_phone() -> str:
    return f"{random.randint(200, 999)}-{random.randint(200, 999)}-{random.randint(1000, 9999)}"


def random_address() -> str:
    street_no = random.randint(100, 9999)
    street_name = random.choice([
        "Main St",
        "Oak Ave",
        "Maple Dr",
        "Broadway",
        "Washington Blvd",
        "Lake St",
        "Park Ave",
        "Elm St",
        "Sunset Blvd",
        "Cedar Rd",
    ])
    city = random.choice([
        "East Dundee",
        "Elgin",
        "Chicago",
        "Schaumburg",
        "Arlington Heights",
        "Naperville",
        "Aurora",
        "Joliet",
    ])
    state = "IL"
    zip_code = f"{random.randint(60000, 62999)}"
    return f"{street_no} {street_name}, {city}, {state}, {zip_code}"


def slugify(value: str) -> str:
    cleaned = "".join(ch.lower() if ch.isalnum() else "-" for ch in value)
    while "--" in cleaned:
        cleaned = cleaned.replace("--", "-")
    return cleaned.strip("-")


def random_company_name() -> str:
    left = random.choice([
        "Globex",
        "Initech",
        "Umbrella",
        "Wayne",
        "Stark",
        "Aperture",
        "Wonka",
        "Hooli",
        "Vandelay",
        "Acme",
        "Cyberdyne",
        "Tyrell",
    ])
    right = random.choice([
        "Auto",
        "Fleet",
        "Logistics",
        "Motors",
        "Transport",
        "Group",
        "Services",
        "Industries",
        "Repair",
        "Solutions",
    ])
    suffix = random.choice(["LLC", "Inc", "Corp", "Ltd", "Co"])
    token = "".join(random.choices(string.ascii_uppercase + string.digits, k=3))
    return f"{left} {right} {token} {suffix}"


def random_person_name() -> tuple[str, str]:
    first_names = [
        "Oleh",
        "Andrii",
        "Dmytro",
        "Maksym",
        "Ivan",
        "Taras",
        "Yaroslav",
        "Oleksii",
        "Petro",
        "Mykhailo",
        "Anna",
        "Olena",
        "Iryna",
        "Natalia",
        "Kateryna",
        "Marta",
    ]
    last_names = [
        "Marchak",
        "Koval",
        "Melnyk",
        "Shevchenko",
        "Bondarenko",
        "Tkachenko",
        "Mazur",
        "Boyko",
        "Kravets",
        "Polishchuk",
        "Hrytsenko",
        "Sydorenko",
    ]
    return random.choice(first_names), random.choice(last_names)


def pick_db_name(shop_doc: dict) -> str | None:
    return (
        shop_doc.get("db_name")
        or shop_doc.get("database")
        or shop_doc.get("db")
        or shop_doc.get("mongo_db")
        or shop_doc.get("shop_db")
    )


def resolve_context(master_db):
    tenant = master_db.tenants.find_one({"status": "active"}, sort=[("created_at", 1)])
    if not tenant:
        raise RuntimeError("No active tenant found in master.tenants")

    shop = master_db.shops.find_one(
        {"tenant_id": tenant["_id"]},
        sort=[("created_at", 1)],
    )
    if not shop:
        raise RuntimeError("No shop found for active tenant in master.shops")

    user = master_db.users.find_one(
        {
            "tenant_id": tenant["_id"],
            "is_active": True,
            "$or": [
                {"shop_ids": shop["_id"]},
                {"shop_id": shop["_id"]},
                {"shop_ids": {"$exists": False}},
            ],
        },
        sort=[("created_at", 1)],
    )
    if not user:
        user = master_db.users.find_one(
            {"tenant_id": tenant["_id"], "is_active": True},
            sort=[("created_at", 1)],
        )
    if not user:
        raise RuntimeError("No active user found for tenant in master.users")

    db_name = pick_db_name(shop)
    if not db_name:
        raise RuntimeError("Shop has no db_name/database field")

    return tenant, shop, user, db_name


def find_default_labor_rate(shop_db, shop_id: ObjectId) -> ObjectId | None:
    rate = shop_db.labor_rates.find_one(
        {"shop_id": shop_id, "is_active": True, "code": "standard"},
        {"_id": 1},
    )
    if rate:
        return rate["_id"]

    rate = shop_db.labor_rates.find_one(
        {"shop_id": shop_id, "is_active": True},
        {"_id": 1},
        sort=[("name", 1)],
    )
    return rate["_id"] if rate else None


def build_customer_doc(index: int, tenant_id: ObjectId, shop_id: ObjectId, user_id: ObjectId, labor_rate_id: ObjectId | None):
    first_name, last_name = random_person_name()
    company_name = random_company_name()
    company_slug = slugify(company_name)

    email = f"{company_slug}.{index + 1:04d}@example.com"
    now = utcnow()

    return {
        "company_name": company_name,
        "first_name": first_name,
        "last_name": last_name,
        "phone": random_phone(),
        "email": email,
        "address": random_address(),
        "default_labor_rate": labor_rate_id,
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


def main():
    parser = argparse.ArgumentParser(description="Seed random customers with real ObjectId references.")
    parser.add_argument("--count", type=int, default=2000, help="How many customers to insert (default: 2000)")
    parser.add_argument("--seed", type=int, default=20260311, help="Random seed for reproducible output")
    args = parser.parse_args()

    if args.count <= 0:
        raise SystemExit("--count must be > 0")

    random.seed(args.seed)
    load_dotenv()

    mongo_uri = os.getenv("MONGO_URI", "mongodb://127.0.0.1:27017")
    master_db_name = os.getenv("MASTER_DB_NAME") or os.getenv("MONGO_DB") or "master_db"

    client = MongoClient(mongo_uri, serverSelectionTimeoutMS=5000)
    client.admin.command("ping")

    master_db = client[master_db_name]
    tenant, shop, user, shop_db_name = resolve_context(master_db)
    shop_db = client[str(shop_db_name)]

    default_labor_rate = find_default_labor_rate(shop_db, shop["_id"])

    docs = [
        build_customer_doc(
            index=i,
            tenant_id=tenant["_id"],
            shop_id=shop["_id"],
            user_id=user["_id"],
            labor_rate_id=default_labor_rate,
        )
        for i in range(args.count)
    ]

    result = shop_db.customers.insert_many(docs, ordered=False)

    print(f"Inserted customers: {len(result.inserted_ids)}")
    print(f"tenant_id: {tenant['_id']}")
    print(f"shop_id: {shop['_id']}")
    print(f"user_id(created_by/updated_by): {user['_id']}")
    print(f"default_labor_rate: {default_labor_rate}")
    print(f"shop_db: {shop_db_name}")


if __name__ == "__main__":
    main()
