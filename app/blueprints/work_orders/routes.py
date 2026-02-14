from __future__ import annotations

from datetime import datetime, timezone
from bson import ObjectId
from flask import request, session, redirect, url_for, flash, jsonify

from app.blueprints.work_orders import work_orders_bp
from app.blueprints.main.routes import _render_app_page
from app.extensions import get_master_db, get_mongo_client
from app.utils.auth import login_required, SESSION_TENANT_ID, SESSION_USER_ID
from app.utils.permissions import permission_required


def utcnow():
    return datetime.now(timezone.utc)


def oid(v):
    if not v:
        return None
    try:
        return ObjectId(str(v))
    except Exception:
        return None


def i32(v):
    if v is None:
        return None
    s = str(v).strip()
    if not s:
        return None
    try:
        return int(s)
    except Exception:
        return None


def current_user_id():
    return oid(session.get(SESSION_USER_ID))


def tenant_id_variants():
    raw = session.get(SESSION_TENANT_ID)
    out = set()
    if raw is None:
        return []
    out.add(raw)
    out.add(str(raw))
    o = oid(raw)
    if o:
        out.add(o)
    return list(out)


def get_shop_db():
    master = get_master_db()

    shop_id = oid(session.get("shop_id"))
    if not shop_id:
        return None, None

    tenant_variants = tenant_id_variants()
    if not tenant_variants:
        return None, None

    shop = master.shops.find_one({"_id": shop_id, "tenant_id": {"$in": tenant_variants}})
    if not shop:
        return None, None

    db_name = shop.get("db_name")
    if not db_name:
        return None, shop

    client = get_mongo_client()
    return client[str(db_name)], shop


def customer_label(c: dict) -> str:
    company = (c.get("company_name") or "").strip()
    if company:
        return company
    fn = (c.get("first_name") or "").strip()
    ln = (c.get("last_name") or "").strip()
    name = (fn + " " + ln).strip()
    return name or "(no name)"


def unit_label(u: dict) -> str:
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


def get_customers(shop_db):
    rows = list(
        shop_db.customers.find({"is_active": True}).sort(
            [("company_name", 1), ("last_name", 1), ("first_name", 1)]
        )
    )
    return [{"id": str(x["_id"]), "label": customer_label(x)} for x in rows]


def get_units(shop_db, customer_id: ObjectId):
    rows = list(
        shop_db.units.find({"customer_id": customer_id, "is_active": True}).sort([("created_at", -1)])
    )
    return [{"id": str(x["_id"]), "label": unit_label(x)} for x in rows]


def get_labor_rates(shop_db, shop_id: ObjectId):
    rows = list(
        shop_db.labor_rates.find({"shop_id": shop_id, "is_active": True}).sort([("name", 1)])
    )
    return [
        {
            "code": r.get("code") or "",
            "name": r.get("name") or (r.get("code") or ""),
            "hourly_rate": float(r.get("hourly_rate") or 0),
        }
        for r in rows
    ]


def get_pricing_rules_json(shop_db, shop_id: ObjectId):
    doc = shop_db.parts_pricing_rules.find_one({"shop_id": shop_id, "is_active": True})
    if not doc:
        return None

    mode = (doc.get("mode") or "margin").strip().lower()  # margin | markup
    rules = []
    for r in (doc.get("rules") or []):
        frm = r.get("from")
        to = r.get("to")
        vp = r.get("value_percent")

        try:
            frm_f = float(frm)
        except Exception:
            continue

        if to is None:
            to_f = None
        else:
            try:
                to_f = float(to)
            except Exception:
                to_f = None

        try:
            vp_f = float(vp)
        except Exception:
            continue

        rules.append({"from": frm_f, "to": to_f, "value_percent": vp_f})

    return {"mode": mode, "rules": rules}


def render_details(shop_db, shop, customer_id, unit_id, form_state=None):
    customers = get_customers(shop_db)

    units = []
    if customer_id:
        units = get_units(shop_db, customer_id)
        if unit_id and not any(u["id"] == str(unit_id) for u in units):
            unit_id = None

    ctx = {
        "active_page": "work_orders",
        "customers": customers,
        "units": units,
        "selected_customer_id": str(customer_id) if customer_id else "",
        "selected_unit_id": str(unit_id) if unit_id else "",
        "labor_rates": get_labor_rates(shop_db, shop["_id"]),
        "parts_pricing_rules": get_pricing_rules_json(shop_db, shop["_id"]),
        "labor_description": (form_state or {}).get("labor_description") or "",
        "labor_hours": (form_state or {}).get("labor_hours") or "",
        "labor_rate_code": (form_state or {}).get("labor_rate_code") or "",
    }

    return _render_app_page("public/work_orders/work_order_details.html", **ctx)


@work_orders_bp.get("/work_orders")
@login_required
@permission_required("work_orders.view")
def work_orders_page():
    return _render_app_page("public/work_orders/work_orders.html", active_page="work_orders")


