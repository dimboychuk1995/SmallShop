import argparse
import random
import sys
from pathlib import Path

from dotenv import load_dotenv
from pymongo import MongoClient

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app.config import Config


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Randomly assign taxable=true/false for every customer in every shop DB."
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=None,
        help="Optional random seed for reproducible assignment.",
    )
    return parser.parse_args()


def resolve_shop_db_name(shop: dict) -> str:
    return (
        shop.get("db_name")
        or shop.get("database")
        or shop.get("db")
        or shop.get("mongo_db")
        or shop.get("shop_db")
        or ""
    )


def main() -> None:
    load_dotenv()
    args = parse_args()

    rng = random.Random(args.seed)

    client = MongoClient(Config.MONGO_URI)
    master_db = client[Config.MASTER_DB_NAME]

    total_customers = 0
    total_true = 0
    total_false = 0

    seen_dbs = set()
    shops = master_db.shops.find(
        {
            "$or": [
                {"db_name": {"$exists": True, "$ne": None}},
                {"database": {"$exists": True, "$ne": None}},
                {"db": {"$exists": True, "$ne": None}},
                {"mongo_db": {"$exists": True, "$ne": None}},
                {"shop_db": {"$exists": True, "$ne": None}},
            ]
        },
        {"db_name": 1, "database": 1, "db": 1, "mongo_db": 1, "shop_db": 1},
    )

    for shop in shops:
        db_name = str(resolve_shop_db_name(shop)).strip()
        if not db_name or db_name in seen_dbs:
            continue

        seen_dbs.add(db_name)
        shop_db = client[db_name]
        coll = shop_db.customers

        customer_docs = list(coll.find({}, {"_id": 1}))
        if not customer_docs:
            print(f"{db_name}: 0 customers")
            continue

        updates = []
        db_true = 0
        db_false = 0

        for doc in customer_docs:
            is_taxable = bool(rng.getrandbits(1))
            updates.append(
                {
                    "_id": doc["_id"],
                    "taxable": is_taxable,
                }
            )
            if is_taxable:
                db_true += 1
            else:
                db_false += 1

        for u in updates:
            coll.update_one({"_id": u["_id"]}, {"$set": {"taxable": u["taxable"]}})

        total_customers += len(updates)
        total_true += db_true
        total_false += db_false

        print(
            f"{db_name}: updated {len(updates)} customers "
            f"(taxable=True: {db_true}, taxable=False: {db_false})"
        )

    print(
        f"Done. Updated {total_customers} customers across {len(seen_dbs)} shop DBs "
        f"(taxable=True: {total_true}, taxable=False: {total_false})."
    )


if __name__ == "__main__":
    main()
