"""
Backend Storage Service for TODO App CVM
Handles encrypted task storage, retrieval, and sync via PostgreSQL.
"""

import json
import os
import logging
import re
import base64
import hashlib
import uuid
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

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
OPENCLAW_WEBHOOK_SECRET = os.environ.get("OPENCLAW_WEBHOOK_SECRET", "")
WALLET_URL = os.environ.get("WALLET_URL", "http://wallet:5004").rstrip("/")
WALLET_SEND_ENABLED = os.environ.get("WALLET_SEND_ENABLED", "false").lower() in ("1", "true", "yes", "on")
WALLET_MAX_TRANSFER_ETH = Decimal(os.environ.get("WALLET_MAX_TRANSFER_ETH", "0.1"))
WALLET_DAILY_LIMIT_ETH = Decimal(os.environ.get("WALLET_DAILY_LIMIT_ETH", "0.25"))
WALLET_PREPARE_LIMIT_PER_HOUR = int(os.environ.get("WALLET_PREPARE_LIMIT_PER_HOUR", "10"))
WALLET_EXPLORER_URL = os.environ.get("WALLET_EXPLORER_URL", "https://base-sepolia.blockscout.com").rstrip("/")
REWARD_XP_PER_TASK = max(1, int(os.environ.get("REWARD_XP_PER_TASK", "10")))
REWARD_XP_PER_LEVEL = max(REWARD_XP_PER_TASK, int(os.environ.get("REWARD_XP_PER_LEVEL", "50")))
REWARD_BADGES_ENABLED = os.environ.get("REWARD_BADGES_ENABLED", "false").lower() in ("1", "true", "yes", "on")
REWARD_BADGE_CONTRACT_ADDRESS = os.environ.get("REWARD_BADGE_CONTRACT_ADDRESS", "").strip()
TASK_ESCROW_ENABLED = os.environ.get("TASK_ESCROW_ENABLED", "false").lower() in ("1", "true", "yes", "on")
TASK_ESCROW_MAX_ETH = Decimal(os.environ.get("TASK_ESCROW_MAX_ETH", "0.05"))

REWARD_ACHIEVEMENTS = (
    {"code": "first_task", "id": 1, "name": "First Step", "description": "Complete your first task.", "tasks": 1},
    {"code": "task_10", "id": 10, "name": "Getting Things Done", "description": "Complete 10 tasks.", "tasks": 10},
    {"code": "task_50", "id": 50, "name": "Momentum", "description": "Complete 50 tasks.", "tasks": 50},
    {"code": "task_100", "id": 100, "name": "Centurion", "description": "Complete 100 tasks.", "tasks": 100},
)

DEVICE_ID_RE = re.compile(r"^[A-Za-z0-9_-]{8,128}$")
IDEMPOTENCY_KEY_RE = re.compile(r"^[A-Za-z0-9_-]{16,128}$")
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


def _send_wallet_confirmation_code(email, code, recipient, amount_eth, chain_name, operation="transfer"):
    """Send a short-lived code for one already-prepared wallet transaction."""
    if os.environ.get("SMTP_ENABLED", "false").lower() != "true":
        log.warning("SMTP is disabled; cannot deliver wallet confirmation code to %s", email)
        return False
    try:
        body = (
            f"Your TODO App wallet confirmation code is: {code}\n\n"
            f"Operation: {operation}\nNetwork: {chain_name}\nAmount: {amount_eth} ETH\nTo: {recipient}\n\n"
            "This code expires in 10 minutes. If you did not request this wallet action, "
            "do not share the code."
        )
        msg = MIMEText(body)
        msg["Subject"] = "Confirm your TODO App testnet wallet action"
        msg["From"] = os.environ.get("SMTP_USER", "")
        msg["To"] = email
        with smtplib.SMTP(os.environ.get("SMTP_HOST", ""), int(os.environ.get("SMTP_PORT", "587"))) as server:
            server.starttls()
            server.login(os.environ.get("SMTP_USER", ""), os.environ.get("SMTP_PASSWORD", ""))
            server.sendmail(msg["From"], [email], msg.as_string())
        return True
    except Exception as exc:
        log.error("Failed to send wallet confirmation email: %s", exc)
        return False


def _wallet_headers():
    headers = {"Content-Type": "application/json"}
    if API_KEY:
        headers["X-API-Key"] = API_KEY
    return headers


def _wallet_request(path, payload, timeout=25):
    response = http_requests.post(
        f"{WALLET_URL}{path}", headers=_wallet_headers(), json=payload, timeout=timeout
    )
    try:
        data = response.json()
    except Exception:
        data = {}
    if response.status_code != 200:
        message = data.get("message", f"Wallet service returned HTTP {response.status_code}")
        error = RuntimeError(message)
        error.status_code = response.status_code
        raise error
    return data


def _eth_to_wei(value):
    try:
        amount = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        raise ValueError("Enter a valid ETH amount")
    if not amount.is_finite() or amount <= 0:
        raise ValueError("Transfer amount must be greater than zero")
    scaled = amount * Decimal(10**18)
    if scaled != scaled.to_integral_value():
        raise ValueError("ETH amount supports at most 18 decimal places")
    if amount > WALLET_MAX_TRANSFER_ETH:
        raise ValueError(f"Maximum transfer is {WALLET_MAX_TRANSFER_ETH} ETH")
    return int(scaled), amount


def _wei_to_eth(value):
    return format(Decimal(str(value)) / Decimal(10**18), "f")


def _wallet_transaction_payload(row):
    if not row:
        return None
    row = dict(row)
    public = {
        "id": str(row["id"]),
        "status": row["status"],
        "from": row["address"],
        "to": row["to_address"],
        "value_wei": str(row["value_wei"]),
        "amount_eth": _wei_to_eth(row["value_wei"]),
        "chain_id": int(row["chain_id"]),
        "chain_name": row["chain_name"],
        "nonce": int(row["nonce"]),
        "gas_limit": int(row["gas_limit"]),
        "max_fee_per_gas": str(row["max_fee_per_gas"]),
        "max_priority_fee_per_gas": str(row["max_priority_fee_per_gas"]),
        "maximum_fee_wei": str(Decimal(row["gas_limit"]) * Decimal(row["max_fee_per_gas"])),
        "maximum_fee_eth": _wei_to_eth(Decimal(row["gas_limit"]) * Decimal(row["max_fee_per_gas"])),
        "transaction_hash": row.get("transaction_hash"),
        "explorer_url": row.get("explorer_url") or "",
        "error_message": row.get("error_message") or "",
        "transaction_kind": row.get("transaction_kind") or "transfer",
        "task_id": row.get("task_id") or "",
        "escrow_action": row.get("escrow_action") or "",
        "escrow_key": row.get("escrow_key") or "",
    }
    for field in ("created_at", "expires_at", "code_expires_at", "broadcast_at", "confirmed_at", "updated_at"):
        value = row.get(field)
        public[field] = value.isoformat() if value else None
    return public


def _task_escrow_payload(row):
    if not row:
        return None
    row = dict(row)
    result = {
        "id": str(row["id"]), "task_id": row["task_id"], "escrow_key": row["escrow_key"],
        "sponsor_address": row["sponsor_address"], "recipient_address": row["recipient_address"],
        "value_wei": str(row["value_wei"]), "amount_eth": _wei_to_eth(row["value_wei"]),
        "status": row["status"],
        "funding_transaction_id": str(row["funding_tx_id"]) if row.get("funding_tx_id") else None,
        "settlement_transaction_id": str(row["settlement_tx_id"]) if row.get("settlement_tx_id") else None,
    }
    for field in ("deadline", "created_at", "updated_at"):
        result[field] = row[field].isoformat() if row.get(field) else None
    return result


def _apply_escrow_transaction_result(cur, transaction_row, chain_status):
    """Advance the linked escrow only after the exact transaction is confirmed."""
    row = dict(transaction_row)
    if row.get("transaction_kind") != "task_escrow" or not row.get("escrow_key"):
        return
    action = row.get("escrow_action")
    if chain_status == "failed":
        failure_status = "failed" if action == "create" else "funded"
        cur.execute(
            "UPDATE task_escrows SET status=%s, updated_at=NOW() WHERE user_id=%s AND escrow_key=%s",
            (failure_status, row["user_id"], row["escrow_key"]),
        )
        return
    next_status = {"create": "funded", "release": "released", "refund": "refunded"}.get(action)
    if next_status:
        cur.execute(
            "UPDATE task_escrows SET status=%s, updated_at=NOW() WHERE user_id=%s AND escrow_key=%s",
            (next_status, row["user_id"], row["escrow_key"]),
        )


def _ensure_reward_schema(cur):
    """Idempotently install reward tables for startup and rolling-deploy safety."""
    # Two Gunicorn workers can reach this rolling-deploy guard together. PostgreSQL
    # may deadlock concurrent CREATE INDEX IF NOT EXISTS calls with later reward
    # updates, so serialize the DDL before either request touches reward rows.
    cur.execute("SELECT pg_advisory_xact_lock(hashtext('todoapp-reward-schema'))")
    cur.execute("""
        CREATE TABLE IF NOT EXISTS user_reward_stats (
            user_id          TEXT PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
            xp               BIGINT NOT NULL DEFAULT 0 CHECK (xp >= 0),
            tasks_completed  BIGINT NOT NULL DEFAULT 0 CHECK (tasks_completed >= 0),
            updated_at       TIMESTAMPTZ DEFAULT NOW()
        );
        CREATE TABLE IF NOT EXISTS task_reward_events (
            user_id       TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            task_id       TEXT NOT NULL,
            xp_awarded    INTEGER NOT NULL CHECK (xp_awarded > 0),
            awarded_at    TIMESTAMPTZ DEFAULT NOW(),
            PRIMARY KEY (user_id, task_id)
        );
        CREATE TABLE IF NOT EXISTS user_achievements (
            user_id             TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            achievement_code    TEXT NOT NULL,
            achievement_id      BIGINT NOT NULL,
            claim_id            TEXT UNIQUE NOT NULL,
            status              TEXT NOT NULL DEFAULT 'eligible',
            raw_transaction     TEXT,
            transaction_hash    TEXT,
            explorer_url        TEXT,
            error_message       TEXT,
            unlocked_at         TIMESTAMPTZ DEFAULT NOW(),
            minted_at           TIMESTAMPTZ,
            updated_at          TIMESTAMPTZ DEFAULT NOW(),
            PRIMARY KEY (user_id, achievement_code),
            CHECK (status IN ('eligible', 'signed', 'broadcast', 'minted', 'failed'))
        );
        CREATE INDEX IF NOT EXISTS idx_user_achievements_status
            ON user_achievements(status, updated_at);
    """)


