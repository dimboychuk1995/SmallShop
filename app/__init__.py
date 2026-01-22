from flask import Flask, g, session
from bson import ObjectId

from app.config import Config
from app.extensions import init_mongo, get_master_db
from app.utils.auth import SESSION_USER_ID, SESSION_TENANT_ID

def create_app():
    app = Flask(__name__)
    app.config.from_object(Config)

    init_mongo(app)

    # каждый запрос: если есть сессия — поднимем g.user и g.tenant
    @app.before_request
    def load_current_context():
        g.user = None
        g.tenant = None

        user_id = session.get(SESSION_USER_ID)
        tenant_id = session.get(SESSION_TENANT_ID)
        if not user_id or not tenant_id:
            return

        master = get_master_db()

        try:
            uid = ObjectId(user_id)
            tid = ObjectId(tenant_id)
        except Exception:
            # битая сессия
            session.clear()
            return

        user = master.users.find_one({"_id": uid, "is_active": True})
        if not user:
            session.clear()
            return

        tenant = master.tenants.find_one({"_id": tid, "status": "active"})
        if not tenant:
            session.clear()
            return

        # защита: tenant из сессии должен совпадать с tenant у user
        if user.get("tenant_id") != tenant["_id"]:
            session.clear()
            return

        g.user = user
        g.tenant = tenant

    # Blueprints
    from app.blueprints.main import main_bp
    from app.blueprints.auth import auth_bp
    from app.blueprints.tenant import tenant_bp
    from app.blueprints.settings import settings_bp

    app.register_blueprint(main_bp)
    app.register_blueprint(auth_bp)
    app.register_blueprint(tenant_bp)
    app.register_blueprint(settings_bp)

    return app
