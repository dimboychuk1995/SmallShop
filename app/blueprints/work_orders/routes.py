from __future__ import annotations

from datetime import datetime, timezone

from bson import ObjectId
from flask import request, session, redirect, url_for, flash

from app.blueprints.main.routes import _render_app_page
from app.blueprints.work_orders import work_orders_bp
from app.extensions import get_master_db, get_mongo_client
from app.utils.auth import login_required, SESSION_TENANT_ID, SESSION_USER_ID
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


def _get_shop_db():
    """
    Возвращает (shop_db, shop_doc).
    shop_db — это база активной шапы (shop database).
    """
    master = get_master_db()

    shop_id = _oid(session.get("shop_id"))
    if not shop_id:
        return None, None

    tenant_variants = _tenant_id_variants()
    if not tenant_variants:
        return None, None

    shop = master.shops.find_one({"_id": shop_id, "tenant_id": {"$in": tenant_variants}})
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


def _current_user_id():
    return _oid(session.get(SESSION_USER_ID))


def _parse_int(v):
    if v is None:
        return None
    s = str(v).strip()
    if not s:
        return None
    try:
        return int(s)
    except Exception:
        return None


def _get_customers(shop_db):
    # customers хранятся в shop DB (как на твоём скрине)
    # сортируем максимально дружелюбно
    return list(
        shop_db.customers.find({"is_active": True}).sort(
            [("company_name", 1), ("last_name", 1), ("first_name", 1)]
        )
    )


def _customer_display(c):
    company = (c.get("company_name") or "").strip()
    fn = (c.get("first_name") or "").strip()
    ln = (c.get("last_name") or "").strip()

    if company:
        return company
    name = (fn + " " + ln).strip()
    return name or "(no name)"


def _get_units(shop_db, customer_id):
    return list(
        shop_db.units.find({"customer_id": customer_id, "is_active": True}).sort([("created_at", -1)])
    )


def _unit_display(u):
    parts = []
    if u.get("unit_number"):
        parts.append(str(u.get("unit_number")))
    if u.get("year"):
        parts.append(str(u.get("year")))
    if u.get("make"):
        parts.append(str(u.get("make")))
    if u.get("model"):
        parts.append(str(u.get("model")))
    if u.get("vin"):
        parts.append(f"VIN {u.get('vin')}")
    return " • ".join([p for p in parts if p]) or "(unit)"


@work_orders_bp.get("/work_orders")
@login_required
@permission_required("work_orders.view")
def work_orders_page():
    # пока просто страница списка (будет позже)
    return _render_app_page("public/work_orders/work_orders.html", active_page="work_orders")


@work_orders_bp.get("/work_orders/details")
@login_required
@permission_required("work_orders.create")
def work_order_details_page():
    """
    Create-mode страница:
    - выбираем customer
    - выбираем unit или создаём unit
    - создаём draft work order
    """
    shop_db, shop = _get_shop_db()
    if shop_db is None:
        flash("Shop database not configured for this shop.", "error")
        return redirect(url_for("main.dashboard"))

    customer_id = _oid(request.args.get("customer_id"))
    unit_id = _oid(request.args.get("unit_id"))

    customers = _get_customers(shop_db)
    customers_ui = [{"id": str(c["_id"]), "label": _customer_display(c)} for c in customers]

    units_ui = []
    if customer_id:
        units = _get_units(shop_db, customer_id)
        units_ui = [{"id": str(u["_id"]), "label": _unit_display(u)} for u in units]

        # если unit_id не принадлежит выбранному customer — сбрасываем
        if unit_id and not any(x["id"] == str(unit_id) for x in units_ui):
            unit_id = None

    auto_open_unit_modal = bool(customer_id) and len(units_ui) == 0


    return _render_app_page(
        "public/work_orders/work_order_details.html",
        active_page="work_orders",
        customers=customers_ui,
        units=units_ui,
        selected_customer_id=str(customer_id) if customer_id else "",
        selected_unit_id=str(unit_id) if unit_id else "",
        auto_open_unit_modal=auto_open_unit_modal,
    )


