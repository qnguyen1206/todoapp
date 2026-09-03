"""
Phala CVM Client Module for TODO App
Handles all communication with Phala CVM endpoints for confidential computing.
Supports: Backend storage, AI inference, task sync, and scheduled automation.
"""

import json
import os
import requests
import threading
from pathlib import Path
from datetime import datetime
import hashlib
import uuid
import base64
import secrets
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import urlencode, urlparse, parse_qs

try:
    from cryptography.fernet import Fernet
    ENCRYPTION_AVAILABLE = True
except ImportError:
    ENCRYPTION_AVAILABLE = False
    print("cryptography not available. CVM end-to-end encryption will be disabled.")

try:
    from e2e_crypto import (
        TASK_ENCRYPTION_PREFIX,
        approval_payload,
        decrypt_task as decrypt_task_v2,
        encrypt_task as encrypt_task_v2,
        generate_private_key,
        private_key_from_b64,
        private_key_to_b64,
        public_key_to_b64,
        sign_approval,
        unwrap_workspace_key,
        wrap_workspace_key,
    )
    PUBLIC_KEY_ENCRYPTION_AVAILABLE = True
except ImportError:
    PUBLIC_KEY_ENCRYPTION_AVAILABLE = False
    print("cryptography is not available. Device-key encryption will be disabled.")


class DeviceApprovalRequired(RuntimeError):
    """Raised when a device has registered but has not been approved yet."""


