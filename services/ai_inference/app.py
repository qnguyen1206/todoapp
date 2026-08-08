"""
AI Inference Service for TODO App CVM

Proxies requests to Phala Confidential AI and returns the model output plus
receipt metadata. Attestation/session verification is intentionally omitted.
"""

import os
import logging
import json
import secrets
import requests
from datetime import datetime, timezone
import threading

import requests
from flask import Flask, request, jsonify
from flask_cors import CORS
from werkzeug.exceptions import HTTPException

logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO").upper())
log = logging.getLogger(__name__)

app = Flask(__name__)
CORS(app)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

API_KEY = os.getenv("API_KEY", "")

PHALA_AI_URL = os.getenv(
    "PHALA_AI_URL",
    "https://inference.phala.com/v1/chat/completions",
)

PHALA_AI_API_KEY = os.getenv("PHALA_AI_API_KEY", "")

DEFAULT_MODEL = os.getenv(
    "PHALA_AI_MODEL",
    "deepseek/deepseek-v4-flash",
)
FALLBACK_MODEL = os.getenv(
    "PHALA_AI_FALLBACK_MODEL",
    "phala/qwen3.5-27b",
)

AI_TIMEOUT    = int(os.getenv("AI_TIMEOUT", "1200"))
ATTESTATION_TIMEOUT = int(os.getenv("ATTESTATION_TIMEOUT", "1200"))

SYSTEM_PROMPT = "You are a helpful task management assistant."

ATTESTATION_BASE = "https://inference.phala.com"

# In-memory cache for attestation reports to ensure we fetch each nonce only once.
ATT_CACHE = {}


def _background_fetch_attestation(nonce, timeout=10):
    """Background fetch that populates ATT_CACHE without blocking the main request.

    Uses a short timeout to avoid long-running blocking fetches.
    """
    if not nonce or nonce in ATT_CACHE:
        return
    try:
        url = f"{ATTESTATION_BASE}/v1/aci/attestation"
        r = requests.get(
            url,
            params={"nonce": nonce},
            headers={"Authorization": f"Bearer {PHALA_AI_API_KEY}", "Accept": "application/json"},
            timeout=timeout,
        )
        if r.ok:
            try:
                payload = r.json()
            except Exception:
                payload = {"status": "error", "message": "invalid json from attestation endpoint"}
        else:
            payload = {"status": "error", "message": f"HTTP {r.status_code}", "upstream": r.text}
        ATT_CACHE[nonce] = payload
    except Exception as exc:
        log.exception("Background attestation fetch failed for nonce %s", nonce)
        ATT_CACHE[nonce] = {"status": "error", "message": str(exc)}

@app.errorhandler(Exception)
def handle_unexpected_exception(exc):
    if isinstance(exc, HTTPException):
        return jsonify({"status": "error", "message": exc.description or "HTTP error"}), exc.code
    log.exception("Unhandled exception")
    return jsonify({"status": "error", "message": "Internal AI service error"}), 500


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def require_api_key():
    if not API_KEY:
        return None
    key = request.headers.get("X-API-Key") or request.args.get("api_key")
    if key != API_KEY:
        return jsonify({"status": "error", "message": "Unauthorized"}), 401
    return None


def _extract_text_response(payload):
    try:
        choices = payload.get("choices") or []
        if choices:
            message = choices[0].get("message") or {}
            content = message.get("content")
            if isinstance(content, str) and content.strip():
                return content

            if isinstance(content, list):
                text_parts = []
                for part in content:
                    if isinstance(part, dict):
                        txt = part.get("text") or part.get("content") or ""
                        if txt:
                            text_parts.append(str(txt))
                    elif isinstance(part, str):
                        text_parts.append(part)
                if text_parts:
                    return "\n".join(text_parts)

        if isinstance(payload.get("response"), str):
            return payload["response"]
        if isinstance(payload.get("text"), str):
            return payload["text"]
    except Exception:
        pass

    return ""


