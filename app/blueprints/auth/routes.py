from __future__ import annotations

from flask import request, redirect, url_for, flash
from werkzeug.security import check_password_hash

from app.extensions import get_master_db
from app.utils.auth import login_user, logout_user
from . import auth_bp


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

    return redirect(url_for("main.dashboard"))



@auth_bp.get("/logout")
def logout():
    logout_user()
    flash("Logged out.", "info")
    return redirect(url_for("main.index"))
