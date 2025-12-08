"""
MySQL LAN Connection Module for TODO App
Contains all MySQL database functionality and LAN sharing capabilities.
"""

import json
import os
import tkinter as tk
from tkinter import ttk, messagebox
import socket
import base64
import threading
import webbrowser
from pathlib import Path

# Handle missing dependencies gracefully
try:
    import mysql.connector
    MYSQL_CONNECTOR_AVAILABLE = True
except ImportError:
    print("mysql-connector-python not available. MySQL features will be disabled.")
    MYSQL_CONNECTOR_AVAILABLE = False
    mysql = None

try:
    import keyring
    KEYRING_AVAILABLE = True
except ImportError:
    print("keyring not available. Passwords will be stored encoded instead.")
    KEYRING_AVAILABLE = False
    keyring = None


class MySQLLANManager:
    def __init__(self, parent_app):
        self.parent_app = parent_app
        
        # Check if MySQL connector is available
        if not MYSQL_CONNECTOR_AVAILABLE:
            raise ImportError("mysql-connector-python is required for MySQL functionality")
        
        # MySQL configuration file path
        self.MYSQL_CONFIG_FILE = str(Path.home()) + "/TODOapp/mysql_config.json"
        
        # MySQL sharing configuration
        self.mysql_enabled = tk.BooleanVar(value=False)
        self.mysql_config = {
            'host': 'localhost',
            'user': 'root',
            'password': '',
            'database': 'todoapp'
        }
        
        # Load existing configuration
        self.load_mysql_config()
    
    def _get_password_from_encoded(self, encoded_pw):
        """Helper to decode password from base64"""
        if encoded_pw:
            return base64.b64decode(encoded_pw).decode('utf-8')
        return ''

    def load_mysql_config(self):
        """Load MySQL configuration from file with better security"""
        try:
            if os.path.exists(self.MYSQL_CONFIG_FILE):
                with open(self.MYSQL_CONFIG_FILE, 'r') as f:
                    config = json.load(f)
                    
                    # Load basic config
                    self.mysql_config = {
                        'host': config['config']['host'],
                        'user': config['config']['user'],
                        'database': config['config']['database']
                    }
                    
                    # Get password from system keyring if available
                    if KEYRING_AVAILABLE:
                        try:
                            password = keyring.get_password("todoapp_mysql", self.mysql_config['user'])
                            if password:
                                self.mysql_config['password'] = password
                            else:
                                self.mysql_config['password'] = self._get_password_from_encoded(config['config'].get('encoded_password', ''))
                        except:
                            self.mysql_config['password'] = self._get_password_from_encoded(config['config'].get('encoded_password', ''))
                    else:
                        self.mysql_config['password'] = self._get_password_from_encoded(config['config'].get('encoded_password', ''))
                    
                    self.mysql_enabled.set(config['enabled'])
        except Exception:
            self.mysql_config = {
                'host': 'localhost',
                'user': 'root',
                'password': '',
                'database': 'todoapp'
            }

    def save_mysql_config(self):
        """Save MySQL configuration to file with better security"""
        try:
            # Try to store password in system keyring if available
            if KEYRING_AVAILABLE:
                try:
                    keyring.set_password("todoapp_mysql", self.mysql_config['user'], self.mysql_config['password'])
                    # If successful, don't store password in file
                    config_to_save = {
                        'host': self.mysql_config['host'],
                        'user': self.mysql_config['user'],
                        'database': self.mysql_config['database']
                    }
                except:
                    # If keyring fails, encode password for file storage
                    config_to_save = {
                        'host': self.mysql_config['host'],
                        'user': self.mysql_config['user'],
                        'database': self.mysql_config['database'],
                        'encoded_password': base64.b64encode(self.mysql_config['password'].encode('utf-8')).decode('utf-8')
                    }
            else:
                # Keyring not available, encode password for file storage
                config_to_save = {
                    'host': self.mysql_config['host'],
                    'user': self.mysql_config['user'],
                    'database': self.mysql_config['database'],
                    'encoded_password': base64.b64encode(self.mysql_config['password'].encode('utf-8')).decode('utf-8')
                }
            
            config = {
                'enabled': self.mysql_enabled.get(),
                'config': config_to_save
            }
            
            with open(self.MYSQL_CONFIG_FILE, 'w') as f:
                json.dump(config, f)
        except Exception:
            pass

    def check_mysql_status(self):
        """Check MySQL status and return a status code
    
        Returns:
            str: One of the following status codes:
                - "running": MySQL is running and credentials are correct
                - "access_denied": MySQL is running but credentials are wrong
                - "not_running": MySQL service exists but is not running
                - "not_installed": MySQL is not installed
        """
        try:
            # First try to connect without database to check basic connectivity
            config = self.mysql_config.copy()
            if 'database' in config:
                config.pop('database')
            
            # Add timeout to avoid hanging
            config['connect_timeout'] = 3
            
            try:
                # Try to connect with the provided credentials
                conn = mysql.connector.connect(**config)
                conn.close()
                return "running"
            except mysql.connector.Error as err:
                if err.errno == mysql.connector.errorcode.ER_ACCESS_DENIED_ERROR:
                    # MySQL is running but credentials are wrong
                    return "access_denied"
                else:
                    # Check if MySQL service is running
                    if self.is_mysql_service_running():
                        return "not_running"
                    else:
                        return "not_installed"
        except:
            # Check if MySQL service exists
            if self.is_mysql_service_running():
                return "not_running"
            else:
                return "not_installed"

    def is_mysql_service_running(self):
        """Check if MySQL service is running on Windows"""
        try:
            # Try to check service status using Windows-specific methods
            import win32serviceutil
            import win32service
            
            try:
                # Try common MySQL service names
                service_names = ["MySQL", "MySQL80", "MySQLServer", "MySQL Server"]
                
                for service_name in service_names:
                    try:
                        status = win32serviceutil.QueryServiceStatus(service_name)[1]
                        if status == win32service.SERVICE_RUNNING:
                            return True
                    except:
                        continue
                
                return False
            except:
                # Fall back to checking port 3306
                s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                s.settimeout(1)
                result = s.connect_ex(('127.0.0.1', 3306))
                s.close()
                return result == 0
        except:
            # If all else fails, try a simple connection to port 3306
            try:
                s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                s.settimeout(1)
                result = s.connect_ex(('127.0.0.1', 3306))
                s.close()
                return result == 0
            except:
                return False

    def start_mysql_service(self):
        """Attempt to start MySQL service on Windows"""
        try:
            import win32serviceutil
            
            # Try common MySQL service names
            service_names = ["MySQL", "MySQL80", "MySQLServer", "MySQL Server"]
            
            for service_name in service_names:
                try:
                    win32serviceutil.StartService(service_name)
                    # Wait a moment for the service to start
                    import time
                    time.sleep(2)
                    return True
                except:
                    continue
            
            return False
        except:
            return False

    def test_mysql_connection(self):
        """Test MySQL connection with better error handling"""
        try:
            # First test connection without database
            config = self.mysql_config.copy()
            if 'database' in config:
                db_name = config.pop('database')
            else:
                db_name = 'todoapp'  # Default database name
            
            # Add timeout to avoid hanging
            config['connect_timeout'] = 5
            
            # Try to connect
            conn = mysql.connector.connect(**config)
            
            # Check if database exists
            cursor = conn.cursor()
            cursor.execute("SHOW DATABASES")
            databases = [db[0] for db in cursor]
            
            if db_name.lower() not in [db.lower() for db in databases]:
                # Database doesn't exist - create it
                cursor.execute(f"CREATE DATABASE `{db_name}`")
                print(f"Created database: {db_name}")
                
            cursor.close()
            conn.close()
            
            # Now try connecting with the database
            self.mysql_config['database'] = db_name
            conn = mysql.connector.connect(**self.mysql_config)
            conn.close()
            
            return True
        except mysql.connector.Error as err:
            print(f"MySQL Error: {err}")
            if err.errno == mysql.connector.errorcode.ER_ACCESS_DENIED_ERROR:
                messagebox.showerror("Access Denied", 
                                   "Access denied. Please check your username and password.")
            elif err.errno == mysql.connector.errorcode.ER_BAD_DB_ERROR:
                messagebox.showerror("Database Error", 
                                   f"Database '{db_name}' does not exist and could not be created.")
            else:
                messagebox.showerror("Connection Error", f"Error: {err}")
            return False
        except Exception as e:
            print(f"Unexpected error: {e}")
            messagebox.showerror("Connection Error", f"Unexpected error: {e}")
            return False

    def setup_mysql_tables(self):
        """Create necessary tables if they don't exist - only for tasks, not character data"""
        try:
            conn = mysql.connector.connect(**self.mysql_config)
            cursor = conn.cursor()
            
            # Create tasks table
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS tasks (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    task_name VARCHAR(255) NOT NULL,
                    due_date VARCHAR(20) NOT NULL,
                    priority INT NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            
            # Create daily tasks table
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS daily_tasks (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    task_text VARCHAR(255) NOT NULL,
                    position INT NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            
            conn.commit()
            cursor.close()
            conn.close()
        except Exception as e:
            print(f"Error setting up MySQL tables: {e}")

    def sync_tasks_to_mysql(self):
        """Sync local tasks to MySQL database - only tasks, not character data"""
        if not self.mysql_enabled.get():
            return
        
        try:
            conn = mysql.connector.connect(**self.mysql_config)
            cursor = conn.cursor()
            
            # Clear existing tasks
            cursor.execute("DELETE FROM tasks")
            cursor.execute("DELETE FROM daily_tasks")
            
            # Insert regular tasks
            tasks = self.parent_app.load_tasks()
            for task in tasks:
                cursor.execute(
                    "INSERT INTO tasks (task_name, due_date, priority) VALUES (%s, %s, %s)",
                    (task[0], task[1], task[2])
                )
            
            # Insert daily tasks
            if hasattr(self.parent_app, 'daily_todo_manager') and hasattr(self.parent_app.daily_todo_manager, 'tasks'):
                for i, task in enumerate(self.parent_app.daily_todo_manager.tasks):
                    if task.winfo_exists():
                        cursor.execute(
                            "INSERT INTO daily_tasks (task_text, position) VALUES (%s, %s)",
                            (task.cget("text"), i)
                        )
            
            conn.commit()
            cursor.close()
            conn.close()
        except Exception as e:
            print(f"Error syncing to MySQL: {e}")

    def sync_tasks_from_mysql(self):
        """Sync tasks from MySQL to local storage - only tasks, not character data"""
        if not self.mysql_enabled.get():
            return
        
        try:
            conn = mysql.connector.connect(**self.mysql_config)
            cursor = conn.cursor()
            
            # Get regular tasks
            cursor.execute("SELECT task_name, due_date, priority FROM tasks ORDER BY due_date")
            tasks = cursor.fetchall()
            self.parent_app.save_tasks(tasks, skip_mysql=True)  # Skip MySQL sync to avoid loop
            
            # Get daily tasks
            cursor.execute("SELECT task_text FROM daily_tasks ORDER BY position")
            daily_tasks = cursor.fetchall()
            
            # Clear existing daily tasks if daily todo manager exists
            if hasattr(self.parent_app, 'daily_todo_manager'):
                for task in self.parent_app.daily_todo_manager.tasks[:]:
                    task.frame.destroy()
                self.parent_app.daily_todo_manager.tasks.clear()
                
                # Add daily tasks from MySQL
                for task in daily_tasks:
                    self.parent_app.daily_todo_manager.add_daily_task_from_file(task[0])
            
            cursor.close()
            conn.close()
            
            # Refresh the UI
            self.parent_app.refresh_task_list()
        except Exception as e:
            print(f"Error syncing from MySQL: {e}")
            messagebox.showerror("Sync Error", f"Failed to sync from MySQL: {str(e)}")

    def toggle_mysql(self):
        """Toggle MySQL sharing functionality with installation check"""
        # Toggle the state since it's now a command button, not a checkbutton
        self.mysql_enabled.set(not self.mysql_enabled.get())
        
        if self.mysql_enabled.get():
            # Check if MySQL is installed first
            mysql_status = self.check_mysql_status()
            
            if mysql_status == "not_installed":
                # MySQL not installed - show installation guide
                self.show_mysql_installation_guide()
                # Reset the checkbox since MySQL isn't available
                self.mysql_enabled.set(False)
                # Update the menu state
                if hasattr(self.parent_app, 'update_share_menu_state'):
                    self.parent_app.update_share_menu_state()
            elif mysql_status == "not_running":
                # MySQL installed but not running
                if messagebox.askyesno("MySQL Service", 
                                      "MySQL is installed but not running. Would you like to try starting it?"):
                    if self.start_mysql_service():
                        # Service started, now open config dialog
                        self.configure_mysql(after_config=self.test_and_enable_mysql)
                    else:
                        messagebox.showerror("Service Error", 
                                            "Could not start MySQL service. Please start it manually.")
                        self.mysql_enabled.set(False)
                        # Update the menu state
                        if hasattr(self.parent_app, 'update_share_menu_state'):
                            self.parent_app.update_share_menu_state()
                else:
                    self.mysql_enabled.set(False)
                    # Update the menu state
                    if hasattr(self.parent_app, 'update_share_menu_state'):
                        self.parent_app.update_share_menu_state()
            elif mysql_status == "access_denied":
                # MySQL is running but credentials are wrong - open config dialog
                messagebox.showinfo("MySQL Configuration", 
                                   "MySQL is running, but we need the correct credentials to connect.")
                self.configure_mysql(after_config=self.test_and_enable_mysql)
            else:
                # MySQL is installed and running with correct credentials
                self.test_and_enable_mysql()
        else:
            messagebox.showinfo("MySQL Disabled", "MySQL sharing has been disabled.")
            self.save_mysql_config()
        
        # Update the menu state to reflect the new status
        if hasattr(self.parent_app, 'update_share_menu_state'):
            self.parent_app.update_share_menu_state()

    def test_and_enable_mysql(self):
        """Test MySQL connection and enable if successful"""
        if self.test_mysql_connection():
            # Connection successful - setup tables and enable
            self.setup_mysql_tables()
            messagebox.showinfo("MySQL Enabled", "MySQL sharing has been enabled successfully.")
            self.save_mysql_config()
            # Update the menu state to reflect the new status
            if hasattr(self.parent_app, 'update_share_menu_state'):
                self.parent_app.update_share_menu_state()
            return True
        else:
            # Connection failed - disable MySQL
            self.mysql_enabled.set(False)
            self.save_mysql_config()
            # Update the menu state to reflect the new status
            if hasattr(self.parent_app, 'update_share_menu_state'):
                self.parent_app.update_share_menu_state()
            return False

    def show_mysql_installation_guide(self):
        """Show a dialog with MySQL installation instructions"""
        dialog = tk.Toplevel(self.parent_app.root)
        dialog.title("MySQL Installation Required")
        dialog.geometry("600x500")
        dialog.resizable(True, True)
        
        # Create a frame with scrollbar
        frame = ttk.Frame(dialog)
        frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        
        # Add scrollbar
        scrollbar = ttk.Scrollbar(frame)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        
        # Add text widget with installation instructions
        text = tk.Text(frame, wrap=tk.WORD, yscrollcommand=scrollbar.set)
        text.pack(fill=tk.BOTH, expand=True)
        scrollbar.config(command=text.yview)
        
        # Installation instructions
        instructions = """
MySQL Installation Guide

The MySQL sharing feature requires MySQL Server to be installed and running on your computer.
Follow these steps to install MySQL:

1. Download MySQL Installer:
   - Go to https://dev.mysql.com/downloads/installer/
   - Download the MySQL Installer for Windows

2. Run the installer:
   - Choose "Custom" installation
   - Select at minimum:
     * MySQL Server
     * MySQL Workbench (optional but recommended)
   - Click "Next" and follow the installation steps

3. Configure MySQL Server:
   - Use the recommended defaults
   - Set a root password (remember this password!)
   - Create a user account if prompted
   - Make sure "Configure MySQL Server as a Windows Service" is selected
   - Ensure "Start the MySQL Server at System Startup" is checked

4. Verify MySQL is running:
   - Open Services (search for "services" in Windows search)
   - Look for "MySQL" in the list
   - Status should show "Running"
   - If not running, right-click and select "Start"

5. Configure TODO App:
   - Return to the TODO App
   - Go to Options → Configure MySQL
   - Enter your MySQL credentials:
     * Host: localhost
     * User: root (or the user you created)
     * Password: (the password you set)
     * Database: todoapp (this will be created automatically)

6. Enable MySQL sharing:
   - Go to Options → Enable MySQL Sharing

Troubleshooting:
- If you get "Access denied" errors, check your username and password
- If you get "Can't connect to MySQL server" errors, make sure the MySQL service is running
- If you installed MySQL previously, you may need to reset your root password

Need more help? Visit:
https://dev.mysql.com/doc/mysql-installation-excerpt/8.0/en/
"""
        
        text.insert(tk.END, instructions)
        text.config(state=tk.DISABLED)  # Make text read-only
        
        # Add buttons
        button_frame = ttk.Frame(dialog)
        button_frame.pack(fill=tk.X, padx=10, pady=10)
        
        # Download button
        def open_mysql_download():
            webbrowser.open("https://dev.mysql.com/downloads/installer/")
        
        download_button = ttk.Button(button_frame, text="Download MySQL", command=open_mysql_download)
        download_button.pack(side=tk.LEFT, padx=5)
        
        # Close button
        close_button = ttk.Button(button_frame, text="Close", command=dialog.destroy)
        close_button.pack(side=tk.RIGHT, padx=5)

    def configure_mysql(self, after_config=None):
        """Open dialog to configure MySQL connection with improved validation"""
        dialog = tk.Toplevel(self.parent_app.root)
        dialog.title("MySQL Configuration")
        dialog.geometry("350x250")
        dialog.resizable(False, False)
        
        # Host
        ttk.Label(dialog, text="Host:").grid(row=0, column=0, padx=5, pady=5, sticky="w")
        host_entry = ttk.Entry(dialog, width=25)
        host_entry.grid(row=0, column=1, padx=5, pady=5)
        host_entry.insert(0, self.mysql_config.get('host', 'localhost'))
        
        # Port (new field)
        ttk.Label(dialog, text="Port:").grid(row=1, column=0, padx=5, pady=5, sticky="w")
        port_entry = ttk.Entry(dialog, width=25)
        port_entry.grid(row=1, column=1, padx=5, pady=5)
        port_entry.insert(0, self.mysql_config.get('port', '3306'))
        
        # User
        ttk.Label(dialog, text="User:").grid(row=2, column=0, padx=5, pady=5, sticky="w")
        user_entry = ttk.Entry(dialog, width=25)
        user_entry.grid(row=2, column=1, padx=5, pady=5)
        user_entry.insert(0, self.mysql_config.get('user', 'root'))
        
        # Password
        ttk.Label(dialog, text="Password:").grid(row=3, column=0, padx=5, pady=5, sticky="w")
        password_entry = ttk.Entry(dialog, width=25, show="*")
        password_entry.grid(row=3, column=1, padx=5, pady=5)
        password_entry.insert(0, self.mysql_config.get('password', ''))
        
        # Database
        ttk.Label(dialog, text="Database:").grid(row=4, column=0, padx=5, pady=5, sticky="w")
        db_entry = ttk.Entry(dialog, width=25)
        db_entry.grid(row=4, column=1, padx=5, pady=5)
        db_entry.insert(0, self.mysql_config.get('database', 'todoapp'))
        
        # Status label
        status_label = ttk.Label(dialog, text="")
        status_label.grid(row=5, column=0, columnspan=2, padx=5, pady=5)
        
        # Test connection button
        def test_connection():
            status_label.config(text="Testing connection...")
            dialog.update()
            
            try:
                # Get values from entries
                config = {
                    'host': host_entry.get(),
                    'port': int(port_entry.get()),
                    'user': user_entry.get(),
                    'password': password_entry.get(),
                    'connect_timeout': 5  # Add timeout
                }
                
                # First test connection without database
                conn = mysql.connector.connect(**config)
                
                # Check if database exists
                cursor = conn.cursor()
                cursor.execute("SHOW DATABASES")
                databases = [db[0] for db in cursor]
                
                db_name = db_entry.get()
                if db_name.lower() not in [db.lower() for db in databases]:
                    # Database doesn't exist - offer to create it
                    if messagebox.askyesno("Create Database", 
                                         f"Database '{db_name}' doesn't exist. Create it?"):
                        cursor.execute(f"CREATE DATABASE `{db_name}`")
                        status_label.config(text=f"Database '{db_name}' created successfully!")
                    else:
                        status_label.config(text="Database not created. Connection test incomplete.")
                        cursor.close()
                        conn.close()
                        return
                
                cursor.close()
                conn.close()
                
                # Now try connecting with the database
                config['database'] = db_name
                conn = mysql.connector.connect(**config)
                conn.close()
                
                status_label.config(text="Connection successful!")
            except ValueError:
                status_label.config(text="Error: Port must be a number")
            except mysql.connector.Error as err:
                if err.errno == mysql.connector.errorcode.ER_ACCESS_DENIED_ERROR:
                    status_label.config(text="Access denied. Check username and password.")
                elif err.errno == mysql.connector.errorcode.ER_BAD_DB_ERROR:
                    status_label.config(text=f"Database '{db_entry.get()}' does not exist.")
                else:
                    status_label.config(text=f"Error: {err}")
            except Exception as e:
                status_label.config(text=f"Error: {e}")
        
        ttk.Button(dialog, text="Test Connection", command=test_connection).grid(row=6, column=0, padx=5, pady=10)
        
        # Save button
        def save_config():
            try:
                # Validate port is a number
                port = int(port_entry.get())
                
                self.mysql_config = {
                    'host': host_entry.get(),
                    'port': port,
                    'user': user_entry.get(),
                    'password': password_entry.get(),
                    'database': db_entry.get()
                }
                self.save_mysql_config()
                dialog.destroy()
                
                # Call the callback function if provided
                if after_config:
                    after_config()
            except ValueError:
                status_label.config(text="Error: Port must be a number")
            
        ttk.Button(dialog, text="Save", command=save_config).grid(row=6, column=1, padx=5, pady=10)

    def share_tasks_on_lan(self):
        """Share tasks with other instances on the LAN - only tasks, not character data"""
        # Get the host IP
        hostname = socket.gethostname()
        host_ip = socket.gethostbyname(hostname)
        
        # Create a server socket
        server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        server.bind((host_ip, 0))  # Bind to any available port
        server.listen(5)
        
        # Get the port number
        _, port = server.getsockname()
        
        # Show sharing info
        share_info = f"Your tasks are being shared at:\nIP: {host_ip}\nPort: {port}\n\nWaiting for connections..."
        
        # Create a dialog to show sharing status
        dialog = tk.Toplevel(self.parent_app.root)
        dialog.title("Sharing Tasks")
        dialog.geometry("300x200")
        
        info_label = ttk.Label(dialog, text=share_info, justify=tk.LEFT)
        info_label.pack(padx=10, pady=10)
        
        status_label = ttk.Label(dialog, text="Status: Waiting for connection...")
        status_label.pack(padx=10, pady=5)
        
        # Function to stop sharing
        def stop_sharing():
            server.close()
            dialog.destroy()
        
        stop_button = ttk.Button(dialog, text="Stop Sharing", command=stop_sharing)
        stop_button.pack(padx=10, pady=10)
        
        # Function to handle client connections in a separate thread
        def handle_connections():
            try:
                while True:
                    client, addr = server.accept()
                    dialog.after(0, lambda: status_label.config(text=f"Status: Connected to {addr[0]}"))
                    
                    # Prepare data to send - ONLY tasks, not character data
                    daily_tasks = []
                    if hasattr(self.parent_app, 'daily_todo_manager') and hasattr(self.parent_app.daily_todo_manager, 'tasks'):
                        daily_tasks = [task.cget("text") for task in self.parent_app.daily_todo_manager.tasks if task.winfo_exists()]
                    
                    data = {
                        'tasks': self.parent_app.load_tasks(),
                        'daily_tasks': daily_tasks
                    }
                    
                    # Send data
                    client.send(json.dumps(data).encode())
                    client.close()
                    
                    dialog.after(0, lambda: status_label.config(text="Status: Tasks shared successfully"))
            except:
                pass  # Server closed or other error
        
        # Start the connection handler thread
        threading.Thread(target=handle_connections, daemon=True).start()

    def import_tasks_from_lan(self):
        """Import tasks from another instance on the LAN - only tasks, not character data"""
        # Ask for connection details
        dialog = tk.Toplevel(self.parent_app.root)
        dialog.title("Import Tasks")
        dialog.geometry("300x150")
        
        ttk.Label(dialog, text="Host IP:").grid(row=0, column=0, padx=5, pady=5, sticky="w")
        ip_entry = ttk.Entry(dialog, width=20)
        ip_entry.grid(row=0, column=1, padx=5, pady=5)
        
        ttk.Label(dialog, text="Port:").grid(row=1, column=0, padx=5, pady=5, sticky="w")
        port_entry = ttk.Entry(dialog, width=20)
        port_entry.grid(row=1, column=1, padx=5, pady=5)
        
        status_label = ttk.Label(dialog, text="")
        status_label.grid(row=2, column=0, columnspan=2, padx=5, pady=5)
        
        def connect_and_import():
            try:
                host = ip_entry.get()
                port = int(port_entry.get())
                
                status_label.config(text="Connecting...")
                
                # Connect to the server
                client = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                client.settimeout(5)  # 5 second timeout
                client.connect((host, port))
                
                status_label.config(text="Receiving data...")
                
                # Receive data
                data_bytes = b""
                while True:
                    chunk = client.recv(4096)
                    if not chunk:
                        break
                    data_bytes += chunk
                
                # Parse the received data
                data = json.loads(data_bytes.decode())
                
                # Ask user if they want to replace or merge tasks
                merge_choice = messagebox.askyesno(
                    "Import Tasks", 
                    "Do you want to merge the imported tasks with your existing tasks?\n\n"
                    "Yes = Merge tasks\nNo = Replace existing tasks"
                )
                
                if merge_choice:
                    # Merge tasks
                    existing_tasks = self.parent_app.load_tasks()
                    imported_tasks = data['tasks']
                    
                    # Create a set of existing task names for quick lookup
                    existing_task_names = {task[0] for task in existing_tasks}
                    
                    # Add only new tasks
                    for task in imported_tasks:
                        if task[0] not in existing_task_names:
                            existing_tasks.append(task)
                    
                    # Save merged tasks
                    self.parent_app.save_tasks(existing_tasks)
                    
                    # Merge daily tasks if daily todo manager exists
                    if hasattr(self.parent_app, 'daily_todo_manager'):
                        existing_daily_tasks = [task.cget("text") for task in self.parent_app.daily_todo_manager.tasks if task.winfo_exists()]
                        imported_daily_tasks = data['daily_tasks']
                        
                        # Add only new daily tasks
                        for task_text in imported_daily_tasks:
                            if task_text not in existing_daily_tasks:
                                self.parent_app.daily_todo_manager.add_daily_task_from_file(task_text)
                else:
                    # Replace tasks
                    self.parent_app.save_tasks(data['tasks'])
                    
                    # Clear existing daily tasks if daily todo manager exists
                    if hasattr(self.parent_app, 'daily_todo_manager'):
                        for task in self.parent_app.daily_todo_manager.tasks[:]:
                            task.frame.destroy()
                        self.parent_app.daily_todo_manager.tasks.clear()
                        
                        # Add imported daily tasks
                        for task_text in data['daily_tasks']:
                            self.parent_app.daily_todo_manager.add_daily_task_from_file(task_text)
                
                # Refresh the UI
                self.parent_app.refresh_task_list()
                if hasattr(self.parent_app, 'daily_todo_manager'):
                    self.parent_app.daily_todo_manager.save_daily_tasks()
                
                status_label.config(text="Tasks imported successfully!")
                
                # Close the connection
                client.close()
                
                # Close the dialog after a delay
                dialog.after(2000, dialog.destroy)
                
            except Exception as e:
                status_label.config(text=f"Error: {str(e)}")
        
        import_button = ttk.Button(dialog, text="Import", command=connect_and_import)
        import_button.grid(row=3, column=0, columnspan=2, padx=5, pady=10)
