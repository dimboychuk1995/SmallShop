from __future__ import annotations

from datetime import datetime, timezone

from bson import ObjectId
from flask import flash, redirect, session, url_for

from app.blueprints.main.routes import _render_app_page
from app.blueprints.work_orders import work_orders_bp
from app.extensions import get_master_db, get_mongo_client
from app.utils.auth import login_required, SESSION_TENANT_ID
from app.utils.permissions import permission_required


def utcnow():
    return datetime.now(timezone.utc)


def _oid(value):
    if not value:
        return None
    try:
        return ObjectId(str(value))
    except Exception:
        return None


def _tenant_id_variants():
    raw = session.get(SESSION_TENANT_ID)
    out = set()
    if raw is None:
        return []
    out.add(raw)
    out.add(str(raw))
    oid = _oid(raw)
    if oid:
        out.add(oid)
    return list(out)


def _get_active_shop(master):
    shop_id_raw = session.get("shop_id")
    shop_oid = _oid(shop_id_raw)
    if not shop_oid:
        return None

    tenant_variants = _tenant_id_variants()
    if not tenant_variants:
        return None

    return master.shops.find_one({"_id": shop_oid, "tenant_id": {"$in": tenant_variants}})


def _get_shop_db(master):
    shop = _get_active_shop(master)
    if not shop:
        return None, None

    db_name = (
        shop.get("db_name")
        or shop.get("database")
        or shop.get("db")
        or shop.get("mongo_db")
        or shop.get("shop_db")
    )
    if not db_name:
        return None, shop

    client = get_mongo_client()
    return client[str(db_name)], shop


def _work_orders_collection():
    master = get_master_db()
    db, shop = _get_shop_db(master)
    if db is None:
        return None, None, None
    return db.work_orders, shop, master


@work_orders_bp.get("/work_orders")
@login_required
@permission_required("work_orders.view")
def work_orders_page():
    coll, shop, master = _work_orders_collection()
    if coll is None or shop is None:
        flash("Shop database not configured for this shop.", "error")
        return redirect(url_for("main.dashboard"))

    # Пока без логики/CRUD: просто открываем страницу.
    # Позже сюда добавим список ордеров, фильтры, создание, статусы и т.д.
    return _render_app_page(
        "public/work_orders/work_orders.html",
        active_page="work_orders",
        work_orders=[],
    )

@work_orders_bp.get("/work_orders/details")
@login_required
@permission_required("work_orders.create")
def work_order_details_page():
    # Пока без логики. Тут будем собирать создание WO.
    return _render_app_page(
        "public/work_orders/work_order_details.html",
        active_page="work_orders",
    )