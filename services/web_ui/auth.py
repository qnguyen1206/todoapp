"""
Authentication bridge for the Web UI Service.
The browser never sees a JWT — only an opaque Flask session cookie.
Access/refresh tokens live server-side in the session and are attached
to backend calls by app.py.
"""

import os
import time
import requests as req
from functools import wraps
from flask import Blueprint, request, jsonify, session, redirect, url_for, render_template

BACKEND_URL = os.getenv("BACKEND_URL", "http://backend:5000")
API_KEY = os.getenv("API_KEY", "")
GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID_WEB", "")

auth_bp = Blueprint("auth", __name__)


def _headers():
    h = {"Content-Type": "application/json"}
    if API_KEY:
        h["X-API-Key"] = API_KEY
    return h


def _backend_auth(method, path, **kwargs):
    kwargs.setdefault("headers", _headers())
    kwargs.setdefault("timeout", 15)
    return req.request(method, f"{BACKEND_URL}{path}", **kwargs)


def _store_session(payload):
    session["user_id"] = payload.get("user_id")
    session["email"] = payload.get("email")
    session["access_token"] = payload.get("access_token")
    session["refresh_token"] = payload.get("refresh_token")
    # 30s safety margin so we refresh slightly before actual expiry
    session["access_expires_at"] = time.time() + int(payload.get("expires_in", 900)) - 30
    session.permanent = True


def clear_session():
    for key in ("user_id", "email", "access_token", "refresh_token", "access_expires_at"):
        session.pop(key, None)


def current_user_id():
    return session.get("user_id")


def is_logged_in():
    return bool(session.get("user_id") and session.get("access_token"))


def _refresh_access_token():
    """Returns True if the session now has a live access token."""
    refresh_token = session.get("refresh_token")
    if not refresh_token:
        return False
    try:
        r = _backend_auth("POST", "/auth/refresh", json={"refresh_token": refresh_token})
    except Exception:
        return False
    if r.status_code != 200:
        clear_session()
        return False
    data = r.json()
    session["access_token"] = data.get("access_token")
    session["refresh_token"] = data.get("refresh_token")
    session["access_expires_at"] = time.time() + int(data.get("expires_in", 900)) - 30
    return True


def get_valid_access_token():
    """Returns a live access token, refreshing first if needed. None if login is required."""
    if not is_logged_in():
        return None
    if time.time() >= session.get("access_expires_at", 0):
        if not _refresh_access_token():
            return None
    return session.get("access_token")


def login_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if not is_logged_in() or get_valid_access_token() is None:
            if request.path.startswith("/api/"):
                return jsonify({"status": "error", "message": "Not logged in"}), 401
            return redirect(url_for("auth.login_page"))
        return f(*args, **kwargs)
    return wrapper


# ---------------------------------------------------------------------------
# Page routes
# ---------------------------------------------------------------------------

@auth_bp.route("/login", methods=["GET"])
def login_page():
    if is_logged_in():
        return redirect(url_for("index"))
    return render_template("login.html", google_client_id=GOOGLE_CLIENT_ID)


@auth_bp.route("/logout", methods=["POST"])
def logout_page():
    refresh_token = session.get("refresh_token")
    if refresh_token:
        try:
            _backend_auth("POST", "/auth/logout", json={"refresh_token": refresh_token})
        except Exception:
            pass
    clear_session()
    return redirect(url_for("auth.login_page"))


# ---------------------------------------------------------------------------
# JSON endpoints consumed by login.html's JS
# ---------------------------------------------------------------------------

def _proxy_and_store(path, data):
    try:
        r = _backend_auth("POST", path, json=data)
    except req.exceptions.RequestException:
        return jsonify({"status": "error", "message": "Backend service unavailable"}), 503
    if r.status_code in (200, 201):
        _store_session(r.json())
        return jsonify({"status": "success"})
    try:
        return jsonify(r.json()), r.status_code
    except Exception:
        return jsonify({"status": "error", "message": "Unexpected backend response"}), 502


@auth_bp.route("/api/auth/register", methods=["POST"])
def api_register():
    return _proxy_and_store("/auth/register", request.get_json(silent=True) or {})


@auth_bp.route("/api/auth/login", methods=["POST"])
def api_login():
    return _proxy_and_store("/auth/login", request.get_json(silent=True) or {})


@auth_bp.route("/api/auth/verify-email", methods=["POST"])
def api_verify_email():
    return _proxy_and_store("/auth/verify-email", request.get_json(silent=True) or {})


@auth_bp.route("/api/auth/google", methods=["POST"])
def api_google_login():
    return _proxy_and_store("/auth/google", request.get_json(silent=True) or {})


@auth_bp.route("/api/auth/password-reset/request", methods=["POST"])
def api_password_reset_request():
    try:
        r = _backend_auth("POST", "/auth/password-reset/request", json=request.get_json(silent=True) or {})
    except req.exceptions.ConnectionError:
        return jsonify({"status": "error", "message": "Backend service unavailable"}), 503
    return jsonify(r.json()), r.status_code


@auth_bp.route("/api/auth/password-reset/confirm", methods=["POST"])
def api_password_reset_confirm():
    try:
        r = _backend_auth("POST", "/auth/password-reset/confirm", json=request.get_json(silent=True) or {})
    except req.exceptions.ConnectionError:
        return jsonify({"status": "error", "message": "Backend service unavailable"}), 503
    return jsonify(r.json()), r.status_code


@auth_bp.route("/api/auth/me", methods=["GET"])
@login_required
def api_me():
    return jsonify({"status": "success", "user_id": session.get("user_id"), "email": session.get("email")})
