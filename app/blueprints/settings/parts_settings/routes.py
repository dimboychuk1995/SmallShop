from __future__ import annotations

from datetime import datetime, timezone

from bson import ObjectId
from flask import (
    render_template,
    redirect,
    url_for,
    flash,
    session,
    request,
)

from app.blueprints.settings import settings_bp
from app.extensions import get_master_db, get_mongo_client
from app.utils.auth import (
    login_required,
    SESSION_USER_ID,
    SESSION_TENANT_ID,
    SESSION_TENANT_DB,
    SESSION_SHOP_ID,
)
from app.utils.permissions import permission_required, filter_nav_items
from app.blueprints.main.routes import NAV_ITEMS
from app.utils.layout import build_app_layout_context


# -----------------------------
# Helpers
# -----------------------------

def utcnow():
    return datetime.now(timezone.utc)


def _maybe_object_id(value):
    if not value:
        return None
    try:
        return ObjectId(str(value))
    except Exception:
        return None


def _get_tenant_db():
    # оставляем (может быть полезно в другом месте),
    # но parts_settings больше НЕ использует tenant DB как fallback
    db_name = session.get(SESSION_TENANT_DB)
    if not db_name:
        return None
    client = get_mongo_client()
    return client[db_name]


def _load_current_user(master):
    user_id = _maybe_object_id(session.get(SESSION_USER_ID))
    if not user_id:
        return None
    return master.users.find_one({"_id": user_id, "is_active": True})


def _render_settings_page(template_name: str, **ctx):
    """
    Один общий рендер для settings-страниц через единый layout builder.
    """
    layout = build_app_layout_context(filter_nav_items(NAV_ITEMS), "settings")

    if not layout.get("_current_user") or not layout.get("_current_tenant"):
        flash("Session expired. Please login again.", "error")
        session.clear()
        return redirect(url_for("main.index"))

    layout.update(ctx)
    return render_template(template_name, **layout)


def _load_shops_for_tenant(master, tenant_id):
    shops = []
    if not tenant_id:
        return shops

    for s in master.shops.find({"tenant_id": tenant_id}).sort("created_at", 1):
        shops.append({
            "id": str(s["_id"]),
            "name": s.get("name") or "—",
        })
    return shops


def _get_shop_db_strict(master):
    """
    STRICT: return ONLY active shop DB.
    No tenant DB fallback (otherwise categories become shared across shops).
    """
    client = get_mongo_client()

    shop_id = _maybe_object_id(session.get(SESSION_SHOP_ID))
    if not shop_id:
        return None

    shop = master.shops.find_one({"_id": shop_id})
    if not shop:
        return None

    db_name = (
        shop.get("db_name")
        or shop.get("database")
        or shop.get("mongo_db")
        or shop.get("shop_db")
    )
    if not db_name:
        return None

    return client[str(db_name)]


def _clean_name(value: str) -> str:
    return (value or "").strip()


def _require_active_shop_or_redirect():
    shop_oid = _maybe_object_id(session.get(SESSION_SHOP_ID))
    if not shop_oid:
        flash("Please select an active shop first.", "error")
        return None
    return shop_oid


def _require_shop_db_or_redirect():
    master = get_master_db()
    shop_oid = _require_active_shop_or_redirect()
    if not shop_oid:
        return None, None, None

    sdb = _get_shop_db_strict(master)
    if sdb is None:
        flash("Shop database is not configured for the active shop.", "error")
        return None, None, None

    return master, sdb, shop_oid


def _find_one_by_id(col, _id_str: str, extra_filter: dict | None = None):
    oid = _maybe_object_id(_id_str)
    if not oid:
        return None
    q = {"_id": oid}
    if extra_filter:
        q.update(extra_filter)
    return col.find_one(q)


# -----------------------------
# UI Route: Parts Settings
# -----------------------------

@settings_bp.route("/parts-settings", methods=["GET"])
@login_required
@permission_required("parts.edit")
def parts_settings_index():
    master = get_master_db()

    tenant_id_raw = session.get(SESSION_TENANT_ID)
    if not tenant_id_raw:
        flash("Tenant session missing. Please login again.", "error")
        session.clear()
        return redirect(url_for("main.index"))

    current_user = _load_current_user(master)
    if not current_user:
        flash("User session mismatch. Please login again.", "error")
        session.clear()
        return redirect(url_for("main.index"))

    tenant_from_user = current_user.get("tenant_id") or tenant_id_raw
    tenant_oid = _maybe_object_id(tenant_from_user) or _maybe_object_id(tenant_id_raw)

    active_shop_id = str(session.get(SESSION_SHOP_ID) or "")
    shops_for_ui = _load_shops_for_tenant(master, tenant_oid)

    shop_oid = _maybe_object_id(active_shop_id)
    sdb = _get_shop_db_strict(master)

    if not shop_oid or sdb is None:
        return _render_settings_page(
            "public/settings/parts_settings.html",
            active_shop_id=active_shop_id,
            tenant_id=str(tenant_oid or tenant_id_raw),
            tenant_db_name=session.get(SESSION_TENANT_DB) or "",
            shops_for_ui=shops_for_ui,
            now_utc=utcnow(),
            current_user=current_user,
            parts_locations=[],
            parts_categories=[],
            edit_location_id=None,
            edit_category_id=None,
            error_message="Please select an active shop (and ensure it has a shop DB).",
        )

    # ✅ ALWAYS filter by active shop_id
    parts_locations = list(
        sdb.parts_locations.find({"shop_id": shop_oid}).sort([("name", 1), ("created_at", 1)])
    )
    parts_categories = list(
        sdb.parts_categories.find({"shop_id": shop_oid}).sort([("name", 1), ("created_at", 1)])
    )

    edit_location_id = request.args.get("edit_location_id") or None
    edit_category_id = request.args.get("edit_category_id") or None

    return _render_settings_page(
        "public/settings/parts_settings.html",
        active_shop_id=active_shop_id,
        tenant_id=str(tenant_oid or tenant_id_raw),
        tenant_db_name=session.get(SESSION_TENANT_DB) or "",
        shops_for_ui=shops_for_ui,
        now_utc=utcnow(),
        current_user=current_user,
        parts_locations=parts_locations,
        parts_categories=parts_categories,
        edit_location_id=edit_location_id,
        edit_category_id=edit_category_id,
        error_message=None,
    )


