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


def f64(v):
    if v is None:
        return None
    try:
        return float(v)
    except Exception:
        return None


def round2(v):
    n = f64(v)
    if n is None:
        return 0.0
    return round(n + 1e-12, 2)


def normalize_totals_payload(raw):
    src = raw if isinstance(raw, dict) else {}

    blocks = []
    for b in (src.get("labors") or []):
        if not isinstance(b, dict):
            continue
        labor_total = round2(b.get("labor_total"))
        parts_total = round2(b.get("parts_total"))
        core_total = round2(b.get("core_total"))
        misc_total = round2(b.get("misc_total"))
        shop_supply_total = round2(b.get("shop_supply_total"))
        labor_full_total = round2(b.get("labor_full_total"))
        blocks.append(
            {
                "labor_total": labor_total,
                "parts_total": parts_total,
                "core_total": core_total,
                "misc_total": misc_total,
                "shop_supply_total": shop_supply_total,
                "labor_full_total": labor_full_total,
            }
        )

    labor_total = round2(src.get("labor_total"))
    parts_total = round2(src.get("parts_total"))
    core_total = round2(src.get("core_total"))
    misc_total = round2(src.get("misc_total"))
    shop_supply_total = round2(src.get("shop_supply_total"))
    grand_total = round2(src.get("grand_total"))

    return {
        "labor_total": labor_total,
        "parts_total": parts_total,
        "core_total": core_total,
        "misc_total": misc_total,
        "shop_supply_total": shop_supply_total,
        "grand_total": grand_total,
        "labors": blocks,
    }


def normalize_saved_labors(raw):
    if not isinstance(raw, list):
        return []

    out = []
    for block in raw:
        if not isinstance(block, dict):
            continue

        labor_src = block.get("labor") if isinstance(block.get("labor"), dict) else {}

        labor_description = str(
            labor_src.get("description")
            if labor_src.get("description") is not None
            else block.get("labor_description")
            or ""
        ).strip()

        labor_hours = str(
            labor_src.get("hours")
            if labor_src.get("hours") is not None
            else block.get("labor_hours")
            or ""
        ).strip()

        labor_rate_code = str(
            labor_src.get("rate_code")
            if labor_src.get("rate_code") is not None
            else block.get("labor_rate_code")
            or ""
        ).strip()

        parts_out = []
        for p in (block.get("parts") or []):
            if not isinstance(p, dict):
                continue

            part_number = str(p.get("part_number") or "").strip()
            description = str(p.get("description") or "").strip()
            qty = str(p.get("qty") if p.get("qty") is not None else "").strip()
            cost = str(p.get("cost") if p.get("cost") is not None else "").strip()
            price = str(p.get("price") if p.get("price") is not None else "").strip()
            core_charge = str(
                p.get("core_charge")
                if p.get("core_charge") is not None
                else (p.get("core_cost") if p.get("core_cost") is not None else "")
            ).strip()
            misc_charge = str(p.get("misc_charge") if p.get("misc_charge") is not None else "").strip()
            misc_charge_description = str(
                p.get("misc_charge_description") if p.get("misc_charge_description") is not None else ""
            ).strip()

            if not (part_number or description or qty or cost or price or core_charge or misc_charge or misc_charge_description):
                continue

            parts_out.append(
                {
                    "part_number": part_number,
                    "description": description,
                    "qty": qty,
                    "cost": cost,
                    "price": price,
                    "core_charge": core_charge,
                    "misc_charge": misc_charge,
                    "misc_charge_description": misc_charge_description,
                }
            )

        out.append(
            {
                "labor": {
                    "description": labor_description,
                    "hours": labor_hours,
                    "rate_code": labor_rate_code,
                },
                "parts": parts_out,
            }
        )

    return out


def format_dt_label(dt):
    if isinstance(dt, datetime):
        try:
            return dt.astimezone().strftime("%Y-%m-%d %H:%M")
        except Exception:
            return dt.strftime("%Y-%m-%d %H:%M")
    return "-"


