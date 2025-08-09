"""
ToDo List Manager Module for TODO App
Contains all functionality for the main To Do Task List Panel including task creation,
editing, completion tracking, and task management with notes support.
"""

import os
import tkinter as tk
from tkinter import ttk, messagebox
from tkcalendar import DateEntry
from datetime import datetime
from pathlib import Path
import re


class ToDoListManager:
    def __init__(self, parent_app, todo_frame):
        self.parent_app = parent_app
        self.todo_frame = todo_frame
        
        # TODO file path - Use current working directory
        self.TODO_FILE = os.path.join(os.getcwd(), "todo.txt")
        
        # Task data storage for notes and extended information
        self.task_data = {}
        
        # Track open notes dialogs to prevent multiple windows
        self.open_notes_dialogs = {}
        
        # Create todo list widgets
        self.create_todo_widgets()

    def create_todo_widgets(self):
        """Create the To Do List interface"""
        # Task list inside its frame with action columns
        self.tree = ttk.Treeview(self.todo_frame, columns=("Task", "Due Date", "Priority", "Finish", "Edit", "Delete"), show="headings")
        
        # Configure main columns
        for col, width in [("Task", 300), ("Due Date", 120), ("Priority", 80)]:
            self.tree.heading(col, text=col, command=lambda c=col: self.sort_column(c, False))
            self.tree.column(col, width=width, minwidth=80, stretch=(col=="Task"))
        
        # Configure action columns
        for col, symbol in [("Finish", "Finish"), ("Edit", "Edit"), ("Delete", "Delete")]:
            self.tree.heading(col, text=symbol)
            self.tree.column(col, width=60, minwidth=50, stretch=False, anchor='center')
        
        # Bind click events for action buttons
        self.tree.bind("<Button-1>", self.on_tree_click)
        
        self.tree.pack(pady=10, padx=10, fill=tk.BOTH, expand=True)

        # Add button at bottom left
        control_frame = ttk.Frame(self.todo_frame)
        control_frame.pack(pady=5, padx=10, fill=tk.X)
        ttk.Button(control_frame, text="+ Add Task", command=self.add_task_dialog).pack(side=tk.LEFT, padx=5)

    def on_tree_click(self, event):
        """Handle clicks on main task action buttons"""
        item = self.tree.identify('item', event.x, event.y)
        column = self.tree.identify('column', event.x, event.y)
        
        if item and column:
            # Convert column ID to column name
            col_name = self.tree.heading(column)['text']
            
            # Select the item first
            self.tree.selection_set(item)
            
            if col_name == "Finish":  # Finish button
                self.remove_task()
            elif col_name == "Edit":  # Edit button
                self.edit_task()
            elif col_name == "Delete":  # Delete button
                self.delete_task()
            elif col_name == "Task":  # Task name clicked - show notes
                self.show_task_notes(item)

    def show_task_notes(self, item):
        """Show notes/details for the selected task"""
        try:
            # Check if a dialog is already open for this task
            if item in self.open_notes_dialogs:
                # Bring existing dialog to front
                existing_dialog = self.open_notes_dialogs[item]
                if existing_dialog.winfo_exists():
                    existing_dialog.lift()
                    existing_dialog.focus_force()
                    return
                else:
                    # Clean up stale reference
                    del self.open_notes_dialogs[item]
            
            # Get the full task data from our dictionary
            if item not in self.task_data:
                messagebox.showerror("Error", "Task data not found")
                return
                
            full_data = self.task_data[item]
            task_name = full_data[0]
            notes = full_data[3] if len(full_data) > 3 else ""
            
            # Create notes display dialog
            notes_dialog = tk.Toplevel(self.parent_app.root)
            notes_dialog.title(f"Task Notes: {task_name}")
            notes_dialog.geometry("450x350")
            notes_dialog.resizable(True, True)
            
            # Register this dialog as open for this task
            self.open_notes_dialogs[item] = notes_dialog
            
            # Clean up when dialog is closed
            def on_close():
                if item in self.open_notes_dialogs:
                    del self.open_notes_dialogs[item]
                notes_dialog.destroy()
            
            notes_dialog.protocol("WM_DELETE_WINDOW", on_close)
            
            # Task name label
            ttk.Label(notes_dialog, text=f"Task: {task_name}", font=('Helvetica', 12, 'bold')).pack(pady=10)
            
            # Notes display
            ttk.Label(notes_dialog, text="Notes/Details:", font=('Helvetica', 10, 'bold')).pack(anchor='w', padx=10)
            
            notes_text = tk.Text(notes_dialog, wrap=tk.WORD, state='disabled', height=12)
            notes_text.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)
            
            # Insert notes or default message
            notes_text.config(state='normal')
            if notes.strip() and notes != "No notes":
                notes_text.insert("1.0", notes)
            else:
                notes_text.insert("1.0", "No notes/extra info/details available for this task.")
                notes_text.tag_add("italic", "1.0", "end")
                notes_text.tag_config("italic", font=('Helvetica', 10, 'italic'), foreground="gray")
            notes_text.config(state='disabled')
            
            # Button frame
            button_frame = ttk.Frame(notes_dialog)
            button_frame.pack(fill=tk.X, padx=10, pady=10)
            
            # Edit Task button (primary action)
            ttk.Button(button_frame, text="✎ Edit Task", command=lambda: self.edit_task_from_notes(notes_dialog, item)).pack(side=tk.LEFT, padx=5)
            
            # Close button
            ttk.Button(button_frame, text="Close", command=on_close).pack(side=tk.RIGHT, padx=5)
            
        except Exception as e:
            messagebox.showerror("Error", f"Could not display task notes: {str(e)}")

    def edit_task_from_notes(self, notes_dialog, item):
        """Edit task from the notes dialog"""
        notes_dialog.destroy()
        # Select the item in the tree and call edit
        self.tree.selection_set(item)
        self.edit_task()

    def sort_column(self, column, reverse):
        """Sort the tree view by column"""
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

    def parse_date(self, raw_date):
        """Parse date string to mm-dd-yyyy format"""
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
        """Show dialog to add a new task"""
        dialog = tk.Toplevel(self.parent_app.root)
        dialog.title("Add New Task")
        dialog.geometry("450x300")
        
        ttk.Label(dialog, text="Task:").grid(row=0, column=0, padx=5, pady=5, sticky="nw")
        task_entry = ttk.Entry(dialog, width=40)
        task_entry.grid(row=0, column=1, padx=5, pady=5)
        
        ttk.Label(dialog, text="Due Date:").grid(row=1, column=0, padx=5, pady=5, sticky="nw")
        date_entry = DateEntry(dialog,
                             date_pattern="mm-dd-yyyy",
                             background="darkblue",
                             foreground="white",
                             borderwidth=2)
        date_entry.grid(row=1, column=1, padx=5, pady=5)
        
        ttk.Label(dialog, text="Priority (1-5):").grid(row=2, column=0, padx=5, pady=5, sticky="nw")
        priority_entry = ttk.Spinbox(dialog, from_=1, to=5)
        priority_entry.grid(row=2, column=1, padx=5, pady=5)
        
        ttk.Label(dialog, text="Notes/Details:").grid(row=3, column=0, padx=5, pady=5, sticky="nw")
        notes_text = tk.Text(dialog, width=40, height=6, wrap=tk.WORD)
        notes_text.grid(row=3, column=1, padx=5, pady=5)
        
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
            
            notes = notes_text.get("1.0", tk.END).strip()
            self.add_task(task_entry.get(), date, priority, notes)
            dialog.destroy()

        ttk.Button(dialog, text="Add", command=validate_and_add).grid(row=4, columnspan=2, pady=10)

    def add_task(self, task, date, priority, notes=""):
        """Add a new task to the list"""
        tasks = self.load_tasks()
        # Ensure notes has a proper default value
        if not notes or notes.strip() == "":
            notes = "No notes"
        tasks.append((task, date, priority, notes))
        tasks = sorted(tasks, key=lambda x: (datetime.strptime(x[1], "%m-%d-%Y"), -int(x[2])))
        self.save_tasks(tasks)
        self.refresh_task_list()

    def remove_task(self):
        """Remove/Complete selected task"""
        selected = self.tree.selection()
        if not selected:
            messagebox.showwarning("Warning", "Please select a task to remove")
            return
        
        task_values = self.tree.item(selected[0], 'values')
        task_to_remove = (task_values[0], task_values[1], task_values[2])
        
        tasks = self.load_tasks()
        task_found = None
        index = -1
        
        # Find the task with matching first 3 fields
        for i, task in enumerate(tasks):
            if task[:3] == task_to_remove:
                task_found = task
                index = i
                break
        
        if task_found is None:
            messagebox.showerror("Error", "Task not found in data file")
            return
        
        del tasks[index]
        self.parent_app.tasks_completed += 1
        if self.parent_app.tasks_completed % 5 == 0:
            self.parent_app.level += 1
        self.parent_app.save_character()
        self.parent_app.update_character_labels()
        self.save_tasks(tasks)
        self.refresh_task_list()
        
    def edit_task(self):
        """Edit selected task"""
        selected = self.tree.selection()
        if not selected:
            messagebox.showwarning("Warning", "Please select a task to edit")
            return
        
        task_values = self.tree.item(selected[0], 'values')
        task_to_edit = (task_values[0], task_values[1], task_values[2])

        tasks = self.load_tasks()
        task_found = None
        index = -1
        
        # Find the task with matching first 3 fields
        for i, task in enumerate(tasks):
            if task[:3] == task_to_edit:
                task_found = task
                index = i
                break
        
        if task_found is None:
            messagebox.showerror("Error", "Task not found in data file")
            return
        
        dialog = tk.Toplevel(self.parent_app.root)
        dialog.title("Edit Task")
        dialog.geometry("450x350")
        
        ttk.Label(dialog, text="Task:").grid(row=0, column=0, padx=5, pady=5, sticky="nw")
        task_entry = ttk.Entry(dialog, width=40)
        task_entry.grid(row=0, column=1, padx=5, pady=5)
        task_entry.insert(0, task_found[0])
        
        ttk.Label(dialog, text="Due Date:").grid(row=1, column=0, padx=5, pady=5, sticky="nw")
        date_entry = DateEntry(dialog,
                             date_pattern="mm-dd-yyyy",
                             background="darkblue", 
                             foreground="white",
                             borderwidth=2)
        date_entry.grid(row=1, column=1, padx=5, pady=5)
        date_entry.set_date(datetime.strptime(task_found[1], "%m-%d-%Y"))
        
        ttk.Label(dialog, text="Priority (1-5):").grid(row=2, column=0, padx=5, pady=5, sticky="nw")
        priority_entry = ttk.Spinbox(dialog, from_=1, to=5)
        priority_entry.grid(row=2, column=1, padx=5, pady=5)
        priority_entry.insert(0, task_found[2])
        
        ttk.Label(dialog, text="Notes/Details:").grid(row=3, column=0, padx=5, pady=5, sticky="nw")
        notes_text = tk.Text(dialog, width=40, height=6, wrap=tk.WORD)
        notes_text.grid(row=3, column=1, padx=5, pady=5)
        # Insert existing notes if available
        if len(task_found) > 3:
            notes_text.insert("1.0", task_found[3])
        
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
            
            notes = notes_text.get("1.0", tk.END).strip()
            tasks[index] = (task_entry.get(), date, priority, notes)
            self.save_tasks(tasks)
            self.refresh_task_list()
            dialog.destroy()
            
        ttk.Button(dialog, text="Save", command=validate_and_edit).grid(row=4, columnspan=2, pady=10)

    def delete_task(self):
        """Delete selected task without completing it"""
        selected = self.tree.selection()
        if not selected:
            messagebox.showwarning("Warning", "Please select a task to delete")
            return
        
        task_values = self.tree.item(selected[0], 'values')
        task_to_remove = (task_values[0], task_values[1], task_values[2])
        
        tasks = self.load_tasks()
        task_found = None
        index = -1
        
        # Find the task with matching first 3 fields
        for i, task in enumerate(tasks):
            if task[:3] == task_to_remove:
                task_found = task
                index = i
                break
        
        if task_found is None:
            messagebox.showerror("Error", "Task not found in data file")
            return
        
        del tasks[index]
        self.save_tasks(tasks)
        self.refresh_task_list()

    def refresh_task_list(self):
        """Refresh the task list display"""
        self.tree.delete(*self.tree.get_children())  # Clear existing tasks
        tasks = self.load_tasks()  # Load tasks from file
        current_datetime = datetime.now()
        today = current_datetime.date()
        
        # Store task data for reference
        self.task_data = {}
        
        # Categorize tasks
        overdue_tasks = []
        today_tasks = []
        upcoming_tasks = []

        for task in tasks:
            task_name, due_date_str, priority = task[:3]  # Handle both 3 and 4 element tuples
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

        # Insert into Treeview with colors and action buttons (only show first 3 columns + action buttons)
        for task in overdue_tasks:
            display_values = task[:3] + ("✓", "✎", "✗")
            item = self.tree.insert("", tk.END, values=display_values, tags=("overdue",), text=task[0])
            # Store the full task data (including notes) in our dictionary
            self.task_data[item] = task
        for task in today_tasks:
            display_values = task[:3] + ("✓", "✎", "✗")
            item = self.tree.insert("", tk.END, values=display_values, tags=("today",), text=task[0])
            self.task_data[item] = task
        for task in upcoming_tasks:
            display_values = task[:3] + ("✓", "✎", "✗")
            item = self.tree.insert("", tk.END, values=display_values, text=task[0])
            self.task_data[item] = task

        # Configure row colors - moved outside the loop for efficiency
        self.tree.tag_configure("overdue", foreground="red")
        self.tree.tag_configure("today", foreground="orange")

        # Update the remaining tasks count in parent app
        if hasattr(self.parent_app, 'remaining_label'):
            self.parent_app.remaining_label.config(text=str(len(self.tree.get_children())))

    def load_tasks(self):
        """Load tasks from file"""
        if not os.path.exists(self.TODO_FILE):
            return []
        with open(self.TODO_FILE, "r") as f:
            tasks = []
            for line in f.readlines():
                line = line.strip()
                if not line:  # Skip empty lines
                    continue
                    
                parts = line.split(" | ")
                if len(parts) >= 3:
                    try:
                        task_name = parts[0]
                        due_date = parts[1]
                        priority = parts[2].strip()  # Strip whitespace and extra characters
                        
                        # Validate priority is a number
                        int(priority)
                        
                        # Handle notes - everything after the third delimiter
                        if len(parts) > 3:
                            notes = " | ".join(parts[3:]).strip()  # Rejoin and strip
                            # If notes is empty or just whitespace, set to default message
                            if not notes:
                                notes = "No notes"
                        else:
                            notes = "No notes"
                        
                        tasks.append((task_name, due_date, priority, notes))
                    except ValueError as e:
                        # Skip malformed lines and show more detailed error info
                        print(f"Warning: Skipping malformed line: {line}")
                        print(f"Error details: {e}")
                        print(f"Parts found: {parts}")
                        continue
            return sorted(tasks, key=lambda x: (datetime.strptime(x[1], "%m-%d-%Y"), -int(x[2])))

    def save_tasks(self, tasks, skip_mysql=False):
        """Save tasks to file and sync with MySQL if enabled"""
        with open(self.TODO_FILE, "w") as f:
            for task in tasks:
                # Ensure we have exactly 4 elements (task, date, priority, notes)
                if len(task) == 3:
                    task = task + ("No notes",)  # Add "No notes" if missing
                elif len(task) > 4:
                    # If somehow we have more than 4 elements, keep only first 4
                    task = task[:4]
                
                # Convert all elements to strings
                task_name, date, priority, notes = task
                
                # Handle empty notes - always ensure we have "No notes" if empty
                if not notes or notes.strip() == "":
                    notes = "No notes"
                
                # Create the line with proper formatting
                task_line = f"{task_name} | {date} | {priority} | {notes}"
                f.write(task_line + "\n")
    
        # Sync to MySQL if enabled and not skipping
        if hasattr(self.parent_app, 'mysql_lan_manager') and self.parent_app.mysql_lan_manager.mysql_enabled.get() and not skip_mysql:
            self.parent_app.mysql_lan_manager.sync_tasks_to_mysql()
