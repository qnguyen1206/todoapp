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
from datetime import datetime, timezone, date
from pathlib import Path

import requests as req
from flask import Flask, render_template, request, jsonify, redirect, url_for
from flask_cors import CORS

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
# Internal service URLs (same CVM, internal Docker network)
# ---------------------------------------------------------------------------
BACKEND_URL      = os.getenv("BACKEND_URL",   "http://backend:5000")
AI_URL           = os.getenv("AI_URL",         "http://ai_inference:5001")
SYNC_URL         = os.getenv("SYNC_URL",       "http://task_sync:5002")
SCHEDULER_URL    = os.getenv("SCHEDULER_URL",  "http://scheduler:5003")
API_KEY          = os.getenv("API_KEY",        "")
AI_PROXY_TIMEOUT = int(os.getenv("AI_PROXY_TIMEOUT", "60"))

TASK_ENCRYPTION_PREFIX = "ENC2:"
DAILY_NOTES_PREFIX = "[CVM_DAILY]"
KEY_WRAP_INFO = b"todoapp-keywrap-v1"
TASK_INFO_PREFIX = "todoapp-task-v2"
_WORKSPACE_KEY_CACHE = {}

# Stable user ID for this web session — override via WEB_USER_ID env var
# to match your desktop user ID for seamless sync.
import socket
_default_uid = hashlib.sha256(socket.gethostname().encode()).hexdigest()[:16]
USER_ID = os.getenv("WEB_USER_ID", _default_uid)

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
    h = {"Content-Type": "application/json"}
    if API_KEY:
        h["X-API-Key"] = API_KEY
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
        resp = _backend("GET", "/crypto/devices", params={"user_id": user_id})
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
            "user_id": user_id,
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


def _encode_daily_payload(raw_text, completed=False):
    payload = {
        "kind": "daily",
        "raw": raw_text,
        "completed": bool(completed),
    }
    return DAILY_NOTES_PREFIX + json.dumps(payload, ensure_ascii=True, separators=(",", ":"))


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
            done = bool(daily_payload.get("completed", task.get("completed", False)))
            daily.append({
                "id": f"remote:{remote_task_id}",
                "title": raw,
                "done": done,
                "source": "remote",
                "remote_task_id": remote_task_id,
            })
        else:
            regular.append(task)

    return regular, daily

# ---------------------------------------------------------------------------
# Page routes
# ---------------------------------------------------------------------------
@app.route("/")
def index():
    return render_template("index.html", user_id=USER_ID)

# ---------------------------------------------------------------------------
# Task API (proxy → backend service)
# ---------------------------------------------------------------------------
@app.route("/api/tasks", methods=["GET"])
def get_tasks():
    try:
        r = _backend("GET", f"/tasks/retrieve", params={"user_id": USER_ID})
        if r.status_code == 200:
            tasks = _decrypt_tasks(r.json().get("tasks", []), USER_ID)
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
def add_task():
    data = request.get_json(silent=True) or {}
    title    = data.get("title", "").strip()
    due_date = data.get("due_date", "")
    due_time = data.get("due_time", "")
    priority = str(data.get("priority", "1"))
    notes    = data.get("notes", "No notes")

    if not title or not due_date:
        return jsonify({"status": "error", "message": "title and due_date required"}), 400

    task_id = hashlib.md5(f"{title}|{due_date}".encode()).hexdigest()[:12]
    task = {"id": task_id, "title": title, "due_date": due_date,
            "due_time": due_time, "priority": priority, "notes": notes, "completed": False}
    try:
        r = _backend("POST", "/tasks/store", json={"user_id": USER_ID, "tasks": _encrypt_tasks([task], USER_ID),
                                                    "timestamp": datetime.now(timezone.utc).isoformat()})
        if r.status_code == 200:
            return jsonify({"status": "success", "task": task})
        return jsonify({"status": "error", "message": r.text}), r.status_code
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 503

@app.route("/api/tasks/<task_id>", methods=["PUT"])
def edit_task(task_id):
    data = request.get_json(silent=True) or {}
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
        r = _backend("POST", "/tasks/store", json={"user_id": USER_ID, "tasks": _encrypt_tasks([task], USER_ID),
                                                    "timestamp": datetime.now(timezone.utc).isoformat()})
        if r.status_code == 200:
            return jsonify({"status": "success"})
        return jsonify({"status": "error", "message": r.text}), r.status_code
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 503

