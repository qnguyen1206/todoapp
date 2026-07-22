"""Client-side cryptography for encrypted TODO App CVM task storage.

Private keys and workspace keys deliberately stay on the device.  The server
only stores public keys and an encrypted copy of the workspace key for each
approved device.
"""

import base64
import json
import os

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF


TASK_ENCRYPTION_PREFIX = "ENC2:"
KEY_WRAP_INFO = b"todoapp-keywrap-v1"
TASK_INFO_PREFIX = "todoapp-task-v2"


def b64url_encode(value: bytes) -> str:
    """Encode bytes without padding so values are safe to embed in JSON."""
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def b64url_decode(value: str) -> bytes:
    """Decode a URL-safe Base64 value and reject non-string inputs."""
    if not isinstance(value, str):
        raise ValueError("Expected a Base64 string")
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def canonical_json(value) -> str:
    """Produce the stable JSON representation used by device approvals."""
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def generate_private_key():
    return ec.generate_private_key(ec.SECP256R1())


def private_key_to_b64(private_key) -> str:
    data = private_key.private_bytes(
        serialization.Encoding.DER,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )
    return b64url_encode(data)


def private_key_from_b64(value: str):
    private_key = serialization.load_der_private_key(b64url_decode(value), password=None)
    if not isinstance(private_key, ec.EllipticCurvePrivateKey) or not isinstance(
        private_key.curve, ec.SECP256R1
    ):
        raise ValueError("Expected a P-256 private key")
    return private_key


def public_key_to_b64(public_key) -> str:
    data = public_key.public_bytes(
        serialization.Encoding.X962,
        serialization.PublicFormat.UncompressedPoint,
    )
    return b64url_encode(data)


def public_key_from_b64(value: str):
    try:
        return ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), b64url_decode(value))
    except (TypeError, ValueError) as exc:
        raise ValueError("Invalid P-256 public key") from exc


def _key_wrap_context(user_id: str, device_id: str) -> bytes:
    return f"{KEY_WRAP_INFO.decode()}|{user_id}|{device_id}".encode("utf-8")


def _task_context(user_id: str, task_id: str) -> bytes:
    return f"{TASK_INFO_PREFIX}|{user_id}|{task_id}".encode("utf-8")


def _derive_wrapping_key(private_key, peer_public_key, salt: bytes) -> bytes:
    shared_secret = private_key.exchange(ec.ECDH(), peer_public_key)
    return HKDF(
        algorithm=hashes.SHA256(),
        length=32,
        salt=salt,
        info=KEY_WRAP_INFO,
    ).derive(shared_secret)


def wrap_workspace_key(workspace_key: bytes, recipient_public_key: str, user_id: str, device_id: str) -> dict:
    """Encrypt a workspace key to one device's ECDH public key."""
    if len(workspace_key) != 32:
        raise ValueError("Workspace keys must be 32 bytes")

    recipient = public_key_from_b64(recipient_public_key)
    ephemeral_private = generate_private_key()
    salt = os.urandom(16)
    nonce = os.urandom(12)
    wrapping_key = _derive_wrapping_key(ephemeral_private, recipient, salt)
    ciphertext = AESGCM(wrapping_key).encrypt(
        nonce,
        workspace_key,
        _key_wrap_context(user_id, device_id),
    )
    return {
        "v": 1,
        "ephemeral_public_key": public_key_to_b64(ephemeral_private.public_key()),
        "salt": b64url_encode(salt),
        "nonce": b64url_encode(nonce),
        "ciphertext": b64url_encode(ciphertext),
    }