def get_work_orders_list(shop_db, shop_id: ObjectId):
    rows = list(
        shop_db.work_orders.find({"shop_id": shop_id, "is_active": True}).sort([("created_at", -1)]).limit(500)
    )

    customer_ids = [x.get("customer_id") for x in rows if x.get("customer_id")]
    unit_ids = [x.get("unit_id") for x in rows if x.get("unit_id")]

    customers_map = {}
    if customer_ids:
        for c in shop_db.customers.find({"_id": {"$in": customer_ids}}):
            customers_map[c.get("_id")] = customer_label(c)

    units_map = {}
    if unit_ids:
        for u in shop_db.units.find({"_id": {"$in": unit_ids}}):
            units_map[u.get("_id")] = unit_label(u)

    items = []
    for x in rows:
        totals = x.get("totals") if isinstance(x.get("totals"), dict) else {}

        labor_total = round2(x.get("labor_total") if x.get("labor_total") is not None else totals.get("labor_total"))
        parts_total = round2(x.get("parts_total") if x.get("parts_total") is not None else totals.get("parts_total"))
        grand_total = round2(x.get("grand_total") if x.get("grand_total") is not None else totals.get("grand_total"))

        status = (x.get("status") or "open").strip().lower()

        items.append(
            {
                "id": str(x.get("_id")),
                "customer": customers_map.get(x.get("customer_id")) or "-",
                "date": format_dt_label(x.get("created_at")),
                "unit": units_map.get(x.get("unit_id")) or "-",
                "labor_total": labor_total,
                "parts_total": parts_total,
                "grand_total": grand_total,
                "is_paid": status == "paid",
            }
        )

    return items


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
    return [
        {
            "id": str(x["_id"]),
            "label": customer_label(x),
            "default_labor_rate": (x.get("default_labor_rate") or "").strip(),
        }
        for x in rows
    ]


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


def get_shop_supply_percentage(shop_db, shop_id: ObjectId) -> float:
    col = shop_db.shop_supply_amount_rules
    doc = col.find_one({"shop_id": shop_id})
    if not doc:
        now = utcnow()
        col.update_one(
            {"shop_id": shop_id},
            {
                "$setOnInsert": {
                    "shop_id": shop_id,
                    "shop_supply_procentage": 5,
                    "is_active": True,
                    "created_at": now,
                },
                "$set": {
                    "updated_at": now,
                },
            },
            upsert=True,
        )
        doc = col.find_one({"shop_id": shop_id}) or {}
    try:
        raw = doc.get("shop_supply_procentage")
        return float(raw) if raw is not None else 0.0
    except Exception:
        return 0.0


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
        "shop_supply_procentage": get_shop_supply_percentage(shop_db, shop["_id"]),

        # старые поля (оставляем как у тебя было)
        "labor_description": (form_state or {}).get("labor_description") or "",
        "labor_hours": (form_state or {}).get("labor_hours") or "",
        "labor_rate_code": (form_state or {}).get("labor_rate_code") or "",

        # NEW: флаг, чтобы после create UI стал неактивным
        "work_order_created": bool((form_state or {}).get("work_order_created")),
        "created_work_order_id": (form_state or {}).get("created_work_order_id") or "",

        "draft_labors": (form_state or {}).get("draft_labors") or (form_state or {}).get("draft_blocks") or [],
        "draft_totals": normalize_totals_payload((form_state or {}).get("draft_totals") or {}),
        "work_order_status": (form_state or {}).get("work_order_status") or "open",
    }

    return _render_app_page("public/work_orders/work_order_details.html", **ctx)


