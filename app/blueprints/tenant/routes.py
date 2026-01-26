from __future__ import annotations

import re
import hashlib
from datetime import datetime, timezone

from flask import request, jsonify
from werkzeug.security import generate_password_hash
from pymongo.errors import DuplicateKeyError

from app.extensions import get_master_db, get_mongo_client
from . import tenant_bp


def utcnow():
    return datetime.now(timezone.utc)


def slugify_company_name(name: str) -> str:
    """
    Convert company name to safe slug: a-z0-9-
    """
    s = (name or "").strip().lower()
    s = re.sub(r"[^a-z0-9]+", "-", s)
    s = s.strip("-")
    s = re.sub(r"-{2,}", "-", s)
    if len(s) < 3:
        s = (s + "-tenant").strip("-")
    return s[:32]


def make_tenant_db_name(company_name: str) -> str:
    slug = slugify_company_name(company_name)
    return f"tenant_{slug}"


def slugify_shop_name(name: str) -> str:
    """
    Shop slug (same rules).
    """
    s = (name or "").strip().lower()
    s = re.sub(r"[^a-z0-9]+", "-", s)
    s = s.strip("-")
    s = re.sub(r"-{2,}", "-", s)
    if len(s) < 2:
        s = (s + "-shop").strip("-")
    return s[:32]


def make_shop_db_name(tenant_slug: str, shop_slug: str) -> str:
    """
    Atlas limit: max 38 bytes for db name.
    Format: shop_<tenant10>_<shop10>_<hash6>
    """
    t10 = (tenant_slug or "")[:10]
    s10 = (shop_slug or "")[:10]

    raw = f"{tenant_slug}:{shop_slug}"
    h6 = hashlib.sha1(raw.encode("utf-8")).hexdigest()[:6]

    db = f"shop_{t10}_{s10}_{h6}"
    return db[:38]


def init_tenant_database(db_name: str, tenant_doc: dict):
    """
    Creates tenant DB and seeds defaults:
    - settings
    - roles (RBAC)
    """
    client = get_mongo_client()
    tdb = client[db_name]

    tdb.settings.insert_one({
        "key": "tenant",
        "tenant_name": tenant_doc["name"],
        "tenant_slug": tenant_doc["slug"],
        "timezone": tenant_doc.get("timezone", "UTC"),
        "created_at": utcnow(),
    })

    tdb.settings.create_index("key", unique=True, name="uniq_settings_key")

    from app.constants.permissions import build_default_roles

    tdb.roles.create_index("key", unique=True, name="uniq_roles_key")
    tdb.roles.create_index("name", name="idx_roles_name")

    if tdb.roles.count_documents({}) == 0:
        now = utcnow()
        roles = build_default_roles()
        for r in roles:
            r["created_at"] = now
            r["updated_at"] = now
        tdb.roles.insert_many(roles)


def init_shop_database(shop_db_name: str, tenant_doc: dict, shop_doc: dict):
    """
    Creates shop DB and seeds minimal defaults.
    """
    client = get_mongo_client()
    sdb = client[shop_db_name]

    # create at least one collection so DB shows up in Compass
    sdb.settings.insert_many([
        {
            "key": "shop",
            "shop_name": shop_doc["name"],
            "shop_slug": shop_doc.get("slug"),
            "created_at": utcnow(),
        },
        {
            "key": "tenant_ref",
            "tenant_name": tenant_doc["name"],
            "tenant_slug": tenant_doc["slug"],
            "timezone": tenant_doc.get("timezone", "UTC"),
            "created_at": utcnow(),
        }
    ])

    sdb.settings.create_index("key", unique=True, name="uniq_settings_key")


