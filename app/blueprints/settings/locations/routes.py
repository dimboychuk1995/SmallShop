from __future__ import annotations

import re
import hashlib
from datetime import datetime, timezone

from bson import ObjectId
from flask import render_template, request, redirect, url_for, flash, session, jsonify

from app.blueprints.settings import settings_bp
from app.extensions import get_master_db, get_mongo_client
from app.utils.auth import login_required, SESSION_USER_ID, SESSION_TENANT_ID
from app.utils.permissions import permission_required, filter_nav_items
from app.blueprints.main.routes import NAV_ITEMS


# -----------------------------
# Helpers
# -----------------------------

def utcnow():
    return datetime.now(timezone.utc)


def _maybe_object_id(value):
    if not value:
        return None
    try:
        return ObjectId(str(value))
    except Exception:
        return str(value)


def _load_current_user(master):
    user_id = _maybe_object_id(session.get(SESSION_USER_ID))
    if not user_id:
        return None
    return master.users.find_one({"_id": user_id, "is_active": True})


def _load_current_tenant(master):
    tenant_id = _maybe_object_id(session.get(SESSION_TENANT_ID))
    if not tenant_id:
        return None
    return master.tenants.find_one({"_id": tenant_id, "status": "active"})


def _load_header_context():
    """
    Даёт app_user_display/app_tenant_display для layouts/app_base.html
    """
    master = get_master_db()

    user = _load_current_user(master)
    tenant = _load_current_tenant(master)

    if not user or not tenant:
        flash("Session expired. Please login again.", "error")
        session.clear()
        return None

    user_name = user.get("name") or user.get("username") or ""
    user_email = user.get("email") or ""
    tenant_name = tenant.get("name") or tenant.get("title") or tenant.get("company_name") or ""

    return {
        "app_user_display": user_name or user_email or "—",
        "app_tenant_display": tenant_name or "—",
        "nav_items": filter_nav_items(NAV_ITEMS),
        "active_page": "settings",
        # иногда удобно в темплейт тоже
        "_current_user": user,
        "_current_tenant": tenant,
    }


def _render_settings(template_name: str, **ctx):
    base = _load_header_context()
    if base is None:
        return redirect(url_for("main.index"))
    base.update(ctx)
    return render_template(template_name, **base)


def slugify_shop_name(name: str) -> str:
    s = (name or "").strip().lower()
    s = re.sub(r"[^a-z0-9]+", "-", s)
    s = s.strip("-")
    s = re.sub(r"-{2,}", "-", s)
    if len(s) < 2:
        s = (s + "-shop").strip("-")
    return s[:32]


def make_shop_db_name(tenant_slug: str, shop_slug: str) -> str:
    """
    Atlas limit (у тебя): max 38 bytes for db name.
    Format: shop_<tenant10>_<shop10>_<hash6>
    """
    t10 = (tenant_slug or "")[:10]
    s10 = (shop_slug or "")[:10]
    raw = f"{tenant_slug}:{shop_slug}"
    h6 = hashlib.sha1(raw.encode("utf-8")).hexdigest()[:6]
    return f"shop_{t10}_{s10}_{h6}"[:38]


def init_shop_database(shop_db_name: str, tenant_doc: dict, shop_doc: dict):
    """
    Чтобы Mongo реально создал базу (и Compass её показал) — создаём коллекцию settings.
    """
    client = get_mongo_client()
    sdb = client[shop_db_name]

    # если уже есть settings — не трогаем (чтобы не дублировать)
    if sdb.settings.count_documents({"key": "shop"}) == 0:
        sdb.settings.insert_many([
            {
                "key": "shop",
                "shop_name": shop_doc["name"],
                "shop_slug": shop_doc.get("slug"),
                "created_at": utcnow(),
            },
            {
                "key": "tenant_ref",
                "tenant_name": tenant_doc.get("name"),
                "tenant_slug": tenant_doc.get("slug"),
                "created_at": utcnow(),
            },
        ])

    sdb.settings.create_index("key", unique=True, name="uniq_settings_key")


def _shop_id_list(user_doc: dict) -> list[str]:
    """
    Возвращает список shop_ids как строки.
    shop_id больше НЕ используется.
    """
    if isinstance(user_doc.get("shop_ids"), list) and user_doc["shop_ids"]:
        return [str(x) for x in user_doc["shop_ids"]]
    return []


# -----------------------------
# UI Routes
# -----------------------------