@work_orders_bp.get("/work_orders")
@login_required
@permission_required("work_orders.view")
def work_orders_page():
    shop_db, shop = get_shop_db()
    if shop_db is None:
        flash("Shop database not configured.", "error")
        return redirect(url_for("main.dashboard"))

    work_orders = get_work_orders_list(shop_db, shop["_id"])
    return _render_app_page(
        "public/work_orders/work_orders.html",
        active_page="work_orders",
        work_orders=work_orders,
    )


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

    work_order_id = oid(request.args.get("work_order_id"))
    if work_order_id:
        wo = shop_db.work_orders.find_one({"_id": work_order_id, "shop_id": shop["_id"], "is_active": True})
        if not wo:
            flash("Work order not found.", "error")
            return redirect(url_for("work_orders.work_orders_page"))

        customer_id = wo.get("customer_id")
        unit_id = wo.get("unit_id")
        work_order_status = (wo.get("status") or "open").strip().lower()
        if work_order_status not in ("open", "paid"):
            work_order_status = "open"

        return render_details(
            shop_db,
            shop,
            customer_id,
            unit_id,
            form_state={
                "work_order_created": True,
                "created_work_order_id": str(wo.get("_id")),
                "draft_labors": normalize_saved_labors(wo.get("labors") or wo.get("blocks") or []),
                "draft_totals": wo.get("totals")
                or {
                    "labor_total": wo.get("labor_total") or 0,
                    "parts_total": wo.get("parts_total") or 0,
                    "grand_total": wo.get("grand_total") or 0,
                    "labors": [],
                },
                "work_order_status": work_order_status,
            },
        )

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

    action = (request.form.get("action") or "recalc").strip().lower()

    customer_id = oid(request.form.get("customer_id"))
    unit_id = oid(request.form.get("unit_id"))

    if not customer_id:
        flash("Customer is required.", "error")
        return redirect(url_for("work_orders.work_order_details_page"))

    if not unit_id:
        flash("Unit is required.", "error")
        return redirect(url_for("work_orders.work_order_details_page", customer_id=str(customer_id)))

    # ---- parse labors ----
    # inputs come like:
    # labors[0][labor_description], labors[0][labor_hours], labors[0][labor_rate_code]
    # labors[0][parts][0][part_number] ... etc
    import re
    import json

    labors_map: dict[int, dict] = {}

    # labor
    labor_re = re.compile(r"^(?:labors|blocks)\[(\d+)\]\[(labor_description|labor_hours|labor_rate_code)\]$")
    # parts
    parts_re = re.compile(
        r"^(?:labors|blocks)\[(\d+)\]\[parts\]\[(\d+)\]\[(part_number|description|qty|cost|price|core_charge|misc_charge|misc_charge_description)\]$"
    )

    for key, val in request.form.items():
        m = labor_re.match(key)
        if m:
            bidx = int(m.group(1))
            field = m.group(2)
            b = labors_map.setdefault(bidx, {"labor": {}, "parts": []})

            if field == "labor_description":
                b["labor"]["description"] = (val or "").strip()
            elif field == "labor_hours":
                b["labor"]["hours"] = (val or "").strip()
            elif field == "labor_rate_code":
                b["labor"]["rate_code"] = (val or "").strip()
            continue

        m = parts_re.match(key)
        if m:
            bidx = int(m.group(1))
            ridx = int(m.group(2))
            field = m.group(3)

            b = labors_map.setdefault(bidx, {"labor": {}, "parts": []})
            while len(b["parts"]) <= ridx:
                b["parts"].append({})

            if field in ("part_number", "description"):
                b["parts"][ridx][field] = (val or "").strip()
            elif field == "qty":
                b["parts"][ridx]["qty"] = (val or "").strip()
            elif field == "cost":
                b["parts"][ridx]["cost"] = (val or "").strip()
            elif field == "price":
                b["parts"][ridx]["price"] = (val or "").strip()
            elif field == "core_charge":
                b["parts"][ridx]["core_charge"] = (val or "").strip()
            elif field == "misc_charge":
                b["parts"][ridx]["misc_charge"] = (val or "").strip()
            elif field == "misc_charge_description":
                b["parts"][ridx]["misc_charge_description"] = (val or "").strip()
            continue

    # normalize labors list in order
    labors = []
    for bidx in sorted(labors_map.keys()):
        b = labors_map[bidx]

        # drop empty trailing part rows
        parts_clean = []
        for p in (b.get("parts") or []):
            pn = (p.get("part_number") or "").strip()
            ds = (p.get("description") or "").strip()
            qty = (p.get("qty") or "").strip()
            cost = (p.get("cost") or "").strip()
            price = (p.get("price") or "").strip()
            core_charge = (p.get("core_charge") or p.get("core_cost") or "").strip()
            misc_charge = (p.get("misc_charge") or "").strip()
            misc_charge_description = (p.get("misc_charge_description") or "").strip()
            if not (pn or ds or qty or cost or price or core_charge or misc_charge or misc_charge_description):
                continue
            parts_clean.append({
                "part_number": pn,
                "description": ds,
                "qty": qty,
                "cost": cost,
                "price": price,
                "core_charge": core_charge,
                "misc_charge": misc_charge,
                "misc_charge_description": misc_charge_description,
            })

        labor = b.get("labor") or {}
        labors.append({
            "labor": {
                "description": (labor.get("description") or "").strip(),
                "hours": (labor.get("hours") or "").strip(),
                "rate_code": (labor.get("rate_code") or "").strip(),
            },
            "parts": parts_clean,
        })

    # ✅ totals from front (we just store)
    totals = {}
    totals_raw = (request.form.get("totals_json") or "").strip()
    if totals_raw:
        try:
            totals = json.loads(totals_raw)
            if not isinstance(totals, dict):
                totals = {}
        except Exception:
            totals = {}

    totals = normalize_totals_payload(totals)

    now = utcnow()
    user_id = current_user_id()

    if action == "create":
        doc = {
            "shop_id": shop["_id"],
            "tenant_id": shop.get("tenant_id"),
            "customer_id": customer_id,
            "unit_id": unit_id,
            "status": "open",
            "labors": labors,

            # ✅ store totals from UI
            "totals": totals,
            "labor_total": totals.get("labor_total", 0.0),
            "parts_total": totals.get("parts_total", 0.0),
            "grand_total": totals.get("grand_total", 0.0),

            "is_active": True,
            "created_at": now,
            "updated_at": now,
            "created_by": user_id,
            "updated_by": user_id,
        }

        res = shop_db.work_orders.insert_one(doc)
        flash("Work order created.", "success")

        return render_details(
            shop_db,
            shop,
            customer_id,
            unit_id,
            form_state={
                "work_order_created": True,
                "created_work_order_id": str(res.inserted_id),
                "draft_labors": labors,
                "draft_totals": totals,
                "work_order_status": "open",
            },
        )

    # recalc/preview: just re-render (for now)
    return render_details(shop_db, shop, customer_id, unit_id)


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
        "core_has_charge": 1,
        "core_cost": 1,
        "misc_has_charge": 1,
        "misc_charges": 1,
    }

    cursor = parts_col.find(query, projection).sort([("part_number", 1)]).limit(limit)

    items = []
    for p in cursor:
        misc_items = []
        for m in (p.get("misc_charges") or []):
            if not isinstance(m, dict):
                continue
            misc_items.append({
                "description": str(m.get("description") or "").strip(),
                "price": float(m.get("price") or 0),
            })

        items.append({
            "id": str(p.get("_id")),
            "part_number": p.get("part_number") or "",
            "description": p.get("description") or "",
            "reference": p.get("reference") or "",
            "average_cost": float(p.get("average_cost") or 0),
            "in_stock": int(p.get("in_stock") or 0),
            "core_has_charge": bool(p.get("core_has_charge")),
            "core_cost": float(p.get("core_cost") or 0),
            "misc_has_charge": bool(p.get("misc_has_charge")),
            "misc_charges": misc_items,
        })

    return jsonify({"items": items}), 200