class CVMClient:
    """Client for communicating with Phala CVM endpoints"""
    
    def __init__(self):
        self.CVM_CONFIG_FILE = str(Path.home()) + "/TODOapp/cvm_config.json"
        self.cvm_endpoints = {}
        self.encryption_key = None
        self.api_key = ""
        self.user_id = ""  # custom persistent user ID (empty = auto from hostname)
        self.account_email = ""
        self.access_token = ""
        self.refresh_token = ""
        self.access_expires_at = 0
        self.google_desktop_client_id = ""
        self.crypto_device_id = ""
        self.crypto_encryption_private_key = ""
        self.crypto_signing_private_key = ""
        self._workspace_keys = {}
        self.load_cvm_config()

    def load_cvm_config(self):
        """Load CVM configuration from file"""
        try:
            if os.path.exists(self.CVM_CONFIG_FILE):
                with open(self.CVM_CONFIG_FILE, 'r') as f:
                    config = json.load(f)
                    self.cvm_endpoints = config.get('endpoints', {})
                    self.encryption_key = config.get('encryption_key', None)
                    self.api_key = config.get('api_key', '')
                    self.user_id = config.get('user_id', '')
                    account = config.get('account', {})
                    self.account_email = account.get('email', '')
                    self.access_token = account.get('access_token', '')
                    self.refresh_token = account.get('refresh_token', '')
                    self.access_expires_at = account.get('access_expires_at', 0)
                    self.google_desktop_client_id = account.get('google_desktop_client_id', '')
                    crypto = config.get('crypto', {})
                    self.crypto_device_id = crypto.get('device_id', '')
                    self.crypto_encryption_private_key = crypto.get('encryption_private_key', '')
                    self.crypto_signing_private_key = crypto.get('signing_private_key', '')
        except Exception as e:
            print(f"Failed to load CVM config: {e}")
            self.cvm_endpoints = {
                'backend': '',
                'ai_inference': '',
                'task_sync': '',
                'scheduler': ''
            }

    def save_cvm_config(self):
        """Save CVM configuration without discarding keys created by another client."""
        try:
            config = {}
            if os.path.exists(self.CVM_CONFIG_FILE):
                try:
                    with open(self.CVM_CONFIG_FILE, 'r') as f:
                        config = json.load(f)
                except (OSError, json.JSONDecodeError):
                    config = {}
            config.update({
                'endpoints': self.cvm_endpoints,
                'encryption_key': self.encryption_key,
                'api_key': self.api_key,
                'user_id': self.user_id,
            })
            if self.crypto_device_id and self.crypto_encryption_private_key and self.crypto_signing_private_key:
                config['crypto'] = {
                    'device_id': self.crypto_device_id,
                    'encryption_private_key': self.crypto_encryption_private_key,
                    'signing_private_key': self.crypto_signing_private_key,
                }
            if self.account_email or self.refresh_token:
                config['account'] = {
                    'email': self.account_email,
                    'access_token': self.access_token,
                    'refresh_token': self.refresh_token,
                    'access_expires_at': self.access_expires_at,
                    'google_desktop_client_id': self.google_desktop_client_id,
                }
            Path(self.CVM_CONFIG_FILE).parent.mkdir(parents=True, exist_ok=True)
            with open(self.CVM_CONFIG_FILE, 'w') as f:
                json.dump(config, f, indent=2)
        except Exception as e:
            print(f"Failed to save CVM config: {e}")

    def _headers(self):
        """Return request headers including API key when set."""
        h = {"Content-Type": "application/json"}
        if self.api_key:
            h["X-API-Key"] = self.api_key
        if self.access_token:
            h["Authorization"] = f"Bearer {self.access_token}"
        return h

    def _backend_url(self):
        return self.cvm_endpoints.get('backend', '').rstrip('/')

    def _store_account_session(self, payload):
        self.user_id = payload.get('user_id', self.user_id)
        self.account_email = payload.get('email', self.account_email)
        self.access_token = payload.get('access_token', '')
        self.refresh_token = payload.get('refresh_token', '')
        self.access_expires_at = int(__import__('time').time()) + int(payload.get('expires_in', 900)) - 30
        self.save_cvm_config()

    def ensure_account_session(self):
        """Ensure a usable access token exists, refreshing it when necessary."""
        import time

        if self.access_token and time.time() < self.access_expires_at:
            return True, self.account_email or 'Signed in'
        if not self.refresh_token:
            return False, 'Sign in to your TODO account before syncing tasks.'

        endpoint = self._backend_url()
        if not endpoint:
            return False, 'Configure the Backend Storage endpoint first.'

        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["X-API-Key"] = self.api_key
        try:
            response = requests.post(
                endpoint + '/auth/refresh',
                json={'refresh_token': self.refresh_token},
                headers=headers,
                timeout=15,
            )
            payload = response.json()
            if response.status_code != 200:
                return False, payload.get('message', 'Your session expired. Sign in again.')
            self._store_account_session(payload)
            return True, self.account_email or 'Signed in'
        except (requests.RequestException, ValueError) as exc:
            return False, f'Could not refresh account session: {exc}'

    def account_login(self, email, password, display_name=None):
        """Sign in or register with the shared CVM account service."""
        endpoint = self._backend_url()
        if not endpoint:
            return False, 'Configure the Backend Storage endpoint first.'
        data = {'email': email.strip(), 'password': password}
        path = '/auth/login'
        if display_name is not None:
            path = '/auth/register'
            data['display_name'] = display_name.strip()
        try:
            response = requests.post(endpoint + path, json=data, headers=self._headers(), timeout=15)
            payload = response.json()
            if response.status_code == 202 and payload.get('status') == 'verification_required':
                return None, payload.get('message', 'Check your email for a verification code.')
            if response.status_code not in (200, 201):
                return False, payload.get('message', 'Sign-in failed')
            self._store_account_session(payload)
            return True, payload.get('email', 'Signed in')
        except (requests.RequestException, ValueError) as exc:
            return False, f'Could not reach account service: {exc}'

    def account_logout(self):
        endpoint = self._backend_url()
        if endpoint and self.refresh_token:
            try:
                requests.post(endpoint + '/auth/logout', json={'refresh_token': self.refresh_token}, headers=self._headers(), timeout=10)
            except requests.RequestException:
                pass
        self.account_email = self.access_token = self.refresh_token = ''
        self.access_expires_at = 0
        self.save_cvm_config()

    def account_verify_email(self, email, code):
        endpoint = self._backend_url()
        if not endpoint:
            return False, 'Configure the Backend Storage endpoint first.'
        try:
            response = requests.post(endpoint + '/auth/verify-email', json={'email': email.strip(), 'code': code.strip()}, headers=self._headers(), timeout=15)
            payload = response.json()
            if response.status_code != 200:
                return False, payload.get('message', 'Verification failed')
            self._store_account_session(payload)
            return True, payload.get('email', 'Signed in')
        except (requests.RequestException, ValueError) as exc:
            return False, f'Could not reach account service: {exc}'

    def google_desktop_login(self, client_id):
        """Launch Google's browser sign-in using OAuth PKCE and a loopback callback."""
        endpoint = self._backend_url()
        if not endpoint:
            return False, 'Configure the Backend Storage endpoint first.'
        if not client_id:
            return False, 'Enter a Google Desktop OAuth client ID.'
        state = secrets.token_urlsafe(24)
        verifier = secrets.token_urlsafe(64)
        challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b'=').decode()
        received = {}
        class Callback(BaseHTTPRequestHandler):
            def do_GET(self):
                query = parse_qs(urlparse(self.path).query)
                received.update({key: values[0] for key, values in query.items() if values})
                self.send_response(200); self.send_header('Content-Type', 'text/html'); self.end_headers()
                self.wfile.write(b'<h2>TODO App sign-in complete</h2><p>You can close this window and return to the app.</p>')
            def log_message(self, format, *args):
                return
        server = HTTPServer(('127.0.0.1', 0), Callback)
        redirect_uri = f'http://127.0.0.1:{server.server_port}/callback'
        auth_url = 'https://accounts.google.com/o/oauth2/v2/auth?' + urlencode({
            'client_id': client_id, 'redirect_uri': redirect_uri, 'response_type': 'code',
            'scope': 'openid email profile', 'state': state, 'code_challenge': challenge,
            'code_challenge_method': 'S256', 'access_type': 'offline',
        })
        webbrowser.open(auth_url)
        server.timeout = 180
        server.handle_request()
        if received.get('state') != state or not received.get('code'):
            return False, received.get('error_description', 'Google sign-in was cancelled or timed out')
        try:
            response = requests.post(endpoint + '/auth/google/desktop', json={
                'code': received['code'], 'code_verifier': verifier, 'redirect_uri': redirect_uri, 'client_id': client_id,
            }, headers=self._headers(), timeout=20)
            payload = response.json()
            if response.status_code != 200:
                return False, payload.get('message', 'Google sign-in failed')
            self._store_account_session(payload)
            return True, payload.get('email', 'Signed in')
        except (requests.RequestException, ValueError) as exc:
            return False, f'Could not complete Google sign-in: {exc}'

    def _ensure_device_keys(self):
        """Create this computer's local ECDH and signing key pairs once."""
        if not PUBLIC_KEY_ENCRYPTION_AVAILABLE:
            return False
        try:
            if self.crypto_encryption_private_key and self.crypto_signing_private_key:
                # Validate persisted material before relying on it.
                private_key_from_b64(self.crypto_encryption_private_key)
                private_key_from_b64(self.crypto_signing_private_key)
                if self.crypto_device_id:
                    return True
            encryption_private_key = generate_private_key()
            signing_private_key = generate_private_key()
            self.crypto_device_id = uuid.uuid4().hex
            self.crypto_encryption_private_key = private_key_to_b64(encryption_private_key)
            self.crypto_signing_private_key = private_key_to_b64(signing_private_key)
            self.save_cvm_config()
            return True
        except Exception as exc:
            print(f"Failed to create local device keys: {exc}")
            return False

    def _device_key_material(self):
        """Return the local private/public keys, generating them when possible."""
        if not self._ensure_device_keys():
            raise RuntimeError("Device-key encryption requires the cryptography package")
        encryption_private_key = private_key_from_b64(self.crypto_encryption_private_key)
        signing_private_key = private_key_from_b64(self.crypto_signing_private_key)
        return {
            'device_id': self.crypto_device_id,
            'encryption_private_key': encryption_private_key,
            'signing_private_key': signing_private_key,
            'encryption_public_key': public_key_to_b64(encryption_private_key.public_key()),
            'signing_public_key': public_key_to_b64(signing_private_key.public_key()),
        }
    
    def set_endpoint(self, service_type, endpoint_url):
        """Set CVM endpoint for a specific service
        
        Args:
            service_type: 'backend', 'ai_inference', 'task_sync', or 'scheduler'
            endpoint_url: URL of the CVM endpoint
        """
        if service_type in self.cvm_endpoints:
            self.cvm_endpoints[service_type] = endpoint_url
            self.save_cvm_config()
            return True
        return False
    
    def test_connection(self, endpoint_url):
        """Test connection to a CVM endpoint
        
        Returns:
            (bool, str): (success, message)
        """
        try:
            response = requests.get(f"{endpoint_url}/health", timeout=5)
            if response.status_code == 200:
                return True, "✓ CVM connection successful"
            else:
                return False, f"✗ CVM returned status {response.status_code}"
        except requests.exceptions.Timeout:
            return False, "✗ Connection timeout - CVM not responding"
        except requests.exceptions.ConnectionError:
            return False, "✗ Cannot connect to CVM endpoint"
        except Exception as e:
            return False, f"✗ Error: {str(e)}"


