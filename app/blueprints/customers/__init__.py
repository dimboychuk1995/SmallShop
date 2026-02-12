from flask import Blueprint

customers_bp = Blueprint("customers", __name__)

from . import routes  # noqa: E402,F401