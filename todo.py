import json
import os
import re
import tkinter as tk
import requests
import threading
import markdown2
from tkinter.scrolledtext import ScrolledText
from tkinter import ttk, messagebox, simpledialog
from tkcalendar import DateEntry
from tkinter.font import Font
from datetime import datetime
from pathlib import Path

TODO_FILE = str(Path.home()) + "/TODOapp/todo.txt"
CHARACTER_FILE = str(Path.home()) + "/TODOapp/character.txt"
VERSION_FILE = str(Path.home()) + "/TODOapp/version.txt"

class TodoApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Cat TODO App")
        self.root.geometry("1000x700")
        
        # Configure styles
        self.style = ttk.Style()
        self.style.configure("Treeview.Heading", font=('Helvetica', 10, 'bold'))
        self.style.configure("Treeview", rowheight=25)
        
        # Character stats
        self.level = 0
        self.tasks_completed = 0
        
        # Create widgets
        self.create_widgets()
        self.load_character()
        self.refresh_task_list()

        # Version
        self.version = "0.0.0"

        # Check if the AI have a response
        self.has_ai_response = False

    def load_app_version(self):
        try:
            with open(VERSION_FILE, "r") as f:
                return f.read().strip()
        except FileNotFoundError:
            return "0.0.0 (dev)"

    def create_widgets(self):
        # Character stats frame
        char_frame = ttk.Frame(self.root)
        char_frame.pack(pady=10, padx=10, fill=tk.X)

        # Level row
        level_frame = ttk.Frame(char_frame)
        level_frame.pack(fill=tk.X, pady=2)
        ttk.Label(level_frame, text="Level:", font=('Helvetica', 12, 'bold')).pack(side=tk.LEFT)
        self.level_label = ttk.Label(level_frame, text="0", font=('Helvetica', 12))
        self.level_label.pack(side=tk.LEFT, padx=5)

        # Tasks Completed row
        completed_frame = ttk.Frame(char_frame)
        completed_frame.pack(fill=tk.X, pady=2)
        ttk.Label(completed_frame, text="Tasks Completed:", font=('Helvetica', 12, 'bold')).pack(side=tk.LEFT)
        self.tasks_label = ttk.Label(completed_frame, text="0", font=('Helvetica', 12))
        self.tasks_label.pack(side=tk.LEFT, padx=5)

        # Tasks Remaining row
        remaining_frame = ttk.Frame(char_frame)
        remaining_frame.pack(fill=tk.X, pady=2)
        ttk.Label(remaining_frame, text="Tasks Remaining:", font=('Helvetica', 12, 'bold')).pack(side=tk.LEFT)
        self.remaining_label = ttk.Label(remaining_frame, text="0", font=('Helvetica', 12))
        self.remaining_label.pack(side=tk.LEFT, padx=5)

        # Task list
        self.tree = ttk.Treeview(self.root, columns=("Task", "Due Date", "Priority"), show="headings")
        self.tree.heading("Task", text="Task", command=lambda: self.sort_column("Task", False))
        self.tree.heading("Due Date", text="Due Date", command=lambda: self.sort_column("Due Date", False))
        self.tree.heading("Priority", text="Priority", command=lambda: self.sort_column("Priority", False))
        self.tree.column("Task", width=400)
        self.tree.column("Due Date", width=150)
        self.tree.column("Priority", width=100)
        self.tree.pack(pady=10, padx=10, fill=tk.BOTH, expand=True)

        # Controls
        control_frame = ttk.Frame(self.root)
        control_frame.pack(pady=10, fill=tk.X)
        
        ttk.Button(control_frame, text="Add Task", command=self.add_task_dialog).pack(side=tk.LEFT, padx=5)
        ttk.Button(control_frame, text="Finish Task", command=self.remove_task).pack(side=tk.LEFT, padx=5)
        ttk.Button(control_frame, text="Delete Task", command=self.delete_task).pack(side=tk.LEFT, padx=5)
        ttk.Button(control_frame, text="Edit Task", command=self.edit_task).pack(side=tk.LEFT, padx=5)
        ttk.Button(control_frame, text="Character Info", command=self.show_character).pack(side=tk.LEFT, padx=5)

        # Add this with other buttons in control_frame
        ttk.Button(control_frame, text="AI Assistant", command=self.open_ai_dialog).pack(side=tk.LEFT, padx=5)

        # Add time display aligned to the right
        self.time_label = ttk.Label(control_frame, font=('Helvetica', 12, 'bold'))
        self.time_label.pack(side=tk.RIGHT, padx=10)
        self.update_time()


        # Version label at bottom right
        version_frame = ttk.Frame(self.root)
        version_frame.pack(side=tk.BOTTOM, fill=tk.X, padx=10, pady=2)
        
        ttk.Label(
            version_frame,
            text=f"v {self.load_app_version()}",
            font=('Helvetica', 8),
            foreground="gray50",
            anchor="e"  # Right-align text
        ).pack(side=tk.RIGHT, fill=tk.X, expand=True)

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
        
        index = self.tree.index(selected[0])
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
        
        index = self.tree.index(selected[0])
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
        
        index = self.tree.index(selected[0])
        tasks = self.load_tasks()
        if 0 <= index < len(tasks):
            del tasks[index]
            self.save_tasks(tasks)
            self.refresh_task_list()        
        else:
            messagebox.showerror("Error", "Invalid task index")

    def refresh_task_list(self):
        self.tree.delete(*self.tree.get_children())  # Clear existing tasks
        tasks = self.load_tasks()  # Load tasks from file
        today = datetime.today().date()
        
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
        overdue_tasks.sort(key=lambda x: ((datetime.strptime(x[1], "%m-%d-%Y")), (int(x[2]))))  # Earliest first
        today_tasks.sort(key=lambda x: int(x[2]))  # Sort by priority (higher first)
        upcoming_tasks.sort(key=lambda x: ((datetime.strptime(x[1], "%m-%d-%Y")), (int(x[2]))))  # Earliest first

        # Insert into Treeview with colors
        for task in overdue_tasks:
            self.tree.insert("", tk.END, values=task, tags=("overdue",))
        for task in today_tasks:
            self.tree.insert("", tk.END, values=task, tags=("today",))
        for task in upcoming_tasks:
            self.tree.insert("", tk.END, values=task)

        # Configure row colors
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

    def save_tasks(self, tasks):
        with open(TODO_FILE, "w") as f:
            for task in tasks:
                f.write(" | ".join(str(x) for x in task) + "\n")

    def show_character(self):
        message = f"Character Level: {self.level}\nTasks Completed: {self.tasks_completed}"
        messagebox.showinfo("Character Info", message)

    def open_ai_dialog(self):
        self.ai_dialog = tk.Toplevel(self.root)
        self.ai_dialog.title("AI Assistant")
        self.ai_dialog.geometry("1000x500")
        
        self.chat_history = ScrolledText(self.ai_dialog, wrap=tk.WORD, state='disabled')
        self.chat_history.pack(padx=10, pady=10, fill=tk.BOTH, expand=False)
        
        input_frame = ttk.Frame(self.ai_dialog)
        input_frame.pack(padx=10, pady=10, fill=tk.X)
        
        self.user_input = ttk.Entry(input_frame)
        self.user_input.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=5)
        self.user_input.bind("<Return>", lambda e: self.send_to_ai())
        
        ttk.Button(input_frame, text="Send", command=self.send_to_ai).pack(side=tk.RIGHT)
        
        # Add initial greeting
        self.update_chat_history("Assistant: Hi! I am your personal AI assistant. How can I help you today?")

    def update_chat_history(self, message):
        self.chat_history.config(state='normal')
        self.chat_history.insert(tk.END, message + "\n\n")
        self.chat_history.config(state='disabled')
        self.chat_history.see(tk.END)

    def send_to_ai(self):
        user_text = self.user_input.get()
        if not user_text:
            return
        
        self.update_chat_history(f"You: {user_text}")
        self.user_input.delete(0, tk.END)
        
        # Disable input while processing
        self.user_input.config(state='disabled')
        self.ai_dialog.config(cursor="watch")
        
        # Start processing in a separate thread
        threading.Thread(target=self.get_ai_response, args=(user_text,)).start()

    # Update the get_ai_response method with streaming support
    def get_ai_response(self, prompt):
        try:
            response = requests.post(
                'http://localhost:11434/api/generate',
                json={
                    'model': 'deepseek-r1:14b',
                    'prompt': f"""
                    User: {prompt}""",
                    'stream': True  # Enable streaming
                },
                stream=True
            )

            # Initialize response tracking
            self.root.after(0, self.prepare_ai_response)
            accumulated_response = ""

            for line in response.iter_lines():
                if line:
                    chunk = json.loads(line)
                    if 'response' in chunk:
                        accumulated_response += chunk['response']
                        # Update GUI with partial response
                        self.root.after(0, self.update_ai_response, accumulated_response)

            # Add final newlines after completion
            self.root.after(0, self.finalize_ai_response)

        except requests.exceptions.ConnectionError:
            self.root.after(0, self.update_chat_history, "Assistant: Could not connect to Ollama. Make sure it's running!")
        except Exception as e:
            self.root.after(0, self.update_chat_history, f"Assistant: Error - {str(e)}")
        finally:
            self.root.after(0, lambda: self.user_input.config(state='normal'))
            self.root.after(0, lambda: self.ai_dialog.config(cursor=""))

    def prepare_ai_response(self):
        self.chat_history.config(state='normal')
        # Insert AI prefix and set start position
        self.chat_history.insert(tk.END, "Assistant:")
        self.ai_response_start = self.chat_history.index("end-1c")
        self.chat_history.config(state='disabled')
        self.chat_history.see(tk.END)

    def update_ai_response(self, text):
        self.chat_history.config(state='normal')
        # Clear previous partial response
        self.chat_history.delete(self.ai_response_start, tk.END)
        # Insert updated response
        self.chat_history.insert(self.ai_response_start, text)
        self.chat_history.config(state='disabled')
        self.chat_history.see(tk.END)

    def finalize_ai_response(self):
        self.chat_history.config(state='normal')
        # Add spacing after completion
        self.chat_history.insert(tk.END, "\n\n")
        self.chat_history.config(state='disabled')
        self.chat_history.see(tk.END)

if __name__ == "__main__":
    root = tk.Tk()
    app = TodoApp(root)
    root.mainloop()