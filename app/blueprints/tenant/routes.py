from __future__ import annotations

import re
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
    # replace non-alnum with dash
    s = re.sub(r"[^a-z0-9]+", "-", s)
    s = s.strip("-")
    # collapse multiple dashes
    s = re.sub(r"-{2,}", "-", s)
    # enforce length
    if len(s) < 3:
        s = (s + "-tenant").strip("-")
    return s[:32]


def make_tenant_db_name(company_name: str) -> str:
    slug = slugify_company_name(company_name)
    return f"tenant_{slug}"


def init_tenant_database(db_name: str, tenant_doc: dict):
    """
    Creates tenant DB and seeds minimal defaults.
    MongoDB creates DB lazily (on first write), so we write a settings doc.
    """
    client = get_mongo_client()
    tdb = client[db_name]

    # Seed settings
    tdb.settings.insert_one({
        "key": "tenant",
        "tenant_name": tenant_doc["name"],
        "tenant_slug": tenant_doc["slug"],
        "timezone": tenant_doc.get("timezone", "UTC"),
        "created_at": utcnow(),
    })

    # Example indexes you’ll likely want later (safe to leave for now)
    tdb.settings.create_index("key", unique=True, name="uniq_settings_key")


@tenant_bp.post("/register")
def register_tenant():
    """
    Registration flow:
    - Insert into master.tenants (company info + slug + db_name)
    - Insert into master.shops (single shop)
    - Insert into master.users (first user = owner)
    - Create separate tenant database by name
    """
    master = get_master_db()

    # Read form fields
    company_name = (request.form.get("company_name") or "").strip()
    company_address = (request.form.get("company_address") or "").strip()
    company_phone = (request.form.get("company_phone") or "").strip()

    first_name = (request.form.get("first_name") or "").strip()
    last_name = (request.form.get("last_name") or "").strip()
    email = (request.form.get("email") or "").strip().lower()
    password = request.form.get("password") or ""

    # Basic validation (minimal for now)
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

    # Generate slug + tenant DB name from company name
    tenant_slug = slugify_company_name(company_name)
    tenant_db_name = make_tenant_db_name(company_name)

    created_at = utcnow()

    tenant_id = None
    created_db = False

    try:
        # 1) Create tenant in master DB
        tenant_doc = {
            "name": company_name,
            "slug": tenant_slug,
            "db_name": tenant_db_name,
            "address": company_address,
            "phone": company_phone,
            "timezone": "America/Chicago",  # можно позже сделать выбор в форме
            "status": "active",
            "created_at": created_at,
            "updated_at": created_at,
        }
        tenant_res = master.tenants.insert_one(tenant_doc)
        tenant_id = tenant_res.inserted_id

        # 2) Create shop (single)
        shop_doc = {
            "tenant_id": tenant_id,
            "name": "Main Shop",
            "address": company_address,
            "phone": company_phone,
            "created_at": created_at,
        }
        shop_res = master.shops.insert_one(shop_doc)
        shop_id = shop_res.inserted_id

        # 3) Create first user (owner)
        user_doc = {
            "tenant_id": tenant_id,
            "first_name": first_name,
            "last_name": last_name,
            "name": f"{first_name} {last_name}".strip(),
            "email": email,
            "password_hash": generate_password_hash(password),
            "role": "owner",
            "is_active": True,
            "shop_id": shop_id,
            "created_at": created_at,
        }
        master.users.insert_one(user_doc)

        # 4) Create tenant database
        init_tenant_database(tenant_db_name, tenant_doc)
        created_db = True

        return jsonify({
            "ok": True,
            "tenant": {
                "tenant_id": str(tenant_id),
                "name": company_name,
                "slug": tenant_slug,
                "db_name": tenant_db_name
            }
        }), 201

    except DuplicateKeyError:
        # Unique slug/db_name conflict
        # Rollback inserted docs if any
        if tenant_id:
            master.users.delete_many({"tenant_id": tenant_id})
            master.shops.delete_many({"tenant_id": tenant_id})
            master.tenants.delete_one({"_id": tenant_id})

        return jsonify({
            "ok": False,
            "errors": ["Company already exists (slug/db conflict). Try a different company name."]
        }), 409

    except Exception as e:
        # Rollback master inserts
        if tenant_id:
            master.users.delete_many({"tenant_id": tenant_id})
            master.shops.delete_many({"tenant_id": tenant_id})
            master.tenants.delete_one({"_id": tenant_id})

        # If tenant DB was created, drop it
        if created_db:
            client = get_mongo_client()
            client.drop_database(tenant_db_name)

        return jsonify({"ok": False, "errors": [str(e)]}), 500
