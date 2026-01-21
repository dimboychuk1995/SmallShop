from __future__ import annotations

from functools import wraps
from flask import session, redirect, url_for, request

SESSION_USER_ID = "user_id"
SESSION_TENANT_ID = "tenant_id"
SESSION_TENANT_DB = "tenant_db_name"

def login_user(user_id, tenant_id, tenant_db_name: str):
    session[SESSION_USER_ID] = str(user_id)
    session[SESSION_TENANT_ID] = str(tenant_id)
    session[SESSION_TENANT_DB] = tenant_db_name

def logout_user():
    session.pop(SESSION_USER_ID, None)
    session.pop(SESSION_TENANT_ID, None)
    session.pop(SESSION_TENANT_DB, None)

def is_logged_in() -> bool:
    return SESSION_USER_ID in session and SESSION_TENANT_ID in session

def login_required(view_func):
    @wraps(view_func)
    def wrapper(*args, **kwargs):
        if not is_logged_in():
            return redirect(url_for("main.index", next=request.path))
        return view_func(*args, **kwargs)
    return wrapper
