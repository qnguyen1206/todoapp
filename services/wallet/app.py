"""Controlled testnet EVM wallet backed by deterministic dstack TEE keys.

Only narrowly validated Base Sepolia native-ETH transfers and task-escrow calls
may be signed. There is no arbitrary message, calldata, private-key, seed, or
mnemonic endpoint.
"""

import hashlib
import logging
import os
import re
import secrets
import time
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation

import requests
from flask import Flask, jsonify, request

try:
    from dstack_sdk import DstackClient
    from dstack_sdk.ethereum import to_account_secure
    from eth_utils import is_address, keccak, to_checksum_address
except ImportError:  # Keeps diagnostics useful in non-CVM development.
    DstackClient = None
    to_account_secure = None
    is_address = None
    keccak = None
    to_checksum_address = None


logging.basicConfig(level=os.getenv("LOG_LEVEL", "info").upper())
log = logging.getLogger(__name__)

app = Flask(__name__)

API_KEY = os.getenv("API_KEY", "")
ENVIRONMENT = os.getenv("ENVIRONMENT", "production").strip().lower()
WALLET_NAMESPACE = os.getenv("WALLET_NAMESPACE", "todoapp-wallet").strip()
WALLET_DERIVATION_VERSION = os.getenv("WALLET_DERIVATION_VERSION", "v1").strip()
WALLET_CHAIN_ID = int(os.getenv("WALLET_CHAIN_ID", "84532"))
WALLET_CHAIN_NAME = os.getenv("WALLET_CHAIN_NAME", "Base Sepolia").strip()
WALLET_NATIVE_SYMBOL = os.getenv("WALLET_NATIVE_SYMBOL", "ETH").strip()
WALLET_RPC_URL = os.getenv("WALLET_RPC_URL", "https://sepolia.base.org").strip()
WALLET_EXPLORER_API_URL = os.getenv(
    "WALLET_EXPLORER_API_URL", "https://base-sepolia.blockscout.com/api/v2"
).rstrip("/")
WALLET_EXPLORER_URL = os.getenv(
    "WALLET_EXPLORER_URL", "https://base-sepolia.blockscout.com"
).rstrip("/")
WALLET_SEND_ENABLED = os.getenv("WALLET_SEND_ENABLED", "false").lower() in ("1", "true", "yes", "on")
WALLET_MAX_TRANSFER_ETH = Decimal(os.getenv("WALLET_MAX_TRANSFER_ETH", "0.1"))
WALLET_MAX_TRANSFER_WEI = int(WALLET_MAX_TRANSFER_ETH * Decimal(10**18))
WALLET_MAX_FEE_GWEI = Decimal(os.getenv("WALLET_MAX_FEE_GWEI", "5"))
WALLET_MAX_FEE_WEI = int(WALLET_MAX_FEE_GWEI * Decimal(10**9))
WALLET_QUOTE_TTL_SECONDS = min(900, max(60, int(os.getenv("WALLET_QUOTE_TTL_SECONDS", "600"))))
SEND_ENABLED_CHAIN_IDS = {84532}  # Base Sepolia only for wallet v3.
REWARD_BADGES_ENABLED = os.getenv("REWARD_BADGES_ENABLED", "false").lower() in ("1", "true", "yes", "on")
REWARD_BADGE_CONTRACT_ADDRESS = os.getenv("REWARD_BADGE_CONTRACT_ADDRESS", "").strip()
REWARD_ALLOWED_ACHIEVEMENT_IDS = {1, 10, 50, 100}
REWARD_MAX_GAS = min(300_000, max(80_000, int(os.getenv("REWARD_MAX_GAS", "200000"))))
TASK_ESCROW_ENABLED = os.getenv("TASK_ESCROW_ENABLED", "false").lower() in ("1", "true", "yes", "on")
TASK_ESCROW_CONTRACT_ADDRESS = os.getenv("TASK_ESCROW_CONTRACT_ADDRESS", "").strip()
TASK_ESCROW_MAX_ETH = Decimal(os.getenv("TASK_ESCROW_MAX_ETH", "0.05"))
TASK_ESCROW_MAX_WEI = int(TASK_ESCROW_MAX_ETH * Decimal(10**18))
TASK_ESCROW_MAX_GAS = min(350_000, max(100_000, int(os.getenv("TASK_ESCROW_MAX_GAS", "250000"))))

USER_ID_RE = re.compile(r"^[A-Za-z0-9_-]{8,128}$")
ADDRESS_RE = re.compile(r"^0x[a-fA-F0-9]{40}$")


def _authorized():
    if not API_KEY:
        return ENVIRONMENT != "production"
    supplied = request.headers.get("X-API-Key", "")
    return secrets.compare_digest(supplied, API_KEY)


