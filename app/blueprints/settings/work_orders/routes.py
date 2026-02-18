from __future__ import annotations

from flask import render_template, redirect, url_for, flash, session

from app.blueprints.settings import settings_bp
from app.extensions import get_master_db
from app.utils.auth import login_required, SESSION_USER_ID, SESSION_TENANT_ID
from app.utils.permissions import permission_required, filter_nav_items
from app.blueprints.main.routes import NAV_ITEMS
from app.utils.layout import build_app_layout_context
from bson import ObjectId


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


@settings_bp.route("/work_orders", methods=["GET"])
@login_required
@permission_required("settings.manage_org")
def work_orders_index():
    master = get_master_db()
    user = _load_current_user(master)
    tenant = _load_current_tenant(master)

    if not user or not tenant:
        flash("Session mismatch. Please login again.", "error")
        session.clear()
        return redirect(url_for("main.index"))

    return _render_settings_page("public/settings/work_orders.html")
