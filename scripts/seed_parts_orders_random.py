from __future__ import annotations

import argparse
import os
import random
from datetime import datetime, timedelta, timezone

from bson import ObjectId
from pymongo import MongoClient


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _oid(value):
    return value if isinstance(value, ObjectId) else None


def discover_target_db(client: MongoClient, explicit_db_name: str | None) -> str:
    if explicit_db_name:
        return explicit_db_name

    candidates: list[str] = []
    for db_name in client.list_database_names():
        db = client[db_name]
        collections = set(db.list_collection_names())
        has_vendors = "vendors" in collections and db.vendors.count_documents({}) > 0
        has_parts = "parts" in collections and db.parts.count_documents({}) > 0
        if has_vendors and has_parts:
            candidates.append(db_name)

    if not candidates:
        raise RuntimeError("No suitable database found (requires non-empty vendors/parts). Use --db-name.")

    if len(candidates) > 1:
        raise RuntimeError(
            "More than one DB is suitable: " + ", ".join(candidates) + ". Use --db-name to select target."
        )

    return candidates[0]


def random_created_at() -> datetime:
    now = utcnow()
    days_back = random.randint(0, 365)
    minutes_back = random.randint(0, 24 * 60 - 1)
    return now - timedelta(days=days_back, minutes=minutes_back)


def round2(value) -> float:
    try:
        return round(float(value or 0) + 1e-12, 2)
    except Exception:
        return 0.0


def _next_order_numbers_by_shop(db, shop_ids: list[ObjectId]) -> dict[ObjectId, int]:
    out: dict[ObjectId, int] = {}
    for shop_id in shop_ids:
        max_row = list(
            db.parts_orders.find({"shop_id": shop_id}, {"order_number": 1})
            .sort([("order_number", -1)])
            .limit(1)
        )
        if max_row and isinstance(max_row[0].get("order_number"), int):
            out[shop_id] = int(max_row[0]["order_number"]) + 1
        else:
            out[shop_id] = 1000
    return out


def _choose_user_id(vendor: dict, fallback_user_id: ObjectId) -> ObjectId:
    user_id = _oid(vendor.get("updated_by")) or _oid(vendor.get("created_by"))
    return user_id or fallback_user_id