@app.before_request
def require_internal_api_key():
    if request.path == "/health":
        return None
    if not _authorized():
        return jsonify({"status": "error", "message": "Unauthorized"}), 401
    return None


def _derivation_path(user_id):
    # Hash the application user ID so it never appears in dstack diagnostics.
    subject = hashlib.sha256(user_id.encode("utf-8")).hexdigest()
    return (
        f"{WALLET_NAMESPACE}/{WALLET_DERIVATION_VERSION}/{ENVIRONMENT}/"
        f"eip155/{WALLET_CHAIN_ID}/{subject}"
    )


def _derive_account(user_id):
    if DstackClient is None or to_account_secure is None:
        raise RuntimeError("dstack Ethereum SDK is not installed")
    client = DstackClient()
    key = client.get_key(_derivation_path(user_id))
    return to_account_secure(key)


def _derive_address(user_id):
    account = _derive_account(user_id)
    return account.address


def _derive_reward_issuer_account():
    if DstackClient is None or to_account_secure is None:
        raise RuntimeError("dstack Ethereum SDK is not installed")
    path = (
        f"{WALLET_NAMESPACE}/reward-issuer/v1/{ENVIRONMENT}/"
        f"eip155/{WALLET_CHAIN_ID}"
    )
    return to_account_secure(DstackClient().get_key(path))


def _reward_contract():
    if not REWARD_BADGES_ENABLED:
        raise ValueError("On-chain achievement badges are disabled")
    if WALLET_CHAIN_ID not in SEND_ENABLED_CHAIN_IDS:
        raise ValueError("Achievement badges are restricted to Base Sepolia")
    if is_address is None or not is_address(REWARD_BADGE_CONTRACT_ADDRESS):
        raise ValueError("REWARD_BADGE_CONTRACT_ADDRESS is not configured")
    contract = to_checksum_address(REWARD_BADGE_CONTRACT_ADDRESS)
    code = _rpc("eth_getCode", [contract, "latest"])
    if code in (None, "0x", "0x0", "0x00"):
        raise ValueError("Achievement contract is not deployed on the configured chain")
    return contract


def _achievement_calldata(recipient, achievement_id, claim_id):
    if keccak is None:
        raise RuntimeError("Ethereum utilities are not installed")
    selector = keccak(text="mintAchievement(address,uint256,bytes32)")[:4]
    recipient_word = bytes.fromhex(recipient[2:]).rjust(32, b"\x00")
    achievement_word = int(achievement_id).to_bytes(32, "big")
    claim_word = bytes.fromhex(claim_id[2:])
    return "0x" + (selector + recipient_word + achievement_word + claim_word).hex()


def _escrow_contract():
    if not TASK_ESCROW_ENABLED:
        raise ValueError("Task escrow is disabled by the operator")
    if WALLET_CHAIN_ID not in SEND_ENABLED_CHAIN_IDS:
        raise ValueError("Task escrow is restricted to Base Sepolia")
    if is_address is None or not is_address(TASK_ESCROW_CONTRACT_ADDRESS):
        raise ValueError("TASK_ESCROW_CONTRACT_ADDRESS is not configured")
    contract = to_checksum_address(TASK_ESCROW_CONTRACT_ADDRESS)
    if _rpc("eth_getCode", [contract, "latest"]) in (None, "0x", "0x0", "0x00"):
        raise ValueError("Task escrow contract is not deployed on the configured chain")
    return contract


def _escrow_calldata(action, escrow_key, recipient="", deadline=0):
    if keccak is None or not re.fullmatch(r"0x[a-f0-9]{64}", escrow_key):
        raise ValueError("Invalid escrow key")
    key_word = bytes.fromhex(escrow_key[2:])
    if action == "create":
        if is_address is None or not is_address(recipient):
            raise ValueError("Invalid escrow recipient")
        selector = keccak(text="createEscrow(bytes32,address,uint64)")[:4]
        recipient_word = bytes.fromhex(to_checksum_address(recipient)[2:]).rjust(32, b"\x00")
        deadline_word = int(deadline).to_bytes(32, "big")
        return "0x" + (selector + key_word + recipient_word + deadline_word).hex()
    signature = {"release": "release(bytes32)", "refund": "refund(bytes32)"}.get(action)
    if not signature:
        raise ValueError("Unsupported escrow action")
    return "0x" + (keccak(text=signature)[:4] + key_word).hex()


