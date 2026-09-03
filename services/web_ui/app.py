"""
Web UI Service for TODO App CVM
Serves a browser-based interface matching the Python desktop app.
Proxies task/AI/sync requests to the internal CVM services.
"""

import os
import json
import hashlib
import base64
import logging
import sqlite3
import uuid
import re
from datetime import datetime, timezone, date, timedelta
from pathlib import Path

import requests as req
from flask import Flask, render_template, request, jsonify, redirect, url_for, Response, g
from flask_cors import CORS

from auth import auth_bp, login_required, current_user_id, is_logged_in, get_valid_access_token

try:
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    from cryptography.hazmat.primitives.kdf.hkdf import HKDF
    ASYMMETRIC_CRYPTO_AVAILABLE = True
except ImportError:
    hashes = None
    serialization = None
    ec = None
    AESGCM = None
    HKDF = None
    ASYMMETRIC_CRYPTO_AVAILABLE = False

logging.basicConfig(level=os.getenv("LOG_LEVEL", "info").upper())
log = logging.getLogger(__name__)

app = Flask(__name__)
CORS(app)

# ---------------------------------------------------------------------------
# Session / auth configuration
# ---------------------------------------------------------------------------
app.secret_key = os.environ.get("SECRET_KEY", "")
if not app.secret_key:
    log.warning("SECRET_KEY is not set — sessions will not survive a restart. Set it in the CVM env vars.")
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
app.config["PERMANENT_SESSION_LIFETIME"] = 60 * 60 * 24 * 30  # 30 days, matches refresh token TTL
app.register_blueprint(auth_bp)

@app.after_request
def disable_api_caching(response):
    """Task-backed API responses must always reflect the latest backend state."""
    if request.path.startswith("/api/"):
        response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
    return response

# ---------------------------------------------------------------------------
# Internal service URLs (same CVM, internal Docker network)
# ---------------------------------------------------------------------------
BACKEND_URL      = os.getenv("BACKEND_URL",   "http://backend:5000")
AI_URL           = os.getenv("AI_URL",         "http://ai_inference:5001")
SYNC_URL         = os.getenv("SYNC_URL",       "http://task_sync:5002")
SCHEDULER_URL    = os.getenv("SCHEDULER_URL",  "http://scheduler:5003")
OPENCLAW_URL     = os.getenv("OPENCLAW_URL",   "http://openclaw:18789")
API_KEY          = os.getenv("API_KEY",        "")
AI_PROXY_TIMEOUT = int(os.getenv("AI_PROXY_TIMEOUT", "100"))

TASK_ENCRYPTION_PREFIX = "ENC2:"
DAILY_NOTES_PREFIX = "[CVM_DAILY]"
KEY_WRAP_INFO = b"todoapp-keywrap-v1"
TASK_INFO_PREFIX = "todoapp-task-v2"
_WORKSPACE_KEY_CACHE = {}

BUILTIN_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "get_tasks",
            "description": "Get the user's current to-do list tasks, including notes and email/SMS reminder settings.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "add_task",
            "description": "Add a task to the user's to-do list. Dates must use MM-DD-YYYY.",
            "parameters": {
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "due_date": {"type": "string", "description": "Due date in MM-DD-YYYY format"},
                    "due_time": {"type": "string", "description": "Optional time such as 03:30 PM"},
                    "priority": {"type": "integer", "minimum": 1, "maximum": 5},
                    "notes": {"type": "string", "description": "Optional task notes supplied by the user"},
                    "reminder_email_enabled": {"type": "boolean"},
                    "reminder_email": {"type": "string", "description": "Email reminder recipient"},
                    "reminder_sms_enabled": {"type": "boolean"},
                    "reminder_phone": {"type": "string", "description": "SMS number such as +15551234567"},
                    "reminder_minutes_before": {"type": "integer", "minimum": 0, "maximum": 10080},
                },
                "required": ["title", "due_date"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "update_task",
            "description": "Update an existing task. Call get_tasks first to obtain its task_id.",
            "parameters": {
                "type": "object",
                "properties": {
                    "task_id": {"type": "string"}, "title": {"type": "string"},
                    "due_date": {"type": "string"}, "due_time": {"type": "string"},
                    "priority": {"type": "integer", "minimum": 1, "maximum": 5},
                    "notes": {"type": "string", "description": "Replacement task notes"},
                    "reminder_email_enabled": {"type": "boolean"},
                    "reminder_email": {"type": "string"},
                    "reminder_sms_enabled": {"type": "boolean"},
                    "reminder_phone": {"type": "string"},
                    "reminder_minutes_before": {"type": "integer", "minimum": 0, "maximum": 10080},
                },
                "required": ["task_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "complete_task",
            "description": "Mark an existing task complete. Call get_tasks first to obtain its task_id.",
            "parameters": {"type": "object", "properties": {"task_id": {"type": "string"}}, "required": ["task_id"]},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "delete_task",
            "description": "Delete an existing task. Call get_tasks first to obtain its task_id.",
            "parameters": {"type": "object", "properties": {"task_id": {"type": "string"}}, "required": ["task_id"]},
        },
    },
    {
        "type": "function", "function": {
            "name": "get_daily_tasks",
            "description": "Get recurring daily tasks. Returns schedule IDs, weekdays, start/end times, and today's completion state.",
            "parameters": {"type": "object", "properties": {
                "day": {"type": "string", "enum": ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"], "description": "Optional weekday filter"},
                "date": {"type": "string", "description": "Local date in YYYY-MM-DD"}
            }},
        },
    },
    {
        "type": "function", "function": {
            "name": "add_daily_task",
            "description": "Add a recurring daily task schedule. Times use 24-hour HH:MM storage format.",
            "parameters": {"type": "object", "properties": {
                "title": {"type": "string"},
                "days": {"type": "array", "items": {"type": "string", "enum": ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]}},
                "start_time": {"type": "string", "description": "HH:MM"},
                "end_time": {"type": "string", "description": "Optional HH:MM"},
                "notes": {"type": "string"},
                "reminder_email_enabled": {"type": "boolean"}, "reminder_email": {"type": "string"},
                "reminder_sms_enabled": {"type": "boolean"}, "reminder_phone": {"type": "string"},
                "reminder_minutes_before": {"type": "integer", "minimum": 0, "maximum": 10080}
            }, "required": ["title", "days", "start_time"]},
        },
    },
    {
        "type": "function", "function": {
            "name": "update_daily_task",
            "description": "Update a recurring daily task. Call get_daily_tasks first and use its exact task_id.",
            "parameters": {"type": "object", "properties": {
                "task_id": {"type": "string"}, "title": {"type": "string"},
                "days": {"type": "array", "items": {"type": "string", "enum": ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]}},
                "start_time": {"type": "string"}, "end_time": {"type": "string"},
                "notes": {"type": "string"},
                "reminder_email_enabled": {"type": "boolean"}, "reminder_email": {"type": "string"},
                "reminder_sms_enabled": {"type": "boolean"}, "reminder_phone": {"type": "string"},
                "reminder_minutes_before": {"type": "integer", "minimum": 0, "maximum": 10080}
            }, "required": ["task_id"]},
        },
    },
    {
        "type": "function", "function": {
            "name": "complete_daily_task",
            "description": "Mark a recurring daily task completed for the specified local date. Call get_daily_tasks first.",
            "parameters": {"type": "object", "properties": {
                "task_id": {"type": "string"}, "date": {"type": "string", "description": "Local date in YYYY-MM-DD"}
            }, "required": ["task_id", "date"]},
        },
    },
    {
        "type": "function", "function": {
            "name": "delete_daily_task",
            "description": "Delete a recurring daily task schedule. Call get_daily_tasks first.",
            "parameters": {"type": "object", "properties": {"task_id": {"type": "string"}}, "required": ["task_id"]},
        },
    },
]

DATA_DIR = Path("/app/data")
DATA_DIR.mkdir(parents=True, exist_ok=True)
DB_PATH = DATA_DIR / "web_ui.db"

