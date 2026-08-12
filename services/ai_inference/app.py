"""
AI Inference Service for TODO App CVM

Proxies requests to Phala Confidential AI and returns the model output plus
receipt metadata.
"""

import os
import logging
import json
import secrets
import requests
import time
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

PHALA_MODELS_URL = os.getenv(
    "PHALA_MODELS_URL", 
    "https://inference.phala.com/v1/models"
)

PHALA_ATTESTATION_URL = os.getenv(
    "PHALA_ATTESTATION_URL", "https://inference.phala.com/v1/aci/attestation"
)
PHALA_RECEIPTS_URL = os.getenv(
    "PHALA_RECEIPTS_URL", "https://inference.phala.com/v1/aci/receipts"
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

_CATALOG_CACHE = {"data": None, "ts": 0.0}
CATALOG_TTL = 300  # seconds

# Keep the default AI timeout shorter than the web-ui proxy timeout so
# callers (web UI) don't get an upstream 504 while the inference request
# is still in progress. These can be overridden via env vars in deploys.
AI_TIMEOUT    = int(os.getenv("AI_TIMEOUT", "90"))

SYSTEM_PROMPT = "You are a helpful task management assistant."

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

def _parse_phala_error(resp):
    """Extract error type/message per Phala's documented error shape."""
    try:
        payload = resp.json()
        err = payload.get("error", {}) if isinstance(payload, dict) else {}
        return err.get("type", ""), err.get("message", "") or resp.text[:200]
    except Exception:
        return "", resp.text[:200]


def _is_retryable(status_code, error_type):
    # Per docs: retry 429, 500, 502, 503. Never retry 400/401.
    if status_code in (429, 500, 502, 503):
        return True
    if error_type == "upstream_error":
        return True
    return False


def phala_request(messages, model, timeout, zdr=False):
    headers = {
        "Authorization": f"Bearer {PHALA_AI_API_KEY}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    payload = {"model": model, "messages": messages}
    if zdr:
        payload["provider"] = {"zdr": True}
    request_bytes = json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8")

    response = requests.post(PHALA_AI_URL, headers=headers, data=request_bytes, timeout=timeout)
    response.raise_for_status()
    receipt_id = response.headers.get("x-receipt-id", "").strip()
    return {"json": response.json(), "receipt_id": receipt_id}


def phala_request_with_fallback(messages, requested_model, zdr=False, has_image=False):
    model = requested_model or DEFAULT_MODEL
    deadline = time.monotonic() + AI_TIMEOUT
    primary_timeout = max(min(AI_TIMEOUT * 0.4, 25), 5)

    try:
        result = phala_request(messages, model, primary_timeout, zdr=zdr)
        result["used_model"] = model
        return result
    except (requests.exceptions.HTTPError, requests.exceptions.Timeout,
             requests.exceptions.ConnectionError) as exc:
        remaining = deadline - time.monotonic()
        status_code = None
        error_type = ""
        resp = getattr(exc, "response", None)
        if resp is not None:
            status_code = resp.status_code
            error_type, _ = _parse_phala_error(resp)

        is_transient = (
            isinstance(exc, (requests.exceptions.Timeout, requests.exceptions.ConnectionError))
            or _is_retryable(status_code, error_type)
            or (zdr and error_type == "not_found_error")
        )
        # Never fall back to a model that can't handle the image in this request.
        fallback_is_viable = (not has_image) or _model_supports_image(FALLBACK_MODEL)

        if model != FALLBACK_MODEL and is_transient and fallback_is_viable and remaining > 5:
            log.warning(
                "Primary model %s failed (%s, status=%s, type=%s); falling back to %s with %.1fs left",
                model, type(exc).__name__, status_code, error_type, FALLBACK_MODEL, remaining,
            )
            result = phala_request(messages, FALLBACK_MODEL, remaining, zdr=zdr)
            result["used_model"] = FALLBACK_MODEL
            result["fallback_from"] = model
            return result
        raise

def _trim_model(m):
    return {
        "id": m.get("id"),
        "name": m.get("name") or m.get("id"),
        "is_tee": bool(m.get("is_tee")),
        "input_modalities": m.get("input_modalities") or [],
        "context_length": m.get("context_length"),
    }


def _fetch_catalog(extra_params=None):
    resp = requests.get(
        PHALA_MODELS_URL,
        params=extra_params or {},
        headers={"Authorization": f"Bearer {PHALA_AI_API_KEY}"},
        timeout=15,
    )
    resp.raise_for_status()
    data = resp.json()
    return [_trim_model(m) for m in data.get("data", []) if isinstance(m, dict) and m.get("id")]


def _get_catalog_cached(force=False):
    now = time.monotonic()
    if not force and _CATALOG_CACHE["data"] is not None and (now - _CATALOG_CACHE["ts"]) < CATALOG_TTL:
        return _CATALOG_CACHE["data"]
    catalog = _fetch_catalog()
    _CATALOG_CACHE["data"] = catalog
    _CATALOG_CACHE["ts"] = now
    return catalog


def _model_supports_image(model_id):
    try:
        catalog = _get_catalog_cached()
    except Exception:
        return True  # fail open — let upstream validate if catalog is unreachable
    entry = next((m for m in catalog if m.get("id") == model_id), None)
    if entry is None:
        return True  # unknown model (not yet cached) — don't block, let upstream validate
    return "image" in (entry.get("input_modalities") or [])

def _model_supports_video(model_id):
    try:
        catalog = _get_catalog_cached()
    except Exception:
        return True  # fail open — let upstream validate if catalog is unreachable
    entry = next((m for m in catalog if m.get("id") == model_id), None)
    if entry is None:
        return True  # unknown model (not yet cached) — don't block, let upstream validate
    return "video" in (entry.get("input_modalities") or [])
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
    force = request.args.get("refresh", "").lower() == "true"
    try:
        catalog = _get_catalog_cached(force=force)
        return jsonify({"status": "success", "models": catalog, "default_model": DEFAULT_MODEL})
    except requests.exceptions.Timeout:
        return jsonify({"status": "error", "message": "Model catalog request timed out"}), 504
    except requests.exceptions.ConnectionError:
        return jsonify({"status": "error", "message": "Unable to reach model catalog service"}), 503
    except requests.exceptions.HTTPError as exc:
        status_code = exc.response.status_code if exc.response is not None else 502
        _, msg = _parse_phala_error(exc.response) if exc.response is not None else ("", "")
        return jsonify({"status": "error", "message": msg or f"Model catalog returned {status_code}"}), status_code
    except Exception:
        log.exception("Model catalog error")
        return jsonify({"status": "error", "message": "Internal error fetching model catalog"}), 500

@app.route("/models/vision", methods=["GET"])
def vision_models():
    err = require_api_key()
    if err:
        return err
    try:
        catalog = _get_catalog_cached()
        vision = [m for m in catalog if "image" in (m.get("input_modalities") or [])]
        return jsonify({"status": "success", "models": vision})
    except requests.exceptions.Timeout:
        return jsonify({"status": "error", "message": "Model catalog request timed out"}), 504
    except requests.exceptions.ConnectionError:
        return jsonify({"status": "error", "message": "Unable to reach model catalog service"}), 503
    except requests.exceptions.HTTPError as exc:
        status_code = exc.response.status_code if exc.response is not None else 502
        _, msg = _parse_phala_error(exc.response) if exc.response is not None else ("", "")
        return jsonify({"status": "error", "message": msg or f"Model catalog returned {status_code}"}), status_code
    except Exception:
        log.exception("Vision model list error")
        return jsonify({"status": "error", "message": "Internal error fetching vision model list"}), 500

@app.route("/models/zdr", methods=["GET"])
def zdr_models():
    err = require_api_key()
    if err:
        return err
    try:
        catalog = _fetch_catalog(extra_params={"zdr": "true"})
        return jsonify({"status": "success", "models": catalog})
    except requests.exceptions.Timeout:
        return jsonify({"status": "error", "message": "ZDR model list request timed out"}), 504
    except requests.exceptions.ConnectionError:
        return jsonify({"status": "error", "message": "Unable to reach model catalog service"}), 503
    except requests.exceptions.HTTPError as exc:
        status_code = exc.response.status_code if exc.response is not None else 502
        _, msg = _parse_phala_error(exc.response) if exc.response is not None else ("", "")
        return jsonify({"status": "error", "message": msg or f"ZDR model list returned {status_code}"}), status_code
    except Exception:
        log.exception("ZDR model list error")
        return jsonify({"status": "error", "message": "Internal error fetching ZDR model list"}), 500

@app.route("/inference", methods=["POST"])
def inference():
    err = require_api_key()
    if err:
        return err

    data = request.get_json(silent=True) or {}
    prompt = data.get("prompt", "").strip()
    image_url = (data.get("image_url") or "").strip()
    if not prompt and not image_url:
        return jsonify({"status": "error", "message": "prompt is required"}), 400

    requested_model = data.get("model") or DEFAULT_MODEL
    zdr = bool(data.get("zdr", False))
    system = data.get("system") or SYSTEM_PROMPT
    context_items = data.get("context", [])

    if image_url and not _model_supports_image(requested_model):
        try:
            vision_ids = [m["id"] for m in _get_catalog_cached() if "image" in (m.get("input_modalities") or [])]
        except Exception:
            vision_ids = []
        return jsonify({
            "status": "error",
            "message": (
                f"'{requested_model}' doesn't support image analysis. "
                f"Choose a vision-capable model: {', '.join(vision_ids) if vision_ids else 'none currently available'}."
            ),
        }), 400

    if context_items:
        context_text = "\n".join(str(item) for item in context_items)
        prompt = f"Context:\n{context_text}\n\nUser:\n{prompt}"

    if image_url:
        user_content = [
            {"type": "text", "text": prompt or "What is in this image?"},
            {"type": "image_url", "image_url": {"url": image_url}},
        ]
    else:
        user_content = prompt

    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": user_content},
    ]

    try:
        result = phala_request_with_fallback(messages, requested_model, zdr=zdr, has_image=bool(image_url))
        response_text = _extract_text_response(result.get("json", {}))
        if not response_text:
            return jsonify({
                "status": "error",
                "message": "Provider returned an unexpected response format",
                "receipt_id": result.get("receipt_id", ""),
            }), 502
        payload = {
            "status": "success",
            "response": response_text,
            "model": result.get("used_model", requested_model),
            "receipt_id": result.get("receipt_id", ""),
            "zdr": zdr,
        }
        if result.get("fallback_from"):
            payload["fallback_from"] = result["fallback_from"]
        return jsonify(payload)

    except requests.exceptions.Timeout:
        return jsonify({"status": "error", "message": "AI request timed out. Please try again."}), 504
    except requests.exceptions.ConnectionError:
        return jsonify({"status": "error", "message": "Unable to connect to Phala AI"}), 503
    except requests.exceptions.HTTPError as exc:
        status_code = exc.response.status_code if exc.response is not None else 502
        error_type, error_msg = (
            _parse_phala_error(exc.response) if exc.response is not None else ("", "")
        )

        if error_type == "authentication_error":
            return jsonify({"status": "error", "message": "AI service authentication failed. Check API key configuration."}), 401
        if error_type == "model_not_found":
            return jsonify({"status": "error", "message": f"Model '{requested_model}' is not available. Try a different model."}), 400
        if error_type == "invalid_request_error" and image_url:
            return jsonify({
                "status": "error",
                "message": f"'{requested_model}' rejected the image input: {error_msg}",
            }), 400
        if error_type == "not_found_error" or status_code == 404:
            return jsonify({
                "status": "error",
                "message": "No zero-data-retention route is available for this model. Pick a different ZDR model.",
            }), 404
        if status_code == 429:
            retry_after = exc.response.headers.get("Retry-After", "") if exc.response is not None else ""
            msg = "Rate limit reached. Please wait a moment before trying again."
            if retry_after:
                msg = f"Rate limit reached. Please wait about {retry_after}s before trying again."
            return jsonify({"status": "error", "message": msg}), 429
        if error_type == "upstream_error" or status_code in (500, 502, 503):
            return jsonify({
                "status": "error",
                "message": "The AI model is temporarily unavailable upstream. Try a different model or wait a moment.",
            }), 503
        return jsonify({"status": "error", "message": error_msg or f"AI service returned {status_code}"}), status_code
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
    err = require_api_key()
    if err:
        return err
    nonce = secrets.token_hex(32)
    try:
        resp = requests.get(
            PHALA_ATTESTATION_URL,
            params={"nonce": nonce},
            headers={"Authorization": f"Bearer {PHALA_AI_API_KEY}"},
            timeout=10,
        )
        if not resp.ok:
            log.warning("Attestation upstream %s: %s", resp.status_code, resp.text[:500])
            try:
                upstream_msg = resp.json().get("error", {}).get("message") or resp.json().get("message")
            except Exception:
                upstream_msg = resp.text[:200]
            return jsonify({
                "status": "error",
                "message": f"Attestation service returned {resp.status_code}: {upstream_msg}",
            }), resp.status_code
        data = resp.json()
        att = data.get("attestation", {}) or {}
        return jsonify({
            "status": "success",
            "nonce": nonce,
            "api_version": data.get("api_version"),
            "workload_id": data.get("workload_id"),
            "workload_keyset_digest": data.get("workload_keyset_digest"),
            "tee_type": att.get("tee_type"),
            "stale_after": (att.get("freshness") or {}).get("stale_after"),
            "source_provenance": att.get("source_provenance"),
        })
    except requests.exceptions.Timeout:
        return jsonify({"status": "error", "message": "Attestation request timed out"}), 504
    except requests.exceptions.ConnectionError:
        return jsonify({"status": "error", "message": "Unable to reach attestation service"}), 503
    except Exception:
        log.exception("Attestation error")
        return jsonify({"status": "error", "message": "Internal error fetching attestation"}), 500


@app.route("/receipts/<receipt_id>", methods=["GET"])
def get_receipt(receipt_id):
    err = require_api_key()
    if err:
        return err
    try:
        resp = requests.get(
            f"{PHALA_RECEIPTS_URL}/{receipt_id}",
            headers={"Authorization": f"Bearer {PHALA_AI_API_KEY}"},
            timeout=10,
        )
        if not resp.ok:
            log.warning("Receipt upstream %s: %s", resp.status_code, resp.text[:500])
            try:
                upstream_msg = resp.json().get("error", {}).get("message") or resp.json().get("message")
            except Exception:
                upstream_msg = resp.text[:200]
            return jsonify({
                "status": "error",
                "message": f"Receipt service returned {resp.status_code}: {upstream_msg}",
            }), resp.status_code
        data = resp.json()
        upstream = next(
            (e for e in data.get("event_log", []) if e.get("type") == "upstream.verified"),
            {},
        )
        return jsonify({
            "status": "success",
            "receipt_id": data.get("receipt_id", receipt_id),
            "workload_id": data.get("workload_id"),
            "workload_keyset_digest": data.get("workload_keyset_digest"),
            "verified": upstream.get("result") == "verified",
            "required": upstream.get("required"),
            "provider": upstream.get("provider"),
            "model_id": upstream.get("model_id"),
            "session_id": upstream.get("session_id"),
        })
    except requests.exceptions.Timeout:
        return jsonify({"status": "error", "message": "Receipt request timed out"}), 504
    except requests.exceptions.ConnectionError:
        return jsonify({"status": "error", "message": "Unable to reach receipt service"}), 503
    except Exception:
        log.exception("Receipt fetch error")
        return jsonify({"status": "error", "message": "Internal error fetching receipt"}), 500

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5001, debug=False)