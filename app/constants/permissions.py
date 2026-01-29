from __future__ import annotations


# =========================================================
# 1) ЕДИНЫЙ КАТАЛОГ PERMISSIONS (источник истины)
#    Формат ключей: <module>.<action>
# =========================================================
PERMISSIONS: dict[str, str] = {
    # Dashboard
    "dashboard.view": "View dashboard",

    # Parts
    "parts.view": "View parts",
    "parts.create": "Create parts",
    "parts.edit": "Edit parts",
    "parts.delete": "Delete parts",

    # Work Orders
    "work_orders.view": "View work orders",
    "work_orders.create": "Create work orders",
    "work_orders.edit": "Edit work orders",
    "work_orders.change_status": "Change work order status",
    "work_orders.delete": "Delete work orders",

    # Vendors
    "vendors.view": "Vendor: view",
    "vendors.edit": "Vendor: edit",
    "vendors.deactivate": "Vendor: deactivate",

    # Reports
    "reports.view": "View reports",
    "reports.export": "Export reports",

    # Settings
    "settings.view": "View settings",
    "settings.manage_org": "Manage organization settings",
    "settings.manage_users": "Manage users",
    "settings.manage_roles": "Manage roles & permissions",
}

ALL_PERMISSIONS: list[str] = sorted(PERMISSIONS.keys())


def _all() -> set[str]:
    return set(ALL_PERMISSIONS)


def _safe_subset(keys: set[str]) -> set[str]:
    """
    На случай опечатки: гарантируем, что роли не содержат ключей,
    которых нет в каталоге PERMISSIONS.
    """
    allp = _all()
    return {k for k in keys if k in allp}


# =========================================================
# 2) ДЕФОЛТНЫЕ РОЛИ (seed в tenant DB)
#
# Роли по твоему списку:
# - Owner: первый пользователь, полный доступ
# - General manager: полный доступ
# - Manager: всё, кроме распределения ролей
# - Parts manager: parts.* + WO view + dashboard view + reports view
# - Senior mechanic: WO view/create + parts view + reports view
# - Mechanic: WO view
#
# Я ДОПОЛНИЛ:
# - Viewer: только просмотр (удобно для офис/аудит)
# =========================================================
def build_default_roles() -> list[dict]:
    allp = _all()

    # Полный доступ
    owner = allp
    general_manager = allp

    # Manager: всё кроме управления ролями (распределение ролей)
    manager = allp - {"settings.manage_roles"}

    # Parts manager:
    # - все права по parts
    # - work_orders: view
    # - dashboard: view
    # - reports: view
    # - vendors: view (чтобы мог смотреть/выбирать поставщиков)
    parts_manager = _safe_subset({
        "dashboard.view",
        "reports.view",
        "parts.view",
        "parts.create",
        "parts.edit",
        "parts.delete",
        "work_orders.view",
        "vendors.view",
    })

    # Senior mechanic:
    # - work_orders: view, create
    # - parts: view (чтобы мог смотреть что списывать)
    # - reports: view (если нужны отчеты по WO/часам)
    # - dashboard: view (обычно да)
    senior_mechanic = _safe_subset({
        "dashboard.view",
        "reports.view",
        "parts.view",
        "work_orders.view",
        "work_orders.create",
    })

    # Mechanic:
    # - только просмотр WO (по твоему)
    # (я оставил без dashboard/reports, чтобы было строго как ты сказал)
    mechanic = _safe_subset({
        "work_orders.view",
    })

    # Viewer (добавил как полезный минимум)
    # + vendors.view (офис/аудит часто надо хотя бы видеть список вендоров)
    viewer = _safe_subset({
        "dashboard.view",
        "parts.view",
        "work_orders.view",
        "reports.view",
        "settings.view",
        "vendors.view",
    })

    return [
        # system roles
        {"key": "owner", "name": "Owner", "permissions": sorted(owner), "is_system": True},
        {"key": "general_manager", "name": "General manager", "permissions": sorted(general_manager), "is_system": True},
        {"key": "manager", "name": "Manager", "permissions": sorted(manager), "is_system": True},
        {"key": "parts_manager", "name": "Parts manager", "permissions": sorted(parts_manager), "is_system": True},
        {"key": "senior_mechanic", "name": "Senior mechanic", "permissions": sorted(senior_mechanic), "is_system": True},
        {"key": "mechanic", "name": "Mechanic", "permissions": sorted(mechanic), "is_system": True},

        # optional helpful role
        {"key": "viewer", "name": "Viewer", "permissions": sorted(viewer), "is_system": True},
    ]
