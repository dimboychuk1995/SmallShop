from flask import Blueprint

settings_bp = Blueprint("settings", __name__, url_prefix="/settings")

# импортируем routes чтобы они зарегистрировались на blueprint
from .users.routes import *  # noqa
from .locations.routes import *
