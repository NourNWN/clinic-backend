from datetime import datetime, timedelta, timezone
from functools import wraps

import jwt
from flask import current_app, g, jsonify, request

# A work shift is a reasonable upper bound for how long an admin session
# should stay valid without requiring a fresh login.
TOKEN_EXPIRY = timedelta(hours=8)

UNAUTHORIZED_ERROR = {
    "error": {
        "code": "unauthorized",
        "message_ar": "يجب تسجيل الدخول أولاً",
        "message_en": "Authentication required",
    }
}

FORBIDDEN_ERROR = {
    "error": {
        "code": "forbidden",
        "message_ar": "ليس لديك صلاحية للقيام بهذا الإجراء",
        "message_en": "You don't have permission to perform this action",
    }
}


def generate_token(user):
    """Build a signed JWT for an admin user, carrying id, role and expiry."""
    now = datetime.now(timezone.utc)
    payload = {
        "sub": user.id,
        "role": user.role,
        "iat": now,
        "exp": now + TOKEN_EXPIRY,
    }
    return jwt.encode(payload, current_app.config["SECRET_KEY"], algorithm="HS256")


def _authenticate():
    """
    Read and verify the `Authorization: Bearer <token>` header. Returns the
    decoded {"id", "role"} dict on success, or None if the header is
    missing or the token is invalid/expired.
    """
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        return None

    token = auth_header[len("Bearer "):].strip()
    try:
        payload = jwt.decode(
            token, current_app.config["SECRET_KEY"], algorithms=["HS256"]
        )
    except jwt.PyJWTError:
        return None

    return {"id": payload.get("sub"), "role": payload.get("role")}


def require_auth(fn):
    """
    Protect a route with JWT authentication. On success, the decoded user
    info ({"id", "role"}) is available on `flask.g.current_user` for the
    route to use. On a missing/invalid/expired token, returns 401.
    """

    @wraps(fn)
    def wrapper(*args, **kwargs):
        user = _authenticate()
        if user is None:
            return jsonify(UNAUTHORIZED_ERROR), 401
        g.current_user = user
        return fn(*args, **kwargs)

    return wrapper


def require_role(role):
    """
    Like `require_auth`, but also requires the authenticated user to have
    the given role — returns 403 otherwise. Use for manager-only routes,
    e.g. `@require_role("manager")`.
    """

    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            user = _authenticate()
            if user is None:
                return jsonify(UNAUTHORIZED_ERROR), 401
            g.current_user = user
            if user["role"] != role:
                return jsonify(FORBIDDEN_ERROR), 403
            return fn(*args, **kwargs)

        return wrapper

    return decorator
