from __future__ import annotations

import argparse
import os
import random
from datetime import datetime, timezone

from pymongo import MongoClient


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def discover_target_db(client: MongoClient, explicit_db_name: str | None) -> str:
    if explicit_db_name:
        return explicit_db_name

    candidates: list[str] = []
    for db_name in client.list_database_names():
        db = client[db_name]
        if "parts" not in db.list_collection_names():
            continue
        if db.parts.count_documents({}) <= 0:
            continue
        candidates.append(db_name)

    if not candidates:
        raise RuntimeError("No database with non-empty 'parts' collection found. Use --db-name.")

    if len(candidates) > 1:
        raise RuntimeError(
            "More than one DB has non-empty 'parts' collection: "
            + ", ".join(candidates)
            + ". Use --db-name to select target."
        )

    return candidates[0]


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Set do_not_track_inventory flag for a target ratio of active parts."
    )
    parser.add_argument(
        "--ratio",
        type=float,
        default=0.10,
        help="Target ratio for active parts with do_not_track_inventory=true (default 0.10).",
    )
    parser.add_argument("--db-name", type=str, default=None, help="Target Mongo database name.")
    parser.add_argument("--seed", type=int, default=None, help="Random seed for reproducible selection.")
    parser.add_argument("--dry-run", action="store_true", help="Only print planned changes.")
    args = parser.parse_args()

    if args.ratio < 0 or args.ratio > 1:
        raise SystemExit("--ratio must be in [0, 1]")

    if args.seed is not None:
        random.seed(args.seed)

    mongo_uri = os.environ.get("MONGO_URI", "mongodb://127.0.0.1:27017")
    client = MongoClient(mongo_uri, serverSelectionTimeoutMS=5000)
    client.admin.command("ping")

    db_name = discover_target_db(client, args.db_name)
    db = client[db_name]

    active_filter = {"is_active": {"$ne": False}}
    total_active = db.parts.count_documents(active_filter)
    if total_active <= 0:
        print(f"Target DB: {db_name}")
        print("No active parts found. Nothing to update.")
        return

    target_count = int(round(total_active * args.ratio))
    if args.ratio > 0 and target_count <= 0:
        target_count = 1

    already_ids = [
        row.get("_id")
        for row in db.parts.find(
            {"is_active": {"$ne": False}, "do_not_track_inventory": True},
            {"_id": 1},
        )
        if row.get("_id") is not None
    ]
    already_count = len(already_ids)

    print(f"Target DB: {db_name}")
    print(f"Active parts: {total_active}")
    print(f"Current do_not_track_inventory=true: {already_count}")
    print(f"Target count by ratio {args.ratio:.2%}: {target_count}")

    if already_count >= target_count:
        print("Current count is already at or above target. No updates needed.")
        return

    need_to_add = target_count - already_count
    pool_ids = [
        row.get("_id")
        for row in db.parts.find(
            {
                "is_active": {"$ne": False},
                "$or": [
                    {"do_not_track_inventory": {"$exists": False}},
                    {"do_not_track_inventory": False},
                ],
            },
            {"_id": 1},
        )
        if row.get("_id") is not None
    ]

    if not pool_ids:
        print("No eligible parts left to update.")
        return

    if need_to_add > len(pool_ids):
        need_to_add = len(pool_ids)

    picked_ids = random.sample(pool_ids, need_to_add)

    print(f"Will set do_not_track_inventory=true for: {len(picked_ids)} parts")
    if args.dry_run:
        print("Dry run complete. No records updated.")
        return

    now = utcnow()
    result = db.parts.update_many(
        {"_id": {"$in": picked_ids}},
        {
            "$set": {
                "do_not_track_inventory": True,
                "updated_at": now,
            }
        },
    )

    final_count = db.parts.count_documents(
        {"is_active": {"$ne": False}, "do_not_track_inventory": True}
    )

    print(f"Matched: {result.matched_count}, modified: {result.modified_count}")
    print(f"Final do_not_track_inventory=true: {final_count} of {total_active}")


if __name__ == "__main__":
    main()