def phala_request(messages, model, nonce):
    """Send a chat completion request to Phala Confidential AI."""

    headers = {
        "Authorization": f"Bearer {PHALA_AI_API_KEY}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }

    payload = {
        "model": model,
        "messages": messages,
    }

    request_bytes = json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8")

    response = requests.post(
        PHALA_AI_URL,
        headers=headers,
        data=request_bytes,
        timeout=AI_TIMEOUT,
    )
    response.raise_for_status()

    receipt_id = response.headers.get("x-receipt-id", "").strip()

    return {
        "json": response.json(),
        "receipt_id": receipt_id,
        "nonce": nonce,
    }


def _is_upstream_verification_route_failure(exc):
    """Detect route/provider verification failures that should trigger model fallback."""
    resp = getattr(exc, "response", None)
    if resp is None or resp.status_code != 503:
        return False

    try:
        payload = resp.json()
    except Exception:
        payload = {}

    err = payload.get("error", {}) if isinstance(payload, dict) else {}
    msg = str(err.get("message", "") or "").lower()
    err_type = str(err.get("type", "") or "").lower()

    return (
        "upstream verification failed" in msg
        or err_type == "service_unavailable"
    )


def phala_request_with_fallback(messages, requested_model, nonce):
    """Try requested model first; retry once on route verification failure."""
    model = requested_model or DEFAULT_MODEL
    try:
        result = phala_request(messages, model, nonce)
        result["used_model"] = model
        return result
    except requests.exceptions.HTTPError as exc:
        # Retry only when the selected route is unavailable and fallback is different.
        if model != FALLBACK_MODEL and _is_upstream_verification_route_failure(exc):
            log.warning("Primary model route unavailable, retrying fallback model: %s", FALLBACK_MODEL)
            result = phala_request(messages, FALLBACK_MODEL, nonce)
            result["used_model"] = FALLBACK_MODEL
            result["fallback_from"] = model
            return result
        raise

def get_attestation(nonce):
    url = f"{ATTESTATION_BASE}/v1/aci/attestation"

    r = requests.get(
        url,
        params={"nonce": nonce},
        headers={
            "Authorization": f"Bearer {PHALA_AI_API_KEY}",
            "Accept": "application/json",
        },
        timeout=ATTESTATION_TIMEOUT,
    )

    if not r.ok:
        log.error(
            "Phala attestation HTTP %s: %s",
            r.status_code,
            r.text,
        )

    r.raise_for_status()
    return r.json()


def get_attestation_cached(nonce):
    """Return cached attestation if available; otherwise fetch and cache it.

    This helper never raises for common HTTP errors to avoid failing the AI
    response flow — callers can inspect the returned dict for error shapes.
    """
    if not nonce:
        raise ValueError("nonce required")

    if nonce in ATT_CACHE:
        return ATT_CACHE[nonce]

    try:
        report = get_attestation(nonce)
        ATT_CACHE[nonce] = report
        return report
    except Exception as exc:
        # Log and return an error-shaped dict so callers can decide what to do.
        log.exception("Failed to fetch attestation for nonce %s", nonce)
        return {"status": "error", "message": str(exc)}

# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.route("/health", methods=["GET"])
def health():
    return jsonify({
        "status": "ok",
        "service": "ai_inference",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "provider": "Phala Confidential AI",
        "endpoint": PHALA_AI_URL,
        "default_model": DEFAULT_MODEL,
        "configured": bool(PHALA_AI_API_KEY),
    })


@app.route("/models", methods=["GET"])
def models():
    err = require_api_key()
    if err:
        return err

    return jsonify({
        "status": "success",
        "models": list(dict.fromkeys([m for m in [DEFAULT_MODEL, FALLBACK_MODEL] if m]))
    })


@app.route("/inference", methods=["POST"])
def inference():
    err = require_api_key()
    if err:
        return err

    data = request.get_json(silent=True) or {}
    prompt = data.get("prompt", "").strip()
    if not prompt:
        return jsonify({"status": "error", "message": "prompt is required"}), 400

    requested_model = data.get("model") or DEFAULT_MODEL
    system = data.get("system") or SYSTEM_PROMPT
    context_items = data.get("context", [])

    if context_items:
        context_text = "\n".join(str(item) for item in context_items)
        prompt = f"Context:\n{context_text}\n\nUser:\n{prompt}"

    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": prompt},
    ]

    try:
        nonce = secrets.token_urlsafe(32)
        result = phala_request_with_fallback(messages, requested_model, nonce)
        response_text = _extract_text_response(result.get("json", {}))
        if not response_text:
            return jsonify({"status": "error",
                            "message": "Provider returned an unexpected response format",
                            "receipt_id": result.get("receipt_id", "")}), 502

        # Kick off a background attestation fetch (short timeout) so the
        # response is returned immediately and the attestation is cached for
        # subsequent /attestation requests or client fetches.
        try:
            t = threading.Thread(target=_background_fetch_attestation, args=(nonce, min(10, ATTESTATION_TIMEOUT)))
            t.daemon = True
            t.start()
        except Exception:
            log.exception("Failed to start background attestation fetch for nonce %s", nonce)

        return jsonify({"status": "success", "response": response_text,
                        "model": result.get("used_model", requested_model),
                        "nonce": result.get("nonce", ""),
                        "receipt_id": result.get("receipt_id", "")})

    except requests.exceptions.Timeout:
        return jsonify({"status": "error", "message": "Phala AI request timed out"}), 504
    except requests.exceptions.HTTPError as exc:
        if _is_upstream_verification_route_failure(exc):
            return jsonify({
                "status": "error",
                "message": "Selected model route is currently unavailable upstream. Try a different model or wait a moment.",
            }), 503
        return jsonify({"status": "error", "message": f"Phala AI returned {exc.response.status_code}: {exc.response.text}"}), 502
    except requests.exceptions.ConnectionError:
        return jsonify({"status": "error", "message": "Unable to connect to Phala AI"}), 503
    except Exception as exc:
        log.exception("Inference error")
        return jsonify({"status": "error", "message": str(exc)}), 500