class CVMBackendClient(CVMClient):
    """Client for Phala CVM Backend Storage & Sync Service"""

    # ENC1 is the legacy shared-secret format; ENC2 is device-key based.
    _ENC_PREFIX = "ENC1:"
    _ENC2_PREFIX = "ENC2:"

    def _fernet(self):
        """Return a Fernet instance derived from the stored encryption key, or None."""
        if not ENCRYPTION_AVAILABLE or not self.encryption_key:
            return None
        try:
            import base64, hashlib
            raw = hashlib.sha256(self.encryption_key.encode()).digest()  # 32 bytes
            return Fernet(base64.urlsafe_b64encode(raw))
        except Exception as e:
            print(f"Fernet init failed: {e}")
            return None

    def _crypto_request(self, method, path, **kwargs):
        """Call the device-key registry; None means a backend is not configured."""
        endpoint = self.cvm_endpoints.get('backend')
        if not endpoint:
            return None
        kwargs.setdefault('headers', self._headers())
        kwargs.setdefault('timeout', 10)
        return requests.request(method, f"{endpoint}{path}", **kwargs)

    def _get_crypto_devices(self, user_id):
        response = self._crypto_request('GET', '/crypto/devices', params={'user_id': user_id})
        if response is None or response.status_code == 404:
            return None
        if response.status_code != 200:
            raise RuntimeError(f"Could not load encryption devices: {response.text}")
        return response.json().get('devices', [])

    def get_encryption_devices(self, user_id):
        """Return (success, devices-or-message) for the desktop pairing UI."""
        try:
            devices = self._get_crypto_devices(user_id)
            if devices is None:
                return False, "The deployed backend does not support device-key encryption yet."
            return True, devices
        except Exception as exc:
            return False, str(exc)

    def _workspace_key(self, user_id):
        """Unlock this computer's workspace key, or register the computer once."""
        if user_id in self._workspace_keys:
            return self._workspace_keys[user_id]
        if not PUBLIC_KEY_ENCRYPTION_AVAILABLE:
            return None

        devices = self._get_crypto_devices(user_id)
        if devices is None:
            return None  # A server from before the ENC2 protocol.

        material = self._device_key_material()
        own = next((d for d in devices if d.get('device_id') == material['device_id']), None)
        if own is None:
            candidate_key = os.urandom(32)
            wrapped = wrap_workspace_key(
                candidate_key,
                material['encryption_public_key'],
                user_id,
                material['device_id'],
            )
            response = self._crypto_request(
                'POST',
                '/crypto/devices/register',
                json={
                    'user_id': user_id,
                    'device_id': material['device_id'],
                    'encryption_public_key': material['encryption_public_key'],
                    'signing_public_key': material['signing_public_key'],
                    'wrapped_workspace_key': wrapped,
                },
            )
            if response is None or response.status_code == 404:
                return None
            if response.status_code not in (200, 201):
                raise RuntimeError(f"Could not register this device: {response.text}")
            own = response.json().get('device', {})
            if own.get('status') == 'active':
                self._workspace_keys[user_id] = candidate_key
                return candidate_key

        if own.get('status') != 'active':
            raise DeviceApprovalRequired(
                "This computer is waiting for approval from a device that already has access."
            )
        wrapped = own.get('wrapped_workspace_key')
        if not wrapped:
            raise RuntimeError("The approved device is missing its encrypted workspace key")
        try:
            workspace_key = unwrap_workspace_key(
                wrapped,
                material['encryption_private_key'],
                user_id,
                material['device_id'],
            )
        except Exception as exc:
            raise RuntimeError("Could not unlock this device's workspace key") from exc
        self._workspace_keys[user_id] = workspace_key
        return workspace_key

    def approve_encryption_device(self, user_id, device_id):
        """Approve a pending device by wrapping the local key to its public key."""
        workspace_key = self._workspace_key(user_id)
        if not workspace_key:
            raise RuntimeError("This backend does not support device-key encryption")
        material = self._device_key_material()
        devices = self._get_crypto_devices(user_id) or []
        target = next((d for d in devices if d.get('device_id') == device_id), None)
        if not target:
            raise RuntimeError("The requested device no longer exists")
        if target.get('status') != 'pending':
            raise RuntimeError("The requested device is not waiting for approval")

        wrapped = wrap_workspace_key(
            workspace_key,
            target['encryption_public_key'],
            user_id,
            device_id,
        )
        payload = approval_payload(
            user_id,
            device_id,
            target['encryption_public_key'],
            target['signing_public_key'],
            wrapped,
        )
        response = self._crypto_request(
            'POST',
            f"/crypto/devices/{device_id}/approve",
            json={
                'user_id': user_id,
                'approver_device_id': material['device_id'],
                'wrapped_workspace_key': wrapped,
                'signature': sign_approval(material['signing_private_key'], payload),
                'signature_format': 'der',
            },
        )
        if response is None or response.status_code == 404:
            raise RuntimeError("The deployed backend does not support device approval yet")
        if response.status_code != 200:
            raise RuntimeError(f"Could not approve device: {response.text}")
        return response.json().get('device', {})

    def reset_encryption_devices(self):
        """Reset server-side device trust after the user confirms key loss."""
        response = self._crypto_request(
            'POST',
            '/crypto/devices/reset',
            json={'confirmation': 'RESET ENCRYPTION'},
        )
        if response is None:
            return False, 'Backend endpoint not configured'
        try:
            payload = response.json()
        except ValueError:
            payload = {}
        if response.status_code == 404:
            return False, 'The deployed backend must be updated before device recovery is available.'
        if response.status_code != 200:
            return False, payload.get('message', f'Device reset failed ({response.status_code})')
        self._workspace_keys.clear()
        return True, payload.get('message', 'Encryption devices reset')

    def _encrypt_tasks(self, user_id, tasks):
        """Encrypt title+notes of every task before sending to CVM.
        Keeps due_date/due_time/priority in plaintext so the backend can sort.
        Returns tasks unchanged if no encryption key is configured.
        """
        workspace_key = self._workspace_key(user_id)
        if workspace_key:
            return [encrypt_task_v2(task, workspace_key, user_id) for task in tasks]

        f = self._fernet()
        if not f:
            return tasks
        encrypted = []
        for task in tasks:
            t = dict(task)
            sensitive = json.dumps({"title": t.get("title", ""),
                                    "notes": t.get("notes", "")})
            ciphertext = f.encrypt(sensitive.encode()).decode()
            t["notes"]  = self._ENC_PREFIX + ciphertext
            t["title"]  = "[Encrypted]"
            encrypted.append(t)
        return encrypted

    def _decrypt_tasks(self, user_id, tasks):
        """Decrypt title+notes of tasks received from CVM.
        Returns tasks unchanged if no key or not encrypted.
        """
        workspace_key = self._workspace_key(user_id)
        has_modern_tasks = any(
            isinstance(task.get("notes"), str) and task["notes"].startswith(self._ENC2_PREFIX)
            for task in tasks
        )
        if has_modern_tasks and not workspace_key:
            raise DeviceApprovalRequired(
                "This computer cannot read encrypted tasks until an existing device approves it."
            )

        decrypted_modern = []
        for task in tasks:
            t = dict(task)
            notes = t.get("notes", "")
            if isinstance(notes, str) and notes.startswith(self._ENC2_PREFIX):
                try:
                    t = decrypt_task_v2(t, workspace_key, user_id)
                except Exception:
                    t["title"] = "[Decryption failed]"
                    t["notes"] = ""
            decrypted_modern.append(t)
        tasks = decrypted_modern

        f = self._fernet()
        if not f:
            return tasks
        decrypted = []
        for task in tasks:
            t = dict(task)
            notes = t.get("notes", "")
            if isinstance(notes, str) and notes.startswith(self._ENC_PREFIX):
                try:
                    ciphertext = notes[len(self._ENC_PREFIX):]
                    sensitive  = json.loads(f.decrypt(ciphertext.encode()).decode())
                    t["title"] = sensitive.get("title", "[Decryption failed]")
                    t["notes"] = sensitive.get("notes", "")
                except Exception:
                    t["title"] = "[Decryption failed – wrong key?]"
                    t["notes"] = ""
            decrypted.append(t)
        return decrypted

    def store_tasks(self, user_id, tasks_data):
        """Store tasks on CVM backend (upsert – keeps tasks not in this list)."""
        endpoint = self.cvm_endpoints.get('backend')
        if not endpoint:
            return False, "Backend endpoint not configured"

        try:
            payload = {
                'user_id': user_id,
                'tasks':   self._encrypt_tasks(user_id, tasks_data),
                'timestamp': datetime.now().isoformat()
            }
            response = requests.post(
                f"{endpoint}/tasks/store",
                json=payload,
                headers=self._headers(),
                timeout=10
            )
            if response.status_code == 200:
                enc = " (encrypted)" if self._fernet() else ""
                return True, f"Tasks stored on CVM{enc}"
            else:
                return False, f"Storage failed: {response.text}"
        except Exception as e:
            return False, f"Error storing tasks: {str(e)}"

    def replace_tasks(self, user_id, tasks_data):
        """Force-overwrite: delete ALL remote tasks for user then insert tasks_data."""
        endpoint = self.cvm_endpoints.get('backend')
        if not endpoint:
            return False, "Backend endpoint not configured"

        try:
            payload = {
                'user_id': user_id,
                'tasks':   self._encrypt_tasks(user_id, tasks_data),
                'timestamp': datetime.now().isoformat()
            }
            response = requests.post(
                f"{endpoint}/tasks/replace",
                json=payload,
                headers={**self._headers(), "X-Confirm-Replace": "true"},
                timeout=15
            )
            if response.status_code == 200:
                r   = response.json()
                enc = " (encrypted)" if self._fernet() else ""
                return True, f"Replaced {r.get('deleted', 0)} old → {r.get('inserted', 0)} new tasks{enc}"
            else:
                return False, f"Replace failed: {response.text}"
        except Exception as e:
            return False, f"Error replacing tasks: {str(e)}"

    def retrieve_tasks(self, user_id):
        """Retrieve and decrypt tasks from CVM backend."""
        endpoint = self.cvm_endpoints.get('backend')
        if not endpoint:
            return False, "Backend endpoint not configured"

        try:
            response = requests.get(
                f"{endpoint}/tasks/retrieve",
                params={'user_id': user_id},
                headers=self._headers(),
                timeout=10
            )
            if response.status_code == 200:
                raw = response.json().get('tasks', [])
                return True, self._decrypt_tasks(user_id, raw)
            else:
                return False, f"Retrieval failed: {response.text}"
        except Exception as e:
            return False, f"Error retrieving tasks: {str(e)}"

    def sync_tasks(self, user_id, local_tasks, last_sync_time=None):
        """Sync tasks with CVM backend (conflict resolution)."""
        endpoint = self.cvm_endpoints.get('backend')
        if not endpoint:
            return False, "Backend endpoint not configured"

        try:
            payload = {
                'user_id':    user_id,
                'local_tasks': self._encrypt_tasks(user_id, local_tasks),
                'last_sync':  last_sync_time or datetime.now().isoformat()
            }
            response = requests.post(
                f"{endpoint}/tasks/sync",
                json=payload,
                headers=self._headers(),
                timeout=10
            )
            if response.status_code == 200:
                raw = response.json().get('synced_tasks', [])
                return True, self._decrypt_tasks(user_id, raw)
            else:
                return False, f"Sync failed: {response.text}"
        except Exception as e:
            return False, f"Error syncing tasks: {str(e)}"