@settings_bp.route("/locations", methods=["GET", "POST"])
@login_required
@permission_required("settings.manage_org")
def locations_index():
    master = get_master_db()

    user = _load_current_user(master)
    tenant = _load_current_tenant(master)

    if not user or not tenant:
        flash("Session mismatch. Please login again.", "error")
        session.clear()
        return redirect(url_for("main.index"))

    # -----------------------------
    # Create (POST)
    # -----------------------------
    if request.method == "POST":
        name = (request.form.get("name") or "").strip()
        address = (request.form.get("address") or "").strip()
        phone = (request.form.get("phone") or "").strip()

        if len(name) < 2:
            flash("Shop name is required.", "error")
            return redirect(url_for("settings.locations_index"))

        tenant_id = tenant["_id"]
        tenant_slug = tenant.get("slug") or slugify_shop_name(tenant.get("name") or "tenant")
        shop_slug = slugify_shop_name(name)

        # unique slug inside tenant
        if master.shops.find_one({"tenant_id": tenant_id, "slug": shop_slug}):
            flash("Shop with this name already exists.", "error")
            return redirect(url_for("settings.locations_index"))

        shop_db_name = make_shop_db_name(tenant_slug, shop_slug)

        shop_doc = {
            "tenant_id": tenant_id,
            "name": name,
            "slug": shop_slug,
            "db_name": shop_db_name,
            "address": address or None,
            "phone": phone or None,
            "status": "active",
            "is_active": True,
            "is_primary": False,
            "created_at": utcnow(),
            "updated_at": utcnow(),
        }

        try:
            res = master.shops.insert_one(shop_doc)
            new_shop_id = res.inserted_id

            # ✅ дать доступ текущему пользователю (shop_ids[])
            shop_ids = user.get("shop_ids")
            if isinstance(shop_ids, list):
                if str(new_shop_id) not in [str(x) for x in shop_ids]:
                    master.users.update_one(
                        {"_id": user["_id"]},
                        {"$push": {"shop_ids": new_shop_id}}
                    )
            else:
                # если shop_ids ещё нет — просто создаём массив
                master.users.update_one(
                    {"_id": user["_id"]},
                    {"$set": {"shop_ids": [new_shop_id]}}
                )

            # ✅ создать shop DB
            init_shop_database(shop_db_name, tenant, shop_doc)

            flash("Shop created successfully.", "success")
            return redirect(url_for("settings.locations_index"))

        except Exception as e:
            flash(f"Failed to create shop: {e}", "error")
            return redirect(url_for("settings.locations_index"))

    # -----------------------------
    # List (GET)
    # -----------------------------
    allowed_shop_ids = _shop_id_list(user)
    primary_shop_id = allowed_shop_ids[0] if allowed_shop_ids else None

    shops = []
    for s in master.shops.find({"tenant_id": tenant["_id"]}).sort("created_at", 1):
        sid = str(s["_id"])
        shops.append({
            "_id": sid,
            "name": s.get("name"),
            "slug": s.get("slug"),
            "db_name": s.get("db_name"),
            "phone": s.get("phone"),
            "email": s.get("email"),
            "address": s.get("address"),
            "address_line": s.get("address_line"),
            "city": s.get("city"),
            "state": s.get("state"),
            "zip": s.get("zip"),
            "status": s.get("status") or ("active" if s.get("is_active", True) else "disabled"),
            "is_active": bool(s.get("is_active", True)),
            "is_primary": (primary_shop_id is not None and sid == primary_shop_id) or bool(s.get("is_primary", False)),
            "has_access": (sid in allowed_shop_ids) if allowed_shop_ids else False,
        })

    return _render_settings(
        "public/settings/locations.html",
        shops=shops,
        allowed_shop_ids=allowed_shop_ids,
        primary_shop_id=primary_shop_id,
    )


# -----------------------------
# API (optional, for future JS)
# -----------------------------

@settings_bp.get("/api/locations")
@login_required
@permission_required("settings.manage_org")
def api_locations_list():
    master = get_master_db()
    user = _load_current_user(master)
    tenant = _load_current_tenant(master)
    if not user or not tenant:
        return jsonify({"ok": False, "errors": ["Session mismatch"]}), 401

    items = []
    for s in master.shops.find({"tenant_id": tenant["_id"]}).sort("created_at", 1):
        items.append({
            "id": str(s["_id"]),
            "name": s.get("name"),
            "slug": s.get("slug"),
            "db_name": s.get("db_name"),
            "phone": s.get("phone"),
            "address": s.get("address"),
            "is_active": bool(s.get("is_active", True)),
            "status": s.get("status") or "active",
        })

    return jsonify({"ok": True, "shops": items})


@settings_bp.post("/api/locations")
@login_required
@permission_required("settings.manage_org")
def api_locations_create():
    master = get_master_db()
    user = _load_current_user(master)
    tenant = _load_current_tenant(master)
    if not user or not tenant:
        return jsonify({"ok": False, "errors": ["Session mismatch"]}), 401

    data = request.get_json(silent=True) or {}
    name = (data.get("name") or "").strip()
    address = (data.get("address") or "").strip()
    phone = (data.get("phone") or "").strip()

    if len(name) < 2:
        return jsonify({"ok": False, "errors": ["Shop name is required."]}), 400

    tenant_slug = tenant.get("slug") or slugify_shop_name(tenant.get("name") or "tenant")
    shop_slug = slugify_shop_name(name)

    if master.shops.find_one({"tenant_id": tenant["_id"], "slug": shop_slug}):
        return jsonify({"ok": False, "errors": ["Shop already exists (slug conflict)."]}), 409

    shop_db_name = make_shop_db_name(tenant_slug, shop_slug)

    shop_doc = {
        "tenant_id": tenant["_id"],
        "name": name,
        "slug": shop_slug,
        "db_name": shop_db_name,
        "address": address or None,
        "phone": phone or None,
        "status": "active",
        "is_active": True,
        "is_primary": False,
        "created_at": utcnow(),
        "updated_at": utcnow(),
    }

    try:
        res = master.shops.insert_one(shop_doc)
        new_shop_id = res.inserted_id

        # ✅ grant access to current user (shop_ids only)
        shop_ids = user.get("shop_ids")
        if isinstance(shop_ids, list):
            if str(new_shop_id) not in [str(x) for x in shop_ids]:
                master.users.update_one({"_id": user["_id"]}, {"$push": {"shop_ids": new_shop_id}})
        else:
            master.users.update_one({"_id": user["_id"]}, {"$set": {"shop_ids": [new_shop_id]}})

        init_shop_database(shop_db_name, tenant, shop_doc)

        return jsonify({
            "ok": True,
            "shop": {
                "id": str(new_shop_id),
                "name": name,
                "slug": shop_slug,
                "db_name": shop_db_name,
            }
        }), 201

    except Exception as e:
        return jsonify({"ok": False, "errors": [str(e)]}), 500
