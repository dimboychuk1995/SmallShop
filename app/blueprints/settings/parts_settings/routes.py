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
# Helpers (как в users.py)
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


def _get_shop_db(master):
    """
    Shop-specific DB (shop DB).
    Пытаемся взять имя базы из master.shops, иначе fallback на tenant DB.

    Ожидаемые поля у shop (варианты): db_name / database / mongo_db / shop_db.
    Если у тебя другое поле — просто добавь его сюда.
    """
    client = get_mongo_client()

    shop_id = _maybe_object_id(session.get(SESSION_SHOP_ID))
    if shop_id:
        shop = master.shops.find_one({"_id": shop_id})
        if shop:
            db_name = (
                shop.get("db_name")
                or shop.get("database")
                or shop.get("mongo_db")
                or shop.get("shop_db")
            )
            if db_name:
                return client[str(db_name)]

    # fallback
    tdb = _get_tenant_db()
    if tdb is not None:
        return tdb

    return None


def _clean_name(value: str) -> str:
    return (value or "").strip()


def _require_shop_db_or_redirect():
    master = get_master_db()
    sdb = _get_shop_db(master)
    if sdb is None:
        flash("Shop database is not configured. Please select a shop and try again.", "error")
        return None, None
    return master, sdb


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
    """
    Рендер страницы Parts Settings.
    Шаблон: public/settings/parts_settings.html

    На странице:
      - Parts Locations CRUD
      - Parts Categories CRUD
    """
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

    sdb = _get_shop_db(master)
    if sdb is None:
        # можно отрендерить пусто, но лучше сказать что нет shop db
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
            error_message="Shop database is not configured for the active shop.",
        )

    # данные
    shop_oid = _maybe_object_id(active_shop_id)
    loc_filter = {"shop_id": shop_oid} if shop_oid else {}
    cat_filter = {"shop_id": shop_oid} if shop_oid else {}

    parts_locations = list(
        sdb.parts_locations.find(loc_filter).sort([("name", 1), ("created_at", 1)])
    )
    parts_categories = list(
        sdb.parts_categories.find(cat_filter).sort([("name", 1), ("created_at", 1)])
    )

    # режим редактирования (без JS)
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
    master, sdb = _require_shop_db_or_redirect()
    if sdb is None:
        return redirect(url_for("settings.parts_settings_index"))

    name = _clean_name(request.form.get("name", ""))
    if not name:
        flash("Location name is required.", "error")
        return redirect(url_for("settings.parts_settings_index"))

    shop_oid = _maybe_object_id(session.get(SESSION_SHOP_ID))
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
    master, sdb = _require_shop_db_or_redirect()
    if sdb is None:
        return redirect(url_for("settings.parts_settings_index"))

    shop_oid = _maybe_object_id(session.get(SESSION_SHOP_ID))
    existing = _find_one_by_id(sdb.parts_locations, location_id, {"shop_id": shop_oid} if shop_oid else None)
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
    master, sdb = _require_shop_db_or_redirect()
    if sdb is None:
        return redirect(url_for("settings.parts_settings_index"))

    shop_oid = _maybe_object_id(session.get(SESSION_SHOP_ID))
    existing = _find_one_by_id(sdb.parts_locations, location_id, {"shop_id": shop_oid} if shop_oid else None)
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
    master, sdb = _require_shop_db_or_redirect()
    if sdb is None:
        return redirect(url_for("settings.parts_settings_index"))

    name = _clean_name(request.form.get("name", ""))
    if not name:
        flash("Category name is required.", "error")
        return redirect(url_for("settings.parts_settings_index"))

    shop_oid = _maybe_object_id(session.get(SESSION_SHOP_ID))
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
    master, sdb = _require_shop_db_or_redirect()
    if sdb is None:
        return redirect(url_for("settings.parts_settings_index"))

    shop_oid = _maybe_object_id(session.get(SESSION_SHOP_ID))
    existing = _find_one_by_id(sdb.parts_categories, category_id, {"shop_id": shop_oid} if shop_oid else None)
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
    master, sdb = _require_shop_db_or_redirect()
    if sdb is None:
        return redirect(url_for("settings.parts_settings_index"))

    shop_oid = _maybe_object_id(session.get(SESSION_SHOP_ID))
    existing = _find_one_by_id(sdb.parts_categories, category_id, {"shop_id": shop_oid} if shop_oid else None)
    if not existing:
        flash("Category not found.", "error")
        return redirect(url_for("settings.parts_settings_index"))

    sdb.parts_categories.delete_one({"_id": existing["_id"]})
    flash("Category deleted.", "success")
    return redirect(url_for("settings.parts_settings_index"))
