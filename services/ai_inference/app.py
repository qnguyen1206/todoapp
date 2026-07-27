"""
AI Inference Service for TODO App CVM

Proxies requests to Phala Confidential AI using HTTP requests.
The service keeps the same REST API so the frontend does not need to change.
"""

import os
import logging
from datetime import datetime, timezone

import requests
from flask import Flask, request, jsonify
from flask_cors import CORS

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

AI_TIMEOUT = int(os.getenv("AI_TIMEOUT", "120"))

SYSTEM_PROMPT = "You are a helpful task management assistant."


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def require_api_key():
    """Require the application's API key (not the Phala AI key)."""
    if not API_KEY:
        return None

    key = request.headers.get("X-API-Key") or request.args.get("api_key")

    if key != API_KEY:
        return jsonify({
            "status": "error",
            "message": "Unauthorized"
        }), 401

    return None


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

    response = requests.post(
        PHALA_AI_URL,
        headers=headers,
        json=payload,
        timeout=AI_TIMEOUT,
    )

    response.raise_for_status()

    return response.json()


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
        "models": [
            DEFAULT_MODEL
        ]
    })


@app.route("/inference", methods=["POST"])
def inference():
    """
    Request body:

    {
        "prompt": "...",
        "model": "optional",
        "system": "optional",
        "context": [...]
    }
    """

    err = require_api_key()
    if err:
        return err

    data = request.get_json(silent=True) or {}

    prompt = data.get("prompt", "").strip()

    if not prompt:
        return jsonify({
            "status": "error",
            "message": "prompt is required"
        }), 400

    model = data.get("model") or DEFAULT_MODEL
    system = data.get("system") or SYSTEM_PROMPT
    context_items = data.get("context", [])

    if context_items:
        context_text = "\n".join(str(item) for item in context_items)
        prompt = f"Context:\n{context_text}\n\nUser:\n{prompt}"

    messages = [
        {
            "role": "system",
            "content": system,
        },
        {
            "role": "user",
            "content": prompt,
        },
    ]

    try:
        result = phala_request(messages, model)

        return jsonify({
            "status": "success",
            "response": result["choices"][0]["message"]["content"],
            "model": model,
        })

    except requests.exceptions.Timeout:
        return jsonify({
            "status": "error",
            "message": "Phala AI request timed out"
        }), 504

    except requests.exceptions.HTTPError as e:
        return jsonify({
            "status": "error",
            "message": f"Phala AI returned {e.response.status_code}: {e.response.text}"
        }), 502

    except requests.exceptions.ConnectionError:
        return jsonify({
            "status": "error",
            "message": "Unable to connect to Phala AI"
        }), 503

    except Exception as exc:
        log.exception("Inference error")

        return jsonify({
            "status": "error",
            "message": str(exc)
        }), 500


@app.route("/chat", methods=["POST"])
def chat():
    """
    Request body:

    {
        "messages": [
            {
                "role": "user",
                "content": "..."
            }
        ],
        "model": "optional"
    }
    """

    err = require_api_key()
    if err:
        return err

    data = request.get_json(silent=True) or {}

    messages = data.get("messages")

    if not messages:
        return jsonify({
            "status": "error",
            "message": "messages list is required"
        }), 400

    model = data.get("model") or DEFAULT_MODEL

    try:
        result = phala_request(messages, model)

        return jsonify({
            "status": "success",
            "message": result["choices"][0]["message"],
            "model": model,
        })

    except requests.exceptions.Timeout:
        return jsonify({
            "status": "error",
            "message": "Phala AI request timed out"
        }), 504

    except requests.exceptions.HTTPError as e:
        return jsonify({
            "status": "error",
            "message": f"Phala AI returned {e.response.status_code}: {e.response.text}"
        }), 502

    except requests.exceptions.ConnectionError:
        return jsonify({
            "status": "error",
            "message": "Unable to connect to Phala AI"
        }), 503

    except Exception as exc:
        log.exception("Chat error")

        return jsonify({
            "status": "error",
            "message": str(exc)
        }), 500


# ---------------------------------------------------------------------------
# Startup
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5001, debug=False)