class CVMAIClient(CVMClient):
    """Client for Phala CVM AI Inference Service"""
    
    def send_inference_request(self, prompt, model_name=None, context_files=None):
        """Send inference request to CVM AI service
        
        Args:
            prompt: User query/prompt
            model_name: Optional model to use on CVM
            context_files: Optional list of file data for context
            
        Returns:
            (bool, response): (success, ai_response_or_error)
        """
        endpoint = self.cvm_endpoints.get('ai_inference')
        if not endpoint:
            return False, "AI inference endpoint not configured"
        
        try:
            payload = {
                'prompt': prompt,
                'model': model_name or 'default',
                'context': context_files or [],
                'timestamp': datetime.now().isoformat()
            }
            
            response = requests.post(
                f"{endpoint}/inference",
                json=payload,
                headers=self._headers(),
                timeout=30
            )
            
            if response.status_code == 200:
                return True, response.json().get('response', '')
            else:
                return False, f"Inference failed: {response.text}"
        except Exception as e:
            return False, f"Error with AI inference: {str(e)}"
    
    def check_ai_models(self):
        """Get list of available AI models on CVM
        
        Returns:
            (bool, models_list): Available models or error message
        """
        endpoint = self.cvm_endpoints.get('ai_inference')
        if not endpoint:
            return False, []
        
        try:
            response = requests.get(
                f"{endpoint}/models",
                headers=self._headers(),
                timeout=5
            )
            
            if response.status_code == 200:
                return True, response.json().get('models', [])
            else:
                return False, []
        except Exception as e:
            print(f"Error fetching models: {e}")
            return False, []