def _record_task_completion_rewards_in_transaction(cur, user_id, task_ids):
    """Core reward award operation. The caller provides its own savepoint."""
    unique_ids = list(dict.fromkeys(str(task_id) for task_id in task_ids if str(task_id)))
    awarded = 0
    for task_id in unique_ids:
        cur.execute(
            "INSERT INTO task_reward_events (user_id, task_id, xp_awarded) VALUES (%s,%s,%s) "
            "ON CONFLICT (user_id, task_id) DO NOTHING RETURNING xp_awarded",
            (user_id, task_id, REWARD_XP_PER_TASK),
        )
        row = cur.fetchone()
        if row:
            awarded += int(row.get("xp_awarded") if isinstance(row, dict) else row[0])

    if awarded:
        cur.execute(
            "INSERT INTO user_reward_stats (user_id, xp, tasks_completed, updated_at) "
            "VALUES (%s,%s,%s,NOW()) ON CONFLICT (user_id) DO UPDATE SET "
            "xp=user_reward_stats.xp + EXCLUDED.xp, "
            "tasks_completed=user_reward_stats.tasks_completed + EXCLUDED.tasks_completed, "
            "updated_at=NOW()",
            (user_id, awarded, awarded // REWARD_XP_PER_TASK),
        )
    cur.execute(
        "SELECT xp, tasks_completed FROM user_reward_stats WHERE user_id=%s",
        (user_id,),
    )
    stats_row = cur.fetchone()
    if isinstance(stats_row, dict):
        xp = int(stats_row["xp"])
        completed = int(stats_row["tasks_completed"])
    else:
        xp = int(stats_row[0]) if stats_row else 0
        completed = int(stats_row[1]) if stats_row else 0
    unlocked = []
    for achievement in REWARD_ACHIEVEMENTS:
        if completed < achievement["tasks"]:
            continue
        claim_id = "0x" + hashlib.sha256(
            f"todoapp-achievement-v1:{user_id}:{achievement['code']}".encode("utf-8")
        ).hexdigest()
        cur.execute(
            "INSERT INTO user_achievements "
            "(user_id, achievement_code, achievement_id, claim_id, status, unlocked_at) "
            "VALUES (%s,%s,%s,%s,'eligible',NOW()) "
            "ON CONFLICT (user_id, achievement_code) DO NOTHING RETURNING achievement_code",
            (user_id, achievement["code"], achievement["id"], claim_id),
        )
        if cur.fetchone():
            unlocked.append(achievement["code"])
    return {
        "xp_awarded": awarded,
        "xp": xp,
        "tasks_completed": completed,
        "level": xp // REWARD_XP_PER_LEVEL,
        "xp_current": xp % REWARD_XP_PER_LEVEL,
        "xp_needed": REWARD_XP_PER_LEVEL,
        "achievements_unlocked": unlocked,
    }


def _record_task_completion_rewards(cur, user_id, task_ids):
    """Award rewards without ever allowing optional XP work to break a task mutation."""
    cur.execute("SAVEPOINT task_reward_award")
    try:
        _ensure_reward_schema(cur)
        result = _record_task_completion_rewards_in_transaction(cur, user_id, task_ids)
        cur.execute("RELEASE SAVEPOINT task_reward_award")
        return result
    except Exception as exc:
        cur.execute("ROLLBACK TO SAVEPOINT task_reward_award")
        cur.execute("RELEASE SAVEPOINT task_reward_award")
        log.exception("Reward award skipped for user %s: %s", user_id, exc)
        return {
            "xp_awarded": 0,
            "achievements_unlocked": [],
            "warning": "Task completed, but rewards are temporarily unavailable",
        }


def _reconcile_completed_task_rewards(cur, user_id):
    """Repair missing idempotent reward events for every completed task."""
    cur.execute(
        "SELECT t.task_id FROM tasks t "
        "LEFT JOIN task_reward_events e ON e.user_id=t.user_id AND e.task_id=t.task_id "
        "WHERE t.user_id=%s AND t.completed=TRUE AND e.task_id IS NULL",
        (user_id,),
    )
    rows = cur.fetchall()
    task_ids = [row.get("task_id") if isinstance(row, dict) else row[0] for row in rows]
    return _record_task_completion_rewards(cur, user_id, task_ids)


def _reward_payload(row):
    row = dict(row)
    result = {
        "code": row["achievement_code"],
        "achievement_id": int(row["achievement_id"]),
        "claim_id": row["claim_id"],
        "status": row["status"],
        "transaction_hash": row.get("transaction_hash"),
        "explorer_url": row.get("explorer_url") or "",
        "error_message": row.get("error_message") or "",
    }
    for field in ("unlocked_at", "minted_at", "updated_at"):
        value = row.get(field)
        result[field] = value.isoformat() if value else None
    return result


def _ensure_user_wallet(conn, user_id):
    """Derive and verify the current TEE address, then persist its public metadata."""
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(
            "SELECT address, chain_id, chain_name, native_symbol, derivation_version, "
            "receive_uri, explorer_url, created_at FROM user_wallets WHERE user_id = %s",
            (user_id,),
        )
        stored_wallet = cur.fetchone()

    response = http_requests.post(
        f"{WALLET_URL}/v1/wallets/derive",
        headers=_wallet_headers(),
        json={"user_id": user_id},
        timeout=20,
    )
    try:
        payload = response.json()
    except Exception:
        payload = {}
    if response.status_code != 200:
        raise RuntimeError(payload.get("message", "Wallet service is unavailable"))

    if stored_wallet:
        stored_wallet = dict(stored_wallet)
        continuity_matches = (
            stored_wallet["address"].lower() == str(payload.get("address", "")).lower()
            and int(stored_wallet["chain_id"]) == int(payload.get("chain_id", -1))
            and stored_wallet["derivation_version"] == payload.get("derivation_version")
        )
        if not continuity_matches:
            raise RuntimeError(
                "Wallet derivation identity changed. Deposits are disabled until the original "
                "CVM identity and wallet derivation settings are restored."
            )
        stored_wallet["derivation_verified"] = True
        return stored_wallet

    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(
            """
            INSERT INTO user_wallets
                (user_id, address, chain_id, chain_name, native_symbol,
                 derivation_version, receive_uri, explorer_url)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (user_id) DO NOTHING
            """,
            (
                user_id, payload["address"], int(payload["chain_id"]),
                payload.get("chain_name", "EVM"), payload.get("native_symbol", "ETH"),
                payload["derivation_version"], payload.get("receive_uri", ""),
                payload.get("explorer_url", ""),
            ),
        )
        cur.execute(
            "SELECT address, chain_id, chain_name, native_symbol, derivation_version, "
            "receive_uri, explorer_url, created_at FROM user_wallets WHERE user_id = %s",
            (user_id,),
        )
        wallet = dict(cur.fetchone())
    conn.commit()
    wallet["derivation_verified"] = True
    return wallet


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

                CREATE TABLE IF NOT EXISTS user_reward_stats (
                    user_id          TEXT PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
                    xp               BIGINT NOT NULL DEFAULT 0 CHECK (xp >= 0),
                    tasks_completed  BIGINT NOT NULL DEFAULT 0 CHECK (tasks_completed >= 0),
                    updated_at       TIMESTAMPTZ DEFAULT NOW()
                );

                CREATE TABLE IF NOT EXISTS task_reward_events (
                    user_id       TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    task_id       TEXT NOT NULL,
                    xp_awarded    INTEGER NOT NULL CHECK (xp_awarded > 0),
                    awarded_at    TIMESTAMPTZ DEFAULT NOW(),
                    PRIMARY KEY (user_id, task_id)
                );

                CREATE TABLE IF NOT EXISTS user_achievements (
                    user_id             TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    achievement_code    TEXT NOT NULL,
                    achievement_id      BIGINT NOT NULL,
                    claim_id            TEXT UNIQUE NOT NULL,
                    status              TEXT NOT NULL DEFAULT 'eligible',
                    raw_transaction     TEXT,
                    transaction_hash    TEXT,
                    explorer_url        TEXT,
                    error_message       TEXT,
                    unlocked_at         TIMESTAMPTZ DEFAULT NOW(),
                    minted_at           TIMESTAMPTZ,
                    updated_at          TIMESTAMPTZ DEFAULT NOW(),
                    PRIMARY KEY (user_id, achievement_code),
                    CHECK (status IN ('eligible', 'signed', 'broadcast', 'minted', 'failed'))
                );
                CREATE INDEX IF NOT EXISTS idx_user_achievements_status
                    ON user_achievements(status, updated_at);

                CREATE TABLE IF NOT EXISTS user_wallets (
                    user_id            TEXT PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
                    address            TEXT UNIQUE NOT NULL,
                    chain_id           BIGINT NOT NULL,
                    chain_name         TEXT NOT NULL,
                    native_symbol      TEXT NOT NULL DEFAULT 'ETH',
                    derivation_version TEXT NOT NULL,
                    receive_uri        TEXT NOT NULL,
                    explorer_url       TEXT NOT NULL,
                    created_at         TIMESTAMPTZ DEFAULT NOW()
                );

                CREATE TABLE IF NOT EXISTS wallet_transactions (
                    id                       UUID PRIMARY KEY,
                    user_id                  TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    idempotency_key           TEXT NOT NULL,
                    address                   TEXT NOT NULL,
                    to_address                TEXT NOT NULL,
                    value_wei                 NUMERIC(78, 0) NOT NULL,
                    chain_id                  BIGINT NOT NULL,
                    chain_name                TEXT NOT NULL,
                    nonce                     BIGINT NOT NULL,
                    gas_limit                 BIGINT NOT NULL,
                    max_fee_per_gas            NUMERIC(78, 0) NOT NULL,
                    max_priority_fee_per_gas   NUMERIC(78, 0) NOT NULL,
                    status                    TEXT NOT NULL DEFAULT 'prepared',
                    code_hash                 TEXT,
                    code_expires_at           TIMESTAMPTZ,
                    code_attempts              INTEGER NOT NULL DEFAULT 0,
                    password_attempts          INTEGER NOT NULL DEFAULT 0,
                    code_sent_at               TIMESTAMPTZ,
                    raw_transaction            TEXT,
                    transaction_hash           TEXT,
                    explorer_url               TEXT,
                    error_message              TEXT,
                    created_at                 TIMESTAMPTZ DEFAULT NOW(),
                    expires_at                 TIMESTAMPTZ NOT NULL,
                    updated_at                 TIMESTAMPTZ DEFAULT NOW(),
                    broadcast_at               TIMESTAMPTZ,
                    confirmed_at               TIMESTAMPTZ,
                    UNIQUE (user_id, idempotency_key),
                    CHECK (status IN ('prepared', 'code_sent', 'signed', 'broadcast', 'confirmed', 'failed', 'expired'))
                );
                CREATE INDEX IF NOT EXISTS idx_wallet_transactions_user_created
                    ON wallet_transactions(user_id, created_at DESC);
                CREATE INDEX IF NOT EXISTS idx_wallet_transactions_hash
                    ON wallet_transactions(transaction_hash) WHERE transaction_hash IS NOT NULL;

                ALTER TABLE wallet_transactions
                    ADD COLUMN IF NOT EXISTS password_attempts INTEGER NOT NULL DEFAULT 0;
                ALTER TABLE wallet_transactions ADD COLUMN IF NOT EXISTS transaction_kind TEXT NOT NULL DEFAULT 'transfer';
                ALTER TABLE wallet_transactions ADD COLUMN IF NOT EXISTS task_id TEXT;
                ALTER TABLE wallet_transactions ADD COLUMN IF NOT EXISTS escrow_action TEXT;
                ALTER TABLE wallet_transactions ADD COLUMN IF NOT EXISTS escrow_key TEXT;
                ALTER TABLE wallet_transactions ADD COLUMN IF NOT EXISTS calldata TEXT;

                CREATE TABLE IF NOT EXISTS task_escrows (
                    id                UUID PRIMARY KEY,
                    user_id           TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    task_id           TEXT NOT NULL,
                    escrow_key        TEXT UNIQUE NOT NULL,
                    sponsor_address   TEXT NOT NULL,
                    recipient_address TEXT NOT NULL,
                    value_wei         NUMERIC(78, 0) NOT NULL CHECK (value_wei > 0),
                    deadline          TIMESTAMPTZ NOT NULL,
                    status            TEXT NOT NULL DEFAULT 'preparing',
                    funding_tx_id     UUID REFERENCES wallet_transactions(id),
                    settlement_tx_id  UUID REFERENCES wallet_transactions(id),
                    created_at        TIMESTAMPTZ DEFAULT NOW(),
                    updated_at        TIMESTAMPTZ DEFAULT NOW(),
                    UNIQUE (user_id, task_id),
                    CHECK (status IN ('preparing','funding','funded','release_pending','released','refund_pending','refunded','failed'))
                );
                CREATE INDEX IF NOT EXISTS idx_task_escrows_user_created ON task_escrows(user_id, created_at DESC);

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

                CREATE TABLE IF NOT EXISTS task_reminders (
                    user_id        TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    task_id        TEXT NOT NULL,
                    task_label     TEXT NOT NULL DEFAULT 'Task',
                    email_enabled  BOOLEAN NOT NULL DEFAULT FALSE,
                    reminder_email TEXT,
                    sms_enabled    BOOLEAN NOT NULL DEFAULT FALSE,
                    phone_number   TEXT,
                    minutes_before INTEGER NOT NULL DEFAULT 15 CHECK (minutes_before BETWEEN 0 AND 10080),
                    timezone_name  TEXT NOT NULL DEFAULT 'UTC',
                    recurring_days TEXT[],
                    recurring_time TEXT,
                    recurring_schedule JSONB NOT NULL DEFAULT '[]'::jsonb,
                    updated_at     TIMESTAMPTZ DEFAULT NOW(),
                    PRIMARY KEY (user_id, task_id)
                );

                CREATE TABLE IF NOT EXISTS reminder_deliveries (
                    user_id     TEXT NOT NULL,
                    task_id     TEXT NOT NULL,
                    channel     TEXT NOT NULL,
                    scheduled_for TIMESTAMPTZ NOT NULL,
                    sent_at     TIMESTAMPTZ DEFAULT NOW(),
                    PRIMARY KEY (user_id, task_id, channel, scheduled_for)
                );

                CREATE TABLE IF NOT EXISTS meeting_proposals (
                    id            UUID PRIMARY KEY,
                    user_id       TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    external_id   TEXT NOT NULL,
                    title         TEXT NOT NULL,
                    organizer     TEXT NOT NULL DEFAULT '',
                    start_at      TIMESTAMPTZ NOT NULL,
                    end_at        TIMESTAMPTZ,
                    meeting_link  TEXT NOT NULL DEFAULT '',
                    notes         TEXT NOT NULL DEFAULT '',
                    status        TEXT NOT NULL DEFAULT 'pending',
                    created_at    TIMESTAMPTZ DEFAULT NOW(),
                    decided_at    TIMESTAMPTZ,
                    UNIQUE (user_id, external_id),
                    CHECK (status IN ('pending', 'accepted', 'ignored'))
                );
                CREATE INDEX IF NOT EXISTS idx_meeting_proposals_user_status
                    ON meeting_proposals(user_id, status, created_at);

                -- Existing accounts predate verification, so preserve their ability to sign in.
                -- New registrations explicitly start with FALSE and must verify a code.
                ALTER TABLE users ADD COLUMN IF NOT EXISTS email_verified BOOLEAN;
                UPDATE users SET email_verified = TRUE WHERE email_verified IS NULL;
                ALTER TABLE users ALTER COLUMN email_verified SET DEFAULT FALSE;
                ALTER TABLE users ALTER COLUMN email_verified SET NOT NULL;
                ALTER TABLE task_reminders ADD COLUMN IF NOT EXISTS recurring_days TEXT[];
                ALTER TABLE task_reminders ADD COLUMN IF NOT EXISTS recurring_time TEXT;
                ALTER TABLE task_reminders ADD COLUMN IF NOT EXISTS recurring_schedule JSONB NOT NULL DEFAULT '[]'::jsonb;
            """)
            # One-time/idempotent migration for tasks completed before rewards existed.
            cur.execute(
                "INSERT INTO task_reward_events (user_id, task_id, xp_awarded) "
                "SELECT t.user_id, t.task_id, %s FROM tasks t "
                "JOIN users u ON u.id=t.user_id WHERE t.completed=TRUE "
                "ON CONFLICT (user_id, task_id) DO NOTHING",
                (REWARD_XP_PER_TASK,),
            )
            cur.execute("""
                INSERT INTO user_reward_stats (user_id, xp, tasks_completed, updated_at)
                SELECT user_id, SUM(xp_awarded), COUNT(*), NOW()
                FROM task_reward_events GROUP BY user_id
                ON CONFLICT (user_id) DO UPDATE SET
                    xp=EXCLUDED.xp,
                    tasks_completed=EXCLUDED.tasks_completed,
                    updated_at=NOW()
            """)
            cur.execute("SELECT user_id FROM user_reward_stats")
            reward_users = [row[0] for row in cur.fetchall()]
            for reward_user_id in reward_users:
                _record_task_completion_rewards(cur, reward_user_id, [])
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
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT 1")
                cur.fetchone()
        finally:
            conn.close()
        return jsonify({
            "status": "ok",
            "service": "backend",
            "database": {"status": "ok", "type": "postgresql"},
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })
    except Exception as exc:
        return jsonify({
            "status": "error",
            "service": "backend",
            "database": {"status": "error", "type": "postgresql"},
            "message": str(exc),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }), 503


# ---------------------------------------------------------------------------
# Client-side encryption device registry
# ---------------------------------------------------------------------------

@app.route("/wallet", methods=["GET"])
@require_auth
def get_wallet():
    """Create/read the signed-in user's controlled testnet wallet and portfolio."""
    conn = get_db()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("SELECT email_verified FROM users WHERE id = %s", (g.user_id,))
            user = cur.fetchone()
        if not user or not user["email_verified"]:
            return jsonify({"status": "error", "message": "Verify your email before creating a wallet"}), 403

        wallet = _ensure_user_wallet(conn, g.user_id)
        wallet["created_at"] = wallet["created_at"].isoformat() if wallet.get("created_at") else None

        portfolio = {"balance": None, "transactions": [], "history_available": False}
        portfolio_error = ""
        include_portfolio = request.args.get("include_portfolio", "true").lower() not in ("0", "false", "no")
        if include_portfolio:
            try:
                response = http_requests.post(
                    f"{WALLET_URL}/v1/wallets/portfolio",
                    headers=_wallet_headers(),
                    json={"address": wallet["address"]},
                    timeout=20,
                )
                data = response.json()
                if response.status_code == 200:
                    portfolio = data
                else:
                    portfolio_error = data.get("message", "Portfolio service is unavailable")
            except Exception as exc:
                portfolio_error = str(exc)

        return jsonify({
            "status": "success",
            "wallet": wallet,
            "balance": portfolio.get("balance"),
            "transactions": portfolio.get("transactions", []),
            "history_available": portfolio.get("history_available", False),
            "history_message": portfolio.get("history_message", ""),
            "portfolio_error": portfolio_error,
            "mode": "controlled-testnet-send" if WALLET_SEND_ENABLED else "receive-only",
            "send_enabled": WALLET_SEND_ENABLED,
        })
    except Exception as exc:
        conn.rollback()
        log.exception("Wallet retrieval failed for user %s", g.user_id)
        return jsonify({"status": "error", "message": str(exc)}), 503
    finally:
        conn.close()

@app.route("/wallet/transactions/prepare", methods=["POST"])
@require_auth
def prepare_wallet_transaction():
    if not WALLET_SEND_ENABLED:
        return jsonify({"status": "error", "message": "Wallet sending is disabled"}), 403
    data = request.get_json(silent=True) or {}
    recipient = str(data.get("to", "")).strip()
    idempotency_key = str(request.headers.get("Idempotency-Key") or data.get("idempotency_key") or "").strip()
    if not IDEMPOTENCY_KEY_RE.fullmatch(idempotency_key):
        return jsonify({"status": "error", "message": "A valid idempotency key is required"}), 400
    try:
        value_wei, _ = _eth_to_wei(data.get("amount_eth"))
    except ValueError as exc:
        return jsonify({"status": "error", "message": str(exc)}), 400
    conn = get_db()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                "SELECT * FROM wallet_transactions WHERE user_id=%s AND idempotency_key=%s",
                (g.user_id, idempotency_key),
            )
            existing = cur.fetchone()
            if existing:
                return jsonify({"status": "success", "transaction": _wallet_transaction_payload(existing), "idempotent": True})
            cur.execute(
                "SELECT COUNT(*) AS count FROM wallet_transactions "
                "WHERE user_id=%s AND created_at > NOW() - INTERVAL '1 hour'",
                (g.user_id,),
            )
            if int(cur.fetchone()["count"]) >= WALLET_PREPARE_LIMIT_PER_HOUR:
                return jsonify({"status": "error", "message": "Hourly wallet preparation limit reached"}), 429
            cur.execute(
                "SELECT COALESCE(SUM(value_wei), 0) AS total FROM wallet_transactions "
                "WHERE user_id=%s AND created_at > NOW() - INTERVAL '24 hours' "
                "AND status IN ('signed', 'broadcast', 'confirmed')",
                (g.user_id,),
            )
            sent_wei = Decimal(cur.fetchone()["total"])
            if sent_wei + Decimal(value_wei) > WALLET_DAILY_LIMIT_ETH * Decimal(10**18):
                return jsonify({"status": "error", "message": f"Daily transfer limit is {WALLET_DAILY_LIMIT_ETH} ETH"}), 400
        wallet = _ensure_user_wallet(conn, g.user_id)
        quote = _wallet_request("/v1/wallets/quote-transfer", {
            "user_id": g.user_id, "address": wallet["address"],
            "to": recipient, "value_wei": str(value_wei),
        })["quote"]
        transaction_id = uuid.uuid4()
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                """
                INSERT INTO wallet_transactions
                    (id, user_id, idempotency_key, address, to_address, value_wei,
                     chain_id, chain_name, nonce, gas_limit, max_fee_per_gas,
                     max_priority_fee_per_gas, expires_at)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,TO_TIMESTAMP(%s))
                RETURNING *
                """,
                (
                    transaction_id, g.user_id, idempotency_key, quote["from"], quote["to"],
                    str(value_wei), int(quote["chain_id"]), wallet["chain_name"], int(quote["nonce"]),
                    int(quote["gas_limit"]), quote["max_fee_per_gas"],
                    quote["max_priority_fee_per_gas"], int(quote["expires_at"]),
                ),
            )
            row = cur.fetchone()
        conn.commit()
        return jsonify({"status": "success", "transaction": _wallet_transaction_payload(row)})
    except (ValueError, RuntimeError) as exc:
        conn.rollback()
        code = getattr(exc, "status_code", 400)
        return jsonify({"status": "error", "message": str(exc)}), code if code in (400, 403, 409, 429, 503) else 503
    except Exception as exc:
        conn.rollback()
        log.exception("Wallet transaction preparation failed")
        return jsonify({"status": "error", "message": str(exc)}), 503
    finally:
        conn.close()


