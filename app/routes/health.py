from flask import Blueprint, jsonify
from sqlalchemy import text
from app.extensions import db

health_bp = Blueprint("health", __name__)


@health_bp.route("/api/health")
def health_check():
    """فحص بسيط: هل Flask شغّال، وهل الاتصال بـ PostgreSQL ناجح؟"""
    try:
        result = db.session.execute(text("SELECT version();"))
        pg_version = result.scalar()
        return jsonify({
            "status": "ok",
            "flask": "running",
            "database": "connected",
            "postgres_version": pg_version,
        })
    except Exception as e:
        return jsonify({
            "status": "error",
            "flask": "running",
            "database": "not connected",
            "error": str(e),
        }), 500
