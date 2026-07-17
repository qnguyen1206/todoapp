"""
AI Inference Service for TODO App CVM
Proxies requests to Ollama running inside the same TEE.
All prompts stay inside the enclave — never exposed externally.
"""

import os
import logging
from datetime import datetime, timezone

import requests
from flask import Flask, request, jsonify, Response, stream_with_context
from flask_cors import CORS

logging.basicConfig(level=os.getenv("LOG_LEVEL", "info").upper())
log = logging.getLogger(__name__)

app = Flask(__name__)
CORS(app)

OLLAMA_ENDPOINT = os.getenv("OLLAMA_ENDPOINT", "http://ollama:11434")
DEFAULT_MODEL = os.getenv("DEFAULT_MODEL", "deepseek-r1:14b")
API_KEY = os.environ.get("API_KEY", "")

OLLAMA_TIMEOUT = int(os.getenv("OLLAMA_TIMEOUT", "120"))


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


def ollama_available():
    try:
        r = requests.get(f"{OLLAMA_ENDPOINT}/api/tags", timeout=3)
        return r.status_code == 200
    except Exception:
        return False


def list_ollama_models():
    try:
        r = requests.get(f"{OLLAMA_ENDPOINT}/api/tags", timeout=5)
        if r.status_code == 200:
            return [m["name"] for m in r.json().get("models", [])]
    except Exception:
        pass
    return []


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.route("/health", methods=["GET"])
def health():
    available = ollama_available()
    models = list_ollama_models() if available else []
    return jsonify({
        "status": "ok",
        "service": "ai_inference",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "ollama": {
            "available": available,
            "endpoint": OLLAMA_ENDPOINT,
            "models": models,
            "default_model": DEFAULT_MODEL,
        }
    })


@app.route("/models", methods=["GET"])
def models():
    err = require_api_key()
    if err:
        return err
    return jsonify({"status": "success", "models": list_ollama_models()})


@app.route("/inference", methods=["POST"])
def inference():
    """
    Send a prompt to Ollama and return the response.
    Supports optional streaming via ?stream=true.

    Request body:
        {
            "prompt": "string",
            "model":  "optional-model-name",
            "system": "optional system prompt",
            "context": []   # optional list of context strings
        }
    """
    err = require_api_key()
    if err:
        return err

    data = request.get_json(silent=True) or {}
    prompt = data.get("prompt", "").strip()
    model = data.get("model") or DEFAULT_MODEL
    system = data.get("system", "You are a helpful task management assistant.")
    context_items = data.get("context", [])
    do_stream = str(request.args.get("stream", "false")).lower() == "true"

    if not prompt:
        return jsonify({"status": "error", "message": "prompt is required"}), 400

    # Build full prompt with optional context
    full_prompt = prompt
    if context_items:
        ctx = "\n".join(str(c) for c in context_items)
        full_prompt = f"Context:\n{ctx}\n\nUser: {prompt}"

    payload = {
        "model": model,
        "prompt": full_prompt,
        "system": system,
        "stream": do_stream,
    }

    try:
        if do_stream:
            # Stream tokens back to the client
            def generate():
                with requests.post(
                    f"{OLLAMA_ENDPOINT}/api/generate",
                    json=payload,
                    stream=True,
                    timeout=OLLAMA_TIMEOUT,
                ) as r:
                    for chunk in r.iter_lines():
                        if chunk:
                            yield chunk + b"\n"

            return Response(
                stream_with_context(generate()),
                content_type="application/x-ndjson",
            )
        else:
            r = requests.post(
                f"{OLLAMA_ENDPOINT}/api/generate",
                json=payload,
                timeout=OLLAMA_TIMEOUT,
            )
            if r.status_code == 200:
                result = r.json()
                return jsonify({
                    "status": "success",
                    "response": result.get("response", ""),
                    "model": model,
                    "done": result.get("done", True),
                })
            else:
                return jsonify({
                    "status": "error",
                    "message": f"Ollama returned {r.status_code}: {r.text}",
                }), 502

    except requests.exceptions.Timeout:
        return jsonify({"status": "error", "message": "Ollama inference timed out"}), 504
    except requests.exceptions.ConnectionError:
        return jsonify({
            "status": "error",
            "message": f"Cannot connect to Ollama at {OLLAMA_ENDPOINT}. Is it running?",
        }), 503
    except Exception as exc:
        log.error("inference error: %s", exc)
        return jsonify({"status": "error", "message": str(exc)}), 500


@app.route("/chat", methods=["POST"])
def chat():
    """
    Chat-style endpoint using Ollama's /api/chat format.

    Request body:
        {
            "messages": [{"role": "user", "content": "..."}, ...],
            "model": "optional-model-name"
        }
    """
    err = require_api_key()
    if err:
        return err

    data = request.get_json(silent=True) or {}
    messages = data.get("messages", [])
    model = data.get("model") or DEFAULT_MODEL

    if not messages:
        return jsonify({"status": "error", "message": "messages list is required"}), 400

    try:
        r = requests.post(
            f"{OLLAMA_ENDPOINT}/api/chat",
            json={"model": model, "messages": messages, "stream": False},
            timeout=OLLAMA_TIMEOUT,
        )
        if r.status_code == 200:
            result = r.json()
            return jsonify({
                "status": "success",
                "message": result.get("message", {}),
                "model": model,
            })
        else:
            return jsonify({"status": "error", "message": r.text}), 502
    except requests.exceptions.ConnectionError:
        return jsonify({"status": "error", "message": "Ollama not available"}), 503
    except Exception as exc:
        log.error("chat error: %s", exc)
        return jsonify({"status": "error", "message": str(exc)}), 500


# ---------------------------------------------------------------------------
# Startup
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5001, debug=False)
