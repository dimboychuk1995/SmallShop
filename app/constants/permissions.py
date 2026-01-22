# app/constants/permissions.py

from __future__ import annotations

# ЕДИНЫЙ каталог permission keys (источник истины)
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

    # Settings
    "settings.view": "View settings",
    "settings.manage_org": "Manage organization settings",
    "settings.manage_users": "Manage users",
    "settings.manage_roles": "Manage roles & permissions",
}

ALL_PERMISSIONS: list[str] = sorted(PERMISSIONS.keys())


def build_default_roles() -> list[dict]:
    """
    Дефолтные роли, которые засеваем в tenant DB при создании.
    Важно: owner получит ALL_PERMISSIONS.
    """
    all_set = set(ALL_PERMISSIONS)

    manager = all_set - {"settings.manage_roles"}
    tech = {
        "dashboard.view",
        "parts.view",
        "work_orders.view",
        "work_orders.create",
        "work_orders.edit",
        "work_orders.change_status",
    }
    viewer = {
        "dashboard.view",
        "parts.view",
        "work_orders.view",
        "settings.view",
    }

    return [
        {
            "key": "owner",
            "name": "Owner",
            "permissions": sorted(all_set),
            "is_system": True,
        },
        {
            "key": "manager",
            "name": "Manager",
            "permissions": sorted(manager),
            "is_system": True,
        },
        {
            "key": "tech",
            "name": "Tech",
            "permissions": sorted(tech),
            "is_system": True,
        },
        {
            "key": "viewer",
            "name": "Viewer",
            "permissions": sorted(viewer),
            "is_system": True,
        },
    ]