# -----------------------------
# CRUD: Parts Locations
# -----------------------------

@settings_bp.route("/parts-settings/locations/create", methods=["POST"])
@login_required
@permission_required("parts.edit")
def parts_locations_create():
    master, sdb, shop_oid = _require_shop_db_or_redirect()
    if sdb is None:
        return redirect(url_for("settings.parts_settings_index"))

    name = _clean_name(request.form.get("name", ""))
    if not name:
        flash("Location name is required.", "error")
        return redirect(url_for("settings.parts_settings_index"))

    doc = {
        "name": name,
        "shop_id": shop_oid,
        "is_active": True,
        "created_at": utcnow(),
        "updated_at": utcnow(),
    }

    sdb.parts_locations.insert_one(doc)
    flash("Location created.", "success")
    return redirect(url_for("settings.parts_settings_index"))


@settings_bp.route("/parts-settings/locations/<location_id>/update", methods=["POST"])
@login_required
@permission_required("parts.edit")
def parts_locations_update(location_id: str):
    master, sdb, shop_oid = _require_shop_db_or_redirect()
    if sdb is None:
        return redirect(url_for("settings.parts_settings_index"))

    existing = _find_one_by_id(sdb.parts_locations, location_id, {"shop_id": shop_oid})
    if not existing:
        flash("Location not found.", "error")
        return redirect(url_for("settings.parts_settings_index"))

    name = _clean_name(request.form.get("name", ""))
    if not name:
        flash("Location name is required.", "error")
        return redirect(url_for("settings.parts_settings_index", edit_location_id=location_id))

    sdb.parts_locations.update_one(
        {"_id": existing["_id"]},
        {"$set": {"name": name, "updated_at": utcnow()}},
    )
    flash("Location updated.", "success")
    return redirect(url_for("settings.parts_settings_index"))


@settings_bp.route("/parts-settings/locations/<location_id>/delete", methods=["POST"])
@login_required
@permission_required("parts.edit")
def parts_locations_delete(location_id: str):
    master, sdb, shop_oid = _require_shop_db_or_redirect()
    if sdb is None:
        return redirect(url_for("settings.parts_settings_index"))

    existing = _find_one_by_id(sdb.parts_locations, location_id, {"shop_id": shop_oid})
    if not existing:
        flash("Location not found.", "error")
        return redirect(url_for("settings.parts_settings_index"))

    sdb.parts_locations.delete_one({"_id": existing["_id"]})
    flash("Location deleted.", "success")
    return redirect(url_for("settings.parts_settings_index"))


# -----------------------------
# CRUD: Parts Categories
# -----------------------------

@settings_bp.route("/parts-settings/categories/create", methods=["POST"])
@login_required
@permission_required("parts.edit")
def parts_categories_create():
    master, sdb, shop_oid = _require_shop_db_or_redirect()
    if sdb is None:
        return redirect(url_for("settings.parts_settings_index"))

    name = _clean_name(request.form.get("name", ""))
    if not name:
        flash("Category name is required.", "error")
        return redirect(url_for("settings.parts_settings_index"))

    doc = {
        "name": name,
        "shop_id": shop_oid,
        "is_active": True,
        "created_at": utcnow(),
        "updated_at": utcnow(),
    }

    sdb.parts_categories.insert_one(doc)
    flash("Category created.", "success")
    return redirect(url_for("settings.parts_settings_index"))


@settings_bp.route("/parts-settings/categories/<category_id>/update", methods=["POST"])
@login_required
@permission_required("parts.edit")
def parts_categories_update(category_id: str):
    master, sdb, shop_oid = _require_shop_db_or_redirect()
    if sdb is None:
        return redirect(url_for("settings.parts_settings_index"))

    existing = _find_one_by_id(sdb.parts_categories, category_id, {"shop_id": shop_oid})
    if not existing:
        flash("Category not found.", "error")
        return redirect(url_for("settings.parts_settings_index"))

    name = _clean_name(request.form.get("name", ""))
    if not name:
        flash("Category name is required.", "error")
        return redirect(url_for("settings.parts_settings_index", edit_category_id=category_id))

    sdb.parts_categories.update_one(
        {"_id": existing["_id"]},
        {"$set": {"name": name, "updated_at": utcnow()}},
    )
    flash("Category updated.", "success")
    return redirect(url_for("settings.parts_settings_index"))


@settings_bp.route("/parts-settings/categories/<category_id>/delete", methods=["POST"])
@login_required
@permission_required("parts.edit")
def parts_categories_delete(category_id: str):
    master, sdb, shop_oid = _require_shop_db_or_redirect()
    if sdb is None:
        return redirect(url_for("settings.parts_settings_index"))

    existing = _find_one_by_id(sdb.parts_categories, category_id, {"shop_id": shop_oid})
    if not existing:
        flash("Category not found.", "error")
        return redirect(url_for("settings.parts_settings_index"))

    sdb.parts_categories.delete_one({"_id": existing["_id"]})
    flash("Category deleted.", "success")
    return redirect(url_for("settings.parts_settings_index"))
