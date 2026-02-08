from __future__ import annotations

from app.blueprints.main.routes import _render_app_page
from app.utils.auth import login_required
from app.utils.permissions import permission_required

from . import parts_bp


@parts_bp.get("/")
@login_required
@permission_required("parts.view")
def parts_page():
    """
    Большой блок "Запчасти" (не настройки).
    Пока только рендер страницы. Без методов/CRUD.
    """
    return _render_app_page("public/parts.html", active_page="parts")