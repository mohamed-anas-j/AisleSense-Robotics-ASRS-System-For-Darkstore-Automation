"""
AisleSense Region Navigator — Main GUI Application
===================================================
Tkinter application for interactive map-based region editing and robot
navigation control.

Features:
    - Load ROS 2 map YAML/PGM files with zoom, pan, and scroll.
    - Draw and name polygon regions with per-region approach poses.
    - Dock pose — saved initial robot pose, auto-published as a 2D
      Pose Estimate on startup.
    - Scan tour — ordered region list for one-click autonomous patrol
      that visits each region with configurable dwell time and
      returns to the dock on completion.
"""

import math
import os
import tkinter as tk
from tkinter import ttk, messagebox, simpledialog, filedialog

from PIL import Image, ImageTk

from config import (
    WINDOW_TITLE, WINDOW_SIZE, CANVAS_BG, PANEL_BG, PANEL_FG,
    BUTTON_BG, BUTTON_FG, STATUS_BG, STATUS_FG,
    NAV_ARROW_LEN, NAV_MARKER_RADIUS, DEFAULT_MAP_YAML,
    DEFAULT_REGIONS_FILE, DOCK_COLOR, DOCK_MARKER_RADIUS,
    ACCENT_GREEN, ACCENT_RED, ACCENT_BLUE, ACCENT_YELLOW,
    ACCENT_PEACH, ACCENT_TEAL, ACCENT_MAUVE,
    SCAN_WAIT_SECONDS,
)
from map_loader import MapData
from region_manager import RegionManager
from navigator import Navigator


# ─── Helpers ──────────────────────────────────────────────────

def _lighten(hex_color: str, factor: float = 0.55) -> str:
    """Return a lighter version of a hex colour."""
    r = int(hex_color[1:3], 16)
    g = int(hex_color[3:5], 16)
    b = int(hex_color[5:7], 16)
    r = int(r + (255 - r) * factor)
    g = int(g + (255 - g) * factor)
    b = int(b + (255 - b) * factor)
    return f"#{r:02x}{g:02x}{b:02x}"


def _darken(hex_color: str, factor: float = 0.3) -> str:
    """Return a darker version of a hex colour."""
    r = int(int(hex_color[1:3], 16) * (1 - factor))
    g = int(int(hex_color[3:5], 16) * (1 - factor))
    b = int(int(hex_color[5:7], 16) * (1 - factor))
    return f"#{r:02x}{g:02x}{b:02x}"


# ──────────────────────────────────────────────────────────────
#  Main application
# ──────────────────────────────────────────────────────────────