def _parse_escrow_deadline(value):
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    except (TypeError, ValueError):
        raise ValueError("Enter a valid escrow deadline")


def _insert_escrow_wallet_transaction(cur, user_id, wallet, task_id, escrow_key, action, quote, idempotency_key):
    transaction_id = uuid.uuid4()
    cur.execute(
        """
        INSERT INTO wallet_transactions
            (id,user_id,idempotency_key,address,to_address,value_wei,chain_id,chain_name,
             nonce,gas_limit,max_fee_per_gas,max_priority_fee_per_gas,expires_at,
             transaction_kind,task_id,escrow_action,escrow_key,calldata)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,TO_TIMESTAMP(%s),'task_escrow',%s,%s,%s,%s)
        RETURNING *
        """,
        (transaction_id, user_id, idempotency_key, quote["from"], quote["to"], quote["value_wei"],
         int(quote["chain_id"]), wallet["chain_name"], int(quote["nonce"]), int(quote["gas_limit"]),
         quote["max_fee_per_gas"], quote["max_priority_fee_per_gas"], int(quote["expires_at"]),
         task_id, action, escrow_key, quote["data"]),
    )
    return cur.fetchone()


@app.route("/task-escrows", methods=["GET"])
@require_auth
def list_task_escrows():
    conn = get_db()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("SELECT * FROM task_escrows WHERE user_id=%s ORDER BY created_at DESC", (g.user_id,))
            rows = cur.fetchall()
        config = _wallet_request("/v1/escrows/config", {})
        return jsonify({
            "status": "success", "enabled": bool(TASK_ESCROW_ENABLED and config.get("enabled")),
            "config": config, "escrows": [_task_escrow_payload(row) for row in rows],
        })
    except Exception as exc:
        return jsonify({"status": "error", "message": str(exc)}), 503
    finally:
        conn.close()