# ---------------------------------------------------------------------------
# Local DB for daily tasks and character stats
# ---------------------------------------------------------------------------
def get_db():
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS daily_tasks (
            id       INTEGER PRIMARY KEY AUTOINCREMENT,
            title    TEXT NOT NULL,
            done     INTEGER DEFAULT 0,
            date     TEXT DEFAULT (date('now')),
            created  TEXT DEFAULT (datetime('now'))
        );
        CREATE TABLE IF NOT EXISTS character (
            key   TEXT PRIMARY KEY,
            value TEXT
        );
        CREATE TABLE IF NOT EXISTS settings (
            key   TEXT PRIMARY KEY,
            value TEXT
        );
    """)
    daily_columns = {row[1] for row in conn.execute("PRAGMA table_info(daily_tasks)").fetchall()}
    if "user_id" not in daily_columns:
        try:
            conn.execute("ALTER TABLE daily_tasks ADD COLUMN user_id TEXT NOT NULL DEFAULT ''")
        except sqlite3.OperationalError as exc:
            # Multiple Gunicorn workers can race on the one-time migration.
            if "duplicate column name" not in str(exc).lower():
                raise
    conn.commit()
    conn.close()

def _get_setting(key, default=""):
    conn = get_db()
    row = conn.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
    conn.close()
    return row["value"] if row else default

def _set_setting(key, value):
    conn = get_db()
    conn.execute("INSERT OR REPLACE INTO settings(key,value) VALUES(?,?)", (key, str(value)))
    conn.commit()
    conn.close()

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _headers():
    """Attach the shared deployment API key plus this session's bearer token.
    get_valid_access_token() transparently refreshes an expiring access token."""
    h = {"Content-Type": "application/json"}
    if API_KEY:
        h["X-API-Key"] = API_KEY
    token = get_valid_access_token()
    if token:
        h["Authorization"] = f"Bearer {token}"
    return h

def _backend(method, path, **kwargs):
    """Call the backend storage service."""
    url = f"{BACKEND_URL}{path}"
    kwargs.setdefault("headers", _headers())
    kwargs.setdefault("timeout", 15)
    return req.request(method, url, **kwargs)

def _ai(method, path, **kwargs):
    url = f"{AI_URL}{path}"
    kwargs.setdefault("headers", _headers())
    kwargs.setdefault("timeout", AI_PROXY_TIMEOUT)
    return req.request(method, url, **kwargs)

def _task_color(due_date_str):
    """Return 'overdue', 'today', or ''."""
    try:
        due = datetime.strptime(due_date_str, "%m-%d-%Y").date()
        today = date.today()
        if due < today:
            return "overdue"
        if due == today:
            return "today"
    except Exception:
        pass
    return ""


def _b64url_encode(value):
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def _b64url_decode(value):
    if not isinstance(value, str):
        raise ValueError("Expected Base64 string")
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def _task_context(user_id, task_id):
    return f"{TASK_INFO_PREFIX}|{user_id}|{task_id}".encode("utf-8")


def _key_wrap_context(user_id, device_id):
    return f"{KEY_WRAP_INFO.decode()}|{user_id}|{device_id}".encode("utf-8")


def _private_key_to_b64(private_key):
    data = private_key.private_bytes(
        serialization.Encoding.DER,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )
    return _b64url_encode(data)


def _private_key_from_b64(value):
    private_key = serialization.load_der_private_key(_b64url_decode(value), password=None)
    if not isinstance(private_key, ec.EllipticCurvePrivateKey) or not isinstance(private_key.curve, ec.SECP256R1):
        raise ValueError("Expected P-256 private key")
    return private_key


def _public_key_to_b64(public_key):
    data = public_key.public_bytes(
        serialization.Encoding.X962,
        serialization.PublicFormat.UncompressedPoint,
    )
    return _b64url_encode(data)


def _public_key_from_b64(value):
    try:
        return ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), _b64url_decode(value))
    except (TypeError, ValueError) as exc:
        raise ValueError("Invalid P-256 public key") from exc


def _derive_wrapping_key(private_key, peer_public_key, salt):
    shared_secret = private_key.exchange(ec.ECDH(), peer_public_key)
    return HKDF(
        algorithm=hashes.SHA256(),
        length=32,
        salt=salt,
        info=KEY_WRAP_INFO,
    ).derive(shared_secret)


def _wrap_workspace_key(workspace_key, recipient_public_key, user_id, device_id):
    recipient = _public_key_from_b64(recipient_public_key)
    ephemeral_private = ec.generate_private_key(ec.SECP256R1())
    salt = os.urandom(16)
    nonce = os.urandom(12)
    wrapping_key = _derive_wrapping_key(ephemeral_private, recipient, salt)
    ciphertext = AESGCM(wrapping_key).encrypt(nonce, workspace_key, _key_wrap_context(user_id, device_id))
    return {
        "v": 1,
        "ephemeral_public_key": _public_key_to_b64(ephemeral_private.public_key()),
        "salt": _b64url_encode(salt),
        "nonce": _b64url_encode(nonce),
        "ciphertext": _b64url_encode(ciphertext),
    }


def _unwrap_workspace_key(envelope, recipient_private_key, user_id, device_id):
    if not isinstance(envelope, dict) or envelope.get("v") != 1:
        raise ValueError("Unsupported workspace-key envelope")
    ephemeral_public = _public_key_from_b64(envelope["ephemeral_public_key"])
    salt = _b64url_decode(envelope["salt"])
    nonce = _b64url_decode(envelope["nonce"])
    ciphertext = _b64url_decode(envelope["ciphertext"])
    wrapping_key = _derive_wrapping_key(recipient_private_key, ephemeral_public, salt)
    workspace_key = AESGCM(wrapping_key).decrypt(
        nonce,
        ciphertext,
        _key_wrap_context(user_id, device_id),
    )
    if len(workspace_key) != 32:
        raise ValueError("Invalid workspace key")
    return workspace_key


def _encrypt_task_v2(task, workspace_key, user_id):
    t = dict(task)
    task_id = str(t.get("id") or t.get("task_id") or "")
    if not task_id:
        raise ValueError("Task ID required")
    sensitive = json.dumps(
        {"title": t.get("title", ""), "notes": t.get("notes", "")},
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    nonce = os.urandom(12)
    ciphertext = AESGCM(workspace_key).encrypt(nonce, sensitive, _task_context(user_id, task_id))
    payload = _b64url_encode(
        json.dumps(
            {"v": 2, "nonce": _b64url_encode(nonce), "ciphertext": _b64url_encode(ciphertext)},
            separators=(",", ":"),
        ).encode("utf-8")
    )
    t["title"] = "[Encrypted]"
    t["notes"] = TASK_ENCRYPTION_PREFIX + payload
    return t


def _decrypt_task_v2(task, workspace_key, user_id):
    t = dict(task)
    notes = t.get("notes", "")
    if not (isinstance(notes, str) and notes.startswith(TASK_ENCRYPTION_PREFIX)):
        return t
    task_id = str(t.get("id") or t.get("task_id") or "")
    if not task_id:
        raise ValueError("Task ID required")
    payload = json.loads(_b64url_decode(notes[len(TASK_ENCRYPTION_PREFIX):]).decode("utf-8"))
    if payload.get("v") != 2:
        raise ValueError("Unsupported ENC2 version")
    nonce = _b64url_decode(payload["nonce"])
    ciphertext = _b64url_decode(payload["ciphertext"])
    sensitive = json.loads(
        AESGCM(workspace_key).decrypt(
            nonce,
            ciphertext,
            _task_context(user_id, task_id),
        ).decode("utf-8")
    )
    t["title"] = sensitive.get("title", "")
    t["notes"] = sensitive.get("notes", "")
    return t


def _ensure_web_device_material():
    """Generate and persist web-ui specific device keys (never desktop keys)."""
    if not ASYMMETRIC_CRYPTO_AVAILABLE:
        return None

    device_id = _get_setting("crypto_device_id", "")
    enc_priv_b64 = _get_setting("crypto_encryption_private_key", "")
    sign_priv_b64 = _get_setting("crypto_signing_private_key", "")

    try:
        if device_id and enc_priv_b64 and sign_priv_b64:
            enc_private = _private_key_from_b64(enc_priv_b64)
            sign_private = _private_key_from_b64(sign_priv_b64)
            return {
                "device_id": device_id,
                "enc_private": enc_private,
                "sign_private": sign_private,
                "enc_public": _public_key_to_b64(enc_private.public_key()),
                "sign_public": _public_key_to_b64(sign_private.public_key()),
            }
    except Exception:
        pass

    enc_private = ec.generate_private_key(ec.SECP256R1())
    sign_private = ec.generate_private_key(ec.SECP256R1())
    device_id = uuid.uuid4().hex

    _set_setting("crypto_device_id", device_id)
    _set_setting("crypto_encryption_private_key", _private_key_to_b64(enc_private))
    _set_setting("crypto_signing_private_key", _private_key_to_b64(sign_private))

    return {
        "device_id": device_id,
        "enc_private": enc_private,
        "sign_private": sign_private,
        "enc_public": _public_key_to_b64(enc_private.public_key()),
        "sign_public": _public_key_to_b64(sign_private.public_key()),
    }


def _workspace_key_for_user(user_id):
    """Return this web-ui device's unwrapped workspace key for ENC2, if approved."""
    if user_id in _WORKSPACE_KEY_CACHE:
        return _WORKSPACE_KEY_CACHE[user_id]
    if not ASYMMETRIC_CRYPTO_AVAILABLE:
        return None

    material = _ensure_web_device_material()
    if not material:
        return None

    try:
        resp = _backend("GET", "/crypto/devices")
    except Exception:
        return None

    if resp.status_code == 404:
        # Backend not upgraded for ENC2.
        return None
    if resp.status_code != 200:
        return None

    devices = resp.json().get("devices", [])
    own = next((d for d in devices if d.get("device_id") == material["device_id"]), None)

    if own is None:
        candidate_key = os.urandom(32)
        wrapped = _wrap_workspace_key(
            candidate_key,
            material["enc_public"],
            user_id,
            material["device_id"],
        )
        register_payload = {
            "device_id": material["device_id"],
            "encryption_public_key": material["enc_public"],
            "signing_public_key": material["sign_public"],
            "wrapped_workspace_key": wrapped,
        }
        try:
            reg_resp = _backend("POST", "/crypto/devices/register", json=register_payload)
        except Exception:
            return None
        if reg_resp.status_code in (200, 201):
            own = reg_resp.json().get("device", {})
            if own.get("status") == "active":
                _WORKSPACE_KEY_CACHE[user_id] = candidate_key
                return candidate_key
        return None

    if own.get("status") != "active":
        return None

    wrapped = own.get("wrapped_workspace_key")
    if not wrapped:
        return None

    try:
        workspace_key = _unwrap_workspace_key(
            wrapped,
            material["enc_private"],
            user_id,
            material["device_id"],
        )
        _WORKSPACE_KEY_CACHE[user_id] = workspace_key
        return workspace_key
    except Exception:
        return None


