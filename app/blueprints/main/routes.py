from flask import render_template, session, redirect, url_for, flash
from bson import ObjectId

from app.utils.auth import login_required, SESSION_USER_ID, SESSION_TENANT_ID
from app.utils.permissions import permission_required
from app.extensions import get_master_db
from . import main_bp


@main_bp.get("/")
def index():
    return render_template("public/auth.html")


# Единый список меню (добавлять новые страницы — 1 строка тут)
NAV_ITEMS = [
    {"key": "dashboard", "label": "Dashboard", "endpoint": "main.dashboard"},
    {"key": "parts", "label": "Parts", "endpoint": "main.parts"},
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


def _render_app_page(template_name: str, active_page: str):
    """
    Общий рендер для всех внутренних страниц.
    """
    user, tenant = _load_user_and_tenant_from_session()

    if not user or not tenant:
        flash("Session data mismatch. Please login again.", "error")
        session.clear()
        return redirect(url_for("main.index"))

    user_name = user.get("name") or user.get("username") or ""
    user_email = user.get("email") or ""
    tenant_name = tenant.get("name") or tenant.get("title") or tenant.get("company_name") or ""

    # ВАЖНО: отдаём и старые переменные (для app_base.html), и новые (для страниц)
    app_user_display = user_name or user_email or "—"
    app_tenant_display = tenant_name or "—"

    return render_template(
        template_name,
        # header (то, что ждёт app_base.html)
        app_user_display=app_user_display,
        app_tenant_display=app_tenant_display,

        # на всякий случай оставим и эти (если где-то используются в страницах)
        user_name=user_name,
        user_email=user_email,
        tenant_name=tenant_name,

        # sidebar
        nav_items=NAV_ITEMS,
        active_page=active_page,
    )


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


@main_bp.get("/settings/users")
@login_required
@permission_required("settings.manage_users")
def settings_users():
    return _render_app_page("public/settings/users.html", active_page="settings")


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


@main_bp.get("/settings/integrations")
@login_required
@permission_required("settings.manage_org")
def settings_integrations():
    return _render_app_page("public/settings/integrations.html", active_page="settings")


@main_bp.get("/reports")
@login_required
def reports():
    return _render_app_page("public/reports.html", active_page="reports")