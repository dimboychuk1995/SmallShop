from flask import Flask
from app.config import Config

def create_app():
    app = Flask(__name__)
    app.config.from_object(Config)

    # Import blueprints inside the factory to avoid circular imports
    from app.blueprints.main import main_bp
    from app.blueprints.auth import auth_bp
    from app.blueprints.tenant import tenant_bp

    app.register_blueprint(main_bp)
    app.register_blueprint(auth_bp)
    app.register_blueprint(tenant_bp)

    return app