from flask import Blueprint

parts_bp = Blueprint("parts", __name__, url_prefix="/parts")
from . import routes  # noqa