@work_orders_bp.get("/work_orders/api/units")
@login_required
@permission_required("work_orders.create")
def api_units_for_customer():
    shop_db, shop = get_shop_db()
    if shop_db is None:
        return jsonify({"items": [], "error": "shop_db_missing"}), 200

    customer_id = oid(request.args.get("customer_id"))
    if not customer_id:
        return jsonify({"items": []}), 200

    rows = list(
        shop_db.units.find({"customer_id": customer_id, "is_active": True})
        .sort([("created_at", -1)])
        .limit(500)
    )

    items = [{"id": str(u["_id"]), "label": unit_label(u)} for u in rows]
    return jsonify({"items": items}), 200


@work_orders_bp.get("/work_orders/api/unit")
@login_required
@permission_required("work_orders.create")
def api_unit_details():
    shop_db, shop = get_shop_db()
    if shop_db is None:
        return jsonify({"ok": False, "item": None, "error": "shop_db_missing"}), 200

    unit_id = oid(request.args.get("id"))
    if not unit_id:
        return jsonify({"ok": False, "item": None}), 200

    u = shop_db.units.find_one({"_id": unit_id, "is_active": True})
    if not u:
        return jsonify({"ok": False, "item": None}), 200

    item = {
        "id": str(u.get("_id")),
        "customer_id": str(u.get("customer_id")) if u.get("customer_id") else "",
        "vin": u.get("vin") or "",
        "unit_number": u.get("unit_number") or "",
        "make": u.get("make") or "",
        "model": u.get("model") or "",
        "year": u.get("year") or "",
        "type": u.get("type") or "",
        "mileage": u.get("mileage") or "",
    }
    return jsonify({"ok": True, "item": item}), 200


