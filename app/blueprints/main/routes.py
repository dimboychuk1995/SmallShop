from flask import render_template, session
from app.utils.auth import login_required, SESSION_USER_ID, SESSION_TENANT_ID, SESSION_TENANT_DB
from . import main_bp

@main_bp.get("/")
def index():
    return render_template("public/auth.html")

@main_bp.get("/dashboard")
@login_required
def dashboard():
    return (
        "Dashboard OK<br>"
        f"user_id: {session.get(SESSION_USER_ID)}<br>"
        f"tenant_id: {session.get(SESSION_TENANT_ID)}<br>"
        f"tenant_db: {session.get(SESSION_TENANT_DB)}<br><br>"
        '<a href="/logout">Logout</a>'
    )