def unwrap_workspace_key(envelope: dict, recipient_private_key, user_id: str, device_id: str) -> bytes:
    """Decrypt a workspace key that was wrapped for this device."""
    if not isinstance(envelope, dict) or envelope.get("v") != 1:
        raise ValueError("Unsupported workspace-key envelope")
    try:
        ephemeral_public = public_key_from_b64(envelope["ephemeral_public_key"])
        salt = b64url_decode(envelope["salt"])
        nonce = b64url_decode(envelope["nonce"])
        ciphertext = b64url_decode(envelope["ciphertext"])
    except (KeyError, ValueError) as exc:
        raise ValueError("Malformed workspace-key envelope") from exc

    if len(salt) != 16 or len(nonce) != 12:
        raise ValueError("Malformed workspace-key envelope")
    workspace_key = AESGCM(_derive_wrapping_key(recipient_private_key, ephemeral_public, salt)).decrypt(
        nonce,
        ciphertext,
        _key_wrap_context(user_id, device_id),
    )
    if len(workspace_key) != 32:
        raise ValueError("Malformed workspace key")
    return workspace_key


def encrypt_task(task: dict, workspace_key: bytes, user_id: str) -> dict:
    """Encrypt a task title and notes while retaining scheduling metadata."""
    task_id = str(task.get("id") or task.get("task_id") or "")
    if not task_id:
        raise ValueError("Task ID is required for encryption")
    if len(workspace_key) != 32:
        raise ValueError("Workspace keys must be 32 bytes")

    sensitive = json.dumps(
        {"title": task.get("title", ""), "notes": task.get("notes", "")},
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    nonce = os.urandom(12)
    ciphertext = AESGCM(workspace_key).encrypt(nonce, sensitive, _task_context(user_id, task_id))
    payload = b64url_encode(
        json.dumps(
            {"v": 2, "nonce": b64url_encode(nonce), "ciphertext": b64url_encode(ciphertext)},
            separators=(",", ":"),
        ).encode("utf-8")
    )
    encrypted = dict(task)
    encrypted["title"] = "[Encrypted]"
    encrypted["notes"] = TASK_ENCRYPTION_PREFIX + payload
    return encrypted


def decrypt_task(task: dict, workspace_key: bytes, user_id: str) -> dict:
    """Decrypt a version-2 task payload, leaving unrelated fields intact."""
    notes = task.get("notes", "")
    if not isinstance(notes, str) or not notes.startswith(TASK_ENCRYPTION_PREFIX):
        return dict(task)

    task_id = str(task.get("id") or task.get("task_id") or "")
    if not task_id:
        raise ValueError("Task ID is required for decryption")
    try:
        payload = json.loads(b64url_decode(notes[len(TASK_ENCRYPTION_PREFIX):]).decode("utf-8"))
        if payload.get("v") != 2:
            raise ValueError("Unsupported task encryption version")
        nonce = b64url_decode(payload["nonce"])
        ciphertext = b64url_decode(payload["ciphertext"])
        sensitive = json.loads(
            AESGCM(workspace_key).decrypt(
                nonce,
                ciphertext,
                _task_context(user_id, task_id),
            ).decode("utf-8")
        )
    except (KeyError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise ValueError("Could not decrypt task") from exc

    decrypted = dict(task)
    decrypted["title"] = sensitive.get("title", "")
    decrypted["notes"] = sensitive.get("notes", "")
    return decrypted


def approval_payload(
    user_id: str,
    device_id: str,
    encryption_public_key: str,
    signing_public_key: str,
    wrapped_workspace_key: dict,
) -> bytes:
    """Return the exact data an existing device signs to approve another."""
    return canonical_json(
        {
            "device_id": device_id,
            "encryption_public_key": encryption_public_key,
            "signing_public_key": signing_public_key,
            "user_id": user_id,
            "wrapped_workspace_key": wrapped_workspace_key,
        }
    ).encode("utf-8")


def sign_approval(private_key, payload: bytes) -> str:
    return b64url_encode(private_key.sign(payload, ec.ECDSA(hashes.SHA256())))


def verify_approval(public_key, payload: bytes, signature: str) -> bool:
    try:
        public_key.verify(b64url_decode(signature), payload, ec.ECDSA(hashes.SHA256()))
        return True
    except (InvalidSignature, ValueError):
        return False
