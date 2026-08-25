"""
Backend Storage Service for TODO App CVM
Handles encrypted task storage, retrieval, and sync via PostgreSQL.
"""

import json
import os
import logging
import re
import base64
from datetime import datetime, timezone

from flask import Flask, request, jsonify, g
from flask_cors import CORS
import psycopg2
import psycopg2.extras
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec, utils

import secrets
import smtplib
import requests as http_requests
from email.mime.text import MIMEText
from functools import wraps

import auth as auth_lib

logging.basicConfig(level=os.getenv("LOG_LEVEL", "info").upper())
log = logging.getLogger(__name__)

app = Flask(__name__)
CORS(app)

DATABASE_URL = os.environ.get("DATABASE_URL", "")
API_KEY = os.environ.get("API_KEY", "")

DEVICE_ID_RE = re.compile(r"^[A-Za-z0-9_-]{8,128}$")
KEY_WRAP_INFO = "todoapp-keywrap-v1"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def get_db():
    conn = psycopg2.connect(DATABASE_URL)
    conn.autocommit = False
    return conn


def require_api_key():
    """Return error response if API key invalid, else None."""
    if not API_KEY:
        return None  # no key configured → open (dev mode)
    key = request.headers.get("X-API-Key") or request.args.get("api_key")
    if key != API_KEY:
        return jsonify({"status": "error", "message": "Unauthorized"}), 401
    return None

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def require_auth(f):
    """Derive g.user_id from a verified JWT. This is what makes sync per-user
    instead of per-anyone-with-the-API-key."""
    @wraps(f)
    def wrapper(*args, **kwargs):
        header = request.headers.get("Authorization", "")
        if not header.startswith("Bearer "):
            return jsonify({"status": "error", "message": "Missing or invalid Authorization header"}), 401
        token = header[len("Bearer "):].strip()
        try:
            claims = auth_lib.decode_access_token(token)
        except Exception:
            return jsonify({"status": "error", "message": "Invalid or expired access token"}), 401
        g.user_id = claims["sub"]
        g.user_email = claims.get("email", "")
        return f(*args, **kwargs)
    return wrapper


def _issue_token_pair(conn, user_id, email):
    access = auth_lib.issue_access_token(user_id, email)
    plaintext_refresh, refresh_hash = auth_lib.new_refresh_token()
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO refresh_tokens (token_hash, user_id, expires_at) "
            "VALUES (%s, %s, NOW() + (%s || ' seconds')::interval)",
            (refresh_hash, user_id, auth_lib.REFRESH_TOKEN_TTL_SECONDS),
        )
    return access, plaintext_refresh


def _send_password_reset_email(email, token):
    reset_base_url = os.environ.get("PASSWORD_RESET_URL", "")  # e.g. web_ui's /reset-password page
    link = f"{reset_base_url}?token={token}" if reset_base_url else f"(no PASSWORD_RESET_URL set — token: {token})"
    if os.environ.get("SMTP_ENABLED", "false").lower() != "true":
        log.info("SMTP disabled — password reset link for %s: %s", email, link)
        return
    try:
        msg = MIMEText(f"Reset your TODO App password:\n\n{link}\n\nThis link expires in 1 hour.")
        msg["Subject"] = "Reset your TODO App password"
        msg["From"] = os.environ.get("SMTP_USER", "")
        msg["To"] = email
        with smtplib.SMTP(os.environ.get("SMTP_HOST", ""), int(os.environ.get("SMTP_PORT", "587"))) as server:
            server.starttls()
            server.login(os.environ.get("SMTP_USER", ""), os.environ.get("SMTP_PASSWORD", ""))
            server.sendmail(msg["From"], [email], msg.as_string())
    except Exception as exc:
        log.error("Failed to send password reset email: %s", exc)


def _send_verification_code(email, code):
    """Send a short-lived account-verification code through the configured SMTP account."""
    if os.environ.get("SMTP_ENABLED", "false").lower() != "true":
        log.warning("SMTP is disabled; cannot deliver verification email to %s", email)
        return False
    try:
        msg = MIMEText(f"Your TODO App verification code is: {code}\n\nIt expires in 15 minutes.")
        msg["Subject"] = "Verify your TODO App account"
        msg["From"] = os.environ.get("SMTP_USER", "")
        msg["To"] = email
        with smtplib.SMTP(os.environ.get("SMTP_HOST", ""), int(os.environ.get("SMTP_PORT", "587"))) as server:
            server.starttls()
            server.login(os.environ.get("SMTP_USER", ""), os.environ.get("SMTP_PASSWORD", ""))
            server.sendmail(msg["From"], [email], msg.as_string())
        return True
    except Exception as exc:
        log.error("Failed to send verification email: %s", exc)
        return False