class AisleSenseNavigatorApp:
    """Tkinter GUI for region editing, dock pose, scan tour."""

    # Interaction modes
    IDLE = "idle"
    DRAWING = "drawing"
    SET_NAV = "set_nav"
    SET_DOCK = "set_dock"

    def __init__(self, root: tk.Tk, *,
                 map_yaml: str = None,
                 regions_file: str = DEFAULT_REGIONS_FILE,
                 ros_domain_id: int = 42):
        self.root = root
        self.root.title(WINDOW_TITLE)
        self.root.geometry(WINDOW_SIZE)
        self.root.configure(bg=PANEL_BG)
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

        # State
        self.map_data: MapData | None = None
        self.scale = 1.0
        self._tk_img = None           # prevent GC
        self.mode = self.IDLE
        self._draw_pts: list = []     # canvas coords during drawing
        self._draw_ids: list = []     # temp canvas item ids
        self._pending_region = None   # Region waiting for nav point
        self._dock_yaw_pending = None # canvas coords for dock direction

        # Managers
        self.region_mgr = RegionManager(regions_file)
        self.navigator = Navigator(domain_id=ros_domain_id)

        # Build UI
        self._build_ui()

        # Load map if given
        if map_yaml and os.path.isfile(map_yaml):
            self._load_map(map_yaml)
        elif os.path.isfile(DEFAULT_MAP_YAML):
            self._load_map(DEFAULT_MAP_YAML)

        # Load saved regions (includes dock_pose + scan_order)
        self.region_mgr.load()
        self._redraw_overlay()
        self._refresh_panel()
        self._refresh_scan_panel()

        # Auto‑publish dock pose on startup
        if self.region_mgr.dock_pose:
            self._publish_dock_pose()

    # ──────────────────────────────────────────────────────────
    #  UI construction
    # ──────────────────────────────────────────────────────────

    def _build_ui(self):
        # ── Menu bar ──────────────────────────────────────────
        menubar = tk.Menu(self.root, bg=PANEL_BG, fg=PANEL_FG,
                          activebackground=ACCENT_BLUE,
                          activeforeground="#000")
        file_menu = tk.Menu(menubar, tearoff=0, bg=PANEL_BG, fg=PANEL_FG,
                            activebackground=ACCENT_BLUE,
                            activeforeground="#000")
        file_menu.add_command(label="Open Map…", command=self._open_map_dialog)
        file_menu.add_separator()
        file_menu.add_command(label="Save Regions", command=self._save)
        file_menu.add_command(label="Load Regions…",
                              command=self._load_regions_dialog)
        file_menu.add_separator()
        file_menu.add_command(label="Exit", command=self._on_close)
        menubar.add_cascade(label="File", menu=file_menu)
        self.root.config(menu=menubar)

        # ── Main paned container ─────────────────────────────
        main = ttk.PanedWindow(self.root, orient=tk.HORIZONTAL)
        main.pack(fill=tk.BOTH, expand=True)

        # Left toolbar
        self._build_toolbar(main)
        # Centre canvas
        self._build_canvas(main)
        # Right panel (regions + scan)
        self._build_right_panel(main)
        # Status bar
        self._build_status_bar()

    # ── Toolbar ───────────────────────────────────────────────
    def _build_toolbar(self, parent):
        frame = tk.Frame(parent, bg=PANEL_BG, width=175)
        parent.add(frame, weight=0)

        lbl = tk.Label(frame, text="⚙  Tools", bg=PANEL_BG, fg=PANEL_FG,
                       font=("Helvetica", 13, "bold"))
        lbl.pack(pady=(14, 10))

        btn_style = dict(
            bg=BUTTON_BG, fg=BUTTON_FG,
            activebackground=_lighten(BUTTON_BG, 0.3),
            activeforeground="#fff",
            relief=tk.FLAT, padx=8, pady=7, width=18,
            font=("Helvetica", 10), cursor="hand2",
        )

        # ── Section: Regions ──
        self._section_label(frame, "REGIONS")
        for label, cmd, color in [
            ("Add Region", self._start_drawing, ACCENT_TEAL),
            ("Set Nav Pose", self._start_set_nav, ACCENT_BLUE),
            ("Delete Region", self._delete_selected, ACCENT_RED),
        ]:
            b = tk.Button(frame, text=label, command=cmd, **btn_style)
            b.configure(highlightbackground=color, highlightthickness=1)
            b.pack(pady=3, padx=10)

        # ── Section: Dock ──
        self._section_label(frame, "DOCK")
        for label, cmd, color in [
            ("Set Dock Pose", self._start_set_dock, ACCENT_YELLOW),
            ("Go to Dock", self._go_to_dock, ACCENT_PEACH),
            ("Clear Dock", self._clear_dock, ACCENT_RED),
        ]:
            b = tk.Button(frame, text=label, command=cmd, **btn_style)
            b.configure(highlightbackground=color, highlightthickness=1)
            b.pack(pady=3, padx=10)

        # ── Section: View ──
        self._section_label(frame, "VIEW")
        for label, cmd in [
            ("Zoom In  (+)", self._zoom_in),
            ("Zoom Out (−)", self._zoom_out),
            ("Fit View", self._zoom_fit),
        ]:
            tk.Button(frame, text=label, command=cmd,
                      **btn_style).pack(pady=3, padx=10)

        # ── Save ──
        self._section_label(frame, "")
        save_btn = tk.Button(frame, text="💾  Save All", command=self._save,
                             bg=ACCENT_GREEN, fg="#1e1e2e",
                             activebackground=_lighten(ACCENT_GREEN, 0.3),
                             relief=tk.FLAT, padx=8, pady=7, width=18,
                             font=("Helvetica", 10, "bold"), cursor="hand2")
        save_btn.pack(pady=6, padx=10)

    @staticmethod
    def _section_label(parent, text):
        tk.Label(parent, text=text, bg=PANEL_BG, fg="#585b70",
                 font=("Helvetica", 9, "bold")).pack(pady=(12, 2), padx=10,
                                                      anchor=tk.W)

    # ── Canvas ────────────────────────────────────────────────
    def _build_canvas(self, parent):
        frame = tk.Frame(parent, bg=CANVAS_BG)
        parent.add(frame, weight=1)

        self.canvas = tk.Canvas(frame, bg=CANVAS_BG, highlightthickness=0)
        h_scroll = tk.Scrollbar(frame, orient=tk.HORIZONTAL,
                                command=self.canvas.xview)
        v_scroll = tk.Scrollbar(frame, orient=tk.VERTICAL,
                                command=self.canvas.yview)
        self.canvas.configure(xscrollcommand=h_scroll.set,
                              yscrollcommand=v_scroll.set)

        h_scroll.pack(side=tk.BOTTOM, fill=tk.X)
        v_scroll.pack(side=tk.RIGHT, fill=tk.Y)
        self.canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        # Bindings
        self.canvas.bind("<Button-1>", self._on_left_click)
        self.canvas.bind("<Button-3>", self._on_right_click)
        self.canvas.bind("<Motion>", self._on_motion)
        self.canvas.bind("<MouseWheel>", self._on_scroll)         # Win/macOS
        self.canvas.bind("<Button-4>", self._on_scroll_up)        # Linux
        self.canvas.bind("<Button-5>", self._on_scroll_down)      # Linux
        self.root.bind("<Escape>", self._cancel)
        self.root.bind("<Return>", self._finish_polygon_key)

    # ── Right panel (regions + scan) ──────────────────────────
    def _build_right_panel(self, parent):
        outer = tk.Frame(parent, bg=PANEL_BG, width=280)
        parent.add(outer, weight=0)

        # ── Notebook (tabs) ──
        style = ttk.Style()
        style.theme_use('clam')
        style.configure('Dark.TNotebook', background=PANEL_BG,
                        borderwidth=0)
        style.configure('Dark.TNotebook.Tab', background=BUTTON_BG,
                        foreground=PANEL_FG, padding=[12, 6],
                        font=("Helvetica", 10, "bold"))
        style.map('Dark.TNotebook.Tab',
                  background=[('selected', ACCENT_BLUE)],
                  foreground=[('selected', '#1e1e2e')])

        self._notebook = ttk.Notebook(outer, style='Dark.TNotebook')
        self._notebook.pack(fill=tk.BOTH, expand=True)

        # Tab 1: Regions
        regions_tab = tk.Frame(self._notebook, bg=PANEL_BG)
        self._notebook.add(regions_tab, text=" Regions ")

        canvas_wrap = tk.Canvas(regions_tab, bg=PANEL_BG,
                                highlightthickness=0, width=260)
        scrollbar = tk.Scrollbar(regions_tab, orient=tk.VERTICAL,
                                 command=canvas_wrap.yview)
        self._region_frame = tk.Frame(canvas_wrap, bg=PANEL_BG)
        self._region_frame.bind(
            "<Configure>",
            lambda e: canvas_wrap.configure(
                scrollregion=canvas_wrap.bbox("all")))
        canvas_wrap.create_window((0, 0), window=self._region_frame,
                                  anchor="nw")
        canvas_wrap.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        canvas_wrap.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        # Tab 2: Scan Tour
        scan_tab = tk.Frame(self._notebook, bg=PANEL_BG)
        self._notebook.add(scan_tab, text=" Scan Tour ")
        self._build_scan_tab(scan_tab)

    def _build_scan_tab(self, parent):
        """Build the scan‑tour ordering + controls tab."""
        # ── Header ──
        hdr = tk.Frame(parent, bg=PANEL_BG)
        hdr.pack(fill=tk.X, padx=10, pady=(10, 4))
        tk.Label(hdr, text="Scan Order", bg=PANEL_BG, fg=PANEL_FG,
                 font=("Helvetica", 12, "bold")).pack(side=tk.LEFT)

        # ── Listbox for ordering ──
        list_frame = tk.Frame(parent, bg=PANEL_BG)
        list_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=4)

        self._scan_listbox = tk.Listbox(
            list_frame, bg=BUTTON_BG, fg=PANEL_FG,
            selectbackground=ACCENT_BLUE, selectforeground="#1e1e2e",
            font=("Helvetica", 11), highlightthickness=0,
            relief=tk.FLAT, activestyle='none')
        sb = tk.Scrollbar(list_frame, orient=tk.VERTICAL,
                          command=self._scan_listbox.yview)
        self._scan_listbox.configure(yscrollcommand=sb.set)
        sb.pack(side=tk.RIGHT, fill=tk.Y)
        self._scan_listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        # ── Order buttons ──
        btn_frame = tk.Frame(parent, bg=PANEL_BG)
        btn_frame.pack(fill=tk.X, padx=10, pady=4)

        small_btn = dict(bg=BUTTON_BG, fg=BUTTON_FG, relief=tk.FLAT,
                         font=("Helvetica", 10), cursor="hand2", width=5)
        tk.Button(btn_frame, text="▲ Up", command=self._scan_move_up,
                  **small_btn).pack(side=tk.LEFT, padx=2)
        tk.Button(btn_frame, text="▼ Down", command=self._scan_move_down,
                  **small_btn).pack(side=tk.LEFT, padx=2)
        tk.Button(btn_frame, text="+ Add", command=self._scan_add_region,
                  bg=ACCENT_TEAL, fg="#1e1e2e", relief=tk.FLAT,
                  font=("Helvetica", 10), cursor="hand2",
                  width=5).pack(side=tk.LEFT, padx=2)
        tk.Button(btn_frame, text="− Remove", command=self._scan_remove,
                  bg=ACCENT_RED, fg="#1e1e2e", relief=tk.FLAT,
                  font=("Helvetica", 10), cursor="hand2",
                  width=7).pack(side=tk.LEFT, padx=2)

        # ── Scan control buttons ──
        ctrl_frame = tk.Frame(parent, bg=PANEL_BG)
        ctrl_frame.pack(fill=tk.X, padx=10, pady=(8, 4))

        self._scan_btn = tk.Button(
            ctrl_frame, text="▶  Start Scan", command=self._start_scan,
            bg=ACCENT_GREEN, fg="#1e1e2e",
            activebackground=_lighten(ACCENT_GREEN, 0.3),
            relief=tk.FLAT, font=("Helvetica", 11, "bold"),
            cursor="hand2", pady=8)
        self._scan_btn.pack(fill=tk.X, pady=2)

        self._stop_scan_btn = tk.Button(
            ctrl_frame, text="■  Stop Scan", command=self._stop_scan,
            bg=ACCENT_RED, fg="#1e1e2e",
            activebackground=_lighten(ACCENT_RED, 0.3),
            relief=tk.FLAT, font=("Helvetica", 11, "bold"),
            cursor="hand2", pady=8, state=tk.DISABLED)
        self._stop_scan_btn.pack(fill=tk.X, pady=2)

        # ── Scan status label ──
        self._scan_status_var = tk.StringVar(value="Ready")
        self._scan_status_lbl = tk.Label(
            parent, textvariable=self._scan_status_var,
            bg=PANEL_BG, fg=ACCENT_YELLOW,
            font=("Helvetica", 10), wraplength=250, justify=tk.LEFT)
        self._scan_status_lbl.pack(fill=tk.X, padx=10, pady=(4, 10))

        # ── Dock info ──
        dock_frame = tk.Frame(parent, bg="#1e1e2e",
                              highlightbackground=DOCK_COLOR,
                              highlightthickness=1)
        dock_frame.pack(fill=tk.X, padx=10, pady=(2, 10))
        self._dock_info_var = tk.StringVar(value="Dock: not set")
        tk.Label(dock_frame, textvariable=self._dock_info_var,
                 bg="#1e1e2e", fg=DOCK_COLOR,
                 font=("Helvetica", 10), padx=8, pady=6).pack(fill=tk.X)

    # ── Status bar ────────────────────────────────────────────
    def _build_status_bar(self):
        bar_frame = tk.Frame(self.root, bg=STATUS_BG, height=28)
        bar_frame.pack(side=tk.BOTTOM, fill=tk.X)
        bar_frame.pack_propagate(False)

        self._status_var = tk.StringVar(value="Ready — open a map to begin")
        tk.Label(bar_frame, textvariable=self._status_var,
                 bg=STATUS_BG, fg=STATUS_FG, anchor=tk.W,
                 padx=12, font=("Helvetica", 10)).pack(
                     side=tk.LEFT, fill=tk.X, expand=True)

        # Mode indicator on the right
        self._mode_var = tk.StringVar(value="IDLE")
        self._mode_lbl = tk.Label(
            bar_frame, textvariable=self._mode_var,
            bg=ACCENT_BLUE, fg="#1e1e2e",
            font=("Helvetica", 9, "bold"), padx=10, pady=2)
        self._mode_lbl.pack(side=tk.RIGHT, padx=4, pady=2)

    def _set_status(self, text: str):
        self._status_var.set(text)

    def _update_mode_indicator(self):
        mode_map = {
            self.IDLE: ("IDLE", ACCENT_BLUE),
            self.DRAWING: ("DRAWING", ACCENT_TEAL),
            self.SET_NAV: ("SET NAV", ACCENT_GREEN),
            self.SET_DOCK: ("SET DOCK", ACCENT_YELLOW),
        }
        label, color = mode_map.get(self.mode, ("IDLE", ACCENT_BLUE))
        self._mode_var.set(label)
        self._mode_lbl.configure(bg=color)

    # ──────────────────────────────────────────────────────────
    #  Map loading & display
    # ──────────────────────────────────────────────────────────

    def _open_map_dialog(self):
        path = filedialog.askopenfilename(
            title="Select Map YAML",
            filetypes=[("YAML files", "*.yaml *.yml"), ("All", "*.*")])
        if path:
            self._load_map(path)

    def _load_map(self, yaml_path: str):
        try:
            self.map_data = MapData(yaml_path)
        except Exception as exc:
            messagebox.showerror("Map Error", str(exc))
            return
        self._zoom_fit()
        self._set_status(
            f"Loaded: {os.path.basename(yaml_path)}  "
            f"({self.map_data.width}×{self.map_data.height} px, "
            f"res {self.map_data.resolution} m/px)")

    def _render_map(self):
        """Create the scaled map image and draw it on the canvas."""
        if not self.map_data:
            return
        base = self.map_data.get_display_image()
        w = max(1, int(self.map_data.width * self.scale))
        h = max(1, int(self.map_data.height * self.scale))
        scaled = base.resize((w, h), Image.NEAREST)
        self._tk_img = ImageTk.PhotoImage(scaled)
        self.canvas.delete("all")
        self.canvas.create_image(0, 0, anchor=tk.NW, image=self._tk_img,
                                 tags="map_img")
        self.canvas.configure(scrollregion=(0, 0, w, h))

    # ──────────────────────────────────────────────────────────
    #  Coordinate helpers
    # ──────────────────────────────────────────────────────────

    def _canvas_to_pixel(self, cx, cy):
        return cx / self.scale, cy / self.scale

    def _pixel_to_canvas(self, px, py):
        return px * self.scale, py * self.scale

    def _canvas_to_map(self, cx, cy):
        px, py = self._canvas_to_pixel(cx, cy)
        return self.map_data.pixel_to_map(px, py)

    def _map_to_canvas(self, mx, my):
        px, py = self.map_data.map_to_pixel(mx, my)
        return self._pixel_to_canvas(px, py)

    # ──────────────────────────────────────────────────────────
    #  Zoom
    # ──────────────────────────────────────────────────────────

    def _zoom_fit(self):
        if not self.map_data:
            return
        self.root.update_idletasks()
        cw = self.canvas.winfo_width() or 800
        ch = self.canvas.winfo_height() or 600
        sx = cw / self.map_data.width
        sy = ch / self.map_data.height
        self.scale = min(sx, sy)
        self._apply_zoom()

    def _zoom_in(self):
        self.scale = min(self.scale * 1.25, 10.0)
        self._apply_zoom()

    def _zoom_out(self):
        self.scale = max(self.scale / 1.25, 0.05)
        self._apply_zoom()

    def _on_scroll(self, event):
        if event.delta > 0:
            self._zoom_in()
        else:
            self._zoom_out()

    def _on_scroll_up(self, _):
        self._zoom_in()

    def _on_scroll_down(self, _):
        self._zoom_out()

    def _apply_zoom(self):
        self._render_map()
        self._redraw_overlay()

    # ──────────────────────────────────────────────────────────
    #  Region overlay drawing
    # ──────────────────────────────────────────────────────────

    def _redraw_overlay(self):
        """Redraw every region polygon + nav marker + dock on canvas."""
        self.canvas.delete("region")
        self.canvas.delete("nav_marker")
        self.canvas.delete("dock_marker")
        if not self.map_data:
            return
        for region in self.region_mgr.regions:
            self._draw_region(region)
            self._draw_nav_marker(region)
        self._draw_dock_marker()

    def _draw_region(self, region):
        coords = []
        for mx, my in region.polygon:
            cx, cy = self._map_to_canvas(mx, my)
            coords.extend([cx, cy])
        if len(coords) < 6:
            return
        # Filled polygon
        fill = _lighten(region.color, 0.6)
        self.canvas.create_polygon(
            coords, fill=fill, outline=region.color, width=2,
            stipple="gray50", tags="region")
        # Label at centroid
        centroid = region.centroid()
        lcx, lcy = self._map_to_canvas(*centroid)
        self.canvas.create_text(
            lcx, lcy, text=region.name, fill=region.color,
            font=("Helvetica", 11, "bold"), tags="region")

    def _draw_nav_marker(self, region):
        """Dot + arrow showing where the robot will go and face."""
        nx, ny = region.nav_point
        cx, cy = self._map_to_canvas(nx, ny)
        r = NAV_MARKER_RADIUS
        # Dot
        self.canvas.create_oval(
            cx - r, cy - r, cx + r, cy + r,
            fill=ACCENT_GREEN, outline=_darken(ACCENT_GREEN),
            width=2, tags="nav_marker")
        # Arrow in the approach direction
        length = NAV_ARROW_LEN
        yaw = region.nav_yaw
        ax = cx + length * math.cos(yaw)
        ay = cy - length * math.sin(yaw)   # canvas Y is inverted
        self.canvas.create_line(
            cx, cy, ax, ay, fill=ACCENT_GREEN, width=3,
            arrow=tk.LAST, arrowshape=(10, 12, 5), tags="nav_marker")

    def _draw_dock_marker(self):
        """Draw the dock/home position on the map."""
        if not self.region_mgr.dock_pose or not self.map_data:
            return
        dx, dy, dyaw = self.region_mgr.dock_pose
        cx, cy = self._map_to_canvas(dx, dy)
        r = DOCK_MARKER_RADIUS

        # Outer ring
        self.canvas.create_oval(
            cx - r - 3, cy - r - 3, cx + r + 3, cy + r + 3,
            outline=DOCK_COLOR, width=2, dash=(4, 2),
            tags="dock_marker")
        # Inner dot
        self.canvas.create_oval(
            cx - r, cy - r, cx + r, cy + r,
            fill=DOCK_COLOR, outline=_darken(DOCK_COLOR),
            width=2, tags="dock_marker")
        # Direction arrow
        length = NAV_ARROW_LEN + 6
        ax = cx + length * math.cos(dyaw)
        ay = cy - length * math.sin(dyaw)
        self.canvas.create_line(
            cx, cy, ax, ay, fill=DOCK_COLOR, width=3,
            arrow=tk.LAST, arrowshape=(12, 14, 6), tags="dock_marker")
        # Label
        self.canvas.create_text(
            cx, cy - r - 12, text="DOCK", fill=DOCK_COLOR,
            font=("Helvetica", 9, "bold"), tags="dock_marker")

    # ──────────────────────────────────────────────────────────
    #  Drawing interaction (add region)
    # ──────────────────────────────────────────────────────────

    def _start_drawing(self):
        if not self.map_data:
            messagebox.showinfo("No Map",
                                "Load a map first (File ▸ Open Map).")
            return
        self.mode = self.DRAWING
        self._update_mode_indicator()
        self._draw_pts.clear()
        self._draw_ids.clear()
        self._set_status(
            "DRAW MODE — Left‑click to add vertices · "
            "Right‑click or Enter to finish · Escape to cancel")

    def _finish_polygon_key(self, _event=None):
        if self.mode == self.DRAWING:
            self._finish_polygon()

    def _finish_polygon(self):
        if len(self._draw_pts) < 3:
            messagebox.showwarning(
                "Too few points", "Need at least 3 vertices.")
            return

        # Ask for name
        name = simpledialog.askstring("Region Name",
                                      "Enter a name for this region:",
                                      parent=self.root)
        if not name or not name.strip():
            self._cancel()
            return
        name = name.strip()
        if self.region_mgr.get(name):
            messagebox.showwarning("Duplicate",
                                   f"Region '{name}' already exists.")
            return

        # Convert canvas points → map coordinates
        polygon_map = []
        for i in range(0, len(self._draw_pts), 2):
            mx, my = self._canvas_to_map(self._draw_pts[i],
                                          self._draw_pts[i + 1])
            polygon_map.append([mx, my])

        # Create region with centroid as default nav point
        region = self.region_mgr.add(name, polygon_map)

        # Clear temp drawing
        for cid in self._draw_ids:
            self.canvas.delete(cid)
        self._draw_ids.clear()
        self._draw_pts.clear()

        # Transition: let user set the approach point
        self._pending_region = region
        self.mode = self.SET_NAV
        self._update_mode_indicator()
        self._redraw_overlay()
        self._refresh_panel()
        self._set_status(
            f"Region '{name}' created — "
            f"click the map to set the approach point  "
            f"(Escape to use centroid)")

    # ──────────────────────────────────────────────────────────
    #  Set navigation pose
    # ──────────────────────────────────────────────────────────

    def _start_set_nav(self):
        """Enter SET_NAV mode for the currently‑selected region."""
        if not self.map_data:
            return
        name = self._pick_region("Set approach pose for which region?")
        if not name:
            return
        region = self.region_mgr.get(name)
        if not region:
            return
        self._pending_region = region
        self.mode = self.SET_NAV
        self._update_mode_indicator()
        self._set_status(
            f"Click the map to set the approach point for '{name}'  "
            f"(Escape to cancel)")

    def _place_nav_point(self, cx, cy):
        """Place approach point at canvas coords and auto‑orient."""
        mx, my = self._canvas_to_map(cx, cy)
        self._pending_region.nav_point = [mx, my]
        # Auto‑orient: face toward region centroid
        self._pending_region.nav_yaw = \
            self._pending_region.auto_orientation_from([mx, my])
        self._pending_region = None
        self.mode = self.IDLE
        self._update_mode_indicator()
        self._redraw_overlay()
        self._refresh_panel()
        self._set_status("Approach pose set ✓")

    # ──────────────────────────────────────────────────────────
    #  Dock pose
    # ──────────────────────────────────────────────────────────

    def _start_set_dock(self):
        """Enter SET_DOCK mode — first click = position."""
        if not self.map_data:
            messagebox.showinfo("No Map",
                                "Load a map first (File ▸ Open Map).")
            return
        self.mode = self.SET_DOCK
        self._dock_yaw_pending = None
        self._update_mode_indicator()
        self._set_status(
            "SET DOCK — Left‑click to place the dock position  ·  "
            "Escape to cancel")

    def _place_dock_position(self, cx, cy):
        """First click in SET_DOCK — record position, wait for yaw click."""
        self._dock_yaw_pending = (cx, cy)
        self._set_status(
            "SET DOCK — Now click a second point to set the "
            "facing direction (or Escape to face right)")

    def _place_dock_yaw(self, cx2, cy2):
        """Second click in SET_DOCK — compute yaw from first→second."""
        cx1, cy1 = self._dock_yaw_pending
        mx1, my1 = self._canvas_to_map(cx1, cy1)
        mx2, my2 = self._canvas_to_map(cx2, cy2)
        yaw = math.atan2(my2 - my1, mx2 - mx1)
        self.region_mgr.dock_pose = [mx1, my1, yaw]
        self._dock_yaw_pending = None
        self.mode = self.IDLE
        self._update_mode_indicator()
        self._redraw_overlay()
        self._update_dock_info()
        self._set_status(
            f"Dock set at ({mx1:.2f}, {my1:.2f}) ∠"
            f"{math.degrees(yaw):.0f}° ✓")
        # Publish immediately
        self._publish_dock_pose()

    def _publish_dock_pose(self):
        """Publish saved dock pose as initial pose estimate."""
        if not self.region_mgr.dock_pose:
            return
        x, y, yaw = self.region_mgr.dock_pose

        def _cb(ok, msg):
            self.root.after(0, lambda: self._set_status(
                f"Dock initial pose: {msg}"))

        self.navigator.set_initial_pose(x, y, yaw, callback=_cb)

    def _go_to_dock(self):
        """Navigate robot back to dock."""
        if not self.region_mgr.dock_pose:
            messagebox.showinfo("No Dock",
                                "Set a dock pose first.")
            return
        x, y, yaw = self.region_mgr.dock_pose
        self._set_status(f"Navigating to Dock…")

        def _cb(ok, msg):
            self.root.after(0, lambda: self._set_status(
                f"Dock: {msg}" if ok else f"Dock FAILED: {msg}"))

        self.navigator.navigate_to(x, y, yaw, callback=_cb)

    def _clear_dock(self):
        """Remove the saved dock pose."""
        if self.region_mgr.dock_pose:
            if messagebox.askyesno("Clear Dock",
                                   "Remove saved dock pose?"):
                self.region_mgr.dock_pose = None
                self._redraw_overlay()
                self._update_dock_info()
                self._set_status("Dock pose cleared")

    def _update_dock_info(self):
        if self.region_mgr.dock_pose:
            x, y, yaw = self.region_mgr.dock_pose
            self._dock_info_var.set(
                f"Dock: ({x:.2f}, {y:.2f}) ∠{math.degrees(yaw):.0f}°")
        else:
            self._dock_info_var.set("Dock: not set")

    # ──────────────────────────────────────────────────────────
    #  Scan tour
    # ──────────────────────────────────────────────────────────

    def _refresh_scan_panel(self):
        """Sync the scan listbox with region_mgr.scan_order."""
        self._scan_listbox.delete(0, tk.END)
        for i, name in enumerate(self.region_mgr.scan_order):
            self._scan_listbox.insert(tk.END, f"  {i+1}.  {name}")
        self._update_dock_info()

    def _scan_add_region(self):
        """Add a region to the scan order."""
        available = [n for n in self.region_mgr.names()
                     if n not in self.region_mgr.scan_order]
        if not available:
            messagebox.showinfo("Scan Order",
                                "All regions are already in the scan list.")
            return
        # Quick picker
        name = self._pick_from_list("Add to Scan Order", available)
        if name:
            self.region_mgr.scan_order.append(name)
            self._refresh_scan_panel()

    def _scan_remove(self):
        sel = self._scan_listbox.curselection()
        if not sel:
            return
        idx = sel[0]
        if 0 <= idx < len(self.region_mgr.scan_order):
            self.region_mgr.scan_order.pop(idx)
            self._refresh_scan_panel()

    def _scan_move_up(self):
        sel = self._scan_listbox.curselection()
        if not sel or sel[0] == 0:
            return
        idx = sel[0]
        order = self.region_mgr.scan_order
        order[idx - 1], order[idx] = order[idx], order[idx - 1]
        self._refresh_scan_panel()
        self._scan_listbox.selection_set(idx - 1)

    def _scan_move_down(self):
        sel = self._scan_listbox.curselection()
        if not sel:
            return
        idx = sel[0]
        order = self.region_mgr.scan_order
        if idx >= len(order) - 1:
            return
        order[idx], order[idx + 1] = order[idx + 1], order[idx]
        self._refresh_scan_panel()
        self._scan_listbox.selection_set(idx + 1)

    def _start_scan(self):
        """Begin the autonomous scan tour."""
        if not self.region_mgr.scan_order:
            messagebox.showinfo("Scan Tour",
                                "Add regions to the scan order first.")
            return
        if self.navigator.scanning:
            messagebox.showinfo("Scan Tour", "A scan is already running.")
            return

        waypoints = self.region_mgr.get_scan_waypoints()
        # Append dock as final destination if set
        if self.region_mgr.dock_pose:
            x, y, yaw = self.region_mgr.dock_pose
            waypoints.append(("Dock", x, y, yaw))

        self._scan_btn.configure(state=tk.DISABLED)
        self._stop_scan_btn.configure(state=tk.NORMAL)
        self._scan_status_var.set("Starting scan tour…")

        def _progress(idx, name, status, msg):
            self.root.after(0, lambda: self._scan_status_var.set(msg))
            self.root.after(0, lambda: self._set_status(msg))
            # Highlight current in listbox
            self.root.after(0, lambda: self._highlight_scan_item(idx))

        def _done(ok, msg):
            def _update():
                self._scan_status_var.set(msg)
                self._set_status(msg)
                self._scan_btn.configure(state=tk.NORMAL)
                self._stop_scan_btn.configure(state=tk.DISABLED)
                self._scan_listbox.selection_clear(0, tk.END)
            self.root.after(0, _update)

        self.navigator.run_scan_tour(
            waypoints, wait_seconds=SCAN_WAIT_SECONDS,
            progress_cb=_progress, done_cb=_done)

    def _stop_scan(self):
        self.navigator.cancel_scan()
        self._scan_status_var.set("Stopping…")

    def _highlight_scan_item(self, idx):
        self._scan_listbox.selection_clear(0, tk.END)
        if 0 <= idx < self._scan_listbox.size():
            self._scan_listbox.selection_set(idx)
            self._scan_listbox.see(idx)

    # ──────────────────────────────────────────────────────────
    #  Delete region
    # ──────────────────────────────────────────────────────────

    def _delete_selected(self):
        name = self._pick_region("Delete which region?")
        if not name:
            return
        if messagebox.askyesno("Confirm",
                               f"Delete region '{name}'?"):
            self.region_mgr.remove(name)
            self._redraw_overlay()
            self._refresh_panel()
            self._refresh_scan_panel()
            self._set_status(f"Deleted '{name}'")

    def _pick_region(self, prompt: str):
        """Show a simple picker and return the chosen region name."""
        names = self.region_mgr.names()
        if not names:
            messagebox.showinfo("No Regions", "No regions defined yet.")
            return None
        if len(names) == 1:
            return names[0]
        return self._pick_from_list(prompt, names)

    def _pick_from_list(self, prompt: str, items: list[str]):
        """Generic picker dialog. Returns selected string or None."""
        win = tk.Toplevel(self.root)
        win.title("Select")
        win.geometry("280x340")
        win.configure(bg=PANEL_BG)
        win.transient(self.root)
        win.grab_set()

        tk.Label(win, text=prompt, bg=PANEL_BG, fg=PANEL_FG,
                 font=("Helvetica", 10),
                 wraplength=250).pack(pady=(12, 6))

        lb = tk.Listbox(win, bg=BUTTON_BG, fg=BUTTON_FG,
                        selectbackground=ACCENT_BLUE,
                        selectforeground="#1e1e2e",
                        font=("Helvetica", 11), height=10,
                        relief=tk.FLAT, highlightthickness=0)
        for n in items:
            lb.insert(tk.END, f"  {n}")
        lb.pack(fill=tk.BOTH, expand=True, padx=12, pady=6)

        result = [None]

        def _ok(_=None):
            sel = lb.curselection()
            if sel:
                result[0] = items[sel[0]]
            win.destroy()

        lb.bind("<Double-Button-1>", _ok)
        tk.Button(win, text="OK", command=_ok, bg=ACCENT_BLUE,
                  fg="#1e1e2e", relief=tk.FLAT,
                  font=("Helvetica", 10, "bold"),
                  padx=20, cursor="hand2").pack(pady=(0, 10))
        win.wait_window()
        return result[0]

    # ──────────────────────────────────────────────────────────
    #  Canvas event handlers
    # ──────────────────────────────────────────────────────────

    def _on_left_click(self, event):
        cx = self.canvas.canvasx(event.x)
        cy = self.canvas.canvasy(event.y)

        if self.mode == self.DRAWING:
            # Add vertex
            self._draw_pts.extend([cx, cy])
            r = 4
            dot = self.canvas.create_oval(
                cx - r, cy - r, cx + r, cy + r,
                fill=ACCENT_YELLOW, outline=ACCENT_PEACH,
                tags="draw_temp")
            self._draw_ids.append(dot)
            n = len(self._draw_pts)
            if n >= 4:
                line = self.canvas.create_line(
                    self._draw_pts[n - 4], self._draw_pts[n - 3],
                    cx, cy, fill=ACCENT_YELLOW, width=2, tags="draw_temp")
                self._draw_ids.append(line)
            nv = n // 2
            self._set_status(
                f"Vertex {nv} placed — "
                f"right‑click/Enter to finish ({nv} vertices)")

        elif self.mode == self.SET_NAV:
            self._place_nav_point(cx, cy)

        elif self.mode == self.SET_DOCK:
            if self._dock_yaw_pending is None:
                self._place_dock_position(cx, cy)
            else:
                self._place_dock_yaw(cx, cy)

    def _on_right_click(self, event):
        if self.mode == self.DRAWING:
            self._finish_polygon()

    def _on_motion(self, event):
        if not self.map_data:
            return
        cx = self.canvas.canvasx(event.x)
        cy = self.canvas.canvasy(event.y)
        mx, my = self._canvas_to_map(cx, cy)

        if self.mode == self.IDLE:
            self._set_status(
                f"Map: ({mx:.2f}, {my:.2f}) m   "
                f"Pixel: ({cx / self.scale:.0f}, {cy / self.scale:.0f})")
        elif self.mode == self.DRAWING:
            nv = len(self._draw_pts) // 2
            self._set_status(
                f"DRAW — {nv} vertices · "
                f"({mx:.2f}, {my:.2f}) m  ·  "
                f"Right‑click/Enter to finish")
        elif self.mode == self.SET_NAV:
            self._set_status(
                f"SET NAV POSE — click to place  ·  "
                f"({mx:.2f}, {my:.2f}) m  ·  Escape to cancel")
        elif self.mode == self.SET_DOCK:
            if self._dock_yaw_pending:
                self._set_status(
                    f"SET DOCK DIRECTION — click to set facing  ·  "
                    f"({mx:.2f}, {my:.2f}) m")
            else:
                self._set_status(
                    f"SET DOCK — click to place  ·  "
                    f"({mx:.2f}, {my:.2f}) m  ·  Escape to cancel")

    def _cancel(self, _event=None):
        if self.mode == self.DRAWING:
            for cid in self._draw_ids:
                self.canvas.delete(cid)
            self._draw_ids.clear()
            self._draw_pts.clear()
        elif self.mode == self.SET_NAV and self._pending_region:
            # Keep centroid default
            self._pending_region = None
        elif self.mode == self.SET_DOCK:
            if self._dock_yaw_pending:
                # Set yaw = 0 (facing right) as default
                cx, cy = self._dock_yaw_pending
                mx, my = self._canvas_to_map(cx, cy)
                self.region_mgr.dock_pose = [mx, my, 0.0]
                self._dock_yaw_pending = None
                self._redraw_overlay()
                self._update_dock_info()
                self._set_status("Dock set with default orientation (0°)")
                self._publish_dock_pose()
            else:
                pass  # just cancel
        self.mode = self.IDLE
        self._update_mode_indicator()
        self._set_status("Cancelled")

    # ──────────────────────────────────────────────────────────
    #  Region panel (right side nav buttons)
    # ──────────────────────────────────────────────────────────

    def _refresh_panel(self):
        for child in self._region_frame.winfo_children():
            child.destroy()

        if not self.region_mgr.regions:
            tk.Label(self._region_frame, text="No regions yet",
                     bg=PANEL_BG, fg="#585b70",
                     font=("Helvetica", 10, "italic")).pack(pady=20)
            return

        for region in self.region_mgr.regions:
            self._add_region_card(region)

    def _add_region_card(self, region):
        card = tk.Frame(self._region_frame, bg="#1e1e2e",
                        highlightbackground=region.color,
                        highlightthickness=2, padx=10, pady=8)
        card.pack(fill=tk.X, padx=6, pady=4)

        # Colour dot + name
        header = tk.Frame(card, bg="#1e1e2e")
        header.pack(fill=tk.X)
        dot = tk.Canvas(header, width=14, height=14, bg="#1e1e2e",
                        highlightthickness=0)
        dot.create_oval(2, 2, 12, 12, fill=region.color, outline="")
        dot.pack(side=tk.LEFT, padx=(0, 6))
        tk.Label(header, text=region.name, bg="#1e1e2e", fg=PANEL_FG,
                 font=("Helvetica", 11, "bold"),
                 anchor=tk.W).pack(side=tk.LEFT, fill=tk.X)

        # Coordinates
        np = region.nav_point
        yaw_deg = math.degrees(region.nav_yaw)
        info = f"  ({np[0]:.2f}, {np[1]:.2f}) m  ∠ {yaw_deg:.0f}°"
        tk.Label(card, text=info, bg="#1e1e2e", fg="#6c7086",
                 font=("Helvetica", 9), anchor=tk.W).pack(
                     fill=tk.X, pady=(2, 6))

        # Buttons
        btn_row = tk.Frame(card, bg="#1e1e2e")
        btn_row.pack(fill=tk.X)

        go_btn = tk.Button(
            btn_row, text="Go ▸", bg=ACCENT_GREEN, fg="#1e1e2e",
            activebackground=_lighten(ACCENT_GREEN, 0.3), relief=tk.FLAT,
            font=("Helvetica", 10, "bold"), padx=12, cursor="hand2",
            command=lambda n=region.name: self._on_navigate(n))
        go_btn.pack(side=tk.LEFT, padx=(0, 4))

        nav_btn = tk.Button(
            btn_row, text="Set Pose", bg=BUTTON_BG, fg=BUTTON_FG,
            relief=tk.FLAT, font=("Helvetica", 9), cursor="hand2",
            command=lambda n=region.name: self._on_set_nav_from_panel(n))
        nav_btn.pack(side=tk.LEFT, padx=(0, 4))

        del_btn = tk.Button(
            btn_row, text="✕", bg=ACCENT_RED, fg="#1e1e2e",
            activebackground=_lighten(ACCENT_RED, 0.3), relief=tk.FLAT,
            font=("Helvetica", 10, "bold"), width=3, cursor="hand2",
            command=lambda n=region.name: self._on_delete_from_panel(n))
        del_btn.pack(side=tk.RIGHT)

    # ── Panel callbacks ───────────────────────────────────────

    def _on_navigate(self, name: str):
        region = self.region_mgr.get(name)
        if not region:
            return
        x, y = region.nav_point
        yaw = region.nav_yaw
        yaw_deg = math.degrees(yaw)
        self._set_status(
            f"Navigating to '{name}' → "
            f"({x:.2f}, {y:.2f}) ∠{yaw_deg:.0f}° …")

        def _cb(success, msg):
            self.root.after(0, lambda: self._set_status(
                f"'{name}': {msg}" if success
                else f"'{name}' FAILED: {msg}"))

        self.navigator.navigate_to(x, y, yaw, callback=_cb)

    def _on_set_nav_from_panel(self, name: str):
        region = self.region_mgr.get(name)
        if not region:
            return
        self._pending_region = region
        self.mode = self.SET_NAV
        self._update_mode_indicator()
        self._set_status(
            f"Click the map to set approach point for '{name}'  "
            f"(Escape to cancel)")

    def _on_delete_from_panel(self, name: str):
        if messagebox.askyesno("Confirm", f"Delete region '{name}'?"):
            self.region_mgr.remove(name)
            self._redraw_overlay()
            self._refresh_panel()
            self._refresh_scan_panel()
            self._set_status(f"Deleted '{name}'")

    # ──────────────────────────────────────────────────────────
    #  File operations
    # ──────────────────────────────────────────────────────────

    def _save(self):
        self.region_mgr.save()
        self._set_status(
            f"Saved {len(self.region_mgr.regions)} region(s) + "
            f"dock + scan order → {self.region_mgr.filepath}")

    def _load_regions_dialog(self):
        path = filedialog.askopenfilename(
            title="Load Regions",
            filetypes=[("JSON", "*.json"), ("All", "*.*")])
        if path:
            self.region_mgr.filepath = path
            self.region_mgr.load()
            self._redraw_overlay()
            self._refresh_panel()
            self._refresh_scan_panel()
            self._set_status(
                f"Loaded {len(self.region_mgr.regions)} region(s)")

    # ──────────────────────────────────────────────────────────
    #  Shutdown
    # ──────────────────────────────────────────────────────────

    def _on_close(self):
        if self.region_mgr.regions or self.region_mgr.dock_pose:
            if messagebox.askyesno("Save?",
                                   "Save regions before exiting?"):
                self._save()
        self.navigator.shutdown()
        self.root.destroy()