@app.route("/task-escrows/prepare", methods=["POST"])
@require_auth
def prepare_task_escrow():
    if not TASK_ESCROW_ENABLED:
        return jsonify({"status": "error", "message": "Task escrow is disabled"}), 403
    data = request.get_json(silent=True) or {}
    task_id = str(data.get("task_id", "")).strip()
    recipient = str(data.get("recipient", "")).strip()
    idempotency_key = str(request.headers.get("Idempotency-Key") or data.get("idempotency_key") or "").strip()
    if not task_id or not re.fullmatch(r"0x[0-9a-fA-F]{40}", recipient):
        return jsonify({"status": "error", "message": "Choose a task and enter a valid recipient address"}), 400
    if not IDEMPOTENCY_KEY_RE.fullmatch(idempotency_key):
        return jsonify({"status": "error", "message": "A valid idempotency key is required"}), 400
    try:
        value_wei, amount = _eth_to_wei(data.get("amount_eth"))
        if amount > TASK_ESCROW_MAX_ETH:
            raise ValueError(f"Maximum task escrow is {TASK_ESCROW_MAX_ETH} ETH")
        deadline = _parse_escrow_deadline(data.get("deadline"))
        if deadline <= datetime.now(timezone.utc):
            raise ValueError("Escrow deadline must be in the future")
    except ValueError as exc:
        return jsonify({"status": "error", "message": str(exc)}), 400
    conn = get_db()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", (g.user_id,))
            cur.execute("SELECT * FROM wallet_transactions WHERE user_id=%s AND idempotency_key=%s", (g.user_id, idempotency_key))
            existing_tx = cur.fetchone()
            if existing_tx:
                return jsonify({"status": "success", "transaction": _wallet_transaction_payload(existing_tx), "idempotent": True})
            cur.execute(
                "SELECT COUNT(*) AS count FROM wallet_transactions "
                "WHERE user_id=%s AND created_at > NOW() - INTERVAL '1 hour'",
                (g.user_id,),
            )
            if int(cur.fetchone()["count"]) >= WALLET_PREPARE_LIMIT_PER_HOUR:
                return jsonify({"status": "error", "message": "Hourly wallet preparation limit reached"}), 429
            cur.execute("SELECT completed FROM tasks WHERE user_id=%s AND task_id=%s", (g.user_id, task_id))
            task = cur.fetchone()
            if not task:
                return jsonify({"status": "error", "message": "Task not found"}), 404
            if task["completed"]:
                return jsonify({"status": "error", "message": "A completed task cannot receive a new escrow"}), 409
            cur.execute(
                "SELECT te.*, wt.status AS funding_status, wt.expires_at AS funding_expires_at "
                "FROM task_escrows te LEFT JOIN wallet_transactions wt ON wt.id=te.funding_tx_id "
                "WHERE te.user_id=%s AND te.task_id=%s FOR UPDATE OF te",
                (g.user_id, task_id),
            )
            existing_escrow = cur.fetchone()
            if existing_escrow and existing_escrow["status"] == "preparing" and (
                existing_escrow.get("funding_status") in ("failed", "expired")
                or (existing_escrow.get("funding_expires_at") and existing_escrow["funding_expires_at"] <= datetime.now(timezone.utc))
            ):
                cur.execute("UPDATE task_escrows SET status='failed',updated_at=NOW() WHERE id=%s", (existing_escrow["id"],))
                existing_escrow["status"] = "failed"
            if existing_escrow and existing_escrow["status"] != "failed":
                return jsonify({"status": "error", "message": "This task already has an escrow or pending escrow request"}), 409
        wallet = _ensure_user_wallet(conn, g.user_id)
        escrow_id = existing_escrow["id"] if existing_escrow else uuid.uuid4()
        escrow_key = existing_escrow["escrow_key"] if existing_escrow else "0x" + hashlib.sha256(f"todoapp-escrow-v1:{g.user_id}:{task_id}".encode()).hexdigest()
        quote = _wallet_request("/v1/escrows/quote", {
            "user_id": g.user_id, "address": wallet["address"], "action": "create",
            "escrow_key": escrow_key, "recipient": recipient, "deadline": int(deadline.timestamp()),
            "value_wei": str(value_wei),
        })["quote"]
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            tx = _insert_escrow_wallet_transaction(cur, g.user_id, wallet, task_id, escrow_key, "create", quote, idempotency_key)
            if existing_escrow:
                cur.execute(
                    "UPDATE task_escrows SET sponsor_address=%s,recipient_address=%s,value_wei=%s,deadline=%s,"
                    "status='preparing',funding_tx_id=%s,settlement_tx_id=NULL,updated_at=NOW() WHERE id=%s RETURNING *",
                    (wallet["address"], recipient, str(value_wei), deadline, tx["id"], escrow_id),
                )
            else:
                cur.execute(
                    "INSERT INTO task_escrows (id,user_id,task_id,escrow_key,sponsor_address,recipient_address,value_wei,deadline,status,funding_tx_id) "
                    "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,'preparing',%s) RETURNING *",
                    (escrow_id, g.user_id, task_id, escrow_key, wallet["address"], recipient, str(value_wei), deadline, tx["id"]),
                )
            escrow = cur.fetchone()
        conn.commit()
        return jsonify({"status": "success", "escrow": _task_escrow_payload(escrow), "transaction": _wallet_transaction_payload(tx)})
    except Exception as exc:
        conn.rollback()
        log.exception("Task escrow preparation failed")
        code = getattr(exc, "status_code", 503)
        return jsonify({"status": "error", "message": str(exc)}), code if code in (400, 403, 409, 429, 503) else 503
    finally:
        conn.close()


@app.route("/task-escrows/<escrow_id>/prepare-action", methods=["POST"])
@require_auth
def prepare_task_escrow_action(escrow_id):
    if not TASK_ESCROW_ENABLED:
        return jsonify({"status": "error", "message": "Task escrow is disabled"}), 403
    try:
        parsed_id = uuid.UUID(escrow_id)
    except ValueError:
        return jsonify({"status": "error", "message": "Invalid escrow ID"}), 400
    data = request.get_json(silent=True) or {}
    action = str(data.get("action", "")).lower()
    idempotency_key = str(request.headers.get("Idempotency-Key") or data.get("idempotency_key") or "").strip()
    if action not in ("release", "refund") or not IDEMPOTENCY_KEY_RE.fullmatch(idempotency_key):
        return jsonify({"status": "error", "message": "Valid action and idempotency key required"}), 400
    conn = get_db()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", (g.user_id,))
            cur.execute(
                "SELECT * FROM wallet_transactions WHERE user_id=%s AND idempotency_key=%s",
                (g.user_id, idempotency_key),
            )
            existing_tx = cur.fetchone()
            if existing_tx:
                return jsonify({"status": "success", "transaction": _wallet_transaction_payload(existing_tx), "idempotent": True})
            cur.execute(
                "SELECT COUNT(*) AS count FROM wallet_transactions "
                "WHERE user_id=%s AND created_at > NOW() - INTERVAL '1 hour'",
                (g.user_id,),
            )
            if int(cur.fetchone()["count"]) >= WALLET_PREPARE_LIMIT_PER_HOUR:
                return jsonify({"status": "error", "message": "Hourly wallet preparation limit reached"}), 429
            cur.execute("SELECT * FROM task_escrows WHERE id=%s AND user_id=%s FOR UPDATE", (parsed_id, g.user_id))
            escrow = cur.fetchone()
            if not escrow:
                return jsonify({"status": "error", "message": "Escrow not found"}), 404
            if escrow["status"] != "funded":
                return jsonify({"status": "error", "message": "Only a funded escrow can be settled"}), 409
            if action == "release":
                cur.execute("SELECT completed FROM tasks WHERE user_id=%s AND task_id=%s", (g.user_id, escrow["task_id"]))
                task = cur.fetchone()
                if not task or not task["completed"]:
                    return jsonify({"status": "error", "message": "Complete the task before releasing its reward"}), 409
            if action == "refund" and escrow["deadline"] > datetime.now(timezone.utc):
                return jsonify({"status": "error", "message": "Refund is available only after the escrow deadline"}), 409
        wallet = _ensure_user_wallet(conn, g.user_id)
        quote = _wallet_request("/v1/escrows/quote", {
            "user_id": g.user_id, "address": wallet["address"], "action": action,
            "escrow_key": escrow["escrow_key"], "recipient": escrow["recipient_address"],
            "deadline": int(escrow["deadline"].timestamp()), "value_wei": "0",
        })["quote"]
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            tx = _insert_escrow_wallet_transaction(cur, g.user_id, wallet, escrow["task_id"], escrow["escrow_key"], action, quote, idempotency_key)
            cur.execute(
                "UPDATE task_escrows SET settlement_tx_id=%s,updated_at=NOW() WHERE id=%s RETURNING *",
                (tx["id"], parsed_id),
            )
            escrow = cur.fetchone()
        conn.commit()
        return jsonify({"status": "success", "escrow": _task_escrow_payload(escrow), "transaction": _wallet_transaction_payload(tx)})
    except Exception as exc:
        conn.rollback()
        return jsonify({"status": "error", "message": str(exc)}), getattr(exc, "status_code", 503)
    finally:
        conn.close()


