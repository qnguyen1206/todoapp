"""
Scheduler Service for TODO App CVM
Runs background cron jobs (reminders, cleanup, auto-sync) using APScheduler.
Jobs persist across restarts via the PostgreSQL job store.
"""

import os
import json
import logging
from datetime import datetime, timezone

import psycopg2
import psycopg2.extras
from flask import Flask, request, jsonify
from flask_cors import CORS
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.jobstores.memory import MemoryJobStore
from apscheduler.executors.pool import ThreadPoolExecutor

logging.basicConfig(level=os.getenv("LOG_LEVEL", "info").upper())
log = logging.getLogger(__name__)

app = Flask(__name__)
CORS(app)

DATABASE_URL = os.environ.get("DATABASE_URL", "")
API_KEY = os.environ.get("API_KEY", "")

# ---------------------------------------------------------------------------
# APScheduler setup
# ---------------------------------------------------------------------------

scheduler = BackgroundScheduler(
    jobstores={"default": MemoryJobStore()},
    executors={"default": ThreadPoolExecutor(max_workers=4)},
    job_defaults={"coalesce": True, "max_instances": 1},
    timezone="UTC",
)


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
                CREATE TABLE IF NOT EXISTS scheduled_jobs (
                    job_id          TEXT PRIMARY KEY,
                    job_type        TEXT        NOT NULL,
                    cron_expr       TEXT        NOT NULL,
                    parameters      JSONB       NOT NULL DEFAULT '{}',
                    created_at      TIMESTAMPTZ DEFAULT NOW(),
                    last_run        TIMESTAMPTZ,
                    execution_count INTEGER     DEFAULT 0,
                    active          BOOLEAN     DEFAULT TRUE
                );
            """)
        conn.commit()
        log.info("scheduler DB initialised")
    except Exception as exc:
        log.error("DB init error: %s", exc)
        conn.rollback()
    finally:
        conn.close()


def parse_cron(cron_expr: str) -> dict:
    """Parse a 5-part cron string into APScheduler keyword arguments."""
    parts = cron_expr.strip().split()
    if len(parts) != 5:
        raise ValueError(f"Invalid cron expression: '{cron_expr}' (need 5 fields)")
    keys = ["minute", "hour", "day", "month", "day_of_week"]
    return dict(zip(keys, parts))


# ---------------------------------------------------------------------------
# Built-in job handlers
# ---------------------------------------------------------------------------

def job_reminder(parameters: dict):
    """Log upcoming deadlines (extend with actual notification logic)."""
    user_id = parameters.get("user_id", "all")
    log.info("[reminder] Checking deadlines for user=%s at %s", user_id, datetime.now(timezone.utc).isoformat())
    # TODO: query backend service and send push / email notification


def job_cleanup(parameters: dict):
    """Archive completed tasks older than N days."""
    days = int(parameters.get("days_old", 30))
    log.info("[cleanup] Archiving tasks completed more than %d days ago", days)
    conn = get_db()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                DELETE FROM tasks
                WHERE completed = TRUE
                  AND updated_at < NOW() - INTERVAL '%s days'
            """, (days,))
            deleted = cur.rowcount
        conn.commit()
        log.info("[cleanup] Deleted %d old completed tasks", deleted)
    except Exception as exc:
        conn.rollback()
        log.warning("[cleanup] Could not reach tasks table (is backend schema in same DB?): %s", exc)
    finally:
        conn.close()


def job_sync(parameters: dict):
    """Placeholder: trigger an external sync webhook."""
    webhook = parameters.get("webhook_url")
    if webhook:
        try:
            import requests as req
            req.post(webhook, json={"trigger": "auto_sync", "ts": datetime.now(timezone.utc).isoformat()}, timeout=10)
            log.info("[sync] Webhook called: %s", webhook)
        except Exception as exc:
            log.warning("[sync] Webhook failed: %s", exc)
    else:
        log.info("[sync] Auto-sync job ran (no webhook configured)")


def job_overdue_alert(parameters: dict):
    """Log overdue tasks (extend with notification logic)."""
    log.info("[overdue_alert] Checking overdue tasks at %s", datetime.now(timezone.utc).isoformat())


JOB_HANDLERS = {
    "reminder": job_reminder,
    "cleanup": job_cleanup,
    "sync": job_sync,
    "notification": job_overdue_alert,
}


def make_job_fn(job_id: str, job_type: str, parameters: dict):
    """Return a closure that runs the job and updates last_run."""
    handler = JOB_HANDLERS.get(job_type, lambda p: log.info("Unknown job type: %s", job_type))

    def run():
        log.info("Running job %s (type=%s)", job_id, job_type)
        try:
            handler(parameters)
        except Exception as exc:
            log.error("Job %s failed: %s", job_id, exc)
        # Update DB
        conn = get_db()
        try:
            with conn.cursor() as cur:
                cur.execute("""
                    UPDATE scheduled_jobs
                    SET last_run = NOW(), execution_count = execution_count + 1
                    WHERE job_id = %s
                """, (job_id,))
            conn.commit()
        except Exception:
            conn.rollback()
        finally:
            conn.close()

    return run


