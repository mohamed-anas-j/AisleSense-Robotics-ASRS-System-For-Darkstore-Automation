"""
AisleSense Region Navigator — Configuration
===========================================
GUI theme constants, filesystem paths, and navigation defaults.
Colour palette inspired by the Catppuccin Mocha theme.
"""
import os

# ── Paths ──────────────────────────────────────────────────────
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
AISLESENSE_DIR = os.path.join(BASE_DIR, '..', 'aislesense')
DEFAULT_MAP_YAML = os.path.join(AISLESENSE_DIR, 'my_room_map.yaml')
DEFAULT_REGIONS_FILE = os.path.join(BASE_DIR, 'regions.json')

# ── GUI ────────────────────────────────────────────────────────
WINDOW_TITLE = "AisleSense Region Navigator"
WINDOW_SIZE = "1450x900"
CANVAS_BG = "#1e1e2e"
PANEL_BG = "#181825"
PANEL_FG = "#cdd6f4"
BUTTON_BG = "#313244"
BUTTON_FG = "#cdd6f4"
STATUS_BG = "#11111b"
STATUS_FG = "#a6adc8"

# Accent colours (Catppuccin Mocha inspired)
ACCENT_GREEN = "#a6e3a1"
ACCENT_RED = "#f38ba8"
ACCENT_BLUE = "#89b4fa"
ACCENT_YELLOW = "#f9e2af"
ACCENT_PEACH = "#fab387"
ACCENT_TEAL = "#94e2d5"
ACCENT_MAUVE = "#cba6f7"

# ── Region Colors (cycled automatically) ───────────────────────
REGION_COLORS = [
    "#f38ba8", "#94e2d5", "#89b4fa", "#a6e3a1",
    "#f9e2af", "#cba6f7", "#89dceb", "#f5c2e7",
    "#fab387", "#74c7ec", "#eba0ac", "#a6e3a1",
]

# ── Dock ───────────────────────────────────────────────────────
DOCK_COLOR = "#f9e2af"        # yellow marker on map
DOCK_MARKER_RADIUS = 10       # pixels

# ── Navigation ─────────────────────────────────────────────────
ROS_DOMAIN_ID = 42
NAV_ARROW_LEN = 20          # pixels — approach direction arrow on canvas
NAV_MARKER_RADIUS = 6       # pixels — approach point dot on canvas
SCAN_WAIT_SECONDS = 2       # seconds to dwell at each region during scan