def _encrypt_task_if_needed(task, user_id):
    """Encrypt title+notes with ENC2 when this web device has been approved."""
    t = dict(task)
    workspace_key = _workspace_key_for_user(user_id)
    if workspace_key:
        return _encrypt_task_v2(t, workspace_key, user_id)
    raise RuntimeError("Web UI device has not been approved for encrypted task storage yet")


def _encrypt_tasks(tasks, user_id):
    return [_encrypt_task_if_needed(task, user_id) for task in tasks]


def _decrypt_task_if_needed(task, user_id):
    """Decrypt ENC2 with the web UI device's workspace key."""
    t = dict(task)
    notes = t.get("notes", "")

    if isinstance(notes, str) and notes.startswith(TASK_ENCRYPTION_PREFIX):
        workspace_key = _workspace_key_for_user(user_id)
        if not workspace_key:
            t["title"] = "[Encrypted - web device approval required]"
            t["notes"] = ""
            return t
        try:
            return _decrypt_task_v2(t, workspace_key, user_id)
        except Exception:
            t["title"] = "[Encrypted - different key or corrupted payload]"
            t["notes"] = ""
            return t
    return t


def _decrypt_tasks(tasks, user_id):
    return [_decrypt_task_if_needed(task, user_id) for task in tasks]


def _decode_daily_payload(notes_text):
    """Decode desktop daily payload stored in notes, or return None."""
    if not isinstance(notes_text, str) or not notes_text.startswith(DAILY_NOTES_PREFIX):
        return None
    try:
        payload = json.loads(notes_text[len(DAILY_NOTES_PREFIX):])
        if isinstance(payload, dict) and payload.get("kind") == "daily":
            return payload
    except Exception:
        pass
    return None


def _encode_daily_payload(raw_text, completed=False, completed_date=None, notes=""):
    payload = {
        "kind": "daily",
        "raw": raw_text,
        "completed": bool(completed),
        "completed_date": completed_date if completed else None,
        "notes": str(notes or ""),
    }
    return DAILY_NOTES_PREFIX + json.dumps(payload, ensure_ascii=True, separators=(",", ":"))


DAILY_RAW_RE = re.compile(
    r"^(?P<days>[A-Za-z,]+)\s+(?P<start>\d{2}:\d{2})(?:-(?P<end>\d{2}:\d{2}))?\s+-\s+(?P<title>.+)$"
)


def _parse_daily_raw(raw_text):
    """Parse the desktop's `Mon,Wed 09:00-10:00 - Task` storage format."""
    raw = str(raw_text or "").strip()
    match = DAILY_RAW_RE.match(raw)
    if not match:
        return {"raw": raw, "title": raw, "days": ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"],
                "start_time": "00:00", "end_time": ""}
    parsed = match.groupdict()
    return {"raw": raw, "title": parsed["title"], "days": parsed["days"].split(","),
            "start_time": parsed["start"], "end_time": parsed.get("end") or ""}


def _build_daily_raw(title, days, start_time, end_time=""):
    day_order = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    selected = [day for day in day_order if day in days]
    if not str(title).strip() or not selected:
        raise ValueError("Task name and at least one day are required")
    datetime.strptime(start_time, "%H:%M")
    if end_time:
        datetime.strptime(end_time, "%H:%M")
    time_text = start_time + (f"-{end_time}" if end_time else "")
    return f"{','.join(selected)} {time_text} - {str(title).strip()}"


def _split_remote_tasks(tasks):
    """Split remote backend tasks into regular-todo and daily-marker lists."""
    regular = []
    daily = []

    for task in tasks:
        daily_payload = _decode_daily_payload(task.get("notes", ""))
        if daily_payload:
            remote_task_id = str(task.get("task_id") or task.get("id") or "")
            raw = (daily_payload.get("raw") or task.get("title") or "").strip()
            if not raw:
                continue
            completed_date = daily_payload.get("completed_date")
            if not completed_date and daily_payload.get("completed") and task.get("updated_at"):
                completed_date = str(task["updated_at"])[:10]
            requested_date = getattr(g, "daily_date", None) or date.today().isoformat()
            done = bool(daily_payload.get("completed", task.get("completed", False))) and completed_date == requested_date
            parsed = _parse_daily_raw(raw)
            requested_day = getattr(g, "daily_day", None) or datetime.now().strftime("%a")
            daily.append({
                "id": f"remote:{remote_task_id}",
                **parsed,
                "done": done,
                "scheduled_today": requested_day in parsed["days"],
                "source": "remote",
                "remote_task_id": remote_task_id,
                "notes": str(daily_payload.get("notes") or ""),
                "reminder_email_enabled": bool(task.get("reminder_email_enabled", False)),
                "reminder_email": task.get("reminder_email", ""),
                "reminder_sms_enabled": bool(task.get("reminder_sms_enabled", False)),
                "reminder_phone": task.get("reminder_phone", ""),
                "reminder_minutes_before": task.get("reminder_minutes_before", 15),
            })
        else:
            regular.append(task)

    daily.sort(key=lambda item: (
        not item.get("scheduled_today", False),
        item.get("start_time", "00:00"),
        item.get("title", "").lower(),
    ))
    return regular, daily