def restore_jobs_from_db():
    """Reload active jobs from DB after service restart."""
    conn = get_db()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("SELECT * FROM scheduled_jobs WHERE active = TRUE")
            rows = cur.fetchall()
        for row in rows:
            cron_kwargs = parse_cron(row["cron_expr"])
            scheduler.add_job(
                make_job_fn(row["job_id"], row["job_type"], row["parameters"]),
                "cron",
                id=row["job_id"],
                replace_existing=True,
                **cron_kwargs,
            )
            log.info("Restored job %s (%s)", row["job_id"], row["cron_expr"])
    except Exception as exc:
        log.error("Failed to restore jobs: %s", exc)
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.route("/health", methods=["GET"])
def health():
    jobs = [{"id": j.id, "next_run": j.next_run_time.isoformat() if j.next_run_time else None}
            for j in scheduler.get_jobs()]
    return jsonify({
        "status": "ok",
        "service": "scheduler",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "active_jobs": len(jobs),
        "jobs": jobs,
    })


@app.route("/schedule", methods=["POST"])
def schedule_job():
    """
    Add or replace a scheduled job.

    Body:
        {
            "job_id":     "unique-id",
            "job_type":   "reminder|cleanup|sync|notification",
            "schedule":   "0 9 * * *",   (5-field cron, UTC)
            "parameters": {}
        }
    """
    err = require_api_key()
    if err:
        return err

    data = request.get_json(silent=True) or {}
    job_id = data.get("job_id")
    job_type = data.get("job_type")
    cron_expr = data.get("schedule", "")
    parameters = data.get("parameters", {})

    if not job_id or not job_type or not cron_expr:
        return jsonify({"status": "error", "message": "job_id, job_type, and schedule are required"}), 400

    if job_type not in JOB_HANDLERS:
        return jsonify({
            "status": "error",
            "message": f"Unknown job_type '{job_type}'. Valid: {list(JOB_HANDLERS.keys())}",
        }), 400

    try:
        cron_kwargs = parse_cron(cron_expr)
    except ValueError as exc:
        return jsonify({"status": "error", "message": str(exc)}), 400

    # Persist to DB
    conn = get_db()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO scheduled_jobs (job_id, job_type, cron_expr, parameters, active)
                VALUES (%s, %s, %s, %s, TRUE)
                ON CONFLICT (job_id) DO UPDATE SET
                    job_type   = EXCLUDED.job_type,
                    cron_expr  = EXCLUDED.cron_expr,
                    parameters = EXCLUDED.parameters,
                    active     = TRUE
            """, (job_id, job_type, cron_expr, json.dumps(parameters)))
        conn.commit()
    except Exception as exc:
        conn.rollback()
        log.error("DB error scheduling job: %s", exc)
        return jsonify({"status": "error", "message": str(exc)}), 500
    finally:
        conn.close()

    # Register with APScheduler
    scheduler.add_job(
        make_job_fn(job_id, job_type, parameters),
        "cron",
        id=job_id,
        replace_existing=True,
        **cron_kwargs,
    )

    job = scheduler.get_job(job_id)
    next_run = job.next_run_time.isoformat() if job and job.next_run_time else None

    return jsonify({"status": "success", "job_id": job_id, "next_run": next_run})


@app.route("/schedule/<job_id>", methods=["DELETE"])
def cancel_job(job_id):
    """Cancel and remove a job."""
    err = require_api_key()
    if err:
        return err

    scheduler.remove_job(job_id)

    conn = get_db()
    try:
        with conn.cursor() as cur:
            cur.execute("UPDATE scheduled_jobs SET active = FALSE WHERE job_id = %s", (job_id,))
        conn.commit()
    except Exception as exc:
        conn.rollback()
        log.error("DB error cancelling job: %s", exc)
    finally:
        conn.close()

    return jsonify({"status": "success", "cancelled": job_id})


@app.route("/schedule/<job_id>", methods=["GET"])
def get_job_status(job_id):
    """Return status of a specific job."""
    err = require_api_key()
    if err:
        return err

    conn = get_db()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("SELECT * FROM scheduled_jobs WHERE job_id = %s", (job_id,))
            row = cur.fetchone()
    except Exception as exc:
        return jsonify({"status": "error", "message": str(exc)}), 500
    finally:
        conn.close()

    if not row:
        return jsonify({"status": "error", "message": "Job not found"}), 404

    apsjob = scheduler.get_job(job_id)
    result = dict(row)
    for key in ("created_at", "last_run"):
        if result.get(key):
            result[key] = result[key].isoformat()
    result["next_run"] = apsjob.next_run_time.isoformat() if apsjob and apsjob.next_run_time else None
    return jsonify({"status": "success", **result})


@app.route("/schedule", methods=["GET"])
def list_jobs():
    """List all active jobs."""
    err = require_api_key()
    if err:
        return err

    conn = get_db()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("SELECT * FROM scheduled_jobs WHERE active = TRUE ORDER BY created_at DESC")
            rows = cur.fetchall()
    except Exception as exc:
        return jsonify({"status": "error", "message": str(exc)}), 500
    finally:
        conn.close()

    jobs = []
    for row in rows:
        entry = dict(row)
        for key in ("created_at", "last_run"):
            if entry.get(key):
                entry[key] = entry[key].isoformat()
        apsjob = scheduler.get_job(row["job_id"])
        entry["next_run"] = apsjob.next_run_time.isoformat() if apsjob and apsjob.next_run_time else None
        jobs.append(entry)

    return jsonify({"status": "success", "jobs": jobs})


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
try:
    restore_jobs_from_db()
    scheduler.start()
    log.info("APScheduler started with %d jobs", len(scheduler.get_jobs()))
except Exception as exc:
    log.error("Scheduler start failed: %s", exc)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5003, debug=False)