def _create_verification_code(conn, user_id):
    code = f"{secrets.randbelow(1_000_000):06d}"
    with conn.cursor() as cur:
        cur.execute("DELETE FROM email_verifications WHERE user_id = %s", (user_id,))
        cur.execute(
            "INSERT INTO email_verifications (code_hash, user_id, expires_at) "
            "VALUES (%s, %s, NOW() + INTERVAL '15 minutes')",
            (auth_lib.hash_token(code), user_id),
        )
    return code


@app.route("/auth/register", methods=["POST"])
def register():
    data = request.get_json(silent=True) or {}
    email = (data.get("email") or "").strip().lower()
    password = data.get("password") or ""
    display_name = (data.get("display_name") or "").strip()[:80]

    if not EMAIL_RE.match(email):
        return jsonify({"status": "error", "message": "Valid email required"}), 400
    if len(password) < 8:
        return jsonify({"status": "error", "message": "Password must be at least 8 characters"}), 400

    conn = get_db()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT id, email_verified FROM users WHERE email = %s", (email,))
            existing = cur.fetchone()
            if existing and existing[1]:
                return jsonify({"status": "error", "message": "An account with this email already exists"}), 409
            if existing:
                user_id = existing[0]
                cur.execute("UPDATE users SET password_hash = %s, display_name = %s WHERE id = %s",
                            (auth_lib.hash_password(password), display_name, user_id))
            else:
                user_id = auth_lib.new_user_id()
                cur.execute(
                    "INSERT INTO users (id, email, password_hash, display_name, email_verified) VALUES (%s, %s, %s, %s, FALSE)",
                    (user_id, email, auth_lib.hash_password(password), display_name),
                )
            code = _create_verification_code(conn, user_id)
        conn.commit()
        if not _send_verification_code(email, code):
            return jsonify({"status": "error", "message": "Could not send verification email. Please try again later."}), 503
        return jsonify({"status": "verification_required", "email": email, "message": "A verification code was sent to your email."}), 202
    except Exception as exc:
        conn.rollback()
        log.error("register error: %s", exc)
        return jsonify({"status": "error", "message": "Could not create account"}), 500
    finally:
        conn.close()


@app.route("/auth/login", methods=["POST"])
def login():
    data = request.get_json(silent=True) or {}
    email = (data.get("email") or "").strip().lower()
    password = data.get("password") or ""

    conn = get_db()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("SELECT id, email, password_hash, email_verified FROM users WHERE email = %s", (email,))
            user = cur.fetchone()
        if not user or not auth_lib.verify_password(password, user["password_hash"]):
            return jsonify({"status": "error", "message": "Incorrect email or password"}), 401
        if not user["email_verified"]:
            return jsonify({"status": "verification_required", "message": "Verify your email before signing in."}), 403

        access, refresh = _issue_token_pair(conn, user["id"], user["email"])
        conn.commit()
        return jsonify({
            "status": "success", "user_id": user["id"], "email": user["email"],
            "access_token": access, "refresh_token": refresh,
            "expires_in": auth_lib.ACCESS_TOKEN_TTL_SECONDS,
        })
    except Exception as exc:
        conn.rollback()
        log.error("login error: %s", exc)
        return jsonify({"status": "error", "message": "Login failed"}), 500
    finally:
        conn.close()


@app.route("/auth/verify-email", methods=["POST"])
def verify_email():
    data = request.get_json(silent=True) or {}
    email = (data.get("email") or "").strip().lower()
    code = (data.get("code") or "").strip()
    if not EMAIL_RE.match(email) or not code.isdigit() or len(code) != 6:
        return jsonify({"status": "error", "message": "Email and six-digit code are required"}), 400
    conn = get_db()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("SELECT id, email_verified FROM users WHERE email = %s", (email,))
            user = cur.fetchone()
            if not user:
                return jsonify({"status": "error", "message": "Invalid verification code"}), 400
            if user["email_verified"]:
                return jsonify({"status": "error", "message": "Email is already verified; sign in instead."}), 400
            cur.execute("SELECT code_hash FROM email_verifications WHERE user_id = %s AND expires_at > NOW()", (user["id"],))
            verification = cur.fetchone()
            if not verification or not secrets.compare_digest(verification["code_hash"], auth_lib.hash_token(code)):
                return jsonify({"status": "error", "message": "Invalid or expired verification code"}), 400
            cur.execute("UPDATE users SET email_verified = TRUE WHERE id = %s", (user["id"],))
            cur.execute("DELETE FROM email_verifications WHERE user_id = %s", (user["id"],))
            access, refresh = _issue_token_pair(conn, user["id"], email)
        conn.commit()
        return jsonify({"status": "success", "user_id": user["id"], "email": email,
                        "access_token": access, "refresh_token": refresh,
                        "expires_in": auth_lib.ACCESS_TOKEN_TTL_SECONDS})
    except Exception as exc:
        conn.rollback(); log.error("verify_email error: %s", exc)
        return jsonify({"status": "error", "message": "Could not verify email"}), 500
    finally:
        conn.close()


