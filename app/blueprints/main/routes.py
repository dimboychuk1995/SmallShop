from flask import render_template, request, redirect, url_for, session, flash, g
from bson import ObjectId

from app.utils.auth import login_required, SESSION_USER_ID, SESSION_TENANT_ID, SESSION_TENANT_DB
from app.utils.permissions import permission_required
from app.extensions import get_master_db, get_mongo_client
from . import main_bp


@main_bp.get("/")
def index():
    return render_template("public/auth.html")


# Единый список меню (добавлять новые страницы — 1 строка тут)
NAV_ITEMS = [
    {"key": "dashboard", "label": "Dashboard", "endpoint": "main.dashboard"},
    {"key": "parts", "label": "Parts", "endpoint": "main.parts"},

    # ✅ Vendors (после Parts)
    {"key": "vendors", "label": "Vendors", "endpoint": "main.vendors"},

    {"key": "work_orders", "label": "Work Orders", "endpoint": "main.work_orders"},
    {"key": "settings", "label": "Settings", "endpoint": "main.settings"},
    {"key": "reports", "label": "Reports", "endpoint": "main.reports"},
]


def _maybe_object_id(value):
    """
    Если value похож на ObjectId (24 hex) — вернём ObjectId(value),
    иначе вернём как есть (строка/что угодно).
    """
    if not value:
        return None
    try:
        return ObjectId(str(value))
    except Exception:
        return str(value)


def _load_user_and_tenant_from_session():
    """
    Возвращает (user, tenant) или (None, None) если сессия битая/не совпадает.
    """
    master = get_master_db()

    user_id = _maybe_object_id(session.get(SESSION_USER_ID))
    tenant_id = _maybe_object_id(session.get(SESSION_TENANT_ID))

    user = master.users.find_one({"_id": user_id, "is_active": True})
    tenant = master.tenants.find_one({"_id": tenant_id, "status": "active"})

    return user, tenant


def _get_tenant_db():
    db_name = session.get(SESSION_TENANT_DB)
    if not db_name:
        return None
    client = get_mongo_client()
    return client[db_name]


def _compute_effective_permissions(user: dict):
    """
    1) tenant DB roles (по key)
    2) master.users allow_permissions / deny_permissions (как у тебя в users create)
    """
    tdb = _get_tenant_db()
    if tdb is None:
        return set()

    # роли: поддержим и "role" (строка) и "roles" (список)
    role_keys = []
    if isinstance(user.get("roles"), list) and user["roles"]:
        role_keys = [str(x).strip() for x in user["roles"] if str(x).strip()]
    else:
        role_keys = [str(user.get("role") or "viewer").strip()]

    perms = set()

    for rk in role_keys:
        role_doc = tdb.roles.find_one({"key": rk})
        if role_doc and isinstance(role_doc.get("permissions"), list):
            for p in role_doc["permissions"]:
                s = str(p).strip()
                if s:
                    perms.add(s)

    # overrides в master.users (у тебя поля именно allow_permissions / deny_permissions)
    allow = user.get("allow_permissions")
    deny = user.get("deny_permissions")

    if isinstance(allow, list):
        for p in allow:
            s = str(p).strip()
            if s:
                perms.add(s)

    if isinstance(deny, list):
        for p in deny:
            s = str(p).strip()
            if s and s in perms:
                perms.remove(s)

    return perms


