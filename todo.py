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

# Import our custom modules with error handling
try:
    from ai_assistant import AIAssistant
    AI_ASSISTANT_AVAILABLE = True
except ImportError as e:
    print(f"AI Assistant not available: {e}")
    AI_ASSISTANT_AVAILABLE = False
    AIAssistant = None

try:
    from mysql_lan_manager import MySQLLANManager
    MYSQL_LAN_AVAILABLE = True
except ImportError as e:
    print(f"MySQL LAN Manager not available: {e}")
    MYSQL_LAN_AVAILABLE = False
    MySQLLANManager = None

from daily_todo_manager import DailyToDoManager
from todo_list_manager import ToDoListManager

# Import calendar view
try:
    from calendar_view import CalendarView
    CALENDAR_VIEW_AVAILABLE = True
except ImportError as e:
    print(f"Calendar View not available: {e}")
    CALENDAR_VIEW_AVAILABLE = False
    CalendarView = None

# Import updater system
try:
    from modular_updater import ModularUpdater
    MODULAR_UPDATER_AVAILABLE = True
except ImportError:
    from todo_updater import Updater
    MODULAR_UPDATER_AVAILABLE = False

if getattr(sys, "frozen", False):
    base_path = sys._MEIPASS
    # Register cleanup for MEI folder on exit
    import atexit
    import shutil
    def cleanup_mei():
        try:
            shutil.rmtree(sys._MEIPASS, ignore_errors=True)
        except:
            pass
    atexit.register(cleanup_mei)
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

        # Remove selection highlight by making it transparent/same as background
        self.style.map("Treeview",
            background=[('selected', 'white')],
            foreground=[('selected', 'black')]
        )
        
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
        """Initialize all the manager modules - deferred for fast startup"""
        # Set initial states - actual initialization will be deferred
        self.mysql_lan_manager = None
        self.mysql_available = False
        self.ai_assistant = None
        self.ai_available = False
        
        # Create fallback AI interface immediately (fast)
        if not AI_ASSISTANT_AVAILABLE:
            self.create_fallback_ai_interface()
        
        # Defer heavy initialization to after UI is shown
        self.root.after(100, self._deferred_manager_init)
        
        # Initialize Daily Todo Manager (will be created when task manager widgets are made)
        # Initialize Todo List Manager (will be created when task manager widgets are made)
    
    def _deferred_manager_init(self):
        """Initialize managers after UI is displayed for faster startup"""
        import threading
        
        def init_managers_background():
            # Initialize MySQL LAN Manager in background
            if MYSQL_LAN_AVAILABLE and MySQLLANManager:
                try:
                    self.mysql_lan_manager = MySQLLANManager(self)
                    self.mysql_available = True
                except Exception as e:
                    print(f"Failed to initialize MySQL LAN Manager: {e}")
            
            # Initialize AI Assistant in background
            if AI_ASSISTANT_AVAILABLE and AIAssistant:
                # Schedule AI init on main thread (requires Tkinter)
                self.root.after(0, self._init_ai_assistant)
        
        # Run in background thread
        threading.Thread(target=init_managers_background, daemon=True).start()
    
    def _init_ai_assistant(self):
        """Initialize AI assistant on main thread"""
        if AI_ASSISTANT_AVAILABLE and AIAssistant:
            try:
                self.ai_assistant = AIAssistant(self, self.ai_frame)
                self.ai_available = True
            except Exception as e:
                print(f"Failed to initialize AI Assistant: {e}")
                self.ai_assistant = None
                self.ai_available = False
                self.create_fallback_ai_interface()

    def create_fallback_ai_interface(self):
        """Create a fallback interface when AI is not available"""
        # Clear the AI frame
        for widget in self.ai_frame.winfo_children():
            widget.destroy()
            
        # Create informational message
        info_frame = ttk.Frame(self.ai_frame)
        info_frame.pack(fill=tk.BOTH, expand=True, padx=20, pady=20)
        
        # Title
        title_label = ttk.Label(info_frame, text="AI Assistant Not Available", 
                               font=('Helvetica', 16, 'bold'))
        title_label.pack(pady=10)
        
        # Information text
        info_text = tk.Text(info_frame, wrap=tk.WORD, height=10, state='disabled', 
                           background=self.ai_frame.cget('background'))
        info_text.pack(fill=tk.BOTH, expand=True, pady=10)
        
        # Add informational content
        info_text.config(state='normal')
        info_content = """The AI Assistant requires additional dependencies to function:

Required packages:
• requests - for communicating with Ollama
• Pillow (PIL) - for image handling
• Ollama - Local LLM runtime

To enable AI features:
1. Install the required packages:
   pip install requests pillow

2. Install Ollama:
   Download from: https://ollama.ai

3. Start Ollama and download a model:
   ollama pull deepseek-r1:14b

4. Restart the TODO app

The app will continue to work normally for task management without AI features."""
        
        info_text.insert(tk.END, info_content)
        info_text.config(state='disabled')
        
        # Add a button to check dependencies again
        check_button = ttk.Button(info_frame, text="Check Dependencies Again", 
                                 command=self.check_ai_dependencies)
        check_button.pack(pady=10)

    def check_ai_dependencies(self):
        """Check if AI dependencies are now available and reinitialize if possible"""
        try:
            # Try to reimport the modules
            import importlib
            if 'ai_assistant' in globals():
                importlib.reload(globals()['ai_assistant'])
            
            from ai_assistant import AIAssistant
            
            # Try to initialize AI assistant
            self.ai_assistant = AIAssistant(self, self.ai_frame)
            self.ai_available = True
            messagebox.showinfo("Success", "AI Assistant is now available!")
            
        except Exception as e:
            messagebox.showerror("Dependencies Missing", 
                               f"AI dependencies are still not available:\n{str(e)}")

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

        # Create a PanedWindow for resizable Daily/Todo split (40/60)
        self.task_pane = ttk.PanedWindow(parent, orient=tk.VERTICAL)
        self.task_pane.pack(fill=tk.BOTH, expand=True, padx=10, pady=(10, 0))

        # Daily To Do List Panel (40% height)
        self.daily_todo_frame = tk.LabelFrame(self.task_pane, text="Daily To Do List",
                                              font=("Helvetica", 10, "bold"), bg="#f0f0f0")

        # Initialize Daily Todo Manager
        self.daily_todo_manager = DailyToDoManager(self, self.daily_todo_frame)
        
        # Add daily frame to pane (weight=2 for 40%)
        self.task_pane.add(self.daily_todo_frame, weight=2)

        # Create notebook for view switching (List View / Calendar View) - 60% height
        self.view_notebook = ttk.Notebook(self.task_pane)
        
        # Tab 1: List View (existing todo list)
        self.todo_frame = tk.Frame(self.view_notebook, bg="#f0f0f0")
        self.view_notebook.add(self.todo_frame, text="📋 List View")
        
        # Add a label frame inside for consistent styling
        list_label_frame = tk.LabelFrame(self.todo_frame, text="To Do List",
                                         font=("Helvetica", 10, "bold"), bg="#f0f0f0")
        list_label_frame.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        # Initialize Todo List Manager with the label frame
        self.todo_list_manager = ToDoListManager(self, list_label_frame)
        
        # Tab 2: Calendar View
        self.calendar_tab_frame = tk.Frame(self.view_notebook, bg="#f0f0f0")
        self.view_notebook.add(self.calendar_tab_frame, text="📅 Calendar View")
        
        # Initialize Calendar View
        if CALENDAR_VIEW_AVAILABLE and CalendarView:
            calendar_label_frame = tk.LabelFrame(self.calendar_tab_frame, text="Calendar View",
                                                 font=("Helvetica", 10, "bold"), bg="#f0f0f0")
            calendar_label_frame.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
            self.calendar_view = CalendarView(self, calendar_label_frame)
        else:
            self.calendar_view = None
            ttk.Label(self.calendar_tab_frame, text="Calendar View not available", 
                     font=('Helvetica', 12)).pack(pady=50)
        
        # Bind tab change event to refresh calendar when switching to it
        self.view_notebook.bind('<<NotebookTabChanged>>', self.on_view_tab_changed)
        
        # Add view notebook to pane (weight=3 for 60%)
        self.task_pane.add(self.view_notebook, weight=3)
        
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

    def on_view_tab_changed(self, event):
        """Handle tab change between List View and Calendar View"""
        selected_tab = self.view_notebook.index(self.view_notebook.select())
        if selected_tab == 1 and self.calendar_view:  # Calendar View tab
            self.calendar_view.refresh()

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
        if hasattr(self, 'ai_assistant') and self.ai_assistant:
            ai_model_menu = tk.Menu(self.options_menu, tearoff=0)
            self.selected_model = tk.StringVar(value=self.ai_assistant.current_ai_model)
            
            # Use installed models if available, otherwise show configured models
            models_to_show = self.ai_assistant.installed_models if self.ai_assistant.installed_models else self.ai_assistant.available_models
            
            if models_to_show:
                for model in models_to_show:
                    ai_model_menu.add_radiobutton(
                        label=model,
                        value=model,
                        variable=self.selected_model,
                        command=lambda m=model: self.ai_assistant.change_ai_model(m)
                    )
                self.options_menu.add_cascade(label="AI Model", menu=ai_model_menu)
            else:
                # No models available - show disabled menu
                ai_model_menu.add_command(label="No models installed", state=tk.DISABLED)
                ai_model_menu.add_separator()
                ai_model_menu.add_command(label="Install a model:", state=tk.DISABLED)
                ai_model_menu.add_command(label="ollama pull deepseek-r1:14b", state=tk.DISABLED)
                self.options_menu.add_cascade(label="AI Model (No Models)", menu=ai_model_menu)

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
        
        # MySQL/LAN sharing section - only add if MySQL is available
        if self.mysql_available and hasattr(self, 'mysql_lan_manager') and self.mysql_lan_manager:
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
        else:
            # Add a disabled menu item to show MySQL is not available
            self.share_menu.add_command(label="MySQL/LAN Sharing (Not Available)", state=tk.DISABLED)
            self.share_menu.add_command(label="Install mysql-connector-python to enable", state=tk.DISABLED)
        
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
        # Only update if MySQL is available
        if not self.mysql_available or not hasattr(self, 'mysql_lan_manager') or not self.mysql_lan_manager:
            return
            
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

