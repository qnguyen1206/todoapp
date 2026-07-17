"""
Web UI Service for TODO App CVM
Serves a browser-based interface matching the Python desktop app.
Proxies task/AI/sync requests to the internal CVM services.
"""

import os
import json
import hashlib
import logging
import sqlite3
from datetime import datetime, timezone, date
from pathlib import Path

import requests as req
from flask import Flask, render_template, request, jsonify, redirect, url_for
from flask_cors import CORS

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
    kwargs.setdefault("timeout", 120)
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
            tasks = r.json().get("tasks", [])
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
        r = _backend("POST", "/tasks/store", json={"user_id": USER_ID, "tasks": [task],
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
        r = _backend("POST", "/tasks/store", json={"user_id": USER_ID, "tasks": [task],
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
        tasks = r.json().get("tasks", []) if r.status_code == 200 else []
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

# ---------------------------------------------------------------------------
# Daily Tasks API (local SQLite)
# ---------------------------------------------------------------------------
@app.route("/api/daily", methods=["GET"])
def get_daily():
    today = date.today().isoformat()
    conn = get_db()
    rows = conn.execute(
        "SELECT * FROM daily_tasks WHERE date=? ORDER BY id", (today,)).fetchall()
    conn.close()
    return jsonify({"status": "success", "tasks": [dict(r) for r in rows]})

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
    return jsonify({"status": "success", "id": row_id})

@app.route("/api/daily/<int:task_id>/toggle", methods=["POST"])
def toggle_daily(task_id):
    conn = get_db()
    conn.execute("UPDATE daily_tasks SET done = 1 - done WHERE id=?", (task_id,))
    conn.commit()
    conn.close()
    return jsonify({"status": "success"})

@app.route("/api/daily/<int:task_id>", methods=["DELETE"])
def delete_daily(task_id):
    conn = get_db()
    conn.execute("DELETE FROM daily_tasks WHERE id=?", (task_id,))
    conn.commit()
    conn.close()
    return jsonify({"status": "success"})

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
        return jsonify({"status": "error", "message": r.text}), r.status_code
    except req.exceptions.ConnectionError:
        return jsonify({"status": "error",
                        "message": "AI service not available. Is Ollama running inside the CVM?"}), 503
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

# ---------------------------------------------------------------------------
# Calendar / Weekly (computed from tasks)
# ---------------------------------------------------------------------------
@app.route("/api/calendar/<int:year>/<int:month>", methods=["GET"])
def calendar_data(year, month):
    try:
        r = _backend("GET", "/tasks/retrieve", params={"user_id": USER_ID})
        tasks = r.json().get("tasks", []) if r.status_code == 200 else []
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
        tasks = r.json().get("tasks", []) if r.status_code == 200 else []
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
@app.route("/api/settings", methods=["GET"])
def get_settings():
    return jsonify({"status": "success", "settings": {
        "use_24_hour": _get_setting("use_24_hour", "true") == "true",
        "web_user_id": USER_ID,
    }})

@app.route("/api/settings", methods=["POST"])
def save_settings():
    data = request.get_json(silent=True) or {}
    for key in ("use_24_hour",):
        if key in data:
            _set_setting(key, str(data[key]).lower())
    return jsonify({"status": "success"})

# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------
@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok", "service": "web_ui",
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "user_id": USER_ID})

# ---------------------------------------------------------------------------
# Startup
# ---------------------------------------------------------------------------
init_db()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080, debug=False)