@tenant_bp.post("/register")
def register_tenant():
    master = get_master_db()

    company_name = (request.form.get("company_name") or "").strip()
    company_address = (request.form.get("company_address") or "").strip()
    company_phone = (request.form.get("company_phone") or "").strip()

    first_name = (request.form.get("first_name") or "").strip()
    last_name = (request.form.get("last_name") or "").strip()
    email = (request.form.get("email") or "").strip().lower()
    password = request.form.get("password") or ""

    errors = []
    if len(company_name) < 2:
        errors.append("Company name is required.")
    if len(company_address) < 5:
        errors.append("Company address is required.")
    if len(company_phone) < 7:
        errors.append("Company phone is required.")
    if len(first_name) < 1:
        errors.append("First name is required.")
    if len(last_name) < 1:
        errors.append("Last name is required.")
    if "@" not in email:
        errors.append("Valid email is required.")
    if len(password) < 6:
        errors.append("Password must be at least 6 characters.")

    if errors:
        return jsonify({"ok": False, "errors": errors}), 400

    # Email must be globally unique
    if master.users.find_one({"email": email}):
        return jsonify({"ok": False, "errors": ["Email already exists. Use another email."]}), 409

    tenant_slug = slugify_company_name(company_name)
    tenant_db_name = make_tenant_db_name(company_name)

    # First shop name = organization name
    first_shop_name = company_name
    first_shop_slug = slugify_shop_name(first_shop_name)
    shop_db_name = make_shop_db_name(tenant_slug, first_shop_slug)

    created_at = utcnow()
    tenant_id = None
    created_tenant_db = False
    created_shop_db = False

    try:
        tenant_doc = {
            "name": company_name,
            "slug": tenant_slug,
            "db_name": tenant_db_name,
            "address": company_address,
            "phone": company_phone,
            "timezone": "America/Chicago",
            "status": "active",
            "created_at": created_at,
            "updated_at": created_at,
        }
        tenant_res = master.tenants.insert_one(tenant_doc)
        tenant_id = tenant_res.inserted_id

        shop_doc = {
            "tenant_id": tenant_id,
            "name": first_shop_name,
            "slug": first_shop_slug,
            "db_name": shop_db_name,
            "address": company_address,
            "phone": company_phone,
            "status": "active",
            "is_active": True,
            "is_primary": True,
            "created_at": created_at,
            "updated_at": created_at,
        }
        shop_res = master.shops.insert_one(shop_doc)
        shop_id = shop_res.inserted_id

        # ✅ user has ONLY shop_ids; NO shop_id field
        user_doc = {
            "tenant_id": tenant_id,
            "shop_ids": [shop_id],
            "first_name": first_name,
            "last_name": last_name,
            "name": f"{first_name} {last_name}".strip(),
            "email": email,
            "password_hash": generate_password_hash(password),
            "role": "owner",
            "is_active": True,
            "created_at": created_at,
            "updated_at": created_at,
        }
        master.users.insert_one(user_doc)

        # Create tenant DB
        init_tenant_database(tenant_db_name, tenant_doc)
        created_tenant_db = True

        # Create shop DB
        init_shop_database(shop_db_name, tenant_doc, shop_doc)
        created_shop_db = True

        return jsonify({
            "ok": True,
            "tenant": {
                "tenant_id": str(tenant_id),
                "name": company_name,
                "slug": tenant_slug,
                "db_name": tenant_db_name,
            },
            "shop": {
                "shop_id": str(shop_id),
                "name": first_shop_name,
                "slug": first_shop_slug,
                "db_name": shop_db_name,
            }
        }), 201

    except DuplicateKeyError:
        if tenant_id:
            master.users.delete_many({"tenant_id": tenant_id})
            master.shops.delete_many({"tenant_id": tenant_id})
            master.tenants.delete_one({"_id": tenant_id})

        client = get_mongo_client()
        if created_shop_db:
            client.drop_database(shop_db_name)
        if created_tenant_db:
            client.drop_database(tenant_db_name)

        return jsonify({
            "ok": False,
            "errors": ["Company already exists (slug/db conflict). Try a different company name."]
        }), 409

    except Exception as e:
        if tenant_id:
            master.users.delete_many({"tenant_id": tenant_id})
            master.shops.delete_many({"tenant_id": tenant_id})
            master.tenants.delete_one({"_id": tenant_id})

        client = get_mongo_client()
        if created_shop_db:
            client.drop_database(shop_db_name)
        if created_tenant_db:
            client.drop_database(tenant_db_name)

        return jsonify({"ok": False, "errors": [str(e)]}), 500
