from __future__ import annotations

import os
from datetime import datetime, timezone

from pymongo import MongoClient


def main() -> None:
    client = MongoClient(os.environ.get("MONGO_URI", "mongodb://127.0.0.1:27017"), serverSelectionTimeoutMS=5000)
    client.admin.command("ping")

    dbs = [
        d
        for d in client.list_database_names()
        if "parts" in client[d].list_collection_names() and client[d].parts.count_documents({}) > 0
    ]
    if len(dbs) != 1:
        raise RuntimeError(f"Expected 1 target DB, found: {dbs}")

    db_name = dbs[0]
    db = client[db_name]

    invalid_filter = {
        "is_active": {"$ne": False},
        "do_not_track_inventory": True,
        "$or": [
            {"core_has_charge": True},
            {"core_cost": {"$ne": None}},
        ],
    }

    before = db.parts.count_documents(invalid_filter)
    result = db.parts.update_many(
        {
            "is_active": {"$ne": False},
            "do_not_track_inventory": True,
        },
        {
            "$set": {
                "core_has_charge": False,
                "updated_at": datetime.now(timezone.utc),
            },
            "$unset": {
                "core_cost": "",
            },
        },
    )
    after = db.parts.count_documents(invalid_filter)

    print(
        f"DB={db_name} matched={result.matched_count} modified={result.modified_count} "
        f"before_invalid={before} after_invalid={after}"
    )


if __name__ == "__main__":
    main()