class LoadingScreen:
    """Loading screen to show startup progress"""
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("Loading TODO App...")
        self.root.geometry("400x200")
        self.root.resizable(False, False)
        
        # Center the window
        self.root.update_idletasks()
        screen_width = self.root.winfo_screenwidth()
        screen_height = self.root.winfo_screenheight()
        x = (screen_width - 400) // 2
        y = (screen_height - 200) // 2
        self.root.geometry(f"400x200+{x}+{y}")
        
        # Set icon if available
        try:
            self.root.iconphoto(True, tk.PhotoImage(file=ICON_PATH))
        except:
            pass
        
        # Create UI
        main_frame = ttk.Frame(self.root, padding=20)
        main_frame.pack(fill=tk.BOTH, expand=True)
        
        # Title
        title_label = ttk.Label(main_frame, text="TODO App", font=('Helvetica', 16, 'bold'))
        title_label.pack(pady=(10, 20))
        
        # Status label
        self.status_label = ttk.Label(main_frame, text="Initializing...", font=('Helvetica', 10))
        self.status_label.pack(pady=10)
        
        # Progress bar
        self.progress = ttk.Progressbar(main_frame, length=300, mode='indeterminate')
        self.progress.pack(pady=10)
        self.progress.start(10)
        
        # Detail label for sub-tasks
        self.detail_label = ttk.Label(main_frame, text="", font=('Helvetica', 8), foreground='gray')
        self.detail_label.pack(pady=5)
        
        self.root.update()
    
    def update_status(self, status, detail=""):
        """Update the loading status"""
        self.status_label.config(text=status)
        self.detail_label.config(text=detail)
        self.root.update()
    
    def close(self):
        """Close the loading screen"""
        self.progress.stop()
        self.root.destroy()

