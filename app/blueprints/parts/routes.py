from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from bson import ObjectId
from flask import request, redirect, url_for, flash, session

from app.blueprints.main.routes import _render_app_page
from app.extensions import get_master_db, get_mongo_client
from app.utils.auth import login_required, SESSION_TENANT_ID, SESSION_USER_ID
from app.utils.permissions import permission_required

from . import parts_bp


def utcnow():
    return datetime.now(timezone.utc)


def _oid(value) -> Optional[ObjectId]:
    if not value:
        return None
    try:
        return ObjectId(str(value))
    except Exception:
        return None


def _tenant_id_variants():
    """
    Нужна из-за того, что tenant_id исторически мог быть то строкой, то ObjectId.
    """
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


def _parts_collections():
    """
    Все коллекции живут в SHOP DB:
      - parts
      - vendors
      - parts_categories
      - parts_locations
    """
    master = get_master_db()
    db, shop = _get_shop_db(master)
    if db is None:
        return None, None, None, None, shop, master

    return (
        db.parts,
        db.vendors,
        db.parts_categories,
        db.parts_locations,
        shop,
        master,
    )


def _parse_int(value: str, default: int = 0) -> int:
    try:
        return int(str(value).strip())
    except Exception:
        return default


def _parse_float(value: str, default: float = 0.0) -> float:
    try:
        return float(str(value).strip())
    except Exception:
        return default


def _validate_ref(coll, ref_id_raw: str, label: str):
    """
    Универсальная валидация ссылок на документы (vendor/category/location) в SHOP DB.
    Если ref_id_raw пустой — вернём (None, None) без ошибки.
    """
    ref_id_raw = (ref_id_raw or "").strip()
    if not ref_id_raw:
        return None, None

    ref_oid = _oid(ref_id_raw)
    if not ref_oid:
        return None, f"Invalid {label} id."

    doc = coll.find_one({"_id": ref_oid})
    if not doc:
        return None, f"{label} not found."

    if doc.get("is_active") is False:
        return None, f"{label} is inactive."

    return ref_oid, None


def _name_from_doc(doc: dict) -> str:
    """
    Универсально вытаскиваем отображаемое имя.
    Подходит и для vendors, и для категорий/локаций.
    """
    return (
        doc.get("name")
        or doc.get("company_name")
        or doc.get("title")
        or doc.get("label")
        or ""
    ).strip()


@parts_bp.get("/")
@login_required
@permission_required("parts.view")
def parts_page():
    """
    Показать те запчасти что у нас есть:
      - is_active=True
      - in_stock > 0

    Также сразу тянем справочники для селектов в модалке:
      vendors / categories / locations (active only)
    """
    parts_coll, vendors_coll, cats_coll, locs_coll, shop, master = _parts_collections()
    if parts_coll is None or shop is None:
        flash("Shop database not configured for this shop.", "error")
        return redirect(url_for("main.dashboard"))

    # 1) Parts in stock
    parts_in_stock = list(
        parts_coll.find({"is_active": True, "in_stock": {"$gt": 0}})
        .sort([("part_number", 1), ("description", 1), ("created_at", -1)])
    )

    # 2) Reference lists for modal selects
    vendors = []
    categories = []
    locations = []

    if vendors_coll is not None:
        vendors = list(
            vendors_coll.find({"is_active": {"$ne": False}})
            .sort([("name", 1), ("company_name", 1), ("created_at", -1)])
        )

    if cats_coll is not None:
        categories = list(
            cats_coll.find({"is_active": {"$ne": False}})
            .sort([("name", 1), ("created_at", -1)])
        )

    if locs_coll is not None:
        locations = list(
            locs_coll.find({"is_active": {"$ne": False}})
            .sort([("name", 1), ("created_at", -1)])
        )

    # 3) Make lookup maps for showing names in the table
    vendor_map = {v["_id"]: _name_from_doc(v) for v in vendors if v.get("_id")}
    category_map = {c["_id"]: _name_from_doc(c) for c in categories if c.get("_id")}
    location_map = {l["_id"]: _name_from_doc(l) for l in locations if l.get("_id")}

    for p in parts_in_stock:
        vid = p.get("vendor_id")
        cid = p.get("category_id")
        lid = p.get("location_id")

        if vid:
            p["vendor_name"] = vendor_map.get(vid) or ""
        if cid:
            p["category_name"] = category_map.get(cid) or ""
        if lid:
            p["location_name"] = location_map.get(lid) or ""

    return _render_app_page(
        "public/parts.html",
        active_page="parts",
        parts=parts_in_stock,
        vendors=vendors,
        categories=categories,
        locations=locations,
    )

