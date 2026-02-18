from __future__ import annotations

from datetime import datetime, timezone

from bson import ObjectId
from flask import request, redirect, url_for, flash, session

from app.blueprints.customers import customers_bp
from app.blueprints.main.routes import _render_app_page
from app.extensions import get_master_db, get_mongo_client
from app.utils.auth import (
    login_required,
    SESSION_TENANT_ID,
    SESSION_USER_ID,
)
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


def _customers_collection():
    master = get_master_db()
    db, shop = _get_shop_db(master)
    if db is None:
        return None, None, None
    return db.customers, shop, master


@customers_bp.get("/customers")
@login_required
@permission_required("customers.view")
def customers_page():
    coll, shop, master = _customers_collection()
    if coll is None or shop is None:
        flash("Shop database not configured for this shop.", "error")
        return redirect(url_for("main.dashboard"))

    customers = list(
        coll.find({}).sort([("is_active", -1), ("company_name", 1), ("last_name", 1), ("first_name", 1), ("created_at", -1)])
    )

    return _render_app_page(
        "public/customers.html",
        active_page="customers",
        customers=customers,
    )


@customers_bp.post("/customers/create")
@login_required
@permission_required("customers.edit")
def customers_create():
    coll, shop, master = _customers_collection()
    if coll is None or shop is None:
        flash("Shop database not configured for this shop.", "error")
        return redirect(url_for("customers.customers_page"))

    tenant_oid = _oid(session.get(SESSION_TENANT_ID))
    if not tenant_oid:
        flash("Tenant session missing. Please login again.", "error")
        session.clear()
        return redirect(url_for("main.index"))

    company_name = (request.form.get("company_name") or "").strip()
    first_name = (request.form.get("first_name") or "").strip()
    last_name = (request.form.get("last_name") or "").strip()
    phone = (request.form.get("phone") or "").strip()
    email = (request.form.get("email") or "").strip().lower()
    address = (request.form.get("address") or "").strip()

    # Минимальная валидация: пусть будет обязательна компания ИЛИ имя+фамилия
    if not company_name and not (first_name and last_name):
        flash("Company name or First+Last name is required.", "error")
        return redirect(url_for("customers.customers_page"))

    now = utcnow()
    user_oid = _oid(session.get(SESSION_USER_ID))

    doc = {
        "company_name": company_name or None,
        "first_name": first_name or None,
        "last_name": last_name or None,
        "phone": phone or None,
        "email": email or None,
        "address": address or None,
        "default_labor_rate": "Standart",

        "is_active": True,

        "created_at": now,
        "updated_at": now,
        "created_by": user_oid,
        "updated_by": user_oid,
        "deactivated_at": None,
        "deactivated_by": None,

        # как и vendors — в SHOP DB, но храним ссылки
        "shop_id": shop["_id"],
        "tenant_id": tenant_oid,
    }

    coll.insert_one(doc)

    flash("Customer created successfully.", "success")
    return redirect(url_for("customers.customers_page"))


@customers_bp.post("/customers/<customer_id>/deactivate")
@login_required
@permission_required("customers.deactivate")
def customers_deactivate(customer_id):
    coll, shop, master = _customers_collection()
    if coll is None or shop is None:
        flash("Shop database not configured for this shop.", "error")
        return redirect(url_for("customers.customers_page"))

    cid = _oid(customer_id)
    if not cid:
        flash("Invalid customer id.", "error")
        return redirect(url_for("customers.customers_page"))

    existing = coll.find_one({"_id": cid})
    if not existing:
        flash("Customer not found.", "error")
        return redirect(url_for("customers.customers_page"))

    if existing.get("is_active") is False:
        flash("Customer is already deactivated.", "info")
        return redirect(url_for("customers.customers_page"))

    now = utcnow()
    user_oid = _oid(session.get(SESSION_USER_ID))

    coll.update_one(
        {"_id": cid},
        {"$set": {
            "is_active": False,
            "updated_at": now,
            "updated_by": user_oid,
            "deactivated_at": now,
            "deactivated_by": user_oid,
        }},
    )

    flash("Customer deactivated.", "success")
    return redirect(url_for("customers.customers_page"))
