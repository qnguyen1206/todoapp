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
            notes = full_data[3] if len(full_data) > 3 else ""
            
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
        # Check if any dialog is already open
        if self.parent_app.check_existing_dialog():
            return
            
        dialog = tk.Toplevel(self.parent_app.root)
        dialog.title("Add New Task")
        dialog.geometry("450x300")
        
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
            """Parse and add all tasks"""
            try:
                content = tasks_text.get("1.0", tk.END).strip()
                if not content:
                    messagebox.showwarning("Warning", "Please enter some tasks first")
                    return
                
                lines = [line.strip() for line in content.split('\n') if line.strip()]
                added_count = 0
                errors = []
                
                for line in lines:
                    try:
                        task_info = self.parse_bulk_task_line(line)
                        self.add_task(task_info['task'], task_info['date'], task_info['priority'], task_info['notes'])
                        added_count += 1
                    except Exception as e:
                        errors.append(f"'{line}': {str(e)}")
                
                if errors:
                    error_msg = f"Added {added_count} tasks successfully.\n\nErrors:\n" + '\n'.join(errors[:5])
                    if len(errors) > 5:
                        error_msg += f"\n... and {len(errors) - 5} more errors"
                    messagebox.showwarning("Partial Success", error_msg)
                else:
                    messagebox.showinfo("Success", f"Successfully added {added_count} tasks!")
                
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
• Call dentist due at 2:30 PM (time goes to notes, "due at" removed)
• Meeting due on next Friday 14:30 priority 1
• Submit report due by 09/20/2025 | urgent | Check formatting

Supported date formats: today, tomorrow, next monday, 09/15/2025, in 3 days
Time formats: 2:30 PM, 14:30, 10 AM, 1430 (automatically moved to notes)
Due phrases: "due at", "due on", "due by" are automatically removed from task names
Priority: 1=urgent/highest, 2=high, 3=medium, 4=low, 5=lowest (default)
Keywords: urgent/critical (=1), high/important (=2), medium/normal (=3), low/minor (=4)"""
        
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
                        parsed_tasks.append(f"{i}. {task_info['task']} | {task_info['date']} | Priority {task_info['priority']}")
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
            
            # Try to extract time
            time_result = self.extract_time_from_text(part)
            if time_result:
                # Add time to notes
                if task_info['notes']:
                    task_info['notes'] += f" | Time: {time_result}"
                else:
                    task_info['notes'] = f"Time: {time_result}"
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
                # Add time to notes
                if task_info['notes']:
                    task_info['notes'] += f" | Time: {time_result}"
                else:
                    task_info['notes'] = f"Time: {time_result}"
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
        # Check if any dialog is already open
        if self.parent_app.check_existing_dialog():
            return
            
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
        if (hasattr(self.parent_app, 'mysql_lan_manager') and 
            self.parent_app.mysql_lan_manager and 
            hasattr(self.parent_app.mysql_lan_manager, 'mysql_enabled') and
            self.parent_app.mysql_lan_manager.mysql_enabled.get() and 
            not skip_mysql):
            try:
                self.parent_app.mysql_lan_manager.sync_tasks_to_mysql()
            except Exception as e:
                print(f"Failed to sync to MySQL: {e}")