@app.route("/auth/google", methods=["POST"])
def google_login():
    return _google_login_from_data(request.get_json(silent=True) or {})


def _google_login_from_data(data):
    """Verify a Google ID token and create/link the corresponding TODO account."""
    try:
        google_sub, email, name = auth_lib.verify_google_id_token(data.get("id_token") or "")
    except ValueError as exc:
        return jsonify({"status": "error", "message": str(exc)}), 401

    conn = get_db()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("SELECT id, email FROM users WHERE google_sub = %s", (google_sub,))
            user = cur.fetchone()
            if not user:
                # Link to an existing password account with the same email, else create new.
                cur.execute("SELECT id, email FROM users WHERE email = %s", (email,))
                existing = cur.fetchone()
                if existing:
                    cur.execute("UPDATE users SET google_sub = %s WHERE id = %s", (google_sub, existing["id"]))
                    user = existing
                else:
                    user_id = auth_lib.new_user_id()
                    cur.execute(
                        "INSERT INTO users (id, email, google_sub, display_name) VALUES (%s, %s, %s, %s)",
                        (user_id, email, google_sub, name[:80]),
                    )
                    user = {"id": user_id, "email": email}

            access, refresh = _issue_token_pair(conn, user["id"], user["email"])
        conn.commit()
        return jsonify({
            "status": "success", "user_id": user["id"], "email": user["email"],
            "access_token": access, "refresh_token": refresh,
            "expires_in": auth_lib.ACCESS_TOKEN_TTL_SECONDS,
        })
    except Exception as exc:
        conn.rollback()
        log.error("google_login error: %s", exc)
        return jsonify({"status": "error", "message": "Google sign-in failed"}), 500
    finally:
        conn.close()


@app.route("/auth/google/desktop", methods=["POST"])
def google_desktop_login():
    """Exchange an OAuth authorization code from the desktop loopback flow.

    The desktop never stores a Google client secret; it supplies a PKCE verifier,
    and this service issues the application's ordinary session tokens.
    """
    data = request.get_json(silent=True) or {}
    code = data.get("code") or ""
    verifier = data.get("code_verifier") or ""
    redirect_uri = data.get("redirect_uri") or ""
    client_id = data.get("client_id") or ""
    if not code or not verifier or not redirect_uri or client_id not in auth_lib.GOOGLE_CLIENT_IDS:
        return jsonify({"status": "error", "message": "Invalid desktop Google sign-in request"}), 400
    try:
        token_response = http_requests.post(
            "https://oauth2.googleapis.com/token",
            data={"code": code, "client_id": client_id, "redirect_uri": redirect_uri,
                  "grant_type": "authorization_code", "code_verifier": verifier},
            timeout=15,
        )
        token_data = token_response.json()
        if token_response.status_code != 200 or not token_data.get("id_token"):
            return jsonify({"status": "error", "message": "Google authorization could not be completed"}), 401
        data["id_token"] = token_data["id_token"]
    except (ValueError, http_requests.RequestException):
        return jsonify({"status": "error", "message": "Could not contact Google"}), 503
    # Reuse the same verified-ID-token account-linking flow as the web client.
    return _google_login_from_data(data)


@app.route("/auth/refresh", methods=["POST"])
def refresh_token():
    data = request.get_json(silent=True) or {}
    plaintext = data.get("refresh_token") or ""
    if not plaintext:
        return jsonify({"status": "error", "message": "refresh_token required"}), 400
    token_hash = auth_lib.hash_token(plaintext)

    conn = get_db()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                "SELECT rt.user_id, u.email FROM refresh_tokens rt "
                "JOIN users u ON u.id = rt.user_id "
                "WHERE rt.token_hash = %s AND rt.revoked = FALSE AND rt.expires_at > NOW()",
                (token_hash,),
            )
            row = cur.fetchone()
            if not row:
                return jsonify({"status": "error", "message": "Session expired — please log in again"}), 401

            cur.execute("UPDATE refresh_tokens SET revoked = TRUE WHERE token_hash = %s", (token_hash,))
            access, new_refresh = _issue_token_pair(conn, row["user_id"], row["email"])
        conn.commit()
        return jsonify({
            "status": "success", "access_token": access, "refresh_token": new_refresh,
            "expires_in": auth_lib.ACCESS_TOKEN_TTL_SECONDS,
        })
    except Exception as exc:
        conn.rollback()
        log.error("refresh_token error: %s", exc)
        return jsonify({"status": "error", "message": "Could not refresh session"}), 500
    finally:
        conn.close()