@app.route("/api/tasks/<task_id>/complete", methods=["POST"])
def complete_task(task_id):
    # Fetch current task, mark completed, upsert back
    try:
        r = _backend("GET", "/tasks/retrieve", params={"user_id": USER_ID})
        tasks = _decrypt_tasks(r.json().get("tasks", []), USER_ID) if r.status_code == 200 else []
        task = next((t for t in tasks if t.get("task_id") == task_id), None)
        if not task:
            return jsonify({"status": "error", "message": "Task not found"}), 404
        task["completed"] = True
        task["id"] = task.pop("task_id", task_id)
        r2 = _backend("POST", "/tasks/store", json={"user_id": USER_ID, "tasks": [task],
                                                     "timestamp": datetime.now(timezone.utc).isoformat()})
        # Also update character stats
        conn = get_db()
        completed = int(conn.execute("SELECT value FROM character WHERE key='tasks_completed'",).fetchone() or [0])[0] if conn.execute("SELECT value FROM character WHERE key='tasks_completed'").fetchone() else 0
        level = completed // 5
        conn.execute("INSERT OR REPLACE INTO character(key,value) VALUES('tasks_completed',?)", (str(completed + 1),))
        conn.execute("INSERT OR REPLACE INTO character(key,value) VALUES('level',?)", (str(level),))
        conn.commit()
        conn.close()
        return jsonify({"status": "success"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 503

@app.route("/api/tasks/<task_id>", methods=["DELETE"])
def delete_task(task_id):
    try:
        r = _backend("DELETE", f"/tasks/{task_id}", params={"user_id": USER_ID})
        if r.status_code == 200:
            return jsonify({"status": "success"})
        return jsonify({"status": "error", "message": r.text}), r.status_code
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 503

@app.route("/api/tasks/clear", methods=["POST"])
def clear_tasks_only():
    """Clear only regular tasks while preserving remote daily tasks."""
    try:
        r = _backend("GET", "/tasks/retrieve", params={"user_id": USER_ID})
        tasks = _decrypt_tasks(r.json().get("tasks", []), USER_ID) if r.status_code == 200 else []

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
                "user_id": USER_ID,
                "tasks": _encrypt_tasks(preserved_daily, USER_ID),
            },
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
def get_daily():
    today = date.today().isoformat()

    # Local web-only daily items
    conn = get_db()
    rows = conn.execute(
        "SELECT * FROM daily_tasks WHERE date=? ORDER BY id", (today,)).fetchall()
    conn.close()

    local_tasks = [{
        "id": f"local:{r['id']}",
        "title": r["title"],
        "done": bool(r["done"]),
        "source": "local",
    } for r in rows]

    # Remote daily items synced from desktop app
    remote_daily = []
    try:
        r = _backend("GET", "/tasks/retrieve", params={"user_id": USER_ID})
        if r.status_code == 200:
            tasks = _decrypt_tasks(r.json().get("tasks", []), USER_ID)
            _regular, remote_daily = _split_remote_tasks(tasks)
    except Exception:
        remote_daily = []

    combined = remote_daily + local_tasks
    deduped = []
    seen = set()
    for item in combined:
        key = (str(item.get("title", "")).strip().lower(), bool(item.get("done", False)))
        if key in seen:
            continue
        seen.add(key)
        deduped.append(item)

    return jsonify({"status": "success", "tasks": deduped})

@app.route("/api/daily", methods=["POST"])
def add_daily():
    data = request.get_json(silent=True) or {}
    title = data.get("title", "").strip()
    if not title:
        return jsonify({"status": "error", "message": "title required"}), 400
    today = date.today().isoformat()
    conn = get_db()
    conn.execute("INSERT INTO daily_tasks(title,date) VALUES(?,?)", (title, today))
    conn.commit()
    row_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    conn.close()

    # Best-effort mirror into remote backend so desktop and web daily lists can converge.
    try:
        remote_task_id = "daily:" + hashlib.md5(title.encode()).hexdigest()[:20]
        remote_task = {
            "id": remote_task_id,
            "title": title,
            "due_date": "",
            "due_time": "",
            "priority": "1",
            "notes": _encode_daily_payload(title, False),
            "completed": False,
        }
        _backend(
            "POST",
            "/tasks/store",
            json={
                "user_id": USER_ID,
                "tasks": _encrypt_tasks([remote_task], USER_ID),
                "timestamp": datetime.now(timezone.utc).isoformat(),
            },
        )
    except Exception:
        pass

    return jsonify({"status": "success", "id": f"local:{row_id}"})

@app.route("/api/daily/<task_id>/toggle", methods=["POST"])
def toggle_daily(task_id):
    if task_id.startswith("remote:"):
        remote_task_id = task_id.split(":", 1)[1]
        try:
            r = _backend("GET", "/tasks/retrieve", params={"user_id": USER_ID})
            if r.status_code != 200:
                return jsonify({"status": "error", "message": r.text}), r.status_code

            tasks = _decrypt_tasks(r.json().get("tasks", []), USER_ID)
            match = next((t for t in tasks if str(t.get("task_id") or t.get("id") or "") == remote_task_id), None)
            if not match:
                return jsonify({"status": "error", "message": "Daily task not found"}), 404

            payload = _decode_daily_payload(match.get("notes", ""))
            if not payload:
                return jsonify({"status": "error", "message": "Not a daily task"}), 400

            raw = (payload.get("raw") or match.get("title") or "").strip()
            done = bool(payload.get("completed", match.get("completed", False)))
            updated = dict(match)
            updated["id"] = remote_task_id
            updated["title"] = raw
            updated["completed"] = not done
            updated["notes"] = _encode_daily_payload(raw, not done)
            updated.pop("task_id", None)

            r2 = _backend(
                "POST",
                "/tasks/store",
                json={
                    "user_id": USER_ID,
                    "tasks": _encrypt_tasks([updated], USER_ID),
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
    conn.execute("UPDATE daily_tasks SET done = 1 - done WHERE id=?", (local_id,))
    conn.commit()
    conn.close()
    return jsonify({"status": "success"})

@app.route("/api/daily/<task_id>", methods=["DELETE"])
def delete_daily(task_id):
    if task_id.startswith("remote:"):
        remote_task_id = task_id.split(":", 1)[1]
        try:
            r = _backend("DELETE", f"/tasks/{remote_task_id}", params={"user_id": USER_ID})
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
    conn.execute("DELETE FROM daily_tasks WHERE id=?", (local_id,))
    conn.commit()
    conn.close()
    return jsonify({"status": "success"})

@app.route("/api/daily/clear", methods=["POST"])
def clear_daily_only():
    """Clear all daily tasks (remote + local) while preserving regular tasks."""
    try:
        r = _backend("GET", "/tasks/retrieve", params={"user_id": USER_ID})
        tasks = _decrypt_tasks(r.json().get("tasks", []), USER_ID) if r.status_code == 200 else []

        preserved_regular = []
        for task in tasks:
            if _decode_daily_payload(task.get("notes", "")):
                continue
            kept = dict(task)
            kept["id"] = str(kept.get("task_id") or kept.get("id") or "")
            kept.pop("task_id", None)
            preserved_regular.append(kept)

        r2 = _backend(
            "POST",
            "/tasks/replace",
            json={
                "user_id": USER_ID,
                "tasks": _encrypt_tasks(preserved_regular, USER_ID),
            },
        )
        if r2.status_code != 200:
            return jsonify({"status": "error", "message": r2.text}), r2.status_code

        conn = get_db()
        conn.execute("DELETE FROM daily_tasks")
        conn.commit()
        conn.close()

        return jsonify({"status": "success", "kept_regular": len(preserved_regular)})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 503

# ---------------------------------------------------------------------------
# AI API (proxy → ai_inference service)
# ---------------------------------------------------------------------------
@app.route("/api/ai/chat", methods=["POST"])
def ai_chat():
    data = request.get_json(silent=True) or {}
    prompt = data.get("prompt", "")
    model  = data.get("model", "")
    if not prompt:
        return jsonify({"status": "error", "message": "prompt required"}), 400
    try:
        r = _ai("POST", "/inference", json={"prompt": prompt, "model": model})
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

@app.route("/api/ai/models", methods=["GET"])
def ai_models():
    try:
        r = _ai("GET", "/models")
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

# ---------------------------------------------------------------------------
# Calendar / Weekly (computed from tasks)
# ---------------------------------------------------------------------------
@app.route("/api/calendar/<int:year>/<int:month>", methods=["GET"])
def calendar_data(year, month):
    try:
        r = _backend("GET", "/tasks/retrieve", params={"user_id": USER_ID})
        tasks = _decrypt_tasks(r.json().get("tasks", []), USER_ID) if r.status_code == 200 else []
        tasks, _daily = _split_remote_tasks(tasks)
    except Exception:
        tasks = []

    by_date = {}
    for t in tasks:
        d = t.get("due_date", "")
        try:
            dt = datetime.strptime(d, "%m-%d-%Y")
            if dt.year == year and dt.month == month:
                key = str(dt.day)
                by_date.setdefault(key, []).append({
                    "title": t.get("title"), "priority": t.get("priority"),
                    "color": _task_color(d)
                })
        except Exception:
            pass
    return jsonify({"status": "success", "tasks_by_day": by_date})

@app.route("/api/weekly", methods=["GET"])
def weekly_data():
    from datetime import timedelta
    try:
        r = _backend("GET", "/tasks/retrieve", params={"user_id": USER_ID})
        tasks = _decrypt_tasks(r.json().get("tasks", []), USER_ID) if r.status_code == 200 else []
        tasks, _daily = _split_remote_tasks(tasks)
    except Exception:
        tasks = []

    today = date.today()
    start = today - timedelta(days=today.weekday())  # Monday
    week_days = [(start + timedelta(days=i)) for i in range(7)]
    week_dates = {d.strftime("%m-%d-%Y"): [] for d in week_days}

    for t in tasks:
        d = t.get("due_date", "")
        if d in week_dates:
            week_dates[d].append({
                "title": t.get("title"), "priority": t.get("priority"),
                "due_time": t.get("due_time", ""), "color": _task_color(d)
            })
    return jsonify({"status": "success", "week": week_dates,
                    "week_days": [d.strftime("%a %b %d") for d in week_days],
                    "week_dates": [d.strftime("%m-%d-%Y") for d in week_days]})

# ---------------------------------------------------------------------------
# Character / Stats
# ---------------------------------------------------------------------------
@app.route("/api/character", methods=["GET"])
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
def _normalize_model_list(models):
    """Normalize model list: trimmed, unique, non-empty strings."""
    out = []
    seen = set()
    for item in models or []:
        model = str(item or "").strip()
        if not model or model in seen:
            continue
        seen.add(model)
        out.append(model)
    return out


def _get_saved_ai_models(default_model=""):
    """Return saved model list from settings storage."""
    raw = _get_setting("phala_ai_models", "")
    models = []
    if raw:
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, list):
                models = parsed
        except Exception:
            models = []

    models = _normalize_model_list(models)
    if default_model and default_model not in models:
        models.insert(0, default_model)
    return models


def _save_ai_models(models):
    """Persist normalized model list as JSON string."""
    normalized = _normalize_model_list(models)
    _set_setting("phala_ai_models", json.dumps(normalized, ensure_ascii=False))


@app.route("/api/settings", methods=["GET"])
def get_settings():
    workspace_key_ready = bool(_workspace_key_for_user(USER_ID))
    default_model = _get_setting("phala_ai_model", os.getenv("PHALA_AI_MODEL", "")).strip()
    saved_models = _get_saved_ai_models(default_model)
    return jsonify({"status": "success", "settings": {
        "use_24_hour": _get_setting("use_24_hour", "true") == "true",
        "web_user_id": USER_ID,
        "phala_ai_model": default_model,
        "phala_ai_models": saved_models,
        "crypto": {
            "device_id": _get_setting("crypto_device_id", "") or None,
            "workspace_key_ready": workspace_key_ready,
            "enc2_supported": ASYMMETRIC_CRYPTO_AVAILABLE,
        },
    }})


@app.route("/api/crypto/status", methods=["GET"])
def crypto_status():
    """Return web-ui device encryption status for troubleshooting ENC2 access."""
    try:
        resp = _backend("GET", "/crypto/devices", params={"user_id": USER_ID})
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
        "workspace_key_ready": bool(_workspace_key_for_user(USER_ID)),
        "user_id": USER_ID,
    })

@app.route("/api/settings", methods=["POST"])
def save_settings():
    data = request.get_json(silent=True) or {}
    if "use_24_hour" in data:
        _set_setting("use_24_hour", str(data["use_24_hour"]).lower())
    if "phala_ai_model" in data:
        _set_setting("phala_ai_model", str(data["phala_ai_model"]).strip())
    if "phala_ai_models" in data and isinstance(data["phala_ai_models"], list):
        _save_ai_models(data["phala_ai_models"])
    return jsonify({"status": "success"})

# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------
@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok", "service": "web_ui",
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "user_id": USER_ID})


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
    }

    for name, svc in services.items():
        if svc.get("url") is None:
            continue
        try:
            resp = req.get(svc["url"], headers=_headers(), timeout=5)
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