def _validated_escrow_fields(data):
    _assert_send_available()
    contract = _escrow_contract()
    user_id = str(data.get("user_id", "")).strip()
    expected_address = str(data.get("address", "")).strip()
    action = str(data.get("action", "")).strip().lower()
    escrow_key = str(data.get("escrow_key", "")).strip().lower()
    if not USER_ID_RE.fullmatch(user_id) or is_address is None or not is_address(expected_address):
        raise ValueError("Invalid wallet identity")
    account = _derive_account(user_id)
    expected_address = to_checksum_address(expected_address)
    if account.address.lower() != expected_address.lower():
        raise ValueError("Wallet derivation continuity check failed")
    try:
        value_wei = int(str(data.get("value_wei", "0")))
        deadline = int(data.get("deadline", 0))
    except (TypeError, ValueError):
        raise ValueError("Invalid escrow value or deadline")
    if action == "create":
        if value_wei <= 0 or value_wei > TASK_ESCROW_MAX_WEI:
            raise ValueError(f"Escrow must be between 0 and {TASK_ESCROW_MAX_ETH} ETH")
        if deadline <= int(time.time()) + 300 or deadline > int(time.time()) + 366 * 86400:
            raise ValueError("Escrow deadline must be between 5 minutes and 366 days away")
    elif action in ("release", "refund"):
        value_wei = 0
    else:
        raise ValueError("Unsupported escrow action")
    calldata = _escrow_calldata(action, escrow_key, str(data.get("recipient", "")), deadline)
    return account, expected_address, contract, action, escrow_key, value_wei, deadline, calldata


