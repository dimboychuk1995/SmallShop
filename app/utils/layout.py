from __future__ import annotations

from bson import ObjectId
from flask import session

from app.extensions import get_master_db


def _maybe_object_id(value):
    if not value:
        return None
    try:
        return ObjectId(str(value))
    except Exception:
        return None


def build_app_layout_context(nav_items, active_page: str):
    """
    Единая точка: собираем все переменные для layouts/app_base.html:
      - app_user_display
      - app_tenant_display
      - app_shop_display (active shop from session["shop_id"])
      - nav_items / active_page
      - также отдаём user/tenant (иногда удобно)
    """
    master = get_master_db()

    user_id = _maybe_object_id(session.get("user_id"))
    tenant_id = _maybe_object_id(session.get("tenant_id"))
    shop_id = _maybe_object_id(session.get("shop_id"))

    user = master.users.find_one({"_id": user_id, "is_active": True}) if user_id else None
    tenant = master.tenants.find_one({"_id": tenant_id, "status": "active"}) if tenant_id else None

    # display
    user_name = (user or {}).get("name") or (user or {}).get("username") or ""
    user_email = (user or {}).get("email") or ""
    tenant_name = (tenant or {}).get("name") or (tenant or {}).get("title") or (tenant or {}).get("company_name") or ""

    app_user_display = user_name or user_email or "—"
    app_tenant_display = tenant_name or "—"

    app_shop_display = "—"
    if shop_id and tenant:
        shop = master.shops.find_one({"_id": shop_id, "tenant_id": tenant["_id"]})
        if shop:
            app_shop_display = shop.get("name") or "—"

    return {
        "app_user_display": app_user_display,
        "app_tenant_display": app_tenant_display,
        "app_shop_display": app_shop_display,
        "nav_items": nav_items,
        "active_page": active_page,
        "_current_user": user,
        "_current_tenant": tenant,
    }
