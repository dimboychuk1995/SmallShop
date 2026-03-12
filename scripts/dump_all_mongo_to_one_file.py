from __future__ import annotations

import gzip
import json
import os
from datetime import datetime
from pathlib import Path

from bson import json_util
from dotenv import load_dotenv
from pymongo import MongoClient


def main() -> int:
    load_dotenv()

    mongo_uri = os.getenv("MONGO_URI", "mongodb://127.0.0.1:27017")
    user_profile = os.getenv("USERPROFILE")
    if not user_profile:
        raise RuntimeError("USERPROFILE is not set")

    desktop_dir = Path(user_profile) / "Desktop"
    desktop_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_file = desktop_dir / f"mongo_full_dump_{timestamp}.jsonl.gz"

    client = MongoClient(mongo_uri, serverSelectionTimeoutMS=10000)
    client.admin.command("ping")

    db_names = sorted(client.list_database_names())

    total_collections = 0
    total_documents = 0

    with gzip.open(out_file, "wt", encoding="utf-8") as f:
        header = {
            "type": "dump_header",
            "created_at": datetime.utcnow().isoformat() + "Z",
            "mongo_uri": mongo_uri,
            "databases": db_names,
        }
        f.write(json.dumps(header, ensure_ascii=False) + "\n")

        for db_name in db_names:
            db = client[db_name]
            col_names = sorted(db.list_collection_names())

            f.write(
                json.dumps(
                    {
                        "type": "database_header",
                        "db": db_name,
                        "collections": col_names,
                    },
                    ensure_ascii=False,
                )
                + "\n"
            )

            for col_name in col_names:
                coll = db[col_name]
                total_collections += 1
                doc_count = 0

                f.write(
                    json.dumps(
                        {
                            "type": "collection_header",
                            "db": db_name,
                            "collection": col_name,
                        },
                        ensure_ascii=False,
                    )
                    + "\n"
                )

                for doc in coll.find({}, no_cursor_timeout=True):
                    doc_count += 1
                    total_documents += 1
                    rec = {
                        "type": "document",
                        "db": db_name,
                        "collection": col_name,
                        "doc": doc,
                    }
                    f.write(json_util.dumps(rec, ensure_ascii=False) + "\n")

                f.write(
                    json.dumps(
                        {
                            "type": "collection_footer",
                            "db": db_name,
                            "collection": col_name,
                            "documents": doc_count,
                        },
                        ensure_ascii=False,
                    )
                    + "\n"
                )

        footer = {
            "type": "dump_footer",
            "total_databases": len(db_names),
            "total_collections": total_collections,
            "total_documents": total_documents,
            "file": str(out_file),
        }
        f.write(json.dumps(footer, ensure_ascii=False) + "\n")

    print(f"Dump saved: {out_file}")
    print(f"Databases: {len(db_names)}")
    print(f"Collections: {total_collections}")
    print(f"Documents: {total_documents}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
