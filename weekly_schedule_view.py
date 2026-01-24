"""
Weekly Schedule View Module for TODO App
Provides a weekly schedule-style view of daily tasks with time slots and day columns.
"""

import tkinter as tk
from tkinter import ttk
from datetime import datetime, timedelta


class WeeklyScheduleView:
    def __init__(self, parent_app, schedule_frame, daily_manager):
        self.parent_app = parent_app
        self.schedule_frame = schedule_frame
        self.daily_manager = daily_manager
        
        # Time slot configuration (6 AM to 11 PM by default)
        self.start_hour = 6
        self.end_hour = 23
        
        # Day columns
        self.days = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
        self.day_full_names = {
            "Mon": "Monday", "Tue": "Tuesday", "Wed": "Wednesday",
            "Thu": "Thursday", "Fri": "Friday", "Sat": "Saturday", "Sun": "Sunday"
        }
        
        # Colors for task display
        self.task_colors = {
            "pending": "#FFE4B5",      # Light orange for pending
            "completed": "#90EE90",    # Light green for completed
            "overdue": "#FFB6C1",      # Light pink for overdue
            "current": "#87CEEB"       # Light blue for current time slot
        }
        
        # Store cell references for task placement
        self.time_cells = {}  # (day, hour) -> frame
        self.task_labels = {}  # Store task label widgets
        
        # Create the schedule interface
        self.create_schedule_widgets()
        
    def create_schedule_widgets(self):
        """Create the weekly schedule grid interface"""
        # Main container with scrollable canvas
        main_container = ttk.Frame(self.schedule_frame)
        main_container.pack(fill=tk.BOTH, expand=True)
        
        # Create canvas with scrollbars
        self.canvas = tk.Canvas(main_container, bg="white", highlightthickness=0)
        v_scrollbar = ttk.Scrollbar(main_container, orient=tk.VERTICAL, command=self.canvas.yview)
        h_scrollbar = ttk.Scrollbar(main_container, orient=tk.HORIZONTAL, command=self.canvas.xview)
        
        self.canvas.configure(yscrollcommand=v_scrollbar.set, xscrollcommand=h_scrollbar.set)
        
        # Grid layout for canvas and scrollbars
        self.canvas.grid(row=0, column=0, sticky="nsew")
        v_scrollbar.grid(row=0, column=1, sticky="ns")
        h_scrollbar.grid(row=1, column=0, sticky="ew")
        
        main_container.grid_rowconfigure(0, weight=1)
        main_container.grid_columnconfigure(0, weight=1)
        
        # Create scrollable frame inside canvas
        self.schedule_grid = ttk.Frame(self.canvas)
        self.canvas_window = self.canvas.create_window((0, 0), window=self.schedule_grid, anchor="nw")
        
        # Bind resize events
        self.schedule_grid.bind("<Configure>", self._on_frame_configure)
        self.canvas.bind("<Configure>", self._on_canvas_configure)
        
        # Enable mousewheel scrolling
        self.canvas.bind_all("<MouseWheel>", self._on_mousewheel)
        
        # Build the schedule grid
        self._build_schedule_grid()
        
    def _on_frame_configure(self, event):
        """Reset scroll region when frame size changes"""
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))
        
    def _on_canvas_configure(self, event):
        """Adjust frame width when canvas is resized"""
        # Keep minimum width for proper display
        min_width = 800
        new_width = max(event.width, min_width)
        self.canvas.itemconfig(self.canvas_window, width=new_width)
        
    def _on_mousewheel(self, event):
        """Handle mousewheel scrolling"""
        self.canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")
        
    def _build_schedule_grid(self):
        """Build the schedule grid with time slots and day columns"""
        # Clear existing widgets
        for widget in self.schedule_grid.winfo_children():
            widget.destroy()
        self.time_cells.clear()
        self.task_labels.clear()
        
        # Cell dimensions
        time_col_width = 70
        day_col_width = 100
        row_height = 50
        
        # Header row with day names
        # Empty corner cell
        corner = tk.Frame(self.schedule_grid, width=time_col_width, height=40, 
                         bg="#4a4a4a", relief="ridge", bd=1)
        corner.grid(row=0, column=0, sticky="nsew")
        corner.grid_propagate(False)
        
        tk.Label(corner, text="Time", font=('Helvetica', 9, 'bold'), 
                bg="#4a4a4a", fg="white").place(relx=0.5, rely=0.5, anchor="center")
        
        # Day headers with current day highlighted
        current_day = datetime.now().strftime("%a")
        for col, day in enumerate(self.days, start=1):
            bg_color = "#2196F3" if day == current_day else "#4a4a4a"
            header = tk.Frame(self.schedule_grid, width=day_col_width, height=40,
                            bg=bg_color, relief="ridge", bd=1)
            header.grid(row=0, column=col, sticky="nsew")
            header.grid_propagate(False)
            
            tk.Label(header, text=self.day_full_names[day], font=('Helvetica', 9, 'bold'),
                    bg=bg_color, fg="white").place(relx=0.5, rely=0.5, anchor="center")
        
        # Time rows
        current_hour = datetime.now().hour
        for row, hour in enumerate(range(self.start_hour, self.end_hour + 1), start=1):
            # Time label column
            time_str = self._format_hour(hour)
            is_current_hour = (hour == current_hour)
            
            time_bg = "#e3f2fd" if is_current_hour else "#f5f5f5"
            time_frame = tk.Frame(self.schedule_grid, width=time_col_width, height=row_height,
                                 bg=time_bg, relief="ridge", bd=1)
            time_frame.grid(row=row, column=0, sticky="nsew")
            time_frame.grid_propagate(False)
            
            tk.Label(time_frame, text=time_str, font=('Helvetica', 8),
                    bg=time_bg).place(relx=0.5, rely=0.5, anchor="center")
            
            # Day cells for this hour
            for col, day in enumerate(self.days, start=1):
                is_today = (day == current_day)
                
                if is_current_hour and is_today:
                    cell_bg = self.task_colors["current"]
                elif is_today:
                    cell_bg = "#f0f8ff"  # Light blue tint for today
                else:
                    cell_bg = "white"
                    
                cell = tk.Frame(self.schedule_grid, width=day_col_width, height=row_height,
                               bg=cell_bg, relief="ridge", bd=1)
                cell.grid(row=row, column=col, sticky="nsew")
                cell.grid_propagate(False)
                
                # Store cell reference
                self.time_cells[(day, hour)] = cell
                
        # Configure column weights for proper resizing
        self.schedule_grid.grid_columnconfigure(0, weight=0, minsize=time_col_width)
        for col in range(1, len(self.days) + 1):
            self.schedule_grid.grid_columnconfigure(col, weight=1, minsize=day_col_width)
            
    def _format_hour(self, hour):
        """Format hour based on user's time preference"""
        if hasattr(self.parent_app, 'use_24_hour') and self.parent_app.use_24_hour.get():
            return f"{hour:02d}:00"
        else:
            if hour == 0:
                return "12:00 AM"
            elif hour < 12:
                return f"{hour}:00 AM"
            elif hour == 12:
                return "12:00 PM"
            else:
                return f"{hour-12}:00 PM"
                
    def refresh(self):
        """Refresh the schedule view with current daily tasks"""
        # Rebuild grid (to update current time highlighting)
        self._build_schedule_grid()
        
        # Get tasks from daily manager
        tasks = self._get_daily_tasks()
        
        # Place tasks on the schedule
        for task in tasks:
            self._place_task_on_schedule(task)
            
    def _get_daily_tasks(self):
        """Get daily tasks from the daily manager's treeview"""
        tasks = []
        
        if not hasattr(self.daily_manager, 'daily_tree'):
            return tasks
            
        for item in self.daily_manager.daily_tree.get_children():
            values = self.daily_manager.daily_tree.item(item, 'values')
            if len(values) >= 8:
                task = {
                    'days': values[0],      # Days string like "Mon,Wed,Fri"
                    'time': values[1],      # Time string
                    'name': values[2],      # Task name
                    'status': values[3],    # Status
                    'original': values[7]   # Original text
                }
                tasks.append(task)
                
        return tasks
        
    def _place_task_on_schedule(self, task):
        """Place a task on the schedule grid"""
        # Parse days
        days_str = task['days']
        task_days = [d.strip() for d in days_str.split(',')]
        
        # Parse time to get hour
        time_str = task['time']
        try:
            # Handle both 12-hour and 24-hour formats
            if 'AM' in time_str or 'PM' in time_str:
                # 12-hour format
                time_str_clean = time_str.replace('AM', '').replace('PM', '').strip()
                hour = int(time_str_clean.split(':')[0])
                if 'PM' in time_str and hour != 12:
                    hour += 12
                elif 'AM' in time_str and hour == 12:
                    hour = 0
            else:
                # 24-hour format
                hour = int(time_str.split(':')[0])
        except (ValueError, IndexError):
            hour = 9  # Default to 9 AM if parsing fails
            
        # Check if hour is within visible range
        if hour < self.start_hour or hour > self.end_hour:
            return
            
        # Determine task color based on status
        status = task['status'].lower()
        if 'completed' in status:
            bg_color = self.task_colors["completed"]
        elif 'overdue' in status:
            bg_color = self.task_colors["overdue"]
        else:
            bg_color = self.task_colors["pending"]
            
        # Place task in each applicable day column
        for day in task_days:
            day = day.strip()
            if day in self.days and (day, hour) in self.time_cells:
                cell = self.time_cells[(day, hour)]
                
                # Create task label
                task_label = tk.Label(
                    cell,
                    text=self._truncate_text(task['name'], 12),
                    font=('Helvetica', 7),
                    bg=bg_color,
                    relief="raised",
                    bd=1,
                    padx=2,
                    pady=1,
                    wraplength=90
                )
                task_label.pack(fill=tk.X, padx=2, pady=1)
                
                # Bind click to show task details
                task_label.bind("<Button-1>", lambda e, t=task: self._show_task_details(t))
                
                # Tooltip on hover
                self._create_tooltip(task_label, f"{task['name']}\n{task['time']} - {task['status']}")
                
    def _truncate_text(self, text, max_length):
        """Truncate text with ellipsis if too long"""
        if len(text) > max_length:
            return text[:max_length-2] + ".."
        return text
        
    def _create_tooltip(self, widget, text):
        """Create a tooltip for a widget"""
        def show_tooltip(event):
            tooltip = tk.Toplevel(widget)
            tooltip.wm_overrideredirect(True)
            tooltip.wm_geometry(f"+{event.x_root+10}+{event.y_root+10}")
            
            label = tk.Label(tooltip, text=text, bg="#ffffe0", relief="solid", bd=1,
                           font=('Helvetica', 8), justify=tk.LEFT)
            label.pack()
            
            widget.tooltip = tooltip
            
        def hide_tooltip(event):
            if hasattr(widget, 'tooltip'):
                widget.tooltip.destroy()
                
        widget.bind("<Enter>", show_tooltip)
        widget.bind("<Leave>", hide_tooltip)
        
    def _show_task_details(self, task):
        """Show task details when clicked"""
        # Find the item in the daily tree and show its details
        for item in self.daily_manager.daily_tree.get_children():
            values = self.daily_manager.daily_tree.item(item, 'values')
            if len(values) >= 8 and values[7] == task['original']:
                self.daily_manager.daily_tree.selection_set(item)
                self.daily_manager.show_daily_task_notes(item)
                break
