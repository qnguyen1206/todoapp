"""
Calendar View Module for TODO App
Provides a calendar-based view of tasks with visual indicators for task due dates.
"""

import tkinter as tk
from tkinter import ttk, messagebox
from datetime import datetime, timedelta
import calendar
import json
import re
from pathlib import Path
from ui_utils import fit_window


class CalendarView:
    def __init__(self, parent_app, calendar_frame):
        self.parent_app = parent_app
        self.calendar_frame = calendar_frame
        
        # Current displayed month/year
        self.current_date = datetime.now()
        self.displayed_year = self.current_date.year
        self.displayed_month = self.current_date.month
        self.anchor_date = self.current_date.date()
        self.view_mode = "month"
        self.calendar_preferences_file = Path.home() / "TODOapp" / "calendar_pref.json"
        self.start_hour = 6
        self.end_hour = 22
        self._load_calendar_preferences()
        
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

        view_frame = ttk.Frame(main_container)
        view_frame.pack(fill=tk.X, pady=(0, 8))
        self.view_buttons = {}
        for mode in ("year", "month", "week", "day"):
            button = ttk.Button(
                view_frame,
                text=mode.title(),
                command=lambda selected=mode: self.set_view_mode(selected),
            )
            button.pack(side=tk.LEFT, padx=(0, 4))
            self.view_buttons[mode] = button
        
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

        ttk.Label(header_frame, text="Go to:").pack(side=tk.LEFT, padx=(12, 3))
        self.date_jump_var = tk.StringVar(master=self.calendar_frame, value=self.anchor_date.strftime("%m-%d-%Y"))
        self.date_jump_entry = ttk.Entry(header_frame, width=12, textvariable=self.date_jump_var)
        self.date_jump_entry.pack(side=tk.LEFT, padx=(0, 3))
        self.date_jump_entry.bind("<Return>", lambda _event: self.go_to_date())
        ttk.Button(header_frame, text="Go", width=4, command=self.go_to_date).pack(side=tk.LEFT, padx=(0, 5))
        
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

        self.range_frame = ttk.Frame(main_container)
        ttk.Label(self.range_frame, text="Visible hours:", font=('Helvetica', 9, 'bold')).pack(side=tk.LEFT)
        self.start_hour_var = tk.StringVar(master=self.calendar_frame, value=str(self.start_hour))
        self.end_hour_var = tk.StringVar(master=self.calendar_frame, value=str(self.end_hour))
        hour_values = [str(hour) for hour in range(24)]
        end_values = [str(hour) for hour in range(1, 25)]
        ttk.Label(self.range_frame, text="From").pack(side=tk.LEFT, padx=(8, 3))
        start_combo = ttk.Combobox(self.range_frame, width=5, state="readonly", values=hour_values, textvariable=self.start_hour_var)
        start_combo.pack(side=tk.LEFT)
        ttk.Label(self.range_frame, text="To").pack(side=tk.LEFT, padx=(8, 3))
        end_combo = ttk.Combobox(self.range_frame, width=5, state="readonly", values=end_values, textvariable=self.end_hour_var)
        end_combo.pack(side=tk.LEFT)
        start_combo.bind("<<ComboboxSelected>>", self.update_visible_hours)
        end_combo.bind("<<ComboboxSelected>>", self.update_visible_hours)
        
        # Calendar grid frame
        self.grid_frame = ttk.Frame(main_container)
        self.grid_frame.pack(fill=tk.BOTH, expand=True)

        self.alternate_frame = ttk.Frame(main_container)
        
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

    def _load_calendar_preferences(self):
        try:
            data = json.loads(self.calendar_preferences_file.read_text(encoding="utf-8"))
            start = int(data.get("start_hour", 6))
            end = int(data.get("end_hour", 22))
            if 0 <= start < end <= 24:
                self.start_hour = start
                self.end_hour = end
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            pass

    def _save_calendar_preferences(self):
        try:
            self.calendar_preferences_file.parent.mkdir(parents=True, exist_ok=True)
            self.calendar_preferences_file.write_text(
                json.dumps({"start_hour": self.start_hour, "end_hour": self.end_hour}),
                encoding="utf-8",
            )
        except OSError:
            pass

    def set_view_mode(self, mode):
        if mode not in {"year", "month", "week", "day"}:
            return
        self.view_mode = mode
        self.displayed_year = self.anchor_date.year
        self.displayed_month = self.anchor_date.month
        if mode == "month":
            self.selected_date = self.anchor_date
        self.render_calendar()

    def update_visible_hours(self, _event=None):
        start = int(self.start_hour_var.get())
        end = int(self.end_hour_var.get())
        if start >= end:
            messagebox.showerror("Invalid range", "The visible end hour must be after the start hour.")
            self.start_hour_var.set(str(self.start_hour))
            self.end_hour_var.set(str(self.end_hour))
            return
        self.start_hour = start
        self.end_hour = end
        self._save_calendar_preferences()
        self.render_calendar()

    def go_to_date(self):
        try:
            selected = datetime.strptime(self.date_jump_var.get().strip(), "%m-%d-%Y").date()
        except ValueError:
            messagebox.showerror("Invalid date", "Enter a date as MM-DD-YYYY.")
            return
        self.anchor_date = selected
        self.displayed_year = selected.year
        self.displayed_month = selected.month
        self.selected_date = selected if self.view_mode == "month" else None
        self.render_calendar()

    def render_calendar(self):
        """Render the selected year, month, week, or day view."""
        self.date_jump_var.set(self.anchor_date.strftime("%m-%d-%Y"))
        for mode, button in self.view_buttons.items():
            button.state(["pressed"] if mode == self.view_mode else ["!pressed"])

        if self.view_mode == "month":
            self.range_frame.pack_forget()
            self.alternate_frame.pack_forget()
            if not self.grid_frame.winfo_manager():
                self.grid_frame.pack(fill=tk.BOTH, expand=True)
            if not self.details_frame.winfo_manager():
                self.details_frame.pack(fill=tk.X, pady=(10, 0))
            self._render_month_calendar()
            return

        self.grid_frame.pack_forget()
        self.details_frame.pack_forget()
        self.alternate_frame.pack_forget()
        if self.view_mode in {"week", "day"}:
            if not self.range_frame.winfo_manager():
                self.range_frame.pack(fill=tk.X, pady=(0, 8))
        else:
            self.range_frame.pack_forget()
        self.alternate_frame.pack(fill=tk.BOTH, expand=True)
        for widget in self.alternate_frame.winfo_children():
            widget.destroy()
        if self.view_mode == "year":
            self._render_year_view()
        else:
            self._render_schedule_view(single_day=self.view_mode == "day")

    def _render_month_calendar(self):
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
        daily_definitions = self._daily_task_definitions()
        
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
                    daily_tasks = self._daily_tasks_for_date(cell_date, daily_definitions)
                    if daily_tasks:
                        self.add_daily_task_indicator(cell['task_container'], daily_tasks, cell_date, bg_color)

    def _daily_task_definitions(self):
        """Load active recurring task definitions once for a calendar render."""
        manager = getattr(self.parent_app, "daily_todo_manager", None)
        file_path = getattr(manager, "DAILY_TASK_FILE", None)
        if not file_path:
            return []
        try:
            lines = Path(file_path).read_text(encoding="utf-8").splitlines()
        except OSError:
            return []

        definitions = []
        pattern = re.compile(
            r"^(?:(?P<days>[A-Za-z,]+)\s+)?(?P<start>\d{2}:\d{2})"
            r"(?:-(?P<end>\d{2}:\d{2}))?\s+-\s+(?P<title>.+)$"
        )
        for raw in lines:
            if not raw.strip() or raw.startswith("[COMPLETED] "):
                continue
            match = pattern.match(raw.strip())
            if not match:
                continue
            definitions.append({
                "days": set((match.group("days") or "").split(",")) if match.group("days") else set(),
                "title": match.group("title"),
                "start": match.group("start"),
                "end": match.group("end") or "",
                "priority": "daily",
                "kind": "daily",
            })
        return definitions

    def _daily_tasks_for_date(self, target_date, definitions=None):
        """Return active recurring tasks that apply to a calendar date."""
        definitions = self._daily_task_definitions() if definitions is None else definitions
        weekday = target_date.strftime("%a")
        return [event for event in definitions if not event["days"] or weekday in event["days"]]

    def _tasks_for_date(self, target_date, todo_tasks=None, daily_definitions=None):
        date_key = target_date.strftime("%m-%d-%Y")
        events = []
        for task in self.get_tasks() if todo_tasks is None else todo_tasks:
            if len(task) < 2 or task[1] != date_key:
                continue
            events.append({
                "title": task[0],
                "start": task[2] if len(task) > 2 else "",
                "end": task[5] if len(task) > 5 else "",
                "priority": str(task[3] if len(task) > 3 else "3"),
                "kind": "todo",
            })
        events.extend(self._daily_tasks_for_date(target_date, daily_definitions))
        return sorted(events, key=lambda event: (event["start"] or "99:99", event["title"].lower()))

    def _render_year_view(self):
        year = self.anchor_date.year
        self.month_label.config(text=str(year))
        today = datetime.now().date()
        todo_tasks = self.get_tasks()
        daily_definitions = self._daily_task_definitions()
        for column in range(3):
            self.alternate_frame.columnconfigure(column, weight=1, uniform="month")
        for row in range(4):
            self.alternate_frame.rowconfigure(row, weight=1, uniform="month")

        for month in range(1, 13):
            month_frame = ttk.LabelFrame(self.alternate_frame, text=calendar.month_name[month])
            month_frame.grid(row=(month - 1) // 3, column=(month - 1) % 3, sticky="nsew", padx=4, pady=4)
            for column, day_name in enumerate(("M", "T", "W", "T", "F", "S", "S")):
                ttk.Label(month_frame, text=day_name, anchor="center").grid(row=0, column=column, sticky="ew")
                month_frame.columnconfigure(column, weight=1)
            weeks = calendar.Calendar(firstweekday=0).monthdayscalendar(year, month)
            for week_index, week in enumerate(weeks, start=1):
                for column, day_number in enumerate(week):
                    if not day_number:
                        continue
                    target = datetime(year, month, day_number).date()
                    count = len(self._tasks_for_date(target, todo_tasks, daily_definitions))
                    text = f"{day_number}\n{count}" if count else str(day_number)
                    button = tk.Button(
                        month_frame,
                        text=text,
                        font=("Helvetica", 8, "bold" if count else "normal"),
                        relief="flat",
                        bg="#E6F3FF" if target == today else ("#E8EAF6" if count else "white"),
                        command=lambda selected=target: self.open_day_view(selected),
                    )
                    button.grid(row=week_index, column=column, sticky="nsew", padx=1, pady=1)

    def open_day_view(self, selected_date):
        self.anchor_date = selected_date
        self.selected_date = selected_date
        self.view_mode = "day"
        self.render_calendar()

    def _render_schedule_view(self, single_day=False):
        if single_day:
            dates = [self.anchor_date]
            self.month_label.config(text=self.anchor_date.strftime("%A, %B %d, %Y"))
        else:
            week_start = self.anchor_date - timedelta(days=self.anchor_date.weekday())
            dates = [week_start + timedelta(days=offset) for offset in range(7)]
            self.month_label.config(
                text=f"{dates[0].strftime('%b %d')} - {dates[-1].strftime('%b %d, %Y')}"
            )

        todo_tasks = self.get_tasks()
        daily_definitions = self._daily_task_definitions()
        events_by_date = {
            target: self._tasks_for_date(target, todo_tasks, daily_definitions)
            for target in dates
        }
        date_only = []
        for target in dates:
            for event in events_by_date[target]:
                if not event["start"]:
                    date_only.append(f"{target.strftime('%a %m/%d')}: {event['title']}")
        if date_only:
            ttk.Label(
                self.alternate_frame,
                text="No start time:  " + "   |   ".join(date_only),
                wraplength=1000,
                justify=tk.LEFT,
            ).pack(fill=tk.X, padx=4, pady=(0, 6))

        container = ttk.Frame(self.alternate_frame)
        container.pack(fill=tk.BOTH, expand=True)
        canvas = tk.Canvas(container, background="white", highlightthickness=0)
        vertical = ttk.Scrollbar(container, orient=tk.VERTICAL, command=canvas.yview)
        horizontal = ttk.Scrollbar(container, orient=tk.HORIZONTAL, command=canvas.xview)
        canvas.configure(yscrollcommand=vertical.set, xscrollcommand=horizontal.set)
        canvas.grid(row=0, column=0, sticky="nsew")
        vertical.grid(row=0, column=1, sticky="ns")
        horizontal.grid(row=1, column=0, sticky="ew")
        container.rowconfigure(0, weight=1)
        container.columnconfigure(0, weight=1)

        schedule = ttk.Frame(canvas)
        window = canvas.create_window((0, 0), window=schedule, anchor="nw")
        schedule.bind("<Configure>", lambda _event: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.bind("<Configure>", lambda event: canvas.itemconfigure(window, width=max(event.width, 260 if single_day else 820)))

        ttk.Label(schedule, text="Time", anchor="center", font=('Helvetica', 9, 'bold')).grid(row=0, column=0, sticky="nsew", padx=1, pady=1)
        schedule.columnconfigure(0, minsize=75)
        today = datetime.now().date()
        for column, target in enumerate(dates, start=1):
            label = ttk.Label(schedule, text=target.strftime("%a\n%b %d"), anchor="center", font=('Helvetica', 9, 'bold'))
            label.grid(row=0, column=column, sticky="nsew", padx=1, pady=1)
            schedule.columnconfigure(column, weight=1, minsize=180 if single_day else 105)

        slots = list(range(self.start_hour * 2, self.end_hour * 2))
        cell_frames = {}
        current = datetime.now()
        for row, slot in enumerate(slots, start=1):
            hour, half = divmod(slot, 2)
            minute = half * 30
            ttk.Label(schedule, text=self.format_time(f"{hour:02d}:{minute:02d}"), anchor="e").grid(row=row, column=0, sticky="nsew", padx=4, pady=1)
            schedule.rowconfigure(row, minsize=34)
            for column, target in enumerate(dates, start=1):
                active = target == today and hour == current.hour and minute <= current.minute < minute + 30
                frame = tk.Frame(schedule, bg="#E6F3FF" if active else "white", relief="solid", borderwidth=1)
                frame.grid(row=row, column=column, sticky="nsew", padx=1, pady=1)
                cell_frames[(target, slot)] = frame

        colors = {"1": "#FF6B6B", "2": "#FFB6C1", "3": "#FFD700", "4": "#B7E4C7", "5": "#90EE90", "daily": "#B2DFDB"}
        for target in dates:
            for event in events_by_date[target]:
                if not event["start"]:
                    continue
                try:
                    hour, minute = map(int, event["start"].split(":"))
                except (TypeError, ValueError):
                    continue
                slot = hour * 2 + (1 if minute >= 30 else 0)
                cell = cell_frames.get((target, slot))
                if not cell:
                    continue
                end = f" - {self.format_time(event['end'])}" if event["end"] else ""
                text = f"{self.format_time(event['start'])}{end}\n{event['title']}"
                tk.Label(
                    cell,
                    text=text,
                    bg=colors.get(event["priority"], "#E8EAF6"),
                    anchor="w",
                    justify=tk.LEFT,
                    wraplength=155 if single_day else 90,
                    font=('Helvetica', 8),
                ).pack(fill=tk.BOTH, expand=True, padx=1, pady=1)
    
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

    def add_daily_task_indicator(self, container, tasks, cell_date, bg_color):
        """Show recurring daily work in month cells and link it to the day schedule."""
        task = tasks[0]
        title = task["title"]
        display_name = title[:11] + "..." if len(title) > 11 else title
        time_text = self.format_time(task["start"])
        if len(tasks) > 1:
            display_name = f"{display_name} +{len(tasks) - 1}"

        row_frame = tk.Frame(container, bg=bg_color)
        row_frame.pack(fill=tk.X, pady=1)
        task_label = tk.Label(
            row_frame,
            text=f"↻ {time_text} {display_name}",
            font=('Helvetica', 8),
            bg='#D8F3DC',
            fg='black',
            anchor='w',
            padx=2,
            cursor='hand2',
        )
        task_label.pack(fill=tk.X, expand=True)
        task_label.bind('<Button-1>', lambda event, day=cell_date: self.open_day_view(day))
    
    def on_task_label_click(self, event, cell_date):
        """Handle click on a task label in the calendar - show all tasks for that day"""
        self.selected_date = cell_date
        self.anchor_date = cell_date
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
        self.anchor_date = cell['date']
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
                end_time = task[5] if len(task) > 5 else ""
                priority = task[3] if len(task) > 3 else task[2]  # Handle old format
                time_display = f" @ {self.format_time(due_time)}" if due_time else ""
                if end_time:
                    time_display += f" - {self.format_time(end_time)}"
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
            fit_window(dialog, 500, 450)
            
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
                end_time = task[5] if len(task) > 5 else ""
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
                time_display = f"Time: {self.format_time(due_time)}" if due_time else ""
                if end_time:
                    time_display += f" - {self.format_time(end_time)}"
                if time_display:
                    time_display += " | "
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
            end_time = task[5] if len(task) > 5 else ""
            priority = task[3] if len(task) > 3 else task[2]  # Handle old format
            notes = task[4] if len(task) > 4 else (task[3] if len(task) > 3 else "No notes")
            
            # Create details dialog
            details_dialog = tk.Toplevel(self.parent_app.root)
            details_dialog.title(f"Task Details: {task_name}")
            fit_window(details_dialog, 450, 420)
            
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
                time_range = self.format_time(due_time)
                if end_time:
                    time_range += f" - {self.format_time(end_time)}"
                ttk.Label(info_frame, text=f"Time: {time_range}", font=('Helvetica', 10)).pack(anchor='w')
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
        """Go to the previous range for the selected view."""
        if self.view_mode == "year":
            target_year = self.anchor_date.year - 1
            day = min(self.anchor_date.day, calendar.monthrange(target_year, self.anchor_date.month)[1])
            self.anchor_date = self.anchor_date.replace(year=target_year, day=day)
        elif self.view_mode == "month":
            year = self.anchor_date.year - (1 if self.anchor_date.month == 1 else 0)
            month = 12 if self.anchor_date.month == 1 else self.anchor_date.month - 1
            self.anchor_date = self.anchor_date.replace(year=year, month=month, day=1)
        elif self.view_mode == "week":
            self.anchor_date -= timedelta(days=7)
        else:
            self.anchor_date -= timedelta(days=1)
        self.displayed_year = self.anchor_date.year
        self.displayed_month = self.anchor_date.month
        self.render_calendar()
    
    def next_month(self):
        """Go to the next range for the selected view."""
        if self.view_mode == "year":
            target_year = self.anchor_date.year + 1
            day = min(self.anchor_date.day, calendar.monthrange(target_year, self.anchor_date.month)[1])
            self.anchor_date = self.anchor_date.replace(year=target_year, day=day)
        elif self.view_mode == "month":
            year = self.anchor_date.year + (1 if self.anchor_date.month == 12 else 0)
            month = 1 if self.anchor_date.month == 12 else self.anchor_date.month + 1
            self.anchor_date = self.anchor_date.replace(year=year, month=month, day=1)
        elif self.view_mode == "week":
            self.anchor_date += timedelta(days=7)
        else:
            self.anchor_date += timedelta(days=1)
        self.displayed_year = self.anchor_date.year
        self.displayed_month = self.anchor_date.month
        self.render_calendar()
    
    def go_to_today(self):
        """Go to current month"""
        today = datetime.now()
        self.displayed_year = today.year
        self.displayed_month = today.month
        self.selected_date = today.date()
        self.anchor_date = today.date()
        self.render_calendar()
        self.update_task_list(self.selected_date)
    
    def refresh(self):
        """Refresh the calendar view"""
        self.render_calendar()
        if self.selected_date:
            self.update_task_list(self.selected_date)