@work_orders_bp.post("/work_orders/api/work_orders/<work_order_id>/update")
@login_required
@permission_required("work_orders.create")
def api_work_order_update(work_order_id):
    shop_db, shop = get_shop_db()
    if shop_db is None:
        return jsonify({"ok": False, "error": "shop_db_missing"}), 200

    wo_id = oid(work_order_id)
    if not wo_id:
        return jsonify({"ok": False, "error": "invalid_work_order_id"}), 200

    wo = shop_db.work_orders.find_one({"_id": wo_id, "shop_id": shop["_id"], "is_active": True})
    if not wo:
        return jsonify({"ok": False, "error": "work_order_not_found"}), 200

    data = request.get_json(silent=True) or {}
    labors = data.get("labors", data.get("blocks"))
    totals = normalize_totals_payload(data.get("totals") or {})

    if not isinstance(labors, list):
        return jsonify({"ok": False, "error": "labors_required"}), 200

    # (опционально) можно запретить редактирование, если paid
    if (wo.get("status") or "open") == "paid":
        return jsonify({"ok": False, "error": "paid_cannot_edit"}), 200

    now = utcnow()
    user_id = current_user_id()

    shop_db.work_orders.update_one(
        {"_id": wo_id},
        {
            "$set": {
                "labors": labors,
                "totals": totals,  # ✅ сохраняем totals от фронта
                "labor_total": totals.get("labor_total", 0.0),
                "parts_total": totals.get("parts_total", 0.0),
                "grand_total": totals.get("grand_total", 0.0),
                "updated_at": now,
                "updated_by": user_id,
            },
            "$unset": {
                "blocks": "",
            },
        }
    )

    return jsonify({"ok": True}), 200