def _execute_tool_call(tool_call, local_date=None, local_day=None, local_timezone="UTC"):
    name = tool_call.get("function", {}).get("name")
    raw_arguments = tool_call.get("function", {}).get("arguments") or {}
    try:
        arguments = json.loads(raw_arguments) if isinstance(raw_arguments, str) else raw_arguments
        if not isinstance(arguments, dict):
            raise ValueError("Tool arguments must be an object")
    except (ValueError, TypeError, json.JSONDecodeError) as exc:
        return json.dumps({"status": "error", "message": f"Invalid tool arguments: {exc}"})
    if name == "get_daily_tasks":
        arguments.setdefault("date", local_date or date.today().isoformat())
        arguments.setdefault("day", local_day or datetime.now().strftime("%a"))
    elif name == "complete_daily_task":
        arguments.setdefault("date", local_date or date.today().isoformat())

    def reminder_changes_from_tool():
        """Accept the current flat schema and older nested calls already in chat history."""
        if "reminder" in arguments:
            nested = arguments.get("reminder")
            if not isinstance(nested, dict):
                raise ValueError("reminder must be an object")
            return dict(nested)
        mapping = {
            "reminder_email_enabled": "email_enabled",
            "reminder_email": "email",
            "reminder_sms_enabled": "sms_enabled",
            "reminder_phone": "phone",
            "reminder_minutes_before": "minutes_before",
        }
        changes = {target: arguments[source] for source, target in mapping.items() if source in arguments}
        if "email" in changes and "email_enabled" not in changes:
            changes["email_enabled"] = bool(str(changes["email"]).strip())
        if "phone" in changes and "sms_enabled" not in changes:
            changes["sms_enabled"] = bool(str(changes["phone"]).strip())
        return changes if changes else None

    def load_regular_tasks():
        user_id = current_user_id()
        response = _backend("GET", "/tasks/retrieve")
        if response.status_code != 200:
            raise RuntimeError(f"Task backend returned {response.status_code}")
        all_tasks = _decrypt_tasks(response.json().get("tasks", []), user_id)
        regular, _daily = _split_remote_tasks(all_tasks)
        return user_id, regular

    def load_all_remote_tasks():
        user_id = current_user_id()
        response = _backend("GET", "/tasks/retrieve")
        if response.status_code != 200:
            raise RuntimeError(f"Task backend returned {response.status_code}: {response.text}")
        return user_id, _decrypt_tasks(response.json().get("tasks", []), user_id)

    if name == "get_tasks":
        try:
            _user_id, tasks = load_regular_tasks()
            summary = [{
                "task_id": str(t.get("task_id") or t.get("id") or ""),
                "title": t.get("title"), "due_date": t.get("due_date"),
                "due_time": t.get("due_time"), "priority": t.get("priority"),
                "notes": t.get("notes", ""), "completed": t.get("completed", False),
                "reminder": {
                    "email_enabled": bool(t.get("reminder_email_enabled", False)),
                    "email": t.get("reminder_email", ""),
                    "sms_enabled": bool(t.get("reminder_sms_enabled", False)),
                    "phone": t.get("reminder_phone", ""),
                    "minutes_before": t.get("reminder_minutes_before", 15),
                    "timezone": t.get("reminder_timezone", "UTC"),
                },
            } for t in tasks]
            return json.dumps({"status": "success", "tasks": summary})
        except Exception as e:
            return json.dumps({"status": "error", "message": str(e)})

    if name == "add_task":
        try:
            user_id = current_user_id()
            title = str(arguments.get("title", "")).strip()
            due_date = str(arguments.get("due_date", "")).strip()
            if not title or not due_date:
                raise ValueError("title and due_date are required")
            datetime.strptime(due_date, "%m-%d-%Y")
            priority = max(1, min(5, int(arguments.get("priority", 1))))
            task_id = uuid.uuid4().hex[:12]
            task = {"id": task_id, "title": title, "due_date": due_date,
                    "due_time": str(arguments.get("due_time", "")), "priority": str(priority),
                    "notes": str(arguments.get("notes", "No notes")), "completed": False}
            response = _backend("POST", "/tasks/store", json={"tasks": _encrypt_tasks([task], user_id)})
            if response.status_code != 200:
                raise RuntimeError(response.text)
            reminder = reminder_changes_from_tool()
            if reminder is not None:
                if not isinstance(reminder, dict):
                    raise ValueError("reminder must be an object")
                if (reminder.get("email_enabled") or reminder.get("sms_enabled")) and not task["due_time"]:
                    raise ValueError("A due_time is required when reminders are enabled")
                reminder = {**reminder, "timezone": local_timezone or "UTC"}
                reminder_response = _store_reminder_preferences(
                    task_id, title, {"reminder": reminder}
                )
                if reminder_response.status_code != 200:
                    raise RuntimeError(reminder_response.text)
            return json.dumps({"status": "success", "message": f"Added task: {title}", "task_id": task_id})
        except Exception as exc:
            return json.dumps({"status": "error", "message": str(exc)})

    if name in ("update_task", "complete_task", "delete_task"):
        try:
            task_id = str(arguments.get("task_id", "")).strip()
            if not task_id:
                raise ValueError("task_id is required")
            user_id, tasks = load_regular_tasks()
            task = next((t for t in tasks if str(t.get("task_id") or t.get("id")) == task_id), None)
            if not task:
                raise ValueError("Task not found; call get_tasks and use its exact task_id")
            title = task.get("title", "")
            if name == "delete_task":
                response = _backend("DELETE", f"/tasks/{task_id}")
                if response.status_code != 200:
                    raise RuntimeError(response.text)
                return json.dumps({"status": "success", "message": f"Deleted task: {title}"})
            updated = dict(task)
            updated["id"] = task_id
            updated.pop("task_id", None)
            if name == "complete_task":
                updated["completed"] = True
            else:
                for field in ("title", "due_date", "due_time", "notes"):
                    if field in arguments:
                        updated[field] = str(arguments[field])
                if "priority" in arguments:
                    updated["priority"] = str(max(1, min(5, int(arguments["priority"]))))
                if "due_date" in arguments:
                    datetime.strptime(updated["due_date"], "%m-%d-%Y")
            response = _backend("POST", "/tasks/store", json={"tasks": _encrypt_tasks([updated], user_id)})
            if response.status_code != 200:
                raise RuntimeError(response.text)
            reminder_changes = reminder_changes_from_tool()
            if name == "update_task" and reminder_changes is not None:
                if not isinstance(reminder_changes, dict):
                    raise ValueError("reminder must be an object")
                reminder = {
                    "email_enabled": bool(task.get("reminder_email_enabled", False)),
                    "email": task.get("reminder_email", ""),
                    "sms_enabled": bool(task.get("reminder_sms_enabled", False)),
                    "phone": task.get("reminder_phone", ""),
                    "minutes_before": task.get("reminder_minutes_before", 15),
                    "timezone": local_timezone or task.get("reminder_timezone", "UTC"),
                }
                reminder.update(reminder_changes)
                if (reminder.get("email_enabled") or reminder.get("sms_enabled")) and not updated.get("due_time"):
                    raise ValueError("A due_time is required when reminders are enabled")
                reminder["timezone"] = local_timezone or reminder.get("timezone", "UTC")
                reminder_response = _store_reminder_preferences(
                    task_id, updated.get("title", title), {"reminder": reminder}
                )
                if reminder_response.status_code != 200:
                    raise RuntimeError(reminder_response.text)
            action = "Completed" if name == "complete_task" else "Updated"
            return json.dumps({"status": "success", "message": f"{action} task: {updated.get('title', title)}"})
        except Exception as exc:
            return json.dumps({"status": "error", "message": str(exc)})

    if name == "get_daily_tasks":
        try:
            _user_id, tasks = load_all_remote_tasks()
            requested_day = arguments.get("day")
            requested_date = str(arguments.get("date") or date.today().isoformat())
            schedules = []
            for task in tasks:
                payload = _decode_daily_payload(task.get("notes", ""))
                if not payload:
                    continue
                parsed = _parse_daily_raw(payload.get("raw") or task.get("title"))
                if requested_day and requested_day not in parsed["days"]:
                    continue
                completed_date = payload.get("completed_date")
                if not completed_date and payload.get("completed") and task.get("updated_at"):
                    completed_date = str(task["updated_at"])[:10]
                schedules.append({
                    "task_id": str(task.get("task_id") or task.get("id") or ""),
                    "title": parsed["title"], "days": parsed["days"],
                    "start_time": parsed["start_time"], "end_time": parsed["end_time"],
                    "notes": str(payload.get("notes") or ""),
                    "reminder": {
                        "email_enabled": bool(task.get("reminder_email_enabled", False)),
                        "email": task.get("reminder_email", ""),
                        "sms_enabled": bool(task.get("reminder_sms_enabled", False)),
                        "phone": task.get("reminder_phone", ""),
                        "minutes_before": task.get("reminder_minutes_before", 15),
                    },
                    "completed_today": bool(payload.get("completed")) and completed_date == requested_date,
                })
            schedules.sort(key=lambda item: item["start_time"])
            return json.dumps({"status": "success", "daily_tasks": schedules})
        except Exception as exc:
            return json.dumps({"status": "error", "message": str(exc)})

    if name == "add_daily_task":
        try:
            raw = _build_daily_raw(arguments.get("title", ""), arguments.get("days") or [],
                                   arguments.get("start_time", ""), arguments.get("end_time", ""))
            user_id = current_user_id()
            task_id = "daily:" + uuid.uuid4().hex[:20]
            task = {"id": task_id, "title": raw, "due_date": "", "due_time": "", "priority": "1",
                    "notes": _encode_daily_payload(raw, False, notes=arguments.get("notes", "")), "completed": False}
            response = _backend("POST", "/tasks/store", json={"tasks": _encrypt_tasks([task], user_id)})
            if response.status_code != 200:
                raise RuntimeError(response.text)
            reminder = reminder_changes_from_tool()
            if reminder is not None:
                reminder["timezone"] = local_timezone or "UTC"
                reminder_response = _store_reminder_preferences(task_id, arguments.get("title", "Daily task"), {
                    "reminder": reminder, "recurring_days": arguments.get("days") or [],
                    "recurring_time": arguments.get("start_time", "")})
                if reminder_response.status_code != 200:
                    raise RuntimeError(reminder_response.text)
            return json.dumps({"status": "success", "message": f"Added daily task: {arguments.get('title')}", "task_id": task_id})
        except Exception as exc:
            return json.dumps({"status": "error", "message": str(exc)})

    if name in ("update_daily_task", "complete_daily_task", "delete_daily_task"):
        try:
            task_id = str(arguments.get("task_id", "")).strip()
            if not task_id:
                raise ValueError("task_id is required")
            user_id, tasks = load_all_remote_tasks()
            task = next((item for item in tasks if str(item.get("task_id") or item.get("id") or "") == task_id), None)
            if not task:
                raise ValueError("Daily task not found; call get_daily_tasks and use its exact task_id")
            payload = _decode_daily_payload(task.get("notes", ""))
            if not payload:
                raise ValueError("The selected task is not a daily task")
            parsed = _parse_daily_raw(payload.get("raw") or task.get("title"))
            if name == "delete_daily_task":
                response = _backend("DELETE", f"/tasks/{task_id}")
                if response.status_code != 200:
                    raise RuntimeError(response.text)
                return json.dumps({"status": "success", "message": f"Deleted daily task: {parsed['title']}"})
            updated = dict(task)
            updated["id"] = task_id
            updated.pop("task_id", None)
            if name == "complete_daily_task":
                completed_date = str(arguments.get("date") or date.today().isoformat())
                datetime.strptime(completed_date, "%Y-%m-%d")
                updated["completed"] = True
                updated["notes"] = _encode_daily_payload(parsed["raw"], True, completed_date, payload.get("notes", ""))
                action = "Completed"
            else:
                raw = _build_daily_raw(
                    arguments.get("title", parsed["title"]), arguments.get("days", parsed["days"]),
                    arguments.get("start_time", parsed["start_time"]), arguments.get("end_time", parsed["end_time"]),
                )
                updated["title"] = raw
                updated["notes"] = _encode_daily_payload(raw, bool(payload.get("completed")), payload.get("completed_date"),
                                                        arguments.get("notes", payload.get("notes", "")))
                action = "Updated"
            response = _backend("POST", "/tasks/store", json={"tasks": _encrypt_tasks([updated], user_id)})
            if response.status_code != 200:
                raise RuntimeError(response.text)
            reminder_changes = reminder_changes_from_tool()
            if name == "update_daily_task" and reminder_changes is not None:
                reminder = {
                    "email_enabled": bool(task.get("reminder_email_enabled", False)), "email": task.get("reminder_email", ""),
                    "sms_enabled": bool(task.get("reminder_sms_enabled", False)), "phone": task.get("reminder_phone", ""),
                    "minutes_before": task.get("reminder_minutes_before", 15), "timezone": local_timezone or "UTC",
                }
                reminder.update(reminder_changes)
                reminder_response = _store_reminder_preferences(task_id, arguments.get("title", parsed["title"]), {
                    "reminder": reminder, "recurring_days": arguments.get("days", parsed["days"]),
                    "recurring_time": arguments.get("start_time", parsed["start_time"])})
                if reminder_response.status_code != 200:
                    raise RuntimeError(reminder_response.text)
            return json.dumps({"status": "success", "message": f"{action} daily task: {parsed['title']}"})
        except Exception as exc:
            return json.dumps({"status": "error", "message": str(exc)})
    return json.dumps({"error": f"Unknown tool: {name}"})

# ---------------------------------------------------------------------------
# Page routes
# ---------------------------------------------------------------------------
@app.route("/")
@login_required
def index():
    return render_template("index.html", user_id=current_user_id())

# ---------------------------------------------------------------------------
# Task API (proxy → backend service)
# ---------------------------------------------------------------------------
@app.route("/api/integrations/meetings", methods=["GET"])
@login_required
def meeting_proposals():
    try:
        response = _backend("GET", "/integrations/meetings")
        return jsonify(response.json()), response.status_code
    except Exception as exc:
        return jsonify({"status": "error", "message": str(exc)}), 503