class CVMSyncClient(CVMClient):
    """Client for Phala CVM Decentralized Task Sync & Sharing"""
    
    def share_tasks(self, user_id, recipient_ids, tasks_data):
        """Share tasks with other users via CVM
        
        Args:
            user_id: Your user ID
            recipient_ids: List of user IDs to share with
            tasks_data: Tasks to share
            
        Returns:
            (bool, message)
        """
        endpoint = self.cvm_endpoints.get('task_sync')
        if not endpoint:
            return False, "Task sync endpoint not configured"
        
        try:
            payload = {
                'user_id': user_id,
                'recipients': recipient_ids,
                'tasks': tasks_data,
                'timestamp': datetime.now().isoformat()
            }
            
            response = requests.post(
                f"{endpoint}/share",
                json=payload,
                headers=self._headers(),
                timeout=10
            )
            
            if response.status_code == 200:
                return True, "Tasks shared successfully"
            else:
                return False, f"Share failed: {response.text}"
        except Exception as e:
            return False, f"Error sharing tasks: {str(e)}"
    
    def get_shared_tasks(self, user_id):
        """Get tasks shared with me by others
        
        Returns:
            (bool, tasks): Shared tasks or error message
        """
        endpoint = self.cvm_endpoints.get('task_sync')
        if not endpoint:
            return False, []
        
        try:
            response = requests.get(
                f"{endpoint}/shared",
                params={'user_id': user_id},
                headers=self._headers(),
                timeout=10
            )
            
            if response.status_code == 200:
                return True, response.json().get('shared_tasks', [])
            else:
                return False, []
        except Exception as e:
            print(f"Error getting shared tasks: {e}")
            return False, []


