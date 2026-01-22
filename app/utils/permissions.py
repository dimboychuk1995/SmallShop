# app/utils/permissions.py

from __future__ import annotations

from functools import wraps
from bson import ObjectId
from flask import session, request, redirect, url_for, flash, jsonify, g

from app.extensions import get_master_db, get_mongo_client
from app.utils.auth import SESSION_USER_ID, SESSION_TENANT_DB
from app.constants.permissions import ALL_PERMISSIONS


def _maybe_object_id(value):
    if not value:
        return None
    try:
        return ObjectId(str(value))
    except Exception:
        return str(value)


def _is_api_request() -> bool:
    # простой и надежный детектор
    if request.path.startswith("/api/"):
        return True
    if request.is_json:
        return True
    accept = (request.headers.get("Accept") or "").lower()
    return "application/json" in accept


def get_tenant_db():
    db_name = session.get(SESSION_TENANT_DB)
    if not db_name:
        return None
    client = get_mongo_client()
    return client[db_name]


def _load_master_user():
    master = get_master_db()
    user_id = _maybe_object_id(session.get(SESSION_USER_ID))
    if not user_id:
        return None
    return master.users.find_one({"_id": user_id, "is_active": True})


def _sync_owner_role_permissions(tdb, role_doc) -> None:
    """
    Чтобы owner АВТОМАТИЧЕСКИ получал новые permissions,
    при каждом запросе проверяем role.permissions и дописываем недостающие.
    """
    if not role_doc or role_doc.get("key") != "owner":
        return

    existing = set(role_doc.get("permissions") or [])
    missing = set(ALL_PERMISSIONS) - existing
    if not missing:
        return

    tdb.roles.update_one(
        {"_id": role_doc["_id"]},
        {"$addToSet": {"permissions": {"$each": sorted(missing)}}},
    )


def get_effective_permissions():
    """
    Возвращает set[str] итоговых прав текущего пользователя.
    Кэшируется в g на время запроса.
    """
    if hasattr(g, "effective_permissions"):
        return g.effective_permissions

    user = _load_master_user()
    if not user:
        g.effective_permissions = set()
        return g.effective_permissions

    tdb = get_tenant_db()
    if not tdb:
        g.effective_permissions = set()
        return g.effective_permissions

    role_key = (user.get("role") or "viewer").strip().lower()
    role_doc = tdb.roles.find_one({"key": role_key})

    # если owner — синхронизируем роль на новые permissions
    _sync_owner_role_permissions(tdb, role_doc)

    role_perms = set(role_doc.get("permissions") or []) if role_doc else set()

    # overrides на пользователя (на будущее, можешь пока не заполнять)
    allow = set(user.get("allow_permissions") or [])
    deny = set(user.get("deny_permissions") or [])

    effective = (role_perms | allow) - deny
    g.effective_permissions = effective
    return effective


def has_permission(permission_key: str) -> bool:
    perms = get_effective_permissions()
    return permission_key in perms


def permission_required(permission_key: str):
    """
    Декоратор для страниц/методов:
    - для HTML: flash + редирект на dashboard
    - для API: 403 JSON
    """
    def decorator(view_func):
        @wraps(view_func)
        def wrapper(*args, **kwargs):
            if has_permission(permission_key):
                return view_func(*args, **kwargs)

            if _is_api_request():
                return jsonify({"ok": False, "error": "forbidden", "required": permission_key}), 403

            flash("Access denied.", "error")
            return redirect(url_for("main.dashboard"))
        return wrapper
    return decorator


def filter_nav_items(nav_items: list[dict]) -> list[dict]:
    """
    Убираем пункты меню, к которым нет доступа.
    item может иметь поле 'perm'. Если perm нет — пункт доступен всем logged-in.
    """
    perms = get_effective_permissions()
    out = []
    for item in nav_items:
        perm = item.get("perm")
        if not perm or perm in perms:
            out.append(item)
    return out