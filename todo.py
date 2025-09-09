"""
Main TODO App Application
This is the main application file that coordinates all the different modules and provides
the core application framework including settings, options, and window management.
"""

import json
import os
import tkinter as tk
from tkinter import ttk, messagebox
from datetime import datetime
from pathlib import Path
import sys
import win32com.client

# Import our custom modules
from ai_assistant import AIAssistant
from mysql_lan_manager import MySQLLANManager
from daily_todo_manager import DailyToDoManager
from todo_list_manager import ToDoListManager

# Import updater system
try:
    from modular_updater import ModularUpdater
    MODULAR_UPDATER_AVAILABLE = True
except ImportError:
    from todo_updater import Updater
    MODULAR_UPDATER_AVAILABLE = False

if getattr(sys, "frozen", False):
    base_path = sys._MEIPASS
else:
    base_path = os.path.dirname(__file__)

ICON_PATH = os.path.join(base_path, "clipboard.png")
CHARACTER_FILE = str(Path.home()) + "/TODOapp/character.txt"
VERSION_FILE = str(Path.home()) + "/TODOapp/version.txt"

class SingletonMeta(type):
    """Metaclass for singleton pattern"""
    _instances = {}
    
    def __call__(cls, *args, **kwargs):
        if cls not in cls._instances:
            cls._instances[cls] = super(SingletonMeta, cls).__call__(*args, **kwargs)
        else:
            # If instance already exists, bring window to front
            existing_instance = cls._instances[cls]
            existing_instance.root.lift()
            existing_instance.root.attributes('-topmost', True)
            existing_instance.root.after_idle(existing_instance.root.attributes, '-topmost', False)
        return cls._instances[cls]