class CVMSchedulerClient(CVMClient):
    """Client for Phala CVM Scheduled Task Automation"""
    
    def schedule_job(self, job_id, job_type, schedule, parameters):
        """Schedule a background job on CVM
        
        Args:
            job_id: Unique job identifier
            job_type: 'reminder', 'cleanup', 'sync', 'notification'
            schedule: Cron expression or interval (e.g., '0 9 * * *' for 9am daily)
            parameters: Dict of parameters for the job
            
        Returns:
            (bool, message)
        """
        endpoint = self.cvm_endpoints.get('scheduler')
        if not endpoint:
            return False, "Scheduler endpoint not configured"
        
        try:
            payload = {
                'job_id': job_id,
                'job_type': job_type,
                'schedule': schedule,
                'parameters': parameters,
                'created_at': datetime.now().isoformat()
            }
            
            response = requests.post(
                f"{endpoint}/schedule",
                json=payload,
                headers=self._headers(),
                timeout=10
            )
            
            if response.status_code == 200:
                return True, "Job scheduled successfully"
            else:
                return False, f"Scheduling failed: {response.text}"
        except Exception as e:
            return False, f"Error scheduling job: {str(e)}"
    
    def cancel_job(self, job_id):
        """Cancel a scheduled job
        
        Returns:
            (bool, message)
        """
        endpoint = self.cvm_endpoints.get('scheduler')
        if not endpoint:
            return False, "Scheduler endpoint not configured"
        
        try:
            response = requests.delete(
                f"{endpoint}/schedule/{job_id}",
                headers=self._headers(),
                timeout=10
            )
            
            if response.status_code == 200:
                return True, "Job cancelled successfully"
            else:
                return False, f"Cancellation failed: {response.text}"
        except Exception as e:
            return False, f"Error cancelling job: {str(e)}"
    
    def get_job_status(self, job_id):
        """Get status of a scheduled job
        
        Returns:
            (bool, status_data)
        """
        endpoint = self.cvm_endpoints.get('scheduler')
        if not endpoint:
            return False, {}
        
        try:
            response = requests.get(
                f"{endpoint}/schedule/{job_id}",
                headers=self._headers(),
                timeout=5
            )
            
            if response.status_code == 200:
                return True, response.json()
            else:
                return False, {}
        except Exception as e:
            print(f"Error getting job status: {e}")
            return False, {}
