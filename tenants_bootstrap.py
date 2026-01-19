import os
import argparse
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from pymongo import MongoClient, ASCENDING, errors

try:
    from dotenv import load_dotenv  # type: ignore
    load_dotenv()
except Exception:
    pass


MONGO_URI = os.getenv("MONGO_URI", "mongodb://localhost:27017")
MONGO_DB = os.getenv("MONGO_DB", "shopmonley_dev")


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def get_db() -> Any:
    client = MongoClient(MONGO_URI)
    return client[MONGO_DB]


def ensure_tenants_indexes(db: Any) -> None:
    tenants = db["tenants"]
    # Unique slug for tenant routing (subdomain / url / identifier)
    tenants.create_index([("slug", ASCENDING)], unique=True, name="uniq_tenants_slug")
    tenants.create_index([("status", ASCENDING)], name="idx_tenants_status")
    tenants.create_index([("created_at", ASCENDING)], name="idx_tenants_created_at")


def make_tenant_doc(
    name: str,
    slug: str,
    default_timezone: str = "America/Chicago",
    owner_email: Optional[str] = None,
) -> Dict[str, Any]:
    t = now_utc()
    return {
        "name": name.strip(),
        "slug": slug.strip().lower(),
        "status": "active",  # active | suspended | trial | deleted
        "default_timezone": default_timezone,
        "plan": "trial",
        "limits": {
            "shops_max": 3,
            "users_max": 5,
            "storage_mb": 1024,
        },
        "contact": {
            "email": (owner_email or "").strip().lower(),
            "phone": "",
            "address": {},
        },
        "settings": {
            "features": {
                "inventory": True,
                "purchasing": True,
                "invoicing": True,
                "reports": True,
            },
            "schema_version": 1,
        },
        "created_at": t,
        "updated_at": t,
        "deleted_at": None,
    }


def cmd_init(args: argparse.Namespace) -> None:
    db = get_db()
    ensure_tenants_indexes(db)
    print("✅ tenants collection is ready (indexes ensured).")


def cmd_create(args: argparse.Namespace) -> None:
    db = get_db()
    ensure_tenants_indexes(db)

    doc = make_tenant_doc(
        name=args.name,
        slug=args.slug,
        default_timezone=args.timezone,
        owner_email=args.owner_email,
    )

    try:
        res = db["tenants"].insert_one(doc)
    except errors.DuplicateKeyError:
        raise SystemExit("❌ slug already exists. Choose another --slug.")

    print(f"✅ Tenant created: _id={res.inserted_id} slug={doc['slug']} name={doc['name']}")


def cmd_list(args: argparse.Namespace) -> None:
    db = get_db()
    q = {}
    if args.only_active:
        q["status"] = "active"

    items = list(db["tenants"].find(q, {"name": 1, "slug": 1, "status": 1, "default_timezone": 1, "created_at": 1}).sort("created_at", 1))
    if not items:
        print("(empty)")
        return

    for t in items:
        print(f"- slug={t.get('slug')} | name={t.get('name')} | status={t.get('status')} | tz={t.get('default_timezone')} | created={t.get('created_at')}")


def cmd_get(args: argparse.Namespace) -> None:
    db = get_db()
    t = db["tenants"].find_one({"slug": args.slug})
    if not t:
        raise SystemExit("❌ Tenant not found.")

    # Pretty print selected fields
    print("Tenant:")
    print(f"  _id: {t.get('_id')}")
    print(f"  name: {t.get('name')}")
    print(f"  slug: {t.get('slug')}")
    print(f"  status: {t.get('status')}")
    print(f"  default_timezone: {t.get('default_timezone')}")
    print(f"  plan: {t.get('plan')}")
    print(f"  limits: {t.get('limits')}")
    print(f"  contact: {t.get('contact')}")
    print(f"  settings: {t.get('settings')}")
    print(f"  created_at: {t.get('created_at')}")
    print(f"  updated_at: {t.get('updated_at')}")


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Tenants bootstrap (MongoDB)")
    sub = p.add_subparsers(dest="cmd", required=True)

    s_init = sub.add_parser("init", help="Create indexes for tenants collection")
    s_init.set_defaults(func=cmd_init)

    s_create = sub.add_parser("create", help="Create a tenant")
    s_create.add_argument("--name", required=True)
    s_create.add_argument("--slug", required=True, help="Unique tenant identifier (e.g. ltsrepair)")
    s_create.add_argument("--timezone", default="America/Chicago")
    s_create.add_argument("--owner-email", default="")
    s_create.set_defaults(func=cmd_create)

    s_list = sub.add_parser("list", help="List tenants")
    s_list.add_argument("--only-active", action="store_true")
    s_list.set_defaults(func=cmd_list)

    s_get = sub.add_parser("get", help="Get tenant by slug")
    s_get.add_argument("--slug", required=True)
    s_get.set_defaults(func=cmd_get)

    return p


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