@app.route("/wallet/transactions/<transaction_id>/request-code", methods=["POST"])
@require_auth
def request_wallet_transaction_code(transaction_id):
    try:
        parsed_id = uuid.UUID(transaction_id)
    except ValueError:
        return jsonify({"status": "error", "message": "Invalid transaction ID"}), 400
    password = str((request.get_json(silent=True) or {}).get("password", ""))
    if not password:
        return jsonify({"status": "error", "message": "Password is required"}), 400
    conn = get_db()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                "SELECT wt.*, u.email, u.password_hash FROM wallet_transactions wt "
                "JOIN users u ON u.id=wt.user_id WHERE wt.id=%s AND wt.user_id=%s FOR UPDATE",
                (parsed_id, g.user_id),
            )
            row = cur.fetchone()
            if not row:
                return jsonify({"status": "error", "message": "Transaction not found"}), 404
            if row["status"] not in ("prepared", "code_sent"):
                return jsonify({"status": "error", "message": "Transaction can no longer be confirmed"}), 409
            now = datetime.now(timezone.utc)
            if row["expires_at"] <= now:
                cur.execute("UPDATE wallet_transactions SET status='expired', updated_at=NOW() WHERE id=%s", (parsed_id,))
                _apply_escrow_transaction_result(cur, row, "failed")
                conn.commit()
                return jsonify({"status": "error", "message": "Transaction quote expired; prepare it again"}), 409
            if row["code_sent_at"] and (now - row["code_sent_at"]).total_seconds() < 60:
                return jsonify({"status": "error", "message": "Wait one minute before requesting another code"}), 429
            if not row["password_hash"] or not auth_lib.verify_password(password, row["password_hash"]):
                password_attempts = int(row.get("password_attempts") or 0) + 1
                next_status = "failed" if password_attempts >= 5 else row["status"]
                cur.execute(
                    "UPDATE wallet_transactions SET password_attempts=%s, status=%s, "
                    "error_message=%s, updated_at=NOW() WHERE id=%s",
                    (
                        password_attempts,
                        next_status,
                        "Too many incorrect password attempts" if next_status == "failed" else None,
                        parsed_id,
                    ),
                )
                if next_status == "failed":
                    _apply_escrow_transaction_result(cur, row, "failed")
                conn.commit()
                message = (
                    "Transaction locked after too many incorrect password attempts"
                    if next_status == "failed" else "Incorrect password"
                )
                return jsonify({"status": "error", "message": message}), 401
            code = f"{secrets.randbelow(1_000_000):06d}"
            code_hash = auth_lib.hash_token(f"wallet:{parsed_id}:{code}")
            operation = "transfer"
            if row.get("transaction_kind") == "task_escrow":
                operation = f"task escrow {row.get('escrow_action') or 'action'}"
            if not _send_wallet_confirmation_code(
                row["email"], code, row["to_address"], _wei_to_eth(row["value_wei"]), row["chain_name"], operation
            ):
                return jsonify({"status": "error", "message": "Could not send confirmation email"}), 503
            cur.execute(
                "UPDATE wallet_transactions SET status='code_sent', code_hash=%s, "
                "code_expires_at=NOW() + INTERVAL '10 minutes', code_attempts=0, "
                "password_attempts=0, code_sent_at=NOW(), error_message=NULL, "
                "updated_at=NOW() WHERE id=%s RETURNING *",
                (code_hash, parsed_id),
            )
            updated = cur.fetchone()
        conn.commit()
        return jsonify({"status": "success", "message": "Confirmation code sent", "transaction": _wallet_transaction_payload(updated)})
    except Exception as exc:
        conn.rollback()
        log.exception("Wallet confirmation-code request failed")
        return jsonify({"status": "error", "message": str(exc)}), 503
    finally:
        conn.close()


@app.route("/wallet/transactions/<transaction_id>/confirm", methods=["POST"])
@require_auth
def confirm_wallet_transaction(transaction_id):
    try:
        parsed_id = uuid.UUID(transaction_id)
    except ValueError:
        return jsonify({"status": "error", "message": "Invalid transaction ID"}), 400
    code = str((request.get_json(silent=True) or {}).get("code", "")).strip()
    conn = get_db()
    raw_transaction = None
    transaction_hash = None
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", (g.user_id,))
            cur.execute(
                "SELECT * FROM wallet_transactions WHERE id=%s AND user_id=%s FOR UPDATE",
                (parsed_id, g.user_id),
            )
            row = cur.fetchone()
            if not row:
                return jsonify({"status": "error", "message": "Transaction not found"}), 404
            if row["status"] in ("broadcast", "confirmed"):
                return jsonify({"status": "success", "transaction": _wallet_transaction_payload(row), "idempotent": True})
            if row["status"] == "signed" and row["raw_transaction"] and row["transaction_hash"]:
                raw_transaction = row["raw_transaction"]
                transaction_hash = row["transaction_hash"]
            else:
                if row["status"] != "code_sent":
                    return jsonify({"status": "error", "message": "Request a confirmation code first"}), 409
                cur.execute(
                    "SELECT id FROM wallet_transactions WHERE user_id=%s AND id<>%s "
                    "AND nonce=%s AND status IN ('signed', 'broadcast') LIMIT 1",
                    (g.user_id, parsed_id, row["nonce"]),
                )
                if cur.fetchone():
                    return jsonify({
                        "status": "error",
                        "message": "Another transfer already uses this nonce; wait for it to finish and prepare again",
                    }), 409
                cur.execute(
                    "SELECT COALESCE(SUM(value_wei), 0) AS total FROM wallet_transactions "
                    "WHERE user_id=%s AND id<>%s AND created_at > NOW() - INTERVAL '24 hours' "
                    "AND status IN ('signed', 'broadcast', 'confirmed')",
                    (g.user_id, parsed_id),
                )
                authorized_wei = Decimal(cur.fetchone()["total"])
                if authorized_wei + Decimal(row["value_wei"]) > WALLET_DAILY_LIMIT_ETH * Decimal(10**18):
                    return jsonify({
                        "status": "error",
                        "message": f"Daily transfer limit is {WALLET_DAILY_LIMIT_ETH} ETH",
                    }), 409
                now = datetime.now(timezone.utc)
                if row["expires_at"] <= now or not row["code_expires_at"] or row["code_expires_at"] <= now:
                    cur.execute("UPDATE wallet_transactions SET status='expired', updated_at=NOW() WHERE id=%s", (parsed_id,))
                    _apply_escrow_transaction_result(cur, row, "failed")
                    conn.commit()
                    return jsonify({"status": "error", "message": "Transaction or confirmation code expired"}), 409
                supplied_hash = auth_lib.hash_token(f"wallet:{parsed_id}:{code}")
                if not code or not row["code_hash"] or not secrets.compare_digest(row["code_hash"], supplied_hash):
                    attempts = int(row["code_attempts"]) + 1
                    new_status = "failed" if attempts >= 5 else "code_sent"
                    cur.execute(
                        "UPDATE wallet_transactions SET code_attempts=%s, status=%s, updated_at=NOW() WHERE id=%s",
                        (attempts, new_status, parsed_id),
                    )
                    if new_status == "failed":
                        _apply_escrow_transaction_result(cur, row, "failed")
                    conn.commit()
                    message = "Too many incorrect codes; prepare a new transaction" if attempts >= 5 else "Invalid confirmation code"
                    return jsonify({"status": "error", "message": message}), 400
                try:
                    authorization = {
                        "user_id": g.user_id, "address": row["address"],
                        "to": row["to_address"], "value_wei": str(row["value_wei"]),
                        "chain_id": int(row["chain_id"]), "nonce": int(row["nonce"]),
                        "gas_limit": int(row["gas_limit"]),
                        "max_fee_per_gas": str(row["max_fee_per_gas"]),
                        "max_priority_fee_per_gas": str(row["max_priority_fee_per_gas"]),
                        "expires_at": int(row["expires_at"].timestamp()),
                    }
                    authorization_path = "/v1/wallets/authorize-transfer"
                    if row.get("transaction_kind") == "task_escrow":
                        cur.execute(
                            "SELECT * FROM task_escrows WHERE user_id=%s AND escrow_key=%s",
                            (g.user_id, row["escrow_key"]),
                        )
                        escrow = cur.fetchone()
                        if not escrow:
                            raise RuntimeError("Linked task escrow not found")
                        authorization.update({
                            "action": row["escrow_action"], "escrow_key": row["escrow_key"],
                            "recipient": escrow["recipient_address"],
                            "deadline": int(escrow["deadline"].timestamp()), "data": row["calldata"],
                        })
                        authorization_path = "/v1/escrows/authorize"
                    signed = _wallet_request(authorization_path, authorization, timeout=30)
                except RuntimeError as exc:
                    if getattr(exc, "status_code", 503) == 400:
                        cur.execute(
                            "UPDATE wallet_transactions SET status='expired', error_message=%s, updated_at=NOW() WHERE id=%s",
                            (str(exc), parsed_id),
                        )
                        _apply_escrow_transaction_result(cur, row, "failed")
                        conn.commit()
                        return jsonify({"status": "error", "message": str(exc)}), 409
                    raise
                raw_transaction = signed["raw_transaction"]
                transaction_hash = signed["transaction_hash"]
                cur.execute(
                    "UPDATE wallet_transactions SET status='signed', raw_transaction=%s, transaction_hash=%s, "
                    "code_hash=NULL, code_expires_at=NULL, updated_at=NOW() WHERE id=%s",
                    (raw_transaction, transaction_hash, parsed_id),
                )
        conn.commit()
    except Exception as exc:
        conn.rollback()
        log.exception("Wallet transaction authorization failed")
        return jsonify({"status": "error", "message": str(exc)}), 503
    finally:
        conn.close()

    try:
        broadcast = _wallet_request("/v1/wallets/broadcast", {
            "raw_transaction": raw_transaction,
            "transaction_hash": transaction_hash,
        }, timeout=30)
        explorer_url = f"{WALLET_EXPLORER_URL}/tx/{broadcast['transaction_hash']}"
        update_conn = get_db()
        try:
            with update_conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(
                    "UPDATE wallet_transactions SET status='broadcast', explorer_url=%s, error_message=NULL, "
                    "broadcast_at=COALESCE(broadcast_at, NOW()), updated_at=NOW() "
                    "WHERE id=%s AND user_id=%s RETURNING *",
                    (explorer_url, parsed_id, g.user_id),
                )
                row = cur.fetchone()
                if row and row.get("transaction_kind") == "task_escrow":
                    pending = {"create": "funding", "release": "release_pending", "refund": "refund_pending"}.get(row.get("escrow_action"))
                    if pending:
                        cur.execute(
                            "UPDATE task_escrows SET status=%s,updated_at=NOW() "
                            "WHERE user_id=%s AND escrow_key=%s",
                            (pending, g.user_id, row["escrow_key"]),
                        )
            update_conn.commit()
        finally:
            update_conn.close()
        return jsonify({"status": "success", "transaction": _wallet_transaction_payload(row)})
    except Exception as exc:
        update_conn = get_db()
        try:
            with update_conn.cursor() as cur:
                cur.execute(
                    "UPDATE wallet_transactions SET error_message=%s, updated_at=NOW() "
                    "WHERE id=%s AND user_id=%s AND status='signed'",
                    (str(exc), parsed_id, g.user_id),
                )
            update_conn.commit()
        finally:
            update_conn.close()
        return jsonify({
            "status": "error",
            "message": "Transaction authorized but broadcast failed. Retry confirmation to resend the exact same transaction.",
        }), 503


