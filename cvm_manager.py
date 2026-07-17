"""
Phala CVM Manager Module for TODO App
Provides UI for configuring and managing CVM integration
"""

import json
import hashlib
import tkinter as tk
from tkinter import ttk, messagebox, simpledialog
from pathlib import Path
import threading

try:
    from cvm_client import CVMClient, CVMBackendClient, CVMAIClient, CVMSyncClient, CVMSchedulerClient
    CVM_AVAILABLE = True
except ImportError:
    CVM_AVAILABLE = False
    print("CVM client not available. CVM features will be disabled.")


class CVMManager:
    """Manages Phala CVM configuration and integration"""
    
    def __init__(self, parent_app):
        self.parent_app = parent_app
        
        if not CVM_AVAILABLE:
            raise ImportError("cvm_client is required for CVM functionality")
        
        # Initialize CVM clients
        self.cvm_client = CVMClient()
        self.backend_client = CVMBackendClient()
        self.ai_client = CVMAIClient()
        self.sync_client = CVMSyncClient()
        self.scheduler_client = CVMSchedulerClient()
        
        # Status tracking
        self.cvm_enabled = tk.BooleanVar(master=parent_app.root, value=False)
        self.endpoint_status = {}
    
    def create_cvm_menu_items(self, menu):
        """Add CVM configuration menu items
        
        Args:
            menu: Parent menu to add items to
        """
        cvm_menu = tk.Menu(menu, tearoff=0)
        menu.add_cascade(label="Phala CVM", menu=cvm_menu)
        
        cvm_menu.add_command(label="Configure Endpoints", command=self.open_endpoint_config)
        cvm_menu.add_command(label="Test Connections", command=self.test_all_connections)
        cvm_menu.add_separator()
        cvm_menu.add_command(label="Backend Storage Settings", command=self.configure_backend)
        cvm_menu.add_command(label="AI Inference Settings", command=self.configure_ai)
        cvm_menu.add_command(label="Task Sync Settings", command=self.configure_sync)
        cvm_menu.add_command(label="Scheduler Settings", command=self.configure_scheduler)
        cvm_menu.add_separator()
        cvm_menu.add_command(label="View CVM Status", command=self.show_cvm_status)
        
        return cvm_menu
    
    def open_endpoint_config(self):
        """Open endpoint configuration dialog"""
        if self.parent_app.check_existing_dialog():
            return
        
        config_window = tk.Toplevel(self.parent_app.root)
        config_window.title("Phala CVM Endpoint Configuration")
        config_window.geometry("600x400")
        
        # Instructions
        instructions = ttk.Label(
            config_window,
            text="Configure your Phala CVM endpoints below.\nEach service can have a different endpoint.",
            wraplength=500
        )
        instructions.pack(pady=10, padx=10)
        
        # Endpoints frame
        endpoints_frame = ttk.LabelFrame(config_window, text="Endpoints", padding=10)
        endpoints_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        
        # Create entry fields for each endpoint
        self.endpoint_entries = {}
        services = [
            ('backend', 'Backend Storage', 'https://cvm.phala.network/backend'),
            ('ai_inference', 'AI Inference', 'https://cvm.phala.network/ai'),
            ('task_sync', 'Task Sync', 'https://cvm.phala.network/sync'),
            ('scheduler', 'Scheduler', 'https://cvm.phala.network/scheduler')
        ]
        
        for service_type, label, placeholder in services:
            row = services.index((service_type, label, placeholder))
            ttk.Label(endpoints_frame, text=f"{label}:").grid(row=row, column=0, sticky='w', pady=5)
            entry = ttk.Entry(endpoints_frame, width=50)
            entry.grid(row=row, column=1, sticky='ew', pady=5)
            entry.insert(0, self.cvm_client.cvm_endpoints.get(service_type, ''))
            self.endpoint_entries[service_type] = entry
            test_btn = ttk.Button(
                endpoints_frame,
                text="Test",
                command=lambda st=service_type: self.test_endpoint(st)
            )
            test_btn.grid(row=row, column=2, padx=5)

        # API Key field
        api_row = len(services)
        ttk.Separator(endpoints_frame, orient='horizontal').grid(
            row=api_row, column=0, columnspan=3, sticky='ew', pady=8)
        ttk.Label(endpoints_frame, text="API Key:").grid(row=api_row + 1, column=0, sticky='w', pady=5)
        self._api_key_entry = ttk.Entry(endpoints_frame, width=50, show="*")
        self._api_key_entry.grid(row=api_row + 1, column=1, sticky='ew', pady=5)
        self._api_key_entry.insert(0, self.cvm_client.api_key or '')
        ttk.Label(endpoints_frame, text="(same key set in Phala dashboard)", foreground="gray").grid(
            row=api_row + 2, column=1, sticky='w')

        # Encryption Key field
        enc_row = api_row + 3
        ttk.Separator(endpoints_frame, orient='horizontal').grid(
            row=enc_row, column=0, columnspan=3, sticky='ew', pady=8)
        ttk.Label(endpoints_frame, text="Encryption Key:").grid(row=enc_row + 1, column=0, sticky='w', pady=5)
        self._enc_key_entry = ttk.Entry(endpoints_frame, width=50, show="*")
        self._enc_key_entry.grid(row=enc_row + 1, column=1, sticky='ew', pady=5)
        self._enc_key_entry.insert(0, self.cvm_client.encryption_key or '')

        enc_hint_frame = ttk.Frame(endpoints_frame)
        enc_hint_frame.grid(row=enc_row + 2, column=1, sticky='w')
        ttk.Label(enc_hint_frame, text="(client-side only – backend never sees plaintext)",
                  foreground="gray").pack(side=tk.LEFT)

        def gen_key():
            import secrets
            new_key = secrets.token_hex(24)
            self._enc_key_entry.delete(0, tk.END)
            self._enc_key_entry.insert(0, new_key)

        ttk.Button(enc_hint_frame, text="Generate", command=gen_key).pack(side=tk.LEFT, padx=6)

        endpoints_frame.columnconfigure(1, weight=1)
        
        # Buttons
        button_frame = ttk.Frame(config_window)
        button_frame.pack(fill=tk.X, padx=10, pady=10)
        
        ttk.Button(button_frame, text="Save", command=self.save_endpoints).pack(side=tk.LEFT, padx=5)
        ttk.Button(button_frame, text="Cancel", command=config_window.destroy).pack(side=tk.RIGHT, padx=5)
    
    def test_endpoint(self, service_type):
        """Test a single endpoint"""
        endpoint = self.endpoint_entries[service_type].get()
        if not endpoint:
            messagebox.showwarning("Empty Endpoint", f"Please enter a URL for {service_type}")
            return
        
        # Test in background
        def test_async():
            success, message = self.cvm_client.test_connection(endpoint)
            self.parent_app.root.after(0, lambda: messagebox.showinfo("Connection Test", message))
        
        threading.Thread(target=test_async, daemon=True).start()
    
    def save_endpoints(self):
        """Save configured endpoints, API key and encryption key"""
        for service_type, entry in self.endpoint_entries.items():
            endpoint_url = entry.get().strip()
            if endpoint_url:
                self.cvm_client.cvm_endpoints[service_type] = endpoint_url

        # Propagate API key and encryption key to all clients
        api_key = self._api_key_entry.get().strip()
        enc_key = self._enc_key_entry.get().strip()
        for client in (self.cvm_client, self.backend_client,
                       self.ai_client, self.sync_client, self.scheduler_client):
            client.api_key        = api_key
            client.encryption_key = enc_key
            client.cvm_endpoints  = self.cvm_client.cvm_endpoints

        self.cvm_client.save_cvm_config()
        enc_status = "enabled ✅" if enc_key else "disabled (no key set)"
        messagebox.showinfo("Saved",
            f"CVM endpoints and keys saved!\nE2E Encryption: {enc_status}")
    
    def test_all_connections(self):
        """Test all configured endpoints"""
        if self.parent_app.check_existing_dialog():
            return
        
        def test_async():
            results = {}
            for service_type, endpoint in self.cvm_client.cvm_endpoints.items():
                if endpoint:
                    success, message = self.cvm_client.test_connection(endpoint)
                    results[service_type] = (success, message)
                else:
                    results[service_type] = (False, "Not configured")
            
            self.parent_app.root.after(0, lambda: self.show_connection_results(results))
        
        threading.Thread(target=test_async, daemon=True).start()
    
    def show_connection_results(self, results):
        """Display connection test results"""
        result_window = tk.Toplevel(self.parent_app.root)
        result_window.title("CVM Connection Test Results")
        result_window.geometry("500x300")
        
        # Results display
        text_widget = tk.Text(result_window, wrap=tk.WORD, height=15, width=60)
        text_widget.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        text_widget.config(state=tk.DISABLED)
        
        # Format results
        result_text = "Phala CVM Connection Test Results:\n" + "="*40 + "\n\n"
        for service_type, (success, message) in results.items():
            result_text += f"{service_type.replace('_', ' ').title()}: {message}\n"
        
        text_widget.config(state=tk.NORMAL)
        text_widget.insert(1.0, result_text)
        text_widget.config(state=tk.DISABLED)
    
    def configure_backend(self):
        """Configure backend storage options"""
        config_window = tk.Toplevel(self.parent_app.root)
        config_window.title("CVM Backend Configuration")
        config_window.geometry("500x300")
        
        # Options
        ttk.Label(config_window, text="Confidential Backend Storage Options", font=("Arial", 11, "bold")).pack(pady=10)
        
        options_frame = ttk.LabelFrame(config_window, text="Settings", padding=10)
        options_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        
        auto_sync = tk.BooleanVar()
        ttk.Checkbutton(
            options_frame,
            text="Auto-sync tasks with CVM backend",
            variable=auto_sync
        ).pack(anchor='w', pady=5)
        
        ttk.Label(options_frame, text="Sync interval (minutes):").pack(anchor='w')
        sync_interval = ttk.Spinbox(options_frame, from_=1, to=60, width=5)
        sync_interval.set(15)
        sync_interval.pack(anchor='w', padx=20)
        
        ttk.Checkbutton(
            options_frame,
            text="Use end-to-end encryption",
            variable=tk.BooleanVar(value=True)
        ).pack(anchor='w', pady=5)
        
        # Buttons
        button_frame = ttk.Frame(config_window)
        button_frame.pack(fill=tk.X, padx=10, pady=10)
        ttk.Button(button_frame, text="Save", command=config_window.destroy).pack(side=tk.LEFT)
        ttk.Button(button_frame, text="Cancel", command=config_window.destroy).pack(side=tk.RIGHT)
    
    def configure_ai(self):
        """Configure AI inference settings"""
        config_window = tk.Toplevel(self.parent_app.root)
        config_window.title("CVM AI Inference Configuration")
        config_window.geometry("500x300")
        
        ttk.Label(config_window, text="Confidential AI Inference Options", font=("Arial", 11, "bold")).pack(pady=10)
        
        options_frame = ttk.LabelFrame(config_window, text="Settings", padding=10)
        options_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        
        ttk.Label(options_frame, text="Default model:").pack(anchor='w')
        model_var = tk.StringVar(value="default")
        ttk.Entry(options_frame, textvariable=model_var).pack(anchor='w', fill=tk.X, padx=20, pady=5)
        
        ttk.Checkbutton(
            options_frame,
            text="Use CVM for heavy computation (fallback to Ollama for quick tasks)",
            variable=tk.BooleanVar(value=False)
        ).pack(anchor='w', pady=5)
        
        ttk.Label(options_frame, text="This keeps your queries confidential on Phala").pack(anchor='w', padx=20, font=("Arial", 9, "italic"))
        
        button_frame = ttk.Frame(config_window)
        button_frame.pack(fill=tk.X, padx=10, pady=10)
        ttk.Button(button_frame, text="Save", command=config_window.destroy).pack(side=tk.LEFT)
    
    def configure_sync(self):
        """Configure task sync settings"""
        config_window = tk.Toplevel(self.parent_app.root)
        config_window.title("CVM Task Sync Configuration")
        config_window.geometry("500x350")
        
        ttk.Label(config_window, text="Decentralized Task Sync & Sharing", font=("Arial", 11, "bold")).pack(pady=10)
        
        options_frame = ttk.LabelFrame(config_window, text="Settings", padding=10)
        options_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        
        ttk.Label(options_frame, text="User ID (for receiving shared tasks):").pack(anchor='w')
        user_id_entry = ttk.Entry(options_frame)
        user_id_entry.pack(fill=tk.X, pady=5)
        
        ttk.Label(options_frame, text="Share tasks with (comma-separated user IDs):").pack(anchor='w', pady=(10, 0))
        recipients_entry = ttk.Entry(options_frame)
        recipients_entry.pack(fill=tk.X, pady=5)
        
        ttk.Checkbutton(
            options_frame,
            text="Encrypt shared tasks",
            variable=tk.BooleanVar(value=True)
        ).pack(anchor='w', pady=5)
        
        button_frame = ttk.Frame(config_window)
        button_frame.pack(fill=tk.X, padx=10, pady=10)
        ttk.Button(button_frame, text="Save", command=config_window.destroy).pack(side=tk.LEFT)
    
    def configure_scheduler(self):
        """Configure scheduled automation settings"""
        config_window = tk.Toplevel(self.parent_app.root)
        config_window.title("CVM Scheduler Configuration")
        config_window.geometry("550x400")
        
        ttk.Label(config_window, text="Scheduled Task Automation on CVM", font=("Arial", 11, "bold")).pack(pady=10)
        
        options_frame = ttk.LabelFrame(config_window, text="Available Automations", padding=10)
        options_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        
        automations = [
            ("Daily deadline reminders", "0 9 * * * (9am daily)"),
            ("Weekly task cleanup", "0 0 * * 1 (Monday midnight)"),
            ("Auto-sync backup", "*/30 * * * * (every 30 minutes)"),
            ("Overdue task alerts", "0 17 * * * (5pm daily)")
        ]
        
        for automation, schedule in automations:
            frame = ttk.Frame(options_frame)
            frame.pack(fill=tk.X, pady=5)
            
            var = tk.BooleanVar()
            ttk.Checkbutton(frame, text=automation, variable=var).pack(side=tk.LEFT)
            ttk.Label(frame, text=schedule, font=("Arial", 9, "italic")).pack(side=tk.RIGHT, padx=20)
        
        button_frame = ttk.Frame(config_window)
        button_frame.pack(fill=tk.X, padx=10, pady=10)
        ttk.Button(button_frame, text="Save & Enable", command=config_window.destroy).pack(side=tk.LEFT)
    
    def show_cvm_status(self):
        """Display overall CVM status"""
        status_window = tk.Toplevel(self.parent_app.root)
        status_window.title("Phala CVM Status")
        status_window.geometry("600x400")
        
        # Status display
        text_widget = tk.Text(status_window, wrap=tk.WORD, height=20, width=70)
        text_widget.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        text_widget.config(state=tk.DISABLED)
        
        status_text = "Phala CVM Integration Status\n" + "="*50 + "\n\n"
        status_text += f"Your User ID: {self._get_user_id()}\n"
        status_text += "(Set a custom ID via 'Phala CVM → View / Change User ID')\n\n"
        
        # Check each service
        for service_type, endpoint in self.cvm_client.cvm_endpoints.items():
            status_text += f"{service_type.replace('_', ' ').title()}:\n"
            if endpoint:
                status_text += f"  Endpoint: {endpoint}\n"
                status_text += "  Status: Configured\n"
            else:
                status_text += "  Status: Not configured\n"
            status_text += "\n"
        
        status_text += "\nTo get started with Phala CVM:\n"
        status_text += "1. Deploy your CVM endpoints\n"
        status_text += "2. Configure endpoints in 'Phala CVM' menu\n"
        status_text += "3. Test connections\n"
        status_text += "4. Configure individual services\n"
        
        text_widget.config(state=tk.NORMAL)
        text_widget.insert(1.0, status_text)
        text_widget.config(state=tk.DISABLED)

    def show_user_id_dialog(self):
        """Let the user view and change their persistent CVM user ID."""
        if self.parent_app.check_existing_dialog():
            return

        win = tk.Toplevel(self.parent_app.root)
        win.title("CVM User ID")
        win.geometry("520x260")
        win.resizable(False, False)

        current_id = self._get_user_id()
        import socket, hashlib
        auto_id = hashlib.sha256(socket.gethostname().encode()).hexdigest()[:16]

        ttk.Label(win, text="Your CVM User ID", font=("Arial", 11, "bold")).pack(pady=(14, 4))
        ttk.Label(
            win,
            text="This ID tags your tasks on the CVM backend.\n"
                 "Use the same ID on every machine to access the same tasks.",
            wraplength=480, justify="left"
        ).pack(padx=16)

        frame = ttk.LabelFrame(win, text="User ID", padding=10)
        frame.pack(fill=tk.X, padx=16, pady=10)

        entry = ttk.Entry(frame, width=50)
        entry.insert(0, self.cvm_client.user_id or "")
        entry.pack(side=tk.LEFT, fill=tk.X, expand=True)

        info_frame = ttk.Frame(win)
        info_frame.pack(fill=tk.X, padx=16)
        ttk.Label(info_frame, text=f"Current active ID:  {current_id}", foreground="#1976d2").pack(anchor="w")
        ttk.Label(info_frame, text=f"This machine's auto ID:  {auto_id}", foreground="#666").pack(anchor="w")

        def save():
            new_id = entry.get().strip()
            for client in (self.cvm_client, self.backend_client,
                           self.ai_client, self.sync_client, self.scheduler_client):
                client.user_id = new_id
            self.cvm_client.save_cvm_config()
            label = new_id if new_id else f"{auto_id} (auto)"
            messagebox.showinfo("Saved", f"User ID set to:\n{label}", parent=win)
            win.destroy()

        def clear():
            entry.delete(0, tk.END)

        btn_frame = ttk.Frame(win)
        btn_frame.pack(pady=8)
        ttk.Button(btn_frame, text="Save", command=save).pack(side=tk.LEFT, padx=6)
        ttk.Button(btn_frame, text="Clear (use auto)", command=clear).pack(side=tk.LEFT, padx=6)
        ttk.Button(btn_frame, text="Cancel", command=win.destroy).pack(side=tk.LEFT, padx=6)

    # ------------------------------------------------------------------
    # Data sync helpers
    # ------------------------------------------------------------------

    def _get_user_id(self):
        """Return the persistent user ID.
        Priority: 1) custom ID saved in cvm_config.json
                  2) auto-generated from machine hostname (fallback)
        """
        saved = self.cvm_client.user_id.strip() if self.cvm_client.user_id else ""
        if saved:
            return saved
        import socket, hashlib
        return hashlib.sha256(socket.gethostname().encode()).hexdigest()[:16]

    def _local_tasks_as_dicts(self):
        """Read all tasks from the local task manager and return as list of dicts."""
        mgr = getattr(self.parent_app, 'todo_list_manager', None)
        if not mgr:
            return []
        tasks = mgr.load_tasks()   # list of (title, due_date, due_time, priority, notes)
        result = []
        for idx, t in enumerate(tasks):
            title    = t[0] if len(t) > 0 else ""
            due_date = t[1] if len(t) > 1 else ""
            due_time = t[2] if len(t) > 2 else ""
            priority = t[3] if len(t) > 3 else "1"
            notes    = t[4] if len(t) > 4 else ""
            # Stable ID: hash of title+date so repeated pushes don't duplicate
            task_id = hashlib.md5(f"{title}|{due_date}".encode()).hexdigest()[:12]
            result.append({
                "id":       task_id,
                "title":    title,
                "due_date": due_date,
                "due_time": due_time,
                "priority": priority,
                "notes":    notes,
                "completed": False,
            })
        return result

    def _apply_remote_tasks(self, remote_tasks):
        """Write remote tasks back to the local task file and refresh the UI."""
        mgr = getattr(self.parent_app, 'todo_list_manager', None)
        if not mgr:
            return 0
        converted = []
        for t in remote_tasks:
            converted.append((
                t.get("title", ""),
                t.get("due_date", ""),
                t.get("due_time", ""),
                str(t.get("priority", "1")),
                t.get("notes", "No notes"),
            ))
        mgr.save_tasks(converted, skip_mysql=True)
        self.parent_app.root.after(0, mgr.refresh_task_list)
        return len(converted)

    # ------------------------------------------------------------------
    # Push / Pull / Sync actions (called from menu)
    # ------------------------------------------------------------------

    def force_push_tasks_to_cvm(self):
        """Force-overwrite all CVM tasks with local tasks (no merge)."""
        endpoint = self.cvm_client.cvm_endpoints.get('backend', '').strip()
        if not endpoint:
            messagebox.showwarning(
                "Not Configured",
                "Backend endpoint not set.\nGo to: Phala CVM \u2192 Configure Endpoints",
                parent=self.parent_app.root
            )
            return

        tasks = self._local_tasks_as_dicts()
        if not tasks:
            if not messagebox.askyesno(
                "Force Push",
                "Local task list is empty.\nThis will DELETE all tasks on the CVM.\nContinue?",
                parent=self.parent_app.root
            ):
                return
        else:
            if not messagebox.askyesno(
                "Force Push to CVM",
                f"This will DELETE all {self._remote_task_count()} existing CVM tasks\n"
                f"and replace them with your {len(tasks)} local task(s).\n\nContinue?",
                parent=self.parent_app.root
            ):
                return

        user_id = self._get_user_id()

        def do_replace():
            success, msg = self.backend_client.replace_tasks(user_id, tasks)
            def finish():
                if success:
                    messagebox.showinfo("Force Push Successful", msg, parent=self.parent_app.root)
                else:
                    messagebox.showerror("Force Push Failed", msg, parent=self.parent_app.root)
            self.parent_app.root.after(0, finish)

        import threading
        threading.Thread(target=do_replace, daemon=True).start()

    def _remote_task_count(self):
        """Quick count of remote tasks (best-effort, returns '?' on error)."""
        try:
            import requests as req
            r = req.get(
                f"{self.cvm_client.cvm_endpoints.get('backend', '')}/tasks/retrieve",
                params={"user_id": self._get_user_id()},
                headers={"X-API-Key": self.cvm_client.api_key},
                timeout=5
            )
            if r.status_code == 200:
                return len(r.json().get("tasks", []))
        except Exception:
            pass
        return "?"

    def push_tasks_to_cvm(self):
        """Push all local tasks to the CVM backend service."""
        endpoint = self.cvm_client.cvm_endpoints.get('backend', '').strip()
        if not endpoint:
            messagebox.showwarning(
                "Not Configured",
                "Backend endpoint not set.\nGo to: Phala CVM → Configure Endpoints",
                parent=self.parent_app.root
            )
            return

        tasks = self._local_tasks_as_dicts()
        if not tasks:
            messagebox.showinfo("No Tasks", "Nothing to push — local task list is empty.",
                                parent=self.parent_app.root)
            return

        user_id = self._get_user_id()

        def do_push():
            success, msg = self.backend_client.store_tasks(user_id, tasks)
            def finish():
                if success:
                    messagebox.showinfo(
                        "Push Successful",
                        f"Pushed {len(tasks)} task(s) to CVM backend.",
                        parent=self.parent_app.root
                    )
                else:
                    messagebox.showerror("Push Failed", msg, parent=self.parent_app.root)
            self.parent_app.root.after(0, finish)

        threading.Thread(target=do_push, daemon=True).start()

    def pull_tasks_from_cvm(self):
        """Pull tasks from the CVM backend and replace the local task list."""
        endpoint = self.cvm_client.cvm_endpoints.get('backend', '').strip()
        if not endpoint:
            messagebox.showwarning(
                "Not Configured",
                "Backend endpoint not set.\nGo to: Phala CVM → Configure Endpoints",
                parent=self.parent_app.root
            )
            return

        if not messagebox.askyesno(
            "Pull from CVM",
            "This will replace your local task list with data from the CVM backend.\nContinue?",
            parent=self.parent_app.root
        ):
            return

        user_id = self._get_user_id()

        def do_pull():
            success, data = self.backend_client.retrieve_tasks(user_id)
            def finish():
                if success:
                    count = self._apply_remote_tasks(data)
                    messagebox.showinfo(
                        "Pull Successful",
                        f"Pulled {count} task(s) from CVM backend.",
                        parent=self.parent_app.root
                    )
                else:
                    messagebox.showerror("Pull Failed", str(data), parent=self.parent_app.root)
            self.parent_app.root.after(0, finish)

        threading.Thread(target=do_pull, daemon=True).start()

    def sync_tasks_with_cvm(self):
        """Two-way sync: send local tasks to CVM, get merged list back."""
        endpoint = self.cvm_client.cvm_endpoints.get('backend', '').strip()
        if not endpoint:
            messagebox.showwarning(
                "Not Configured",
                "Backend endpoint not set.\nGo to: Phala CVM → Configure Endpoints",
                parent=self.parent_app.root
            )
            return

        local_tasks = self._local_tasks_as_dicts()
        user_id = self._get_user_id()

        def do_sync():
            success, data = self.backend_client.sync_tasks(user_id, local_tasks)
            def finish():
                if success:
                    count = self._apply_remote_tasks(data)
                    messagebox.showinfo(
                        "Sync Successful",
                        f"Synced — {count} task(s) now in local list.",
                        parent=self.parent_app.root
                    )
                else:
                    messagebox.showerror("Sync Failed", str(data), parent=self.parent_app.root)
            self.parent_app.root.after(0, finish)

        threading.Thread(target=do_sync, daemon=True).start()