@app.route("/auth/logout", methods=["POST"])
def logout():
    data = request.get_json(silent=True) or {}
    plaintext = data.get("refresh_token") or ""
    if plaintext:
        conn = get_db()
        try:
            with conn.cursor() as cur:
                cur.execute("UPDATE refresh_tokens SET revoked = TRUE WHERE token_hash = %s",
                            (auth_lib.hash_token(plaintext),))
            conn.commit()
        except Exception:
            conn.rollback()
        finally:
            conn.close()
    return jsonify({"status": "success"})


@app.route("/auth/me", methods=["GET"])
@require_auth
def me():
    return jsonify({"status": "success", "user_id": g.user_id, "email": g.user_email})


@app.route("/auth/password-reset/request", methods=["POST"])
def password_reset_request():
    email = ((request.get_json(silent=True) or {}).get("email") or "").strip().lower()
    conn = get_db()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("SELECT id FROM users WHERE email = %s", (email,))
            user = cur.fetchone()
            if user:
                plaintext = secrets.token_urlsafe(32)
                cur.execute(
                    "INSERT INTO password_resets (token_hash, user_id, expires_at) "
                    "VALUES (%s, %s, NOW() + INTERVAL '1 hour')",
                    (auth_lib.hash_token(plaintext), user["id"]),
                )
                conn.commit()
                _send_password_reset_email(email, plaintext)
        return jsonify({"status": "success", "message": "If that email exists, a reset link has been sent."})
    except Exception as exc:
        conn.rollback()
        log.error("password_reset_request error: %s", exc)
        return jsonify({"status": "success", "message": "If that email exists, a reset link has been sent."})
    finally:
        conn.close()


@app.route("/auth/password-reset/confirm", methods=["POST"])
def password_reset_confirm():
    data = request.get_json(silent=True) or {}
    plaintext = data.get("token") or ""
    new_password = data.get("password") or ""
    if len(new_password) < 8:
        return jsonify({"status": "error", "message": "Password must be at least 8 characters"}), 400

    conn = get_db()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            token_hash = auth_lib.hash_token(plaintext)
            cur.execute(
                "SELECT user_id FROM password_resets WHERE token_hash = %s AND used = FALSE AND expires_at > NOW()",
                (token_hash,),
            )
            row = cur.fetchone()
            if not row:
                return jsonify({"status": "error", "message": "Reset link is invalid or expired"}), 400

            cur.execute("UPDATE users SET password_hash = %s WHERE id = %s",
                        (auth_lib.hash_password(new_password), row["user_id"]))
            cur.execute("UPDATE password_resets SET used = TRUE WHERE token_hash = %s", (token_hash,))
            cur.execute("UPDATE refresh_tokens SET revoked = TRUE WHERE user_id = %s", (row["user_id"],))
        conn.commit()
        return jsonify({"status": "success"})
    except Exception as exc:
        conn.rollback()
        log.error("password_reset_confirm error: %s", exc)
        return jsonify({"status": "error", "message": "Could not reset password"}), 500
    finally:
        conn.close()


def _b64url_decode(value):
    """Decode a URL-safe Base64 string used by the client crypto protocol."""
    if not isinstance(value, str):
        raise ValueError("Expected Base64 string")
    try:
        return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))
    except (ValueError, TypeError) as exc:
        raise ValueError("Invalid Base64 value") from exc


def _validate_public_key(value, field_name):
    """Validate a P-256 point without retaining or deriving any secret."""
    try:
        raw = _b64url_decode(value)
        if len(raw) != 65:
            raise ValueError("Unexpected key length")
        ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), raw)
    except ValueError as exc:
        raise ValueError(f"Invalid {field_name}") from exc


def _validate_wrapped_workspace_key(value):
    """Perform structural validation on an opaque client-side key envelope."""
    if not isinstance(value, dict) or value.get("v") != 1:
        raise ValueError("Invalid wrapped_workspace_key")
    required = ("ephemeral_public_key", "salt", "nonce", "ciphertext")
    if any(not isinstance(value.get(key), str) for key in required):
        raise ValueError("Invalid wrapped_workspace_key")
    _validate_public_key(value["ephemeral_public_key"], "ephemeral public key")
    if len(_b64url_decode(value["salt"])) != 16:
        raise ValueError("Invalid wrapped_workspace_key salt")
    if len(_b64url_decode(value["nonce"])) != 12:
        raise ValueError("Invalid wrapped_workspace_key nonce")
    if len(_b64url_decode(value["ciphertext"])) < 48:  # 32-byte key + 16-byte GCM tag
        raise ValueError("Invalid wrapped_workspace_key ciphertext")


def _device_record(row):
    """Convert a PostgreSQL crypto-device row into a JSON-safe object."""
    result = dict(row)
    for key in ("created_at", "approved_at"):
        if result.get(key):
            result[key] = result[key].isoformat()
    return result


