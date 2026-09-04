from flask import Flask

import config as config_module
from config import Config
from app.extensions import db, migrate, cors


def create_app():
    app = Flask(__name__)
    app.config.from_object(Config)

    # Refuse to start on a configuration that would be unsafe in a
    # deployment (missing/placeholder SECRET_KEY, no DATABASE_URL).
    config_module.validate(app.config)

    # ربط الإضافات بالتطبيق
    db.init_app(app)
    migrate.init_app(app, db)

    # يسمح لموقع React (على منفذ مختلف) بالاتصال بالـ API — but only from
    # the origins this deployment names, and only on /api/*. Nothing else on
    # this server is meant to be reachable cross-origin.
    cors.init_app(
        app,
        resources={r"/api/*": {"origins": list(app.config["CORS_ORIGINS"])}},
    )

    # تسجيل الـ routes (blueprints)
    from app.routes.services import services_bp
    app.register_blueprint(services_bp)

    from app.routes.appointments import appointments_bp
    app.register_blueprint(appointments_bp)

    from app.routes.health import health_bp
    app.register_blueprint(health_bp)

    from app.routes.admin import admin_bp
    app.register_blueprint(admin_bp)

    return app