class TodoApp(metaclass=SingletonMeta):
    def __init__(self, root):
        self.root = root
        self.root.title("TODO App")
        self.root.state('zoomed')
        
        # Configure styles
        self.style = ttk.Style()
        self.style.configure("Treeview.Heading", font=('Helvetica', 10, 'bold'))
        self.style.configure("Treeview", rowheight=25)
        
        # Character stats
        self.level = 0
        self.tasks_completed = 0
        
        # Global dialog management - only allow one dialog at a time across the entire app
        self.current_dialog = None
        
        # Add startup check before creating widgets
        self.startup_enabled = self.check_startup_status()
        
        # Add storage preference configuration - default to False
        self.store_tasks = tk.BooleanVar(value=False)  # Default to NOT storing tasks
        self.load_storage_preference()
        
        # Time format preference - default to 24-hour
        self.use_24_hour = tk.BooleanVar(value=True)  # Default to 24-hour format
        self.load_time_format_preference()
        
        # Add chatbot visibility state - default to hidden
        self.chatbot_visible = tk.BooleanVar(value=False)
        
        # Load character data
        self.load_character()
        
        # Create main interface
        self.create_main_interface()
        
        # Initialize managers
        self.initialize_managers()
        
        # Create menu system
        self.create_widgets()
        
        # Version
        self.version = "0.0.0"

        # Add this to your existing init
        self.last_refresh_date = datetime.now().date()
        
        # Start the auto-refresh timer after initializing the UI
        self.start_auto_refresh()

    def create_main_interface(self):
        """Create the main application interface"""
        self.main_pane = ttk.Panedwindow(self.root, orient=tk.HORIZONTAL)
        self.main_pane.pack(fill=tk.BOTH, expand=True)

        # Left pane: task manager
        self.task_frame = ttk.Frame(self.main_pane, width=800)
        self.main_pane.add(self.task_frame, weight=3)

        # Right pane: AI assistant - only add if visible
        self.ai_frame = ttk.Frame(self.main_pane, width=200)
        if self.chatbot_visible.get():
            self.main_pane.add(self.ai_frame, weight=2)

        # Create task manager widgets
        self.create_task_manager_widgets(self.task_frame)

    def initialize_managers(self):
        """Initialize all the manager modules"""
        # Initialize MySQL LAN Manager
        self.mysql_lan_manager = MySQLLANManager(self)
        
        # Initialize AI Assistant
        self.ai_assistant = AIAssistant(self, self.ai_frame)
        
        # Initialize Daily Todo Manager (will be created when task manager widgets are made)
        # Initialize Todo List Manager (will be created when task manager widgets are made)

    def create_task_manager_widgets(self, parent):
        """Create the main task management interface"""
        # Character stats frame
        char_frame = ttk.Frame(parent)
        char_frame.pack(pady=10, padx=10, fill=tk.X)

        # Level row
        level_frame = ttk.Frame(char_frame)
        level_frame.pack(fill=tk.X, pady=2)
        ttk.Label(level_frame, text="Level:", font=('Helvetica', 12, 'bold')).pack(side=tk.LEFT)
        self.level_label = ttk.Label(level_frame, text=str(self.level), font=('Helvetica', 12))
        self.level_label.pack(side=tk.LEFT, padx=5)

        # Add progress bar for level
        self.level_progress = ttk.Progressbar(level_frame, length=500, mode='determinate')
        self.level_progress.pack(side=tk.LEFT, padx=5)
        # Set initial progress value based on tasks completed
        self.update_level_progress()

        # Tasks Completed row
        completed_frame = ttk.Frame(char_frame)
        completed_frame.pack(fill=tk.X, pady=2)
        ttk.Label(completed_frame, text="Tasks Completed:", font=('Helvetica', 12, 'bold')).pack(side=tk.LEFT)
        self.tasks_label = ttk.Label(completed_frame, text=str(self.tasks_completed), font=('Helvetica', 12))
        self.tasks_label.pack(side=tk.LEFT, padx=5)

        # Tasks Remaining row
        remaining_frame = ttk.Frame(char_frame)
        remaining_frame.pack(fill=tk.X, pady=2)
        ttk.Label(remaining_frame, text="Tasks Remaining:", font=('Helvetica', 12, 'bold')).pack(side=tk.LEFT)
        self.remaining_label = ttk.Label(remaining_frame, text="0", font=('Helvetica', 12))
        self.remaining_label.pack(side=tk.LEFT, padx=5)

        # Daily To Do List Panel
        self.daily_todo_frame = tk.LabelFrame(self.task_frame, text="Daily To Do List", font=("Helvetica", 10, "bold"), bg="#f0f0f0")
        self.daily_todo_frame.pack(fill=tk.X, padx=10, pady=(10, 0))

        # Initialize Daily Todo Manager
        self.daily_todo_manager = DailyToDoManager(self, self.daily_todo_frame)

        # Task list
        self.todo_frame = tk.LabelFrame(parent, text="To Do List",
                                       font=("Helvetica", 10, "bold"),
                                       bg="#f0f0f0")
        self.todo_frame.pack(fill=tk.BOTH, padx=10, pady=(10, 0), expand=True)

        # Initialize Todo List Manager
        self.todo_list_manager = ToDoListManager(self, self.todo_frame)
        
        # Load and display tasks immediately after initialization
        self.todo_list_manager.refresh_task_list()

        # Version and controls frame
        version_frame = ttk.Frame(parent)
        version_frame.pack(side=tk.BOTTOM, fill=tk.X, padx=10, pady=2)
        
        # Chatbot toggle button on the left side of version frame
        self.chatbot_toggle_btn = ttk.Button(
            version_frame,
            text="Hide AI Assistant" if self.chatbot_visible.get() else "Show AI Assistant",
            command=self.toggle_chatbot
        )
        self.chatbot_toggle_btn.pack(side=tk.LEFT)
        
        ttk.Label(
            version_frame,
            text=f"v {self.load_app_version()}",
            font=('Helvetica', 8),
            foreground="gray50",
            anchor="e"
        ).pack(side=tk.RIGHT, fill=tk.X, expand=True)

        # Time display aligned to the right
        time_frame = ttk.Frame(parent)
        time_frame.pack(side=tk.RIGHT, padx=10)
        self.time_label = ttk.Label(time_frame, font=('Helvetica', 12, 'bold'))
        self.time_label.pack(side=tk.RIGHT, padx=10)
        self.update_time()  # start the clock

    def load_app_version(self):
        """Load application version from file"""
        try:
            with open(VERSION_FILE, "r") as f:
                return f.read().strip()
        except FileNotFoundError:
            return "0.0.0 (dev)"

    def toggle_chatbot(self):
        """Toggle the visibility of the AI assistant panel"""
        if self.chatbot_visible.get():
            # Hide the chatbot
            self.main_pane.forget(self.ai_frame)
            self.chatbot_visible.set(False)
            self.chatbot_toggle_btn.config(text="Show AI Assistant")
        else:
            # Show the chatbot
            self.main_pane.add(self.ai_frame, weight=2)
            self.chatbot_visible.set(True)
            self.chatbot_toggle_btn.config(text="Hide AI Assistant")

    def update_time(self):
        """Update the time display and daily task colors"""
        current_time = datetime.now().strftime("%m-%d-%Y %H:%M:%S")
        self.time_label.config(text=current_time)
        
        # Update daily task colors based on current time
        if hasattr(self, 'daily_todo_manager'):
            self.daily_todo_manager.update_daily_task_colors()
        
        self.root.after(1000, self.update_time)  # Update every second

    def load_character(self):
        """Load character statistics from file"""
        if os.path.exists(CHARACTER_FILE):
            with open(CHARACTER_FILE, "r") as f:
                parts = f.read().strip().split(" | ")
                if len(parts) == 2:
                    self.level = int(parts[0])
                    self.tasks_completed = int(parts[1])
        self.update_character_labels()

    def save_character(self):
        """Save character statistics to file"""
        with open(CHARACTER_FILE, "w") as f:
            f.write(f"{self.level} | {self.tasks_completed}")

    def update_character_labels(self):
        """Update character statistic labels"""
        if hasattr(self, 'level_label'):
            self.level_label.config(text=str(self.level))
        if hasattr(self, 'tasks_label'):
            self.tasks_label.config(text=str(self.tasks_completed))
        self.update_level_progress()  # Update progress bar
    
    def update_level_progress(self):
        """Update the level progress bar based on tasks completed"""
        # Calculate progress to next level (every 5 tasks)
        tasks_to_next_level = 5
        progress_value = (self.tasks_completed % tasks_to_next_level) * (100 / tasks_to_next_level)
        if hasattr(self, 'level_progress'):
            self.level_progress.config(value=progress_value)

    def parse_date(self, raw_date):
        """Parse date string to standardized format"""
        import re
        digits = re.sub(r"\D", "", raw_date)
        if len(digits) not in [6, 8]:
            return None
        
        mm = digits[:2].zfill(2)
        dd = digits[2:4].zfill(2) if len(digits) >=4 else "01"
        yy = digits[4:6] if len(digits) ==6 else digits[6:8]
        yyyy = f"20{yy}" if len(digits) ==6 else digits[4:8]
        
        try:
            datetime.strptime(f"{mm}-{dd}-{yyyy}", "%m-%d-%Y")
            return f"{mm}-{dd}-{yyyy}"
        except ValueError:
            return None

    def add_task(self, task, date, priority, notes=""):
        """Add a task using the todo list manager"""
        if hasattr(self, 'todo_list_manager'):
            self.todo_list_manager.add_task(task, date, priority, notes)

    def load_tasks(self):
        """Load tasks using the todo list manager"""
        if hasattr(self, 'todo_list_manager'):
            return self.todo_list_manager.load_tasks()
        return []

    def save_tasks(self, tasks, skip_mysql=False):
        """Save tasks using the todo list manager"""
        if hasattr(self, 'todo_list_manager'):
            self.todo_list_manager.save_tasks(tasks, skip_mysql)

    def refresh_task_list(self):
        """Refresh the task list display"""
        if hasattr(self, 'todo_list_manager'):
            self.todo_list_manager.refresh_task_list()

    def load_storage_preference(self):
        """Load the user's preference for storing tasks"""
        storage_file = str(Path.home()) + "/TODOapp/storage_pref.txt"
        try:
            with open(storage_file, "r") as f:
                pref = f.read().strip()
                self.store_tasks.set(pref == "True")
        except FileNotFoundError:
            # Default to False if file doesn't exist
            self.store_tasks.set(False)
            # Save the default preference
            self.save_storage_preference()

    def save_storage_preference(self):
        """Save the user's preference for storing tasks"""
        storage_file = str(Path.home()) + "/TODOapp/storage_pref.txt"
        with open(storage_file, "w") as f:
            f.write(str(self.store_tasks.get()))

    def load_time_format_preference(self):
        """Load the user's preference for time format"""
        time_format_file = str(Path.home()) + "/TODOapp/time_format_pref.txt"
        try:
            with open(time_format_file, "r") as f:
                pref = f.read().strip()
                self.use_24_hour.set(pref == "True")
        except FileNotFoundError:
            # Default to 24-hour if file doesn't exist
            self.use_24_hour.set(True)
            # Save the default preference
            self.save_time_format_preference()

    def save_time_format_preference(self):
        """Save the user's preference for time format"""
        time_format_file = str(Path.home()) + "/TODOapp/time_format_pref.txt"
        with open(time_format_file, "w") as f:
            f.write(str(self.use_24_hour.get()))

    def toggle_time_format(self):
        """Toggle between 24-hour and 12-hour time format"""
        self.save_time_format_preference()
        format_type = "24-hour" if self.use_24_hour.get() else "12-hour"
        
        # Refresh daily task display to show new time format
        if hasattr(self, 'daily_todo_manager'):
            self.daily_todo_manager.refresh_daily_task_display()
        
        messagebox.showinfo(
            "Time Format Changed", 
            f"Time format has been changed to {format_type}.\n"
            "This will apply to new tasks and task editing."
        )

    def toggle_storage(self):
        """Toggle whether tasks are stored persistently"""
        self.save_storage_preference()
        if not self.store_tasks.get():
            messagebox.showinfo(
                "Storage Disabled", 
                "Tasks will no longer be saved between sessions.\n"
                "Existing saved tasks will remain until you restart the app."
            )
        else:
            # Save current tasks immediately when enabling storage
            self.save_tasks(self.load_tasks())
            if hasattr(self, 'daily_todo_manager'):
                self.daily_todo_manager.save_daily_tasks()
            messagebox.showinfo(
                "Storage Enabled", 
                "Tasks will now be saved between sessions."
            )

    def check_startup_status(self):
        """Check if the app is set to run at startup"""
        startup_path = self.get_startup_path()
        return startup_path.exists()

    def get_startup_path(self):
        """Get the path to the startup shortcut"""
        startup_folder = Path(os.path.expandvars("%APPDATA%\\Microsoft\\Windows\\Start Menu\\Programs\\Startup"))
        return startup_folder / "TODOApp.lnk"

    def toggle_startup(self):
        """Toggle startup status"""
        if self.startup_var.get():
            self.enable_startup()
        else:
            self.disable_startup()

    def enable_startup(self):
        """Enable startup with Windows"""
        try:
            # Get the path of the current executable
            if getattr(sys, 'frozen', False):
                # Running as compiled executable
                app_path = sys.executable
            else:
                # Running as script - create a batch file that runs the script directly
                script_path = os.path.abspath(sys.argv[0])
                app_dir = os.path.dirname(script_path)
                
                # Create a batch file to run Python directly
                batch_path = os.path.join(app_dir, "run_todo.bat")
                with open(batch_path, "w") as f:
                    f.write(f'@echo off\n"{sys.executable}" "{script_path}"\n')
                
                app_path = batch_path

            startup_path = self.get_startup_path()

            # Create shortcut
            shell = win32com.client.Dispatch("WScript.Shell")
            shortcut = shell.CreateShortCut(str(startup_path))
            shortcut.Targetpath = app_path
            shortcut.WorkingDirectory = os.path.dirname(app_path)
            shortcut.Description = "TODO App"
            shortcut.save()

            messagebox.showinfo("Success", "TODO App will now start with Windows")
        except Exception as e:
            messagebox.showerror("Error", f"Failed to enable startup: {str(e)}")
            self.startup_var.set(False)

    def disable_startup(self):
        """Disable startup with Windows"""
        try:
            startup_path = self.get_startup_path()
            if startup_path.exists():
                startup_path.unlink()
            messagebox.showinfo("Success", "TODO App will no longer start with Windows")
        except Exception as e:
            messagebox.showerror("Error", f"Failed to disable startup: {str(e)}")
            self.startup_var.set(True)

    def start_auto_refresh(self):
        """Start the auto-refresh timer"""
        # Check tasks every minute (60000 milliseconds)
        self.check_tasks_status()
        self.root.after(60000, self.start_auto_refresh)

    def check_tasks_status(self):
        """Check if tasks need to be refreshed"""
        current_date = datetime.now().date()
        
        # Refresh if:
        # 1. The date has changed (midnight crossed)
        # 2. Or if there are tasks in the list (to update overdue status)
        if (current_date != self.last_refresh_date or 
            (hasattr(self, 'todo_list_manager') and len(self.todo_list_manager.tree.get_children()) > 0)):
            
            # Check for daily task reset if date changed
            if current_date != self.last_refresh_date and hasattr(self, 'daily_todo_manager'):
                self.daily_todo_manager.check_and_reset_daily_tasks()
                self.daily_todo_manager.load_daily_tasks()
            
            self.refresh_task_list()
            self.last_refresh_date = current_date

    def create_widgets(self):
        """Create the main menu system"""
        menubar = tk.Menu(self.root)
        self.options_menu = tk.Menu(menubar, tearoff=0)  # Make this an instance variable

        # AI Model submenu
        if hasattr(self, 'ai_assistant'):
            ai_model_menu = tk.Menu(self.options_menu, tearoff=0)
            self.selected_model = tk.StringVar(value=self.ai_assistant.current_ai_model)
            for model in self.ai_assistant.available_models:
                ai_model_menu.add_radiobutton(
                    label=model,
                    value=model,
                    variable=self.selected_model,
                    command=lambda m=model: self.ai_assistant.change_ai_model(m)
                )
            self.options_menu.add_cascade(label="AI Model", menu=ai_model_menu)

        # Startup checkbox
        self.startup_var = tk.BooleanVar(value=self.startup_enabled)
        self.options_menu.add_checkbutton(
            label="Start with Windows",
            variable=self.startup_var,
            command=self.toggle_startup
        )

        # Add storage preference checkbox
        self.options_menu.add_checkbutton(
            label="Store Tasks Persistently",
            variable=self.store_tasks,
            command=self.toggle_storage
        )
        
        # Add time format preference checkbox
        self.options_menu.add_checkbutton(
            label="Use 24-Hour Time Format",
            variable=self.use_24_hour,
            command=self.toggle_time_format
        )
        
        # Create Share menu with all sharing options
        self.share_menu = tk.Menu(menubar, tearoff=0)
        
        # LAN sharing section
        self.share_menu.add_command(label="Share Tasks on LAN", command=self.mysql_lan_manager.share_tasks_on_lan)
        self.share_menu.add_command(label="Import Tasks from LAN", command=self.mysql_lan_manager.import_tasks_from_lan)
        
        # MySQL sharing section
        self.share_menu.add_separator()
        self.mysql_menu_index = self.share_menu.index(tk.END) + 1  # Store the index of the MySQL menu item
        self.share_menu.add_command(
            label="Enable MySQL Sharing",
            command=self.mysql_lan_manager.toggle_mysql
        )
        self.share_menu.add_command(label="Configure MySQL Connection", command=self.mysql_lan_manager.configure_mysql)
        
        # Create Help menu with updates
        help_menu = tk.Menu(menubar, tearoff=0)
        help_menu.add_command(label="Check for Updates", command=self.check_for_updates)
        help_menu.add_separator()
        help_menu.add_command(label="About", command=self.show_about)
        
        # Add menus to menubar
        menubar.add_cascade(label="Options", menu=self.options_menu)
        menubar.add_cascade(label="Share", menu=self.share_menu)
        menubar.add_cascade(label="Help", menu=help_menu)
        self.root.config(menu=menubar)
        
        # Update menu states based on current settings
        self.update_share_menu_state()

    def update_share_menu_state(self):
        """Update menu items based on MySQL enabled status"""
        # Enable/disable LAN sharing options based on MySQL status
        if self.mysql_lan_manager.mysql_enabled.get():
            # Enable LAN sharing options when MySQL is enabled
            self.share_menu.entryconfigure("Share Tasks on LAN", state=tk.NORMAL)
            self.share_menu.entryconfigure("Import Tasks from LAN", state=tk.NORMAL)
            # Update the menu text to show disable option using index
            self.share_menu.entryconfigure(self.mysql_menu_index, label="Disable MySQL Sharing")
        else:
            # Disable LAN sharing options when MySQL is disabled
            self.share_menu.entryconfigure("Share Tasks on LAN", state=tk.DISABLED)
            self.share_menu.entryconfigure("Import Tasks from LAN", state=tk.DISABLED)
            # Update the menu text to show enable option using index
            self.share_menu.entryconfigure(self.mysql_menu_index, label="Enable MySQL Sharing")
        
        # Always keep Configure MySQL Connection enabled
        self.share_menu.entryconfigure("Configure MySQL Connection", state=tk.NORMAL)

    def check_for_updates(self):
        """Check for updates using the appropriate updater"""
        try:
            if MODULAR_UPDATER_AVAILABLE:
                # Create a fresh updater instance for manual check
                updater = ModularUpdater(auto_check=False)
                # Manually trigger the update check
                updater.check_for_updates()
            else:
                # Fall back to the simple updater
                updater = Updater()
                messagebox.showinfo("Update Check", "Using legacy updater. Check console for update status.")
                
        except Exception as e:
            messagebox.showerror("Update Error", f"Failed to check for updates: {e}")

    def show_about(self):
        """Show application information"""
        try:
            with open(VERSION_FILE, 'r') as f:
                version = f.read().strip()
        except:
            version = "Unknown"
        
        about_text = f"""TODO App
Version: {version}
        
A comprehensive task management application with:
• Task creation and management
• AI assistant integration
• LAN/MySQL sharing capabilities
• Automatic updates
• Level progression system

Built with Python and Tkinter"""
        
        messagebox.showinfo("About TODO App", about_text)

    def check_existing_dialog(self):
        """Check if a dialog is already open and bring it to front if so"""
        if self.current_dialog and self.current_dialog.winfo_exists():
            # Bring dialog to front and ensure it stays on top
            self.current_dialog.lift()
            self.current_dialog.attributes('-topmost', True)
            self.current_dialog.focus_force()
            # Remove topmost after a brief moment to allow normal window behavior
            self.current_dialog.after(100, lambda: self.current_dialog.attributes('-topmost', False))
            return True
        # Clean up stale reference
        self.current_dialog = None
        return False
    
    def register_dialog(self, dialog):
        """Register a new dialog and set up cleanup"""
        self.current_dialog = dialog
        
        # Make dialog modal and ensure it stays in front
        dialog.transient(self.root)  # Make dialog transient to main window
        dialog.grab_set()  # Make dialog modal
        dialog.lift()  # Bring to front
        dialog.attributes('-topmost', True)  # Ensure it's on top
        dialog.focus_force()  # Give it focus
        
        # Remove topmost after a brief moment to allow normal window behavior
        dialog.after(100, lambda: dialog.attributes('-topmost', False))
        
        # Center dialog on main window
        dialog.update_idletasks()
        x = self.root.winfo_x() + (self.root.winfo_width() // 2) - (dialog.winfo_width() // 2)
        y = self.root.winfo_y() + (self.root.winfo_height() // 2) - (dialog.winfo_height() // 2)
        dialog.geometry(f"+{x}+{y}")
        
        # Store original destroy method
        original_destroy = dialog.destroy
        
        def cleanup_and_destroy():
            if self.current_dialog == dialog:
                self.current_dialog = None
            try:
                dialog.grab_release()  # Release modal grab
            except:
                pass  # Dialog might already be destroyed
            original_destroy()
        
        # Override destroy method
        dialog.destroy = cleanup_and_destroy
        
        # Also handle window close event
        dialog.protocol("WM_DELETE_WINDOW", cleanup_and_destroy)

if __name__ == "__main__":
    # Check for updates before launching the main app
    try:
        if MODULAR_UPDATER_AVAILABLE:
            # Use modular updater for better update experience
            updater = ModularUpdater(auto_check=True)
            # Update check is done automatically in constructor
        else:
            # Fall back to simple updater
            import todo_updater
            todo_updater.Updater()
    except Exception as e:
        print(f"Update check failed: {e}")
        
    # Continue with normal app startup
    root = tk.Tk()
    app = TodoApp(root)
    app.root.iconphoto(True, tk.PhotoImage(file=ICON_PATH))
    root.mainloop()