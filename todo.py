import os
import re
from datetime import datetime
from pathlib import Path
import tkinter as tk
from tkinter import ttk, messagebox, simpledialog
from tkcalendar import DateEntry
from tkinter.font import Font

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
        self.tree.delete(*self.tree.get_children())
        tasks = self.load_tasks()
        for task in tasks:
            self.tree.insert("", tk.END, values=task)
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

if __name__ == "__main__":
    root = tk.Tk()
    app = TodoApp(root)
    root.mainloop()