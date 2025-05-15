import json
import os
import re
import tkinter as tk
import requests
import threading
from tkinter.scrolledtext import ScrolledText
from tkinter import ttk, messagebox, simpledialog, filedialog
from tkcalendar import DateEntry
from tkinter.font import Font
from datetime import datetime
from pathlib import Path
from PIL import Image, ImageTk
import shutil
import mimetypes
import sys
import win32com.client
import mysql.connector
import socket
import base64
import keyring

DAILY_TASK_FILE = str(Path.home()) + "/TODOapp/dailytask.txt"
TODO_FILE = str(Path.home()) + "/TODOapp/todo.txt"
CHARACTER_FILE = str(Path.home()) + "/TODOapp/character.txt"
VERSION_FILE = str(Path.home()) + "/TODOapp/version.txt"
MYSQL_CONFIG_FILE = str(Path.home()) + "/TODOapp/mysql_config.json"

class TodoApp:
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
        
        # Add AI model configuration
        self.current_ai_model = "deepseek-r1:14b"  # Default model
        self.available_models = [
            "deepseek-r1:14b",
        ]

        # Add startup check before creating widgets
        self.startup_enabled = self.check_startup_status()
        
        # Add storage preference configuration - default to False
        self.store_tasks = tk.BooleanVar(value=False)  # Default to NOT storing tasks
        self.load_storage_preference()
        
        # MySQL sharing configuration
        self.mysql_enabled = tk.BooleanVar(value=False)
        self.mysql_config = {
            'host': 'localhost',
            'user': 'root',
            'password': '',
            'database': 'todoapp'
        }
        self.load_mysql_config()
        
        # Create widgets
        self.create_widgets()

        self.main_pane = ttk.Panedwindow(self.root, orient=tk.HORIZONTAL)
        self.main_pane.pack(fill=tk.BOTH, expand=True)

        # Left pane: task manager
        self.task_frame = ttk.Frame(self.main_pane, width=800)
        self.main_pane.add(self.task_frame, weight=3)

        # Right pane: AI assistant
        self.ai_frame = ttk.Frame(self.main_pane, width=200)
        self.main_pane.add(self.ai_frame, weight=2)

        # Populate each pane
        self.create_task_manager_widgets(self.task_frame)
        self.create_ai_widgets(self.ai_frame)


        self.load_character()
        self.refresh_task_list()

        # Version
        self.version = "0.0.0"

        # Add this to your existing init
        self.upload_folder = str(Path.home()) + "/TODOapp/uploads/"
        Path(self.upload_folder).mkdir(parents=True, exist_ok=True)

        # Add to your existing init
        self.last_refresh_date = datetime.now().date()
        
        # Start the auto-refresh timer after initializing the UI
        self.start_auto_refresh()

    def load_app_version(self):
        try:
            with open(VERSION_FILE, "r") as f:
                return f.read().strip()
        except FileNotFoundError:
            return "0.0.0 (dev)"

    def create_widgets(self):
        menubar = tk.Menu(self.root)
        options_menu = tk.Menu(menubar, tearoff=0)

        # AI Model submenu
        ai_model_menu = tk.Menu(options_menu, tearoff=0)
        self.selected_model = tk.StringVar(value=self.current_ai_model)
        for model in self.available_models:
            ai_model_menu.add_radiobutton(
                label=model,
                value=model,
                variable=self.selected_model,
                command=lambda m=model: self.change_ai_model(m)
            )
        options_menu.add_cascade(label="AI Model", menu=ai_model_menu)

        # Startup checkbox
        self.startup_var = tk.BooleanVar(value=self.startup_enabled)
        options_menu.add_checkbutton(
            label="Start with Windows",
            variable=self.startup_var,
            command=self.toggle_startup
        )

        # Add storage preference checkbox
        options_menu.add_checkbutton(
            label="Store Tasks Persistently",
            variable=self.store_tasks,
            command=self.toggle_storage
        )
        
        # Add MySQL sharing option
        options_menu.add_checkbutton(
            label="Enable MySQL Sharing",
            variable=self.mysql_enabled,
            command=self.toggle_mysql
        )
        options_menu.add_command(label="Configure MySQL", command=self.configure_mysql)
        
        # Add LAN sharing options
        share_menu = tk.Menu(menubar, tearoff=0)
        share_menu.add_command(label="Share Tasks on LAN", command=self.share_tasks_on_lan)
        share_menu.add_command(label="Import Tasks from LAN", command=self.import_tasks_from_lan)
        
        menubar.add_cascade(label="Options", menu=options_menu)
        menubar.add_cascade(label="Share", menu=share_menu)
        self.root.config(menu=menubar)

    def create_task_manager_widgets(self, parent):
        # Character stats frame
        char_frame = ttk.Frame(parent)
        char_frame.pack(pady=10, padx=10, fill=tk.X)

        # Level row
        level_frame = ttk.Frame(char_frame)
        level_frame.pack(fill=tk.X, pady=2)
        ttk.Label(level_frame, text="Level:", font=('Helvetica', 12, 'bold')).pack(side=tk.LEFT)
        self.level_label = ttk.Label(level_frame, text=str(self.level), font=('Helvetica', 12))
        self.level_label.pack(side=tk.LEFT, padx=5)

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

        self.button_frame = tk.Frame(self.daily_todo_frame, bg="#f0f0f0")
        self.button_frame.pack(side=tk.TOP, fill=tk.X, padx=2, pady=2)

        self.add_button = tk.Button(self.button_frame, text="+", width=2, command=self.add_daily_task)
        self.add_button.pack(side=tk.LEFT, padx=2)

        # Remove these buttons since each task will have its own
        # self.remove_button = tk.Button(self.button_frame, text="-", width=2, command=self.remove_daily_task)
        # self.remove_button.pack(side=tk.LEFT, padx=2)
        # self.edit_button = tk.Button(self.button_frame, text="✎", width=2, command=self.edit_daily_task)
        # self.edit_button.pack(side=tk.LEFT, padx=2)

        # Add a frame instead of listbox for better layout control
        self.daily_todo_listbox = tk.Frame(self.daily_todo_frame)
        self.daily_todo_listbox.pack(fill=tk.BOTH, padx=5, pady=5)

        self.load_daily_tasks()

        # Task list
        self.tree = ttk.Treeview(parent, columns=("Task", "Due Date", "Priority"), show="headings")
        self.tree.heading("Task", text="Task", command=lambda: self.sort_column("Task", False))
        self.tree.heading("Due Date", text="Due Date", command=lambda: self.sort_column("Due Date", False))
        self.tree.heading("Priority", text="Priority", command=lambda: self.sort_column("Priority", False))
        self.tree.column("Task", width=350, minwidth=100, stretch=True)
        self.tree.column("Due Date", width=250, minwidth=80, stretch=False)
        self.tree.column("Priority", width=200, minwidth=40, stretch=False)
        self.tree.pack(pady=10, padx=10, fill=tk.BOTH, expand=True)

        # Controls frame
        control_frame = ttk.Frame(parent)
        control_frame.pack(pady=10, fill=tk.X)
        ttk.Button(control_frame, text="Add Task", command=self.add_task_dialog).pack(side=tk.LEFT, padx=5)
        ttk.Button(control_frame, text="Finish Task", command=self.remove_task).pack(side=tk.LEFT, padx=5)
        ttk.Button(control_frame, text="Delete Task", command=self.delete_task).pack(side=tk.LEFT, padx=5)
        ttk.Button(control_frame, text="Edit Task", command=self.edit_task).pack(side=tk.LEFT, padx=5)
        ttk.Button(control_frame, text="Character Info", command=self.show_character).pack(side=tk.LEFT, padx=5)

        # Time display aligned to the right
        self.time_label = ttk.Label(control_frame, font=('Helvetica', 12, 'bold'))
        self.time_label.pack(side=tk.RIGHT, padx=10)
        self.update_time()  # start the clock

        # Version label at bottom right
        version_frame = ttk.Frame(parent)
        version_frame.pack(side=tk.BOTTOM, fill=tk.X, padx=10, pady=2)
        ttk.Label(
            version_frame,
            text=f"v {self.load_app_version()}",
            font=('Helvetica', 8),
            foreground="gray50",
            anchor="e"
        ).pack(side=tk.RIGHT, fill=tk.X, expand=True)

    def create_ai_widgets(self, parent):
        # Chat history
        self.chat_history = ScrolledText(parent, wrap=tk.WORD, state='disabled')
        self.chat_history.pack(padx=10, pady=10, fill=tk.BOTH, expand=True)

        # Input row
        input_frame = ttk.Frame(parent)
        input_frame.pack(padx=10, pady=10, fill=tk.X)
        self.upload_button = ttk.Button(input_frame, text="📎", width=3, command=self.upload_file)
        self.upload_button.pack(side=tk.LEFT, padx=5)
        self.user_input = ttk.Entry(input_frame)
        self.user_input.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=5)
        self.user_input.bind("<Return>", lambda e: self.send_to_ai())
        self.send_button = ttk.Button(input_frame, text="Send", command=self.send_to_ai)
        self.send_button.pack(side=tk.RIGHT)

        # Markdown tags
        for tag, cfg in [
            ("bold",    {'font':('Helvetica',10,'bold')}),
            ("italic",  {'font':('Helvetica',10,'italic')}),
            ("header",  {'font':('Helvetica',12,'bold')}),
            ("list",    {'lmargin2':20,'spacing3':3}),
            ("code",    {'background':"#f0f0f0",'relief':'groove'}),
            ("think",   {'foreground':"gray50",'spacing1':5,'spacing3':5}),
        ]:
            self.chat_history.tag_config(tag, **cfg)

        # Initial greeting
        self.update_chat_history("AI: Hello! I'm your personal task assistant. How can I help you today?\n")

    def update_time(self):
        current_time = datetime.now().strftime("%m-%d-%Y %H:%M:%S")
        self.time_label.config(text=current_time)
        self.root.after(1000, self.update_time)  # Update every second

    def sort_column(self, column, reverse):
        # Get current tasks
        tasks = [(self.tree.set(child, column), child) for child in self.tree.get_children('')]
        
        # Custom sorting
        if column == "Due Date":
            tasks.sort(key=lambda x: datetime.strptime(x[0], "%m-%d-%Y"), reverse=reverse)
        elif column == "Priority":
            tasks.sort(key=lambda x: int(x[0]), reverse=reverse)
        else:
            tasks.sort(reverse=reverse)

        # Rearrange items in sorted positions
        for index, (val, child) in enumerate(tasks):
            self.tree.move(child, '', index)

        # Reverse sort next time
        self.tree.heading(column, command=lambda: self.sort_column(column, not reverse))

    def load_character(self):
        if os.path.exists(CHARACTER_FILE):
            with open(CHARACTER_FILE, "r") as f:
                parts = f.read().strip().split(" | ")
                if len(parts) == 2:
                    self.level = int(parts[0])
                    self.tasks_completed = int(parts[1])
        self.update_character_labels()

    def save_character(self):
        with open(CHARACTER_FILE, "w") as f:
            f.write(f"{self.level} | {self.tasks_completed}")

    def update_character_labels(self):
        self.level_label.config(text=str(self.level))
        self.tasks_label.config(text=str(self.tasks_completed))

    def parse_date(self, raw_date):
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

    def add_task_dialog(self):
        dialog = tk.Toplevel(self.root)
        dialog.title("Add New Task")
        
        ttk.Label(dialog, text="Task:").grid(row=0, column=0, padx=5, pady=5)
        task_entry = ttk.Entry(dialog, width=40)
        task_entry.grid(row=0, column=1, padx=5, pady=5)
        
        ttk.Label(dialog, text="Due Date:").grid(row=1, column=0, padx=5, pady=5)
        date_entry = DateEntry(dialog,
                             date_pattern="mm-dd-yyyy",
                             background="darkblue",
                             foreground="white",
                             borderwidth=2)
        date_entry.grid(row=1, column=1, padx=5, pady=5)
        
        ttk.Label(dialog, text="Priority (1-5):").grid(row=2, column=0, padx=5, pady=5)
        priority_entry = ttk.Spinbox(dialog, from_=1, to=5)
        priority_entry.grid(row=2, column=1, padx=5, pady=5)
        
        def validate_and_add():
            date = self.parse_date(date_entry.get())
            if not date:
                messagebox.showerror("Error", "Invalid date format")
                return
            
            try:
                priority = int(priority_entry.get())
                if not 1 <= priority <= 5:
                    raise ValueError
            except ValueError:
                messagebox.showerror("Error", "Priority must be 1-5")
                return
            
            self.add_task(task_entry.get(), date, priority)
            dialog.destroy()

        ttk.Button(dialog, text="Add", command=validate_and_add).grid(row=3, columnspan=2, pady=10)

    def add_task(self, task, date, priority):
        tasks = self.load_tasks()
        tasks.append((task, date, priority))
        tasks = sorted(tasks, key=lambda x: (datetime.strptime(x[1], "%m-%d-%Y"), -int(x[2])))
        self.save_tasks(tasks)
        self.refresh_task_list()

    def remove_task(self):
        selected = self.tree.selection()
        if not selected:
            messagebox.showwarning("Warning", "Please select a task to remove")
            return
        
        task_values = self.tree.item(selected[0], 'values')
        task_to_remove = (task_values[0], task_values[1], task_values[2])
        
        tasks = self.load_tasks()
        try:
            index = tasks.index(task_to_remove)
        except ValueError:
            messagebox.showerror("Error", "Task not found in data file")
            return
        
        tasks = self.load_tasks()
        if 0 <= index < len(tasks):
            del tasks[index]
            self.tasks_completed += 1
            if self.tasks_completed % 5 == 0:
                self.level += 1
            self.save_character()
            self.update_character_labels()
            self.save_tasks(tasks)
            self.refresh_task_list()
        
    def edit_task(self):
        selected = self.tree.selection()
        if not selected:
            messagebox.showwarning("Warning", "Please select a task to edit")
            return
        
        task_values = self.tree.item(selected[0], 'values')
        task_to_edit = (task_values[0], task_values[1], task_values[2])

        tasks = self.load_tasks()
        try:
            # Find the index by content instead of Treeview position
            index = tasks.index(task_to_edit)
        except ValueError:
            messagebox.showerror("Error", "Task not found in data file")
            return
        
        tasks = self.load_tasks()
        if 0 <= index < len(tasks):
            dialog = tk.Toplevel(self.root)
            dialog.title("Edit Task")
            
            ttk.Label(dialog, text="Task:").grid(row=0, column=0, padx=5, pady=5)
            task_entry = ttk.Entry(dialog, width=40)
            task_entry.grid(row=0, column=1, padx=5, pady=5)
            task_entry.insert(0, tasks[index][0])
            
            ttk.Label(dialog, text="Due Date:").grid(row=1, column=0, padx=5, pady=5)
            date_entry = DateEntry(dialog,
                                 date_pattern="mm-dd-yyyy",
                                 background="darkblue", 
                                 foreground="white",
                                 borderwidth=2)
            date_entry.grid(row=1, column=1, padx=5, pady=5)
            date_entry.set_date(datetime.strptime(tasks[index][1], "%m-%d-%Y"))
            
            ttk.Label(dialog, text="Priority (1-5):").grid(row=2, column=0, padx=5, pady=5)
            priority_entry = ttk.Spinbox(dialog, from_=1, to=5)
            priority_entry.grid(row=2, column=1, padx=5, pady=5)
            priority_entry.insert(0, tasks[index][2])
            
        def validate_and_edit():
            date = self.parse_date(date_entry.get())
            if not date:
                messagebox.showerror("Error", "Invalid date format")
                return
            
            try:
                priority = int(priority_entry.get())
                if not 1 <= priority <= 5:
                    raise ValueError
            except ValueError:
                messagebox.showerror("Error", "Priority must be 1-5")
                return
            
            tasks[index] = (task_entry.get(), date, priority)
            self.save_tasks(tasks)
            self.refresh_task_list()
            dialog.destroy()
            
        ttk.Button(dialog, text="Save", command=validate_and_edit).grid(row=3, columnspan=2, pady=10)

    def delete_task(self):
        selected = self.tree.selection()
        if not selected:
            messagebox.showwarning("Warning", "Please select a task to delete")
            return
        
        task_values = self.tree.item(selected[0], 'values')
        task_to_remove = (task_values[0], task_values[1], task_values[2])
        
        tasks = self.load_tasks()
        try:
            index = tasks.index(task_to_remove)
        except ValueError:
            messagebox.showerror("Error", "Task not found in data file")
            return
        
        tasks = self.load_tasks()
        if 0 <= index < len(tasks):
            del tasks[index]
            self.save_tasks(tasks)
            self.refresh_task_list()        
        else:
            messagebox.showerror("Error", "Invalid task index")

    def refresh_task_list(self):
        """Modified refresh_task_list method"""
        self.tree.delete(*self.tree.get_children())  # Clear existing tasks
        tasks = self.load_tasks()  # Load tasks from file
        current_datetime = datetime.now()
        today = current_datetime.date()
        
        # Categorize tasks
        overdue_tasks = []
        today_tasks = []
        upcoming_tasks = []

        for task in tasks:
            task_name, due_date_str, priority = task
            due_date = datetime.strptime(due_date_str, "%m-%d-%Y").date()

            if due_date < today:
                overdue_tasks.append(task)  # Overdue tasks
            elif due_date == today:
                today_tasks.append(task)  # Due today
            else:
                upcoming_tasks.append(task)  # Future tasks

        # Sort each category
        overdue_tasks.sort(key=lambda x: (datetime.strptime(x[1], "%m-%d-%Y"), -int(x[2])))  # Earliest first
        today_tasks.sort(key=lambda x: int(x[2]), reverse=True)  # Sort by priority (higher first)
        upcoming_tasks.sort(key=lambda x: (datetime.strptime(x[1], "%m-%d-%Y"), -int(x[2])))  # Earliest first

        # Insert into Treeview with colors
        for task in overdue_tasks:
            self.tree.insert("", tk.END, values=task, tags=("overdue",), text=task[0])
        for task in today_tasks:
            self.tree.insert("", tk.END, values=task, tags=("today",), text=task[0])
        for task in upcoming_tasks:
            self.tree.insert("", tk.END, values=task, text=task[0])

        # Configure row colors - moved outside the loop for efficiency
        self.tree.tag_configure("overdue", foreground="red")
        self.tree.tag_configure("today", foreground="orange")

        # Update the remaining tasks count
        self.remaining_label.config(text=str(len(self.tree.get_children())))

    def load_tasks(self):
        if not os.path.exists(TODO_FILE):
            return []
        with open(TODO_FILE, "r") as f:
            tasks = []
            for line in f.readlines():
                parts = line.strip().split(" | ")
                if len(parts) == 3:
                    tasks.append((parts[0], parts[1], parts[2]))
            return sorted(tasks, key=lambda x: (datetime.strptime(x[1], "%m-%d-%Y"), -int(x[2])))

    def save_tasks(self, tasks, skip_mysql=False):
        """Modified to respect storage preference and sync to MySQL if enabled"""
        if self.store_tasks.get():
            with open(TODO_FILE, "w") as f:
                for task in tasks:
                    f.write(" | ".join(str(x) for x in task) + "\n")
    
        # Sync to MySQL if enabled and not skipping
        if self.mysql_enabled.get() and not skip_mysql:
            self.sync_tasks_to_mysql()

    def show_character(self):
        message = f"Character Level: {self.level}\nTasks Completed: {self.tasks_completed}"
        messagebox.showinfo("Character Info", message)

    def update_chat_history(self, message):
        self.chat_history.config(state='normal')
        self.chat_history.insert(tk.END, message + "\n")
        self.chat_history.config(state='disabled')
        self.chat_history.see(tk.END)

    def send_to_ai(self):
        user_text = self.user_input.get()
        if not user_text:
            return
        
        self.update_chat_history(f"User: {user_text}")
        self.user_input.delete(0, tk.END)

         # Show "Thinking..." and store the index so we can replace it later
        self.chat_history.config(state='normal')
        self.chat_history.insert(tk.END, "AI: Thinking...\n", "think")
        thinking_index = self.chat_history.index("end-2l")  # Store line before last newline
        self.chat_history.config(state='disabled')
        self.chat_history.see(tk.END)
        
        # Disable input while processing
        self.user_input.config(state='disabled')
        self.ai_dialog.config(cursor="watch")
        self.send_button.config(state='disabled')
        
        # Start processing in a separate thread
        threading.Thread(target=self.get_ai_response, args=(user_text, thinking_index)).start()

    def get_ai_response(self, prompt, thinking_index):
        try:
            # If there are uploaded files, include their paths in the context
            uploaded_files = [f for f in os.listdir(self.upload_folder)]
            files_context = "\nUploaded files: " + ", ".join(uploaded_files) if uploaded_files else ""
            
            response = requests.post(
                'http://localhost:11434/api/generate',
                json={
                    'model': self.current_ai_model,
                    'prompt': f"""You are a TODO assistant. 

                        Available commands:
                        <command>add;[task];[date];[priority]</command>
                        <command>finish;[task]</command>
                        <command>delete;[task]</command>
                        <command>edit;[old task];[new task];[new date];[new priority]</command>

                        Current time: {datetime.now().strftime("%m-%d-%Y")}{files_context}
                        User: {prompt}""",
                    'stream': True
                },
                stream=True
            )

            # Accumulate the full response
            # ...after accumulating response text
            accumulated_response = ""
            for line in response.iter_lines():
                if line:
                    chunk = json.loads(line)
                    if 'response' in chunk:
                        accumulated_response += chunk['response']

            # Replace "Thinking..." with the response
            def replace_thinking():
                self.chat_history.config(state='normal')
                self.chat_history.delete(f"{thinking_index}", f"{thinking_index} lineend + 1c")
                self.chat_history.insert(tk.END, f"AI: {accumulated_response}\n")
                self.chat_history.config(state='disabled')
                self.chat_history.see(tk.END)

            self.root.after(0, replace_thinking)
            self.root.after(0, self.handle_ai_commands, accumulated_response)


        except requests.exceptions.ConnectionError:
            self.root.after(0, self.update_chat_history, "AI: Could not connect to Ollama. Make sure it's running!")
        except Exception as e:
            self.root.after(0, self.update_chat_history, f"AI: Error - {str(e)}")
        finally:
            self.root.after(0, lambda: self.user_input.config(state='normal'))
            self.root.after(0, lambda: self.ai_dialog.config(cursor=""))
            self.root.after(0, lambda: self.send_button.config(state='normal'))

    def prepare_ai_response(self):
        self.chat_history.config(state='normal')
        # Insert AI prefix and set start position
        self.chat_history.insert(tk.END, "AI:")
        self.ai_response_start = self.chat_history.index("end-1c")
        self.chat_history.config(state='disabled')
        self.chat_history.see(tk.END)

    def update_ai_response(self, text):
        self.chat_history.config(state='normal')
        
        # Check if this is the first response chunk
        if self.chat_history.get("end-2c") != "\n":
            self.chat_history.insert(tk.END, "AI: ")
        
        self.chat_history.insert(tk.END, text)
        self.chat_history.config(state='disabled')
        self.chat_history.see(tk.END)

    def finalize_ai_response(self):
        self.chat_history.config(state='normal')
        # Add spacing after completion
        self.chat_history.insert(tk.END, "\n\n")
        self.chat_history.config(state='disabled')
        self.chat_history.see(tk.END)

    def insert_with_markdown(self, text):
        # Split into lines for block-level processing
        lines = text.split('\n')
        list_mode = False
        
        for line in lines:
            # Headers
            if line.startswith('#'):
                header_level = min(line.count('#'), 3)
                clean_line = line.lstrip('#').strip()
                self.chat_history.insert(tk.END, clean_line + '\n', f"h{header_level}")
                continue
                
            # Lists
            if line.startswith(('- ', '* ', '+ ')):
                if not list_mode:
                    list_mode = True
                    self.chat_history.insert(tk.END, '\n')
                self.chat_history.insert(tk.END, '• ' + line[2:] + '\n', "list")
                continue
            else:
                list_mode = False
                
            # Bold and italic
            pos = 0
            while pos < len(line):
                # Handle bold (**...**)
                bold_start = line.find('**', pos)
                if bold_start != -1:
                    bold_end = line.find('**', bold_start + 2)
                    if bold_end != -1:
                        self.chat_history.insert(tk.END, line[pos:bold_start])
                        self.chat_history.insert(tk.END, line[bold_start+2:bold_end], "bold")
                        pos = bold_end + 2
                        continue
                        
                # Handle italic (*...* or _..._)
                italic_start = max(line.find('*', pos), line.find('_', pos))
                if italic_start != -1:
                    italic_end = max(line.find('*', italic_start + 1), 
                                line.find('_', italic_start + 1))
                    if italic_end != -1:
                        self.chat_history.insert(tk.END, line[pos:italic_start])
                        self.chat_history.insert(tk.END, line[italic_start+1:italic_end], "italic")
                        pos = italic_end + 1
                        continue
                        
                # Handle code blocks (`...`)
                code_start = line.find('`', pos)
                if code_start != -1:
                    code_end = line.find('`', code_start + 1)
                    if code_end != -1:
                        self.chat_history.insert(tk.END, line[pos:code_start])
                        self.chat_history.insert(tk.END, line[code_start+1:code_end], "code")
                        pos = code_end + 1
                        continue
                        
                # Insert remaining text
                self.chat_history.insert(tk.END, line[pos:])
                break
                
            self.chat_history.insert(tk.END, '\n')

    def handle_ai_commands(self, full_response):
        # Extract commands from response
        command_pattern = re.compile(r'<command>(.*?)</command>', re.DOTALL)
        commands = command_pattern.findall(full_response)
        
        # Process commands silently without displaying the message again
        for cmd in commands:
            self.process_command(cmd.strip())

    def process_command(self, cmd_text):
        parts = [p.strip() for p in cmd_text.split(';')]
        if not parts:
            return

        action = parts[0].lower()
        
        try:
            if action == "add":
                task = parts[1]
                date = parts[2]
                priority = parts[3]
                self.add_task_programmatically(task, date, priority)
            elif action == "finish":
                task = parts[1]
                self.complete_task_by_name(task)
            elif action == "delete":
                task = parts[1]
                self.delete_task_by_name(task)
            elif action == "edit":
                old_task = parts[1]
                new_task = parts[2]
                new_date = parts[3]
                new_priority = parts[4]
                self.edit_task_programmatically(old_task, new_task, new_date, new_priority)
        except (IndexError, ValueError) as e:
            self.update_chat_history(f"AI: Error processing command: {str(e)}")

    def add_task_programmatically(self, task, date_str, priority_str):
        date = self.parse_date(date_str)
        if not date:
            raise ValueError("Invalid date format")
        
        try:
            priority = int(priority_str)
            if not 1 <= priority <= 5:
                raise ValueError
        except ValueError:
            raise ValueError("Priority must be 1-5")

        self.add_task(task, date, priority)
        self.update_chat_history(f"AI: Task '{task}' added successfully!")

    def complete_task_by_name(self, task_name):
        tasks = self.load_tasks()
        for t in tasks:
            if t[0] == task_name:
                tasks.remove(t)
                self.tasks_completed += 1
                if self.tasks_completed % 5 == 0:
                    self.level += 1
                self.save_character()
                self.update_character_labels()
                self.save_tasks(tasks)
                self.refresh_task_list()
                self.update_chat_history(f"AI: Task '{task_name}' completed!")
                return
        raise ValueError("Task not found")

    def delete_task_by_name(self, task_name):
        tasks = self.load_tasks()
        new_tasks = [t for t in tasks if t[0] != task_name]
        if len(new_tasks) != len(tasks):
            self.save_tasks(new_tasks)
            self.refresh_task_list()
            self.update_chat_history(f"AI: Task '{task_name}' deleted!")
        else:
            raise ValueError("Task not found")

    def edit_task_programmatically(self, old_task_name, new_task_name, new_date_str, new_priority_str):
        new_date = self.parse_date(new_date_str)
        if not new_date:
            raise ValueError("Invalid new date format")
        
        try:
            new_priority = int(new_priority_str)
            if not 1 <= new_priority <= 5:
                raise ValueError
        except ValueError:
            raise ValueError("Priority must be 1-5")

        tasks = self.load_tasks()
        for i, t in enumerate(tasks):
            if t[0] == old_task_name:
                tasks[i] = (new_task_name, new_date, new_priority)
                self.save_tasks(tasks)
                self.refresh_task_list()
                self.update_chat_history(f"AI: Task updated successfully!")
                return
        raise ValueError("Task not found")

    def change_ai_model(self, model_name):
        self.current_ai_model = model_name
        if hasattr(self, 'ai_dialog') and self.ai_dialog.winfo_exists():
            self.update_chat_history(f"System: Switched to {model_name} model\n")

    def upload_file(self):
        file_path = filedialog.askopenfilename(
            title="Select a file",
            filetypes=[
                ("Images", "*.png *.jpg *.jpeg *.gif *.bmp"),
                ("Documents", "*.pdf *.doc *.docx *.txt"),
                ("All files", "*.*")
            ]
        )
        
        if file_path:
            # Create a unique filename
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            original_filename = Path(file_path).name
            new_filename = f"{timestamp}_{original_filename}"
            new_path = Path(self.upload_folder) / new_filename
            
            # Copy file to uploads folder
            shutil.copy2(file_path, new_path)
            
            # Handle different file types
            mime_type = mimetypes.guess_type(file_path)[0]
            
            if mime_type and mime_type.startswith('image/'):
                self.display_image(new_path)
            else:
                self.display_file_link(new_filename)

    def display_image(self, image_path):
        try:
            # Open and resize image
            image = Image.open(image_path)
            max_size = (300, 300)
            image.thumbnail(max_size, Image.Resampling.LANCZOS)
            
            # Convert to PhotoImage
            photo = ImageTk.PhotoImage(image)
            
            # Store reference to prevent garbage collection
            if not hasattr(self, 'photo_references'):
                self.photo_references = []
            self.photo_references.append(photo)
            
            # Display in chat
            self.chat_history.config(state='normal')
            self.chat_history.insert(tk.END, "\nUser: Uploaded image:\n")
            
            # Create a label for the image and insert it
            image_label = tk.Label(self.chat_history, image=photo)
            self.chat_history.window_create(tk.END, window=image_label)
            self.chat_history.insert(tk.END, "\n")
            self.chat_history.config(state='disabled')
            self.chat_history.see(tk.END)
            
        except Exception as e:
            self.update_chat_history(f"Error displaying image: {str(e)}")

    def display_file_link(self, filename):
        self.chat_history.config(state='normal')
        self.chat_history.insert(tk.END, f"\nUser: Uploaded file: {filename}\n")
        self.chat_history.config(state='disabled')
        self.chat_history.see(tk.END)

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
            len(self.tree.get_children()) > 0):
            self.refresh_task_list()
            self.last_refresh_date = current_date
    
    def load_daily_tasks(self):
        self.tasks = []  # Initialize tasks list
        if not os.path.exists(DAILY_TASK_FILE):
            with open(DAILY_TASK_FILE, "w") as f:
                pass

        with open(DAILY_TASK_FILE, "r") as file:
            for line in file:
                task = line.strip()
                if task:
                    self.add_daily_task_from_file(task)

    def add_daily_task_from_file(self, task_text):
        # Create a frame for each task with its buttons
        task_frame = tk.Frame(self.daily_todo_listbox, bg="#f0f0f0")
        task_frame.pack(fill="x", anchor="w", padx=5, pady=2)
        
        # Add drag handle
        drag_handle = tk.Label(task_frame, text="≡", fg="gray", bg="#f0f0f0", cursor="fleur")
        drag_handle.pack(side=tk.LEFT, padx=(0, 5))
        
        # Create checkbox
        var = tk.BooleanVar()
        checkbox = tk.Checkbutton(task_frame, text=task_text, variable=var,
                                  command=lambda v=var, cb=None: self.toggle_strikethrough(v, cb),
                                  anchor='w', bg="#f0f0f0")
        checkbox.var = var
        checkbox.config(command=lambda v=var, cb=checkbox: self.toggle_strikethrough(v, cb))
        checkbox.pack(side=tk.LEFT, fill="x", expand=True)
        
        # Add edit button
        edit_btn = tk.Button(task_frame, text="✎", width=2, 
                             command=lambda t=checkbox: self.edit_specific_task(t))
        edit_btn.pack(side=tk.RIGHT, padx=2)
        
        # Add remove button
        remove_btn = tk.Button(task_frame, text="×", width=2, 
                               command=lambda f=task_frame, t=checkbox: self.remove_specific_task(f, t))
        remove_btn.pack(side=tk.RIGHT, padx=2)
        
        # Store the frame and checkbox
        checkbox.frame = task_frame
        self.tasks.append(checkbox)
        
        # Configure drag and drop
        self.configure_drag_drop(task_frame, drag_handle, checkbox)

    def configure_drag_drop(self, task_frame, drag_handle, checkbox):
        # Store data needed during drag operations
        task_frame.drag_data = {"y": 0, "item": None, "index": 0}
        
        # Bind mouse events to the drag handle
        drag_handle.bind("<ButtonPress-1>", lambda e, f=task_frame: self.on_drag_start(e, f))
        drag_handle.bind("<B1-Motion>", lambda e, f=task_frame: self.on_drag_motion(e, f))
        drag_handle.bind("<ButtonRelease-1>", lambda e, f=task_frame, cb=checkbox: self.on_drag_stop(e, f, cb))

    def on_drag_start(self, event, frame):
        # Record the initial position and mark this item for dragging
        frame.drag_data["y"] = event.y_root
        frame.drag_data["item"] = frame
        
        # Find the index of this task in our list
        for i, task in enumerate(self.tasks):
            if task.frame == frame:
                frame.drag_data["index"] = i
                break
        
        # Change background color to indicate dragging
        frame.config(bg="#e0e0e0")
        for widget in frame.winfo_children():
            if widget.winfo_class() != 'Button':  # Don't change button colors
                widget.config(bg="#e0e0e0")

    def on_drag_motion(self, event, frame):
        # Calculate how far we've moved
        delta_y = event.y_root - frame.drag_data["y"]
        
        if abs(delta_y) > 10:  # Only move if we've dragged a significant amount
            # Get current position in the list
            current_index = frame.drag_data["index"]
            
            # Determine new position based on drag direction
            new_index = current_index
            if delta_y < 0 and current_index > 0:  # Moving up
                new_index = current_index - 1
            elif delta_y > 0 and current_index < len(self.tasks) - 1:  # Moving down
                new_index = current_index + 1
            
            # If position changed, update the list
            if new_index != current_index:
                # Update the task list
                task = self.tasks.pop(current_index)
                self.tasks.insert(new_index, task)
                
                # Repack all frames in the new order
                for t in self.tasks:
                    t.frame.pack_forget()
                
                for t in self.tasks:
                    t.frame.pack(fill="x", anchor="w", padx=5, pady=2)
                    
                # Update the drag data for the next motion
                frame.drag_data["y"] = event.y_root
                frame.drag_data["index"] = new_index

    def on_drag_stop(self, event, frame, checkbox):
        # Reset the appearance
        frame.config(bg="#f0f0f0")
        for widget in frame.winfo_children():
            if widget.winfo_class() != 'Button':  # Don't change button colors
                widget.config(bg="#f0f0f0")
        
        # Save the new order
        self.save_daily_tasks()

    def save_daily_tasks(self):
        """Modified to respect storage preference"""
        if self.store_tasks.get():
            tasks = []
            for task in self.tasks:
                if task.winfo_exists():  # Check if widget still exists
                    tasks.append(task.cget("text"))
    
            with open(DAILY_TASK_FILE, "w") as file:
                for task in tasks:
                    file.write(task + "\n")

    def add_daily_task(self):
        task_text = simpledialog.askstring("New Task", "Enter task:")
        if task_text:
            self.add_daily_task_from_file(task_text)
            self.save_daily_tasks()

    def remove_daily_task(self):
        removed = False
        for task in self.tasks[:]:
            if task.var.get():
                task.destroy()
                self.tasks.remove(task)
                removed = True
        
        if removed:
            self.save_daily_tasks()

    def edit_specific_task(self, checkbox):
        new_text = simpledialog.askstring("Edit Task", "Update task:", initialvalue=checkbox.cget("text"))
        if new_text:
            checkbox.config(text=new_text)
            self.save_daily_tasks()

    def remove_specific_task(self, frame, checkbox):
        if checkbox in self.tasks:
            self.tasks.remove(checkbox)
        frame.destroy()
        self.save_daily_tasks()

    def toggle_strikethrough(self, var, checkbox):
        if var.get():
            checkbox.config(fg="gray", font=("Arial", 10, "overstrike"))
        else:
            checkbox.config(fg="black", font=("Arial", 10, "normal"))

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
            self.save_daily_tasks()
            messagebox.showinfo(
                "Storage Enabled", 
                "Tasks will now be saved between sessions."
            )

    def toggle_mysql(self):
        """Toggle MySQL sharing functionality"""
        if self.mysql_enabled.get():
            # Test connection before enabling
            if self.test_mysql_connection():
                self.setup_mysql_tables()
                messagebox.showinfo("MySQL Enabled", "MySQL sharing has been enabled.")
                # Sync current tasks to MySQL
                self.sync_tasks_to_mysql()
            else:
                self.mysql_enabled.set(False)
                messagebox.showerror("Connection Failed", "Could not connect to MySQL. Please check your configuration.")
        else:
            messagebox.showinfo("MySQL Disabled", "MySQL sharing has been disabled.")
        
        # Save the configuration
        self.save_mysql_config()

    def configure_mysql(self):
        """Open dialog to configure MySQL connection"""
        dialog = tk.Toplevel(self.root)
        dialog.title("MySQL Configuration")
        dialog.geometry("300x200")
        dialog.resizable(False, False)
        
        # Host
        ttk.Label(dialog, text="Host:").grid(row=0, column=0, padx=5, pady=5, sticky="w")
        host_entry = ttk.Entry(dialog, width=25)
        host_entry.grid(row=0, column=1, padx=5, pady=5)
        host_entry.insert(0, self.mysql_config['host'])
        
        # User
        ttk.Label(dialog, text="User:").grid(row=1, column=0, padx=5, pady=5, sticky="w")
        user_entry = ttk.Entry(dialog, width=25)
        user_entry.grid(row=1, column=1, padx=5, pady=5)
        user_entry.insert(0, self.mysql_config['user'])
        
        # Password
        ttk.Label(dialog, text="Password:").grid(row=2, column=0, padx=5, pady=5, sticky="w")
        password_entry = ttk.Entry(dialog, width=25, show="*")
        password_entry.grid(row=2, column=1, padx=5, pady=5)
        password_entry.insert(0, self.mysql_config['password'])
        
        # Database
        ttk.Label(dialog, text="Database:").grid(row=3, column=0, padx=5, pady=5, sticky="w")
        db_entry = ttk.Entry(dialog, width=25)
        db_entry.grid(row=3, column=1, padx=5, pady=5)
        db_entry.insert(0, self.mysql_config['database'])
        
        # Test connection button
        def test_connection():
            config = {
                'host': host_entry.get(),
                'user': user_entry.get(),
                'password': password_entry.get(),
                'database': db_entry.get()
            }
            
            try:
                conn = mysql.connector.connect(**config)
                conn.close()
                messagebox.showinfo("Success", "Connection successful!")
            except Exception as e:
                messagebox.showerror("Error", f"Connection failed: {str(e)}")
        
        ttk.Button(dialog, text="Test Connection", command=test_connection).grid(row=4, column=0, padx=5, pady=10)
        
        # Save button
        def save_config():
            self.mysql_config = {
                'host': host_entry.get(),
                'user': user_entry.get(),
                'password': password_entry.get(),
                'database': db_entry.get()
            }
            self.save_mysql_config()
            dialog.destroy()
            
        ttk.Button(dialog, text="Save", command=save_config).grid(row=4, column=1, padx=5, pady=10)

    def load_mysql_config(self):
        """Load MySQL configuration from file with better security"""
        try:
            if os.path.exists(MYSQL_CONFIG_FILE):
                with open(MYSQL_CONFIG_FILE, 'r') as f:
                    config = json.load(f)
                    
                    # Load basic config
                    self.mysql_config = {
                        'host': config['config']['host'],
                        'user': config['config']['user'],
                        'database': config['config']['database']
                    }
                    
                    # Get password from system keyring if available
                    try:
                        password = keyring.get_password("todoapp_mysql", self.mysql_config['user'])
                        if password:
                            self.mysql_config['password'] = password
                        else:
                            # Fall back to encoded password from file
                            encoded_pw = config['config'].get('encoded_password', '')
                            if encoded_pw:
                                self.mysql_config['password'] = base64.b64decode(encoded_pw).decode('utf-8')
                            else:
                                self.mysql_config['password'] = ''
                    except:
                        # If keyring fails, use encoded password from file
                        encoded_pw = config['config'].get('encoded_password', '')
                        if encoded_pw:
                            self.mysql_config['password'] = base64.b64decode(encoded_pw).decode('utf-8')
                        else:
                            self.mysql_config['password'] = ''
                    
                    self.mysql_enabled.set(config['enabled'])
        except Exception as e:
            print(f"Error loading MySQL config: {e}")
            self.mysql_config = {
                'host': 'localhost',
                'user': 'root',
                'password': '',
                'database': 'todoapp'
            }

    def save_mysql_config(self):
        """Save MySQL configuration to file with better security"""
        try:
            # Try to store password in system keyring
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
            
            config = {
                'enabled': self.mysql_enabled.get(),
                'config': config_to_save
            }
            
            with open(MYSQL_CONFIG_FILE, 'w') as f:
                json.dump(config, f)
        except Exception as e:
            print(f"Error saving MySQL config: {e}")

    def test_mysql_connection(self):
        """Test connection to MySQL server and create database if needed"""
        try:
            # First try to connect without specifying the database
            config = self.mysql_config.copy()
            database_name = config.pop('database')  # Remove database from config temporarily
            
            # Connect to MySQL server without specifying database
            conn = mysql.connector.connect(**config)
            cursor = conn.cursor()
            
            # Check if database exists
            cursor.execute("SHOW DATABASES LIKE %s", (database_name,))
            result = cursor.fetchone()
            
            # If database doesn't exist, create it
            if not result:
                cursor.execute(f"CREATE DATABASE {database_name}")
                print(f"Created database: {database_name}")
            
            cursor.close()
            conn.close()
            
            # Now try connecting with the database specified
            conn = mysql.connector.connect(**self.mysql_config)
            conn.close()
            return True
        except Exception as e:
            print(f"MySQL connection error: {e}")
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
            tasks = self.load_tasks()
            for task in tasks:
                cursor.execute(
                    "INSERT INTO tasks (task_name, due_date, priority) VALUES (%s, %s, %s)",
                    (task[0], task[1], task[2])
                )
            
            # Insert daily tasks
            for i, task in enumerate(self.tasks):
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
            self.save_tasks(tasks, skip_mysql=True)  # Skip MySQL sync to avoid loop
            
            # Get daily tasks
            cursor.execute("SELECT task_text FROM daily_tasks ORDER BY position")
            daily_tasks = cursor.fetchall()
            
            # Clear existing daily tasks
            for task in self.tasks[:]:
                task.frame.destroy()
            self.tasks.clear()
            
            # Add daily tasks from MySQL
            for task in daily_tasks:
                self.add_daily_task_from_file(task[0])
            
            cursor.close()
            conn.close()
            
            # Refresh the UI
            self.refresh_task_list()
        except Exception as e:
            print(f"Error syncing from MySQL: {e}")
            messagebox.showerror("Sync Error", f"Failed to sync from MySQL: {str(e)}")

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
        dialog = tk.Toplevel(self.root)
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
                    data = {
                        'tasks': self.load_tasks(),
                        'daily_tasks': [task.cget("text") for task in self.tasks if task.winfo_exists()]
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
        dialog = tk.Toplevel(self.root)
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
                    existing_tasks = self.load_tasks()
                    imported_tasks = data['tasks']
                    
                    # Create a set of existing task names for quick lookup
                    existing_task_names = {task[0] for task in existing_tasks}
                    
                    # Add only new tasks
                    for task in imported_tasks:
                        if task[0] not in existing_task_names:
                            existing_tasks.append(task)
                    
                    # Save merged tasks
                    self.save_tasks(existing_tasks)
                    
                    # Merge daily tasks
                    existing_daily_tasks = [task.cget("text") for task in self.tasks if task.winfo_exists()]
                    imported_daily_tasks = data['daily_tasks']
                    
                    # Add only new daily tasks
                    for task_text in imported_daily_tasks:
                        if task_text not in existing_daily_tasks:
                            self.add_daily_task_from_file(task_text)
                else:
                    # Replace tasks
                    self.save_tasks(data['tasks'])
                    
                    # Clear existing daily tasks
                    for task in self.tasks[:]:
                        task.frame.destroy()
                    self.tasks.clear()
                    
                    # Add imported daily tasks
                    for task_text in data['daily_tasks']:
                        self.add_daily_task_from_file(task_text)
                
                # Refresh the UI
                self.refresh_task_list()
                self.save_daily_tasks()
                
                status_label.config(text="Tasks imported successfully!")
                
                # Close the connection
                client.close()
                
                # Close the dialog after a delay
                dialog.after(2000, dialog.destroy)
                
            except Exception as e:
                status_label.config(text=f"Error: {str(e)}")
        
        import_button = ttk.Button(dialog, text="Import", command=connect_and_import)
        import_button.grid(row=3, column=0, columnspan=2, padx=5, pady=10)

    def merge_tasks(self, new_tasks):
        """Merge new tasks with existing tasks"""
        current_tasks = self.load_tasks()
        task_dict = {task[0]: task for task in current_tasks}
        
        for new_task in new_tasks:
            if new_task[0] not in task_dict:
                current_tasks.append(new_task)
        
        self.save_tasks(current_tasks)

    def merge_daily_tasks(self, new_daily_tasks):
        """Merge new daily tasks with existing daily tasks"""
        current_daily_tasks = [task.cget("text") for task in self.tasks if task.winfo_exists()]
        task_dict = {task: True for task in current_daily_tasks}
        
        for new_task in new_daily_tasks:
            if new_task not in task_dict:
                self.add_daily_task_from_file(new_task)
                self.save_daily_tasks()

    def replace_daily_tasks(self, new_daily_tasks):
        """Replace current daily tasks with new daily tasks"""
        for task in self.tasks[:]:
            task.frame.destroy()
        self.tasks.clear()
        
        for task in new_daily_tasks:
            self.add_daily_task_from_file(task)
        self.save_daily_tasks()

if __name__ == "__main__":
    # Check for updates before launching the main app
    import todo_updater
    try:
        todo_updater.Updater()
    except Exception as e:
        print(f"Update check failed: {e}")
        
    # Continue with normal app startup
    root = tk.Tk()
    app = TodoApp(root)
    app.root.iconphoto(True, tk.PhotoImage(file='clipboard.png'))
    root.mainloop()
