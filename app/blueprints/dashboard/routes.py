from __future__ import annotations

from datetime import datetime, timedelta, timezone

from bson import ObjectId
from flask import request, redirect, url_for, flash, session

from app.blueprints.dashboard import dashboard_bp
from app.blueprints.main.routes import _render_app_page
from app.extensions import get_master_db, get_mongo_client
from app.utils.auth import login_required, SESSION_TENANT_ID
from app.utils.permissions import permission_required


def _maybe_object_id(value):
    if not value:
        return None
    try:
        return ObjectId(str(value))
    except Exception:
        return str(value)


def _tenant_id_variants():
    raw = session.get(SESSION_TENANT_ID)
    out = set()
    if raw is None:
        return []
    out.add(raw)
    out.add(str(raw))
    try:
        out.add(ObjectId(str(raw)))
    except Exception:
        pass
    return list(out)


def _get_active_shop_db():
    master = get_master_db()
    shop_oid = _maybe_object_id(session.get("shop_id"))
    tenant_variants = _tenant_id_variants()
    if not shop_oid or not tenant_variants:
        return None, None

    shop = master.shops.find_one({"_id": shop_oid, "tenant_id": {"$in": tenant_variants}})
    if not shop:
        return None, None

    db_name = shop.get("db_name")
    if not db_name:
        return None, shop

    client = get_mongo_client()
    return client[str(db_name)], shop


def _parse_iso_date_utc(value: str):
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        parsed = datetime.strptime(raw, "%Y-%m-%d")
        return parsed.replace(tzinfo=timezone.utc)
    except Exception:
        return None


def _to_iso_date(value):
    if not value:
        return ""
    return value.strftime("%Y-%m-%d")


def _start_of_week_monday(value):
    return value - timedelta(days=value.weekday())


def _start_of_month(value):
    return value.replace(day=1)


