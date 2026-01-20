"""
Calendar View Module for TODO App
Provides a calendar-based view of tasks with visual indicators for task due dates.
"""

import tkinter as tk
from tkinter import ttk, messagebox
from datetime import datetime, timedelta
import calendar


class CalendarView:
    def __init__(self, parent_app, calendar_frame):
        self.parent_app = parent_app
        self.calendar_frame = calendar_frame
        
        # Current displayed month/year
        self.current_date = datetime.now()
        self.displayed_year = self.current_date.year
        self.displayed_month = self.current_date.month
        
        # Selected date
        self.selected_date = None
        
        # Task colors by priority
        self.priority_colors = {
            '1': '#90EE90',  # Light green - Low
            '2': '#98FB98',  # Pale green
            '3': '#FFD700',  # Gold - Medium
            '4': '#FFA500',  # Orange
            '5': '#FF6B6B',  # Red - High
        }
        
        # Day cell references
        self.day_cells = {}
        self.day_labels = {}
        
        # Create the calendar interface
        self.create_calendar_widgets()
    
    def format_time(self, time_str):
        """Format time string according to user's preference (12-hour or 24-hour)"""
        if not time_str or not time_str.strip():
            return ""
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
            return time_str
        
    def create_calendar_widgets(self):
        """Create the calendar view interface"""
        # Main container with padding
        main_container = ttk.Frame(self.calendar_frame)
        main_container.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        
        # Header frame with navigation
        header_frame = ttk.Frame(main_container)
        header_frame.pack(fill=tk.X, pady=(0, 10))
        
        # Month/Year label on the left
        self.month_label = ttk.Label(header_frame, text="", font=('Helvetica', 16, 'bold'))
        self.month_label.pack(side=tk.LEFT, expand=True)
        
        # Navigation buttons on the right: Prev | Today | Next
        self.prev_btn = ttk.Button(header_frame, text="◀ Prev", width=10, command=self.prev_month)
        self.prev_btn.pack(side=tk.LEFT, padx=5)
        
        self.today_btn = ttk.Button(header_frame, text="Today", width=10, command=self.go_to_today)
        self.today_btn.pack(side=tk.LEFT, padx=5)
        
        self.next_btn = ttk.Button(header_frame, text="Next ▶", width=10, command=self.next_month)
        self.next_btn.pack(side=tk.LEFT, padx=5)
        
        # Legend frame
        legend_frame = ttk.Frame(main_container)
        legend_frame.pack(fill=tk.X, pady=(0, 10))
        
        ttk.Label(legend_frame, text="Priority: ", font=('Helvetica', 9, 'bold')).pack(side=tk.LEFT)
        for priority, color in [('1-2 (Urgent)', '#FF6B6B'), ('3', '#FFD700'), ('4-5 (Low)', '#90EE90')]:
            legend_item = tk.Frame(legend_frame, bg=color, width=20, height=15)
            legend_item.pack(side=tk.LEFT, padx=2)
            legend_item.pack_propagate(False)
            ttk.Label(legend_frame, text=priority, font=('Helvetica', 8)).pack(side=tk.LEFT, padx=(0, 10))
        
        # Overdue indicator
        overdue_frame = tk.Frame(legend_frame, bg='#FF0000', width=20, height=15)
        overdue_frame.pack(side=tk.LEFT, padx=2)
        overdue_frame.pack_propagate(False)
        ttk.Label(legend_frame, text="Overdue", font=('Helvetica', 8)).pack(side=tk.LEFT, padx=(0, 10))
        
        # Calendar grid frame
        self.grid_frame = ttk.Frame(main_container)
        self.grid_frame.pack(fill=tk.BOTH, expand=True)
        
        # Configure grid columns to be equal width
        for i in range(7):
            self.grid_frame.columnconfigure(i, weight=1, uniform="day")
        
        # Day headers
        days = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat']
        for i, day in enumerate(days):
            header = ttk.Label(self.grid_frame, text=day, font=('Helvetica', 10, 'bold'), anchor='center')
            header.grid(row=0, column=i, sticky='nsew', padx=1, pady=2)
        
        # Create day cells (6 rows max for any month)
        for row in range(1, 7):
            self.grid_frame.rowconfigure(row, weight=1, uniform="week")
            for col in range(7):
                cell_frame = tk.Frame(self.grid_frame, bg='white', relief='solid', borderwidth=1)
                cell_frame.grid(row=row, column=col, sticky='nsew', padx=1, pady=1)
                cell_frame.grid_propagate(False)
                
                # Day number label
                day_label = tk.Label(cell_frame, text="", font=('Helvetica', 10, 'bold'), 
                                    bg='white', anchor='ne')
                day_label.pack(side=tk.TOP, anchor='ne', padx=2, pady=1)
                
                # Task container (scrollable)
                task_container = tk.Frame(cell_frame, bg='white')
                task_container.pack(fill=tk.BOTH, expand=True, padx=2, pady=1)
                
                # Store references
                key = (row, col)
                self.day_cells[key] = {'frame': cell_frame, 'day_label': day_label, 
                                       'task_container': task_container, 'date': None}
                
                # Bind click event to cell
                cell_frame.bind('<Button-1>', lambda e, k=key: self.on_day_click(k))
                day_label.bind('<Button-1>', lambda e, k=key: self.on_day_click(k))
                task_container.bind('<Button-1>', lambda e, k=key: self.on_day_click(k))
        
        # Task details frame at bottom
        self.details_frame = ttk.LabelFrame(main_container, text="Tasks for Selected Date")
        self.details_frame.pack(fill=tk.X, pady=(10, 0))
        
        # Task list for selected date
        self.task_listbox = tk.Listbox(self.details_frame, height=4, font=('Helvetica', 10))
        self.task_listbox.pack(fill=tk.X, padx=5, pady=5)
        self.task_listbox.bind('<Double-Button-1>', self.on_task_double_click)
        self.task_listbox.bind('<Button-1>', self.on_task_click)
        
        # Button frame for actions
        action_frame = ttk.Frame(self.details_frame)
        action_frame.pack(fill=tk.X, padx=5, pady=(0, 5))
        
        self.view_details_btn = ttk.Button(action_frame, text="📄 View Details", command=self.view_selected_task_details)
        self.view_details_btn.pack(side=tk.LEFT, padx=5)
        
        self.edit_task_btn = ttk.Button(action_frame, text="✎ Edit Task", command=self.edit_selected_task)
        self.edit_task_btn.pack(side=tk.LEFT, padx=5)
        
        # Hint label
        hint_label = ttk.Label(self.details_frame, text="Select a task and click 'View Details' or 'Edit Task'", 
                              font=('Helvetica', 8), foreground='gray')
        hint_label.pack(pady=(0, 5))
        
        # Initial render
        self.render_calendar()
    
    def render_calendar(self):
        """Render the calendar for the current month"""
        # Update month label
        month_name = calendar.month_name[self.displayed_month]
        self.month_label.config(text=f"{month_name} {self.displayed_year}")
        
        # Get the calendar for this month
        cal = calendar.Calendar(firstweekday=6)  # Start with Sunday
        month_days = cal.monthdayscalendar(self.displayed_year, self.displayed_month)
        
        # Pad to 6 rows if needed
        while len(month_days) < 6:
            month_days.append([0] * 7)
        
        # Get tasks from parent app
        tasks = self.get_tasks()
        tasks_by_date = self.organize_tasks_by_date(tasks)
        
        today = datetime.now().date()
        
        # Update each cell
        for row in range(1, 7):
            for col in range(7):
                key = (row, col)
                cell = self.day_cells[key]
                day_num = month_days[row - 1][col]
                
                # Clear previous task widgets
                for widget in cell['task_container'].winfo_children():
                    widget.destroy()
                
                if day_num == 0:
                    # Empty cell (not in this month)
                    cell['day_label'].config(text="", bg='#f5f5f5')
                    cell['frame'].config(bg='#f5f5f5')
                    cell['task_container'].config(bg='#f5f5f5')
                    cell['date'] = None
                else:
                    # Valid day
                    cell_date = datetime(self.displayed_year, self.displayed_month, day_num).date()
                    cell['date'] = cell_date
                    date_str = cell_date.strftime("%m-%d-%Y")
                    
                    # Determine background color
                    bg_color = 'white'
                    if cell_date == today:
                        bg_color = '#E6F3FF'  # Light blue for today
                    elif self.selected_date and cell_date == self.selected_date:
                        bg_color = '#D4EDDA'  # Light green for selected
                    
                    cell['day_label'].config(text=str(day_num), bg=bg_color)
                    cell['frame'].config(bg=bg_color)
                    cell['task_container'].config(bg=bg_color)
                    
                    # Add task indicators
                    if date_str in tasks_by_date:
                        day_tasks = tasks_by_date[date_str]
                        self.add_task_indicators(cell['task_container'], day_tasks, cell_date, today, bg_color)
    
    def add_task_indicators(self, container, tasks, cell_date, today, bg_color):
        """Add visual indicators for tasks on a day"""
        if not tasks:
            return
        
        # Calculate how many total tasks
        total_tasks = len(tasks)
            
        # Show only the first task
        task = tasks[0]
        task_name = task[0]
        due_date = task[1]
        due_time = task[2] if len(task) > 2 else ""
        priority = task[3] if len(task) > 3 else task[2]  # Handle old format
        
        # Determine color based on priority and overdue status
        # Priority 1 = most urgent (red), Priority 5 = least urgent (green)
        if cell_date < today:
            color = '#FF0000'  # Red for overdue
        else:
            priority_num = int(priority) if str(priority).isdigit() else 3
            if priority_num <= 2:
                color = '#FF6B6B'  # Red - Urgent (1-2)
            elif priority_num == 3:
                color = '#FFD700'  # Gold - Medium (3)
            else:
                color = '#90EE90'  # Green - Low (4-5)
        
        # Truncate task name - shorter if we need to show count
        if total_tasks > 1:
            display_name = task_name[:10] + "..." if len(task_name) > 10 else task_name
        else:
            display_name = task_name[:14] + "..." if len(task_name) > 14 else task_name
        
        # Create a row frame for task + count
        row_frame = tk.Frame(container, bg=bg_color)
        row_frame.pack(fill=tk.X, pady=1)
        
        task_label = tk.Label(row_frame, text=f"• {display_name}", font=('Helvetica', 8),
                             bg=color, fg='black', anchor='w', padx=2, cursor='hand2')
        task_label.pack(side=tk.LEFT, fill=tk.X, expand=True)
        task_label.bind('<Button-1>', lambda e, d=cell_date: self.on_task_label_click(e, d))
        
        # Always show count indicator if there's more than 1 task - on the same row
        if total_tasks > 1:
            remaining = total_tasks - 1
            more_label = tk.Label(row_frame, text=f"+{remaining}", 
                                 font=('Helvetica', 8, 'bold'), bg='#4A90D9', fg='white', 
                                 cursor='hand2', padx=3)
            more_label.pack(side=tk.RIGHT, padx=1)
            more_label.bind('<Button-1>', lambda e, d=cell_date: self.on_task_label_click(e, d))
    
    def on_task_label_click(self, event, cell_date):
        """Handle click on a task label in the calendar - show all tasks for that day"""
        self.selected_date = cell_date
        self.render_calendar()  # Re-render to show selection
        self.update_task_list(cell_date)
        self.show_day_tasks_dialog(cell_date)
    
    def get_cell_key(self, target_date):
        """Get the cell key for a given date"""
        for key, cell in self.day_cells.items():
            if cell['date'] == target_date:
                return key
        return None
    
    def organize_tasks_by_date(self, tasks):
        """Organize tasks into a dictionary by date"""
        tasks_by_date = {}
        for task in tasks:
            due_date = task[1]  # Format: mm-dd-yyyy
            if due_date not in tasks_by_date:
                tasks_by_date[due_date] = []
            tasks_by_date[due_date].append(task)
        return tasks_by_date
    
    def get_tasks(self):
        """Get tasks from the parent app's todo list manager"""
        if hasattr(self.parent_app, 'todo_list_manager') and self.parent_app.todo_list_manager:
            return self.parent_app.todo_list_manager.load_tasks()
        return []
    
    def on_day_click(self, key):
        """Handle click on a calendar day"""
        if key is None:
            return
            
        cell = self.day_cells[key]
        if cell['date'] is None:
            return
        
        self.selected_date = cell['date']
        self.render_calendar()  # Re-render to show selection
        
        # Update task list
        self.update_task_list(cell['date'])
    
    def update_task_list(self, selected_date):
        """Update the task listbox for the selected date"""
        self.task_listbox.delete(0, tk.END)
        
        date_str = selected_date.strftime("%m-%d-%Y")
        tasks = self.get_tasks()
        
        # Store tasks for double-click reference
        self.current_day_tasks = []
        
        for task in tasks:
            if task[1] == date_str:
                task_name = task[0]
                due_time = task[2] if len(task) > 2 else ""
                priority = task[3] if len(task) > 3 else task[2]  # Handle old format
                time_display = f" @ {self.format_time(due_time)}" if due_time else ""
                display = f"[P{priority}]{time_display} {task_name}"
                self.task_listbox.insert(tk.END, display)
                self.current_day_tasks.append(task)
        
        if not self.current_day_tasks:
            self.task_listbox.insert(tk.END, "No tasks for this date")
    
    def on_task_click(self, event):
        """Handle click on task listbox - just for selection"""
        pass  # Selection is handled automatically by Listbox
    
    def view_selected_task_details(self):
        """View details of the selected task"""
        selection = self.task_listbox.curselection()
        if not selection or not hasattr(self, 'current_day_tasks'):
            return
        
        idx = selection[0]
        if idx < len(self.current_day_tasks):
            task = self.current_day_tasks[idx]
            self.show_task_details(task)
    
    def edit_selected_task(self):
        """Edit the selected task"""
        selection = self.task_listbox.curselection()
        if not selection or not hasattr(self, 'current_day_tasks'):
            return
        
        idx = selection[0]
        if idx < len(self.current_day_tasks):
            task = self.current_day_tasks[idx]
            self.edit_task_from_calendar(task)
    
    def show_day_tasks_dialog(self, selected_date):
        """Show a dialog with all tasks for a specific day"""
        try:
            # Check if any dialog is already open
            if hasattr(self.parent_app, 'check_existing_dialog') and self.parent_app.check_existing_dialog():
                return
            
            date_str = selected_date.strftime("%m-%d-%Y")
            display_date = selected_date.strftime("%B %d, %Y")
            tasks = self.get_tasks()
            
            # Filter tasks for this day
            day_tasks = [t for t in tasks if t[1] == date_str]
            
            if not day_tasks:
                return  # No tasks for this day
            
            # Create dialog
            dialog = tk.Toplevel(self.parent_app.root)
            dialog.title(f"Tasks for {display_date}")
            dialog.geometry("500x450")
            dialog.resizable(True, True)
            
            # Register this dialog globally
            if hasattr(self.parent_app, 'register_dialog'):
                self.parent_app.register_dialog(dialog)
            
            # Header
            header_frame = ttk.Frame(dialog)
            header_frame.pack(fill=tk.X, padx=10, pady=10)
            ttk.Label(header_frame, text=f"Tasks for {display_date}", font=('Helvetica', 14, 'bold')).pack()
            ttk.Label(header_frame, text=f"{len(day_tasks)} task(s)", font=('Helvetica', 10), foreground='gray').pack()
            
            # Task list frame with scrollbar
            list_frame = ttk.Frame(dialog)
            list_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)
            
            # Create canvas with scrollbar for tasks
            canvas = tk.Canvas(list_frame)
            scrollbar = ttk.Scrollbar(list_frame, orient="vertical", command=canvas.yview)
            scrollable_frame = ttk.Frame(canvas)
            
            scrollable_frame.bind(
                "<Configure>",
                lambda e: canvas.configure(scrollregion=canvas.bbox("all"))
            )
            
            canvas.create_window((0, 0), window=scrollable_frame, anchor="nw")
            canvas.configure(yscrollcommand=scrollbar.set)
            
            canvas.pack(side="left", fill="both", expand=True)
            scrollbar.pack(side="right", fill="y")
            
            # Store task references for click handling
            self.dialog_tasks = day_tasks
            
            # Add each task as a clickable card
            for i, task in enumerate(day_tasks):
                task_name = task[0]
                due_date = task[1]
                due_time = task[2] if len(task) > 2 else ""
                priority = task[3] if len(task) > 3 else task[2]  # Handle old format
                notes = task[4] if len(task) > 4 else (task[3] if len(task) > 3 else "No notes")
                
                # Determine priority color
                priority_num = int(priority) if str(priority).isdigit() else 3
                if priority_num <= 2:
                    color = '#FF6B6B'  # Urgent
                elif priority_num == 3:
                    color = '#FFD700'  # Medium
                else:
                    color = '#90EE90'  # Low
                
                # Task card frame
                task_frame = tk.Frame(scrollable_frame, bg=color, relief='raised', borderwidth=1)
                task_frame.pack(fill=tk.X, padx=5, pady=3)
                
                # Task content
                content_frame = tk.Frame(task_frame, bg=color)
                content_frame.pack(fill=tk.X, padx=8, pady=5)
                
                # Task name
                name_label = tk.Label(content_frame, text=task_name, font=('Helvetica', 11, 'bold'),
                                     bg=color, fg='black', anchor='w')
                name_label.pack(fill=tk.X)
                
                # Due time and Priority on same line
                time_display = f"Time: {self.format_time(due_time)} | " if due_time else ""
                info_label = tk.Label(content_frame, text=f"{time_display}Priority: {priority}", 
                                         font=('Helvetica', 9), bg=color, fg='#333', anchor='w')
                info_label.pack(fill=tk.X)
                
                # Notes preview (truncated)
                if notes and notes != "No notes":
                    notes_preview = notes[:50] + "..." if len(notes) > 50 else notes
                    notes_label = tk.Label(content_frame, text=f"Notes: {notes_preview}", 
                                          font=('Helvetica', 9, 'italic'), bg=color, fg='#555', anchor='w')
                    notes_label.pack(fill=tk.X)
                
                # Button frame
                btn_frame = tk.Frame(task_frame, bg=color)
                btn_frame.pack(fill=tk.X, padx=8, pady=(0, 5))
                
                ttk.Button(btn_frame, text="View Details", 
                          command=lambda t=task: self.show_task_details_from_dialog(dialog, t)).pack(side=tk.LEFT, padx=2)
                ttk.Button(btn_frame, text="Edit", 
                          command=lambda t=task: self.edit_task_from_day_dialog(dialog, t)).pack(side=tk.LEFT, padx=2)
            
            # Close button
            ttk.Button(dialog, text="Close", command=dialog.destroy).pack(pady=10)
            
        except Exception as e:
            from tkinter import messagebox
            messagebox.showerror("Error", f"Could not display tasks: {str(e)}")
    
    def show_task_details_from_dialog(self, parent_dialog, task):
        """Show single task details from the day tasks dialog"""
        parent_dialog.destroy()
        self.show_task_details(task)
    
    def edit_task_from_day_dialog(self, parent_dialog, task):
        """Edit task from the day tasks dialog"""
        parent_dialog.destroy()
        self.edit_task_from_calendar(task)
    
    def show_task_details(self, task):
        """Show task details dialog similar to list view"""
        try:
            # Check if any dialog is already open
            if hasattr(self.parent_app, 'check_existing_dialog') and self.parent_app.check_existing_dialog():
                return
            
            task_name = task[0]
            due_date = task[1]
            due_time = task[2] if len(task) > 2 else ""
            priority = task[3] if len(task) > 3 else task[2]  # Handle old format
            notes = task[4] if len(task) > 4 else (task[3] if len(task) > 3 else "No notes")
            
            # Create details dialog
            details_dialog = tk.Toplevel(self.parent_app.root)
            details_dialog.title(f"Task Details: {task_name}")
            details_dialog.geometry("450x420")
            details_dialog.resizable(True, True)
            
            # Register this dialog globally
            if hasattr(self.parent_app, 'register_dialog'):
                self.parent_app.register_dialog(details_dialog)
            
            # Task name label
            ttk.Label(details_dialog, text=f"Task: {task_name}", font=('Helvetica', 12, 'bold')).pack(pady=10)
            
            # Task info frame
            info_frame = ttk.Frame(details_dialog)
            info_frame.pack(fill=tk.X, padx=10, pady=5)
            
            ttk.Label(info_frame, text=f"Due Date: {due_date}", font=('Helvetica', 10)).pack(anchor='w')
            if due_time:
                ttk.Label(info_frame, text=f"Due Time: {self.format_time(due_time)}", font=('Helvetica', 10)).pack(anchor='w')
            ttk.Label(info_frame, text=f"Priority: {priority}", font=('Helvetica', 10)).pack(anchor='w')
            
            # Notes display
            ttk.Label(details_dialog, text="Notes/Details:", font=('Helvetica', 10, 'bold')).pack(anchor='w', padx=10, pady=(10, 0))
            
            notes_text = tk.Text(details_dialog, wrap=tk.WORD, state='disabled', height=10)
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
            button_frame = ttk.Frame(details_dialog)
            button_frame.pack(fill=tk.X, padx=10, pady=10)
            
            # Edit Task button
            ttk.Button(button_frame, text="✎ Edit Task", 
                      command=lambda: self.edit_task_from_details(details_dialog, task)).pack(side=tk.LEFT, padx=5)
            
            # Close button
            ttk.Button(button_frame, text="Close", command=details_dialog.destroy).pack(side=tk.RIGHT, padx=5)
            
        except Exception as e:
            from tkinter import messagebox
            messagebox.showerror("Error", f"Could not display task details: {str(e)}")
    
    def edit_task_from_details(self, dialog, task):
        """Edit task from the details dialog"""
        dialog.destroy()
        self.edit_task_from_calendar(task)
    
    def on_task_double_click(self, event):
        """Handle double-click on a task in the list"""
        selection = self.task_listbox.curselection()
        if not selection or not hasattr(self, 'current_day_tasks'):
            return
        
        idx = selection[0]
        if idx < len(self.current_day_tasks):
            task = self.current_day_tasks[idx]
            self.edit_task_from_calendar(task)
    
    def edit_task_from_calendar(self, task):
        """Open edit dialog for a task"""
        if hasattr(self.parent_app, 'todo_list_manager') and self.parent_app.todo_list_manager:
            # Find the task in the tree and select it
            manager = self.parent_app.todo_list_manager
            for item in manager.tree.get_children():
                if item in manager.task_data:
                    if manager.task_data[item][0] == task[0]:  # Match by task name
                        manager.tree.selection_set(item)
                        manager.edit_task()
                        return
    
    def prev_month(self):
        """Go to previous month"""
        if self.displayed_month == 1:
            self.displayed_month = 12
            self.displayed_year -= 1
        else:
            self.displayed_month -= 1
        self.render_calendar()
    
    def next_month(self):
        """Go to next month"""
        if self.displayed_month == 12:
            self.displayed_month = 1
            self.displayed_year += 1
        else:
            self.displayed_month += 1
        self.render_calendar()
    
    def go_to_today(self):
        """Go to current month"""
        today = datetime.now()
        self.displayed_year = today.year
        self.displayed_month = today.month
        self.selected_date = today.date()
        self.render_calendar()
        self.update_task_list(self.selected_date)
    
    def refresh(self):
        """Refresh the calendar view"""
        self.render_calendar()
        if self.selected_date:
            self.update_task_list(self.selected_date)