@app.route("/wallet/transactions/<transaction_id>", methods=["GET"])
@require_auth
def get_wallet_transaction(transaction_id):
    try:
        parsed_id = uuid.UUID(transaction_id)
    except ValueError:
        return jsonify({"status": "error", "message": "Invalid transaction ID"}), 400
    conn = get_db()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("SELECT * FROM wallet_transactions WHERE id=%s AND user_id=%s", (parsed_id, g.user_id))
            row = cur.fetchone()
            if not row:
                return jsonify({"status": "error", "message": "Transaction not found"}), 404
            if row["status"] == "broadcast" and row["transaction_hash"]:
                try:
                    result = _wallet_request("/v1/wallets/transaction-status", {
                        "transaction_hash": row["transaction_hash"]
                    })
                    chain_status = result.get("transaction_status")
                    if chain_status in ("confirmed", "failed"):
                        cur.execute(
                            "UPDATE wallet_transactions SET status=%s, "
                            "confirmed_at=CASE WHEN %s='confirmed' THEN NOW() ELSE confirmed_at END, "
                            "raw_transaction=NULL, updated_at=NOW() WHERE id=%s RETURNING *",
                            (chain_status, chain_status, parsed_id),
                        )
                        row = cur.fetchone()
                        _apply_escrow_transaction_result(cur, row, chain_status)
                        conn.commit()
                except Exception as exc:
                    log.warning("Could not refresh wallet transaction %s: %s", parsed_id, exc)
        return jsonify({"status": "success", "transaction": _wallet_transaction_payload(row)})
    finally:
        conn.close()


@app.route("/wallet/transactions", methods=["GET"])
@require_auth
def list_wallet_transactions():
    conn = get_db()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                "SELECT * FROM wallet_transactions WHERE user_id=%s ORDER BY created_at DESC LIMIT 20",
                (g.user_id,),
            )
            rows = cur.fetchall()
        return jsonify({"status": "success", "transactions": [_wallet_transaction_payload(row) for row in rows]})
    finally:
        conn.close()


@app.route("/rewards", methods=["GET"])
@require_auth
def get_rewards():
    conn = get_db()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            _ensure_reward_schema(cur)
            # Release the schema advisory lock before reconciliation or remote
            # wallet status checks. The remaining work starts a new transaction.
            conn.commit()
            # A completion may have committed while optional reward processing
            # failed. Reconcile on every read so missed XP repairs itself.
            _reconcile_completed_task_rewards(cur, g.user_id)
            cur.execute(
                "SELECT xp, tasks_completed FROM user_reward_stats WHERE user_id=%s",
                (g.user_id,),
            )
            stats = cur.fetchone() or {"xp": 0, "tasks_completed": 0}
            cur.execute(
                "SELECT * FROM user_achievements WHERE user_id=%s ORDER BY achievement_id",
                (g.user_id,),
            )
            achievement_rows = {row["achievement_code"]: row for row in cur.fetchall()}
            for code, row in list(achievement_rows.items()):
                if row["status"] != "broadcast" or not row["transaction_hash"]:
                    continue
                try:
                    chain = _wallet_request("/v1/wallets/transaction-status", {
                        "transaction_hash": row["transaction_hash"],
                    })
                    chain_status = chain.get("transaction_status")
                    if chain_status in ("confirmed", "failed"):
                        new_status = "minted" if chain_status == "confirmed" else "failed"
                        cur.execute(
                            "UPDATE user_achievements SET status=%s, "
                            "minted_at=CASE WHEN %s='minted' THEN NOW() ELSE minted_at END, "
                            "raw_transaction=NULL, updated_at=NOW() "
                            "WHERE user_id=%s AND achievement_code=%s RETURNING *",
                            (new_status, new_status, g.user_id, code),
                        )
                        achievement_rows[code] = cur.fetchone()
                except Exception as exc:
                    log.warning("Could not refresh achievement %s for %s: %s", code, g.user_id, exc)
        conn.commit()
        xp = int(stats["xp"])
        completed = int(stats["tasks_completed"])
        achievements = []
        for definition in REWARD_ACHIEVEMENTS:
            row = achievement_rows.get(definition["code"])
            item = dict(definition)
            item.update(_reward_payload(row) if row else {
                "status": "locked", "transaction_hash": None,
                "explorer_url": "", "error_message": "",
            })
            achievements.append(item)
        reward_config = {"enabled": False}
        if REWARD_BADGES_ENABLED:
            try:
                reward_config = _wallet_request("/v1/rewards/config", {})
            except Exception as exc:
                reward_config = {"enabled": False, "message": str(exc)}
        return jsonify({
            "status": "success",
            "stats": {
                "xp": xp, "tasks_completed": completed,
                "level": xp // REWARD_XP_PER_LEVEL,
                "xp_current": xp % REWARD_XP_PER_LEVEL,
                "xp_needed": REWARD_XP_PER_LEVEL,
            },
            "achievements": achievements,
            "badges_enabled": bool(REWARD_BADGES_ENABLED and reward_config.get("enabled")),
            "badge_config": reward_config,
        })
    except Exception as exc:
        conn.rollback()
        log.exception("Reward retrieval failed")
        return jsonify({"status": "error", "message": str(exc)}), 503
    finally:
        conn.close()


@app.route("/rewards/achievements/<achievement_code>/mint", methods=["POST"])
@require_auth
def mint_reward_achievement(achievement_code):
    if not REWARD_BADGES_ENABLED:
        return jsonify({"status": "error", "message": "On-chain achievement badges are disabled"}), 403
    definition = next((item for item in REWARD_ACHIEVEMENTS if item["code"] == achievement_code), None)
    if not definition:
        return jsonify({"status": "error", "message": "Unknown achievement"}), 404
    conn = get_db()
    raw_transaction = None
    transaction_hash = None
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            _ensure_reward_schema(cur)
            conn.commit()
            cur.execute("SELECT pg_advisory_xact_lock(hashtext('todoapp-reward-issuer'))")
            cur.execute(
                "SELECT * FROM user_achievements WHERE user_id=%s AND achievement_code=%s FOR UPDATE",
                (g.user_id, achievement_code),
            )
            row = cur.fetchone()
            if not row:
                return jsonify({"status": "error", "message": "Achievement is still locked"}), 409
            if row["status"] in ("broadcast", "minted"):
                return jsonify({"status": "success", "achievement": _reward_payload(row), "idempotent": True})
            if row["status"] == "signed" and row["raw_transaction"] and row["transaction_hash"]:
                raw_transaction = row["raw_transaction"]
                transaction_hash = row["transaction_hash"]
            else:
                cur.execute(
                    "SELECT 1 FROM user_achievements WHERE status IN ('signed','broadcast') "
                    "AND NOT (user_id=%s AND achievement_code=%s) LIMIT 1",
                    (g.user_id, achievement_code),
                )
                if cur.fetchone():
                    return jsonify({
                        "status": "error",
                        "message": "Another achievement mint is pending; wait for it to finish",
                    }), 409
                wallet = _ensure_user_wallet(conn, g.user_id)
                signed = _wallet_request("/v1/rewards/authorize-achievement", {
                    "recipient": wallet["address"],
                    "achievement_id": int(row["achievement_id"]),
                    "claim_id": row["claim_id"],
                }, timeout=30)
                raw_transaction = signed["raw_transaction"]
                transaction_hash = signed["transaction_hash"]
                cur.execute(
                    "UPDATE user_achievements SET status='signed', raw_transaction=%s, "
                    "transaction_hash=%s, error_message=NULL, updated_at=NOW() "
                    "WHERE user_id=%s AND achievement_code=%s",
                    (raw_transaction, transaction_hash, g.user_id, achievement_code),
                )
        conn.commit()
    except (ValueError, RuntimeError) as exc:
        conn.rollback()
        code = getattr(exc, "status_code", 503)
        return jsonify({"status": "error", "message": str(exc)}), 400 if code == 400 else 503
    except Exception as exc:
        conn.rollback()
        log.exception("Achievement authorization failed")
        return jsonify({"status": "error", "message": str(exc)}), 503
    finally:
        conn.close()

    try:
        broadcast = _wallet_request("/v1/wallets/broadcast", {
            "raw_transaction": raw_transaction,
            "transaction_hash": transaction_hash,
        }, timeout=30)
        explorer_url = f"{WALLET_EXPLORER_URL}/tx/{broadcast['transaction_hash']}"
        update_conn = get_db()
        try:
            with update_conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(
                    "UPDATE user_achievements SET status='broadcast', explorer_url=%s, "
                    "error_message=NULL, updated_at=NOW() WHERE user_id=%s AND achievement_code=%s "
                    "RETURNING *",
                    (explorer_url, g.user_id, achievement_code),
                )
                row = cur.fetchone()
            update_conn.commit()
        finally:
            update_conn.close()
        return jsonify({"status": "success", "achievement": _reward_payload(row)})
    except Exception as exc:
        update_conn = get_db()
        try:
            with update_conn.cursor() as cur:
                cur.execute(
                    "UPDATE user_achievements SET error_message=%s, updated_at=NOW() "
                    "WHERE user_id=%s AND achievement_code=%s AND status='signed'",
                    (str(exc), g.user_id, achievement_code),
                )
            update_conn.commit()
        finally:
            update_conn.close()
        return jsonify({
            "status": "error",
            "message": "Badge authorized but broadcast failed. Retry to resend the same transaction.",
        }), 503


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


@app.route("/crypto/devices/reset", methods=["POST"])
@require_auth
def reset_crypto_devices():
    """Reset lost device trust so the next registering device becomes active.

    Existing tasks are deliberately left untouched. The desktop recovery flow
    immediately replaces them after registering its new workspace key.
    """
    err = require_api_key()
    if err:
        return err

    data = request.get_json(silent=True) or {}
    if data.get("confirmation") != "RESET ENCRYPTION":
        return jsonify({
            "status": "error",
            "message": "Explicit RESET ENCRYPTION confirmation is required",
        }), 400

    conn = get_db()
    try:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM crypto_devices WHERE user_id = %s", (g.user_id,))
            removed_devices = cur.rowcount
            cur.execute("DELETE FROM crypto_workspaces WHERE user_id = %s", (g.user_id,))
        conn.commit()
        return jsonify({
            "status": "success",
            "removed_devices": removed_devices,
            "message": "Encryption devices reset",
        })
    except Exception as exc:
        conn.rollback()
        log.error("reset_crypto_devices error: %s", exc)
        return jsonify({"status": "error", "message": str(exc)}), 500
    finally:
        conn.close()