@app.route("/api/integrations/meetings/<proposal_id>", methods=["PATCH"])
@login_required
def decide_meeting(proposal_id):
    try:
        response = _backend("PATCH", f"/integrations/meetings/{proposal_id}",
                            json=request.get_json(silent=True) or {})
        return jsonify(response.json()), response.status_code
    except Exception as exc:
        return jsonify({"status": "error", "message": str(exc)}), 503


def _store_reminder_preferences(task_id, task_title, data):
    reminder = data.get("reminder") or {}
    payload = {
        "task_label": task_title,
        "email_enabled": bool(reminder.get("email_enabled", False)),
        "email": str(reminder.get("email") or "").strip(),
        "sms_enabled": bool(reminder.get("sms_enabled", False)),
        "phone": str(reminder.get("phone") or "").strip(),
        "minutes_before": reminder.get("minutes_before", 15),
        "timezone": str(reminder.get("timezone") or "UTC"),
        "recurring_days": data.get("recurring_days") or [],
        "recurring_time": str(data.get("recurring_time") or ""),
    }
    return _backend("PUT", f"/tasks/{task_id}/reminder", json=payload)


@app.route("/api/tasks", methods=["GET"])
@login_required
def get_tasks():
    try:
        user_id = current_user_id()
        r = _backend("GET", "/tasks/retrieve")
        if r.status_code == 200:
            tasks = _decrypt_tasks(r.json().get("tasks", []), user_id)
            tasks, _daily = _split_remote_tasks(tasks)
            # Annotate with color
            for t in tasks:
                t["color"] = _task_color(t.get("due_date", ""))
            # Sort: overdue first, then today, then upcoming; within each by date+priority
            def sort_key(t):
                color = t.get("color", "")
                order = {"overdue": 0, "today": 1, "": 2}[color]
                try:
                    dt = datetime.strptime(t.get("due_date", "12-31-9999"), "%m-%d-%Y")
                except Exception:
                    dt = datetime(9999, 12, 31)
                try:
                    pri = int(t.get("priority", 5))
                except Exception:
                    pri = 5
                return (order, dt, pri)
            tasks.sort(key=sort_key)
            return jsonify({"status": "success", "tasks": tasks})
        return jsonify({"status": "error", "message": r.text}), r.status_code
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 503

@app.route("/api/tasks", methods=["POST"])
@login_required
def add_task():
    data = request.get_json(silent=True) or {}
    title    = data.get("title", "").strip()
    due_date = data.get("due_date", "")
    due_time = data.get("due_time", "")
    priority = str(data.get("priority", "1"))
    notes    = data.get("notes", "No notes")

    if not title or not due_date:
        return jsonify({"status": "error", "message": "title and due_date required"}), 400

    user_id = current_user_id()
    task_id = hashlib.md5(f"{title}|{due_date}".encode()).hexdigest()[:12]
    task = {"id": task_id, "title": title, "due_date": due_date,
            "due_time": due_time, "priority": priority, "notes": notes, "completed": False}
    try:
        r = _backend("POST", "/tasks/store", json={"tasks": _encrypt_tasks([task], user_id),
                                                    "timestamp": datetime.now(timezone.utc).isoformat()})
        if r.status_code == 200:
            reminder_response = _store_reminder_preferences(task_id, title, data)
            if reminder_response.status_code != 200:
                return jsonify({"status": "error", "message": reminder_response.text}), reminder_response.status_code
            return jsonify({"status": "success", "task": task})
        return jsonify({"status": "error", "message": r.text}), r.status_code
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 503

@app.route("/api/tasks/<task_id>", methods=["PUT"])
@login_required
def edit_task(task_id):
    data = request.get_json(silent=True) or {}
    user_id = current_user_id()
    task = {
        "id":       task_id,
        "title":    data.get("title", ""),
        "due_date": data.get("due_date", ""),
        "due_time": data.get("due_time", ""),
        "priority": str(data.get("priority", "1")),
        "notes":    data.get("notes", "No notes"),
        "completed": data.get("completed", False),
    }
    try:
        r = _backend("POST", "/tasks/store", json={"tasks": _encrypt_tasks([task], user_id),
                                                    "timestamp": datetime.now(timezone.utc).isoformat()})
        if r.status_code == 200:
            reminder_response = _store_reminder_preferences(task_id, task["title"], data)
            if reminder_response.status_code != 200:
                return jsonify({"status": "error", "message": reminder_response.text}), reminder_response.status_code
            return jsonify({"status": "success"})
        return jsonify({"status": "error", "message": r.text}), r.status_code
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 503

@app.route("/api/tasks/<task_id>/complete", methods=["POST"])
@login_required
def complete_task(task_id):
    try:
        response = _backend("POST", f"/tasks/{task_id}/complete")
        if response.status_code != 200:
            try:
                message = response.json().get("message", response.text)
            except Exception:
                message = response.text
            return jsonify({"status": "error", "message": message}), response.status_code

        backend_result = response.json()
        if not backend_result.get("updated"):
            return jsonify({"status": "success", "task_id": task_id, "already_completed": True})

        # Also update character stats
        conn = get_db()
        row = conn.execute("SELECT value FROM character WHERE key='tasks_completed'").fetchone()
        completed = int(row[0]) if row else 0
        new_completed = completed + 1
        level = new_completed // 5
        conn.execute("INSERT OR REPLACE INTO character(key,value) VALUES('tasks_completed',?)", (str(new_completed),))
        conn.execute("INSERT OR REPLACE INTO character(key,value) VALUES('level',?)", (str(level),))
        conn.commit()
        conn.close()
        return jsonify({"status": "success", "task_id": task_id})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 503

@app.route("/api/tasks/<task_id>", methods=["DELETE"])
@login_required
def delete_task(task_id):
    try:
        r = _backend("DELETE", f"/tasks/{task_id}")
        if r.status_code == 200:
            return jsonify({"status": "success"})
        return jsonify({"status": "error", "message": r.text}), r.status_code
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 503

@app.route("/api/tasks/clear", methods=["POST"])
@login_required
def clear_tasks_only():
    """Clear only regular tasks while preserving remote daily tasks."""
    try:
        user_id = current_user_id()
        r = _backend("GET", "/tasks/retrieve")
        tasks = _decrypt_tasks(r.json().get("tasks", []), user_id) if r.status_code == 200 else []

        preserved_daily = []
        for task in tasks:
            if _decode_daily_payload(task.get("notes", "")):
                kept = dict(task)
                kept["id"] = str(kept.get("task_id") or kept.get("id") or "")
                kept.pop("task_id", None)
                preserved_daily.append(kept)

        r2 = _backend(
            "POST",
            "/tasks/replace",
            json={
                "tasks": _encrypt_tasks(preserved_daily, user_id),
            },
            headers={**_headers(), "X-Confirm-Replace": "true"},
        )
        if r2.status_code == 200:
            return jsonify({"status": "success", "kept_daily": len(preserved_daily)})
        return jsonify({"status": "error", "message": r2.text}), r2.status_code
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 503

# ---------------------------------------------------------------------------
# Daily Tasks API (local SQLite)
# ---------------------------------------------------------------------------
@app.route("/api/daily", methods=["GET"])
@login_required
def get_daily():
    today = request.args.get("date", date.today().isoformat())
    requested_day = request.args.get("day", datetime.now().strftime("%a"))
    if requested_day not in ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"):
        return jsonify({"status": "error", "message": "Invalid weekday"}), 400
    g.daily_day = requested_day
    g.daily_date = today
    user_id = current_user_id()

    # Local web-only daily items
    conn = get_db()
    rows = conn.execute(
        "SELECT * FROM daily_tasks WHERE date=? AND user_id=? ORDER BY id", (today, user_id)).fetchall()
    conn.close()

    local_tasks = [{
        "id": f"local:{r['id']}",
        "title": r["title"],
        "raw": r["title"],
        "days": ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"],
        "start_time": "00:00",
        "end_time": "",
        "done": bool(r["done"]),
        "scheduled_today": True,
        "source": "local",
    } for r in rows]

    # Remote daily items synced from desktop app
    remote_daily = []
    try:
        r = _backend("GET", "/tasks/retrieve")
        if r.status_code != 200:
            return jsonify({"status": "error", "message": f"Task backend returned {r.status_code}: {r.text}"}), r.status_code
        tasks = _decrypt_tasks(r.json().get("tasks", []), user_id)
        _regular, remote_daily = _split_remote_tasks(tasks)
    except Exception as exc:
        log.exception("daily task retrieval failed")
        return jsonify({"status": "error", "message": str(exc)}), 503

    combined = remote_daily + local_tasks
    deduped = []
    seen = set()
    for item in combined:
        key = str(item.get("id", ""))
        if key in seen:
            continue
        seen.add(key)
        deduped.append(item)

    return jsonify({"status": "success", "tasks": deduped})

