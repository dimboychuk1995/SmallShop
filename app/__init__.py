from flask import Flask

def create_app():
    app = Flask(__name__)

    # Import Config INSIDE factory (fixes circular import issues)
    from app.config import Config
    app.config.from_object(Config)

    # Blueprints
    from app.blueprints.main import main_bp
    from app.blueprints.auth import auth_bp
    from app.blueprints.tenant import tenant_bp

    app.register_blueprint(main_bp)
    app.register_blueprint(auth_bp)
    app.register_blueprint(tenant_bp)

    return app