@work_orders_bp.get("/work_orders/details")
@login_required
@permission_required("work_orders.create")
def work_order_details_page():
    shop_db, shop = get_shop_db()
    if shop_db is None:
        flash("Shop database not configured.", "error")
        return redirect(url_for("main.dashboard"))

    customer_id = oid(request.args.get("customer_id"))
    unit_id = oid(request.args.get("unit_id"))

    return render_details(shop_db, shop, customer_id, unit_id)


@work_orders_bp.post("/work_orders/units/create")
@login_required
@permission_required("work_orders.create")
def create_unit():
    shop_db, shop = get_shop_db()
    if shop_db is None:
        flash("Shop database not configured.", "error")
        return redirect(url_for("main.dashboard"))

    customer_id = oid(request.form.get("customer_id"))
    if not customer_id:
        flash("Customer is required.", "error")
        return redirect(url_for("work_orders.work_order_details_page"))

    customer = shop_db.customers.find_one({"_id": customer_id, "is_active": True})
    if not customer:
        flash("Customer not found.", "error")
        return redirect(url_for("work_orders.work_order_details_page"))

    now = utcnow()
    user_id = current_user_id()

    doc = {
        "customer_id": customer_id,
        "vin": (request.form.get("vin") or "").strip() or None,
        "unit_number": (request.form.get("unit_number") or "").strip() or None,
        "make": (request.form.get("make") or "").strip() or None,
        "model": (request.form.get("model") or "").strip() or None,
        "year": i32(request.form.get("year")),
        "type": (request.form.get("type") or "").strip() or None,
        "mileage": i32(request.form.get("mileage")),
        "shop_id": shop["_id"],
        "tenant_id": shop.get("tenant_id"),
        "is_active": True,
        "created_at": now,
        "updated_at": now,
        "created_by": user_id,
        "updated_by": user_id,
    }

    res = shop_db.units.insert_one(doc)
    unit_id = res.inserted_id

    flash("Unit created.", "success")
    return redirect(url_for("work_orders.work_order_details_page", customer_id=str(customer_id), unit_id=str(unit_id)))


@work_orders_bp.post("/work_orders/preview")
@login_required
@permission_required("work_orders.create")
def preview_work_order():
    shop_db, shop = get_shop_db()
    if shop_db is None:
        flash("Shop database not configured.", "error")
        return redirect(url_for("main.dashboard"))

    customer_id = oid(request.form.get("customer_id"))
    unit_id = oid(request.form.get("unit_id"))

    form_state = {
        "labor_description": (request.form.get("labor_description") or "").strip(),
        "labor_hours": (request.form.get("labor_hours") or "").strip(),
        "labor_rate_code": (request.form.get("labor_rate_code") or "").strip(),
    }

    return render_details(shop_db, shop, customer_id, unit_id, form_state=form_state)


# -----------------------------
# FAST PARTS SEARCH API
# -----------------------------

@work_orders_bp.get("/work_orders/api/parts/search")
@login_required
@permission_required("work_orders.create")
def api_parts_search():
    """
    Very fast search for parts in active shop DB.
    Query params:
      q: search string (min 3)
      limit: default 20 (max 50)
    Returns:
      {"items":[{id, part_number, description, reference, average_cost, in_stock}]}
    """
    import re

    shop_db, shop = get_shop_db()
    if shop_db is None:
        return jsonify({"items": [], "error": "shop_db_missing"}), 200

    q = (request.args.get("q") or "").strip()
    if len(q) < 3:
        return jsonify({"items": []}), 200

    try:
        limit = int(request.args.get("limit") or 20)
    except Exception:
        limit = 20
    limit = max(1, min(limit, 50))

    # Escape for regex
    q_escaped = re.escape(q)
    starts = f"^{q_escaped}"
    contains = q_escaped  # regex "contains"

    parts_col = shop_db.parts

    query = {
        "shop_id": shop["_id"],
        "is_active": True,
        "$or": [
            # part_number: prefix first (fast + nice UX)
            {"part_number": {"$regex": starts, "$options": "i"}},
            # part_number: contains (fix: "225" matches "10-225")
            {"part_number": {"$regex": contains, "$options": "i"}},
            # other fields already contain
            {"description": {"$regex": contains, "$options": "i"}},
            {"reference": {"$regex": contains, "$options": "i"}},
        ],
    }

    projection = {
        "part_number": 1,
        "description": 1,
        "reference": 1,
        "average_cost": 1,
        "in_stock": 1,
    }

    cursor = parts_col.find(query, projection).sort([("part_number", 1)]).limit(limit)

    items = []
    for p in cursor:
        items.append({
            "id": str(p.get("_id")),
            "part_number": p.get("part_number") or "",
            "description": p.get("description") or "",
            "reference": p.get("reference") or "",
            "average_cost": float(p.get("average_cost") or 0),
            "in_stock": int(p.get("in_stock") or 0),
        })

    return jsonify({"items": items}), 200
