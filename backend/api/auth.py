"""JWT helpers + auth decorator for the Flask API."""

import time
from functools import wraps

import jwt
from flask import current_app, g, jsonify, request

from backend.db import models


def encode_token(user):
    now = int(time.time())
    payload = {
        "sub": str(user["id"]),
        "username": user["username"],
        "role": user["role"],
        "iat": now,
        "exp": now + 12 * 60 * 60,  # 12 hours
    }
    return jwt.encode(payload, current_app.config["JWT_SECRET_KEY"], algorithm="HS256")


def decode_token(token):
    try:
        return jwt.decode(token, current_app.config["JWT_SECRET_KEY"], algorithms=["HS256"]), None
    except jwt.ExpiredSignatureError:
        return None, "Token expired"
    except jwt.InvalidTokenError:
        return None, "Invalid token"


def token_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        auth = request.headers.get("Authorization", "")
        if not auth.lower().startswith("bearer "):
            return jsonify(error="Missing or malformed Authorization header"), 401
        payload, err = decode_token(auth[7:])
        if payload is None:
            return jsonify(error=err or "Unauthorized"), 401
        user = models.get_user_by_id(int(payload["sub"]))
        if user is None:
            return jsonify(error="User no longer exists"), 401
        g.user = user
        return f(*args, **kwargs)

    return wrapper


def role_required(*roles):
    """Restrict an endpoint to authenticated users holding one of the given roles.

    Must be chained below token_required so g.user is populated.
    """
    def decorator(f):
        @wraps(f)
        def wrapper(*args, **kwargs):
            if g.user.get("role") not in roles:
                return jsonify(error=f"Forbidden: requires one of {sorted(roles)} role"), 403
            return f(*args, **kwargs)
        return wrapper
    return decorator