@app.route("/api/daily", methods=["POST"])
@login_required
def add_daily():
    data = request.get_json(silent=True) or {}
    title = data.get("title", "").strip()
    days = data.get("days") or ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    start_time = data.get("start_time", "00:00")
    end_time = data.get("end_time", "")
    try:
        raw = _build_daily_raw(title, days, start_time, end_time)
    except ValueError as exc:
        return jsonify({"status": "error", "message": str(exc)}), 400
    user_id = current_user_id()
    try:
        remote_task_id = "daily:" + uuid.uuid4().hex[:20]
        remote_task = {
            "id": remote_task_id,
            "title": raw,
            "due_date": "",
            "due_time": "",
            "priority": "1",
            "notes": _encode_daily_payload(raw, False, notes=data.get("notes", "")),
            "completed": False,
        }
        response = _backend(
            "POST",
            "/tasks/store",
            json={
                "tasks": _encrypt_tasks([remote_task], user_id),
                "timestamp": datetime.now(timezone.utc).isoformat(),
            },
        )
        if response.status_code != 200:
            return jsonify({"status": "error", "message": response.text}), response.status_code
        reminder_response = _store_reminder_preferences(remote_task_id, title, {
            "reminder": data.get("reminder") or {}, "recurring_days": days, "recurring_time": start_time})
        if reminder_response.status_code != 200:
            return jsonify({"status": "error", "message": reminder_response.text}), reminder_response.status_code
    except Exception as exc:
        return jsonify({"status": "error", "message": str(exc)}), 503
    return jsonify({"status": "success", "id": f"remote:{remote_task_id}"})


@app.route("/api/daily/<task_id>", methods=["PUT"])
@login_required
def edit_daily(task_id):
    if not task_id.startswith("remote:"):
        return jsonify({"status": "error", "message": "Legacy local tasks cannot be edited; recreate this task."}), 400
    remote_task_id = task_id.split(":", 1)[1]
    data = request.get_json(silent=True) or {}
    try:
        raw = _build_daily_raw(data.get("title", ""), data.get("days") or [],
                               data.get("start_time", ""), data.get("end_time", ""))
        user_id = current_user_id()
        response = _backend("GET", "/tasks/retrieve")
        tasks = _decrypt_tasks(response.json().get("tasks", []), user_id) if response.status_code == 200 else []
        match = next((t for t in tasks if str(t.get("task_id") or t.get("id") or "") == remote_task_id), None)
        if not match:
            return jsonify({"status": "error", "message": "Daily task not found"}), 404
        payload = _decode_daily_payload(match.get("notes", "")) or {}
        updated = dict(match)
        updated["id"] = remote_task_id
        updated.pop("task_id", None)
        updated["title"] = raw
        updated["notes"] = _encode_daily_payload(raw, bool(payload.get("completed")), payload.get("completed_date"),
                                                data.get("notes", payload.get("notes", "")))
        stored = _backend("POST", "/tasks/store", json={"tasks": _encrypt_tasks([updated], user_id)})
        if stored.status_code == 200:
            reminder_response = _store_reminder_preferences(remote_task_id, data.get("title", "Daily task"), {
                "reminder": data.get("reminder") or {}, "recurring_days": data.get("days") or [],
                "recurring_time": data.get("start_time", "")})
            if reminder_response.status_code != 200:
                return jsonify({"status": "error", "message": reminder_response.text}), reminder_response.status_code
            return jsonify({"status": "success"})
        return jsonify({"status": "error", "message": stored.text}), stored.status_code
    except Exception as exc:
        return jsonify({"status": "error", "message": str(exc)}), 503

@app.route("/api/daily/<task_id>/toggle", methods=["POST"])
@login_required
def toggle_daily(task_id):
    user_id = current_user_id()
    client_date = (request.get_json(silent=True) or {}).get("date") or date.today().isoformat()
    if task_id.startswith("remote:"):
        remote_task_id = task_id.split(":", 1)[1]
        try:
            r = _backend("GET", "/tasks/retrieve")
            if r.status_code != 200:
                return jsonify({"status": "error", "message": r.text}), r.status_code

            tasks = _decrypt_tasks(r.json().get("tasks", []), user_id)
            match = next((t for t in tasks if str(t.get("task_id") or t.get("id") or "") == remote_task_id), None)
            if not match:
                return jsonify({"status": "error", "message": "Daily task not found"}), 404

            payload = _decode_daily_payload(match.get("notes", ""))
            if not payload:
                return jsonify({"status": "error", "message": "Not a daily task"}), 400

            raw = (payload.get("raw") or match.get("title") or "").strip()
            completed_date = payload.get("completed_date")
            if not completed_date and payload.get("completed") and match.get("updated_at"):
                completed_date = str(match["updated_at"])[:10]
            done = bool(payload.get("completed", match.get("completed", False))) and completed_date == client_date
            updated = dict(match)
            updated["id"] = remote_task_id
            updated["title"] = raw
            updated["completed"] = not done
            updated["notes"] = _encode_daily_payload(raw, not done, client_date if not done else None,
                                                     payload.get("notes", ""))
            updated.pop("task_id", None)

            r2 = _backend(
                "POST",
                "/tasks/store",
                json={
                    "tasks": _encrypt_tasks([updated], user_id),
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                },
            )
            if r2.status_code == 200:
                return jsonify({"status": "success"})
            return jsonify({"status": "error", "message": r2.text}), r2.status_code
        except Exception as e:
            return jsonify({"status": "error", "message": str(e)}), 503

    if task_id.startswith("local:"):
        task_id = task_id.split(":", 1)[1]

    try:
        local_id = int(task_id)
    except ValueError:
        return jsonify({"status": "error", "message": "Invalid daily task id"}), 400

    conn = get_db()
    conn.execute("UPDATE daily_tasks SET done = 1 - done WHERE id=? AND user_id=?", (local_id, user_id))
    conn.commit()
    conn.close()
    return jsonify({"status": "success"})

@app.route("/api/daily/<task_id>", methods=["DELETE"])
@login_required
def delete_daily(task_id):
    user_id = current_user_id()
    if task_id.startswith("remote:"):
        remote_task_id = task_id.split(":", 1)[1]
        try:
            r = _backend("DELETE", f"/tasks/{remote_task_id}")
            if r.status_code == 200:
                return jsonify({"status": "success"})
            return jsonify({"status": "error", "message": r.text}), r.status_code
        except Exception as e:
            return jsonify({"status": "error", "message": str(e)}), 503

    if task_id.startswith("local:"):
        task_id = task_id.split(":", 1)[1]

    try:
        local_id = int(task_id)
    except ValueError:
        return jsonify({"status": "error", "message": "Invalid daily task id"}), 400

    conn = get_db()
    conn.execute("DELETE FROM daily_tasks WHERE id=? AND user_id=?", (local_id, user_id))
    conn.commit()
    conn.close()
    return jsonify({"status": "success"})

@app.route("/api/daily/clear", methods=["POST"])
@login_required
def clear_daily_only():
    """Clear all daily tasks (remote + local) while preserving regular tasks."""
    try:
        user_id = current_user_id()
        r = _backend("GET", "/tasks/retrieve")
        tasks = _decrypt_tasks(r.json().get("tasks", []), user_id) if r.status_code == 200 else []

        data = request.get_json(silent=True) or {}
        requested_day = data.get("day") or datetime.now().strftime("%a")
        requested_date = data.get("date") or date.today().isoformat()
        preserved_regular = []
        for task in tasks:
            daily_payload = _decode_daily_payload(task.get("notes", ""))
            if daily_payload:
                parsed = _parse_daily_raw(daily_payload.get("raw") or task.get("title"))
                if requested_day in parsed["days"]:
                    continue
            kept = dict(task)
            kept["id"] = str(kept.get("task_id") or kept.get("id") or "")
            kept.pop("task_id", None)
            preserved_regular.append(kept)

        r2 = _backend(
            "POST",
            "/tasks/replace",
            json={
                "tasks": _encrypt_tasks(preserved_regular, user_id),
            },
            headers={**_headers(), "X-Confirm-Replace": "true"},
        )
        if r2.status_code != 200:
            return jsonify({"status": "error", "message": r2.text}), r2.status_code

        conn = get_db()
        conn.execute("DELETE FROM daily_tasks WHERE date=? AND user_id=?", (requested_date, user_id))
        conn.commit()
        conn.close()

        return jsonify({"status": "success", "kept_regular": len(preserved_regular)})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 503

# ---------------------------------------------------------------------------
# AI API (proxy → ai_inference service)
# ---------------------------------------------------------------------------
@app.route("/api/ai/chat", methods=["POST"])
@login_required
def ai_chat():
    data = request.get_json(silent=True) or {}
    prompt = data.get("prompt", "")
    model  = data.get("model", "")
    zdr    = bool(data.get("zdr", False))
    image_url = data.get("image_url", "")
    response_format = data.get("response_format")
    history = data.get("history") or []
    if not prompt and not image_url:
        return jsonify({"status": "error", "message": "prompt required"}), 400
    try:
        payload = {"prompt": prompt, "model": model, "zdr": zdr, "image_url": image_url, "history": history}
        if response_format:
            payload["response_format"] = response_format
        r = _ai("POST", "/inference", json=payload)
        if r.status_code == 200:
            return jsonify(r.json())

        message = f"AI service error ({r.status_code})"
        receipt_id = ""
        nonce = ""
        try:
            upstream = r.json()
            if isinstance(upstream, dict):
                # Extract the deepest human-readable error string.
                raw = upstream.get("message") or ""
                if not raw:
                    err_obj = upstream.get("error", {})
                    if isinstance(err_obj, dict):
                        raw = err_obj.get("message") or ""
                # Strip internal URL noise from upstream verifier errors.
                if "upstream verification failed" in raw.lower():
                    message = "AI model route temporarily unavailable. Try again or select a different model."
                elif raw:
                    message = raw
                receipt_id = upstream.get("receipt_id", "")
                nonce = upstream.get("nonce", "")
        except Exception:
            pass

        payload = {"status": "error", "message": message}
        if receipt_id:
            payload["receipt_id"] = receipt_id
        if nonce:
            payload["nonce"] = nonce
        return jsonify(payload), r.status_code
    except req.exceptions.Timeout:
        return jsonify({
            "status": "error",
            "message": "AI request timed out waiting for ai_inference. Please try again."
        }), 504
    except req.exceptions.ConnectionError:
        return jsonify({"status": "error",
                        "message": "AI service not available. Check ai_inference service health in CVM."}), 503
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 503

