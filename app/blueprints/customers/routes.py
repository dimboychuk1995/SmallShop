from __future__ import annotations

from datetime import datetime, timezone

from bson import ObjectId
from flask import request, redirect, url_for, flash, session, jsonify

from app.blueprints.customers import customers_bp
from app.blueprints.main.routes import _render_app_page
from app.extensions import get_master_db, get_mongo_client
from app.utils.auth import (
    login_required,
    SESSION_TENANT_ID,
    SESSION_USER_ID,
)
from app.utils.pagination import get_pagination_params, paginate_find
from app.utils.permissions import permission_required


def utcnow():
    return datetime.now(timezone.utc)


def _round2(value):
    try:
        return round(float(value or 0) + 1e-12, 2)
    except Exception:
        return 0.0


def _fmt_dt_label(dt):
    if isinstance(dt, datetime):
        try:
            return dt.astimezone().strftime("%Y-%m-%d %H:%M")
        except Exception:
            return dt.strftime("%Y-%m-%d %H:%M")
    return "-"


def _customer_label(customer: dict) -> str:
    company = (customer.get("company_name") or "").strip()
    if company:
        return company
    first_name = (customer.get("first_name") or "").strip()
    last_name = (customer.get("last_name") or "").strip()
    full_name = f"{first_name} {last_name}".strip()
    return full_name or "-"


def _order_grand_total(order: dict) -> float:
    totals = order.get("totals") if isinstance(order.get("totals"), dict) else {}
    if totals.get("grand_total") is not None:
        return _round2(totals.get("grand_total"))
    return _round2(order.get("grand_total"))


def _build_paid_map(payments_coll, work_order_ids: list[ObjectId]) -> dict[ObjectId, float]:
    if not work_order_ids:
        return {}

    pipeline = [
        {
            "$match": {
                "work_order_id": {"$in": work_order_ids},
                "is_active": True,
            }
        },
        {
            "$group": {
                "_id": "$work_order_id",
                "paid_total": {"$sum": "$amount"},
            }
        },
    ]

    out = {}
    for row in payments_coll.aggregate(pipeline):
        out[row.get("_id")] = _round2(row.get("paid_total"))
    return out


