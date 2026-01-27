from __future__ import annotations

from datetime import datetime, timezone

from bson import ObjectId
from flask import render_template, request, redirect, url_for, flash, session

from app.blueprints.settings import settings_bp
from app.extensions import get_master_db, get_mongo_client
from app.utils.auth import (
    login_required,
    SESSION_USER_ID,
    SESSION_TENANT_ID,
    SESSION_TENANT_DB,
    SESSION_SHOP_ID,
)
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


def _id_variants(value):
    """
    Варианты для надёжного поиска tenant_id:
    - как есть
    - ObjectId(.) если возможно
    - str(.)
    """
    if value is None:
        return []

    variants = [value]

    oid = _maybe_object_id(value)
    if oid is not None:
        variants.append(oid)

    variants.append(str(value))

    out = []
    seen = set()
    for v in variants:
        key = str(v)
        if key in seen:
            continue
        seen.add(key)
        out.append(v)
    return out


def _get_tenant_db():
    db_name = session.get(SESSION_TENANT_DB)
    if not db_name:
        return None
    client = get_mongo_client()
    return client[db_name]


def _load_current_user(master):
    user_id = _maybe_object_id(session.get(SESSION_USER_ID))
    if not user_id:
        return None
    return master.users.find_one({"_id": user_id, "is_active": True})


def _render_settings_page(template_name: str, **ctx):
    """
    Один общий рендер для settings-страниц через единый layout builder.
    """
    layout = build_app_layout_context(filter_nav_items(NAV_ITEMS), "settings")

    if not layout.get("_current_user") or not layout.get("_current_tenant"):
        flash("Session expired. Please login again.", "error")
        session.clear()
        return redirect(url_for("main.index"))

    layout.update(ctx)
    return render_template(template_name, **layout)


# -----------------------------
# UI Routes
# -----------------------------

@settings_bp.route("/users", methods=["GET", "POST"])
@login_required
@permission_required("settings.manage_users")
def users_index():
    master = get_master_db()

    tenant_id_raw = session.get(SESSION_TENANT_ID)
    if not tenant_id_raw:
        flash("Tenant session missing. Please login again.", "error")
        session.clear()
        return redirect(url_for("main.index"))

    current_user = _load_current_user(master)
    if not current_user:
        flash("User session mismatch. Please login again.", "error")
        session.clear()
        return redirect(url_for("main.index"))

    if request.method == "POST":
        return _handle_create_user(master, current_user, tenant_id_raw)

    # Истина: tenant_id из current_user (fallback на сессию)
    tenant_from_user = current_user.get("tenant_id") or tenant_id_raw
    tenant_values = _id_variants(tenant_from_user)

    users = list(
        master.users.find({"tenant_id": {"$in": tenant_values}}).sort("created_at", -1)
    )

    return _render_settings_page("public/settings/users.html", users=users)


def _handle_create_user(master, current_user, tenant_id_raw):
    first_name = (request.form.get("first_name") or "").strip()
    last_name = (request.form.get("last_name") or "").strip()
    email = (request.form.get("email") or "").strip().lower()
    phone = (request.form.get("phone") or "").strip()
    role = (request.form.get("role") or "viewer").strip().lower()
    is_active = bool(request.form.get("is_active"))

    password = request.form.get("password") or ""
    password_confirm = request.form.get("password_confirm") or ""

    if not first_name or not last_name or not email:
        flash("Please fill first name, last name and email.", "error")
        return redirect(url_for("settings.users_index"))

    if len(password) < 8:
        flash("Password must be at least 8 characters.", "error")
        return redirect(url_for("settings.users_index"))

    if password != password_confirm:
        flash("Passwords do not match.", "error")
        return redirect(url_for("settings.users_index"))

    if master.users.find_one({"email": email}):
        flash("User with this email already exists.", "error")
        return redirect(url_for("settings.users_index"))

    # Validate role exists in tenant DB
    tdb = _get_tenant_db()
    if tdb is None:
        flash("Tenant DB not found in session. Please login again.", "error")
        session.clear()
        return redirect(url_for("main.index"))

    role_doc = tdb.roles.find_one({"key": role})
    if not role_doc:
        flash("Selected role does not exist in tenant roles.", "error")
        return redirect(url_for("settings.users_index"))

    from werkzeug.security import generate_password_hash

    tenant_id = _maybe_object_id(current_user.get("tenant_id")) or _maybe_object_id(tenant_id_raw)
    creator_id = _maybe_object_id(session.get(SESSION_USER_ID))

    # ✅ Новый юзер получает доступ только к АКТИВНОЙ шапе (session shop_id),
    # fallback на primary шапу создателя (creator.shop_ids[0]).
    active_shop_oid = _maybe_object_id(session.get(SESSION_SHOP_ID))

    creator_shop_ids = current_user.get("shop_ids") if isinstance(current_user.get("shop_ids"), list) else []
    if active_shop_oid is None and creator_shop_ids:
        # creator_shop_ids может содержать ObjectId — это ок
        active_shop_oid = creator_shop_ids[0]

    shop_ids = [active_shop_oid] if active_shop_oid is not None else []

    user_doc = {
        "tenant_id": tenant_id,
        "shop_ids": shop_ids,  # ✅ только shop_ids
        "email": email,
        "password_hash": generate_password_hash(password),
        "first_name": first_name,
        "last_name": last_name,
        "name": f"{first_name} {last_name}".strip(),
        "phone": phone or None,
        "role": role,
        "is_active": is_active,
        "must_reset_password": False,
        "allow_permissions": [],
        "deny_permissions": [],
        "created_at": utcnow(),
        "updated_at": utcnow(),
        "created_by": creator_id,
    }

    master.users.insert_one(user_doc)

    flash("User created successfully.", "success")
    return redirect(url_for("settings.users_index"))