def _pick_items(parts_for_vendor: list[dict], parts_for_shop: list[dict]) -> list[dict]:
    source = parts_for_vendor if parts_for_vendor else parts_for_shop
    if not source:
        return []

    take = random.randint(1, min(5, len(source)))
    selected = random.sample(source, k=take)

    items: list[dict] = []
    for p in selected:
        part_id = _oid(p.get("_id"))
        if not part_id:
            continue

        qty = random.randint(1, 8)
        base_cost = round2(p.get("average_cost") or random.uniform(10.0, 180.0))
        price = round2(base_cost * random.uniform(1.05, 1.8))

        items.append(
            {
                "part_id": part_id,
                "part_number": str(p.get("part_number") or "").strip(),
                "description": str(p.get("description") or "").strip(),
                "price": price,
                "quantity": qty,
            }
        )

    return items


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Seed random parts orders using real vendors and parts with valid references."
    )
    parser.add_argument("--count", type=int, default=400, help="How many parts orders to insert.")
    parser.add_argument("--db-name", type=str, default=None, help="Target Mongo database name.")
    parser.add_argument("--batch-size", type=int, default=200, help="Insert batch size.")
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

    vendors = list(
        db.vendors.find(
            {"is_active": {"$ne": False}},
            {"_id": 1, "shop_id": 1, "tenant_id": 1, "created_by": 1, "updated_by": 1},
        )
    )
    if not vendors:
        raise RuntimeError("No active vendors found")

    parts = list(
        db.parts.find(
            {"is_active": {"$ne": False}},
            {"_id": 1, "shop_id": 1, "tenant_id": 1, "vendor_id": 1, "part_number": 1, "description": 1, "average_cost": 1},
        )
    )
    if not parts:
        raise RuntimeError("No active parts found")

    vendors_by_shop: dict[ObjectId, list[dict]] = {}
    for v in vendors:
        sid = _oid(v.get("shop_id"))
        tid = _oid(v.get("tenant_id"))
        vid = _oid(v.get("_id"))
        if not sid or not tid or not vid:
            continue
        vendors_by_shop.setdefault(sid, []).append(v)

    parts_by_shop: dict[ObjectId, list[dict]] = {}
    parts_by_shop_vendor: dict[tuple[ObjectId, ObjectId], list[dict]] = {}
    fallback_user_id = None
    for p in parts:
        sid = _oid(p.get("shop_id"))
        pid = _oid(p.get("_id"))
        if not sid or not pid:
            continue
        parts_by_shop.setdefault(sid, []).append(p)

        vid = _oid(p.get("vendor_id"))
        if vid:
            parts_by_shop_vendor.setdefault((sid, vid), []).append(p)

        if fallback_user_id is None:
            fallback_user_id = _oid(p.get("updated_by")) or _oid(p.get("created_by"))

    eligible_shop_ids = [sid for sid in vendors_by_shop.keys() if sid in parts_by_shop and vendors_by_shop[sid]]
    if not eligible_shop_ids:
        raise RuntimeError("No eligible shops with active vendors and parts")

    if fallback_user_id is None:
        sample_vendor = vendors_by_shop[eligible_shop_ids[0]][0]
        fallback_user_id = _oid(sample_vendor.get("updated_by")) or _oid(sample_vendor.get("created_by"))
    if fallback_user_id is None:
        raise RuntimeError("Could not resolve fallback user id from vendors/parts")

    next_number_by_shop = _next_order_numbers_by_shop(db, eligible_shop_ids)

    docs_buffer: list[dict] = []
    generated_total = 0
    inserted_total = 0
    max_inserted_order_number_by_shop: dict[ObjectId, int] = {}

    for _ in range(args.count):
        shop_id = random.choice(eligible_shop_ids)
        vendor = random.choice(vendors_by_shop[shop_id])

        vendor_id = _oid(vendor.get("_id"))
        tenant_id = _oid(vendor.get("tenant_id"))
        if not vendor_id or not tenant_id:
            continue

        parts_for_shop = parts_by_shop.get(shop_id) or []
        parts_for_vendor = parts_by_shop_vendor.get((shop_id, vendor_id)) or []
        items = _pick_items(parts_for_vendor, parts_for_shop)
        if not items:
            continue

        created_at = random_created_at()
        status = "received" if random.random() < 0.3 else "ordered"
        updated_at = created_at + timedelta(days=random.randint(0, 30), minutes=random.randint(0, 180))
        if updated_at > utcnow():
            updated_at = utcnow()

        user_id = _choose_user_id(vendor, fallback_user_id)
        order_number = next_number_by_shop[shop_id]
        next_number_by_shop[shop_id] = order_number + 1

        doc = {
            "vendor_id": vendor_id,
            "order_number": int(order_number),
            "items": items,
            "status": status,
            "is_active": True,
            "created_at": created_at,
            "updated_at": updated_at,
            "created_by": user_id,
            "updated_by": user_id,
            "shop_id": shop_id,
            "tenant_id": tenant_id,
        }

        if status == "received":
            received_at = updated_at if updated_at >= created_at else created_at
            doc["received_at"] = received_at
            doc["received_by"] = user_id

        docs_buffer.append(doc)
        generated_total += 1
        max_inserted_order_number_by_shop[shop_id] = max(
            order_number,
            max_inserted_order_number_by_shop.get(shop_id, order_number),
        )

        if not args.dry_run and len(docs_buffer) >= args.batch_size:
            result = db.parts_orders.insert_many(docs_buffer, ordered=False)
            inserted_total += len(result.inserted_ids)
            docs_buffer = []

    print(f"Target DB: {db_name}")
    print(f"Eligible shops: {len(eligible_shop_ids)}")
    print(f"Requested inserts: {args.count}")
    print(f"Generated records: {generated_total}")

    if args.dry_run:
        print("Dry run complete. No records inserted.")
        return

    if docs_buffer:
        result = db.parts_orders.insert_many(docs_buffer, ordered=False)
        inserted_total += len(result.inserted_ids)

    for shop_id, max_order_number in max_inserted_order_number_by_shop.items():
        desired_seq = max(1, int(max_order_number) - 1000 + 1)
        db.counters.update_one(
            {"_id": f"order_number_{shop_id}"},
            {
                "$setOnInsert": {"initial_value": 1000},
                "$max": {"seq": desired_seq},
                "$set": {"updated_at": utcnow()},
            },
            upsert=True,
        )

    print(f"Inserted records: {inserted_total}")


if __name__ == "__main__":
    main()