@work_orders_bp.get("/work_orders/details/<work_order_id>")
@login_required
@permission_required("work_orders.view")
def work_order_details_view(work_order_id):
    """
    Пока просто заглушка, чтобы после create был редирект.
    Дальше тут будет полноценный edit-mode.
    """
    shop_db, shop = _get_shop_db()
    if shop_db is None:
        flash("Shop database not configured for this shop.", "error")
        return redirect(url_for("main.dashboard"))

    wo_oid = _oid(work_order_id)
    if not wo_oid:
        flash("Invalid work order id.", "error")
        return redirect(url_for("work_orders.work_orders_page"))

    wo = shop_db.work_orders.find_one({"_id": wo_oid})
    if not wo:
        flash("Work order not found.", "error")
        return redirect(url_for("work_orders.work_orders_page"))

    return _render_app_page(
        "public/work_orders/work_order_details_view.html",
        active_page="work_orders",
        work_order_id=str(wo_oid),
        work_order=wo,
    )


@work_orders_bp.post("/work_orders/units/create")
@login_required
@permission_required("work_orders.create")
def create_unit():
    """
    Создание unit для выбранного customer.
    Создаём в shop DB: units
    """
    shop_db, shop = _get_shop_db()
    if shop_db is None:
        flash("Shop database not configured for this shop.", "error")
        return redirect(url_for("main.dashboard"))

    customer_id = _oid(request.form.get("customer_id"))
    if not customer_id:
        flash("Customer is required to create a unit.", "error")
        return redirect(url_for("work_orders.work_order_details_page"))

    # проверяем что customer существует в shop DB
    customer = shop_db.customers.find_one({"_id": customer_id, "is_active": True})
    if not customer:
        flash("Customer not found.", "error")
        return redirect(url_for("work_orders.work_order_details_page"))

    user_id = _current_user_id()
    now = utcnow()

    doc = {
        "customer_id": customer_id,

        "vin": (request.form.get("vin") or "").strip() or None,
        "make": (request.form.get("make") or "").strip() or None,
        "model": (request.form.get("model") or "").strip() or None,
        "year": _parse_int(request.form.get("year")),
        "type": (request.form.get("type") or "").strip() or None,
        "mileage": _parse_int(request.form.get("mileage")),
        "unit_number": (request.form.get("unit_number") or "").strip() or None,

        "is_active": True,
        "created_at": now,
        "updated_at": now,
        "created_by": user_id,
        "updated_by": user_id,

        # рекомендую хранить для целостности (как у customers на скрине)
        "shop_id": shop["_id"],
        "tenant_id": shop.get("tenant_id"),
        "deactivated_at": None,
        "deactivated_by": None,
    }

    res = shop_db.units.insert_one(doc)
    new_unit_id = res.inserted_id

    flash("Unit created.", "success")
    return redirect(
        url_for(
            "work_orders.work_order_details_page",
            customer_id=str(customer_id),
            unit_id=str(new_unit_id),
        )
    )


@work_orders_bp.post("/work_orders/create")
@login_required
@permission_required("work_orders.create")
def create_work_order():
    shop_db, shop = _get_shop_db()
    if shop_db is None:
        flash("Shop database not configured for this shop.", "error")
        return redirect(url_for("main.dashboard"))

    customer_id = _oid(request.form.get("customer_id"))
    unit_id = _oid(request.form.get("unit_id"))

    if not customer_id:
        flash("Customer is required.", "error")
        return redirect(url_for("work_orders.work_order_details_page"))

    if not unit_id:
        flash("Unit is required (select existing or create new).", "error")
        return redirect(url_for("work_orders.work_order_details_page", customer_id=str(customer_id)))

    customer = shop_db.customers.find_one({"_id": customer_id, "is_active": True})
    if not customer:
        flash("Customer not found.", "error")
        return redirect(url_for("work_orders.work_order_details_page"))

    unit = shop_db.units.find_one({"_id": unit_id, "customer_id": customer_id, "is_active": True})
    if not unit:
        flash("Unit not found for this customer.", "error")
        return redirect(url_for("work_orders.work_order_details_page", customer_id=str(customer_id)))

    user_id = _current_user_id()
    now = utcnow()

    wo = {
        "customer_id": customer_id,
        "unit_id": unit_id,

        "status": "draft",
        "is_active": True,

        "created_at": now,
        "updated_at": now,
        "created_by": user_id,
        "updated_by": user_id,

        "shop_id": shop["_id"],
        "tenant_id": shop.get("tenant_id"),

        "notes": None,
        "deactivated_at": None,
        "deactivated_by": None,
    }

    res = shop_db.work_orders.insert_one(wo)
    wo_id = res.inserted_id  # ✅ fixed

    return redirect(url_for("work_orders.work_order_details_view", work_order_id=str(wo_id)))


