"""
Authentication helpers for the Backend Storage Service.
Handles password hashing, JWT access tokens, opaque refresh tokens,
and Google ID token verification.
"""

import os
import secrets
import hashlib
import time
import uuid

import jwt as pyjwt
from werkzeug.security import generate_password_hash, check_password_hash

try:
    from google.oauth2 import id_token as google_id_token
    from google.auth.transport import requests as google_requests
    GOOGLE_AUTH_AVAILABLE = True
except ImportError:
    GOOGLE_AUTH_AVAILABLE = False

JWT_SECRET = os.environ.get("JWT_SECRET", "")
JWT_ALGO = "HS256"
ACCESS_TOKEN_TTL_SECONDS = int(os.environ.get("ACCESS_TOKEN_TTL_SECONDS", "900"))              # 15 min
REFRESH_TOKEN_TTL_SECONDS = int(os.environ.get("REFRESH_TOKEN_TTL_SECONDS", str(30 * 24 * 3600)))  # 30 days

GOOGLE_CLIENT_IDS = [c.strip() for c in os.environ.get("GOOGLE_CLIENT_IDS", "").split(",") if c.strip()]


def new_user_id():
    """Same shape as the legacy hostname-hash IDs, so existing tasks/crypto_devices
    rows keep working unmodified once claimed onto an account."""
    return uuid.uuid4().hex[:16]


def hash_password(password):
    return generate_password_hash(password)


def verify_password(password, password_hash):
    if not password_hash:
        return False
    return check_password_hash(password_hash, password)


def issue_access_token(user_id, email):
    now = int(time.time())
    payload = {
        "sub": user_id,
        "email": email,
        "iat": now,
        "exp": now + ACCESS_TOKEN_TTL_SECONDS,
        "type": "access",
    }
    return pyjwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGO)


def decode_access_token(token):
    """Returns claims dict, or raises jwt.PyJWTError on invalid/expired tokens."""
    return pyjwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGO])


def new_refresh_token():
    """Returns (plaintext_token, token_hash). Only the hash is ever stored."""
    plaintext = secrets.token_urlsafe(48)
    return plaintext, hash_token(plaintext)


def hash_token(plaintext):
    return hashlib.sha256(plaintext.encode("utf-8")).hexdigest()


def verify_google_id_token(id_token_str):
    """Verify a Google-issued ID token. Returns (google_sub, email, name) or raises ValueError."""
    if not GOOGLE_AUTH_AVAILABLE:
        raise ValueError("Google sign-in is not configured on this server")
    if not GOOGLE_CLIENT_IDS:
        raise ValueError("GOOGLE_CLIENT_IDS is not configured")
    try:
        info = google_id_token.verify_oauth2_token(id_token_str, google_requests.Request())
    except Exception as exc:
        raise ValueError(f"Invalid Google token: {exc}") from exc
    if info.get("aud") not in GOOGLE_CLIENT_IDS:
        raise ValueError("Google token was not issued for this app")
    if not info.get("email_verified", False):
        raise ValueError("Google account email is not verified")
    return info["sub"], info.get("email", ""), info.get("name", "")