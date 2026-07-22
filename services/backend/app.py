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

from flask import Flask, request, jsonify
from flask_cors import CORS
import psycopg2
import psycopg2.extras
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec, utils

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
def list_crypto_devices():
    """List public device records and each device's encrypted key envelope."""
    err = require_api_key()
    if err:
        return err

    user_id = (request.args.get("user_id") or "").strip()
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
def register_crypto_device():
    """Register a device public key.  Only the first device becomes active."""
    err = require_api_key()
    if err:
        return err

    data = request.get_json(silent=True) or {}
    user_id = str(data.get("user_id") or "").strip()
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
def approve_crypto_device(device_id):
    """Activate a pending device after an active device signs its key envelope."""
    err = require_api_key()
    if err:
        return err

    data = request.get_json(silent=True) or {}
    user_id = str(data.get("user_id") or "").strip()
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
def store_tasks():
    """Upsert a list of tasks for a user."""
    err = require_api_key()
    if err:
        return err

    data = request.get_json(silent=True) or {}
    user_id = data.get("user_id")
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
def retrieve_tasks():
    """Return all tasks for a user."""
    err = require_api_key()
    if err:
        return err

    user_id = request.args.get("user_id")
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
def sync_tasks():
    """Merge local tasks with server; return the unified list."""
    err = require_api_key()
    if err:
        return err

    data = request.get_json(silent=True) or {}
    user_id = data.get("user_id")
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
def delete_task(task_id):
    """Delete a specific task for a user."""
    err = require_api_key()
    if err:
        return err

    user_id = request.args.get("user_id")
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
def replace_tasks():
    """Delete ALL existing tasks for a user then insert the provided list.
    This is the force-push / overwrite operation."""
    err = require_api_key()
    if err:
        return err

    data = request.get_json(silent=True) or {}
    user_id = data.get("user_id")
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