@app.route("/integrations/openclaw/meetings", methods=["POST"])
def receive_openclaw_meeting():
    """Receive a normalized meeting proposal from a trusted OpenClaw hook."""
    supplied = request.headers.get("X-OpenClaw-Secret", "")
    if not OPENCLAW_WEBHOOK_SECRET or not secrets.compare_digest(supplied, OPENCLAW_WEBHOOK_SECRET):
        return jsonify({"status": "error", "message": "Unauthorized"}), 401

    data = request.get_json(silent=True) or {}
    account_email = str(data.get("account_email") or "").strip().lower()
    external_id = str(data.get("external_id") or "").strip()[:300]
    title = str(data.get("title") or "").strip()[:300]
    if not EMAIL_RE.match(account_email) or not external_id or not title:
        return jsonify({"status": "error", "message": "account_email, external_id, and title are required"}), 400
    try:
        start_at = datetime.fromisoformat(str(data.get("start_at") or "").replace("Z", "+00:00"))
        if start_at.tzinfo is None:
            raise ValueError("start_at needs a timezone")
        end_text = str(data.get("end_at") or "").strip()
        end_at = datetime.fromisoformat(end_text.replace("Z", "+00:00")) if end_text else None
        if end_at and (end_at.tzinfo is None or end_at <= start_at):
            raise ValueError("invalid end_at")
    except ValueError:
        return jsonify({"status": "error", "message": "start_at/end_at must be timezone-aware ISO-8601 values"}), 400

    conn = get_db()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("SELECT id FROM users WHERE email = %s AND email_verified = TRUE", (account_email,))
            user = cur.fetchone()
            if not user:
                return jsonify({"status": "error", "message": "Verified TODO account not found"}), 404
            proposal_id = str(uuid.uuid4())
            cur.execute("""
                INSERT INTO meeting_proposals
                    (id, user_id, external_id, title, organizer, start_at, end_at, meeting_link, notes)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (user_id, external_id) DO NOTHING
                RETURNING id
            """, (proposal_id, user["id"], external_id, title,
                  str(data.get("organizer") or "")[:300], start_at, end_at,
                  str(data.get("meeting_link") or "")[:2000], str(data.get("notes") or "")[:5000]))
            inserted = cur.fetchone()
        conn.commit()
        return jsonify({"status": "success", "proposal_id": str(inserted["id"]) if inserted else None,
                        "duplicate": inserted is None}), 202 if inserted else 200
    except Exception as exc:
        conn.rollback()
        log.error("receive_openclaw_meeting error: %s", exc)
        return jsonify({"status": "error", "message": str(exc)}), 500
    finally:
        conn.close()


@app.route("/integrations/meetings", methods=["GET"])
@require_auth
def list_meeting_proposals():
    err = require_api_key()
    if err:
        return err
    conn = get_db()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("""
                SELECT id, external_id, title, organizer, start_at, end_at, meeting_link, notes, created_at
                FROM meeting_proposals
                WHERE user_id = %s AND status = 'pending'
                ORDER BY start_at, created_at LIMIT 20
            """, (g.user_id,))
            rows = cur.fetchall()
        for row in rows:
            for field in ("id", "start_at", "end_at", "created_at"):
                if row.get(field) is not None:
                    row[field] = str(row[field]) if field == "id" else row[field].isoformat()
        return jsonify({"status": "success", "proposals": rows})
    finally:
        conn.close()


@app.route("/integrations/meetings/<proposal_id>", methods=["PATCH"])
@require_auth
def decide_meeting_proposal(proposal_id):
    err = require_api_key()
    if err:
        return err
    decision = str((request.get_json(silent=True) or {}).get("decision") or "").lower()
    if decision not in ("accepted", "ignored"):
        return jsonify({"status": "error", "message": "decision must be accepted or ignored"}), 400
    conn = get_db()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                UPDATE meeting_proposals SET status = %s, decided_at = NOW()
                WHERE id = %s AND user_id = %s AND status = 'pending'
            """, (decision, proposal_id, g.user_id))
            updated = cur.rowcount
        conn.commit()
        if not updated:
            return jsonify({"status": "error", "message": "Meeting proposal not found"}), 404
        return jsonify({"status": "success"})
    except Exception as exc:
        conn.rollback()
        return jsonify({"status": "error", "message": str(exc)}), 500
    finally:
        conn.close()


def _validate_task_batch(tasks):
    if not isinstance(tasks, list):
        return "tasks must be a list"
    seen = set()
    for index, task in enumerate(tasks):
        if not isinstance(task, dict):
            return f"task at index {index} must be an object"
        task_id = str(task.get("id") or "").strip()
        if not task_id:
            return f"task at index {index} is missing an id"
        if task_id in seen:
            return f"duplicate task id in request: {task_id}"
        seen.add(task_id)
    return None


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
    preserve_remote = data.get("conflict_policy") == "preserve_remote"
    batch_error = _validate_task_batch(tasks)
    if batch_error:
        return jsonify({"status": "error", "message": batch_error}), 400

    if not user_id:
        return jsonify({"status": "error", "message": "user_id required"}), 400

    conn = get_db()
    try:
        with conn.cursor() as cur:
            completed_reward_ids = []
            for task in tasks:
                task_id = str(task.get("id", ""))
                completed = bool(task.get("completed", False))
                conflict_clause = (
                    "ON CONFLICT (user_id, task_id) DO NOTHING"
                    if preserve_remote else
                    """ON CONFLICT (user_id, task_id) DO UPDATE SET
                        title = EXCLUDED.title, due_date = EXCLUDED.due_date,
                        due_time = EXCLUDED.due_time, priority = EXCLUDED.priority,
                        notes = EXCLUDED.notes, completed = EXCLUDED.completed,
                        updated_at = NOW()"""
                )
                cur.execute(f"""
                    INSERT INTO tasks (user_id, task_id, title, due_date, due_time, priority, notes, completed, updated_at)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, NOW())
                    {conflict_clause}
                """, (
                    user_id,
                    task_id,
                    task.get("title", ""),
                    task.get("due_date"),
                    task.get("due_time"),
                    int(task.get("priority", 1)),
                    task.get("notes", ""),
                    completed,
                ))
                # Include already-completed rows too. The reward-event primary
                # key prevents duplicates and lets a retry heal a prior miss.
                if completed and cur.rowcount:
                    completed_reward_ids.append(task_id)
            rewards = _record_task_completion_rewards(cur, user_id, completed_reward_ids)
        conn.commit()
        return jsonify({"status": "success", "stored": len(tasks), "rewards": rewards})
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
                SELECT t.task_id, t.title, t.due_date, t.due_time, t.priority, t.notes,
                       t.completed, t.updated_at,
                       COALESCE(r.email_enabled, FALSE) AS reminder_email_enabled,
                       COALESCE(r.reminder_email, '') AS reminder_email,
                       COALESCE(r.sms_enabled, FALSE) AS reminder_sms_enabled,
                       COALESCE(r.phone_number, '') AS reminder_phone,
                       COALESCE(r.minutes_before, 15) AS reminder_minutes_before,
                       COALESCE(r.timezone_name, 'UTC') AS reminder_timezone
                FROM tasks t
                LEFT JOIN task_reminders r ON r.user_id = t.user_id AND r.task_id = t.task_id
                WHERE t.user_id = %s
                ORDER BY t.updated_at DESC
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
    completed_task_ids = data.get("completed_task_ids", [])
    deleted_task_ids = data.get("deleted_task_ids", [])
    batch_error = _validate_task_batch(local_tasks)
    if batch_error:
        return jsonify({"status": "error", "message": batch_error}), 400
    for field_name, task_ids in (
        ("completed_task_ids", completed_task_ids),
        ("deleted_task_ids", deleted_task_ids),
    ):
        if not isinstance(task_ids, list):
            return jsonify({"status": "error", "message": f"{field_name} must be a list"}), 400
        if any(not str(task_id).strip() for task_id in task_ids):
            return jsonify({"status": "error", "message": f"{field_name} contains an empty ID"}), 400
        if len(task_ids) > 5000:
            return jsonify({"status": "error", "message": f"{field_name} exceeds 5000 IDs"}), 400

    completed_task_ids = list(dict.fromkeys(str(task_id).strip() for task_id in completed_task_ids))
    deleted_task_ids = list(dict.fromkeys(str(task_id).strip() for task_id in deleted_task_ids))
    # Deletion wins if a task somehow appears in both pending queues.
    completed_task_ids = [task_id for task_id in completed_task_ids if task_id not in set(deleted_task_ids)]

    if not user_id:
        return jsonify({"status": "error", "message": "user_id required"}), 400

    conn = get_db()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            if completed_task_ids:
                cur.execute(
                    "UPDATE tasks SET completed = TRUE, updated_at = NOW() "
                    "WHERE user_id = %s AND task_id = ANY(%s) AND completed = FALSE ",
                    (user_id, completed_task_ids),
                )
            if deleted_task_ids:
                cur.execute(
                    "DELETE FROM reminder_deliveries WHERE user_id = %s AND task_id = ANY(%s)",
                    (user_id, deleted_task_ids),
                )
                cur.execute(
                    "DELETE FROM task_reminders WHERE user_id = %s AND task_id = ANY(%s)",
                    (user_id, deleted_task_ids),
                )
                cur.execute(
                    "DELETE FROM tasks WHERE user_id = %s AND task_id = ANY(%s)",
                    (user_id, deleted_task_ids),
                )
            # Import missing local tasks; the existing remote version wins collisions.
            for task in local_tasks:
                cur.execute("""
                    INSERT INTO tasks (user_id, task_id, title, due_date, due_time, priority, notes, completed, updated_at)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, NOW())
                    ON CONFLICT (user_id, task_id) DO NOTHING
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
            reward_candidates = list(completed_task_ids)
            reward_candidates.extend(
                str(task.get("id", "")) for task in local_tasks if task.get("completed", False)
            )
            reward_candidates = [task_id for task_id in dict.fromkeys(reward_candidates) if task_id]
            completed_reward_ids = []
            if reward_candidates:
                cur.execute(
                    "SELECT task_id FROM tasks WHERE user_id=%s AND task_id=ANY(%s) AND completed=TRUE",
                    (user_id, reward_candidates),
                )
                completed_reward_ids = [row["task_id"] for row in cur.fetchall()]
            rewards = _record_task_completion_rewards(cur, user_id, completed_reward_ids)
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
        return jsonify({"status": "success", "synced_tasks": synced, "rewards": rewards})
    except Exception as exc:
        conn.rollback()
        log.error("sync_tasks error: %s", exc)
        return jsonify({"status": "error", "message": str(exc)}), 500
    finally:
        conn.close()