def _approval_payload(user_id, device_id, encryption_public_key, signing_public_key, wrapped_workspace_key):
    """The canonical approval payload shared by the Python and browser clients."""
    return json.dumps(
        {
            "device_id": device_id,
            "encryption_public_key": encryption_public_key,
            "signing_public_key": signing_public_key,
            "user_id": user_id,
            "wrapped_workspace_key": wrapped_workspace_key,
        },
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")


def _verify_approval_signature(public_key_text, payload, signature_text, signature_format):
    """Verify a P-256 signature made by an already-approved device."""
    try:
        public_key = ec.EllipticCurvePublicKey.from_encoded_point(
            ec.SECP256R1(), _b64url_decode(public_key_text)
        )
        signature = _b64url_decode(signature_text)
        if signature_format == "raw":
            if len(signature) != 64:
                return False
            signature = utils.encode_dss_signature(
                int.from_bytes(signature[:32], "big"),
                int.from_bytes(signature[32:], "big"),
            )
        elif signature_format != "der":
            return False
        public_key.verify(signature, payload, ec.ECDSA(hashes.SHA256()))
        return True
    except (InvalidSignature, ValueError, TypeError):
        return False


def init_db():
    conn = get_db()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS tasks (
                    id          SERIAL PRIMARY KEY,
                    user_id     TEXT        NOT NULL,
                    task_id     TEXT        NOT NULL,
                    title       TEXT        NOT NULL,
                    due_date    TEXT,
                    due_time    TEXT,
                    priority    INTEGER     DEFAULT 1,
                    notes       TEXT        DEFAULT '',
                    completed   BOOLEAN     DEFAULT FALSE,
                    updated_at  TIMESTAMPTZ DEFAULT NOW(),
                    UNIQUE (user_id, task_id)
                );
                CREATE INDEX IF NOT EXISTS idx_tasks_user ON tasks(user_id);

                -- A workspace row establishes trust-on-first-use for a user ID.
                -- The server never stores a private key or plaintext workspace key.
                CREATE TABLE IF NOT EXISTS crypto_workspaces (
                    user_id         TEXT PRIMARY KEY,
                    initialized_at  TIMESTAMPTZ DEFAULT NOW()
                );

                CREATE TABLE IF NOT EXISTS crypto_devices (
                    user_id                TEXT        NOT NULL,
                    device_id              TEXT        NOT NULL,
                    encryption_public_key  TEXT        NOT NULL,
                    signing_public_key     TEXT        NOT NULL,
                    wrapped_workspace_key  JSONB,
                    status                 TEXT        NOT NULL DEFAULT 'pending',
                    approved_by            TEXT,
                    created_at             TIMESTAMPTZ DEFAULT NOW(),
                    approved_at            TIMESTAMPTZ,
                    PRIMARY KEY (user_id, device_id),
                    CHECK (status IN ('pending', 'active'))
                );
                CREATE INDEX IF NOT EXISTS idx_crypto_devices_user_status
                    ON crypto_devices(user_id, status);
                
                CREATE TABLE IF NOT EXISTS users (
                    id             TEXT PRIMARY KEY,
                    email          TEXT UNIQUE NOT NULL,
                    password_hash  TEXT,
                    google_sub     TEXT UNIQUE,
                    display_name   TEXT,
                    email_verified BOOLEAN,
                    created_at     TIMESTAMPTZ DEFAULT NOW()
                );

                CREATE TABLE IF NOT EXISTS refresh_tokens (
                    token_hash   TEXT PRIMARY KEY,
                    user_id      TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    created_at   TIMESTAMPTZ DEFAULT NOW(),
                    expires_at   TIMESTAMPTZ NOT NULL,
                    revoked      BOOLEAN DEFAULT FALSE
                );
                CREATE INDEX IF NOT EXISTS idx_refresh_user ON refresh_tokens(user_id);

                CREATE TABLE IF NOT EXISTS password_resets (
                    token_hash  TEXT PRIMARY KEY,
                    user_id     TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    expires_at  TIMESTAMPTZ NOT NULL,
                    used        BOOLEAN DEFAULT FALSE
                );

                CREATE TABLE IF NOT EXISTS email_verifications (
                    code_hash   TEXT PRIMARY KEY,
                    user_id     TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    expires_at  TIMESTAMPTZ NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_email_verifications_user ON email_verifications(user_id);

                -- Existing accounts predate verification, so preserve their ability to sign in.
                -- New registrations explicitly start with FALSE and must verify a code.
                ALTER TABLE users ADD COLUMN IF NOT EXISTS email_verified BOOLEAN;
                UPDATE users SET email_verified = TRUE WHERE email_verified IS NULL;
                ALTER TABLE users ALTER COLUMN email_verified SET DEFAULT FALSE;
                ALTER TABLE users ALTER COLUMN email_verified SET NOT NULL;
            """)
        conn.commit()
        log.info("Database initialised")
    except Exception as exc:
        conn.rollback()
        log.exception("DB init error: %s", exc)
        raise
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.route("/health", methods=["GET"])
def health():
    try:
        conn = get_db()
        conn.close()
        return jsonify({"status": "ok", "service": "backend", "timestamp": datetime.now(timezone.utc).isoformat()})
    except Exception as exc:
        return jsonify({"status": "error", "message": str(exc)}), 503


# ---------------------------------------------------------------------------
# Client-side encryption device registry
# ---------------------------------------------------------------------------

@app.route("/crypto/devices", methods=["GET"])
@require_auth
def list_crypto_devices():
    """List public device records and each device's encrypted key envelope."""
    err = require_api_key()
    if err:
        return err

    user_id = g.user_id
    if not user_id:
        return jsonify({"status": "error", "message": "user_id required"}), 400

    conn = get_db()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                """
                SELECT device_id, encryption_public_key, signing_public_key,
                       wrapped_workspace_key, status, approved_by, created_at, approved_at
                FROM crypto_devices
                WHERE user_id = %s
                ORDER BY created_at ASC
                """,
                (user_id,),
            )
            devices = [_device_record(row) for row in cur.fetchall()]
        return jsonify({"status": "success", "devices": devices})
    except Exception as exc:
        log.error("list_crypto_devices error: %s", exc)
        return jsonify({"status": "error", "message": str(exc)}), 500
    finally:
        conn.close()


@app.route("/crypto/devices/register", methods=["POST"])
@require_auth
def register_crypto_device():
    """Register a device public key.  Only the first device becomes active."""
    err = require_api_key()
    if err:
        return err

    data = request.get_json(silent=True) or {}
    user_id = g.user_id
    device_id = str(data.get("device_id") or "").strip()
    encryption_public_key = data.get("encryption_public_key")
    signing_public_key = data.get("signing_public_key")
    wrapped_workspace_key = data.get("wrapped_workspace_key")

    if not user_id:
        return jsonify({"status": "error", "message": "user_id required"}), 400
    if not DEVICE_ID_RE.fullmatch(device_id):
        return jsonify({"status": "error", "message": "invalid device_id"}), 400
    try:
        _validate_public_key(encryption_public_key, "encryption public key")
        _validate_public_key(signing_public_key, "signing public key")
    except ValueError as exc:
        return jsonify({"status": "error", "message": str(exc)}), 400

    conn = get_db()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            # The successful insert establishes this user ID's first trusted device.
            cur.execute(
                "INSERT INTO crypto_workspaces (user_id) VALUES (%s) "
                "ON CONFLICT (user_id) DO NOTHING RETURNING user_id",
                (user_id,),
            )
            is_first_device = cur.fetchone() is not None
            if is_first_device:
                try:
                    _validate_wrapped_workspace_key(wrapped_workspace_key)
                except ValueError as exc:
                    raise ValueError(
                        "The first device must provide a valid wrapped_workspace_key"
                    ) from exc

            status = "active" if is_first_device else "pending"
            approved_at = "NOW()" if is_first_device else "NULL"
            # approved_at is deliberately expressed in SQL only, never supplied by a client.
            cur.execute(
                f"""
                INSERT INTO crypto_devices
                    (user_id, device_id, encryption_public_key, signing_public_key,
                     wrapped_workspace_key, status, approved_at)
                VALUES (%s, %s, %s, %s, %s, %s, {approved_at})
                RETURNING device_id, encryption_public_key, signing_public_key,
                          wrapped_workspace_key, status, approved_by, created_at, approved_at
                """,
                (
                    user_id,
                    device_id,
                    encryption_public_key,
                    signing_public_key,
                    psycopg2.extras.Json(wrapped_workspace_key) if is_first_device else None,
                    status,
                ),
            )
            device = _device_record(cur.fetchone())
        conn.commit()
        return jsonify({"status": "success", "device": device}), 201
    except ValueError as exc:
        conn.rollback()
        return jsonify({"status": "error", "message": str(exc)}), 400
    except psycopg2.IntegrityError:
        conn.rollback()
        return jsonify({"status": "error", "message": "device_id already registered"}), 409
    except Exception as exc:
        conn.rollback()
        log.error("register_crypto_device error: %s", exc)
        return jsonify({"status": "error", "message": str(exc)}), 500
    finally:
        conn.close()


@app.route("/crypto/devices/<device_id>/approve", methods=["POST"])
@require_auth
def approve_crypto_device(device_id):
    """Activate a pending device after an active device signs its key envelope."""
    err = require_api_key()
    if err:
        return err

    data = request.get_json(silent=True) or {}
    user_id = g.user_id
    approver_device_id = str(data.get("approver_device_id") or "").strip()
    wrapped_workspace_key = data.get("wrapped_workspace_key")
    signature = data.get("signature")
    signature_format = data.get("signature_format", "der")

    if not user_id:
        return jsonify({"status": "error", "message": "user_id required"}), 400
    if not DEVICE_ID_RE.fullmatch(device_id) or not DEVICE_ID_RE.fullmatch(approver_device_id):
        return jsonify({"status": "error", "message": "invalid device_id"}), 400
    if device_id == approver_device_id:
        return jsonify({"status": "error", "message": "a device cannot approve itself"}), 400
    try:
        _validate_wrapped_workspace_key(wrapped_workspace_key)
    except ValueError as exc:
        return jsonify({"status": "error", "message": str(exc)}), 400

    conn = get_db()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            # Lock in a stable order so concurrent approvals cannot deadlock.
            cur.execute(
                """
                SELECT device_id, encryption_public_key, signing_public_key, status
                FROM crypto_devices
                WHERE user_id = %s AND device_id = ANY(%s)
                ORDER BY device_id
                FOR UPDATE
                """,
                (user_id, [device_id, approver_device_id]),
            )
            records = {row["device_id"]: dict(row) for row in cur.fetchall()}
            target = records.get(device_id)
            approver = records.get(approver_device_id)
            if not target or not approver:
                return jsonify({"status": "error", "message": "device not found"}), 404
            if target["status"] != "pending":
                return jsonify({"status": "error", "message": "device is not pending approval"}), 409
            if approver["status"] != "active":
                return jsonify({"status": "error", "message": "approver is not active"}), 403

            payload = _approval_payload(
                user_id,
                device_id,
                target["encryption_public_key"],
                target["signing_public_key"],
                wrapped_workspace_key,
            )
            if not _verify_approval_signature(
                approver["signing_public_key"], payload, signature, signature_format
            ):
                return jsonify({"status": "error", "message": "invalid approval signature"}), 403

            cur.execute(
                """
                UPDATE crypto_devices
                SET wrapped_workspace_key = %s,
                    status = 'active',
                    approved_by = %s,
                    approved_at = NOW()
                WHERE user_id = %s AND device_id = %s
                RETURNING device_id, encryption_public_key, signing_public_key,
                          wrapped_workspace_key, status, approved_by, created_at, approved_at
                """,
                (
                    psycopg2.extras.Json(wrapped_workspace_key),
                    approver_device_id,
                    user_id,
                    device_id,
                ),
            )
            device = _device_record(cur.fetchone())
        conn.commit()
        return jsonify({"status": "success", "device": device})
    except Exception as exc:
        conn.rollback()
        log.error("approve_crypto_device error: %s", exc)
        return jsonify({"status": "error", "message": str(exc)}), 500
    finally:
        conn.close()


@app.route("/tasks/store", methods=["POST"])
@require_auth
def store_tasks():
    """Upsert a list of tasks for a user."""
    err = require_api_key()
    if err:
        return err

    data = request.get_json(silent=True) or {}
    user_id = g.user_id
    tasks = data.get("tasks", [])

    if not user_id:
        return jsonify({"status": "error", "message": "user_id required"}), 400

    conn = get_db()
    try:
        with conn.cursor() as cur:
            for task in tasks:
                cur.execute("""
                    INSERT INTO tasks (user_id, task_id, title, due_date, due_time, priority, notes, completed, updated_at)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, NOW())
                    ON CONFLICT (user_id, task_id) DO UPDATE SET
                        title      = EXCLUDED.title,
                        due_date   = EXCLUDED.due_date,
                        due_time   = EXCLUDED.due_time,
                        priority   = EXCLUDED.priority,
                        notes      = EXCLUDED.notes,
                        completed  = EXCLUDED.completed,
                        updated_at = NOW()
                """, (
                    user_id,
                    str(task.get("id", "")),
                    task.get("title", ""),
                    task.get("due_date"),
                    task.get("due_time"),
                    int(task.get("priority", 1)),
                    task.get("notes", ""),
                    bool(task.get("completed", False)),
                ))
        conn.commit()
        return jsonify({"status": "success", "stored": len(tasks)})
    except Exception as exc:
        conn.rollback()
        log.error("store_tasks error: %s", exc)
        return jsonify({"status": "error", "message": str(exc)}), 500
    finally:
        conn.close()


@app.route("/tasks/retrieve", methods=["GET"])
@require_auth
def retrieve_tasks():
    """Return all tasks for a user."""
    err = require_api_key()
    if err:
        return err

    user_id = g.user_id
    if not user_id:
        return jsonify({"status": "error", "message": "user_id required"}), 400

    conn = get_db()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("""
                SELECT task_id, title, due_date, due_time, priority, notes, completed, updated_at
                FROM tasks
                WHERE user_id = %s
                ORDER BY updated_at DESC
            """, (user_id,))
            rows = cur.fetchall()
        tasks = [dict(r) for r in rows]
        for t in tasks:
            if t.get("updated_at"):
                t["updated_at"] = t["updated_at"].isoformat()
        return jsonify({"status": "success", "tasks": tasks})
    except Exception as exc:
        log.error("retrieve_tasks error: %s", exc)
        return jsonify({"status": "error", "message": str(exc)}), 500
    finally:
        conn.close()


@app.route("/tasks/sync", methods=["POST"])
@require_auth
def sync_tasks():
    """Merge local tasks with server; return the unified list."""
    err = require_api_key()
    if err:
        return err

    data = request.get_json(silent=True) or {}
    user_id = g.user_id
    local_tasks = data.get("local_tasks", [])

    if not user_id:
        return jsonify({"status": "error", "message": "user_id required"}), 400

    conn = get_db()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            # Upsert all incoming local tasks
            for task in local_tasks:
                cur.execute("""
                    INSERT INTO tasks (user_id, task_id, title, due_date, due_time, priority, notes, completed, updated_at)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, NOW())
                    ON CONFLICT (user_id, task_id) DO UPDATE SET
                        title      = EXCLUDED.title,
                        due_date   = EXCLUDED.due_date,
                        due_time   = EXCLUDED.due_time,
                        priority   = EXCLUDED.priority,
                        notes      = EXCLUDED.notes,
                        completed  = EXCLUDED.completed,
                        updated_at = NOW()
                """, (
                    user_id,
                    str(task.get("id", "")),
                    task.get("title", ""),
                    task.get("due_date"),
                    task.get("due_time"),
                    int(task.get("priority", 1)),
                    task.get("notes", ""),
                    bool(task.get("completed", False)),
                ))
            # Return the full merged list
            cur.execute("""
                SELECT task_id AS id, title, due_date, due_time, priority, notes, completed, updated_at
                FROM tasks WHERE user_id = %s ORDER BY due_date, priority
            """, (user_id,))
            rows = cur.fetchall()
        conn.commit()
        synced = [dict(r) for r in rows]
        for t in synced:
            if t.get("updated_at"):
                t["updated_at"] = t["updated_at"].isoformat()
        return jsonify({"status": "success", "synced_tasks": synced})
    except Exception as exc:
        conn.rollback()
        log.error("sync_tasks error: %s", exc)
        return jsonify({"status": "error", "message": str(exc)}), 500
    finally:
        conn.close()


@app.route("/tasks/<task_id>", methods=["DELETE"])
@require_auth
def delete_task(task_id):
    """Delete a specific task for a user."""
    err = require_api_key()
    if err:
        return err

    user_id = g.user_id
    if not user_id:
        return jsonify({"status": "error", "message": "user_id required"}), 400

    conn = get_db()
    try:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM tasks WHERE user_id = %s AND task_id = %s", (user_id, task_id))
            deleted = cur.rowcount
        conn.commit()
        return jsonify({"status": "success", "deleted": deleted})
    except Exception as exc:
        conn.rollback()
        return jsonify({"status": "error", "message": str(exc)}), 500
    finally:
        conn.close()


@app.route("/tasks/replace", methods=["POST"])
@require_auth
def replace_tasks():
    """Delete ALL existing tasks for a user then insert the provided list.
    This is the force-push / overwrite operation."""
    err = require_api_key()
    if err:
        return err

    data = request.get_json(silent=True) or {}
    user_id = g.user_id
    tasks = data.get("tasks", [])

    if not user_id:
        return jsonify({"status": "error", "message": "user_id required"}), 400

    conn = get_db()
    try:
        with conn.cursor() as cur:
            # Wipe everything for this user
            cur.execute("DELETE FROM tasks WHERE user_id = %s", (user_id,))
            deleted = cur.rowcount

            # Insert the new list
            for task in tasks:
                cur.execute("""
                    INSERT INTO tasks
                        (user_id, task_id, title, due_date, due_time, priority, notes, completed, updated_at)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, NOW())
                """, (
                    user_id,
                    str(task.get("id", "")),
                    task.get("title", ""),
                    task.get("due_date"),
                    task.get("due_time"),
                    int(task.get("priority", 1)),
                    task.get("notes", ""),
                    bool(task.get("completed", False)),
                ))
        conn.commit()
        return jsonify({"status": "success", "deleted": deleted, "inserted": len(tasks)})
    except Exception as exc:
        conn.rollback()
        log.error("replace_tasks error: %s", exc)
        return jsonify({"status": "error", "message": str(exc)}), 500
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Startup – retry until postgres is ready (handles slow CVM cold-starts)
# ---------------------------------------------------------------------------

import time

def _startup_with_retry(max_attempts=10, delay=3):
    for attempt in range(1, max_attempts + 1):
        try:
            init_db()
            log.info("Database ready after %d attempt(s)", attempt)
            return
        except Exception as exc:
            log.warning("DB not ready (attempt %d/%d): %s", attempt, max_attempts, exc)
            if attempt < max_attempts:
                time.sleep(delay)
    log.error("Could not connect to database after %d attempts – starting anyway", max_attempts)

_startup_with_retry()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=False)
