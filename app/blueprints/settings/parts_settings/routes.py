from __future__ import annotations

from datetime import datetime, timezone

from bson import ObjectId
from flask import render_template, redirect, url_for, flash, session

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
# Helpers (как в users.py)
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


def _load_shops_for_tenant(master, tenant_id):
    """
    Отдаём список шап (для UI) в формате:
      [{id, name}, ...]
    """
    shops = []
    if not tenant_id:
        return shops

    for s in master.shops.find({"tenant_id": tenant_id}).sort("created_at", 1):
        shops.append({
            "id": str(s["_id"]),
            "name": s.get("name") or "—",
        })
    return shops


# -----------------------------
# UI Route: Parts Settings
# -----------------------------

@settings_bp.route("/parts-settings", methods=["GET"])
@login_required
@permission_required("parts.edit")
def parts_settings_index():
    """
    Рендер страницы Parts Settings.
    Шаблон: public/settings/parts_settings.html
    """
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

    # tenant id (нормализуем)
    tenant_from_user = current_user.get("tenant_id") or tenant_id_raw
    tenant_oid = _maybe_object_id(tenant_from_user) or _maybe_object_id(tenant_id_raw)

    # активная шапа
    active_shop_id = str(session.get(SESSION_SHOP_ID) or "")

    # (опционально) список шап — если в шаблоне надо показать список/селектор
    shops_for_ui = _load_shops_for_tenant(master, tenant_oid)

    # (опционально) доступ к tenant DB, если позже захочешь тянуть роли/настройки/справочники
    tdb = _get_tenant_db()
    tenant_db_name = session.get(SESSION_TENANT_DB) or ""

    return _render_settings_page(
        "public/settings/parts_settings.html",
        active_shop_id=active_shop_id,
        tenant_id=str(tenant_oid or tenant_id_raw),
        tenant_db_name=tenant_db_name,
        shops_for_ui=shops_for_ui,
        now_utc=utcnow(),
        # если шаблону нужно понимать пользователя:
        current_user=current_user,
    )
