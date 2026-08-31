from flask import Blueprint, jsonify, request
from werkzeug.security import check_password_hash

from app.auth import generate_token
from app.models import AdminUser

admin_bp = Blueprint("admin", __name__)

INVALID_CREDENTIALS_ERROR = {
    "error": {
        "code": "invalid_credentials",
        "message_ar": "اسم المستخدم أو كلمة المرور غير صحيحة",
        "message_en": "Invalid username or password",
    }
}


@admin_bp.route("/api/admin/login", methods=["POST"])
def login():
    data = request.get_json() or {}
    username = data.get("username")
    password = data.get("password")

    if not username or not password:
        return jsonify(INVALID_CREDENTIALS_ERROR), 401

    user = AdminUser.query.filter_by(username=username).first()

    # Same generic error whether the username doesn't exist or the password
    # is wrong, so a caller can't use this endpoint to enumerate usernames.
    if not user or not check_password_hash(user.password_hash, password):
        return jsonify(INVALID_CREDENTIALS_ERROR), 401

    token = generate_token(user)

    return jsonify({
        "token": token,
        "user": {
            "id": user.id,
            "full_name": user.full_name,
            "role": user.role,
        },
    })