@work_orders_bp.post("/work_orders/api/work_orders/<work_order_id>/payment")
@login_required
@permission_required("work_orders.create")
def api_work_order_payment(work_order_id):
    """
    Record a payment for a work order.
    Request body: {amount, payment_method, notes}
    Saves to work_order_payments collection and updates work_order status if fully paid.
    """
    shop_db, shop = get_shop_db()
    if shop_db is None:
        return jsonify({"ok": False, "error": "shop_db_missing"}), 200

    wo_id = oid(work_order_id)
    if not wo_id:
        return jsonify({"ok": False, "error": "invalid_work_order_id"}), 200

    wo = shop_db.work_orders.find_one({"_id": wo_id, "shop_id": shop["_id"], "is_active": True})
    if not wo:
        return jsonify({"ok": False, "error": "work_order_not_found"}), 200

    data = request.get_json(silent=True) or {}
    amount = f64(data.get("amount"))
    payment_method = (data.get("payment_method") or "").strip() or "cash"
    notes = (data.get("notes") or "").strip()

    if amount is None or not (isinstance(amount, (int, float)) and amount > 0):
        return jsonify({"ok": False, "error": "invalid_amount"}), 200

    # Get work order grand total
    grand_total = round2(wo.get("grand_total") or 0)

    # Get payments already made
    existing_payments = list(
        shop_db.work_order_payments.find({"work_order_id": wo_id, "is_active": True})
    )
    paid_amount = round2(sum(round2(p.get("amount") or 0) for p in existing_payments))

    # Calculate new balance
    new_paid_amount = round2(paid_amount + amount)
    remaining_balance = round2(grand_total - new_paid_amount)

    # If payment exceeds total, return error
    if new_paid_amount > grand_total:
        return jsonify({
            "ok": False,
            "error": "overpayment",
            "message": f"Payment would exceed invoice total. Current balance: ${round2(grand_total - paid_amount)}"
        }), 200

    now = utcnow()
    user_id = current_user_id()

    # Save payment record
    payment_doc = {
        "work_order_id": wo_id,
        "shop_id": shop["_id"],
        "tenant_id": shop.get("tenant_id"),
        "amount": round2(amount),
        "payment_method": payment_method,
        "notes": notes,
        "is_active": True,
        "created_at": now,
        "created_by": user_id,
    }

    payment_result = shop_db.work_order_payments.insert_one(payment_doc)
    payment_id = payment_result.inserted_id

    # Check if fully paid - if so, update work order status
    is_fully_paid = remaining_balance <= 0.01  # Allow 1 cent rounding difference
    if is_fully_paid:
        shop_db.work_orders.update_one(
            {"_id": wo_id},
            {
                "$set": {
                    "status": "paid",
                    "updated_at": now,
                    "updated_by": user_id,
                }
            }
        )

    return jsonify({
        "ok": True,
        "payment_id": str(payment_id),
        "amount_paid": round2(new_paid_amount),
        "remaining_balance": remaining_balance,
        "is_fully_paid": is_fully_paid
    }), 200


@work_orders_bp.get("/work_orders/api/work_orders/<work_order_id>/payments")
@login_required
@permission_required("work_orders.create")
def api_get_work_order_payments(work_order_id):
    """
    Get all payments for a work order with balance info.
    """
    shop_db, shop = get_shop_db()
    if shop_db is None:
        return jsonify({"ok": False, "error": "shop_db_missing"}), 200

    wo_id = oid(work_order_id)
    if not wo_id:
        return jsonify({"ok": False, "error": "invalid_work_order_id"}), 200

    wo = shop_db.work_orders.find_one({"_id": wo_id, "shop_id": shop["_id"], "is_active": True})
    if not wo:
        return jsonify({"ok": False, "error": "work_order_not_found"}), 200

    grand_total = round2(wo.get("grand_total") or 0)

    payments = list(
        shop_db.work_order_payments.find({"work_order_id": wo_id, "is_active": True})
        .sort([("created_at", -1)])
    )

    paid_amount = round2(sum(round2(p.get("amount") or 0) for p in payments))
    remaining_balance = round2(grand_total - paid_amount)

    payment_list = [
        {
            "id": str(p.get("_id")),
            "amount": round2(p.get("amount") or 0),
            "payment_method": p.get("payment_method") or "cash",
            "notes": p.get("notes") or "",
            "created_at": p.get("created_at").isoformat() if p.get("created_at") else "",
        }
        for p in payments
    ]

    return jsonify({
        "ok": True,
        "grand_total": grand_total,
        "paid_amount": paid_amount,
        "remaining_balance": remaining_balance,
        "payments": payment_list
    }), 200


