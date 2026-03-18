from __future__ import annotations

from flask import request, session

from app.blueprints.main.routes import NAV_ITEMS
from app.blueprints.reports import reports_bp
from app.extensions import get_master_db
from app.utils.auth import login_required, SESSION_TENANT_ID
from app.utils.layout import render_internal_page
from app.utils.permissions import filter_nav_items


@reports_bp.get("")
@login_required
def reports_index():
    layout_nav = filter_nav_items(NAV_ITEMS)
    return render_internal_page(
        "public/reports.html",
        layout_nav,
        "reports",
    )


@reports_bp.get("/audit")
@login_required
def activity_journal_page():
    layout_nav = filter_nav_items(NAV_ITEMS)
    master = get_master_db()

    tenant_id = str(session.get(SESSION_TENANT_ID) or "")

    page_raw = (request.args.get("page") or "1").strip()
    try:
        page = int(page_raw)
    except Exception:
        page = 1
    if page < 1:
        page = 1

    per_page = 25
    method_filter = (request.args.get("method") or "").strip().upper()
    endpoint_filter = (request.args.get("endpoint") or "").strip()

    query = {}
    if tenant_id:
        query["tenant_id"] = tenant_id
    if method_filter:
        query["method"] = method_filter
    if endpoint_filter:
        query["endpoint"] = endpoint_filter

    total = master.audit_journal.count_documents(query)
    total_pages = (total + per_page - 1) // per_page if total > 0 else 1
    if page > total_pages:
        page = total_pages

    skip = (page - 1) * per_page
    cursor = master.audit_journal.find(
        query,
        {
            "created_at": 1,
            "method": 1,
            "path": 1,
            "endpoint": 1,
            "status_code": 1,
            "user_id": 1,
            "shop_id": 1,
            "payload": 1,
            "error": 1,
        },
    ).sort("created_at", -1).skip(skip).limit(per_page)

    entries = []
    for row in cursor:
        payload = row.get("payload") if isinstance(row.get("payload"), dict) else {}
        entries.append(
            {
                "created_at": row.get("created_at"),
                "method": str(row.get("method") or ""),
                "path": str(row.get("path") or ""),
                "endpoint": str(row.get("endpoint") or ""),
                "status_code": int(row.get("status_code") or 0),
                "user_id": str(row.get("user_id") or ""),
                "shop_id": str(row.get("shop_id") or ""),
                "error": str(row.get("error") or ""),
                "payload": payload,
            }
        )

    return render_internal_page(
        "public/reports/audit.html",
        layout_nav,
        "reports",
        activity_entries=entries,
        activity_total=total,
        activity_page=page,
        activity_per_page=per_page,
        activity_total_pages=total_pages,
        method_filter=method_filter,
        endpoint_filter=endpoint_filter,
    )
