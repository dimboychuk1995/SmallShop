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

    tenant = master.tenants.find_one({"_id": user["tenant_id"]})
    if not tenant or tenant.get("status") != "active":
        flash("Tenant is not active or not found.", "error")
        return redirect(url_for("main.index"))

    login_user(user["_id"], tenant["_id"], tenant.get("db_name", ""))
    return redirect(url_for("main.dashboard"))


@auth_bp.get("/logout")
def logout():
    logout_user()
    flash("Logged out.", "info")
    return redirect(url_for("main.index"))