def _start_of_quarter(value):
    quarter_start_month = ((value.month - 1) // 3) * 3 + 1
    return value.replace(month=quarter_start_month, day=1)


def _start_of_year(value):
    return value.replace(month=1, day=1)


def _date_range_for_preset(preset: str, today):
    if preset == "today":
        return today, today
    if preset == "yesterday":
        y = today - timedelta(days=1)
        return y, y
    if preset == "this_week":
        return _start_of_week_monday(today), today
    if preset == "last_week":
        this_week_start = _start_of_week_monday(today)
        last_week_start = this_week_start - timedelta(days=7)
        return last_week_start, this_week_start - timedelta(days=1)
    if preset == "this_month":
        return _start_of_month(today), today
    if preset == "last_month":
        this_month_start = _start_of_month(today)
        last_month_end = this_month_start - timedelta(days=1)
        return _start_of_month(last_month_end), last_month_end
    if preset == "this_quarter":
        return _start_of_quarter(today), today
    if preset == "last_quarter":
        this_quarter_start = _start_of_quarter(today)
        last_quarter_end = this_quarter_start - timedelta(days=1)
        return _start_of_quarter(last_quarter_end), last_quarter_end
    if preset == "this_year":
        return _start_of_year(today), today
    if preset == "last_year":
        this_year_start = _start_of_year(today)
        last_year_end = this_year_start - timedelta(days=1)
        return _start_of_year(last_year_end), last_year_end
    return None, None


def _get_date_range_filters(args, from_key: str = "date_from", to_key: str = "date_to", preset_key: str = "date_preset"):
    allowed_presets = {
        "custom",
        "today",
        "yesterday",
        "this_week",
        "last_week",
        "this_month",
        "last_month",
        "this_quarter",
        "last_quarter",
        "this_year",
        "last_year",
    }

    date_from_raw = (args.get(from_key) or "").strip()
    date_to_raw = (args.get(to_key) or "").strip()
    preset_raw = (args.get(preset_key) or "").strip().lower()

    if preset_raw not in allowed_presets:
        preset_raw = "this_week"

    if preset_raw == "custom":
        date_from = date_from_raw
        date_to = date_to_raw
        if not date_from and not date_to:
            preset_raw = "this_week"
            start_date, end_date = _date_range_for_preset(preset_raw, datetime.now(timezone.utc).date())
            date_from = _to_iso_date(start_date)
            date_to = _to_iso_date(end_date)
    else:
        start_date, end_date = _date_range_for_preset(preset_raw, datetime.now(timezone.utc).date())
        date_from = _to_iso_date(start_date)
        date_to = _to_iso_date(end_date)

    created_from = _parse_iso_date_utc(date_from)
    created_to_raw = _parse_iso_date_utc(date_to)

    if created_from and created_to_raw and created_from > created_to_raw:
        created_from, created_to_raw = created_to_raw, created_from
        date_from, date_to = date_to, date_from

    created_to_exclusive = created_to_raw + timedelta(days=1) if created_to_raw else None
    return {
        "date_from": date_from,
        "date_to": date_to,
        "date_preset": preset_raw,
        "created_from": created_from,
        "created_to_exclusive": created_to_exclusive,
    }


def _round2(value):
    try:
        return round(float(value or 0) + 1e-12, 2)
    except Exception:
        return 0.0


@dashboard_bp.get("/dashboard")
@login_required
@permission_required("dashboard.view")
def dashboard():
    shop_db, shop = _get_active_shop_db()
    if shop_db is None:
        flash("Shop database not configured for this shop.", "error")
        return redirect(url_for("main.settings"))

    date_filters = _get_date_range_filters(request.args)
    date_from = date_filters["date_from"]
    date_to = date_filters["date_to"]
    date_preset = date_filters["date_preset"]
    created_from = date_filters["created_from"]
    created_to_exclusive = date_filters["created_to_exclusive"]

    date_match = {"shop_id": shop["_id"], "is_active": True}
    created_filter = {}
    if created_from:
        created_filter["$gte"] = created_from
    if created_to_exclusive:
        created_filter["$lt"] = created_to_exclusive
    if created_filter:
        date_match["created_at"] = created_filter

    period_wo_rows = list(
        shop_db.work_orders.find(
            date_match,
            {"_id": 1, "totals": 1, "grand_total": 1, "labor_total": 1, "parts_total": 1},
        )
    )

    period_total = len(period_wo_rows)

    period_labor_total = 0.0
    period_parts_total = 0.0
    period_grand_total = 0.0
    for wo in period_wo_rows:
        totals = wo.get("totals") if isinstance(wo.get("totals"), dict) else {}
        labor_total = totals.get("labor_total") if totals.get("labor_total") is not None else wo.get("labor_total")
        parts_total = totals.get("parts_total") if totals.get("parts_total") is not None else wo.get("parts_total")
        grand_total = totals.get("grand_total") if totals.get("grand_total") is not None else wo.get("grand_total")
        period_labor_total = _round2(period_labor_total + _round2(labor_total))
        period_parts_total = _round2(period_parts_total + _round2(parts_total))
        period_grand_total = _round2(period_grand_total + _round2(grand_total))

    period_wo_ids = [x.get("_id") for x in period_wo_rows if x.get("_id")]
    period_paid_map = {}
    if period_wo_ids:
        period_pipeline = [
            {"$match": {"work_order_id": {"$in": period_wo_ids}, "is_active": True}},
            {"$group": {"_id": "$work_order_id", "paid_total": {"$sum": "$amount"}}},
        ]
        for row in shop_db.work_order_payments.aggregate(period_pipeline):
            period_paid_map[row.get("_id")] = _round2(row.get("paid_total") or 0)

    period_paid_amount = 0.0
    period_unpaid_amount = 0.0
    for wo in period_wo_rows:
        totals = wo.get("totals") if isinstance(wo.get("totals"), dict) else {}
        grand_total = totals.get("grand_total") if totals.get("grand_total") is not None else wo.get("grand_total")
        grand_total = _round2(grand_total)
        paid_amount = _round2(period_paid_map.get(wo.get("_id"), 0))
        paid_capped = _round2(min(grand_total, paid_amount))
        unpaid_amount = _round2(max(0.0, grand_total - paid_capped))
        period_paid_amount = _round2(period_paid_amount + paid_capped)
        period_unpaid_amount = _round2(period_unpaid_amount + unpaid_amount)

    period_money_total = _round2(period_paid_amount + period_unpaid_amount)
    paid_percent = (period_paid_amount / period_money_total * 100.0) if period_money_total else 0.0

    all_time_base = {"shop_id": shop["_id"], "is_active": True}
    all_time_wo_total = shop_db.work_orders.count_documents(all_time_base)

    # Temporary dynamic goal source via query arg; replace with DB/settings source later.
    goal_raw = str(request.args.get("goal") or "").strip()
    try:
        goal_count = int(goal_raw) if goal_raw else 120
    except Exception:
        goal_count = 120
    if goal_count < 1:
        goal_count = 1

    goal_percent = min(100.0, (period_total / goal_count) * 100.0)

    wo_rows = list(
        shop_db.work_orders.find(
            all_time_base,
            {"_id": 1, "totals": 1, "grand_total": 1},
        )
    )
    wo_ids = [x.get("_id") for x in wo_rows if x.get("_id")]

    paid_map = {}
    if wo_ids:
        pipeline = [
            {"$match": {"work_order_id": {"$in": wo_ids}, "is_active": True}},
            {"$group": {"_id": "$work_order_id", "paid_total": {"$sum": "$amount"}}},
        ]
        for row in shop_db.work_order_payments.aggregate(pipeline):
            paid_map[row.get("_id")] = _round2(row.get("paid_total") or 0)

    outstanding_balance = 0.0
    for wo in wo_rows:
        totals = wo.get("totals") if isinstance(wo.get("totals"), dict) else {}
        grand_total = totals.get("grand_total") if totals.get("grand_total") is not None else wo.get("grand_total")
        grand_total = _round2(grand_total)
        paid_amount = _round2(paid_map.get(wo.get("_id"), 0))
        remaining = _round2(grand_total - paid_amount)
        if remaining > 0:
            outstanding_balance = _round2(outstanding_balance + remaining)

    return _render_app_page(
        "public/dashboard.html",
        active_page="dashboard",
        date_from=date_from,
        date_to=date_to,
        date_preset=date_preset,
        period_paid_amount=period_paid_amount,
        period_unpaid_amount=period_unpaid_amount,
        period_labor_total=period_labor_total,
        period_parts_total=period_parts_total,
        period_grand_total=period_grand_total,
        period_money_total=period_money_total,
        period_total=period_total,
        paid_percent=paid_percent,
        goal_count=goal_count,
        period_wo_total=period_total,
        all_time_wo_total=all_time_wo_total,
        goal_percent=goal_percent,
        outstanding_balance=outstanding_balance,
    )
