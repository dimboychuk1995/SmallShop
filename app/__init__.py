from flask import Flask
from app.config import Config
from app.extensions import init_mongo

def create_app():
    app = Flask(__name__)
    app.config.from_object(Config)

    # Mongo init + master indexes
    init_mongo(app)

    # Blueprints
    from app.blueprints.main import main_bp
    from app.blueprints.auth import auth_bp
    from app.blueprints.tenant import tenant_bp

    app.register_blueprint(main_bp)
    app.register_blueprint(auth_bp)
    app.register_blueprint(tenant_bp)

    return app
