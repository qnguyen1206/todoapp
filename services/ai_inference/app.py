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

AI_TIMEOUT    = int(os.getenv("AI_TIMEOUT", "45"))

SYSTEM_PROMPT = "You are a helpful task management assistant."

ATTESTATION_BASE = "https://inference.phala.com"

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


def phala_request(messages, model):
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
        "attestation" : None,
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


def phala_request_with_fallback(messages, requested_model):
    """Try requested model first; retry once on route verification failure."""
    model = requested_model or DEFAULT_MODEL
    try:
        result = phala_request(messages, model)
        result["used_model"] = model
        return result
    except requests.exceptions.HTTPError as exc:
        # Retry only when the selected route is unavailable and fallback is different.
        if model != FALLBACK_MODEL and _is_upstream_verification_route_failure(exc):
            log.warning("Primary model route unavailable, retrying fallback model: %s", FALLBACK_MODEL)
            result = phala_request(messages, FALLBACK_MODEL)
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
            "Authorization": f"Bearer {PHALA_AI_API_KEY}"
        },
        timeout=30
    )

    r.raise_for_status()
    return r.json()

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
        result = phala_request_with_fallback(messages, requested_model)
        response_text = _extract_text_response(result.get("json", {}))
        if not response_text:
            return jsonify({"status": "error",
                            "message": "Provider returned an unexpected response format",
                            "receipt_id": result.get("receipt_id", "")}), 502

        return jsonify({"status": "success", "response": response_text,
                        "model": result.get("used_model", requested_model),
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
        result = phala_request_with_fallback(messages, requested_model)
        return jsonify({"status": "success",
                        "message": result["json"].get("choices", [{}])[0].get("message", {}),
                        "model": result.get("used_model", requested_model),
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

    nonce = request.args.get("nonce")

    report = get_attestation(nonce)

    return jsonify(report)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5001, debug=False)