@app.route("/tasks/<task_id>/reminder", methods=["PUT"])
@require_auth
def save_task_reminder(task_id):
    """Create, update, or disable delivery preferences for one task."""
    err = require_api_key()
    if err:
        return err

    data = request.get_json(silent=True) or {}
    user_id = g.user_id
    email_enabled = bool(data.get("email_enabled", False))
    sms_enabled = bool(data.get("sms_enabled", False))
    reminder_email = str(data.get("email") or "").strip().lower()
    phone = re.sub(r"[\s().-]", "", str(data.get("phone") or "").strip())
    timezone_name = str(data.get("timezone") or "UTC").strip()
    task_label = str(data.get("task_label") or "Task").strip()[:200] or "Task"
    recurring_days = data.get("recurring_days") or []
    recurring_time = str(data.get("recurring_time") or "").strip()
    recurring_schedule = data.get("recurring_schedule") or []
    try:
        minutes_before = int(data.get("minutes_before", 15))
    except (TypeError, ValueError):
        return jsonify({"status": "error", "message": "Reminder lead time must be a number"}), 400
    if not 0 <= minutes_before <= 10080:
        return jsonify({"status": "error", "message": "Reminder lead time must be between 0 and 10080 minutes"}), 400
    if email_enabled and not EMAIL_RE.match(reminder_email):
        return jsonify({"status": "error", "message": "A valid reminder email is required"}), 400
    if sms_enabled and not re.fullmatch(r"\+[1-9]\d{7,14}", phone):
        return jsonify({"status": "error", "message": "Phone number must use international format, such as +15551234567"}), 400
    valid_days = {"Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"}
    if not isinstance(recurring_schedule, list):
        return jsonify({"status": "error", "message": "Recurring schedule must be a list"}), 400
    scheduled_days = set()
    for entry in recurring_schedule:
        if not isinstance(entry, dict) or not isinstance(entry.get("days"), list) or not entry.get("days"):
            return jsonify({"status": "error", "message": "Each recurring schedule needs a days list"}), 400
        if any(day not in valid_days for day in entry["days"]):
            return jsonify({"status": "error", "message": "Invalid recurring schedule day"}), 400
        if scheduled_days.intersection(entry["days"]):
            return jsonify({"status": "error", "message": "A recurring day can only have one reminder time"}), 400
        try:
            datetime.strptime(str(entry.get("start_time") or ""), "%H:%M")
        except ValueError:
            return jsonify({"status": "error", "message": "Recurring schedule times must use HH:MM"}), 400
        scheduled_days.update(entry["days"])
    if recurring_schedule:
        day_order = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
        recurring_days = [day for day in day_order if day in scheduled_days]
        recurring_time = str(recurring_schedule[0].get("start_time") or "")
    if recurring_days:
        if not isinstance(recurring_days, list) or not recurring_days or any(day not in valid_days for day in recurring_days):
            return jsonify({"status": "error", "message": "Invalid recurring reminder days"}), 400
        try:
            datetime.strptime(recurring_time, "%H:%M")
        except ValueError:
            return jsonify({"status": "error", "message": "Recurring reminders require an HH:MM start time"}), 400
    try:
        ZoneInfo(timezone_name)
    except ZoneInfoNotFoundError:
        return jsonify({"status": "error", "message": "Invalid timezone"}), 400

    conn = get_db()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT 1 FROM tasks WHERE user_id = %s AND task_id = %s", (user_id, task_id))
            if not cur.fetchone():
                return jsonify({"status": "error", "message": "Task not found"}), 404
            cur.execute("""
                INSERT INTO task_reminders
                    (user_id, task_id, task_label, email_enabled, reminder_email,
                     sms_enabled, phone_number, minutes_before, timezone_name,
                     recurring_days, recurring_time, recurring_schedule, updated_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW())
                ON CONFLICT (user_id, task_id) DO UPDATE SET
                    task_label = EXCLUDED.task_label,
                    email_enabled = EXCLUDED.email_enabled,
                    reminder_email = EXCLUDED.reminder_email,
                    sms_enabled = EXCLUDED.sms_enabled,
                    phone_number = EXCLUDED.phone_number,
                    minutes_before = EXCLUDED.minutes_before,
                    timezone_name = EXCLUDED.timezone_name,
                    recurring_days = EXCLUDED.recurring_days,
                    recurring_time = EXCLUDED.recurring_time,
                    recurring_schedule = EXCLUDED.recurring_schedule,
                    updated_at = NOW()
            """, (user_id, task_id, task_label, email_enabled,
                  reminder_email if email_enabled else None, sms_enabled,
                  phone if sms_enabled else None, minutes_before, timezone_name,
                  recurring_days or None, recurring_time or None,
                  psycopg2.extras.Json(recurring_schedule)))
        conn.commit()
        return jsonify({"status": "success"})
    except Exception as exc:
        conn.rollback()
        log.error("save_task_reminder error: %s", exc)
        return jsonify({"status": "error", "message": str(exc)}), 500
    finally:
        conn.close()


@app.route("/tasks/<task_id>/complete", methods=["POST"])
@require_auth
def complete_task(task_id):
    """Mark one task complete without retrieving or rewriting its encrypted fields."""
    err = require_api_key()
    if err:
        return err

    user_id = g.user_id
    if not user_id:
        return jsonify({"status": "error", "message": "user_id required"}), 400

    conn = get_db()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE tasks SET completed = TRUE, updated_at = NOW() "
                "WHERE user_id = %s AND task_id = %s AND completed = FALSE RETURNING task_id",
                (user_id, task_id),
            )
            completed_row = cur.fetchone()
            updated = 1 if completed_row else 0
            if not updated:
                cur.execute(
                    "SELECT completed FROM tasks WHERE user_id = %s AND task_id = %s",
                    (user_id, task_id),
                )
                existing = cur.fetchone()
                if not existing:
                    conn.rollback()
                    return jsonify({"status": "error", "message": "Task not found"}), 404
            # Retry reward accounting even when the task was already complete;
            # the unique reward event makes this safe and self-healing.
            rewards = _record_task_completion_rewards(cur, user_id, [task_id])
        conn.commit()
        return jsonify({"status": "success", "completed": True, "updated": updated, "rewards": rewards})
    except Exception as exc:
        conn.rollback()
        log.error("complete_task error: %s", exc)
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
            cur.execute(
                "SELECT 1 FROM task_escrows WHERE user_id=%s AND task_id=%s "
                "AND status NOT IN ('released','refunded','failed') LIMIT 1",
                (user_id, task_id),
            )
            if cur.fetchone():
                return jsonify({"status": "error", "message": "Settle or refund this task's escrow before deleting it"}), 409
            cur.execute("DELETE FROM tasks WHERE user_id = %s AND task_id = %s", (user_id, task_id))
            deleted = cur.rowcount
            cur.execute("DELETE FROM task_reminders WHERE user_id = %s AND task_id = %s", (user_id, task_id))
            cur.execute("DELETE FROM reminder_deliveries WHERE user_id = %s AND task_id = %s", (user_id, task_id))
        conn.commit()
        return jsonify({"status": "success", "deleted": deleted})
    except Exception as exc:
        conn.rollback()
        return jsonify({"status": "error", "message": str(exc)}), 500
    finally:
        conn.close()


def _batch_task_ids(data):
    raw_ids = data.get("task_ids") if isinstance(data, dict) else None
    if not isinstance(raw_ids, list) or not raw_ids:
        return None, "task_ids must be a non-empty list"
    task_ids = list(dict.fromkeys(str(task_id).strip() for task_id in raw_ids if str(task_id).strip()))
    if not task_ids:
        return None, "task_ids must contain at least one ID"
    return task_ids, None


@app.route("/tasks/batch/complete", methods=["POST"])
@require_auth
def complete_tasks_batch():
    """Atomically complete multiple tasks belonging to the authenticated user."""
    err = require_api_key()
    if err:
        return err
    task_ids, validation_error = _batch_task_ids(request.get_json(silent=True) or {})
    if validation_error:
        return jsonify({"status": "error", "message": validation_error}), 400

    conn = get_db()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE tasks SET completed = TRUE, updated_at = NOW() "
                "WHERE user_id = %s AND task_id = ANY(%s) AND completed = FALSE RETURNING task_id",
                (g.user_id, task_ids),
            )
            completed_rows = cur.fetchall()
            updated = len(completed_rows)
            cur.execute(
                "SELECT task_id FROM tasks WHERE user_id = %s AND task_id = ANY(%s) AND completed=TRUE",
                (g.user_id, task_ids),
            )
            matched_rows = cur.fetchall()
            matched = len(matched_rows)
            rewards = _record_task_completion_rewards(
                cur, g.user_id, [row[0] for row in matched_rows]
            )
        conn.commit()
        return jsonify({
            "status": "success", "requested": len(task_ids), "matched": matched,
            "updated": updated, "rewards": rewards,
        })
    except Exception as exc:
        conn.rollback()
        log.error("complete_tasks_batch error: %s", exc)
        return jsonify({"status": "error", "message": str(exc)}), 500
    finally:
        conn.close()


@app.route("/tasks/batch/delete", methods=["POST"])
@require_auth
def delete_tasks_batch():
    """Atomically delete multiple tasks and their reminder state."""
    err = require_api_key()
    if err:
        return err
    task_ids, validation_error = _batch_task_ids(request.get_json(silent=True) or {})
    if validation_error:
        return jsonify({"status": "error", "message": validation_error}), 400

    conn = get_db()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT task_id FROM task_escrows WHERE user_id=%s AND task_id = ANY(%s) "
                "AND status NOT IN ('released','refunded','failed') LIMIT 1",
                (g.user_id, task_ids),
            )
            if cur.fetchone():
                return jsonify({"status": "error", "message": "Settle or refund task escrows before deleting those tasks"}), 409
            cur.execute("DELETE FROM tasks WHERE user_id = %s AND task_id = ANY(%s)", (g.user_id, task_ids))
            deleted = cur.rowcount
            cur.execute("DELETE FROM task_reminders WHERE user_id = %s AND task_id = ANY(%s)", (g.user_id, task_ids))
            cur.execute("DELETE FROM reminder_deliveries WHERE user_id = %s AND task_id = ANY(%s)", (g.user_id, task_ids))
        conn.commit()
        return jsonify({"status": "success", "requested": len(task_ids), "deleted": deleted})
    except Exception as exc:
        conn.rollback()
        log.error("delete_tasks_batch error: %s", exc)
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
    if request.headers.get("X-Confirm-Replace", "").strip().lower() != "true":
        return jsonify({
            "status": "error",
            "message": "Full replacement requires explicit force-push confirmation",
        }), 409

    data = request.get_json(silent=True) or {}
    if data.get("confirmation") != "FORCE REPLACE ALL TASKS":
        return jsonify({
            "status": "error",
            "message": "Full replacement requires the explicit confirmation phrase",
        }), 409
    user_id = g.user_id
    tasks = data.get("tasks", [])
    batch_error = _validate_task_batch(tasks)
    if batch_error:
        return jsonify({"status": "error", "message": batch_error}), 400

    if not user_id:
        return jsonify({"status": "error", "message": "user_id required"}), 400

    conn = get_db()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT 1 FROM task_escrows WHERE user_id=%s "
                "AND status NOT IN ('released','refunded','failed') LIMIT 1",
                (user_id,),
            )
            if cur.fetchone():
                return jsonify({
                    "status": "error",
                    "message": "Settle or refund all task escrows before replacing the task list",
                }), 409
            # Wipe everything for this user
            cur.execute("DELETE FROM reminder_deliveries WHERE user_id = %s", (user_id,))
            cur.execute("DELETE FROM task_reminders WHERE user_id = %s", (user_id,))
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