@app.route("/chat", methods=["POST"])
def chat():
    err = require_api_key()
    if err:
        return err

    data = request.get_json(silent=True) or {}
    messages = data.get("messages")
    if not messages:
        return jsonify({"status": "error", "message": "messages list is required"}), 400

    requested_model = data.get("model") or DEFAULT_MODEL

    try:
        nonce = secrets.token_urlsafe(32)
        result = phala_request_with_fallback(messages, requested_model, nonce)

        # Start background attestation fetch and return the chat response
        try:
            t = threading.Thread(target=_background_fetch_attestation, args=(nonce, min(10, ATTESTATION_TIMEOUT)))
            t.daemon = True
            t.start()
        except Exception:
            log.exception("Failed to start background attestation fetch for nonce %s", nonce)

        return jsonify({"status": "success",
                        "message": result["json"].get("choices", [{}])[0].get("message", {}),
                        "model": result.get("used_model", requested_model),
                        "nonce": result.get("nonce", ""),
                        "receipt_id": result.get("receipt_id", "")})

    except requests.exceptions.Timeout:
        return jsonify({"status": "error", "message": "Phala AI request timed out"}), 504
    except requests.exceptions.HTTPError as exc:
        if _is_upstream_verification_route_failure(exc):
            return jsonify({
                "status": "error",
                "message": "Selected model route is currently unavailable upstream. Try a different model or wait a moment.",
            }), 503
        return jsonify({"status": "error", "message": f"Phala AI returned {exc.response.status_code}: {exc.response.text}"}), 502
    except requests.exceptions.ConnectionError:
        return jsonify({"status": "error", "message": "Unable to connect to Phala AI"}), 503
    except Exception as exc:
        log.exception("Chat error")
        return jsonify({"status": "error", "message": str(exc)}), 500

@app.route("/attestation", methods=["GET"])
def attestation():
    err = require_api_key()
    if err:
        return err

    nonce = request.args.get("nonce")

    if not nonce:
        return jsonify({
            "status": "error",
            "message": "nonce is required"
        }), 400

    # If background fetch already populated the cache, return it immediately.
    if nonce in ATT_CACHE:
        return jsonify(ATT_CACHE[nonce])

    try:
        report = get_attestation(nonce)
        # Cache the fetched report for subsequent requests.
        ATT_CACHE[nonce] = report
        return jsonify(report)

    except requests.exceptions.Timeout:
        return jsonify({
            "status": "error",
            "message": "Phala attestation request timed out"
        }), 504

    except requests.exceptions.HTTPError as exc:
        body = exc.response.text if exc.response is not None else ""

        log.error(
            "Phala attestation failed: status=%s body=%s",
            exc.response.status_code if exc.response else "unknown",
            body,
        )

        return jsonify({
            "status": "error",
            "message": "Phala attestation request failed",
            "upstream_status": exc.response.status_code if exc.response else None,
            "upstream_response": body,
        }), 502

    except requests.exceptions.RequestException as exc:
        log.exception("Phala attestation request failed")
        return jsonify({
            "status": "error",
            "message": str(exc)
        }), 502

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5001, debug=False)