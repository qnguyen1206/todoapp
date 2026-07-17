"""
Backend Storage Service for TODO App CVM
Handles encrypted task storage, retrieval, and sync via PostgreSQL.
"""

import json
import os
import logging
from datetime import datetime, timezone

from flask import Flask, request, jsonify
from flask_cors import CORS
import psycopg2
import psycopg2.extras

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
    """Return error response if API key invalid, else None."""
    if not API_KEY:
        return None  # no key configured → open (dev mode)
    key = request.headers.get("X-API-Key") or request.args.get("api_key")
    if key != API_KEY:
        return jsonify({"status": "error", "message": "Unauthorized"}), 401
    return None


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
            """)
        conn.commit()
        log.info("Database initialised")
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
        return jsonify({"status": "ok", "service": "backend", "timestamp": datetime.now(timezone.utc).isoformat()})
    except Exception as exc:
        return jsonify({"status": "error", "message": str(exc)}), 503


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
