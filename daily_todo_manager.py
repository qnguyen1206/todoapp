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
            
            # Update the stored date
            os.makedirs(os.path.dirname(self.DAILY_DATE_FILE), exist_ok=True)
            with open(self.DAILY_DATE_FILE, "w") as f:
                f.write(current_date)

    def create_daily_todo_widgets(self):
        """Create the Daily To Do List interface"""
        # Add button at bottom left - PACK THIS FIRST with side=BOTTOM so it's always visible
        daily_add_frame = ttk.Frame(self.daily_todo_frame)
        daily_add_frame.pack(side=tk.BOTTOM, pady=5, padx=10, fill=tk.X)
        ttk.Button(daily_add_frame, text="+ Add", command=self.add_daily_task).pack(side=tk.LEFT, padx=5)
        
        # Create Treeview for daily tasks with action columns
        self.daily_tree = ttk.Treeview(self.daily_todo_frame, columns=("Days", "Time", "Task", "Status", "Complete", "Edit", "Delete", "Original"), show="headings", height=6)
        self.daily_tree.heading("Days", text="Days")
        self.daily_tree.heading("Time", text="Time")
        self.daily_tree.heading("Task", text="Task")
        self.daily_tree.heading("Status", text="Status")
        self.daily_tree.heading("Complete", text="Complete")
        self.daily_tree.heading("Edit", text="Edit")
        self.daily_tree.heading("Delete", text="Delete")

        # Set column widths
        self.daily_tree.column("Days", width=120, minwidth=100)
        self.daily_tree.column("Time", width=140, minwidth=100)  # Wider for time ranges
        self.daily_tree.column("Task", width=200, minwidth=150, stretch=True)
        self.daily_tree.column("Status", width=90, minwidth=70)  # Wider for "In Progress"
        self.daily_tree.column("Complete", width=70, minwidth=60, stretch=False, anchor='center')
        self.daily_tree.column("Edit", width=50, minwidth=40, stretch=False, anchor='center')
        self.daily_tree.column("Delete", width=60, minwidth=50, stretch=False, anchor='center')

        # Hide the Original column (used for storing original task text)
        self.daily_tree.column("Original", width=0, minwidth=0, stretch=False)
        self.daily_tree.heading("Original", text="")
        
        # Bind click events for action buttons
        self.daily_tree.bind("<Button-1>", self.on_daily_tree_click)
        
        # Pack treeview to fill remaining space
        self.daily_tree.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

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
            elif col_name in ["Days", "Time", "Task", "Status"]:  # Any info column clicked - show notes
                self.show_daily_task_notes(item)

    def show_daily_task_notes(self, item):
        """Show details for the selected daily task"""
        try:
            # Check if any dialog is already open
            if self.parent_app.check_existing_dialog():
                return

            # Get task details from the Treeview
            values = self.daily_tree.item(item, 'values')
            if len(values) < 8:
                messagebox.showerror("Error", "Task data incomplete")
                return

            days_str = values[0]
            time_str = values[1]
            task_name = values[2]
            status = values[3]
            original_text = values[7]  # Original column
            
            # Create notes display dialog
            notes_dialog = tk.Toplevel(self.parent_app.root)
            notes_dialog.title(f"Daily Task Details: {task_name}")
            notes_dialog.geometry("450x300")
            notes_dialog.resizable(True, True)
            
            # Task details
            details_frame = ttk.Frame(notes_dialog)
            details_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
            
            ttk.Label(details_frame, text="Daily Task Details", font=('Helvetica', 12, 'bold')).pack(pady=(0, 10))

            # Days
            days_frame = ttk.Frame(details_frame)
            days_frame.pack(fill=tk.X, pady=2)
            ttk.Label(days_frame, text="Days:", font=('Helvetica', 10, 'bold')).pack(side=tk.LEFT)
            ttk.Label(days_frame, text=days_str).pack(side=tk.LEFT, padx=(10, 0))

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
            
            # Register dialog AFTER all widgets are created
            self.parent_app.register_dialog(notes_dialog)
            
        except Exception as e:
            messagebox.showerror("Error", f"Could not display task details: {str(e)}")

    def edit_daily_task_from_notes(self, notes_dialog, item):
        """Edit daily task from the notes dialog"""
        notes_dialog.destroy()
        # Select the item in the daily tree and call edit
        self.daily_tree.selection_set(item)
        self.edit_daily_task()

    def get_current_day_abbr(self):
        """Get current day abbreviation (Mon, Tue, etc.)"""
        day_map = {
            0: "Mon",
            1: "Tue",
            2: "Wed",
            3: "Thu",
            4: "Fri",
            5: "Sat",
            6: "Sun"
        }
        return day_map[datetime.now().weekday()]

    def load_daily_tasks(self):
        """Load daily tasks into the Treeview, sorted by time, filtered by current day"""
        # Clear existing items
        if hasattr(self, 'daily_tree'):
            self.daily_tree.delete(*self.daily_tree.get_children())

        if not os.path.exists(self.DAILY_TASK_FILE):
            with open(self.DAILY_TASK_FILE, "w") as f:
                pass
            return

        # Get current day abbreviation
        current_day = self.get_current_day_abbr()

        # Read all tasks and filter by current day
        tasks = []
        with open(self.DAILY_TASK_FILE, "r") as file:
            for line in file:
                task_text = line.strip()
                if task_text:
                    # Check if task is scheduled for today
                    clean_task = task_text.replace("[COMPLETED] ", "")
                    days_time_pattern = r"^([A-Za-z,]+)\s+(\d{2}:\d{2}) - (.+)$"
                    match = re.match(days_time_pattern, clean_task)

                    if match:
                        days_str = match.group(1)
                        scheduled_days = days_str.split(',')
                        # Only add if scheduled for current day
                        if current_day in scheduled_days:
                            tasks.append(task_text)
                    else:
                        # Old format without days - show every day
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

            # Parse task to extract time (try formats in order of specificity)
            days_time_range_pattern = r"^([A-Za-z,]+)\s+(\d{2}:\d{2})-(\d{2}:\d{2}) - (.+)$"
            days_time_pattern = r"^([A-Za-z,]+)\s+(\d{2}:\d{2}) - (.+)$"
            time_range_pattern = r"^(\d{2}:\d{2})-(\d{2}:\d{2}) - (.+)$"
            time_pattern = r"^(\d{2}:\d{2}) - (.+)$"

            match_days_range = re.match(days_time_range_pattern, clean_task)
            match_with_days = re.match(days_time_pattern, clean_task)
            match_time_range = re.match(time_range_pattern, clean_task)
            match_without_days = re.match(time_pattern, clean_task)

            if match_days_range:
                time_str = match_days_range.group(2)  # Use start time for sorting
                hour, minute = map(int, time_str.split(':'))
                return hour * 60 + minute
            elif match_with_days:
                time_str = match_with_days.group(2)
                hour, minute = map(int, time_str.split(':'))
                return hour * 60 + minute
            elif match_time_range:
                time_str = match_time_range.group(1)  # Use start time for sorting
                hour, minute = map(int, time_str.split(':'))
                return hour * 60 + minute
            elif match_without_days:
                time_str = match_without_days.group(1)
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
            if len(values) >= 8:
                original_text = values[7]  # Original column (now index 7)
                # Remove completion status for parsing
                clean_task = original_text.replace("[COMPLETED] ", "")

                # Parse task to extract time (try formats in order of specificity)
                days_time_range_pattern = r"^([A-Za-z,]+)\s+(\d{2}:\d{2})-(\d{2}:\d{2}) - (.+)$"
                days_time_pattern = r"^([A-Za-z,]+)\s+(\d{2}:\d{2}) - (.+)$"
                time_range_pattern = r"^(\d{2}:\d{2})-(\d{2}:\d{2}) - (.+)$"
                time_pattern = r"^(\d{2}:\d{2}) - (.+)$"

                match_days_range = re.match(days_time_range_pattern, clean_task)
                match_with_days = re.match(days_time_pattern, clean_task)
                match_time_range = re.match(time_range_pattern, clean_task)
                match_without_days = re.match(time_pattern, clean_task)

                if match_days_range:
                    time_str = match_days_range.group(2)  # Use start time for sorting
                    hour, minute = map(int, time_str.split(':'))
                    return hour * 60 + minute
                elif match_with_days:
                    time_str = match_with_days.group(2)
                    hour, minute = map(int, time_str.split(':'))
                    return hour * 60 + minute
                elif match_time_range:
                    time_str = match_time_range.group(1)  # Use start time for sorting
                    hour, minute = map(int, time_str.split(':'))
                    return hour * 60 + minute
                elif match_without_days:
                    time_str = match_without_days.group(1)
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
            # Determine the appropriate tag based on status (now index 3)
            status = values[3] if len(values) > 3 else "Pending"
            if status == "Completed":
                tag = "completed"
            elif status == "Overdue":
                tag = "overdue"
            elif status == "In Progress":
                tag = "in_progress"
            elif status == "Not Today":
                tag = "not_today"
            else:
                tag = "pending"

            self.daily_tree.insert("", tk.END, values=values, tags=(tag,))

    def is_task_scheduled_today(self, days_str):
        """Check if the task is scheduled for today based on the days string"""
        # Map day abbreviations to weekday numbers (Monday=0, Sunday=6)
        day_map = {
            'mon': 0, 'tue': 1, 'wed': 2, 'thu': 3, 'fri': 4, 'sat': 5, 'sun': 6
        }
        
        # Get today's weekday
        today_weekday = datetime.now().weekday()
        
        # Parse the days string (e.g., "Mon,Wed,Fri" or "Mon,Tue,Wed,Thu,Fri,Sat,Sun")
        scheduled_days = [d.strip().lower() for d in days_str.split(',')]
        
        # Check if today is in the scheduled days
        for day in scheduled_days:
            if day in day_map and day_map[day] == today_weekday:
                return True
        
        return False

    def add_daily_task_to_tree(self, task_text):
        """Add a single daily task to the Treeview"""
        # Check if task is completed (marked with [COMPLETED] prefix)
        is_completed = task_text.startswith("[COMPLETED] ")
        if is_completed:
            task_text = task_text.replace("[COMPLETED] ", "")

        # Parse task to extract days, time and task parts
        # New format with time range: Days HH:MM-HH:MM - Task (e.g., "Mon,Wed,Fri 09:00-10:00 - Meeting")
        # New format single time: Days HH:MM - Task (e.g., "Mon,Wed,Fri 09:00 - Meeting")
        # Old format: HH:MM - Task (for backward compatibility)
        days_time_range_pattern = r"^([A-Za-z,]+)\s+(\d{2}:\d{2})-(\d{2}:\d{2}) - (.+)$"
        days_time_pattern = r"^([A-Za-z,]+)\s+(\d{2}:\d{2}) - (.+)$"
        time_range_pattern = r"^(\d{2}:\d{2})-(\d{2}:\d{2}) - (.+)$"
        time_pattern = r"^(\d{2}:\d{2}) - (.+)$"

        match_days_range = re.match(days_time_range_pattern, task_text)
        match_with_days = re.match(days_time_pattern, task_text)
        match_time_range = re.match(time_range_pattern, task_text)
        match_without_days = re.match(time_pattern, task_text)

        end_time_str = None  # Will be set if there's an end time
        
        if match_days_range:
            # New format with days and time range
            days_str = match_days_range.group(1)
            time_str = match_days_range.group(2)
            end_time_str = match_days_range.group(3)
            task_only = match_days_range.group(4)
        elif match_with_days:
            # New format with days, single time
            days_str = match_with_days.group(1)
            time_str = match_with_days.group(2)
            task_only = match_with_days.group(3)
        elif match_time_range:
            # Time range without days - default to all days
            days_str = "Mon,Tue,Wed,Thu,Fri,Sat,Sun"
            time_str = match_time_range.group(1)
            end_time_str = match_time_range.group(2)
            task_only = match_time_range.group(3)
        elif match_without_days:
            # Old format without days - default to all days
            days_str = "Mon,Tue,Wed,Thu,Fri,Sat,Sun"
            time_str = match_without_days.group(1)
            task_only = match_without_days.group(2)
        else:
            # Task without proper format - default to all days and 00:00
            days_str = "Mon,Tue,Wed,Thu,Fri,Sat,Sun"
            time_str = "00:00"
            task_only = task_text

        # Format time for display based on user preference
        hour_24, minute = map(int, time_str.split(':'))
        if self.parent_app.use_24_hour.get():
            display_time = f"{hour_24:02d}:{minute:02d}"
            if end_time_str:
                end_hour_24, end_minute = map(int, end_time_str.split(':'))
                display_time += f" - {end_hour_24:02d}:{end_minute:02d}"
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
            
            if end_time_str:
                end_hour_24, end_minute = map(int, end_time_str.split(':'))
                if end_hour_24 == 0:
                    display_time += f" - 12:{end_minute:02d} AM"
                elif end_hour_24 < 12:
                    display_time += f" - {end_hour_24}:{end_minute:02d} AM"
                elif end_hour_24 == 12:
                    display_time += f" - 12:{end_minute:02d} PM"
                else:
                    display_time += f" - {end_hour_24-12}:{end_minute:02d} PM"
        
        # Check if today is in the scheduled days
        is_scheduled_today = self.is_task_scheduled_today(days_str)
        
        # Determine status
        if is_completed:
            status = "Completed"
            tag = "completed"
        elif not is_scheduled_today:
            # Task is not scheduled for today - show as "Not Today"
            status = "Not Today"
            tag = "not_today"
        else:
            # Check if deadline has passed for status
            current_time = datetime.now()
            current_hour = current_time.hour
            current_minute = current_time.minute
            current_time_minutes = current_hour * 60 + current_minute

            # Parse task time (use end time if available, otherwise start time)
            # For time ranges, task is overdue only after the end time
            check_time_str = end_time_str if end_time_str else time_str
            task_hour, task_minute = map(int, check_time_str.split(':'))
            task_time_minutes = task_hour * 60 + task_minute
            
            # Treat midnight (00:00) as end of day (23:59) for overdue comparison
            # Midnight tasks are never overdue during the same day
            if task_hour == 0 and task_minute == 0:
                task_time_minutes = 23 * 60 + 59  # 23:59

            if current_time_minutes > task_time_minutes:
                status = "Overdue"
                tag = "overdue"
            else:
                # Check if we're currently in the time range (for tasks with start-end times)
                if end_time_str:
                    start_hour, start_minute = map(int, time_str.split(':'))
                    start_time_minutes = start_hour * 60 + start_minute
                    if start_time_minutes <= current_time_minutes <= task_time_minutes:
                        status = "In Progress"
                        tag = "in_progress"
                    else:
                        status = "Pending"
                        tag = "pending"
                else:
                    status = "Pending"
                    tag = "pending"

        # Store original task text (with completion marker if applicable)
        original_with_completion = f"[COMPLETED] {task_text}" if is_completed else task_text

        # Insert into Treeview with action buttons (now includes Days column)
        item = self.daily_tree.insert("", tk.END, values=(days_str, display_time, task_only, status, "✓", "✎", "✗", original_with_completion), tags=(tag,))
        
        # Configure colors
        self.daily_tree.tag_configure("overdue", foreground="red")
        self.daily_tree.tag_configure("pending", foreground="black")
        self.daily_tree.tag_configure("in_progress", foreground="blue")
        self.daily_tree.tag_configure("completed", foreground="gray", font=('Helvetica', 10, 'overstrike'))
        self.daily_tree.tag_configure("not_today", foreground="gray")

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
            # Get original task text from the "Original" column (now index 7)
            values = self.daily_tree.item(item, 'values')
            if len(values) >= 8:  # Make sure we have the Original column
                original_text = values[7]  # Original column is now index 7

                # Skip updating if task is completed - preserve completed styling
                if original_text.startswith("[COMPLETED] ") or values[3] == "Completed":
                    # Ensure completed tasks maintain their styling
                    self.daily_tree.item(item, tags=("completed",))
                    continue

                # Remove any completion marker for parsing
                clean_text = original_text.replace("[COMPLETED] ", "")
                # Try formats: with days and time range, with days single time, time range only, single time only
                days_time_range_pattern = r"^([A-Za-z,]+)\s+(\d{2}:\d{2})-(\d{2}:\d{2}) - (.+)$"
                days_time_pattern = r"^([A-Za-z,]+)\s+(\d{2}:\d{2}) - (.+)$"
                time_range_pattern = r"^(\d{2}:\d{2})-(\d{2}:\d{2}) - (.+)$"
                time_pattern = r"^(\d{2}:\d{2}) - (.+)$"

                match_days_range = re.match(days_time_range_pattern, clean_text)
                match_with_days = re.match(days_time_pattern, clean_text)
                match_time_range = re.match(time_range_pattern, clean_text)
                match_without_days = re.match(time_pattern, clean_text)

                end_time_str = None
                
                if match_days_range:
                    days_str = match_days_range.group(1)
                    time_str = match_days_range.group(2)
                    end_time_str = match_days_range.group(3)
                elif match_with_days:
                    days_str = match_with_days.group(1)
                    time_str = match_with_days.group(2)
                elif match_time_range:
                    days_str = "Mon,Tue,Wed,Thu,Fri,Sat,Sun"
                    time_str = match_time_range.group(1)
                    end_time_str = match_time_range.group(2)
                elif match_without_days:
                    days_str = "Mon,Tue,Wed,Thu,Fri,Sat,Sun"  # Default to all days
                    time_str = match_without_days.group(1)
                else:
                    continue

                # Get current values
                current_values = list(values)
                
                # Check if task is scheduled for today
                is_scheduled_today = self.is_task_scheduled_today(days_str)
                
                if not is_scheduled_today:
                    # Task is not for today - show as "Not Today"
                    current_values[3] = "Not Today"
                    self.daily_tree.item(item, values=current_values, tags=("not_today",))
                    continue

                # Use end time for overdue check if available, otherwise start time
                check_time_str = end_time_str if end_time_str else time_str
                task_hour, task_minute = map(int, check_time_str.split(':'))
                task_time_minutes = task_hour * 60 + task_minute
                
                # Treat midnight (00:00) as end of day (23:59) for overdue comparison
                # Midnight tasks are never overdue during the same day
                if task_hour == 0 and task_minute == 0:
                    task_time_minutes = 23 * 60 + 59  # 23:59

                if current_time_minutes > task_time_minutes:
                    # Time has passed - update status and color
                    current_values[3] = "Overdue"  # Update status column (now index 3)
                    self.daily_tree.item(item, values=current_values, tags=("overdue",))
                else:
                    # Check if we're currently in the time range (for tasks with start-end times)
                    if end_time_str:
                        start_hour, start_minute = map(int, time_str.split(':'))
                        start_time_minutes = start_hour * 60 + start_minute
                        if start_time_minutes <= current_time_minutes <= task_time_minutes:
                            current_values[3] = "In Progress"
                            self.daily_tree.item(item, values=current_values, tags=("in_progress",))
                        else:
                            current_values[3] = "Pending"
                            self.daily_tree.item(item, values=current_values, tags=("pending",))
                    else:
                        # Time hasn't passed - update status and color
                        current_values[3] = "Pending"  # Update status column (now index 3)
                        self.daily_tree.item(item, values=current_values, tags=("pending",))

    def complete_daily_task(self):
        """Mark selected daily task as completed and cross it out"""
        selected = self.daily_tree.selection()
        if not selected:
            messagebox.showwarning("Warning", "Please select a task to complete")
            return

        # Get current values
        values = list(self.daily_tree.item(selected[0], 'values'))
        original_text = values[7]  # Original column (now index 7)

        # Skip if already completed
        if original_text.startswith("[COMPLETED] ") or values[3] == "Completed":
            messagebox.showinfo("Info", "Task is already completed!")
            return

        # Update status to "Completed"
        values[3] = "Completed"  # Status column (now index 3)

        # Mark original text as completed
        values[7] = f"[COMPLETED] {original_text}"

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

        # Get original task text from the "Original" column (now index 7)
        values = self.daily_tree.item(selected[0], 'values')
        if len(values) >= 8:  # Make sure we have the Original column
            original_text = values[7]  # Original column is now index 7
        else:
            messagebox.showerror("Error", "Unable to retrieve task data")
            return

        # Parse current task to extract days, time (and optional end time) and task parts
        days_time_range_pattern = r"^([A-Za-z,]+)\s+(\d{2}:\d{2})-(\d{2}:\d{2}) - (.+)$"
        days_time_pattern = r"^([A-Za-z,]+)\s+(\d{2}:\d{2}) - (.+)$"
        time_range_pattern = r"^(\d{2}:\d{2})-(\d{2}:\d{2}) - (.+)$"
        time_pattern = r"^(\d{2}:\d{2}) - (.+)$"

        match_days_range = re.match(days_time_range_pattern, original_text)
        match_with_days = re.match(days_time_pattern, original_text)
        match_time_range = re.match(time_range_pattern, original_text)
        match_without_days = re.match(time_pattern, original_text)

        current_end_time = None  # Will be set if there's an end time
        
        if match_days_range:
            current_days = match_days_range.group(1).split(',')
            current_time = match_days_range.group(2)
            current_end_time = match_days_range.group(3)
            current_task = match_days_range.group(4)
            current_hour, current_minute = current_time.split(":")
            current_end_hour, current_end_minute = current_end_time.split(":")
        elif match_with_days:
            current_days = match_with_days.group(1).split(',')
            current_time = match_with_days.group(2)
            current_task = match_with_days.group(3)
            current_hour, current_minute = current_time.split(":")
        elif match_time_range:
            current_days = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
            current_time = match_time_range.group(1)
            current_end_time = match_time_range.group(2)
            current_task = match_time_range.group(3)
            current_hour, current_minute = current_time.split(":")
            current_end_hour, current_end_minute = current_end_time.split(":")
        elif match_without_days:
            current_days = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
            current_time = match_without_days.group(1)
            current_task = match_without_days.group(2)
            current_hour, current_minute = current_time.split(":")
        else:
            # Task without proper format - default to all days and 00:00
            current_days = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
            current_time = "00:00"
            current_task = original_text
            current_hour = "00"
            current_minute = "00"
        
        # Create edit dialog (similar to add dialog)
        dialog = tk.Toplevel(self.parent_app.root)
        dialog.title("Edit Daily Task")
        dialog.geometry("500x420")
        dialog.resizable(False, False)

        # Task name
        ttk.Label(dialog, text="Task:").grid(row=0, column=0, padx=5, pady=10, sticky="w")
        task_entry = ttk.Entry(dialog, width=40)
        task_entry.grid(row=0, column=1, padx=5, pady=10, columnspan=3)
        task_entry.insert(0, current_task)

        # Days of week selection
        ttk.Label(dialog, text="Days:").grid(row=1, column=0, padx=5, pady=10, sticky="nw")
        days_frame = ttk.Frame(dialog)
        days_frame.grid(row=1, column=1, padx=5, pady=10, columnspan=3, sticky="w")

        day_vars = {}
        day_names = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
        day_labels = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]

        for i, (day, label) in enumerate(zip(day_names, day_labels)):
            var = tk.BooleanVar(master=dialog, value=(day in current_days))
            day_vars[day] = var
            cb = ttk.Checkbutton(days_frame, text=label, variable=var)
            cb.grid(row=i//2, column=i%2, sticky="w", padx=5, pady=2)
        
        # Start Time
        ttk.Label(dialog, text="Start Time:").grid(row=2, column=0, padx=5, pady=10, sticky="w")

        if self.parent_app.use_24_hour.get():
            # 24-hour format - Start time
            hour_var = tk.StringVar(master=dialog, value=current_hour)
            hour_combo = ttk.Combobox(dialog, textvariable=hour_var, width=5, state="readonly")
            hour_combo['values'] = [f"{i:02d}" for i in range(24)]
            hour_combo.grid(row=2, column=1, padx=(5, 0), pady=10, sticky="w")

            ttk.Label(dialog, text=":").grid(row=2, column=1, padx=(55, 0), pady=10, sticky="w")

            minute_var = tk.StringVar(master=dialog, value=current_minute)
            minute_combo = ttk.Combobox(dialog, textvariable=minute_var, width=5, state="readonly")
            minute_combo['values'] = [f"{i:02d}" for i in range(0, 60, 5)]
            minute_combo.grid(row=2, column=1, padx=(65, 0), pady=10, sticky="w")
            
            # End Time (optional) - 24 hour
            ttk.Label(dialog, text="End Time (optional):").grid(row=3, column=0, padx=5, pady=10, sticky="w")
            
            use_end_time_var = tk.BooleanVar(master=dialog, value=(current_end_time is not None))
            
            end_hour_val = current_end_hour if current_end_time else str(int(current_hour) + 1).zfill(2)
            end_minute_val = current_end_minute if current_end_time else "00"
            
            end_hour_var = tk.StringVar(master=dialog, value=end_hour_val)
            end_hour_combo = ttk.Combobox(dialog, textvariable=end_hour_var, width=5, 
                                          state="readonly" if current_end_time else "disabled")
            end_hour_combo['values'] = [f"{i:02d}" for i in range(24)]
            end_hour_combo.grid(row=3, column=1, padx=(5, 0), pady=10, sticky="w")

            ttk.Label(dialog, text=":").grid(row=3, column=1, padx=(55, 0), pady=10, sticky="w")

            end_minute_var = tk.StringVar(master=dialog, value=end_minute_val)
            end_minute_combo = ttk.Combobox(dialog, textvariable=end_minute_var, width=5,
                                            state="readonly" if current_end_time else "disabled")
            end_minute_combo['values'] = [f"{i:02d}" for i in range(0, 60, 5)]
            end_minute_combo.grid(row=3, column=1, padx=(65, 0), pady=10, sticky="w")
            
            def toggle_end_time():
                state = "readonly" if use_end_time_var.get() else "disabled"
                end_hour_combo.config(state=state)
                end_minute_combo.config(state=state)
            
            end_time_cb = ttk.Checkbutton(dialog, text="Enable", variable=use_end_time_var, command=toggle_end_time)
            end_time_cb.grid(row=3, column=1, padx=(125, 0), pady=10, sticky="w")
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

            hour_var = tk.StringVar(master=dialog, value=display_hour)
            hour_combo = ttk.Combobox(dialog, textvariable=hour_var, width=4, state="readonly")
            hour_combo['values'] = [f"{i}" for i in range(1, 13)]
            hour_combo.grid(row=2, column=1, padx=(5, 0), pady=10, sticky="w")

            ttk.Label(dialog, text=":").grid(row=2, column=1, padx=(45, 0), pady=10, sticky="w")

            minute_var = tk.StringVar(master=dialog, value=current_minute)
            minute_combo = ttk.Combobox(dialog, textvariable=minute_var, width=4, state="readonly")
            minute_combo['values'] = [f"{i:02d}" for i in range(0, 60, 5)]
            minute_combo.grid(row=2, column=1, padx=(55, 0), pady=10, sticky="w")

            period_var = tk.StringVar(master=dialog, value=period)
            period_combo = ttk.Combobox(dialog, textvariable=period_var, width=4, state="readonly")
            period_combo['values'] = ["AM", "PM"]
            period_combo.grid(row=2, column=1, padx=(105, 0), pady=10, sticky="w")
            
            # End Time (optional) - 12 hour
            ttk.Label(dialog, text="End Time (optional):").grid(row=3, column=0, padx=5, pady=10, sticky="w")
            
            use_end_time_var = tk.BooleanVar(master=dialog, value=(current_end_time is not None))
            
            # Convert end time to 12-hour if exists
            if current_end_time:
                end_hour_24 = int(current_end_hour)
                if end_hour_24 == 0:
                    end_display_hour = "12"
                    end_period = "AM"
                elif end_hour_24 < 12:
                    end_display_hour = str(end_hour_24)
                    end_period = "AM"
                elif end_hour_24 == 12:
                    end_display_hour = "12"
                    end_period = "PM"
                else:
                    end_display_hour = str(end_hour_24 - 12)
                    end_period = "PM"
            else:
                # Default to 1 hour after start
                end_display_hour = str(int(display_hour) + 1) if int(display_hour) < 12 else "1"
                end_period = period
            
            end_hour_var = tk.StringVar(master=dialog, value=end_display_hour)
            end_hour_combo = ttk.Combobox(dialog, textvariable=end_hour_var, width=4,
                                          state="readonly" if current_end_time else "disabled")
            end_hour_combo['values'] = [f"{i}" for i in range(1, 13)]
            end_hour_combo.grid(row=3, column=1, padx=(5, 0), pady=10, sticky="w")

            ttk.Label(dialog, text=":").grid(row=3, column=1, padx=(45, 0), pady=10, sticky="w")

            end_minute_var = tk.StringVar(master=dialog, value=current_end_minute if current_end_time else "00")
            end_minute_combo = ttk.Combobox(dialog, textvariable=end_minute_var, width=4,
                                            state="readonly" if current_end_time else "disabled")
            end_minute_combo['values'] = [f"{i:02d}" for i in range(0, 60, 5)]
            end_minute_combo.grid(row=3, column=1, padx=(55, 0), pady=10, sticky="w")

            end_period_var = tk.StringVar(master=dialog, value=end_period if current_end_time else period)
            end_period_combo = ttk.Combobox(dialog, textvariable=end_period_var, width=4,
                                            state="readonly" if current_end_time else "disabled")
            end_period_combo['values'] = ["AM", "PM"]
            end_period_combo.grid(row=3, column=1, padx=(105, 0), pady=10, sticky="w")
            
            def toggle_end_time():
                state = "readonly" if use_end_time_var.get() else "disabled"
                end_hour_combo.config(state=state)
                end_minute_combo.config(state=state)
                end_period_combo.config(state=state)
            
            end_time_cb = ttk.Checkbutton(dialog, text="Enable", variable=use_end_time_var, command=toggle_end_time)
            end_time_cb.grid(row=3, column=1, padx=(160, 0), pady=10, sticky="w")
        
        result = {"task": None}

        def validate_and_save():
            task_text = task_entry.get().strip()
            if not task_text:
                messagebox.showerror("Error", "Please enter a task name")
                return

            # Get selected days
            selected_days = [day for day, var in day_vars.items() if var.get()]
            if not selected_days:
                messagebox.showerror("Error", "Please select at least one day")
                return

            # Sort days in week order
            day_order = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
            selected_days.sort(key=lambda x: day_order.index(x))
            days_str = ",".join(selected_days)

            # Format start time based on selected format
            if self.parent_app.use_24_hour.get():
                # 24-hour format
                if not hour_var.get() or not minute_var.get():
                    messagebox.showerror("Error", "Please select both hour and minute for start time")
                    return
                start_time_str = f"{hour_var.get()}:{minute_var.get()}"
                
                # Check end time if enabled
                if use_end_time_var.get():
                    if not end_hour_var.get() or not end_minute_var.get():
                        messagebox.showerror("Error", "Please select both hour and minute for end time")
                        return
                    end_time_str = f"{end_hour_var.get()}:{end_minute_var.get()}"
                    time_str = f"{start_time_str}-{end_time_str}"
                else:
                    time_str = start_time_str
            else:
                # 12-hour format - convert to 24-hour for storage
                if not hour_var.get() or not minute_var.get() or not period_var.get():
                    messagebox.showerror("Error", "Please select hour, minute, and AM/PM for start time")
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

                start_time_str = f"{hour:02d}:{minute}"
                
                # Check end time if enabled
                if use_end_time_var.get():
                    if not end_hour_var.get() or not end_minute_var.get() or not end_period_var.get():
                        messagebox.showerror("Error", "Please select hour, minute, and AM/PM for end time")
                        return
                    
                    end_hour = int(end_hour_var.get())
                    end_minute = end_minute_var.get()
                    end_period = end_period_var.get()

                    if end_period == "AM":
                        if end_hour == 12:
                            end_hour = 0
                    else:  # PM
                        if end_hour != 12:
                            end_hour += 12

                    end_time_str = f"{end_hour:02d}:{end_minute}"
                    time_str = f"{start_time_str}-{end_time_str}"
                else:
                    time_str = start_time_str

            # Combine days, time and task in new format: DAYS TIME - TASK
            full_task = f"{days_str} {time_str} - {task_text}"

            result["task"] = full_task
            dialog.destroy()
        
        def cancel():
            dialog.destroy()

        # Buttons
        button_frame = ttk.Frame(dialog)
        button_frame.grid(row=4, column=0, columnspan=4, pady=20)
        
        ttk.Button(button_frame, text="Save", command=validate_and_save).pack(side=tk.LEFT, padx=5)
        ttk.Button(button_frame, text="Cancel", command=cancel).pack(side=tk.LEFT, padx=5)
        
        # Register dialog AFTER all widgets are created
        self.parent_app.register_dialog(dialog)
        
        # Focus on task entry
        task_entry.focus()

        # Bind the Return key to the validate_and_save function
        dialog.bind('<Return>', lambda e: validate_and_save())

        # Wait for dialog to close
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
        dialog.geometry("500x420")
        dialog.resizable(False, False)

        # Task name
        ttk.Label(dialog, text="Task:").grid(row=0, column=0, padx=5, pady=10, sticky="w")
        task_entry = ttk.Entry(dialog, width=40)
        task_entry.grid(row=0, column=1, padx=5, pady=10, columnspan=3)

        # Days of week selection
        ttk.Label(dialog, text="Days:").grid(row=1, column=0, padx=5, pady=10, sticky="nw")
        days_frame = ttk.Frame(dialog)
        days_frame.grid(row=1, column=1, padx=5, pady=10, columnspan=3, sticky="w")

        day_vars = {}
        day_names = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
        day_labels = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]

        # Default to all days selected
        for i, (day, label) in enumerate(zip(day_names, day_labels)):
            var = tk.BooleanVar(master=dialog, value=True)
            day_vars[day] = var
            cb = ttk.Checkbutton(days_frame, text=label, variable=var)
            cb.grid(row=i//2, column=i%2, sticky="w", padx=5, pady=2)
        
        # Start Time (required)
        ttk.Label(dialog, text="Start Time:").grid(row=2, column=0, padx=5, pady=10, sticky="w")

        if self.parent_app.use_24_hour.get():
            # 24-hour format - Start time
            hour_var = tk.StringVar(master=dialog, value="09")
            hour_combo = ttk.Combobox(dialog, textvariable=hour_var, width=5, state="readonly")
            hour_combo['values'] = [f"{i:02d}" for i in range(24)]
            hour_combo.grid(row=2, column=1, padx=(5, 0), pady=10, sticky="w")

            ttk.Label(dialog, text=":").grid(row=2, column=1, padx=(55, 0), pady=10, sticky="w")

            minute_var = tk.StringVar(master=dialog, value="00")
            minute_combo = ttk.Combobox(dialog, textvariable=minute_var, width=5, state="readonly")
            minute_combo['values'] = [f"{i:02d}" for i in range(0, 60, 5)]
            minute_combo.grid(row=2, column=1, padx=(65, 0), pady=10, sticky="w")
            
            # End Time (optional) - 24 hour
            ttk.Label(dialog, text="End Time (optional):").grid(row=3, column=0, padx=5, pady=10, sticky="w")
            
            use_end_time_var = tk.BooleanVar(master=dialog, value=False)
            
            end_hour_var = tk.StringVar(master=dialog, value="10")
            end_hour_combo = ttk.Combobox(dialog, textvariable=end_hour_var, width=5, state="disabled")
            end_hour_combo['values'] = [f"{i:02d}" for i in range(24)]
            end_hour_combo.grid(row=3, column=1, padx=(5, 0), pady=10, sticky="w")

            ttk.Label(dialog, text=":").grid(row=3, column=1, padx=(55, 0), pady=10, sticky="w")

            end_minute_var = tk.StringVar(master=dialog, value="00")
            end_minute_combo = ttk.Combobox(dialog, textvariable=end_minute_var, width=5, state="disabled")
            end_minute_combo['values'] = [f"{i:02d}" for i in range(0, 60, 5)]
            end_minute_combo.grid(row=3, column=1, padx=(65, 0), pady=10, sticky="w")
            
            def toggle_end_time():
                state = "readonly" if use_end_time_var.get() else "disabled"
                end_hour_combo.config(state=state)
                end_minute_combo.config(state=state)
            
            end_time_cb = ttk.Checkbutton(dialog, text="Enable", variable=use_end_time_var, command=toggle_end_time)
            end_time_cb.grid(row=3, column=1, padx=(125, 0), pady=10, sticky="w")
        else:
            # 12-hour format - Start time
            hour_var = tk.StringVar(master=dialog, value="9")
            hour_combo = ttk.Combobox(dialog, textvariable=hour_var, width=4, state="readonly")
            hour_combo['values'] = [f"{i}" for i in range(1, 13)]
            hour_combo.grid(row=2, column=1, padx=(5, 0), pady=10, sticky="w")

            ttk.Label(dialog, text=":").grid(row=2, column=1, padx=(45, 0), pady=10, sticky="w")

            minute_var = tk.StringVar(master=dialog, value="00")
            minute_combo = ttk.Combobox(dialog, textvariable=minute_var, width=4, state="readonly")
            minute_combo['values'] = [f"{i:02d}" for i in range(0, 60, 5)]
            minute_combo.grid(row=2, column=1, padx=(55, 0), pady=10, sticky="w")

            period_var = tk.StringVar(master=dialog, value="AM")
            period_combo = ttk.Combobox(dialog, textvariable=period_var, width=4, state="readonly")
            period_combo['values'] = ["AM", "PM"]
            period_combo.grid(row=2, column=1, padx=(105, 0), pady=10, sticky="w")
            
            # End Time (optional) - 12 hour
            ttk.Label(dialog, text="End Time (optional):").grid(row=3, column=0, padx=5, pady=10, sticky="w")
            
            use_end_time_var = tk.BooleanVar(master=dialog, value=False)
            
            end_hour_var = tk.StringVar(master=dialog, value="10")
            end_hour_combo = ttk.Combobox(dialog, textvariable=end_hour_var, width=4, state="disabled")
            end_hour_combo['values'] = [f"{i}" for i in range(1, 13)]
            end_hour_combo.grid(row=3, column=1, padx=(5, 0), pady=10, sticky="w")

            ttk.Label(dialog, text=":").grid(row=3, column=1, padx=(45, 0), pady=10, sticky="w")

            end_minute_var = tk.StringVar(master=dialog, value="00")
            end_minute_combo = ttk.Combobox(dialog, textvariable=end_minute_var, width=4, state="disabled")
            end_minute_combo['values'] = [f"{i:02d}" for i in range(0, 60, 5)]
            end_minute_combo.grid(row=3, column=1, padx=(55, 0), pady=10, sticky="w")

            end_period_var = tk.StringVar(master=dialog, value="AM")
            end_period_combo = ttk.Combobox(dialog, textvariable=end_period_var, width=4, state="disabled")
            end_period_combo['values'] = ["AM", "PM"]
            end_period_combo.grid(row=3, column=1, padx=(105, 0), pady=10, sticky="w")
            
            def toggle_end_time():
                state = "readonly" if use_end_time_var.get() else "disabled"
                end_hour_combo.config(state=state)
                end_minute_combo.config(state=state)
                end_period_combo.config(state=state)
            
            end_time_cb = ttk.Checkbutton(dialog, text="Enable", variable=use_end_time_var, command=toggle_end_time)
            end_time_cb.grid(row=3, column=1, padx=(160, 0), pady=10, sticky="w")
        
        result = {"task": None, "time": None}

        def validate_and_add():
            task_text = task_entry.get().strip()
            if not task_text:
                messagebox.showerror("Error", "Please enter a task name")
                return

            # Get selected days
            selected_days = [day for day, var in day_vars.items() if var.get()]
            if not selected_days:
                messagebox.showerror("Error", "Please select at least one day")
                return

            # Sort days in week order
            day_order = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
            selected_days.sort(key=lambda x: day_order.index(x))
            days_str = ",".join(selected_days)

            # Format start time based on selected format
            if self.parent_app.use_24_hour.get():
                # 24-hour format
                if not hour_var.get() or not minute_var.get():
                    messagebox.showerror("Error", "Please select both hour and minute for start time")
                    return
                start_time_str = f"{hour_var.get()}:{minute_var.get()}"
                
                # Check end time if enabled
                if use_end_time_var.get():
                    if not end_hour_var.get() or not end_minute_var.get():
                        messagebox.showerror("Error", "Please select both hour and minute for end time")
                        return
                    end_time_str = f"{end_hour_var.get()}:{end_minute_var.get()}"
                    time_str = f"{start_time_str}-{end_time_str}"
                else:
                    time_str = start_time_str
            else:
                # 12-hour format - convert to 24-hour for storage
                if not hour_var.get() or not minute_var.get() or not period_var.get():
                    messagebox.showerror("Error", "Please select hour, minute, and AM/PM for start time")
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

                start_time_str = f"{hour:02d}:{minute}"
                
                # Check end time if enabled
                if use_end_time_var.get():
                    if not end_hour_var.get() or not end_minute_var.get() or not end_period_var.get():
                        messagebox.showerror("Error", "Please select hour, minute, and AM/PM for end time")
                        return
                    
                    end_hour = int(end_hour_var.get())
                    end_minute = end_minute_var.get()
                    end_period = end_period_var.get()

                    if end_period == "AM":
                        if end_hour == 12:
                            end_hour = 0
                    else:  # PM
                        if end_hour != 12:
                            end_hour += 12

                    end_time_str = f"{end_hour:02d}:{end_minute}"
                    time_str = f"{start_time_str}-{end_time_str}"
                else:
                    time_str = start_time_str

            # Combine days, time and task in new format: DAYS TIME - TASK
            full_task = f"{days_str} {time_str} - {task_text}"

            result["task"] = full_task
            result["time"] = time_str
            dialog.destroy()
        
        def cancel():
            dialog.destroy()

        # Buttons
        button_frame = ttk.Frame(dialog)
        button_frame.grid(row=4, column=0, columnspan=4, pady=20)
        
        ttk.Button(button_frame, text="Add", command=validate_and_add).pack(side=tk.LEFT, padx=5)
        ttk.Button(button_frame, text="Cancel", command=cancel).pack(side=tk.LEFT, padx=5)
        
        # Register dialog AFTER all widgets are created
        self.parent_app.register_dialog(dialog)
        
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
                # Get the original task text stored in the "Original" column (now index 7)
                values = self.daily_tree.item(item, 'values')
                if len(values) >= 8:  # Make sure we have the Original column
                    original_text = values[7]  # Original column is now index 7
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