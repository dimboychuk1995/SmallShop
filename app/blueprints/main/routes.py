from flask import render_template, g
from app.utils.auth import login_required
from . import main_bp


@main_bp.get("/")
def index():
    return render_template("public/auth.html")


@main_bp.get("/dashboard")
@login_required
def dashboard():
    # теперь это “понимание” есть всегда: g.user и g.tenant
    u = g.user
    t = g.tenant
    return (
        "Dashboard OK<br>"
        f"User: {u.get('email')} ({u.get('name')})<br>"
        f"Tenant: {t.get('name')} / db: {t.get('db_name')}<br><br>"
        '<a href="/logout">Logout</a>'
    )