if __name__ == "__main__":
    # Show loading screen immediately
    loading = LoadingScreen()
    
    try:
        # Skip update check on startup - defer to background
        loading.update_status("Loading application...", "Initializing components")
        
        # Initialize main app immediately
        root = tk.Tk()
        root.withdraw()  # Hide main window temporarily
        
        # Set icon before creating app
        try:
            root.iconphoto(True, tk.PhotoImage(file=ICON_PATH))
        except:
            pass
        
        loading.update_status("Loading application...", "Setting up interface")
        app = TodoApp(root)
        
        loading.update_status("Loading application...", "Loading tasks")
        
        # Close loading screen and show main app
        loading.close()
        root.deiconify()  # Show main window
        
        # Check for updates in background AFTER app is visible
        def background_update_check():
            try:
                if MODULAR_UPDATER_AVAILABLE:
                    ModularUpdater(auto_check=True)
            except Exception as e:
                print(f"Background update check failed: {e}")
        
        import threading
        update_thread = threading.Thread(target=background_update_check, daemon=True)
        update_thread.start()
        
        root.mainloop()
        
    except Exception as e:
        loading.close()
        # Show error and exit
        error_root = tk.Tk()
        error_root.withdraw()
        messagebox.showerror("Startup Error", f"Failed to start TODO App:\n{str(e)}")
        error_root.destroy()
        raise