def _attach_customers_current_balances(customers: list[dict], shop_db, shop_id: ObjectId):
    if not customers:
        return

    customer_ids = [c.get("_id") for c in customers if c.get("_id")]
    if not customer_ids:
        return

    work_orders = list(
        shop_db.work_orders.find(
            {
                "shop_id": shop_id,
                "customer_id": {"$in": customer_ids},
                "is_active": True,
            },
            {
                "_id": 1,
                "customer_id": 1,
                "totals": 1,
                "grand_total": 1,
            },
        )
    )

    work_order_ids = [wo.get("_id") for wo in work_orders if wo.get("_id")]
    paid_map = _build_paid_map(shop_db.work_order_payments, work_order_ids)

    balances_by_customer = {cid: 0.0 for cid in customer_ids}
    for wo in work_orders:
        cid = wo.get("customer_id")
        wo_id = wo.get("_id")
        if not cid or not wo_id:
            continue

        grand_total = _order_grand_total(wo)
        paid_amount = _round2(paid_map.get(wo_id, 0.0))
        remaining = _round2(grand_total - paid_amount)
        if remaining > 0:
            balances_by_customer[cid] = _round2(balances_by_customer.get(cid, 0.0) + remaining)

    for customer in customers:
        customer["current_balance"] = _round2(balances_by_customer.get(customer.get("_id"), 0.0))


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

    page, per_page = get_pagination_params(request.args, default_per_page=20, max_per_page=100)
    customers, pagination = paginate_find(
        coll,
        {},
        [("is_active", -1), ("company_name", 1), ("last_name", 1), ("first_name", 1), ("created_at", -1)],
        page,
        per_page,
    )

    _attach_customers_current_balances(customers, coll.database, shop["_id"])

    return _render_app_page(
        "public/customers.html",
        active_page="customers",
        customers=customers,
        pagination=pagination,
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


@customers_bp.get("/customers/api/<customer_id>")
@login_required
@permission_required("customers.view")
def customers_api_get(customer_id):
    coll, shop, master = _customers_collection()
    if coll is None or shop is None:
        return jsonify({"ok": False, "error": "Shop not configured"}), 400

    cid = _oid(customer_id)
    if not cid:
        return jsonify({"ok": False, "error": "Invalid customer id"}), 400

    customer = coll.find_one({"_id": cid, "shop_id": shop["_id"]})
    if not customer:
        return jsonify({"ok": False, "error": "Customer not found"}), 404

    return jsonify(
        {
            "ok": True,
            "item": {
                "_id": str(customer.get("_id")),
                "company_name": customer.get("company_name") or "",
                "first_name": customer.get("first_name") or "",
                "last_name": customer.get("last_name") or "",
                "phone": customer.get("phone") or "",
                "email": customer.get("email") or "",
                "address": customer.get("address") or "",
                "is_active": customer.get("is_active", True),
            },
        }
    )


@customers_bp.post("/customers/api/<customer_id>/update")
@login_required
@permission_required("customers.edit")
def customers_api_update(customer_id):
    coll, shop, master = _customers_collection()
    if coll is None or shop is None:
        return jsonify({"ok": False, "error": "Shop not configured"}), 400

    cid = _oid(customer_id)
    if not cid:
        return jsonify({"ok": False, "error": "Invalid customer id"}), 400

    customer = coll.find_one({"_id": cid, "shop_id": shop["_id"]})
    if not customer:
        return jsonify({"ok": False, "error": "Customer not found"}), 404

    data = request.get_json(silent=True) or {}
    company_name = (data.get("company_name") or "").strip()
    first_name = (data.get("first_name") or "").strip()
    last_name = (data.get("last_name") or "").strip()
    phone = (data.get("phone") or "").strip()
    email = (data.get("email") or "").strip().lower()
    address = (data.get("address") or "").strip()

    if not company_name and not (first_name and last_name):
        return jsonify({"ok": False, "error": "Company name or First+Last name is required."}), 400

    now = utcnow()
    user_oid = _oid(session.get(SESSION_USER_ID))

    coll.update_one(
        {"_id": cid},
        {
            "$set": {
                "company_name": company_name or None,
                "first_name": first_name or None,
                "last_name": last_name or None,
                "phone": phone or None,
                "email": email or None,
                "address": address or None,
                "updated_at": now,
                "updated_by": user_oid,
            }
        },
    )

    return jsonify({"ok": True, "message": "Customer updated successfully"})


@customers_bp.post("/customers/api/<customer_id>/deactivate")
@login_required
@permission_required("customers.deactivate")
def customers_api_deactivate(customer_id):
    coll, shop, master = _customers_collection()
    if coll is None or shop is None:
        return jsonify({"ok": False, "error": "Shop not configured"}), 400

    cid = _oid(customer_id)
    if not cid:
        return jsonify({"ok": False, "error": "Invalid customer id"}), 400

    customer = coll.find_one({"_id": cid, "shop_id": shop["_id"]})
    if not customer:
        return jsonify({"ok": False, "error": "Customer not found"}), 404

    if customer.get("is_active") is False:
        return jsonify({"ok": False, "error": "Customer is already deactivated"}), 400

    now = utcnow()
    user_oid = _oid(session.get(SESSION_USER_ID))

    coll.update_one(
        {"_id": cid},
        {
            "$set": {
                "is_active": False,
                "updated_at": now,
                "updated_by": user_oid,
                "deactivated_at": now,
                "deactivated_by": user_oid,
            }
        },
    )

    return jsonify({"ok": True, "message": "Customer deactivated"})


@customers_bp.get("/customers/api/<customer_id>/work-orders")
@login_required
@permission_required("customers.view")
def customers_api_work_orders(customer_id):
    coll, shop, master = _customers_collection()
    if coll is None or shop is None:
        return jsonify({"ok": False, "error": "Shop not configured"}), 400

    cid = _oid(customer_id)
    if not cid:
        return jsonify({"ok": False, "error": "Invalid customer id"}), 400

    customer = coll.find_one({"_id": cid, "shop_id": shop["_id"]})
    if not customer:
        return jsonify({"ok": False, "error": "Customer not found"}), 404

    shop_db = coll.database
    work_orders_coll = shop_db.work_orders
    payments_coll = shop_db.work_order_payments

    page, per_page = get_pagination_params(request.args, default_per_page=10, max_per_page=100)
    wo_query = {
        "shop_id": shop["_id"],
        "customer_id": cid,
        "is_active": True,
    }

    work_orders, pagination = paginate_find(
        work_orders_coll,
        wo_query,
        [("created_at", -1)],
        page,
        per_page,
        projection={
            "wo_number": 1,
            "status": 1,
            "created_at": 1,
            "totals": 1,
            "grand_total": 1,
        },
    )

    page_wo_ids = [wo.get("_id") for wo in work_orders if wo.get("_id")]
    paid_map = _build_paid_map(payments_coll, page_wo_ids)

    items = []
    for wo in work_orders:
        wo_id = wo.get("_id")
        grand_total = _order_grand_total(wo)
        paid_amount = _round2(paid_map.get(wo_id, 0.0))
        remaining = _round2(grand_total - paid_amount)
        if remaining < 0:
            remaining = 0.0

        items.append(
            {
                "id": str(wo_id),
                "wo_number": wo.get("wo_number") or "-",
                "status": (wo.get("status") or "open").strip().lower(),
                "created_at": _fmt_dt_label(wo.get("created_at")),
                "grand_total": grand_total,
                "paid_amount": paid_amount,
                "remaining_balance": remaining,
            }
        )

    # Current customer balance over all active work orders.
    all_orders = list(
        work_orders_coll.find(
            wo_query,
            {"_id": 1, "totals": 1, "grand_total": 1},
        )
    )
    all_order_ids = [wo.get("_id") for wo in all_orders if wo.get("_id")]
    all_paid_map = _build_paid_map(payments_coll, all_order_ids)

    current_balance = 0.0
    for wo in all_orders:
        wo_id = wo.get("_id")
        grand_total = _order_grand_total(wo)
        paid_amount = _round2(all_paid_map.get(wo_id, 0.0))
        remaining = _round2(grand_total - paid_amount)
        if remaining > 0:
            current_balance = _round2(current_balance + remaining)

    return jsonify(
        {
            "ok": True,
            "customer": {
                "id": str(customer.get("_id")),
                "name": _customer_label(customer),
                "current_balance": current_balance,
            },
            "items": items,
            "pagination": pagination,
        }
    )