@work_orders_bp.get("/work_orders/api/work_orders/all-payments")
@login_required
@permission_required("work_orders.view")
def api_get_all_payments():
    """
    Get all payments for the current shop.
    """
    shop_db, shop = get_shop_db()
    if shop_db is None:
        return jsonify({"ok": False, "error": "shop_db_missing"}), 200

    shop_id = shop["_id"]

    payments = list(
        shop_db.work_order_payments.find({"shop_id": shop_id, "is_active": True})
        .sort([("created_at", -1)])
        .limit(500)
    )

    work_order_ids = [p.get("work_order_id") for p in payments if p.get("work_order_id")]
    work_orders_map = {}
    customer_ids = []
    if work_order_ids:
        work_orders = list(
            shop_db.work_orders.find(
                {"_id": {"$in": work_order_ids}, "shop_id": shop_id},
                {"customer_id": 1},
            )
        )
        for wo in work_orders:
            wo_id = wo.get("_id")
            if wo_id:
                work_orders_map[wo_id] = wo
            customer_id = wo.get("customer_id")
            if customer_id:
                customer_ids.append(customer_id)

    customers_map = {}
    if customer_ids:
        customers = list(
            shop_db.customers.find({"_id": {"$in": customer_ids}}, {"company_name": 1, "first_name": 1, "last_name": 1})
        )
        for c in customers:
            c_id = c.get("_id")
            if c_id:
                customers_map[c_id] = customer_label(c)

    payment_list = [
        {
            "id": str(p.get("_id")),
            "work_order_id": str(p.get("work_order_id")) if p.get("work_order_id") else "",
            "customer": customers_map.get((work_orders_map.get(p.get("work_order_id")) or {}).get("customer_id")) or "-",
            "amount": round2(p.get("amount") or 0),
            "payment_method": p.get("payment_method") or "cash",
            "notes": p.get("notes") or "",
            "created_at": p.get("created_at").isoformat() if p.get("created_at") else "",
        }
        for p in payments
    ]

    return jsonify({
        "ok": True,
        "payments": payment_list
    }), 200


@work_orders_bp.post("/work_orders/api/test/create-sample-payment/<work_order_id>")
@login_required
@permission_required("work_orders.create")
def api_test_create_sample_payment(work_order_id):
    """
    TEST ENDPOINT: Create a sample payment for testing (remove in production).
    """
    shop_db, shop = get_shop_db()
    if shop_db is None:
        return jsonify({"ok": False, "error": "shop_db_missing"}), 200

    wo_id = oid(work_order_id)
    if not wo_id:
        return jsonify({"ok": False, "error": "invalid_work_order_id"}), 200

    wo = shop_db.work_orders.find_one({"_id": wo_id, "shop_id": shop["_id"], "is_active": True})
    if not wo:
        return jsonify({"ok": False, "error": "work_order_not_found"}), 200

    now = utcnow()
    user_id = current_user_id()

    # Create test payment
    payment_doc = {
        "work_order_id": wo_id,
        "shop_id": shop["_id"],
        "tenant_id": shop.get("tenant_id"),
        "amount": 99.99,
        "payment_method": "cash",
        "notes": "[TEST PAYMENT]",
        "is_active": True,
        "created_at": now,
        "created_by": user_id,
    }

    result = shop_db.work_order_payments.insert_one(payment_doc)

    return jsonify({
        "ok": True,
        "message": "Test payment created",
        "payment_id": str(result.inserted_id)
    }), 200


@work_orders_bp.post("/work_orders/api/work_orders/<work_order_id>/status")
@login_required
@permission_required("work_orders.create")
def api_work_order_set_status(work_order_id):
    shop_db, shop = get_shop_db()
    if shop_db is None:
        return jsonify({"ok": False, "error": "shop_db_missing"}), 200

    wo_id = oid(work_order_id)
    if not wo_id:
        return jsonify({"ok": False, "error": "invalid_work_order_id"}), 200

    wo = shop_db.work_orders.find_one({"_id": wo_id, "shop_id": shop["_id"], "is_active": True})
    if not wo:
        return jsonify({"ok": False, "error": "work_order_not_found"}), 200

    data = request.get_json(silent=True) or {}
    status = (data.get("status") or "").strip().lower()

    if status not in ("open", "paid"):
        return jsonify({"ok": False, "error": "invalid_status"}), 200

    now = utcnow()
    user_id = current_user_id()

    # If changing to "open" (unpaid), delete all payment records for this work order
    if status == "open":
        shop_db.work_order_payments.delete_many({"work_order_id": wo_id})

    shop_db.work_orders.update_one(
        {"_id": wo_id},
        {
            "$set": {
                "status": status,
                "updated_at": now,
                "updated_by": user_id,
            }
        }
    )

    return jsonify({"ok": True, "status": status}), 200
