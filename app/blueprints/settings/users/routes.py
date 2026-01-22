from __future__ import annotations

from datetime import datetime, timezone

from bson import ObjectId
from flask import render_template, request, redirect, url_for, flash, session

from app.blueprints.settings import settings_bp
from app.extensions import get_master_db, get_mongo_client
from app.utils.auth import login_required, SESSION_USER_ID, SESSION_TENANT_ID, SESSION_TENANT_DB
from app.utils.permissions import permission_required, filter_nav_items
from app.blueprints.main.routes import NAV_ITEMS


def utcnow():
    return datetime.now(timezone.utc)


def _maybe_object_id(value):
    if not value:
        return None
    try:
        return ObjectId(str(value))
    except Exception:
        return str(value)


def _id_variants(value):
    """
    Возвращает варианты значения id для надёжного поиска:
    - как есть
    - ObjectId(...) если возможно
    - str(...)
    """
    if value is None:
        return []
    variants = []
    variants.append(value)

    oid = _maybe_object_id(value)
    if oid is not None:
        variants.append(oid)

    variants.append(str(value))
    # уникализируем, сохраняя порядок
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
    return master.users.find_one({"_id": user_id})


def _load_header_context():
    """
    Даёт app_user_display/app_tenant_display для layouts/app_base.html
    """
    master = get_master_db()

    user_id = _maybe_object_id(session.get(SESSION_USER_ID))
    tenant_id = _maybe_object_id(session.get(SESSION_TENANT_ID))

    user = master.users.find_one({"_id": user_id, "is_active": True})
    tenant = master.tenants.find_one({"_id": tenant_id, "status": "active"})

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
    }


def _render_settings(template_name: str, **ctx):
    base = _load_header_context()
    if base is None:
        return redirect(url_for("main.index"))
    base.update(ctx)
    return render_template(template_name, **base)


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

    # ✅ Истина — tenant_id из master.users текущего пользователя
    tenant_from_user = current_user.get("tenant_id")
    shop_from_user = current_user.get("shop_id")

    tenant_values = []
    for v in _id_variants(tenant_from_user) + _id_variants(tenant_id_raw):
        tenant_values.append(v)
    # unique
    tenant_values = [v for v in dict.fromkeys([x for x in tenant_values if x is not None])]

    shop_values = _id_variants(shop_from_user)

    # 1) основной поиск по tenant_id
    users = list(
        master.users.find({"tenant_id": {"$in": tenant_values}}).sort("created_at", -1)
    )

    # 2) fallback (если вдруг у тебя часть пользователей “привязана” к shop_id)
    if not users and shop_values:
        users = list(
            master.users.find({"shop_id": {"$in": shop_values}}).sort("created_at", -1)
        )

    debug_users = {
        "handler": "settings.users_index",
        "template": "public/settings/users.html",
        "master_db_name": getattr(master, "name", ""),
        "mongo_address": str(getattr(getattr(master, "client", None), "address", "")),
        "session_user_id": str(session.get(SESSION_USER_ID) or ""),
        "session_tenant_id": str(session.get(SESSION_TENANT_ID) or ""),
        "current_user_id": str(current_user.get("_id") or ""),
        "current_user_tenant_id": str(tenant_from_user or ""),
        "current_user_shop_id": str(shop_from_user or ""),
        "tenant_values": [str(x) for x in tenant_values],
        "shop_values": [str(x) for x in shop_values],
        "total_users_in_master": master.users.count_documents({}),
        "found_users": len(users),
    }

    return _render_settings("public/settings/users.html", users=users, debug_users=debug_users)


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

    # Email uniqueness (global, because login uses email only)
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

    # ✅ tenant_id берём из current_user (чтобы не было рассинхрона)
    tenant_id = _maybe_object_id(current_user.get("tenant_id")) or _maybe_object_id(tenant_id_raw)
    creator_id = _maybe_object_id(session.get(SESSION_USER_ID))

    shop_id = current_user.get("shop_id")

    user_doc = {
        "tenant_id": tenant_id,
        "shop_id": shop_id,
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

    if user_doc["shop_id"] is None:
        user_doc.pop("shop_id", None)

    master.users.insert_one(user_doc)

    flash("User created successfully.", "success")
    return redirect(url_for("settings.users_index"))
