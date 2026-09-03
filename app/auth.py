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

# Distinct from UNAUTHORIZED_ERROR so a client can tell "your session ran
# out, log in again" apart from "you never sent a usable token" and react
# accordingly (e.g. redirect straight to the login screen).
TOKEN_EXPIRED_ERROR = {
    "error": {
        "code": "token_expired",
        "message_ar": "انتهت صلاحية الجلسة، يرجى تسجيل الدخول من جديد",
        "message_en": "Your session has expired, please log in again",
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
        # RFC 7519 requires `sub` to be a string, and PyJWT enforces that on
        # decode from 2.10 onwards (InvalidSubjectError). Encoding the id as
        # a number produced tokens that this app happily issued and then
        # rejected on every protected route; `_authenticate` casts it back.
        "sub": str(user.id),
        "role": user.role,
        "iat": now,
        "exp": now + TOKEN_EXPIRY,
    }
    return jwt.encode(payload, current_app.config["SECRET_KEY"], algorithm="HS256")


def _authenticate():
    """
    Read and verify the `Authorization: Bearer <token>` header. Returns
    `(user, None)` with the decoded {"id", "role"} dict on success, or
    `(None, error_body)` with the 401 body to send back on failure.
    """
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        return None, UNAUTHORIZED_ERROR

    token = auth_header[len("Bearer "):].strip()
    try:
        payload = jwt.decode(
            token, current_app.config["SECRET_KEY"], algorithms=["HS256"]
        )
    except jwt.ExpiredSignatureError:
        return None, TOKEN_EXPIRED_ERROR
    except jwt.PyJWTError:
        return None, UNAUTHORIZED_ERROR

    try:
        user_id = int(payload["sub"])
    except (KeyError, TypeError, ValueError):
        return None, UNAUTHORIZED_ERROR

    return {"id": user_id, "role": payload.get("role")}, None


def require_auth(fn):
    """
    Protect a route with JWT authentication. On success, the decoded user
    info ({"id", "role"}) is available on `flask.g.current_user` for the
    route to use. On a missing/invalid token returns 401 `unauthorized`,
    and on an expired one 401 `token_expired`.
    """

    @wraps(fn)
    def wrapper(*args, **kwargs):
        user, error = _authenticate()
        if user is None:
            return jsonify(error), 401
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
            user, error = _authenticate()
            if user is None:
                return jsonify(error), 401
            g.current_user = user
            if user["role"] != role:
                return jsonify(FORBIDDEN_ERROR), 403
            return fn(*args, **kwargs)

        return wrapper

    return decorator
