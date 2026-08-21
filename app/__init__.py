from flask import Flask
from config import Config
from app.extensions import db, migrate, cors


def create_app():
    app = Flask(__name__)
    app.config.from_object(Config)

    # ربط الإضافات بالتطبيق
    db.init_app(app)
    migrate.init_app(app, db)
    cors.init_app(app)  # يسمح لموقع React (على منفذ مختلف) بالاتصال بالـ API

    # تسجيل الـ routes (blueprints)
    from app.routes.services import services_bp
    app.register_blueprint(services_bp)

    from app.routes.appointments import appointments_bp
    app.register_blueprint(appointments_bp)

    return app
