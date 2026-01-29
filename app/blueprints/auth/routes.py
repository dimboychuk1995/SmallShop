from __future__ import annotations

from flask import request, redirect, url_for, flash, session
from werkzeug.security import check_password_hash
from bson import ObjectId

from app.extensions import get_master_db, get_mongo_client
from app.utils.auth import login_user, logout_user, SESSION_USER_ID, SESSION_TENANT_ID, SESSION_TENANT_DB
from . import auth_bp


def _maybe_object_id(value):
    if not value:
        return None
    try:
        return ObjectId(str(value))
    except Exception:
        return None


def _safe_list(v):
    if not isinstance(v, list):
        return []
    return [x for x in v if x is not None]


def _compute_effective_permissions(user_doc: dict, tenant_doc: dict) -> list[str]:
    """
    Effective permissions:
    1) берем роль(и) из master.users (обычно user_doc["role"])
    2) читаем permissions из tenant_db.roles
    3) применяем overrides (если есть):
       - permissions_allow: добавляем
       - permissions_deny: вычитаем
       - если вдруг есть user_doc["permissions"] как явный override — используем его как базу (highest priority)
    """
    tenant_db_name = (tenant_doc.get("db_name") or "").strip()
    if not tenant_db_name:
        return []

    client = get_mongo_client()
    tdb = client[tenant_db_name]

    # Highest priority override: если кто-то вручную вписал permissions прямо в user doc
    direct = user_doc.get("permissions")
    if isinstance(direct, list) and direct:
        base = {str(p).strip() for p in direct if str(p).strip()}
    else:
        base = set()

        # Роли по умолчанию у тебя строкой: user_doc["role"] = "owner"/"viewer"/...
        role_key = (user_doc.get("role") or "viewer").strip()

        # Также поддержим вариант, если когда-то появится roles: ["owner","manager"]
        roles_list = user_doc.get("roles")
        role_keys = []
        if isinstance(roles_list, list) and roles_list:
            role_keys = [str(x).strip() for x in roles_list if str(x).strip()]
        else:
            role_keys = [role_key]

        for rk in role_keys:
            role_doc = tdb.roles.find_one({"key": rk})
            if role_doc and isinstance(role_doc.get("permissions"), list):
                base |= {str(p).strip() for p in role_doc["permissions"] if str(p).strip()}

    # allow/deny overrides (если есть)
    allow = user_doc.get("permissions_allow")
    deny = user_doc.get("permissions_deny")

    if isinstance(allow, list) and allow:
        base |= {str(p).strip() for p in allow if str(p).strip()}

    if isinstance(deny, list) and deny:
        base -= {str(p).strip() for p in deny if str(p).strip()}

    return sorted(base)


@auth_bp.post("/login")
def login():
    master = get_master_db()

    email = (request.form.get("email") or "").strip().lower()
    password = request.form.get("password") or ""

    if not email or not password:
        flash("Fill in email and password.", "error")
        return redirect(url_for("main.index"))

    user = master.users.find_one({"email": email, "is_active": True})
    if not user:
        flash("User not found or inactive.", "error")
        return redirect(url_for("main.index"))

    if not check_password_hash(user.get("password_hash", ""), password):
        flash("Wrong password.", "error")
        return redirect(url_for("main.index"))

    tenant = master.tenants.find_one({"_id": user["tenant_id"], "status": "active"})
    if not tenant:
        flash("Tenant not found or inactive.", "error")
        return redirect(url_for("main.index"))

    # ✅ only shop_ids from DB
    shop_ids = user.get("shop_ids") if isinstance(user.get("shop_ids"), list) else []
    shop_ids_str = [str(x) for x in shop_ids]

    # ✅ do NOT pass shop_id -> login_user will set session["shop_id"] = shop_ids_str[0]
    login_user(
        user_id=user["_id"],
        tenant_id=tenant["_id"],
        tenant_db_name=tenant.get("db_name", ""),
        shop_ids=shop_ids_str,
        shop_id=None,
    )

    # ✅ Сохраняем effective permissions в session, чтобы UI везде мог их читать
    perms = _compute_effective_permissions(user, tenant)
    session["user_permissions"] = perms
    session.modified = True

    return redirect(url_for("main.dashboard"))


@auth_bp.get("/logout")
def logout():
    logout_user()
    flash("Logged out.", "info")
    return redirect(url_for("main.index"))