def _quote_escrow(data):
    account, sender, contract, action, escrow_key, value_wei, deadline, calldata = _validated_escrow_fields(data)
    max_fee, priority_fee = _fee_quote()
    estimate = int(_rpc("eth_estimateGas", [{
        "from": sender, "to": contract, "value": hex(value_wei), "data": calldata,
    }]), 16)
    if estimate > TASK_ESCROW_MAX_GAS:
        raise ValueError("Escrow action exceeds the configured gas policy")
    gas_limit = min(TASK_ESCROW_MAX_GAS, max(100_000, (estimate * 120 + 99) // 100))
    nonce = int(_rpc("eth_getTransactionCount", [sender, "pending"]), 16)
    balance = int(_rpc("eth_getBalance", [sender, "pending"]), 16)
    if balance < value_wei + gas_limit * max_fee:
        raise ValueError("Insufficient balance for escrow value and maximum network fee")
    now = int(time.time())
    return {
        "from": sender, "to": contract, "value_wei": str(value_wei), "data": calldata,
        "action": action, "escrow_key": escrow_key, "deadline": deadline,
        "nonce": nonce, "gas_limit": gas_limit, "max_fee_per_gas": str(max_fee),
        "max_priority_fee_per_gas": str(priority_fee), "chain_id": WALLET_CHAIN_ID,
        "quoted_at": now, "expires_at": now + WALLET_QUOTE_TTL_SECONDS,
    }


def _authorize_escrow(data):
    account, sender, contract, action, escrow_key, value_wei, deadline, calldata = _validated_escrow_fields(data)
    try:
        nonce = int(data["nonce"]); gas_limit = int(data["gas_limit"])
        max_fee = int(str(data["max_fee_per_gas"])); priority_fee = int(str(data["max_priority_fee_per_gas"]))
        expires_at = int(data["expires_at"]); chain_id = int(data["chain_id"])
    except (KeyError, TypeError, ValueError):
        raise ValueError("Malformed prepared escrow action")
    if chain_id != WALLET_CHAIN_ID or int(time.time()) > expires_at:
        raise ValueError("Escrow quote expired or has the wrong chain")
    if str(data.get("data", "")).lower() != calldata.lower():
        raise ValueError("Escrow calldata does not match the approved action")
    if not 100_000 <= gas_limit <= TASK_ESCROW_MAX_GAS:
        raise ValueError("Invalid escrow gas limit")
    if priority_fee <= 0 or max_fee < priority_fee or max_fee > WALLET_MAX_FEE_WEI:
        raise ValueError("Prepared network fee is outside the safety policy")
    if int(_rpc("eth_getTransactionCount", [sender, "pending"]), 16) != nonce:
        raise ValueError("Wallet nonce changed; prepare the escrow action again")
    estimate = int(_rpc("eth_estimateGas", [{
        "from": sender, "to": contract, "value": hex(value_wei), "data": calldata,
    }]), 16)
    if estimate > gas_limit:
        raise ValueError("Escrow gas estimate changed; prepare again")
    transaction = {
        "type": 2, "chainId": chain_id, "nonce": nonce, "to": contract,
        "value": value_wei, "data": calldata, "gas": gas_limit,
        "maxFeePerGas": max_fee, "maxPriorityFeePerGas": priority_fee,
    }
    signed = account.sign_transaction(transaction)
    raw = getattr(signed, "raw_transaction", None) or getattr(signed, "rawTransaction", None)
    raw_hex = raw.hex(); tx_hash = signed.hash.hex()
    return (raw_hex if raw_hex.startswith("0x") else "0x" + raw_hex,
            tx_hash if tx_hash.startswith("0x") else "0x" + tx_hash)


def _authorize_achievement(data):
    _assert_send_available()
    contract = _reward_contract()
    recipient = str(data.get("recipient", "")).strip()
    claim_id = str(data.get("claim_id", "")).strip().lower()
    try:
        achievement_id = int(data.get("achievement_id"))
    except (TypeError, ValueError):
        raise ValueError("Invalid achievement ID")
    if is_address is None or not is_address(recipient):
        raise ValueError("Invalid badge recipient")
    if achievement_id not in REWARD_ALLOWED_ACHIEVEMENT_IDS:
        raise ValueError("Achievement ID is not allowlisted")
    if not re.fullmatch(r"0x[a-f0-9]{64}", claim_id):
        raise ValueError("Invalid achievement claim ID")
    recipient = to_checksum_address(recipient)
    account = _derive_reward_issuer_account()
    calldata = _achievement_calldata(recipient, achievement_id, claim_id)
    max_fee, priority_fee = _fee_quote()
    nonce = int(_rpc("eth_getTransactionCount", [account.address, "pending"]), 16)
    estimate = int(_rpc("eth_estimateGas", [{
        "from": account.address, "to": contract, "value": "0x0", "data": calldata,
    }]), 16)
    gas_limit = min(REWARD_MAX_GAS, max(estimate, (estimate * 120 + 99) // 100))
    if estimate > REWARD_MAX_GAS:
        raise ValueError("Achievement mint exceeds the configured gas policy")
    balance = int(_rpc("eth_getBalance", [account.address, "pending"]), 16)
    if balance < gas_limit * max_fee:
        raise ValueError("Achievement issuer needs Base Sepolia ETH for gas")
    transaction = {
        "type": 2, "chainId": WALLET_CHAIN_ID, "nonce": nonce,
        "to": contract, "value": 0, "data": calldata, "gas": gas_limit,
        "maxFeePerGas": max_fee, "maxPriorityFeePerGas": priority_fee,
    }
    signed = account.sign_transaction(transaction)
    raw = getattr(signed, "raw_transaction", None) or getattr(signed, "rawTransaction", None)
    raw_hex = raw.hex()
    tx_hash = signed.hash.hex()
    return (
        raw_hex if raw_hex.startswith("0x") else "0x" + raw_hex,
        tx_hash if tx_hash.startswith("0x") else "0x" + tx_hash,
        account.address,
    )


def _rpc(method, params):
    if not WALLET_RPC_URL:
        raise RuntimeError("WALLET_RPC_URL is not configured")
    response = requests.post(
        WALLET_RPC_URL,
        json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params},
        timeout=12,
    )
    response.raise_for_status()
    payload = response.json()
    if payload.get("error"):
        raise RuntimeError(payload["error"].get("message", "EVM RPC request failed"))
    return payload.get("result")


def _native_balance(address):
    actual_chain_id = int(_rpc("eth_chainId", []), 16)
    if actual_chain_id != WALLET_CHAIN_ID:
        raise RuntimeError(
            f"Configured RPC is chain {actual_chain_id}, expected {WALLET_CHAIN_ID}"
        )
    wei = int(_rpc("eth_getBalance", [address, "latest"]), 16)
    amount = Decimal(wei) / Decimal(10**18)
    return {"wei": str(wei), "formatted": format(amount, "f"), "symbol": WALLET_NATIVE_SYMBOL}


def _assert_send_available():
    if not WALLET_SEND_ENABLED:
        raise ValueError("Wallet sending is disabled by the operator")
    if WALLET_CHAIN_ID not in SEND_ENABLED_CHAIN_IDS:
        raise ValueError("Wallet v2 sending is restricted to Base Sepolia testnet")
    actual_chain_id = int(_rpc("eth_chainId", []), 16)
    if actual_chain_id != WALLET_CHAIN_ID:
        raise ValueError(f"RPC chain {actual_chain_id} does not match configured chain {WALLET_CHAIN_ID}")


def _validated_transfer_fields(data):
    user_id = str(data.get("user_id", "")).strip()
    expected_address = str(data.get("address", "")).strip()
    recipient = str(data.get("to", "")).strip()
    if not USER_ID_RE.fullmatch(user_id):
        raise ValueError("Invalid user ID")
    if is_address is None or not is_address(expected_address) or not is_address(recipient):
        raise ValueError("Invalid EVM address")
    expected_address = to_checksum_address(expected_address)
    recipient = to_checksum_address(recipient)
    account = _derive_account(user_id)
    if account.address.lower() != expected_address.lower():
        raise ValueError("Wallet derivation continuity check failed")
    try:
        value_wei = int(str(data.get("value_wei", "")))
    except (TypeError, ValueError):
        raise ValueError("Invalid transfer amount")
    if value_wei <= 0 or value_wei > WALLET_MAX_TRANSFER_WEI:
        raise ValueError(f"Transfer must be between 0 and {WALLET_MAX_TRANSFER_ETH} ETH")
    if recipient.lower() == expected_address.lower():
        raise ValueError("Sending to the same wallet is not allowed")
    return user_id, account, expected_address, recipient, value_wei


def _recipient_must_be_eoa(recipient):
    code = _rpc("eth_getCode", [recipient, "latest"])
    if code not in (None, "0x", "0x0", "0x00"):
        raise ValueError("Wallet v2 cannot send to smart contracts")


def _fee_quote():
    latest = _rpc("eth_getBlockByNumber", ["latest", False]) or {}
    base_fee = int(latest.get("baseFeePerGas") or "0x0", 16)
    try:
        priority_fee = int(_rpc("eth_maxPriorityFeePerGas", []), 16)
    except Exception:
        priority_fee = 1_000_000
    priority_fee = max(priority_fee, 1_000_000)
    max_fee = base_fee * 2 + priority_fee
    if max_fee > WALLET_MAX_FEE_WEI or priority_fee > WALLET_MAX_FEE_WEI:
        raise ValueError("Current network fee exceeds the configured safety cap")
    return max_fee, priority_fee


def _quote_transfer(data):
    _assert_send_available()
    _, _, sender, recipient, value_wei = _validated_transfer_fields(data)
    _recipient_must_be_eoa(recipient)
    max_fee, priority_fee = _fee_quote()
    gas_limit = int(_rpc("eth_estimateGas", [{
        "from": sender, "to": recipient, "value": hex(value_wei), "data": "0x"
    }]), 16)
    if gas_limit < 21_000 or gas_limit > 25_000:
        raise ValueError("Unexpected gas estimate; only simple native ETH transfers are allowed")
    # Small margin for RPC estimate differences, still capped to a native transfer.
    gas_limit = min(25_000, max(21_000, (gas_limit * 110 + 99) // 100))
    nonce = int(_rpc("eth_getTransactionCount", [sender, "pending"]), 16)
    balance_wei = int(_rpc("eth_getBalance", [sender, "pending"]), 16)
    maximum_cost = value_wei + gas_limit * max_fee
    if balance_wei < maximum_cost:
        raise ValueError("Insufficient balance for the transfer and maximum network fee")
    now = int(time.time())
    return {
        "from": sender,
        "to": recipient,
        "value_wei": str(value_wei),
        "nonce": nonce,
        "gas_limit": gas_limit,
        "max_fee_per_gas": str(max_fee),
        "max_priority_fee_per_gas": str(priority_fee),
        "maximum_fee_wei": str(gas_limit * max_fee),
        "chain_id": WALLET_CHAIN_ID,
        "quoted_at": now,
        "expires_at": now + WALLET_QUOTE_TTL_SECONDS,
    }


def _authorize_transfer(data):
    _assert_send_available()
    _, account, sender, recipient, value_wei = _validated_transfer_fields(data)
    _recipient_must_be_eoa(recipient)
    try:
        nonce = int(data["nonce"])
        gas_limit = int(data["gas_limit"])
        max_fee = int(str(data["max_fee_per_gas"]))
        priority_fee = int(str(data["max_priority_fee_per_gas"]))
        expires_at = int(data["expires_at"])
        chain_id = int(data["chain_id"])
    except (KeyError, TypeError, ValueError):
        raise ValueError("Malformed prepared transaction")
    if chain_id != WALLET_CHAIN_ID:
        raise ValueError("Prepared transaction has the wrong chain ID")
    if int(time.time()) > expires_at:
        raise ValueError("Transaction quote expired; prepare it again")
    if not 21_000 <= gas_limit <= 25_000:
        raise ValueError("Invalid gas limit")
    if priority_fee <= 0 or max_fee < priority_fee or max_fee > WALLET_MAX_FEE_WEI:
        raise ValueError("Prepared network fee is outside the safety policy")
    current_nonce = int(_rpc("eth_getTransactionCount", [sender, "pending"]), 16)
    if current_nonce != nonce:
        raise ValueError("Wallet nonce changed; prepare the transaction again")
    current_estimate = int(_rpc("eth_estimateGas", [{
        "from": sender, "to": recipient, "value": hex(value_wei), "data": "0x"
    }]), 16)
    if current_estimate > gas_limit:
        raise ValueError("Gas estimate changed; prepare the transaction again")
    balance_wei = int(_rpc("eth_getBalance", [sender, "pending"]), 16)
    if balance_wei < value_wei + gas_limit * max_fee:
        raise ValueError("Insufficient balance for the approved transaction")
    transaction = {
        "type": 2,
        "chainId": chain_id,
        "nonce": nonce,
        "to": recipient,
        "value": value_wei,
        "data": b"",
        "gas": gas_limit,
        "maxFeePerGas": max_fee,
        "maxPriorityFeePerGas": priority_fee,
    }
    signed = account.sign_transaction(transaction)
    raw = getattr(signed, "raw_transaction", None) or getattr(signed, "rawTransaction", None)
    tx_hash = signed.hash.hex()
    raw_hex = raw.hex()
    if not raw_hex.startswith("0x"):
        raw_hex = "0x" + raw_hex
    if not tx_hash.startswith("0x"):
        tx_hash = "0x" + tx_hash
    return raw_hex, tx_hash


def _transaction_history(address):
    if not WALLET_EXPLORER_API_URL:
        return [], False, "Transaction history provider is not configured"
    try:
        response = requests.get(
            f"{WALLET_EXPLORER_API_URL}/addresses/{address}/transactions",
            timeout=12,
        )
        response.raise_for_status()
        payload = response.json()
        items = payload.get("items", []) if isinstance(payload, dict) else []
        transactions = []
        for item in items[:20]:
            from_value = item.get("from") or {}
            to_value = item.get("to") or {}
            value_wei = int(str(item.get("value") or "0"), 0)
            transactions.append({
                "hash": item.get("hash", ""),
                "timestamp": item.get("timestamp"),
                "from": from_value.get("hash", "") if isinstance(from_value, dict) else "",
                "to": to_value.get("hash", "") if isinstance(to_value, dict) else "",
                "value": format(Decimal(value_wei) / Decimal(10**18), "f"),
                "symbol": WALLET_NATIVE_SYMBOL,
                "status": item.get("status", "unknown"),
                "method": item.get("method") or "Transfer",
                "explorer_url": f"{WALLET_EXPLORER_URL}/tx/{item.get('hash', '')}",
            })
        return transactions, True, ""
    except Exception as exc:
        log.warning("Explorer history unavailable: %s", exc)
        return [], False, "Transaction history is temporarily unavailable"


@app.route("/health", methods=["GET"])
def health():
    sdk_available = DstackClient is not None and to_account_secure is not None
    dstack_reachable = False
    if sdk_available:
        try:
            dstack_reachable = bool(DstackClient().is_reachable())
        except Exception:
            dstack_reachable = False
    rpc_reachable = None
    rpc_chain_id = None
    rpc_error = ""
    if WALLET_SEND_ENABLED:
        try:
            rpc_chain_id = int(_rpc("eth_chainId", []), 16)
            rpc_reachable = rpc_chain_id == WALLET_CHAIN_ID
            if not rpc_reachable:
                rpc_error = (
                    f"RPC returned chain {rpc_chain_id}; expected {WALLET_CHAIN_ID}"
                )
        except Exception as exc:
            rpc_reachable = False
            rpc_error = str(exc)
    send_policy_valid = (
        not WALLET_SEND_ENABLED or WALLET_CHAIN_ID in SEND_ENABLED_CHAIN_IDS
    )
    ok = (
        sdk_available
        and dstack_reachable
        and send_policy_valid
        and (not WALLET_SEND_ENABLED or rpc_reachable is True)
    )
    return jsonify({
        "status": "ok" if ok else "error",
        "service": "wallet",
        "mode": "controlled-testnet-send" if WALLET_SEND_ENABLED else "receive-only",
        "send_enabled": WALLET_SEND_ENABLED and WALLET_CHAIN_ID in SEND_ENABLED_CHAIN_IDS,
        "chain_id": WALLET_CHAIN_ID,
        "chain_name": WALLET_CHAIN_NAME,
        "dstack_reachable": dstack_reachable,
        "rpc_reachable": rpc_reachable,
        "rpc_chain_id": rpc_chain_id,
        "rpc_error": rpc_error,
        "reward_badges_enabled": REWARD_BADGES_ENABLED,
        "reward_contract_configured": bool(REWARD_BADGE_CONTRACT_ADDRESS),
        "task_escrow_enabled": TASK_ESCROW_ENABLED,
        "task_escrow_contract_configured": bool(TASK_ESCROW_CONTRACT_ADDRESS),
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }), 200 if ok else 503


@app.route("/v1/wallets/derive", methods=["POST"])
def derive_wallet():
    data = request.get_json(silent=True) or {}
    user_id = str(data.get("user_id", "")).strip()
    if not USER_ID_RE.fullmatch(user_id):
        return jsonify({"status": "error", "message": "Invalid user ID"}), 400
    try:
        address = _derive_address(user_id)
        return jsonify({
            "status": "success",
            "address": address,
            "chain_id": WALLET_CHAIN_ID,
            "chain_name": WALLET_CHAIN_NAME,
            "native_symbol": WALLET_NATIVE_SYMBOL,
            "derivation_version": WALLET_DERIVATION_VERSION,
            "receive_uri": f"ethereum:{address}@{WALLET_CHAIN_ID}",
            "explorer_url": f"{WALLET_EXPLORER_URL}/address/{address}",
            "mode": "controlled-testnet-send" if WALLET_SEND_ENABLED else "receive-only",
        })
    except Exception as exc:
        log.exception("Wallet address derivation failed")
        return jsonify({"status": "error", "message": f"Wallet derivation unavailable: {exc}"}), 503


@app.route("/v1/rewards/config", methods=["POST"])
def reward_config():
    try:
        issuer = _derive_reward_issuer_account().address
        contract = (
            to_checksum_address(REWARD_BADGE_CONTRACT_ADDRESS)
            if REWARD_BADGE_CONTRACT_ADDRESS and is_address(REWARD_BADGE_CONTRACT_ADDRESS)
            else ""
        )
        return jsonify({
            "status": "success",
            "enabled": REWARD_BADGES_ENABLED,
            "chain_id": WALLET_CHAIN_ID,
            "chain_name": WALLET_CHAIN_NAME,
            "issuer_address": issuer,
            "contract_address": contract,
            "contract_explorer_url": f"{WALLET_EXPLORER_URL}/address/{contract}" if contract else "",
            "issuer_explorer_url": f"{WALLET_EXPLORER_URL}/address/{issuer}",
        })
    except Exception as exc:
        return jsonify({"status": "error", "message": f"Reward configuration unavailable: {exc}"}), 503


@app.route("/v1/escrows/config", methods=["POST"])
def escrow_config():
    contract = ""
    if TASK_ESCROW_CONTRACT_ADDRESS and is_address and is_address(TASK_ESCROW_CONTRACT_ADDRESS):
        contract = to_checksum_address(TASK_ESCROW_CONTRACT_ADDRESS)
    enabled = bool(
        TASK_ESCROW_ENABLED and WALLET_SEND_ENABLED
        and WALLET_CHAIN_ID in SEND_ENABLED_CHAIN_IDS and contract
    )
    return jsonify({
        "status": "success", "enabled": enabled,
        "chain_id": WALLET_CHAIN_ID, "chain_name": WALLET_CHAIN_NAME,
        "contract_address": contract, "maximum_escrow_eth": str(TASK_ESCROW_MAX_ETH),
        "contract_explorer_url": f"{WALLET_EXPLORER_URL}/address/{contract}" if contract else "",
    })


@app.route("/v1/escrows/quote", methods=["POST"])
def quote_escrow():
    try:
        return jsonify({"status": "success", "quote": _quote_escrow(request.get_json(silent=True) or {})})
    except ValueError as exc:
        return jsonify({"status": "error", "message": str(exc)}), 400
    except Exception as exc:
        log.exception("Escrow quote failed")
        return jsonify({"status": "error", "message": f"Escrow quote unavailable: {exc}"}), 503


@app.route("/v1/escrows/authorize", methods=["POST"])
def authorize_escrow():
    """Sign only create, release, or refund calls to the configured escrow contract."""
    try:
        raw_transaction, transaction_hash = _authorize_escrow(request.get_json(silent=True) or {})
        return jsonify({
            "status": "success", "raw_transaction": raw_transaction,
            "transaction_hash": transaction_hash,
        })
    except ValueError as exc:
        return jsonify({"status": "error", "message": str(exc)}), 400
    except Exception as exc:
        log.exception("Escrow authorization failed")
        return jsonify({"status": "error", "message": f"Escrow authorization unavailable: {exc}"}), 503


@app.route("/v1/rewards/authorize-achievement", methods=["POST"])
def authorize_achievement():
    """Sign only the fixed allowlisted non-transferable badge mint call."""
    try:
        raw_transaction, transaction_hash, issuer = _authorize_achievement(
            request.get_json(silent=True) or {}
        )
        return jsonify({
            "status": "success", "raw_transaction": raw_transaction,
            "transaction_hash": transaction_hash, "issuer_address": issuer,
        })
    except ValueError as exc:
        return jsonify({"status": "error", "message": str(exc)}), 400
    except Exception as exc:
        log.exception("Achievement authorization failed")
        return jsonify({"status": "error", "message": f"Achievement authorization unavailable: {exc}"}), 503


@app.route("/v1/wallets/portfolio", methods=["POST"])
def wallet_portfolio():
    data = request.get_json(silent=True) or {}
    address = str(data.get("address", "")).strip()
    if not ADDRESS_RE.fullmatch(address):
        return jsonify({"status": "error", "message": "Invalid EVM address"}), 400
    try:
        balance = _native_balance(address)
    except Exception as exc:
        return jsonify({"status": "error", "message": f"Balance unavailable: {exc}"}), 503
    transactions, history_available, history_message = _transaction_history(address)
    return jsonify({
        "status": "success",
        "balance": balance,
        "transactions": transactions,
        "history_available": history_available,
        "history_message": history_message,
    })


@app.route("/v1/wallets/quote-transfer", methods=["POST"])
def quote_transfer():
    try:
        quote = _quote_transfer(request.get_json(silent=True) or {})
        return jsonify({"status": "success", "quote": quote})
    except ValueError as exc:
        return jsonify({"status": "error", "message": str(exc)}), 400
    except Exception as exc:
        log.exception("Transfer quote failed")
        return jsonify({"status": "error", "message": f"Transfer quote unavailable: {exc}"}), 503


@app.route("/v1/wallets/authorize-transfer", methods=["POST"])
def authorize_transfer():
    """Sign one fully specified native transfer; arbitrary payloads are impossible."""
    try:
        raw_transaction, transaction_hash = _authorize_transfer(request.get_json(silent=True) or {})
        return jsonify({
            "status": "success",
            "raw_transaction": raw_transaction,
            "transaction_hash": transaction_hash,
        })
    except ValueError as exc:
        return jsonify({"status": "error", "message": str(exc)}), 400
    except Exception as exc:
        log.exception("Transfer authorization failed")
        return jsonify({"status": "error", "message": f"Transfer authorization unavailable: {exc}"}), 503


@app.route("/v1/wallets/broadcast", methods=["POST"])
def broadcast_transaction():
    data = request.get_json(silent=True) or {}
    raw_transaction = str(data.get("raw_transaction", "")).strip()
    expected_hash = str(data.get("transaction_hash", "")).strip().lower()
    if not re.fullmatch(r"0x[0-9a-fA-F]{2,8192}", raw_transaction):
        return jsonify({"status": "error", "message": "Invalid signed transaction"}), 400
    if not re.fullmatch(r"0x[0-9a-f]{64}", expected_hash):
        return jsonify({"status": "error", "message": "Invalid transaction hash"}), 400
    try:
        _assert_send_available()
        transaction_hash = str(_rpc("eth_sendRawTransaction", [raw_transaction])).lower()
        if transaction_hash != expected_hash:
            raise RuntimeError("RPC returned a different transaction hash")
        return jsonify({"status": "success", "transaction_hash": transaction_hash})
    except Exception as exc:
        # Retrying the exact signed transaction is safe. If it is already known,
        # confirm by hash rather than creating or signing a replacement nonce.
        try:
            known = _rpc("eth_getTransactionByHash", [expected_hash])
            if known:
                return jsonify({"status": "success", "transaction_hash": expected_hash, "already_known": True})
        except Exception:
            pass
        return jsonify({"status": "error", "message": f"Broadcast failed: {exc}"}), 503


@app.route("/v1/wallets/transaction-status", methods=["POST"])
def transaction_status():
    transaction_hash = str((request.get_json(silent=True) or {}).get("transaction_hash", "")).lower()
    if not re.fullmatch(r"0x[0-9a-f]{64}", transaction_hash):
        return jsonify({"status": "error", "message": "Invalid transaction hash"}), 400
    try:
        receipt = _rpc("eth_getTransactionReceipt", [transaction_hash])
        if not receipt:
            known = _rpc("eth_getTransactionByHash", [transaction_hash])
            return jsonify({
                "status": "success",
                "transaction_status": "pending" if known else "not_found",
                "transaction_hash": transaction_hash,
            })
        succeeded = int(receipt.get("status", "0x0"), 16) == 1
        return jsonify({
            "status": "success",
            "transaction_status": "confirmed" if succeeded else "failed",
            "transaction_hash": transaction_hash,
            "block_number": int(receipt["blockNumber"], 16) if receipt.get("blockNumber") else None,
            "gas_used": str(int(receipt["gasUsed"], 16)) if receipt.get("gasUsed") else None,
            "explorer_url": f"{WALLET_EXPLORER_URL}/tx/{transaction_hash}",
        })
    except Exception as exc:
        return jsonify({"status": "error", "message": f"Transaction status unavailable: {exc}"}), 503


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5004)