def _render_app_page(template_name: str, active_page: str, **ctx):
    """
    Общий рендер для всех внутренних страниц.
    + Считает effective permissions из tenant DB roles + user allow/deny
    + Прокидывает permissions в payload и в g.user_permissions
    """
    user, tenant = _load_user_and_tenant_from_session()

    if not user or not tenant:
        flash("Session data mismatch. Please login again.", "error")
        session.clear()
        return redirect(url_for("main.index"))

    user_name = user.get("name") or user.get("username") or ""
    user_email = user.get("email") or ""
    tenant_name = tenant.get("name") or tenant.get("title") or tenant.get("company_name") or ""

    app_user_display = user_name or user_email or "—"
    app_tenant_display = tenant_name or "—"

    master = get_master_db()

    # ✅ shops list for dropdown (only allowed shops)
    allowed_ids = session.get("shop_ids") or []
    allowed_ids = [str(x) for x in allowed_ids]

    allowed_oids = []
    for sid in allowed_ids:
        try:
            allowed_oids.append(ObjectId(sid))
        except Exception:
            pass

    shop_options = []
    if allowed_oids:
        for s in master.shops.find({"tenant_id": tenant["_id"], "_id": {"$in": allowed_oids}}).sort("created_at", 1):
            shop_options.append({"id": str(s["_id"]), "name": s.get("name") or "—"})

    # ✅ ensure active shop in session
    active_shop_id = session.get("shop_id")
    if not active_shop_id or active_shop_id not in [x["id"] for x in shop_options]:
        if shop_options:
            active_shop_id = shop_options[0]["id"]
            session["shop_id"] = active_shop_id
            session.modified = True
        else:
            active_shop_id = None

    # ✅ Active shop display
    app_shop_display = "—"
    if active_shop_id:
        for opt in shop_options:
            if opt["id"] == active_shop_id:
                app_shop_display = opt["name"]
                break

    # ✅ EFFECTIVE PERMISSIONS
    perms_set = _compute_effective_permissions(user)
    g.user_permissions = perms_set

    user_permissions_list = sorted(perms_set)

    payload = dict(
        app_user_display=app_user_display,
        app_tenant_display=app_tenant_display,
        app_shop_display=app_shop_display,

        # для dropdown в хедере
        shop_options=shop_options,
        active_shop_id=active_shop_id,

        nav_items=NAV_ITEMS,
        active_page=active_page,

        # ✅ permissions
        user_permissions=user_permissions_list,         # list[str]
        user_permissions_list=user_permissions_list,    # alias для твоего debug
    )

    payload.update(ctx)
    return render_template(template_name, **payload)


@main_bp.post("/session/active-shop")
@login_required
def set_active_shop():
    master = get_master_db()
    user, tenant = _load_user_and_tenant_from_session()

    if not user or not tenant:
        flash("Session data mismatch. Please login again.", "error")
        session.clear()
        return redirect(url_for("main.index"))

    shop_id_raw = (request.form.get("shop_id") or "").strip()
    if not shop_id_raw:
        flash("Shop is required.", "error")
        return redirect(request.referrer or url_for("main.dashboard"))

    allowed = session.get("shop_ids") or []
    allowed = [str(x) for x in allowed]

    if shop_id_raw not in allowed:
        flash("You don't have access to this shop.", "error")
        return redirect(request.referrer or url_for("main.dashboard"))

    try:
        shop_oid = ObjectId(shop_id_raw)
    except Exception:
        flash("Invalid shop id.", "error")
        return redirect(request.referrer or url_for("main.dashboard"))

    shop = master.shops.find_one({"_id": shop_oid, "tenant_id": tenant["_id"]})
    if not shop:
        flash("Shop not found.", "error")
        return redirect(request.referrer or url_for("main.dashboard"))

    session["shop_id"] = shop_id_raw
    session.modified = True

    return redirect(request.referrer or url_for("main.dashboard"))


# ===== Pages =====

@main_bp.get("/dashboard")
@login_required
@permission_required("dashboard.view")
def dashboard():
    return _render_app_page("public/dashboard.html", active_page="dashboard")


@main_bp.get("/parts")
@permission_required("parts.view")
@login_required
def parts():
    return _render_app_page("public/parts.html", active_page="parts")


@main_bp.get("/vendors")
@login_required
@permission_required("vendors.view")
def vendors():
    return _render_app_page("public/vendors.html", active_page="vendors")


@main_bp.get("/work-orders")
@login_required
@permission_required("work_orders.view")
def work_orders():
    return _render_app_page("public/work_orders.html", active_page="work_orders")


@main_bp.get("/settings")
@login_required
@permission_required("settings.view")
def settings():
    return _render_app_page("public/settings.html", active_page="settings")


@main_bp.get("/settings/organization")
@login_required
@permission_required("settings.manage_org")
def settings_organization():
    return _render_app_page("public/settings/organization.html", active_page="settings")


@main_bp.get("/settings/roles")
@login_required
@permission_required("settings.manage_roles")
def settings_roles():
    return _render_app_page("public/settings/roles.html", active_page="settings")


@main_bp.get("/settings/workflows")
@login_required
@permission_required("settings.manage_org")
def settings_workflows():
    return _render_app_page("public/settings/workflows.html", active_page="settings")


@main_bp.get("/settings/notifications")
@login_required
@permission_required("settings.manage_org")
def settings_notifications():
    return _render_app_page("public/settings/notifications.html", active_page="settings")


@main_bp.get("/reports")
@login_required
def reports():
    return _render_app_page("public/reports.html", active_page="reports")
