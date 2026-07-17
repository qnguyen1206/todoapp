"""
Task Sync Service for TODO App CVM
Handles encrypted P2P task sharing between users via PostgreSQL.
"""

import os
import json
import logging
from datetime import datetime, timezone

import psycopg2
import psycopg2.extras
from flask import Flask, request, jsonify
from flask_cors import CORS

logging.basicConfig(level=os.getenv("LOG_LEVEL", "info").upper())
log = logging.getLogger(__name__)

app = Flask(__name__)
CORS(app)

DATABASE_URL = os.environ.get("DATABASE_URL", "")
API_KEY = os.environ.get("API_KEY", "")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def get_db():
    conn = psycopg2.connect(DATABASE_URL)
    conn.autocommit = False
    return conn


def require_api_key():
    if not API_KEY:
        return None
    key = request.headers.get("X-API-Key") or request.args.get("api_key")
    if key != API_KEY:
        return jsonify({"status": "error", "message": "Unauthorized"}), 401
    return None


def init_db():
    conn = get_db()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS shared_tasks (
                    id          SERIAL PRIMARY KEY,
                    from_user   TEXT        NOT NULL,
                    to_user     TEXT        NOT NULL,
                    task_id     TEXT        NOT NULL,
                    task_data   JSONB       NOT NULL,
                    shared_at   TIMESTAMPTZ DEFAULT NOW(),
                    accepted    BOOLEAN     DEFAULT FALSE
                );
                CREATE INDEX IF NOT EXISTS idx_shared_to   ON shared_tasks(to_user);
                CREATE INDEX IF NOT EXISTS idx_shared_from ON shared_tasks(from_user);
            """)
        conn.commit()
        log.info("task_sync DB initialised")
    except Exception as exc:
        log.error("DB init error: %s", exc)
        conn.rollback()
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
        return jsonify({
            "status": "ok",
            "service": "task_sync",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })
    except Exception as exc:
        return jsonify({"status": "error", "message": str(exc)}), 503


@app.route("/share", methods=["POST"])
def share_tasks():
    """
    Share one or more tasks with a list of recipients.

    Body:
        {
            "user_id":    "sender_id",
            "recipients": ["user_a", "user_b"],
            "tasks":      [{"id": "...", "title": "...", ...}]
        }
    """
    err = require_api_key()
    if err:
        return err

    data = request.get_json(silent=True) or {}
    from_user = data.get("user_id")
    recipients = data.get("recipients", [])
    tasks = data.get("tasks", [])

    if not from_user:
        return jsonify({"status": "error", "message": "user_id required"}), 400
    if not recipients:
        return jsonify({"status": "error", "message": "recipients required"}), 400
    if not tasks:
        return jsonify({"status": "error", "message": "tasks required"}), 400

    conn = get_db()
    shared_ids = []
    try:
        with conn.cursor() as cur:
            for task in tasks:
                task_id = str(task.get("id", ""))
                for to_user in recipients:
                    cur.execute("""
                        INSERT INTO shared_tasks (from_user, to_user, task_id, task_data, shared_at)
                        VALUES (%s, %s, %s, %s, NOW())
                        RETURNING id
                    """, (from_user, to_user, task_id, json.dumps(task)))
                    shared_ids.append(cur.fetchone()[0])
        conn.commit()
        return jsonify({
            "status": "success",
            "shared_count": len(shared_ids),
            "shared_ids": shared_ids,
        })
    except Exception as exc:
        conn.rollback()
        log.error("share error: %s", exc)
        return jsonify({"status": "error", "message": str(exc)}), 500
    finally:
        conn.close()


@app.route("/shared", methods=["GET"])
def get_shared_tasks():
    """
    Return all tasks shared WITH a user (their inbox).
    Query: ?user_id=xxx&unaccepted_only=true
    """
    err = require_api_key()
    if err:
        return err

    user_id = request.args.get("user_id")
    unaccepted_only = request.args.get("unaccepted_only", "false").lower() == "true"

    if not user_id:
        return jsonify({"status": "error", "message": "user_id required"}), 400

    conn = get_db()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            if unaccepted_only:
                cur.execute("""
                    SELECT id, from_user, task_id, task_data, shared_at, accepted
                    FROM shared_tasks
                    WHERE to_user = %s AND accepted = FALSE
                    ORDER BY shared_at DESC
                """, (user_id,))
            else:
                cur.execute("""
                    SELECT id, from_user, task_id, task_data, shared_at, accepted
                    FROM shared_tasks
                    WHERE to_user = %s
                    ORDER BY shared_at DESC
                """, (user_id,))
            rows = cur.fetchall()

        result = []
        for r in rows:
            entry = dict(r)
            if entry.get("shared_at"):
                entry["shared_at"] = entry["shared_at"].isoformat()
            result.append(entry)

        return jsonify({"status": "success", "shared_tasks": result})
    except Exception as exc:
        log.error("get_shared error: %s", exc)
        return jsonify({"status": "error", "message": str(exc)}), 500
    finally:
        conn.close()


@app.route("/shared/<int:share_id>/accept", methods=["POST"])
def accept_shared_task(share_id):
    """Mark a shared task as accepted."""
    err = require_api_key()
    if err:
        return err

    conn = get_db()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE shared_tasks SET accepted = TRUE WHERE id = %s",
                (share_id,)
            )
        conn.commit()
        return jsonify({"status": "success", "accepted": share_id})
    except Exception as exc:
        conn.rollback()
        return jsonify({"status": "error", "message": str(exc)}), 500
    finally:
        conn.close()


@app.route("/shared/<int:share_id>", methods=["DELETE"])
def delete_shared_task(share_id):
    """Delete a shared task entry."""
    err = require_api_key()
    if err:
        return err

    conn = get_db()
    try:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM shared_tasks WHERE id = %s", (share_id,))
        conn.commit()
        return jsonify({"status": "success", "deleted": share_id})
    except Exception as exc:
        conn.rollback()
        return jsonify({"status": "error", "message": str(exc)}), 500
    finally:
        conn.close()


@app.route("/shared/sent", methods=["GET"])
def get_sent_tasks():
    """Return tasks the user has shared with others (their outbox)."""
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
                SELECT id, to_user, task_id, task_data, shared_at, accepted
                FROM shared_tasks WHERE from_user = %s ORDER BY shared_at DESC
            """, (user_id,))
            rows = cur.fetchall()
        result = []
        for r in rows:
            entry = dict(r)
            if entry.get("shared_at"):
                entry["shared_at"] = entry["shared_at"].isoformat()
            result.append(entry)
        return jsonify({"status": "success", "sent_tasks": result})
    except Exception as exc:
        return jsonify({"status": "error", "message": str(exc)}), 500
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Startup – retry until postgres is ready
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
    app.run(host="0.0.0.0", port=5002, debug=False)
