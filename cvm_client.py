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

try:
    from cryptography.fernet import Fernet
    ENCRYPTION_AVAILABLE = True
except ImportError:
    ENCRYPTION_AVAILABLE = False
    print("cryptography not available. CVM end-to-end encryption will be disabled.")


class CVMClient:
    """Client for communicating with Phala CVM endpoints"""
    
    def __init__(self):
        self.CVM_CONFIG_FILE = str(Path.home()) + "/TODOapp/cvm_config.json"
        self.cvm_endpoints = {}
        self.encryption_key = None
        self.api_key = ""
        self.user_id = ""  # custom persistent user ID (empty = auto from hostname)
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
        except Exception as e:
            print(f"Failed to load CVM config: {e}")
            self.cvm_endpoints = {
                'backend': '',
                'ai_inference': '',
                'task_sync': '',
                'scheduler': ''
            }

    def save_cvm_config(self):
        """Save CVM configuration to file"""
        try:
            config = {
                'endpoints': self.cvm_endpoints,
                'encryption_key': self.encryption_key,
                'api_key': self.api_key,
                'user_id': self.user_id,
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
        return h
    
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

    # Prefix that marks an encrypted task blob in the notes field
    _ENC_PREFIX = "ENC1:"

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

    def _encrypt_tasks(self, tasks):
        """Encrypt title+notes of every task before sending to CVM.
        Keeps due_date/due_time/priority in plaintext so the backend can sort.
        Returns tasks unchanged if no encryption key is configured.
        """
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

    def _decrypt_tasks(self, tasks):
        """Decrypt title+notes of tasks received from CVM.
        Returns tasks unchanged if no key or not encrypted.
        """
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
                'tasks':   self._encrypt_tasks(tasks_data),
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
                'tasks':   self._encrypt_tasks(tasks_data),
                'timestamp': datetime.now().isoformat()
            }
            response = requests.post(
                f"{endpoint}/tasks/replace",
                json=payload,
                headers=self._headers(),
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
                return True, self._decrypt_tasks(raw)
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
                'local_tasks': self._encrypt_tasks(local_tasks),
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
                return True, self._decrypt_tasks(raw)
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