@app.route("/api/ai/chat/stream", methods=["POST"])
@login_required
def ai_chat_stream():
    data = request.get_json(silent=True) or {}
    prompt = data.get("prompt", "")
    model = data.get("model", "")
    zdr = bool(data.get("zdr", False))
    image_url = data.get("image_url", "")
    response_format = data.get("response_format")

    if not prompt and not image_url:
        return jsonify({"status": "error", "message": "prompt required"}), 400

    if image_url:
        user_content = [
            {"type": "text", "text": prompt or "What is in this image?"},
            {"type": "image_url", "image_url": {"url": image_url}},
        ]
    else:
        user_content = prompt

    history = data.get("history") or []
    messages = [{"role": "system", "content": "You are a helpful task management assistant."}]
    messages.extend(h for h in history if isinstance(h, dict) and h.get("role") in ("user", "assistant"))
    messages.append({"role": "user", "content": user_content})

    payload = {"messages": messages, "model": model, "zdr": zdr}
    if response_format:
        payload["response_format"] = response_format

    try:
        upstream = req.post(
            f"{AI_URL}/chat/stream", json=payload, headers=_headers(),
            timeout=AI_PROXY_TIMEOUT, stream=True,
        )
    except req.exceptions.Timeout:
        return jsonify({"status": "error", "message": "AI request timed out waiting for ai_inference."}), 504
    except req.exceptions.ConnectionError:
        return jsonify({"status": "error", "message": "AI service not available."}), 503

    if upstream.status_code != 200:
        try:
            payload = upstream.json()
        except Exception:
            payload = {}
        return jsonify({"status": "error", "message": payload.get("message", "AI service error")}), upstream.status_code

    def relay():
        try:
            for chunk in upstream.iter_content(chunk_size=None):
                if chunk:
                    yield chunk
        finally:
            upstream.close()

    return Response(relay(), mimetype="text/event-stream",
                     headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

@app.route("/api/ai/chat/tools", methods=["POST"])
@login_required
def ai_chat_tools():
    data = request.get_json(silent=True) or {}
    prompt = data.get("prompt", "").strip()
    model = data.get("model", "")
    zdr = bool(data.get("zdr", False))
    local_date = str(data.get("local_date") or date.today().isoformat())
    local_day = str(data.get("local_day") or datetime.now().strftime("%a"))
    local_timezone = str(data.get("local_timezone") or "UTC")
    if not prompt:
        return jsonify({"status": "error", "message": "prompt required"}), 400

    history = data.get("history") or []
    messages = [
        {"role": "system", "content": (
            "You are a task management assistant. Regular tasks and recurring daily tasks are different lists. "
            "Use get_tasks before changing a regular task, and get_daily_tasks before changing a daily task; "
            "always use the exact task_id returned by the matching tool. Daily schedules use weekday arrays and "
            "24-hour HH:MM tool arguments. When adding multiple independent tasks, issue all add tool calls in "
            "the same response instead of one per round. Never claim a change unless its tool returned success. "
            "Task notes belong in the notes field. Reminder tool arguments are flat fields prefixed with reminder_; "
            "phone reminders are sent by SMS and numbers must use international +country-code format. "
            "Ask for any missing recipient address/number, due time, or reminder lead time instead of inventing it. "
            f"The user's local date is {local_date}, weekday is {local_day}, and timezone is {local_timezone}."
        )},
    ]
    messages.extend(h for h in history if isinstance(h, dict) and h.get("role") in ("user", "assistant"))
    messages.append({"role": "user", "content": prompt})

    try:
        tasks_changed = False
        daily_tasks_changed = False
        tool_failures = []
        while True:
            r = _ai("POST", "/chat", json={
                "messages": messages, "model": model, "zdr": zdr,
                "tools": BUILTIN_TOOLS, "tool_choice": "auto",
            })
            if r.status_code != 200:
                try:
                    payload = r.json()
                except Exception:
                    payload = {}
                return jsonify({"status": "error", "message": payload.get("message", "AI service error")}), r.status_code

            body = r.json()
            message = body.get("message", {})
            tool_calls = message.get("tool_calls") or []

            if not tool_calls:
                if tool_failures and not (tasks_changed or daily_tasks_changed):
                    return jsonify({
                        "status": "error",
                        "message": "Task change failed: " + "; ".join(tool_failures),
                    }), 400
                return jsonify({
                    "status": "success",
                    "response": message.get("content") or "(no response)",
                    "model": body.get("model", model),
                    "receipt_id": body.get("receipt_id", ""),
                    "tasks_changed": tasks_changed,
                    "daily_tasks_changed": daily_tasks_changed,
                })

            messages.append(message)
            for tc in tool_calls:
                result = _execute_tool_call(tc, local_date=local_date, local_day=local_day,
                                            local_timezone=local_timezone)
                result_payload = {}
                try:
                    result_payload = json.loads(result)
                    if result_payload.get("status") == "error" or result_payload.get("error"):
                        failure = str(result_payload.get("message") or result_payload.get("error"))
                        if "has not been approved for encrypted task storage" in failure:
                            return jsonify({
                                "status": "error",
                                "message": (
                                    "This Web UI is waiting for encryption approval. Open the desktop app on an "
                                    "already trusted computer, sign in to the same account, then retry this request."
                                ),
                            }), 409
                        tool_failures.append(failure)
                except (TypeError, ValueError, json.JSONDecodeError):
                    tool_failures.append("Task tool returned an invalid response")
                if tc.get("function", {}).get("name") in ("add_task", "update_task", "complete_task", "delete_task"):
                    try:
                        tasks_changed = tasks_changed or result_payload.get("status") == "success"
                    except (TypeError, ValueError, json.JSONDecodeError):
                        pass
                if tc.get("function", {}).get("name") in ("add_daily_task", "update_daily_task", "complete_daily_task", "delete_daily_task"):
                    try:
                        daily_tasks_changed = daily_tasks_changed or result_payload.get("status") == "success"
                    except (TypeError, ValueError, json.JSONDecodeError):
                        pass
                messages.append({"role": "tool", "content": result, "tool_call_id": tc.get("id")})

    except req.exceptions.Timeout:
        return jsonify({"status": "error", "message": "AI request timed out waiting for ai_inference."}), 504
    except req.exceptions.ConnectionError:
        return jsonify({"status": "error", "message": "AI service not available."}), 503
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 503

@app.route("/api/ai/models", methods=["GET"])
def ai_models():
    try:
        refresh = request.args.get("refresh", "")
        r = _ai("GET", "/models", params={"refresh": refresh} if refresh else None)
        if r.status_code == 200:
            return jsonify(r.json())
        return jsonify({"status": "success", "models": []})
    except Exception:
        return jsonify({"status": "success", "models": []})

@app.route("/api/ai/models/vision", methods=["GET"])
def ai_models_vision():
    try:
        r = _ai("GET", "/models/vision", timeout=15)
        if r.status_code == 200:
            return jsonify(r.json())
        return jsonify({"status": "success", "models": []})
    except Exception:
        return jsonify({"status": "success", "models": []})


@app.route("/api/ai/health", methods=["GET"])
def ai_health():
    try:
        r = _ai("GET", "/health", timeout=5)
        return jsonify(r.json())
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 503

@app.route("/api/ai/attestation", methods=["GET"])
def ai_attestation():
    try:
        r = _ai("GET", "/attestation", timeout=12)
        if r.status_code == 200:
            return jsonify(r.json())
        try:
            payload = r.json()
        except Exception:
            payload = {}
        return jsonify({"status": "error", "message": payload.get("message", "Attestation unavailable")}), r.status_code
    except req.exceptions.Timeout:
        return jsonify({"status": "error", "message": "Attestation request timed out"}), 504
    except req.exceptions.ConnectionError:
        return jsonify({"status": "error", "message": "AI service not available"}), 503
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 503


@app.route("/api/ai/receipt/<receipt_id>", methods=["GET"])
def ai_receipt(receipt_id):
    try:
        r = _ai("GET", f"/receipts/{receipt_id}", timeout=12)
        if r.status_code == 200:
            return jsonify(r.json())
        try:
            payload = r.json()
        except Exception:
            payload = {}
        return jsonify({"status": "error", "message": payload.get("message", "Receipt unavailable")}), r.status_code
    except req.exceptions.Timeout:
        return jsonify({"status": "error", "message": "Receipt request timed out"}), 504
    except req.exceptions.ConnectionError:
        return jsonify({"status": "error", "message": "AI service not available"}), 503
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 503

@app.route("/api/ai/models/zdr", methods=["GET"])
def ai_models_zdr():
    try:
        r = _ai("GET", "/models/zdr", timeout=15)
        if r.status_code == 200:
            return jsonify(r.json())
        try:
            payload = r.json()
        except Exception:
            payload = {}
        return jsonify({"status": "error", "message": payload.get("message", "ZDR model list unavailable")}), r.status_code
    except req.exceptions.Timeout:
        return jsonify({"status": "error", "message": "ZDR model list request timed out"}), 504
    except req.exceptions.ConnectionError:
        return jsonify({"status": "error", "message": "AI service not available"}), 503
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 503

# ---------------------------------------------------------------------------
# Calendar / Weekly (computed from tasks)
# ---------------------------------------------------------------------------
@app.route("/api/calendar/<int:year>/<int:month>", methods=["GET"])
@login_required
def calendar_data(year, month):
    try:
        user_id = current_user_id()
        r = _backend("GET", "/tasks/retrieve")
        if r.status_code != 200:
            try:
                message = r.json().get("message", "Could not load tasks")
            except Exception:
                message = "Could not load tasks"
            return jsonify({"status": "error", "message": message}), r.status_code
        tasks = _decrypt_tasks(r.json().get("tasks", []), user_id)
        tasks, daily_tasks = _split_remote_tasks(tasks)
        tasks = [task for task in tasks if not task.get("completed", False)]
    except Exception as exc:
        log.exception("Failed to load calendar tasks")
        return jsonify({"status": "error", "message": "Could not load the latest calendar tasks"}), 503

    by_date = {}
    for t in tasks:
        d = t.get("due_date", "")
        try:
            dt = datetime.strptime(d, "%m-%d-%Y")
            if dt.year == year and dt.month == month:
                key = str(dt.day)
                by_date.setdefault(key, []).append({
                    "title": t.get("title"), "priority": t.get("priority"),
                    "due_time": t.get("due_time", ""),
                    "color": _task_color(d), "type": "todo"
                })
        except Exception:
            pass

    last_day = (datetime(year + (month == 12), 1 if month == 12 else month + 1, 1) -
                timedelta(days=1)).day
    for day_number in range(1, last_day + 1):
        weekday = datetime(year, month, day_number).strftime("%a")
        for task in daily_tasks:
            if weekday in task.get("days", []):
                by_date.setdefault(str(day_number), []).append({
                    "title": task.get("title"),
                    "due_time": task.get("start_time", ""),
                    "end_time": task.get("end_time", ""),
                    "color": "daily", "type": "daily",
                })
    for entries in by_date.values():
        entries.sort(key=lambda item: (item.get("due_time") or "99:99", item.get("title") or ""))
    return jsonify({"status": "success", "tasks_by_day": by_date})

@app.route("/api/weekly", methods=["GET"])
@login_required
def weekly_data():
    try:
        user_id = current_user_id()
        r = _backend("GET", "/tasks/retrieve")
        if r.status_code != 200:
            try:
                message = r.json().get("message", "Could not load tasks")
            except Exception:
                message = "Could not load tasks"
            return jsonify({"status": "error", "message": message}), r.status_code
        tasks = _decrypt_tasks(r.json().get("tasks", []), user_id)
        tasks, daily_tasks = _split_remote_tasks(tasks)
        tasks = [task for task in tasks if not task.get("completed", False)]
    except Exception as exc:
        log.exception("Failed to load weekly tasks")
        return jsonify({"status": "error", "message": "Could not load the latest weekly tasks"}), 503

    try:
        today = datetime.strptime(request.args.get("date", ""), "%Y-%m-%d").date()
    except ValueError:
        today = date.today()
    start = today - timedelta(days=today.weekday())  # Monday
    week_days = [(start + timedelta(days=i)) for i in range(7)]
    week_dates = {d.strftime("%m-%d-%Y"): [] for d in week_days}

    for t in tasks:
        d = t.get("due_date", "")
        if d in week_dates:
            week_dates[d].append({
                "title": t.get("title"), "priority": t.get("priority"),
                "due_time": t.get("due_time", ""), "color": _task_color(d),
                "type": "todo"
            })
    for day_date in week_days:
        date_key = day_date.strftime("%m-%d-%Y")
        weekday = day_date.strftime("%a")
        for task in daily_tasks:
            if weekday in task.get("days", []):
                week_dates[date_key].append({
                    "title": task.get("title"),
                    "due_time": task.get("start_time", ""),
                    "end_time": task.get("end_time", ""),
                    "color": "daily", "type": "daily",
                })
    for entries in week_dates.values():
        entries.sort(key=lambda item: (item.get("due_time") or "99:99", item.get("title") or ""))
    return jsonify({"status": "success", "week": week_dates,
                    "week_days": [d.strftime("%a %b %d") for d in week_days],
                    "week_dates": [d.strftime("%m-%d-%Y") for d in week_days]})

# ---------------------------------------------------------------------------
# Character / Stats
# ---------------------------------------------------------------------------
@app.route("/api/character", methods=["GET"])
@login_required
def get_character():
    conn = get_db()
    rows = conn.execute("SELECT key,value FROM character").fetchall()
    conn.close()
    data = {r["key"]: r["value"] for r in rows}
    completed = int(data.get("tasks_completed", 0))
    level = completed // 5
    xp_current = completed % 5
    return jsonify({"status": "success", "level": level,
                    "tasks_completed": completed,
                    "xp_current": xp_current, "xp_needed": 5})

# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------
@app.route("/api/settings", methods=["GET"])
@login_required
def get_settings():
    user_id = current_user_id()
    workspace_key_ready = bool(_workspace_key_for_user(user_id))
    default_model = _get_setting("phala_ai_model", os.getenv("PHALA_AI_MODEL", "")).strip()
    return jsonify({"status": "success", "settings": {
        "use_24_hour": _get_setting("use_24_hour", "true") == "true",
        "web_user_id": user_id,
        "phala_ai_model": default_model,
        "crypto": {
            "device_id": _get_setting("crypto_device_id", "") or None,
            "workspace_key_ready": workspace_key_ready,
            "enc2_supported": ASYMMETRIC_CRYPTO_AVAILABLE,
        },
    }})


@app.route("/api/crypto/status", methods=["GET"])
@login_required
def crypto_status():
    """Return web-ui device encryption status for troubleshooting ENC2 access."""
    user_id = current_user_id()
    try:
        resp = _backend("GET", "/crypto/devices")
        devices = resp.json().get("devices", []) if resp.status_code == 200 else []
    except Exception:
        devices = []

    device_id = _get_setting("crypto_device_id", "")
    own = next((d for d in devices if d.get("device_id") == device_id), None)
    return jsonify({
        "status": "success",
        "enc2_supported": ASYMMETRIC_CRYPTO_AVAILABLE,
        "device_id": device_id or None,
        "device_status": own.get("status") if own else "not_registered",
        "workspace_key_ready": bool(_workspace_key_for_user(user_id)),
        "user_id": user_id,
    })

@app.route("/api/settings", methods=["POST"])
@login_required
def save_settings():
    data = request.get_json(silent=True) or {}
    if "use_24_hour" in data:
        _set_setting("use_24_hour", str(data["use_24_hour"]).lower())
    if "phala_ai_model" in data:
        _set_setting("phala_ai_model", str(data["phala_ai_model"]).strip())
    return jsonify({"status": "success"})

# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------
@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok", "service": "web_ui",
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "user_id": current_user_id() if is_logged_in() else None})


