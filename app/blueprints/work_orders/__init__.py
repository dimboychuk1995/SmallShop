from flask import Blueprint

work_orders_bp = Blueprint("work_orders", __name__)

from . import routes  # noqa: E402,F401
