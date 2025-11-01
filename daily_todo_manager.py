"""
Daily ToDo List Module for TODO App
Contains all functionality for the Daily To Do List Panel including time management,
task completion tracking, and drag-and-drop reordering.
"""

import os
import re
import tkinter as tk
from tkinter import ttk, messagebox
from datetime import datetime
from pathlib import Path


class DailyToDoManager:
    def __init__(self, parent_app, daily_todo_frame):
        self.parent_app = parent_app
        self.daily_todo_frame = daily_todo_frame
        
        # Daily task file path
        self.DAILY_TASK_FILE = str(Path.home()) + "/TODOapp/dailytask.txt"
        self.DAILY_DATE_FILE = str(Path.home()) + "/TODOapp/daily_date.txt"
        
        # Task storage
        self.tasks = []
        
        # Create daily todo widgets
        self.create_daily_todo_widgets()
        
        # Check if we need to reset for a new day
        self.check_and_reset_daily_tasks()
        
        # Load existing tasks
        self.load_daily_tasks()

    def check_and_reset_daily_tasks(self):
        """Check if it's a new day and reset daily task completion status if needed"""
        current_date = datetime.now().date().strftime("%Y-%m-%d")
        
        try:
            # Read the last stored date
            with open(self.DAILY_DATE_FILE, "r") as f:
                stored_date = f.read().strip()
        except FileNotFoundError:
            # First time running or file doesn't exist
            stored_date = ""
        
        if stored_date != current_date:
            # It's a new day - reset completion status of daily tasks
            print(f"New day detected ({current_date}). Resetting daily task completion status.")
            
            if os.path.exists(self.DAILY_TASK_FILE):
                # Read existing tasks
                with open(self.DAILY_TASK_FILE, "r") as f:
                    tasks = f.readlines()
                
                # Reset completion status (remove [COMPLETED] prefix)
                reset_tasks = []
                for task in tasks:
                    task = task.strip()
                    if task.startswith("[COMPLETED] "):
                        # Remove completion status but keep the task
                        task = task.replace("[COMPLETED] ", "")
                    reset_tasks.append(task)
                
                # Write back the reset tasks
                with open(self.DAILY_TASK_FILE, "w") as f:
                    for task in reset_tasks:
                        if task:  # Only write non-empty tasks
                            f.write(task + "\n")
                
                print(f"Reset completion status for {len(reset_tasks)} daily tasks.")
            
            # Update the stored date
            os.makedirs(os.path.dirname(self.DAILY_DATE_FILE), exist_ok=True)
            with open(self.DAILY_DATE_FILE, "w") as f:
                f.write(current_date)
            
            print("Daily task completion status has been reset for the new day.")
        else:
            print(f"Same day ({current_date}). Keeping existing daily task status.")

    def create_daily_todo_widgets(self):
        """Create the Daily To Do List interface"""
        # Create Treeview for daily tasks with action columns
        self.daily_tree = ttk.Treeview(self.daily_todo_frame, columns=("Time", "Task", "Status", "Complete", "Edit", "Delete", "Original"), show="headings", height=6)
        self.daily_tree.heading("Time", text="Time")
        self.daily_tree.heading("Task", text="Task")
        self.daily_tree.heading("Status", text="Status")
        self.daily_tree.heading("Complete", text="Complete")
        self.daily_tree.heading("Edit", text="Edit")
        self.daily_tree.heading("Delete", text="Delete")
        
        # Set column widths
        self.daily_tree.column("Time", width=100, minwidth=80)
        self.daily_tree.column("Task", width=250, minwidth=200, stretch=True)
        self.daily_tree.column("Status", width=80, minwidth=60)
        self.daily_tree.column("Complete", width=70, minwidth=60, stretch=False, anchor='center')
        self.daily_tree.column("Edit", width=50, minwidth=40, stretch=False, anchor='center')
        self.daily_tree.column("Delete", width=60, minwidth=50, stretch=False, anchor='center')
        
        # Hide the Original column (used for storing original task text)
        self.daily_tree.column("Original", width=0, minwidth=0, stretch=False)
        self.daily_tree.heading("Original", text="")
        
        # Bind click events for action buttons
        self.daily_tree.bind("<Button-1>", self.on_daily_tree_click)
        
        self.daily_tree.pack(fill=tk.X, padx=5, pady=5)
        
        # Add button at bottom left
        daily_add_frame = ttk.Frame(self.daily_todo_frame)
        daily_add_frame.pack(pady=5, padx=10, fill=tk.X)
        ttk.Button(daily_add_frame, text="+ Add", command=self.add_daily_task).pack(side=tk.LEFT, padx=5)

    def on_daily_tree_click(self, event):
        """Handle clicks on daily task action buttons"""
        item = self.daily_tree.identify('item', event.x, event.y)
        column = self.daily_tree.identify('column', event.x, event.y)
        
        if item and column:
            # Convert column ID to column name
            col_name = self.daily_tree.heading(column)['text']
            
            # Select the item first
            self.daily_tree.selection_set(item)
            
            if col_name == "Complete":  # Complete button
                self.complete_daily_task()
            elif col_name == "Edit":  # Edit button
                self.edit_daily_task()
            elif col_name == "Delete":  # Delete button
                self.delete_daily_task()
            elif col_name == "Task":  # Task name clicked - show notes for daily tasks
                self.show_daily_task_notes(item)

    def show_daily_task_notes(self, item):
        """Show details for the selected daily task"""
        try:
            # Check if any dialog is already open
            if self.parent_app.check_existing_dialog():
                return
            
            # Get task details from the Treeview
            values = self.daily_tree.item(item, 'values')
            if len(values) < 7:
                messagebox.showerror("Error", "Task data incomplete")
                return
                
            time_str = values[0]
            task_name = values[1]
            status = values[2]
            original_text = values[6]  # Original column
            
            # Create notes display dialog
            notes_dialog = tk.Toplevel(self.parent_app.root)
            notes_dialog.title(f"Daily Task Details: {task_name}")
            notes_dialog.geometry("450x300")
            notes_dialog.resizable(True, True)
            
            # Register this dialog globally
            self.parent_app.register_dialog(notes_dialog)
            
            # Task details
            details_frame = ttk.Frame(notes_dialog)
            details_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
            
            ttk.Label(details_frame, text="Daily Task Details", font=('Helvetica', 12, 'bold')).pack(pady=(0, 10))
            
            # Time
            time_frame = ttk.Frame(details_frame)
            time_frame.pack(fill=tk.X, pady=2)
            ttk.Label(time_frame, text="Time:", font=('Helvetica', 10, 'bold')).pack(side=tk.LEFT)
            ttk.Label(time_frame, text=time_str).pack(side=tk.LEFT, padx=(10, 0))
            
            # Task
            task_frame = ttk.Frame(details_frame)
            task_frame.pack(fill=tk.X, pady=2)
            ttk.Label(task_frame, text="Task:", font=('Helvetica', 10, 'bold')).pack(side=tk.LEFT)
            ttk.Label(task_frame, text=task_name, wraplength=350).pack(side=tk.LEFT, padx=(10, 0))
            
            # Status
            status_frame = ttk.Frame(details_frame)
            status_frame.pack(fill=tk.X, pady=2)
            ttk.Label(status_frame, text="Status:", font=('Helvetica', 10, 'bold')).pack(side=tk.LEFT)
            status_label = ttk.Label(status_frame, text=status)
            status_label.pack(side=tk.LEFT, padx=(10, 0))
            
            # Color code status
            if status == "Completed":
                status_label.config(foreground="green")
            elif status == "Overdue":
                status_label.config(foreground="red")
            else:
                status_label.config(foreground="black")
            
            # Show original format if different from display
            if original_text.startswith("[COMPLETED] "):
                clean_original = original_text.replace("[COMPLETED] ", "")
                original_frame = ttk.Frame(details_frame)
                original_frame.pack(fill=tk.X, pady=2)
                ttk.Label(original_frame, text="Original:", font=('Helvetica', 10, 'bold')).pack(side=tk.LEFT)
                ttk.Label(original_frame, text=clean_original, wraplength=350).pack(side=tk.LEFT, padx=(10, 0))
            
            # Button frame
            button_frame = ttk.Frame(notes_dialog)
            button_frame.pack(fill=tk.X, padx=10, pady=10)
            
            # Edit Task button (primary action)
            ttk.Button(button_frame, text="✎ Edit Task", command=lambda: self.edit_daily_task_from_notes(notes_dialog, item)).pack(side=tk.LEFT, padx=5)
            
            # Close button
            ttk.Button(button_frame, text="Close", command=notes_dialog.destroy).pack(side=tk.RIGHT, padx=5)
            
        except Exception as e:
            messagebox.showerror("Error", f"Could not display task details: {str(e)}")

    def edit_daily_task_from_notes(self, notes_dialog, item):
        """Edit daily task from the notes dialog"""
        notes_dialog.destroy()
        # Select the item in the daily tree and call edit
        self.daily_tree.selection_set(item)
        self.edit_daily_task()

    def load_daily_tasks(self):
        """Load daily tasks into the Treeview, sorted by time"""
        # Clear existing items
        if hasattr(self, 'daily_tree'):
            self.daily_tree.delete(*self.daily_tree.get_children())
        
        if not os.path.exists(self.DAILY_TASK_FILE):
            with open(self.DAILY_TASK_FILE, "w") as f:
                pass
            return

        # Read all tasks and sort them by time
        tasks = []
        with open(self.DAILY_TASK_FILE, "r") as file:
            for line in file:
                task_text = line.strip()
                if task_text:
                    tasks.append(task_text)
        
        # Sort tasks by time
        sorted_tasks = self.sort_tasks_by_time(tasks)
        
        # Add sorted tasks to tree
        for task_text in sorted_tasks:
            self.add_daily_task_to_tree(task_text)

    def sort_tasks_by_time(self, tasks):
        """Sort tasks by their time component"""
        def extract_time_for_sorting(task_text):
            # Remove completion status for parsing
            clean_task = task_text.replace("[COMPLETED] ", "")
            
            # Parse task to extract time
            time_pattern = r"^(\d{2}:\d{2}) - (.+)$"
            match = re.match(time_pattern, clean_task)
            
            if match:
                time_str = match.group(1)
                # Convert to minutes for easy sorting (HH:MM -> total minutes)
                hour, minute = map(int, time_str.split(':'))
                return hour * 60 + minute
            else:
                # Tasks without time default to 00:00 (0 minutes)
                return 0
        
        # Sort tasks by their time value
        return sorted(tasks, key=extract_time_for_sorting)

    def sort_tree_by_time(self):
        """Sort the daily tasks tree view by chronological order"""
        # Get all items from the tree
        items = []
        for item_id in self.daily_tree.get_children():
            values = self.daily_tree.item(item_id, 'values')
            items.append((item_id, values))
        
        # Sort items by time
        def extract_time_for_tree_sorting(item_data):
            values = item_data[1]
            if len(values) >= 7:
                original_text = values[6]  # Original column
                # Remove completion status for parsing
                clean_task = original_text.replace("[COMPLETED] ", "")
                
                # Parse task to extract time
                time_pattern = r"^(\d{2}:\d{2}) - (.+)$"
                match = re.match(time_pattern, clean_task)
                
                if match:
                    time_str = match.group(1)
                    # Convert to minutes for easy sorting (HH:MM -> total minutes)
                    hour, minute = map(int, time_str.split(':'))
                    return hour * 60 + minute
                else:
                    # Tasks without time default to 00:00 (0 minutes)
                    return 0
            return 0
        
        # Sort items by time
        sorted_items = sorted(items, key=extract_time_for_tree_sorting)
        
        # Clear tree and re-insert in sorted order
        for item_id, _ in items:
            self.daily_tree.delete(item_id)
        
        # Re-insert items in sorted order
        for _, values in sorted_items:
            # Determine the appropriate tag based on status
            status = values[2] if len(values) > 2 else "Pending"
            if status == "Completed":
                tag = "completed"
            elif status == "Overdue":
                tag = "overdue"
            else:
                tag = "pending"
            
            self.daily_tree.insert("", tk.END, values=values, tags=(tag,))

    def add_daily_task_to_tree(self, task_text):
        """Add a single daily task to the Treeview"""
        # Check if task is completed (marked with [COMPLETED] prefix)
        is_completed = task_text.startswith("[COMPLETED] ")
        if is_completed:
            task_text = task_text.replace("[COMPLETED] ", "")
        
        # Parse task to extract time and task parts
        time_pattern = r"^(\d{2}:\d{2}) - (.+)$"
        match = re.match(time_pattern, task_text)
        
        if match:
            time_str = match.group(1)  # Always stored in 24-hour format
            task_only = match.group(2)
            
            # Format time for display based on user preference
            hour_24, minute = map(int, time_str.split(':'))
            if self.parent_app.use_24_hour.get():
                display_time = f"{hour_24:02d}:{minute:02d}"
            else:
                # Convert to 12-hour format for display
                if hour_24 == 0:
                    display_time = f"12:{minute:02d} AM"
                elif hour_24 < 12:
                    display_time = f"{hour_24}:{minute:02d} AM"
                elif hour_24 == 12:
                    display_time = f"12:{minute:02d} PM"
                else:
                    display_time = f"{hour_24-12}:{minute:02d} PM"
        else:
            # Task without time - default to 00:00
            time_str = "00:00"
            task_only = task_text
            
            # Format default time for display
            if self.parent_app.use_24_hour.get():
                display_time = "00:00"
            else:
                display_time = "12:00 AM"
        
        # Determine status
        if is_completed:
            status = "Completed"
            tag = "completed"
        else:
            # Check if deadline has passed for status
            current_time = datetime.now()
            current_hour = current_time.hour
            current_minute = current_time.minute
            current_time_minutes = current_hour * 60 + current_minute
            
            # Parse task time
            task_hour, task_minute = map(int, time_str.split(':'))
            task_time_minutes = task_hour * 60 + task_minute
            
            if current_time_minutes > task_time_minutes:
                status = "Overdue"
                tag = "overdue"
            else:
                status = "Pending"
                tag = "pending"
        
        # Store original task text (with completion marker if applicable)
        original_with_completion = f"[COMPLETED] {task_text}" if is_completed else task_text
        
        # Insert into Treeview with action buttons
        item = self.daily_tree.insert("", tk.END, values=(display_time, task_only, status, "✓", "✎", "✗", original_with_completion), tags=(tag,))
        
        # Configure colors
        self.daily_tree.tag_configure("overdue", foreground="red")
        self.daily_tree.tag_configure("pending", foreground="black")
        self.daily_tree.tag_configure("completed", foreground="gray", font=('Helvetica', 10, 'overstrike'))

    def update_daily_task_colors(self):
        """Update colors of daily tasks based on current time"""
        if not hasattr(self, 'daily_tree'):
            return
            
        current_time = datetime.now()
        current_hour = current_time.hour
        current_minute = current_time.minute
        current_time_minutes = current_hour * 60 + current_minute
        
        # Update each item in the Treeview
        for item in self.daily_tree.get_children():
            # Get original task text from the "Original" column (now index 6)
            values = self.daily_tree.item(item, 'values')
            if len(values) >= 7:  # Make sure we have the Original column
                original_text = values[6]  # Original column is now index 6
                
                # Skip updating if task is completed - preserve completed styling
                if original_text.startswith("[COMPLETED] ") or values[2] == "Completed":
                    # Ensure completed tasks maintain their styling
                    self.daily_tree.item(item, tags=("completed",))
                    continue
                
                # Remove any completion marker for parsing
                clean_text = original_text.replace("[COMPLETED] ", "")
                time_pattern = r"^(\d{2}:\d{2}) - (.+)$"
                match = re.match(time_pattern, clean_text)
                
                if match:
                    time_str = match.group(1)
                    task_hour, task_minute = map(int, time_str.split(':'))
                    task_time_minutes = task_hour * 60 + task_minute
                    
                    # Get current values
                    current_values = list(values)
                    
                    if current_time_minutes > task_time_minutes:
                        # Time has passed - update status and color
                        current_values[2] = "Overdue"  # Update status column
                        self.daily_tree.item(item, values=current_values, tags=("overdue",))
                    else:
                        # Time hasn't passed - update status and color
                        current_values[2] = "Pending"  # Update status column
                        self.daily_tree.item(item, values=current_values, tags=("pending",))

    def complete_daily_task(self):
        """Mark selected daily task as completed and cross it out"""
        selected = self.daily_tree.selection()
        if not selected:
            messagebox.showwarning("Warning", "Please select a task to complete")
            return
        
        # Get current values
        values = list(self.daily_tree.item(selected[0], 'values'))
        original_text = values[6]  # Original column
        
        # Skip if already completed
        if original_text.startswith("[COMPLETED] ") or values[2] == "Completed":
            messagebox.showinfo("Info", "Task is already completed!")
            return
        
        # Update status to "Completed"
        values[2] = "Completed"  # Status column
        
        # Mark original text as completed
        values[6] = f"[COMPLETED] {original_text}"
        
        # Update the item with new values and apply completed tag
        self.daily_tree.item(selected[0], values=values, tags=("completed",))
        
        # Configure strikethrough style for completed tasks
        self.daily_tree.tag_configure("completed", foreground="gray", font=('Helvetica', 10, 'overstrike'))
        
        # Save to file with completion marker
        self.save_daily_tasks()
        messagebox.showinfo("Success", "Task completed!")

    def edit_daily_task(self):
        """Edit selected daily task"""
        # Check if any dialog is already open
        if self.parent_app.check_existing_dialog():
            return
            
        selected = self.daily_tree.selection()
        if not selected:
            messagebox.showwarning("Warning", "Please select a task to edit")
            return
        
        # Get original task text from the "Original" column (now index 6)
        values = self.daily_tree.item(selected[0], 'values')
        if len(values) >= 7:  # Make sure we have the Original column
            original_text = values[6]  # Original column is now index 6
        else:
            messagebox.showerror("Error", "Unable to retrieve task data")
            return
        
        # Parse current task to extract time and task parts
        time_pattern = r"^(\d{2}:\d{2}) - (.+)$"
        match = re.match(time_pattern, original_text)
        
        if match:
            current_time = match.group(1)
            current_task = match.group(2)
            current_hour, current_minute = current_time.split(":")
        else:
            # Task without proper time format - default to 00:00
            current_time = "00:00"
            current_task = original_text
            current_hour = "00"
            current_minute = "00"
        
        # Create edit dialog (similar to add dialog)
        dialog = tk.Toplevel(self.parent_app.root)
        dialog.title("Edit Daily Task")
        dialog.geometry("400x200")
        dialog.resizable(False, False)
        
        # Register this dialog globally
        self.parent_app.register_dialog(dialog)
        
        # Task name
        ttk.Label(dialog, text="Task:").grid(row=0, column=0, padx=5, pady=10, sticky="w")
        task_entry = ttk.Entry(dialog, width=30)
        task_entry.grid(row=0, column=1, padx=5, pady=10, columnspan=2)
        task_entry.insert(0, current_task)
        
        # Time (required)
        ttk.Label(dialog, text="Time (required):").grid(row=1, column=0, padx=5, pady=10, sticky="w")
        
        if self.parent_app.use_24_hour.get():
            # 24-hour format
            hour_var = tk.StringVar(value=current_hour)
            hour_combo = ttk.Combobox(dialog, textvariable=hour_var, width=6, state="readonly")
            hour_combo['values'] = [f"{i:02d}" for i in range(24)]
            hour_combo.grid(row=1, column=1, padx=(5, 2), pady=10, sticky="w")
            
            ttk.Label(dialog, text=":").grid(row=1, column=1, padx=(65, 0), pady=10, sticky="w")
            
            minute_var = tk.StringVar(value=current_minute)
            minute_combo = ttk.Combobox(dialog, textvariable=minute_var, width=6, state="readonly")
            minute_combo['values'] = [f"{i:02d}" for i in range(0, 60, 15)]
            minute_combo.grid(row=1, column=1, padx=(80, 0), pady=10, sticky="w")
        else:
            # 12-hour format - convert current 24-hour time to 12-hour
            hour_24 = int(current_hour)
            if hour_24 == 0:
                display_hour = "12"
                period = "AM"
            elif hour_24 < 12:
                display_hour = str(hour_24)
                period = "AM"
            elif hour_24 == 12:
                display_hour = "12"
                period = "PM"
            else:
                display_hour = str(hour_24 - 12)
                period = "PM"
            
            hour_var = tk.StringVar(value=display_hour)
            hour_combo = ttk.Combobox(dialog, textvariable=hour_var, width=6, state="readonly")
            hour_combo['values'] = [f"{i}" for i in range(1, 13)]
            hour_combo.grid(row=1, column=1, padx=(5, 2), pady=10, sticky="w")
            
            ttk.Label(dialog, text=":").grid(row=1, column=1, padx=(65, 0), pady=10, sticky="w")
            
            minute_var = tk.StringVar(value=current_minute)
            minute_combo = ttk.Combobox(dialog, textvariable=minute_var, width=6, state="readonly")
            minute_combo['values'] = [f"{i:02d}" for i in range(0, 60, 15)]
            minute_combo.grid(row=1, column=1, padx=(80, 0), pady=10, sticky="w")
            
            period_var = tk.StringVar(value=period)
            period_combo = ttk.Combobox(dialog, textvariable=period_var, width=6, state="readonly")
            period_combo['values'] = ["AM", "PM"]
            period_combo.grid(row=1, column=1, padx=(145, 0), pady=10, sticky="w")
        
        result = {"task": None}
        
        def validate_and_save():
            task_text = task_entry.get().strip()
            if not task_text:
                messagebox.showerror("Error", "Please enter a task name")
                return
            
            # Format time based on selected format
            if self.parent_app.use_24_hour.get():
                # 24-hour format
                if not hour_var.get() or not minute_var.get():
                    messagebox.showerror("Error", "Please select both hour and minute")
                    return
                time_str = f"{hour_var.get()}:{minute_var.get()}"
            else:
                # 12-hour format - convert to 24-hour for storage
                if not hour_var.get() or not minute_var.get() or not period_var.get():
                    messagebox.showerror("Error", "Please select hour, minute, and AM/PM")
                    return
                
                hour = int(hour_var.get())
                minute = minute_var.get()
                period = period_var.get()
                
                if period == "AM":
                    if hour == 12:
                        hour = 0
                else:  # PM
                    if hour != 12:
                        hour += 12
                
                time_str = f"{hour:02d}:{minute}"
            
            # Combine time and task in new format: TIME - TASK
            full_task = f"{time_str} - {task_text}"
                
            result["task"] = full_task
            dialog.destroy()
        
        def cancel():
            dialog.destroy()
            
        # Buttons
        button_frame = ttk.Frame(dialog)
        button_frame.grid(row=3, column=0, columnspan=3, pady=20)
        
        ttk.Button(button_frame, text="Save", command=validate_and_save).pack(side=tk.LEFT, padx=5)
        ttk.Button(button_frame, text="Cancel", command=cancel).pack(side=tk.LEFT, padx=5)
        
        # Focus on task entry
        task_entry.focus()
        
        # Wait for dialog to close
        dialog.transient(self.parent_app.root)
        dialog.grab_set()
        self.parent_app.root.wait_window(dialog)
        
        # Update the task if changes were made
        if result["task"]:
            # Remove old item and add updated one
            self.daily_tree.delete(selected[0])
            self.add_daily_task_to_tree(result["task"])
            self.save_daily_tasks()
            # Re-sort tasks after editing to maintain chronological order
            self.sort_tree_by_time()

    def delete_daily_task(self):
        """Delete selected daily task"""
        selected = self.daily_tree.selection()
        if not selected:
            messagebox.showwarning("Warning", "Please select a task to delete")
            return
        
        # Confirm deletion
        if messagebox.askyesno("Confirm Delete", "Are you sure you want to delete this task?"):
            self.daily_tree.delete(selected[0])
            self.save_daily_tasks()
            # Re-sort tasks after deleting to maintain chronological order
            self.sort_tree_by_time()
            messagebox.showinfo("Success", "Task deleted!")

    def add_daily_task(self):
        """Add a new daily task"""
        # Check if any dialog is already open
        if self.parent_app.check_existing_dialog():
            return
            
        # Create a custom dialog for task with time
        dialog = tk.Toplevel(self.parent_app.root)
        dialog.title("Add Daily Task")
        dialog.geometry("400x200")
        dialog.resizable(False, False)
        
        # Important: Register dialog BEFORE any other setup
        self.parent_app.register_dialog(dialog)
        
        # Task name
        ttk.Label(dialog, text="Task:").grid(row=0, column=0, padx=5, pady=10, sticky="w")
        task_entry = ttk.Entry(dialog, width=30)
        task_entry.grid(row=0, column=1, padx=5, pady=10, columnspan=2)
        
        # Time (required)
        ttk.Label(dialog, text="Time (required):").grid(row=1, column=0, padx=5, pady=10, sticky="w")
        
        if self.parent_app.use_24_hour.get():
            # 24-hour format
            hour_var = tk.StringVar(value="00")
            hour_combo = ttk.Combobox(dialog, textvariable=hour_var, width=6, state="readonly")
            hour_combo['values'] = [f"{i:02d}" for i in range(24)]
            hour_combo.grid(row=1, column=1, padx=(5, 2), pady=10, sticky="w")
            
            ttk.Label(dialog, text=":").grid(row=1, column=1, padx=(65, 0), pady=10, sticky="w")
            
            minute_var = tk.StringVar(value="00")
            minute_combo = ttk.Combobox(dialog, textvariable=minute_var, width=6, state="readonly")
            minute_combo['values'] = [f"{i:02d}" for i in range(0, 60, 15)]
            minute_combo.grid(row=1, column=1, padx=(80, 0), pady=10, sticky="w")
        else:
            # 12-hour format
            hour_var = tk.StringVar(value="12")
            hour_combo = ttk.Combobox(dialog, textvariable=hour_var, width=6, state="readonly")
            hour_combo['values'] = [f"{i}" for i in range(1, 13)]
            hour_combo.grid(row=1, column=1, padx=(5, 2), pady=10, sticky="w")
            
            ttk.Label(dialog, text=":").grid(row=1, column=1, padx=(65, 0), pady=10, sticky="w")
            
            minute_var = tk.StringVar(value="00")
            minute_combo = ttk.Combobox(dialog, textvariable=minute_var, width=6, state="readonly")
            minute_combo['values'] = [f"{i:02d}" for i in range(0, 60, 15)]
            minute_combo.grid(row=1, column=1, padx=(80, 0), pady=10, sticky="w")
            
            period_var = tk.StringVar(value="AM")
            period_combo = ttk.Combobox(dialog, textvariable=period_var, width=6, state="readonly")
            period_combo['values'] = ["AM", "PM"]
            period_combo.grid(row=1, column=1, padx=(145, 0), pady=10, sticky="w")
        
        result = {"task": None, "time": None}
        
        def validate_and_add():
            task_text = task_entry.get().strip()
            if not task_text:
                messagebox.showerror("Error", "Please enter a task name")
                return
            
            # Format time based on selected format
            if self.parent_app.use_24_hour.get():
                # 24-hour format
                if not hour_var.get() or not minute_var.get():
                    messagebox.showerror("Error", "Please select both hour and minute")
                    return
                time_str = f"{hour_var.get()}:{minute_var.get()}"
            else:
                # 12-hour format - convert to 24-hour for storage
                if not hour_var.get() or not minute_var.get() or not period_var.get():
                    messagebox.showerror("Error", "Please select hour, minute, and AM/PM")
                    return
                
                hour = int(hour_var.get())
                minute = minute_var.get()
                period = period_var.get()
                
                if period == "AM":
                    if hour == 12:
                        hour = 0
                else:  # PM
                    if hour != 12:
                        hour += 12
                
                time_str = f"{hour:02d}:{minute}"
            
            # Combine time and task in new format: TIME - TASK
            full_task = f"{time_str} - {task_text}"
                
            result["task"] = full_task
            result["time"] = time_str
            dialog.destroy()
        
        def cancel():
            dialog.destroy()
            
        # Buttons
        button_frame = ttk.Frame(dialog)
        button_frame.grid(row=3, column=0, columnspan=3, pady=20)
        
        ttk.Button(button_frame, text="Add", command=validate_and_add).pack(side=tk.LEFT, padx=5)
        ttk.Button(button_frame, text="Cancel", command=cancel).pack(side=tk.LEFT, padx=5)
        
        # Focus on task entry
        task_entry.focus()
        
        # Bind the Return key to the validate_and_add function
        dialog.bind('<Return>', lambda e: validate_and_add())
        
        # Wait for dialog to close
        self.parent_app.root.wait_window(dialog)
        
        # Add the task if one was created
        if result["task"]:
            self.add_daily_task_to_tree(result["task"])
            self.save_daily_tasks()
            # Re-sort tasks after adding to maintain chronological order
            self.sort_tree_by_time()

    def save_daily_tasks(self):
        """Save daily tasks from Treeview to file in chronological order"""
        if self.parent_app.store_tasks.get():
            tasks = []
            # Get all items from the Treeview
            for item in self.daily_tree.get_children():
                # Get the original task text stored in the "Original" column (now index 6)
                values = self.daily_tree.item(item, 'values')
                if len(values) >= 7:  # Make sure we have the Original column
                    original_text = values[6]  # Original column is now index 6
                    if original_text:
                        tasks.append(original_text)
            
            # Sort tasks by time before saving
            sorted_tasks = self.sort_tasks_by_time(tasks)
    
            with open(self.DAILY_TASK_FILE, "w") as file:
                for task in sorted_tasks:
                    file.write(task + "\n")

    def refresh_daily_task_display(self):
        """Refresh the display of all daily tasks to show current time format"""
        if not hasattr(self, 'daily_tree'):
            return
            
        # Reload all tasks to update time format display
        self.load_daily_tasks()