@app.route("/api/openclaw/health", methods=["GET"])
def openclaw_health():
    """Publicly reachable health probe for the internal OpenClaw gateway."""
    try:
        resp = req.get(f"{OPENCLAW_URL}/healthz", timeout=5)
        payload = {}
        try:
            payload = resp.json()
        except Exception:
            payload = {}
        return jsonify({
            "status": "ok" if resp.status_code == 200 else "error",
            "service": "openclaw",
            "code": resp.status_code,
            "upstream_status": payload.get("status", "") if isinstance(payload, dict) else "",
            "upstream": f"{OPENCLAW_URL}/healthz",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }), 200 if resp.status_code == 200 else 503
    except Exception as exc:
        return jsonify({
            "status": "error",
            "service": "openclaw",
            "code": 0,
            "message": str(exc),
            "upstream": f"{OPENCLAW_URL}/healthz",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }), 503


@app.route("/api/health/all", methods=["GET"])
def health_all():
    """Check health for all internal services reachable from web_ui."""
    services = {
        "web_ui": {
            "url": None,
            "ok": True,
            "status": "ok",
            "code": 200,
            "message": "running",
        },
        "backend": {"url": f"{BACKEND_URL}/health"},
        "ai_inference": {"url": f"{AI_URL}/health"},
        "task_sync": {"url": f"{SYNC_URL}/health"},
        "scheduler": {"url": f"{SCHEDULER_URL}/health"},
        "openclaw": {"url": f"{OPENCLAW_URL}/healthz"},
    }

    for name, svc in services.items():
        if svc.get("url") is None:
            continue
        try:
            resp = req.get(svc["url"], headers={"Content-Type": "application/json", **({"X-API-Key": API_KEY} if API_KEY else {})}, timeout=5)
            payload = {}
            try:
                payload = resp.json()
            except Exception:
                payload = {}

            status_text = str(payload.get("status", "")).lower() if isinstance(payload, dict) else ""
            is_ok = resp.status_code == 200 and status_text in ("ok", "success", "healthy", "")
            services[name] = {
                "url": svc["url"],
                "ok": is_ok,
                "status": payload.get("status", "ok") if isinstance(payload, dict) else "unknown",
                "code": resp.status_code,
                "message": payload.get("message", "") if isinstance(payload, dict) else "",
            }
        except Exception as exc:
            services[name] = {
                "url": svc["url"],
                "ok": False,
                "status": "error",
                "code": 0,
                "message": str(exc),
            }

    overall_ok = all(svc.get("ok", False) for svc in services.values())
    return jsonify({
        "status": "ok" if overall_ok else "degraded",
        "overall_ok": overall_ok,
        "services": services,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    })

# ---------------------------------------------------------------------------
# Startup
# ---------------------------------------------------------------------------
init_db()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080, debug=False)
