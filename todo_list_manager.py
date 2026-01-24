"""
ToDo List Manager Module for TODO App
Contains all functionality for the main To Do Task List Panel including task creation,
editing, completion tracking, and task management with notes support.
"""

import os
import tkinter as tk
from tkinter import ttk, messagebox
from tkcalendar import DateEntry
from datetime import datetime, timedelta
from pathlib import Path
import re


class ToDoListManager:
    def __init__(self, parent_app, todo_frame):
        self.parent_app = parent_app
        self.todo_frame = todo_frame
        
        # TODO file path - Use home directory
        self.TODO_FILE = str(Path.home()) + "/TODOapp/todo.txt"
        
        # Task data storage for notes and extended information
        self.task_data = {}
        
        # Create todo list widgets
        self.create_todo_widgets()

    def create_todo_widgets(self):
        """Create the To Do List interface"""
        # Task list inside its frame with action columns
        self.tree = ttk.Treeview(self.todo_frame, columns=("Task", "Due Date", "Due Time", "Priority", "Finish", "Edit", "Delete"), show="headings")
        
        # Configure main columns
        for col, width in [("Task", 280), ("Due Date", 100), ("Due Time", 80), ("Priority", 70)]:
            self.tree.heading(col, text=col, command=lambda c=col: self.sort_column(c, False))
            self.tree.column(col, width=width, minwidth=60, stretch=(col=="Task"))
        
        # Configure action columns
        for col, symbol in [("Finish", "Finish"), ("Edit", "Edit"), ("Delete", "Delete")]:
            self.tree.heading(col, text=symbol)
            self.tree.column(col, width=60, minwidth=50, stretch=False, anchor='center')
        
        # Bind click events for action buttons
        self.tree.bind("<Button-1>", self.on_tree_click)
        
        self.tree.pack(pady=10, padx=10, fill=tk.BOTH, expand=True)
        
        # Configure row colors once at initialization
        self.tree.tag_configure("overdue", foreground="red")
        self.tree.tag_configure("today", foreground="orange")

        # Add button at bottom left
        control_frame = ttk.Frame(self.todo_frame)
        control_frame.pack(pady=5, padx=10, fill=tk.X)
        ttk.Button(control_frame, text="+ Add Task", command=self.add_task_dialog).pack(side=tk.LEFT, padx=5)
        ttk.Button(control_frame, text="+ Add Multiple Tasks", command=self.add_multiple_tasks_dialog).pack(side=tk.LEFT, padx=5)

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
            # Check if any dialog is already open
            if self.parent_app.check_existing_dialog():
                return
            
            # Get the full task data from our dictionary
            if item not in self.task_data:
                messagebox.showerror("Error", "Task data not found")
                return
                
            full_data = self.task_data[item]
            task_name = full_data[0]
            # New format: (task, date, time, priority, notes) - notes is index 4
            notes = full_data[4] if len(full_data) > 4 else ""
            
            # Create notes display dialog
            notes_dialog = tk.Toplevel(self.parent_app.root)
            notes_dialog.title(f"Task Notes: {task_name}")
            notes_dialog.geometry("450x350")
            notes_dialog.resizable(True, True)
            
            # Register this dialog globally
            self.parent_app.register_dialog(notes_dialog)
            
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
            ttk.Button(button_frame, text="Close", command=notes_dialog.destroy).pack(side=tk.RIGHT, padx=5)
            
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
            # Sort by date, then by time
            def date_time_key(x):
                child = x[1]
                date_str = self.tree.set(child, "Due Date")
                time_str = self.tree.set(child, "Due Time")
                date_val = datetime.strptime(date_str, "%m-%d-%Y")
                # Parse time, use 23:59 for empty time so tasks without time sort last
                if time_str and time_str != "--:--":
                    try:
                        time_parts = self.parse_display_time_to_24h(time_str)
                        if time_parts:
                            date_val = date_val.replace(hour=time_parts[0], minute=time_parts[1])
                        else:
                            date_val = date_val.replace(hour=23, minute=59)
                    except:
                        date_val = date_val.replace(hour=23, minute=59)
                else:
                    date_val = date_val.replace(hour=23, minute=59)
                return date_val
            tasks.sort(key=date_time_key, reverse=reverse)
        elif column == "Due Time":
            def time_key(x):
                time_str = x[0]
                if not time_str or time_str == "--:--":
                    return (1, 23, 59)  # Empty times sort last
                try:
                    time_parts = self.parse_display_time_to_24h(time_str)
                    if time_parts:
                        return (0, time_parts[0], time_parts[1])
                except:
                    pass
                return (1, 23, 59)
            tasks.sort(key=time_key, reverse=reverse)
        elif column == "Priority":
            tasks.sort(key=lambda x: int(x[0]), reverse=reverse)
        else:
            tasks.sort(reverse=reverse)

        # Rearrange items in sorted positions
        for index, (val, child) in enumerate(tasks):
            self.tree.move(child, '', index)

        # Reverse sort next time
        self.tree.heading(column, command=lambda: self.sort_column(column, not reverse))
    
    def parse_display_time_to_24h(self, time_str):
        """Parse displayed time string back to 24-hour format (hour, minute) tuple"""
        if not time_str or time_str == "--:--":
            return None
        try:
            # Handle 12-hour format with AM/PM
            if 'AM' in time_str.upper() or 'PM' in time_str.upper():
                time_str_clean = time_str.upper().replace(' ', '')
                if 'AM' in time_str_clean:
                    time_part = time_str_clean.replace('AM', '')
                    is_pm = False
                else:
                    time_part = time_str_clean.replace('PM', '')
                    is_pm = True
                hour, minute = map(int, time_part.split(':'))
                if is_pm and hour != 12:
                    hour += 12
                elif not is_pm and hour == 12:
                    hour = 0
                return (hour, minute)
            else:
                # 24-hour format
                hour, minute = map(int, time_str.split(':'))
                return (hour, minute)
        except:
            return None

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
        # Check if any dialog is already open
        if self.parent_app.check_existing_dialog():
            return
            
        dialog = tk.Toplevel(self.parent_app.root)
        dialog.title("Add New Task")
        dialog.geometry("450x350")
        
        # Register this dialog globally
        self.parent_app.register_dialog(dialog)
        
        ttk.Label(dialog, text="Task:").grid(row=0, column=0, padx=5, pady=5, sticky="nw")
        task_entry = ttk.Entry(dialog, width=40)
        task_entry.grid(row=0, column=1, padx=5, pady=5)
        
        ttk.Label(dialog, text="Due Date:").grid(row=1, column=0, padx=5, pady=5, sticky="nw")
        date_entry = DateEntry(dialog,
                             date_pattern="mm-dd-yyyy",
                             background="darkblue",
                             foreground="white",
                             borderwidth=2)
        date_entry.grid(row=1, column=1, padx=5, pady=5, sticky="w")
        
        ttk.Label(dialog, text="Due Time:").grid(row=2, column=0, padx=5, pady=5, sticky="nw")
        time_frame = ttk.Frame(dialog)
        time_frame.grid(row=2, column=1, padx=5, pady=5, sticky="w")
        
        # Check user's time format preference
        use_24_hour = True
        if hasattr(self.parent_app, 'use_24_hour'):
            use_24_hour = self.parent_app.use_24_hour.get()
        
        hour_var = tk.StringVar(master=dialog, value="")
        minute_var = tk.StringVar(master=dialog, value="")
        ampm_var = tk.StringVar(master=dialog, value="AM")
        
        if use_24_hour:
            hour_spinbox = ttk.Spinbox(time_frame, from_=0, to=23, width=3, textvariable=hour_var, format="%02.0f")
        else:
            hour_spinbox = ttk.Spinbox(time_frame, from_=1, to=12, width=3, textvariable=hour_var)
        hour_spinbox.pack(side=tk.LEFT)
        ttk.Label(time_frame, text=":").pack(side=tk.LEFT)
        minute_spinbox = ttk.Spinbox(time_frame, from_=0, to=59, width=3, textvariable=minute_var, format="%02.0f")
        minute_spinbox.pack(side=tk.LEFT)
        
        if not use_24_hour:
            ttk.Label(time_frame, text=" ").pack(side=tk.LEFT)
            ampm_combo = ttk.Combobox(time_frame, textvariable=ampm_var, values=["AM", "PM"], width=4, state="readonly")
            ampm_combo.pack(side=tk.LEFT)
        
        ttk.Label(time_frame, text=" (leave empty for no specific time)", foreground="gray").pack(side=tk.LEFT, padx=5)
        
        ttk.Label(dialog, text="Priority (1-5):").grid(row=3, column=0, padx=5, pady=5, sticky="nw")
        priority_entry = ttk.Spinbox(dialog, from_=1, to=5)
        priority_entry.grid(row=3, column=1, padx=5, pady=5, sticky="w")
        
        ttk.Label(dialog, text="Notes/Details:").grid(row=4, column=0, padx=5, pady=5, sticky="nw")
        notes_text = tk.Text(dialog, width=40, height=6, wrap=tk.WORD)
        notes_text.grid(row=4, column=1, padx=5, pady=5)
        
        def validate_and_add():
            date = self.parse_date(date_entry.get())
            if not date:
                messagebox.showerror("Error", "Invalid date format")
                return
            
            # Parse time (optional)
            due_time = ""
            hour_str = hour_var.get().strip()
            minute_str = minute_var.get().strip()
            if hour_str or minute_str:
                try:
                    hour = int(hour_str) if hour_str else 0
                    minute = int(minute_str) if minute_str else 0
                    
                    if use_24_hour:
                        if not (0 <= hour <= 23 and 0 <= minute <= 59):
                            raise ValueError
                    else:
                        # Convert 12-hour to 24-hour
                        if not (1 <= hour <= 12 and 0 <= minute <= 59):
                            raise ValueError
                        ampm = ampm_var.get()
                        if ampm == "PM" and hour != 12:
                            hour += 12
                        elif ampm == "AM" and hour == 12:
                            hour = 0
                    
                    due_time = f"{hour:02d}:{minute:02d}"
                except ValueError:
                    if use_24_hour:
                        messagebox.showerror("Error", "Invalid time format. Use 0-23 for hour and 0-59 for minute.")
                    else:
                        messagebox.showerror("Error", "Invalid time format. Use 1-12 for hour and 0-59 for minute.")
                    return
            
            try:
                priority = int(priority_entry.get())
                if not 1 <= priority <= 5:
                    raise ValueError
            except ValueError:
                messagebox.showerror("Error", "Priority must be 1-5")
                return
            
            notes = notes_text.get("1.0", tk.END).strip()
            self.add_task(task_entry.get(), date, due_time, priority, notes)
            dialog.destroy()

        ttk.Button(dialog, text="Add", command=validate_and_add).grid(row=5, columnspan=2, pady=10)

    def add_task(self, task, date, due_time, priority, notes="", check_duplicate=True):
        """Add a new task to the list"""
        tasks = self.load_tasks()
        # Ensure notes has a proper default value
        if not notes or notes.strip() == "":
            notes = "No notes"
        # Ensure due_time has a proper default value
        if not due_time or due_time.strip() == "":
            due_time = ""
        
        # Check for duplicate task names
        if check_duplicate:
            duplicate_index = self.find_duplicate_task(tasks, task)
            if duplicate_index is not None:
                # Found a duplicate - ask user what to do
                result = self.show_duplicate_dialog(task, tasks[duplicate_index])
                if result == "overwrite":
                    # Remove the old task and add the new one
                    tasks.pop(duplicate_index)
                elif result == "skip":
                    # Don't add the task
                    return False
                # If result == "create_new", just continue to add the task
        
        tasks.append((task, date, due_time, priority, notes))
        tasks = sorted(tasks, key=lambda x: self._task_sort_key(x))
        self.save_tasks(tasks)
        self.refresh_task_list()
        return True
    
    def find_duplicate_task(self, tasks, task_name):
        """Find if a task with the same name already exists. Returns index or None."""
        task_name_lower = task_name.lower().strip()
        for i, existing_task in enumerate(tasks):
            if existing_task[0].lower().strip() == task_name_lower:
                return i
        return None
    
    def show_duplicate_dialog(self, new_task_name, existing_task):
        """Show dialog when a duplicate task is found. Returns 'overwrite', 'create_new', or 'skip'."""
        existing_name, existing_date, existing_time, existing_priority, existing_notes = existing_task
        
        # Format existing task info for display
        time_display = f" at {existing_time}" if existing_time else ""
        existing_info = f"'{existing_name}'\nDue: {existing_date}{time_display}\nPriority: {existing_priority}"
        
        message = f"A task with the same name already exists:\n\n{existing_info}\n\nWhat would you like to do?"
        
        # Create a custom dialog with 3 options
        dialog = tk.Toplevel(self.parent_app.root)
        dialog.title("Duplicate Task Found")
        dialog.geometry("400x200")
        dialog.resizable(False, False)
        dialog.transient(self.parent_app.root)
        dialog.grab_set()
        
        result = {"value": "skip"}  # Default to skip
        
        # Message
        ttk.Label(dialog, text=message, wraplength=380, justify=tk.LEFT).pack(padx=20, pady=15)
        
        # Buttons
        button_frame = ttk.Frame(dialog)
        button_frame.pack(pady=10)
        
        def set_overwrite():
            result["value"] = "overwrite"
            dialog.destroy()
        
        def set_create_new():
            result["value"] = "create_new"
            dialog.destroy()
        
        def set_skip():
            result["value"] = "skip"
            dialog.destroy()
        
        ttk.Button(button_frame, text="Overwrite Existing", command=set_overwrite).pack(side=tk.LEFT, padx=5)
        ttk.Button(button_frame, text="Create New Anyway", command=set_create_new).pack(side=tk.LEFT, padx=5)
        ttk.Button(button_frame, text="Skip", command=set_skip).pack(side=tk.LEFT, padx=5)
        
        # Center the dialog
        dialog.update_idletasks()
        x = (dialog.winfo_screenwidth() // 2) - (dialog.winfo_width() // 2)
        y = (dialog.winfo_screenheight() // 2) - (dialog.winfo_height() // 2)
        dialog.geometry(f"+{x}+{y}")
        
        # Wait for dialog to close
        self.parent_app.root.wait_window(dialog)
        
        return result["value"]
    
    def show_bulk_duplicate_dialog(self, duplicates):
        """Show dialog when multiple duplicates are found during bulk add.
        Returns: 'overwrite_all', 'skip_all', 'create_all', 'ask', or 'cancel'"""
        
        dup_count = len(duplicates)
        dup_names = [d[0]['task'] for d in duplicates[:5]]  # Show first 5
        names_display = '\n'.join(f"• {name}" for name in dup_names)
        if dup_count > 5:
            names_display += f"\n... and {dup_count - 5} more"
        
        message = f"Found {dup_count} duplicate task(s):\n\n{names_display}\n\nHow would you like to handle these duplicates?"
        
        # Create a custom dialog
        dialog = tk.Toplevel(self.parent_app.root)
        dialog.title("Duplicate Tasks Found")
        dialog.geometry("450x280")
        dialog.resizable(False, False)
        dialog.transient(self.parent_app.root)
        dialog.grab_set()
        
        result = {"value": "cancel"}  # Default to cancel
        
        # Message
        ttk.Label(dialog, text=message, wraplength=420, justify=tk.LEFT).pack(padx=20, pady=15)
        
        # Buttons frame
        button_frame = ttk.Frame(dialog)
        button_frame.pack(pady=10, fill=tk.X, padx=20)
        
        def set_result(val):
            result["value"] = val
            dialog.destroy()
        
        # Row 1: Main actions
        row1 = ttk.Frame(button_frame)
        row1.pack(fill=tk.X, pady=3)
        ttk.Button(row1, text="Overwrite All", command=lambda: set_result("overwrite_all"), width=15).pack(side=tk.LEFT, padx=3)
        ttk.Button(row1, text="Skip All Duplicates", command=lambda: set_result("skip_all"), width=15).pack(side=tk.LEFT, padx=3)
        ttk.Button(row1, text="Create All Anyway", command=lambda: set_result("create_all"), width=15).pack(side=tk.LEFT, padx=3)
        
        # Row 2: Other options
        row2 = ttk.Frame(button_frame)
        row2.pack(fill=tk.X, pady=3)
        ttk.Button(row2, text="Ask For Each", command=lambda: set_result("ask"), width=15).pack(side=tk.LEFT, padx=3)
        ttk.Button(row2, text="Cancel", command=lambda: set_result("cancel"), width=15).pack(side=tk.RIGHT, padx=3)
        
        # Center the dialog
        dialog.update_idletasks()
        x = (dialog.winfo_screenwidth() // 2) - (dialog.winfo_width() // 2)
        y = (dialog.winfo_screenheight() // 2) - (dialog.winfo_height() // 2)
        dialog.geometry(f"+{x}+{y}")
        
        # Wait for dialog to close
        self.parent_app.root.wait_window(dialog)
        
        return result["value"]
    
    def _task_sort_key(self, task):
        """Generate sort key for a task (date, time, inverse priority)"""
        date_str = task[1]
        time_str = task[2] if len(task) > 2 else ""
        priority = task[3] if len(task) > 3 else task[2]  # Handle old format
        
        date_val = datetime.strptime(date_str, "%m-%d-%Y")
        
        # Parse time, use 23:59 for empty time so tasks without time sort last within the day
        if time_str and time_str.strip():
            try:
                hour, minute = map(int, time_str.split(':'))
                time_val = (0, hour, minute)  # 0 prefix means has time, sorts first
            except:
                time_val = (1, 23, 59)  # No valid time, sort last
        else:
            time_val = (1, 23, 59)  # No time specified, sort last within the day
        
        return (date_val, time_val, -int(priority))

    def add_multiple_tasks_dialog(self):
        """Show dialog to add multiple tasks at once"""
        # Check if any dialog is already open
        if self.parent_app.check_existing_dialog():
            return
            
        dialog = tk.Toplevel(self.parent_app.root)
        dialog.title("Add Multiple Tasks")
        dialog.geometry("700x700")  # Even larger to ensure buttons show
        dialog.minsize(600, 600)    # Larger minimum size
        dialog.resizable(True, True)
        
        # Register this dialog globally
        self.parent_app.register_dialog(dialog)
        
        # Create buttons FIRST at the bottom to ensure they're always visible
        button_frame = ttk.Frame(dialog)
        button_frame.pack(side=tk.BOTTOM, fill=tk.X, padx=10, pady=10)
        
        def add_all_tasks():
            """Parse and add all tasks with duplicate detection"""
            try:
                content = tasks_text.get("1.0", tk.END).strip()
                if not content:
                    messagebox.showwarning("Warning", "Please enter some tasks first")
                    return
                
                lines = [line.strip() for line in content.split('\n') if line.strip()]
                
                # First pass: parse all tasks and check for duplicates
                parsed_tasks = []
                parse_errors = []
                existing_tasks = self.load_tasks()
                duplicates = []
                
                for line in lines:
                    try:
                        task_info = self.parse_bulk_task_line(line)
                        dup_index = self.find_duplicate_task(existing_tasks, task_info['task'])
                        if dup_index is not None:
                            duplicates.append((task_info, existing_tasks[dup_index]))
                        parsed_tasks.append(task_info)
                    except Exception as e:
                        parse_errors.append(f"'{line}': {str(e)}")
                
                # If there are duplicates, ask user how to handle them
                duplicate_action = "ask"  # Default: ask for each
                if duplicates:
                    duplicate_action = self.show_bulk_duplicate_dialog(duplicates)
                    if duplicate_action == "cancel":
                        return  # User cancelled the whole operation
                
                # Second pass: add tasks based on duplicate handling preference
                added_count = 0
                skipped_count = 0
                overwritten_count = 0
                
                for task_info in parsed_tasks:
                    try:
                        # Check for duplicate
                        dup_index = self.find_duplicate_task(self.load_tasks(), task_info['task'])
                        
                        if dup_index is not None:
                            if duplicate_action == "skip_all":
                                skipped_count += 1
                                continue
                            elif duplicate_action == "overwrite_all":
                                # Remove old task first, then add new (skip duplicate check)
                                tasks = self.load_tasks()
                                tasks.pop(dup_index)
                                self.save_tasks(tasks)
                                self.add_task(task_info['task'], task_info['date'], 
                                            task_info.get('due_time', ''), task_info['priority'], 
                                            task_info['notes'], check_duplicate=False)
                                overwritten_count += 1
                                added_count += 1
                            elif duplicate_action == "create_all":
                                # Add without checking duplicates
                                self.add_task(task_info['task'], task_info['date'], 
                                            task_info.get('due_time', ''), task_info['priority'], 
                                            task_info['notes'], check_duplicate=False)
                                added_count += 1
                            else:  # "ask" - ask for each individual duplicate
                                result = self.add_task(task_info['task'], task_info['date'], 
                                                      task_info.get('due_time', ''), task_info['priority'], 
                                                      task_info['notes'], check_duplicate=True)
                                if result:
                                    added_count += 1
                                else:
                                    skipped_count += 1
                        else:
                            # No duplicate, just add
                            self.add_task(task_info['task'], task_info['date'], 
                                        task_info.get('due_time', ''), task_info['priority'], 
                                        task_info['notes'], check_duplicate=False)
                            added_count += 1
                    except Exception as e:
                        parse_errors.append(f"'{task_info['task']}': {str(e)}")
                
                # Show summary
                summary_parts = []
                if added_count > 0:
                    summary_parts.append(f"Added: {added_count}")
                if overwritten_count > 0:
                    summary_parts.append(f"Overwritten: {overwritten_count}")
                if skipped_count > 0:
                    summary_parts.append(f"Skipped (duplicates): {skipped_count}")
                
                summary = ", ".join(summary_parts) if summary_parts else "No tasks added"
                
                if parse_errors:
                    error_msg = f"{summary}\n\nErrors:\n" + '\n'.join(parse_errors[:5])
                    if len(parse_errors) > 5:
                        error_msg += f"\n... and {len(parse_errors) - 5} more errors"
                    messagebox.showwarning("Partial Success", error_msg)
                else:
                    messagebox.showinfo("Success", summary)
                
                if added_count > 0:
                    dialog.destroy()
                    
            except Exception as e:
                messagebox.showerror("Error", f"Failed to add tasks: {str(e)}")
        
        # Create prominent buttons at the bottom
        add_button = ttk.Button(button_frame, text="✓ Add All Tasks", command=add_all_tasks)
        add_button.pack(side=tk.LEFT, padx=10, pady=5)
        
        cancel_button = ttk.Button(button_frame, text="✗ Cancel", command=dialog.destroy)
        cancel_button.pack(side=tk.RIGHT, padx=10, pady=5)
        
        # Now create the main content frame ABOVE the buttons
        main_frame = ttk.Frame(dialog)
        main_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        
        # Instructions
        instructions = ttk.Label(main_frame, text="Enter multiple tasks (one per line). Use keywords for dates and priorities:", font=('Helvetica', 10, 'bold'))
        instructions.pack(anchor='w', pady=(0, 5))
        
        # Format help
        help_text = """Examples:
• Buy groceries due tomorrow - priority 3 - Need milk and bread
• Call dentist due at 2:30 PM priority 2
• Meeting due on next Friday 14:30 priority 1
• Submit report due by 09/20/2025 | urgent | Check formatting

Supported date formats: today, tomorrow, next monday, 09/15/2025, in 3 days
Time formats: 2:30 PM, 14:30, 10 AM (now saved as Due Time!)
Due phrases: "due at", "due on", "due by" are automatically removed from task names
Priority: 1=urgent/highest, 2=high, 3=medium, 4=low, 5=lowest (default)
Keywords: urgent/critical (=1), high/important (=2), medium/normal (=3), low/minor (=4)
Note: Duplicate task names will be detected and you'll be asked how to handle them."""
        
        help_label = ttk.Label(main_frame, text=help_text, font=('Helvetica', 8), foreground="gray")
        help_label.pack(anchor='w', pady=(0, 10))
        
        # Input area
        ttk.Label(main_frame, text="Tasks:", font=('Helvetica', 10, 'bold')).pack(anchor='w')
        
        # Text input with scrollbar
        text_frame = ttk.Frame(main_frame)
        text_frame.pack(fill=tk.BOTH, expand=True, pady=5)
        
        tasks_text = tk.Text(text_frame, wrap=tk.WORD, height=15, font=('Helvetica', 10))
        scrollbar = ttk.Scrollbar(text_frame, orient="vertical", command=tasks_text.yview)
        tasks_text.configure(yscrollcommand=scrollbar.set)
        
        tasks_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        
        # Preview area
        ttk.Label(main_frame, text="Preview (parsed tasks):", font=('Helvetica', 10, 'bold')).pack(anchor='w', pady=(10, 5))
        
        preview_frame = ttk.Frame(main_frame)
        preview_frame.pack(fill=tk.BOTH, expand=True, pady=5)
        
        preview_text = tk.Text(preview_frame, wrap=tk.WORD, height=6, font=('Helvetica', 9), state='disabled')  # Reduced height
        preview_scrollbar = ttk.Scrollbar(preview_frame, orient="vertical", command=preview_text.yview)
        preview_text.configure(yscrollcommand=preview_scrollbar.set)
        
        preview_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        preview_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        
        # Function to update preview
        def update_preview():
            """Update the preview with parsed tasks"""
            try:
                content = tasks_text.get("1.0", tk.END).strip()
                if not content:
                    preview_text.config(state='normal')
                    preview_text.delete("1.0", tk.END)
                    preview_text.insert("1.0", "No tasks entered yet...")
                    preview_text.config(state='disabled')
                    return
                
                lines = [line.strip() for line in content.split('\n') if line.strip()]
                parsed_tasks = []
                
                for i, line in enumerate(lines, 1):
                    try:
                        task_info = self.parse_bulk_task_line(line)
                        time_display = f" @ {task_info.get('due_time', '')}" if task_info.get('due_time') else ""
                        parsed_tasks.append(f"{i}. {task_info['task']} | {task_info['date']}{time_display} | Priority {task_info['priority']}")
                        if task_info['notes']:
                            parsed_tasks.append(f"   Notes: {task_info['notes']}")
                    except Exception as e:
                        parsed_tasks.append(f"{i}. ERROR: {line} - {str(e)}")
                
                preview_text.config(state='normal')
                preview_text.delete("1.0", tk.END)
                preview_text.insert("1.0", '\n'.join(parsed_tasks))
                preview_text.config(state='disabled')
                
            except Exception as e:
                preview_text.config(state='normal')
                preview_text.delete("1.0", tk.END)
                preview_text.insert("1.0", f"Preview error: {str(e)}")
                preview_text.config(state='disabled')
        
        # Bind text change to update preview
        def on_text_change(event=None):
            dialog.after_idle(update_preview)
        
        tasks_text.bind('<KeyRelease>', on_text_change)
        tasks_text.bind('<Button-1>', on_text_change)
        tasks_text.bind('<FocusOut>', on_text_change)
        
        # Initial preview
        update_preview()

    def parse_bulk_task_line(self, line):
        """Parse a single line from bulk task input into task components"""
        if not line.strip():
            raise ValueError("Empty line")
        
        # Default values
        today = datetime.now()
        task_info = {
            'task': line.strip(),
            'date': today.strftime("%m-%d-%Y"),
            'due_time': "",  # Optional due time
            'priority': 5,  # Default to lowest priority (5)
            'notes': ""
        }
        
        # Split by common delimiters to extract components
        delimiters = [' - ', ' | ', ' :: ', ' // ']
        parts = [line]
        
        for delimiter in delimiters:
            if delimiter in line:
                parts = [part.strip() for part in line.split(delimiter)]
                break
        
        # Extract task name (first part, will be refined)
        task_name = parts[0].strip()
        remaining_parts = parts[1:] if len(parts) > 1 else []
        
        # Clean up "due at" and "due on" phrases from task name and remaining parts
        task_name = self.clean_due_phrases(task_name)
        remaining_parts = [self.clean_due_phrases(part) for part in remaining_parts]
        
        # Process all parts to extract date, priority, time, and notes
        processed_parts = []
        
        for part in remaining_parts:
            if not part.strip():
                continue
                
            # Try to extract date
            date_result = self.extract_date_from_text(part)
            if date_result:
                task_info['date'] = date_result
                continue
            
            # Try to extract priority
            priority_result = self.extract_priority_from_text(part)
            if priority_result:
                task_info['priority'] = priority_result
                continue
            
            # Try to extract time - now store as due_time instead of notes
            time_result = self.extract_time_from_text(part)
            if time_result:
                task_info['due_time'] = time_result
                continue
            
            # If it's not a date, priority, or time, it's probably notes
            processed_parts.append(part)
        
        # Also check the task name itself for embedded date/priority/time info, but be more careful
        task_words = task_name.split()
        clean_task_words = []
        
        i = 0
        while i < len(task_words):
            word = task_words[i]
            
            # Check for multi-word date patterns first (like "next friday")
            if i < len(task_words) - 1:
                two_word = f"{word} {task_words[i + 1]}"
                date_result = self.extract_date_from_text(two_word)
                if date_result:
                    task_info['date'] = date_result
                    i += 2  # Skip both words
                    continue
            
            # Check for single word date
            date_result = self.extract_date_from_text(word)
            if date_result and len(word) > 2:  # Avoid single letters/numbers being treated as dates
                task_info['date'] = date_result
                i += 1
                continue
            
            # Check for time patterns
            time_result = self.extract_time_from_text(word)
            if time_result:
                # Store as due_time
                task_info['due_time'] = time_result
                i += 1
                continue
            
            # Check for priority keywords in task name, but only if it looks like priority
            if any(priority_word in word.lower() for priority_word in ['priority', 'urgent', 'high', 'low', 'medium']):
                priority_result = self.extract_priority_from_text(word)
                if priority_result:
                    task_info['priority'] = priority_result
                    i += 1
                    continue
            
            # Keep the word in the task name
            clean_task_words.append(word)
            i += 1
        
        # Reconstruct clean task name and apply final cleaning
        task_info['task'] = ' '.join(clean_task_words).strip()
        task_info['task'] = self.clean_due_phrases(task_info['task'])
        
        # Join remaining parts as notes
        if processed_parts:
            additional_notes = ' '.join(processed_parts).strip()
            if task_info['notes']:
                task_info['notes'] += f" | {additional_notes}"
            else:
                task_info['notes'] = additional_notes
        
        # Validation
        if not task_info['task']:
            raise ValueError("No task name found")
        
        return task_info

    def extract_date_from_text(self, text):
        """Extract date from text and return formatted date string"""
        text = text.lower().strip()
        today = datetime.now()
        
        # Handle relative dates
        if text in ['today']:
            return today.strftime("%m-%d-%Y")
        elif text in ['tomorrow']:
            return (today + timedelta(days=1)).strftime("%m-%d-%Y")
        elif text in ['yesterday']:
            return (today - timedelta(days=1)).strftime("%m-%d-%Y")
        elif 'next week' in text:
            return (today + timedelta(days=7)).strftime("%m-%d-%Y")
        elif text.startswith('in ') and text.endswith(' days'):
            try:
                days = int(text.split()[1])
                return (today + timedelta(days=days)).strftime("%m-%d-%Y")
            except:
                pass
        elif text.startswith('next '):
            # Handle "next monday", "next friday", etc.
            day_name = text.replace('next ', '')
            weekdays = ['monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday', 'sunday']
            if day_name in weekdays:
                target_weekday = weekdays.index(day_name)
                days_ahead = target_weekday - today.weekday()
                if days_ahead <= 0:  # Target day already happened this week
                    days_ahead += 7
                return (today + timedelta(days=days_ahead)).strftime("%m-%d-%Y")
        elif text.startswith('this '):
            # Handle "this friday", etc.
            day_name = text.replace('this ', '')
            weekdays = ['monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday', 'sunday']
            if day_name in weekdays:
                target_weekday = weekdays.index(day_name)
                days_ahead = target_weekday - today.weekday()
                if days_ahead < 0:  # If the day has passed this week, get next week's
                    days_ahead += 7
                return (today + timedelta(days=days_ahead)).strftime("%m-%d-%Y")
        
        # Handle absolute dates - improved patterns
        date_patterns = [
            r'(\d{1,2})[/-](\d{1,2})[/-](\d{4})',  # MM/DD/YYYY or MM-DD-YYYY
            r'(\d{4})[/-](\d{1,2})[/-](\d{1,2})',  # YYYY/MM/DD or YYYY-MM-DD
            r'(\d{1,2})[/-](\d{1,2})[/-](\d{2})',  # MM/DD/YY or MM-DD-YY
            r'(\d{1,2})\.(\d{1,2})\.(\d{4})',      # MM.DD.YYYY
            r'(\d{1,2})\.(\d{1,2})\.(\d{2})',      # MM.DD.YY
        ]
        
        for i, pattern in enumerate(date_patterns):
            match = re.search(pattern, text)
            if match:
                try:
                    groups = match.groups()
                    if i == 0 or i == 2 or i == 3 or i == 4:  # MM/DD/YYYY, MM/DD/YY, MM.DD.YYYY, MM.DD.YY
                        month, day, year = groups
                        if len(year) == 2:
                            year = f"20{year}" if int(year) < 50 else f"19{year}"
                    elif i == 1:  # YYYY/MM/DD or YYYY-MM-DD
                        year, month, day = groups
                    
                    # Validate and format
                    month, day, year = int(month), int(day), int(year)
                    if 1 <= month <= 12 and 1 <= day <= 31:
                        date_obj = datetime(year, month, day)
                        return date_obj.strftime("%m-%d-%Y")
                except Exception as e:
                    continue
        
        return None

    def extract_priority_from_text(self, text):
        """Extract priority from text and return priority number"""
        text = text.lower().strip()
        
        # Direct priority numbers (case insensitive)
        priority_patterns = [
            r'priority\s*(\d)',
            r'pri\s*(\d)',
            r'p\s*(\d)'
        ]
        
        for pattern in priority_patterns:
            priority_match = re.search(pattern, text)
            if priority_match:
                priority = int(priority_match.group(1))
                return priority if 1 <= priority <= 5 else 1
        
        # Priority keywords - corrected mapping (1 = highest, 5 = lowest)
        if any(word in text for word in ['urgent', 'critical', 'asap']):
            return 1  # Highest priority
        elif any(word in text for word in ['high', 'important']):
            return 2  # High priority
        elif any(word in text for word in ['medium', 'normal']):
            return 3  # Medium priority
        elif any(word in text for word in ['low', 'minor']):
            return 4  # Low priority
        
        # Check for standalone numbers that might be priority
        if text.isdigit():
            priority = int(text)
            return priority if 1 <= priority <= 5 else 1
        
        return None

    def extract_time_from_text(self, text):
        """Extract time from text and return formatted time string"""
        text = text.strip()
        
        # Time patterns to match
        time_patterns = [
            r'(\d{1,2}):(\d{2})\s*(am|pm|AM|PM)',  # 12:30 PM, 2:15 am
            r'(\d{1,2}):(\d{2})',                  # 14:30, 09:15 (24-hour)
            r'(\d{1,2})\s*(am|pm|AM|PM)',          # 2 PM, 9 am
            r'(\d{1,2})(\d{2})\s*(am|pm|AM|PM)',   # 230 PM, 915 am
            r'(\d{1,2})(\d{2})',                   # 1430, 0915 (24-hour without colon)
        ]
        
        for i, pattern in enumerate(time_patterns):
            match = re.search(pattern, text)
            if match:
                try:
                    groups = match.groups()
                    
                    if i == 0:  # HH:MM AM/PM
                        hour, minute, ampm = groups
                        hour, minute = int(hour), int(minute)
                        if ampm.lower() == 'pm' and hour != 12:
                            hour += 12
                        elif ampm.lower() == 'am' and hour == 12:
                            hour = 0
                        return f"{hour:02d}:{minute:02d}"
                        
                    elif i == 1:  # HH:MM (24-hour)
                        hour, minute = int(groups[0]), int(groups[1])
                        if 0 <= hour <= 23 and 0 <= minute <= 59:
                            return f"{hour:02d}:{minute:02d}"
                            
                    elif i == 2:  # H AM/PM
                        hour, ampm = int(groups[0]), groups[1]
                        if ampm.lower() == 'pm' and hour != 12:
                            hour += 12
                        elif ampm.lower() == 'am' and hour == 12:
                            hour = 0
                        return f"{hour:02d}:00"
                        
                    elif i == 3:  # HHMM AM/PM
                        hour, minute, ampm = int(groups[0]), int(groups[1]), groups[2]
                        if ampm.lower() == 'pm' and hour != 12:
                            hour += 12
                        elif ampm.lower() == 'am' and hour == 12:
                            hour = 0
                        if 0 <= hour <= 23 and 0 <= minute <= 59:
                            return f"{hour:02d}:{minute:02d}"
                            
                    elif i == 4:  # HHMM (24-hour)
                        if len(groups[0] + groups[1]) == 4:
                            hour, minute = int(groups[0]), int(groups[1])
                        elif len(groups[0] + groups[1]) == 3:
                            hour, minute = int(groups[0][0]), int(groups[0][1:] + groups[1])
                        else:
                            continue
                        if 0 <= hour <= 23 and 0 <= minute <= 59:
                            return f"{hour:02d}:{minute:02d}"
                            
                except (ValueError, IndexError):
                    continue
        
        return None

    def clean_due_phrases(self, text):
        """Remove 'due at', 'due on', etc. phrases from text"""
        if not text or not text.strip():
            return text
            
        # Patterns to remove (case insensitive)
        due_patterns = [
            r'\bdue\s+at\b',
            r'\bdue\s+on\b',
            r'\bdue\s+by\b',
            r'\bdue\b(?=\s+\d)',  # "due" followed by date/time
        ]
        
        cleaned_text = text
        for pattern in due_patterns:
            cleaned_text = re.sub(pattern, '', cleaned_text, flags=re.IGNORECASE)
        
        # Clean up extra whitespace
        cleaned_text = re.sub(r'\s+', ' ', cleaned_text).strip()
        
        return cleaned_text

    def remove_task(self):
        """Remove/Complete selected task"""
        selected = self.tree.selection()
        if not selected:
            messagebox.showwarning("Warning", "Please select a task to remove")
            return
        
        # Get the stored task data directly from our dictionary
        item_id = selected[0]
        if item_id not in self.task_data:
            messagebox.showerror("Error", "Task data not found")
            return
        
        task_to_remove = self.task_data[item_id]
        
        tasks = self.load_tasks()
        task_found = None
        index = -1
        
        # Find the task by matching all fields
        for i, task in enumerate(tasks):
            if task[:4] == task_to_remove[:4]:  # Match task, date, time, priority
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
        # Check if any dialog is already open
        if self.parent_app.check_existing_dialog():
            return
            
        selected = self.tree.selection()
        if not selected:
            messagebox.showwarning("Warning", "Please select a task to edit")
            return
        
        # Get the stored task data directly from our dictionary
        item_id = selected[0]
        if item_id not in self.task_data:
            messagebox.showerror("Error", "Task data not found")
            return
        
        task_to_edit = self.task_data[item_id]

        tasks = self.load_tasks()
        task_found = None
        index = -1
        
        # Find the task by matching all fields
        for i, task in enumerate(tasks):
            if task[:4] == task_to_edit[:4]:  # Match task, date, time, priority
                task_found = task
                index = i
                break
        
        if task_found is None:
            messagebox.showerror("Error", "Task not found in data file")
            return
        
        dialog = tk.Toplevel(self.parent_app.root)
        dialog.title("Edit Task")
        dialog.geometry("450x400")
        
        # Register this dialog globally
        self.parent_app.register_dialog(dialog)
        
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
        date_entry.grid(row=1, column=1, padx=5, pady=5, sticky="w")
        date_entry.set_date(datetime.strptime(task_found[1], "%m-%d-%Y"))
        
        ttk.Label(dialog, text="Due Time:").grid(row=2, column=0, padx=5, pady=5, sticky="nw")
        time_frame = ttk.Frame(dialog)
        time_frame.grid(row=2, column=1, padx=5, pady=5, sticky="w")
        
        # Check user's time format preference
        use_24_hour = True
        if hasattr(self.parent_app, 'use_24_hour'):
            use_24_hour = self.parent_app.use_24_hour.get()
        
        # Parse existing time (stored in 24-hour format)
        existing_time = task_found[2] if len(task_found) > 2 else ""
        existing_hour = ""
        existing_minute = ""
        existing_ampm = "AM"
        if existing_time and ':' in existing_time:
            try:
                h, m = existing_time.split(':')
                hour_24 = int(h)
                existing_minute = m
                
                if use_24_hour:
                    existing_hour = h
                else:
                    # Convert 24-hour to 12-hour for display
                    if hour_24 == 0:
                        existing_hour = "12"
                        existing_ampm = "AM"
                    elif hour_24 < 12:
                        existing_hour = str(hour_24)
                        existing_ampm = "AM"
                    elif hour_24 == 12:
                        existing_hour = "12"
                        existing_ampm = "PM"
                    else:
                        existing_hour = str(hour_24 - 12)
                        existing_ampm = "PM"
            except:
                pass
        
        hour_var = tk.StringVar(master=dialog, value=existing_hour)
        minute_var = tk.StringVar(master=dialog, value=existing_minute)
        ampm_var = tk.StringVar(master=dialog, value=existing_ampm)
        
        if use_24_hour:
            hour_spinbox = ttk.Spinbox(time_frame, from_=0, to=23, width=3, textvariable=hour_var, format="%02.0f")
        else:
            hour_spinbox = ttk.Spinbox(time_frame, from_=1, to=12, width=3, textvariable=hour_var)
        hour_spinbox.pack(side=tk.LEFT)
        ttk.Label(time_frame, text=":").pack(side=tk.LEFT)
        minute_spinbox = ttk.Spinbox(time_frame, from_=0, to=59, width=3, textvariable=minute_var, format="%02.0f")
        minute_spinbox.pack(side=tk.LEFT)
        
        if not use_24_hour:
            ttk.Label(time_frame, text=" ").pack(side=tk.LEFT)
            ampm_combo = ttk.Combobox(time_frame, textvariable=ampm_var, values=["AM", "PM"], width=4, state="readonly")
            ampm_combo.pack(side=tk.LEFT)
        
        def clear_time():
            hour_var.set("")
            minute_var.set("")
            if not use_24_hour:
                ampm_var.set("AM")
        
        clear_time_btn = ttk.Button(time_frame, text="Clear", width=5, command=clear_time)
        clear_time_btn.pack(side=tk.LEFT, padx=10)
        
        ttk.Label(dialog, text="Priority (1-5):").grid(row=3, column=0, padx=5, pady=5, sticky="nw")
        priority_entry = ttk.Spinbox(dialog, from_=1, to=5)
        priority_entry.grid(row=3, column=1, padx=5, pady=5, sticky="w")
        priority_entry.delete(0, tk.END)
        priority_entry.insert(0, task_found[3])
        
        ttk.Label(dialog, text="Notes/Details:").grid(row=4, column=0, padx=5, pady=5, sticky="nw")
        notes_text = tk.Text(dialog, width=40, height=6, wrap=tk.WORD)
        notes_text.grid(row=4, column=1, padx=5, pady=5)
        # Insert existing notes if available
        if len(task_found) > 4:
            notes_text.insert("1.0", task_found[4])
        
        def validate_and_edit():
            date = self.parse_date(date_entry.get())
            if not date:
                messagebox.showerror("Error", "Invalid date format")
                return
            
            # Parse time (optional)
            due_time = ""
            hour_str = hour_var.get().strip()
            minute_str = minute_var.get().strip()
            if hour_str or minute_str:
                try:
                    hour = int(hour_str) if hour_str else 0
                    minute = int(minute_str) if minute_str else 0
                    
                    if use_24_hour:
                        if not (0 <= hour <= 23 and 0 <= minute <= 59):
                            raise ValueError
                    else:
                        # Convert 12-hour to 24-hour
                        if not (1 <= hour <= 12 and 0 <= minute <= 59):
                            raise ValueError
                        ampm = ampm_var.get()
                        if ampm == "PM" and hour != 12:
                            hour += 12
                        elif ampm == "AM" and hour == 12:
                            hour = 0
                    
                    due_time = f"{hour:02d}:{minute:02d}"
                except ValueError:
                    if use_24_hour:
                        messagebox.showerror("Error", "Invalid time format. Use 0-23 for hour and 0-59 for minute.")
                    else:
                        messagebox.showerror("Error", "Invalid time format. Use 1-12 for hour and 0-59 for minute.")
                    return
            
            try:
                priority = int(priority_entry.get())
                if not 1 <= priority <= 5:
                    raise ValueError
            except ValueError:
                messagebox.showerror("Error", "Priority must be 1-5")
                return
            
            notes = notes_text.get("1.0", tk.END).strip()
            tasks[index] = (task_entry.get(), date, due_time, priority, notes)
            self.save_tasks(tasks)
            self.refresh_task_list()
            dialog.destroy()
            
        ttk.Button(dialog, text="Save", command=validate_and_edit).grid(row=5, columnspan=2, pady=10)

    def delete_task(self):
        """Delete selected task without completing it"""
        selected = self.tree.selection()
        if not selected:
            messagebox.showwarning("Warning", "Please select a task to delete")
            return
        
        # Get the stored task data directly from our dictionary
        item_id = selected[0]
        if item_id not in self.task_data:
            messagebox.showerror("Error", "Task data not found")
            return
        
        task_to_remove = self.task_data[item_id]
        
        tasks = self.load_tasks()
        task_found = None
        index = -1
        
        # Find the task by matching all fields
        for i, task in enumerate(tasks):
            if task[:4] == task_to_remove[:4]:  # Match task, date, time, priority
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
            task_name = task[0]
            due_date_str = task[1]
            due_time_str = task[2] if len(task) > 2 else ""
            priority = task[3] if len(task) > 3 else task[2]  # Handle old format
            due_date = datetime.strptime(due_date_str, "%m-%d-%Y").date()
            
            # Check if task is overdue considering time
            if due_date < today:
                overdue_tasks.append(task)  # Overdue tasks
            elif due_date == today:
                # For today's tasks, check if time has passed
                if due_time_str and ':' in due_time_str:
                    try:
                        hour, minute = map(int, due_time_str.split(':'))
                        task_datetime = datetime.combine(due_date, datetime.min.time().replace(hour=hour, minute=minute))
                        if task_datetime < current_datetime:
                            overdue_tasks.append(task)  # Time has passed
                        else:
                            today_tasks.append(task)
                    except:
                        today_tasks.append(task)  # Due today
                else:
                    today_tasks.append(task)  # Due today
            else:
                upcoming_tasks.append(task)  # Future tasks

        # Sort each category using the sort key helper
        overdue_tasks.sort(key=lambda x: self._task_sort_key(x))
        today_tasks.sort(key=lambda x: self._task_sort_key(x))
        upcoming_tasks.sort(key=lambda x: self._task_sort_key(x))
        
        # Helper function to format time for display
        def format_display_time(time_str):
            if not time_str or not time_str.strip():
                return "--:--"
            try:
                hour, minute = map(int, time_str.split(':'))
                # Check user's time format preference
                if hasattr(self.parent_app, 'use_24_hour') and not self.parent_app.use_24_hour.get():
                    # 12-hour format
                    if hour == 0:
                        return f"12:{minute:02d} AM"
                    elif hour < 12:
                        return f"{hour}:{minute:02d} AM"
                    elif hour == 12:
                        return f"12:{minute:02d} PM"
                    else:
                        return f"{hour-12}:{minute:02d} PM"
                else:
                    # 24-hour format
                    return f"{hour:02d}:{minute:02d}"
            except:
                return "--:--"

        # Insert into Treeview with colors and action buttons
        for task in overdue_tasks:
            time_display = format_display_time(task[2] if len(task) > 2 else "")
            priority_val = task[3] if len(task) > 3 else task[2]
            display_values = (task[0], task[1], time_display, priority_val, "✓", "✎", "✗")
            item = self.tree.insert("", tk.END, values=display_values, tags=("overdue",), text=task[0])
            # Store the full task data (including notes) in our dictionary
            self.task_data[item] = task
        for task in today_tasks:
            time_display = format_display_time(task[2] if len(task) > 2 else "")
            priority_val = task[3] if len(task) > 3 else task[2]
            display_values = (task[0], task[1], time_display, priority_val, "✓", "✎", "✗")
            item = self.tree.insert("", tk.END, values=display_values, tags=("today",), text=task[0])
            self.task_data[item] = task
        for task in upcoming_tasks:
            time_display = format_display_time(task[2] if len(task) > 2 else "")
            priority_val = task[3] if len(task) > 3 else task[2]
            display_values = (task[0], task[1], time_display, priority_val, "✓", "✎", "✗")
            item = self.tree.insert("", tk.END, values=display_values, text=task[0])
            self.task_data[item] = task

        # Update the remaining tasks count in parent app
        if hasattr(self.parent_app, 'remaining_label'):
            self.parent_app.remaining_label.config(text=str(len(self.tree.get_children())))
        
        # Refresh calendar view if it exists
        if hasattr(self.parent_app, 'calendar_view') and self.parent_app.calendar_view:
            self.parent_app.calendar_view.refresh()

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
                        
                        # Check if this is old format (no time) or new format (with time)
                        # Old format: task | date | priority | notes
                        # New format: task | date | time | priority | notes
                        
                        # Try to detect format by checking if parts[2] looks like a time or priority
                        potential_time = parts[2].strip()
                        
                        if ':' in potential_time or potential_time == "":
                            # New format with time
                            due_time = potential_time
                            priority = parts[3].strip() if len(parts) > 3 else "5"
                            
                            # Validate priority is a number
                            int(priority)
                            
                            # Handle notes
                            if len(parts) > 4:
                                notes = " | ".join(parts[4:]).strip()
                                if not notes:
                                    notes = "No notes"
                            else:
                                notes = "No notes"
                        else:
                            # Old format without time - parts[2] is priority
                            due_time = ""
                            priority = potential_time
                            
                            # Validate priority is a number
                            int(priority)
                            
                            # Handle notes
                            if len(parts) > 3:
                                notes = " | ".join(parts[3:]).strip()
                                if not notes:
                                    notes = "No notes"
                            else:
                                notes = "No notes"
                        
                        tasks.append((task_name, due_date, due_time, priority, notes))
                    except ValueError as e:
                        # Skip malformed lines and show more detailed error info
                        print(f"Warning: Skipping malformed line: {line}")
                        print(f"Error details: {e}")
                        print(f"Parts found: {parts}")
                        continue
            return sorted(tasks, key=lambda x: self._task_sort_key(x))

    def save_tasks(self, tasks, skip_mysql=False):
        """Save tasks to file and sync with MySQL if enabled"""
        with open(self.TODO_FILE, "w") as f:
            for task in tasks:
                # Ensure we have exactly 5 elements (task, date, time, priority, notes)
                if len(task) == 3:
                    # Old format: (task, date, priority) -> add empty time and "No notes"
                    task = (task[0], task[1], "", task[2], "No notes")
                elif len(task) == 4:
                    # Could be old format (task, date, priority, notes) or partial new format
                    # Check if third element looks like a time
                    if ':' in str(task[2]) or task[2] == "":
                        # New format missing notes
                        task = task + ("No notes",)
                    else:
                        # Old format (task, date, priority, notes) -> insert empty time
                        task = (task[0], task[1], "", task[2], task[3])
                elif len(task) > 5:
                    # If somehow we have more than 5 elements, keep only first 5
                    task = task[:5]
                
                # Convert all elements to strings
                task_name, date, due_time, priority, notes = task
                
                # Handle empty notes - always ensure we have "No notes" if empty
                if not notes or notes.strip() == "":
                    notes = "No notes"
                
                # Handle empty time
                if not due_time:
                    due_time = ""
                
                # Create the line with proper formatting (including time)
                task_line = f"{task_name} | {date} | {due_time} | {priority} | {notes}"
                f.write(task_line + "\n")
    
        # Sync to MySQL if enabled and not skipping
        if (hasattr(self.parent_app, 'mysql_lan_manager') and 
            self.parent_app.mysql_lan_manager and 
            hasattr(self.parent_app.mysql_lan_manager, 'mysql_enabled') and
            self.parent_app.mysql_lan_manager.mysql_enabled.get() and 
            not skip_mysql):
            try:
                self.parent_app.mysql_lan_manager.sync_tasks_to_mysql()
            except Exception as e:
                print(f"Failed to sync to MySQL: {e}")