@parts_bp.post("/create")
@login_required
@permission_required("parts.edit")
def parts_create():
    """
    Добавление запчасти:
      part_number (required)
      description
      reference
      vendor_id (из vendors в этом shop DB)
      category_id (из parts_categories в этом shop DB)
      location_id (из parts_locations в этом shop DB)
      in_stock (int)
      average_cost (float)
    """
    parts_coll, vendors_coll, cats_coll, locs_coll, shop, master = _parts_collections()
    if parts_coll is None or shop is None:
        flash("Shop database not configured for this shop.", "error")
        return redirect(url_for("parts.parts_page"))

    tenant_oid = _oid(session.get(SESSION_TENANT_ID))
    if not tenant_oid:
        flash("Tenant session missing. Please login again.", "error")
        session.clear()
        return redirect(url_for("main.index"))

    part_number = (request.form.get("part_number") or "").strip()
    description = (request.form.get("description") or "").strip()
    reference = (request.form.get("reference") or "").strip()

    vendor_id_raw = (request.form.get("vendor_id") or "").strip()
    category_id_raw = (request.form.get("category_id") or "").strip()
    location_id_raw = (request.form.get("location_id") or "").strip()

    in_stock_raw = (request.form.get("in_stock") or "").strip()
    avg_cost_raw = (request.form.get("average_cost") or "").strip()

    if not part_number:
        flash("Part number is required.", "error")
        return redirect(url_for("parts.parts_page"))

    in_stock = _parse_int(in_stock_raw, default=0)
    if in_stock < 0:
        flash("In stock cannot be negative.", "error")
        return redirect(url_for("parts.parts_page"))

    average_cost = _parse_float(avg_cost_raw, default=0.0)
    if average_cost < 0:
        flash("Average cost cannot be negative.", "error")
        return redirect(url_for("parts.parts_page"))

    # ✅ PyMongo Collection нельзя проверять через bool()
    vendor_oid, err = (
        _validate_ref(vendors_coll, vendor_id_raw, "Vendor")
        if vendors_coll is not None
        else (None, None)
    )
    if err:
        flash(err, "error")
        return redirect(url_for("parts.parts_page"))

    category_oid, err = (
        _validate_ref(cats_coll, category_id_raw, "Category")
        if cats_coll is not None
        else (None, None)
    )
    if err:
        flash(err, "error")
        return redirect(url_for("parts.parts_page"))

    location_oid, err = (
        _validate_ref(locs_coll, location_id_raw, "Location")
        if locs_coll is not None
        else (None, None)
    )
    if err:
        flash(err, "error")
        return redirect(url_for("parts.parts_page"))

    now = utcnow()
    user_oid = _oid(session.get(SESSION_USER_ID))

    doc = {
        "part_number": part_number,
        "description": description or None,
        "reference": reference or None,

        "vendor_id": vendor_oid,
        "category_id": category_oid,
        "location_id": location_oid,

        "in_stock": in_stock,
        "average_cost": float(average_cost),

        "is_active": True,

        "created_at": now,
        "updated_at": now,
        "created_by": user_oid,
        "updated_by": user_oid,
        "deactivated_at": None,
        "deactivated_by": None,

        "shop_id": shop["_id"],
        "tenant_id": tenant_oid,
    }

    parts_coll.insert_one(doc)

    flash("Part created successfully.", "success")
    return redirect(url_for("parts.parts_page"))


@parts_bp.post("/<part_id>/deactivate")
@login_required
@permission_required("parts.deactivate")
def parts_deactivate(part_id: str):
    """
    Удаление запчасти = деактивация (soft delete).
    """
    parts_coll, vendors_coll, cats_coll, locs_coll, shop, master = _parts_collections()
    if parts_coll is None or shop is None:
        flash("Shop database not configured for this shop.", "error")
        return redirect(url_for("parts.parts_page"))

    pid = _oid(part_id)
    if not pid:
        flash("Invalid part id.", "error")
        return redirect(url_for("parts.parts_page"))

    existing = parts_coll.find_one({"_id": pid})
    if not existing:
        flash("Part not found.", "error")
        return redirect(url_for("parts.parts_page"))

    if existing.get("is_active") is False:
        flash("Part is already deactivated.", "info")
        return redirect(url_for("parts.parts_page"))

    now = utcnow()
    user_oid = _oid(session.get(SESSION_USER_ID))

    parts_coll.update_one(
        {"_id": pid},
        {"$set": {
            "is_active": False,
            "updated_at": now,
            "updated_by": user_oid,
            "deactivated_at": now,
            "deactivated_by": user_oid,
        }},
    )

    flash("Part deactivated.", "success")
    return redirect(url_for("parts.parts_page"))


@parts_bp.post("/<part_id>/restore")
@login_required
@permission_required("parts.deactivate")
def parts_restore(part_id: str):
    """
    Restore (reactivate) part.
    Используем то же право parts.deactivate.
    """
    parts_coll, vendors_coll, cats_coll, locs_coll, shop, master = _parts_collections()
    if parts_coll is None or shop is None:
        flash("Shop database not configured for this shop.", "error")
        return redirect(url_for("parts.parts_page"))

    pid = _oid(part_id)
    if not pid:
        flash("Invalid part id.", "error")
        return redirect(url_for("parts.parts_page"))

    existing = parts_coll.find_one({"_id": pid})
    if not existing:
        flash("Part not found.", "error")
        return redirect(url_for("parts.parts_page"))

    if existing.get("is_active") is True:
        flash("Part is already active.", "info")
        return redirect(url_for("parts.parts_page"))

    now = utcnow()
    user_oid = _oid(session.get(SESSION_USER_ID))

    parts_coll.update_one(
        {"_id": pid},
        {"$set": {
            "is_active": True,
            "updated_at": now,
            "updated_by": user_oid,
            "deactivated_at": None,
            "deactivated_by": None,
        }},
    )

    flash("Part restored.", "success")
    return redirect(url_for("parts.parts_page"))
