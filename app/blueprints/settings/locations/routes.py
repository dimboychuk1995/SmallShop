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
from app.utils.layout import build_app_layout_context


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
        return None


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


def _render_settings_page(template_name: str, **ctx):
    """
    Общий рендер для settings-страниц через единый layout builder.
    """
    layout = build_app_layout_context(filter_nav_items(NAV_ITEMS), "settings")

    if not layout.get("_current_user") or not layout.get("_current_tenant"):
        flash("Session data mismatch. Please login again.", "error")
        session.clear()
        return redirect(url_for("main.index"))

    layout.update(ctx)
    return render_template(template_name, **layout)


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
    Atlas limit: max 38 bytes for db name.
    Format: shop_<tenant10>_<shop10>_<hash6>
    """
    t10 = (tenant_slug or "")[:10]
    s10 = (shop_slug or "")[:10]
    raw = f"{tenant_slug}:{shop_slug}"
    h6 = hashlib.sha1(raw.encode("utf-8")).hexdigest()[:6]
    return f"shop_{t10}_{s10}_{h6}"[:38]


# -----------------------------
# NEW: parts categories seeding (shop DB)
# -----------------------------

DEFAULT_PARTS_CATEGORIES = [
    "Filters",
    "Electrical",
    "Exhaust",
    "Body",
    "Interior",
    "DEF",
    "Cores",
]


def _slugify_simple(name: str) -> str:
    s = (name or "").strip().lower()
    out = []
    last_dash = False
    for ch in s:
        if ch.isalnum():
            out.append(ch)
            last_dash = False
        else:
            if not last_dash:
                out.append("-")
                last_dash = True
    slug = "".join(out).strip("-")
    return slug or "category"


def seed_parts_categories(shop_db, shop_id: ObjectId):
    """
    Ensure default parts categories exist in shop DB (idempotent).
    """
    if shop_db is None or shop_id is None:
        return

    col = shop_db.parts_categories

    # Prevent duplicates per shop
    try:
        col.create_index([("shop_id", 1), ("slug", 1)], unique=True, name="uniq_parts_categories_shop_slug")
    except Exception:
        pass

    now = utcnow()

    for name in DEFAULT_PARTS_CATEGORIES:
        slug = _slugify_simple(name)
        col.update_one(
            {"shop_id": shop_id, "slug": slug},
            {
                "$setOnInsert": {
                    "name": name,
                    "slug": slug,
                    "shop_id": shop_id,
                    "is_active": True,
                    "created_at": now,
                },
                "$set": {
                    "updated_at": now,
                },
            },
            upsert=True,
        )


def init_shop_database(shop_db_name: str, tenant_doc: dict, shop_doc: dict):
    """
    Создаём базу шапа + сидим дефолтные parts_categories.
    Идемпотентно: можно вызвать несколько раз.
    """
    client = get_mongo_client()
    sdb = client[shop_db_name]

    now = utcnow()

    # settings: делаем upsert, чтобы не ловить duplicate key
    sdb.settings.update_one(
        {"key": "shop"},
        {"$setOnInsert": {
            "key": "shop",
            "shop_name": shop_doc.get("name"),
            "shop_slug": shop_doc.get("slug"),
            "created_at": now,
        }},
        upsert=True
    )

    sdb.settings.update_one(
        {"key": "tenant_ref"},
        {"$setOnInsert": {
            "key": "tenant_ref",
            "tenant_name": tenant_doc.get("name"),
            "tenant_slug": tenant_doc.get("slug"),
            "created_at": now,
        }},
        upsert=True
    )

    sdb.settings.create_index("key", unique=True, name="uniq_settings_key")

    # ✅ seed default categories (needs shop_id)
    shop_id = shop_doc.get("_id")
    if isinstance(shop_id, ObjectId):
        seed_parts_categories(sdb, shop_id)
    elif shop_id is not None:
        try:
            seed_parts_categories(sdb, ObjectId(str(shop_id)))
        except Exception:
            pass


def _grant_shop_to_owners(master, tenant_id, new_shop_id):
    """
    Добавляем новый shop только всем пользователям role=owner (в этом tenant).
    shop_id поля больше нет — только shop_ids[].
    """
    master.users.update_many(
        {
            "tenant_id": tenant_id,
            "role": "owner",
            "is_active": True,
            "$or": [
                {"shop_ids": {"$exists": False}},
                {"shop_ids": {"$ne": new_shop_id}},
            ],
        },
        [
            {
                "$set": {
                    "shop_ids": {
                        "$cond": [
                            {"$isArray": "$shop_ids"},
                            {
                                "$cond": [
                                    {"$in": [new_shop_id, "$shop_ids"]},
                                    "$shop_ids",
                                    {"$concatArrays": ["$shop_ids", [new_shop_id]]},
                                ]
                            },
                            [new_shop_id],
                        ]
                    },
                    "updated_at": utcnow(),
                }
            }
        ]
    )


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

        tenant_slug = tenant.get("slug") or slugify_shop_name(tenant.get("name") or "tenant")
        shop_slug = slugify_shop_name(name)

        if master.shops.find_one({"tenant_id": tenant["_id"], "slug": shop_slug}):
            flash("Shop with this name already exists.", "error")
            return redirect(url_for("settings.locations_index"))

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

            # ✅ IMPORTANT: нужен _id для seed parts_categories
            shop_doc["_id"] = new_shop_id

            # ✅ доступ выдаём только owners
            _grant_shop_to_owners(master, tenant["_id"], new_shop_id)

            # ✅ создать shop DB + seed parts_categories
            init_shop_database(shop_db_name, tenant, shop_doc)

            flash("Shop created successfully.", "success")
            return redirect(url_for("settings.locations_index"))

        except Exception as e:
            flash(f"Failed to create shop: {e}", "error")
            return redirect(url_for("settings.locations_index"))

    # -----------------------------
    # List (GET)
    # -----------------------------
    allowed_shop_ids = session.get("shop_ids") if isinstance(session.get("shop_ids"), list) else []
    allowed_shop_ids = [str(x) for x in allowed_shop_ids]

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
            "is_primary": False,  # primary = shop_ids[0], можно дорисовать позже
            "has_access": (sid in allowed_shop_ids),
        })

    return _render_settings_page("public/settings/locations.html", shops=shops)


# -----------------------------
# API (optional, for future JS)
# -----------------------------

@settings_bp.get("/api/locations")
@login_required
@permission_required("settings.manage_org")
def api_locations_list():
    master = get_master_db()
    tenant = _load_current_tenant(master)
    user = _load_current_user(master)

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

        # ✅ IMPORTANT: нужен _id для seed parts_categories
        shop_doc["_id"] = new_shop_id

        # ✅ доступ выдаём только owners
        _grant_shop_to_owners(master, tenant["_id"], new_shop_id)

        # ✅ создать shop DB + seed parts_categories
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
