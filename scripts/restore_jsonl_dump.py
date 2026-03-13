import argparse
import gzip
from collections import defaultdict

from bson import json_util
from pymongo import MongoClient


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Restore custom JSONL gzip Mongo dump into local MongoDB."
    )
    parser.add_argument("dump_file", help="Path to .jsonl.gz dump file")
    parser.add_argument(
        "--uri",
        default="mongodb://127.0.0.1:27017",
        help="MongoDB URI (default: mongodb://127.0.0.1:27017)",
    )
    parser.add_argument(
        "--drop",
        action="store_true",
        help="Drop each collection at first encounter before inserting documents.",
    )
    parser.add_argument(
        "--include-system-dbs",
        action="store_true",
        help="Also restore admin/config/local databases.",
    )
    return parser.parse_args()


def should_skip_db(db_name: str, include_system_dbs: bool) -> bool:
    if include_system_dbs:
        return False
    return db_name in {"admin", "config", "local"}


def main() -> None:
    args = parse_args()
    client = MongoClient(args.uri)

    dropped = set()
    inserted = defaultdict(int)

    with gzip.open(args.dump_file, mode="rt", encoding="utf-8") as fh:
        for line_no, raw in enumerate(fh, start=1):
            line = raw.strip()
            if not line:
                continue

            try:
                rec = json_util.loads(line)
            except Exception as exc:
                raise RuntimeError(
                    f"Invalid JSON at line {line_no}: {exc}"
                ) from exc

            if rec.get("type") != "document":
                continue

            db_name = rec.get("db")
            coll_name = rec.get("collection")
            doc = rec.get("doc")

            if not db_name or not coll_name or doc is None:
                continue

            if should_skip_db(db_name, args.include_system_dbs):
                continue

            coll = client[db_name][coll_name]
            key = (db_name, coll_name)
            if args.drop and key not in dropped:
                coll.drop()
                dropped.add(key)

            coll.insert_one(doc)
            inserted[key] += 1

    total = sum(inserted.values())
    print(f"Restored {total} documents into {len(inserted)} collections.")
    for (db_name, coll_name), count in sorted(inserted.items()):
        print(f" - {db_name}.{coll_name}: {count}")


if __name__ == "__main__":
    main()
