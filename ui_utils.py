"""Shared helpers for keeping Tk windows usable across screen sizes and DPI scales."""

import tkinter as tk
from tkinter import ttk


def fit_window(
    window,
    requested_width,
    requested_height,
    *,
    min_width=320,
    min_height=180,
    resizable=True,
    margin=48,
):
    """Size and center a window without allowing it to extend off-screen."""
    window.update_idletasks()
    screen_width = max(window.winfo_screenwidth(), min_width)
    screen_height = max(window.winfo_screenheight(), min_height)
    available_width = max(240, screen_width - margin)
    available_height = max(160, screen_height - margin)

    width = min(requested_width, available_width)
    height = min(requested_height, available_height)
    x = max(0, (screen_width - width) // 2)
    y = max(0, (screen_height - height) // 2)

    window.geometry(f"{width}x{height}+{x}+{y}")
    window.minsize(min(min_width, width), min(min_height, height))
    window.resizable(resizable, resizable)
    return width, height


class ScrollableFrame(ttk.Frame):
    """A vertically scrollable frame that also supports the mouse wheel."""

    def __init__(self, parent, **kwargs):
        super().__init__(parent, **kwargs)
        self.canvas = tk.Canvas(self, highlightthickness=0, borderwidth=0, yscrollincrement=16)
        self.scrollbar = tk.Scrollbar(self, orient=tk.VERTICAL, command=self.canvas.yview)
        self.content = ttk.Frame(self.canvas)
        self._content_id = self.canvas.create_window((0, 0), window=self.content, anchor="nw")
        self.canvas.configure(yscrollcommand=self.scrollbar.set)

        self.canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.content.bind("<Configure>", self._sync_scroll_region)
        self.canvas.bind("<Configure>", self._sync_content_width)
        self.winfo_toplevel().bind("<MouseWheel>", self._on_mousewheel, add="+")

    def _sync_scroll_region(self, _event=None):
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))
        self.canvas.yview_moveto(0)

    def _sync_content_width(self, event):
        self.canvas.itemconfigure(self._content_id, width=event.width)

    def _on_mousewheel(self, event):
        first, last = self.canvas.yview()
        direction = int(-event.delta / 120)
        if (direction < 0 and first <= 0) or (direction > 0 and last >= 1):
            return "break"
        self.canvas.yview_scroll(direction, "units")
        return "break"
