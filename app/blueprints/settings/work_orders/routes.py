from __future__ import annotations

from datetime import datetime, timezone

from flask import render_template, redirect, url_for, flash, session, request

from app.blueprints.settings import settings_bp
from app.extensions import get_master_db, get_mongo_client
from app.utils.auth import login_required, SESSION_USER_ID, SESSION_TENANT_ID, SESSION_SHOP_ID
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


def _get_shop_db_strict(master):
    client = get_mongo_client()

    shop_id = _maybe_object_id(session.get(SESSION_SHOP_ID))
    if not shop_id:
        return None, None

    shop = master.shops.find_one({"_id": shop_id})
    if not shop:
        return None, None

    db_name = (
        shop.get("db_name")
        or shop.get("database")
        or shop.get("mongo_db")
        or shop.get("shop_db")
    )
    if not db_name:
        return None, None

    return client[str(db_name)], shop_id


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


@settings_bp.route("/work_orders", methods=["GET", "POST"])
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

    sdb, shop_oid = _get_shop_db_strict(master)
    if sdb is None or shop_oid is None:
        flash("Please select an active shop first.", "error")
        return redirect(url_for("main.settings"))

    rules_col = sdb.shop_supply_amount_rules
    existing = rules_col.find_one({"shop_id": shop_oid})
    core_rules_col = sdb.core_charge_rules
    core_existing = core_rules_col.find_one({"shop_id": shop_oid})

    if request.method == "POST":
        raw = (request.form.get("shop_supply_procentage") or "").strip()
        charge_for_cores_default = bool(request.form.get("charge_for_cores_default"))
        try:
            value = float(raw)
        except Exception:
            flash("Shop supply amount must be a number.", "error")
            return redirect(url_for("settings.work_orders_index"))

        now = datetime.now(timezone.utc)
        rules_col.update_one(
            {"shop_id": shop_oid},
            {
                "$set": {
                    "shop_supply_procentage": value,
                    "is_active": True,
                    "updated_at": now,
                },
                "$setOnInsert": {
                    "shop_id": shop_oid,
                    "created_at": now,
                },
            },
            upsert=True,
        )

        core_rules_col.update_one(
            {"shop_id": shop_oid},
            {
                "$set": {
                    "charge_for_cores_default": charge_for_cores_default,
                    "updated_at": now,
                    "updated_by": user.get("_id"),
                },
                "$setOnInsert": {
                    "shop_id": shop_oid,
                    "created_at": now,
                    "created_by": user.get("_id"),
                },
            },
            upsert=True,
        )

        flash("Work order settings updated.", "success")
        return redirect(url_for("settings.work_orders_index"))

    if existing is None:
        rules_col.update_one(
            {"shop_id": shop_oid},
            {
                "$setOnInsert": {
                    "shop_id": shop_oid,
                    "shop_supply_procentage": 5,
                    "is_active": True,
                    "created_at": datetime.now(timezone.utc),
                }
            },
            upsert=True,
        )
        existing = rules_col.find_one({"shop_id": shop_oid})

    if core_existing is None:
        now = datetime.now(timezone.utc)
        core_rules_col.update_one(
            {"shop_id": shop_oid},
            {
                "$setOnInsert": {
                    "shop_id": shop_oid,
                    "charge_for_cores_default": False,
                    "created_at": now,
                    "created_by": user.get("_id"),
                },
                "$set": {
                    "updated_at": now,
                    "updated_by": user.get("_id"),
                },
            },
            upsert=True,
        )
        core_existing = core_rules_col.find_one({"shop_id": shop_oid})

    supply_value = existing.get("shop_supply_procentage") if isinstance(existing, dict) else 5
    core_charge_default = bool(core_existing.get("charge_for_cores_default")) if isinstance(core_existing, dict) else False

    return _render_settings_page(
        "public/settings/work_orders.html",
        shop_supply_procentage=supply_value,
        core_charge_default=core_charge_default,
    )
