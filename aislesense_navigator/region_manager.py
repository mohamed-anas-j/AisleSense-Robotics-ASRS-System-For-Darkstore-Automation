"""
AisleSense Region Navigator — Region Manager

Stores named polygon regions in map‑frame coordinates.
Each region carries:
  • polygon   – list of [x, y] vertices in metres
  • nav_point – [x, y] approach position (metres)
  • nav_yaw   – approach orientation in radians (faces the region centre)
  • color     – hex colour for display

Also stores:
  • dock_pose   – [x, y, yaw] initial robot pose (2D Pose Estimate)
  • scan_order  – ordered list of region names for autonomous scan tour
"""
import json
import math
import os

from config import REGION_COLORS


class Region:
    """A single named region on the map."""

    def __init__(self, name: str, polygon, nav_point=None,
                 nav_yaw: float = 0.0, color: str = "#FF6B6B"):
        self.name = name
        self.polygon = polygon          # [[x,y], …]  map metres
        self.nav_point = nav_point or self.centroid()
        self.nav_yaw = nav_yaw
        self.color = color

    def centroid(self):
        """Geometric centre of the polygon."""
        if not self.polygon:
            return [0.0, 0.0]
        cx = sum(p[0] for p in self.polygon) / len(self.polygon)
        cy = sum(p[1] for p in self.polygon) / len(self.polygon)
        return [cx, cy]

    def auto_orientation_from(self, point):
        """Compute yaw from *point* facing toward the region centroid."""
        c = self.centroid()
        dx = c[0] - point[0]
        dy = c[1] - point[1]
        return math.atan2(dy, dx)

    # ── Serialisation ─────────────────────────────────────────
    def to_dict(self):
        return dict(name=self.name, polygon=self.polygon,
                    nav_point=self.nav_point, nav_yaw=self.nav_yaw,
                    color=self.color)

    @classmethod
    def from_dict(cls, d):
        return cls(name=d['name'], polygon=d['polygon'],
                   nav_point=d.get('nav_point'),
                   nav_yaw=d.get('nav_yaw', 0.0),
                   color=d.get('color', '#FF6B6B'))


class RegionManager:
    """CRUD + persistence for a collection of Regions."""

    def __init__(self, filepath: str = 'regions.json'):
        self.filepath = filepath
        self.regions: list[Region] = []
        self._color_idx = 0
        # Dock pose: [x, y, yaw] or None
        self.dock_pose: list | None = None
        # Ordered list of region names for scan tour
        self.scan_order: list[str] = []

    def _next_color(self) -> str:
        c = REGION_COLORS[self._color_idx % len(REGION_COLORS)]
        self._color_idx += 1
        return c

    def add(self, name: str, polygon, nav_point=None, nav_yaw: float = 0.0) -> Region:
        color = self._next_color()
        region = Region(name, polygon, nav_point, nav_yaw, color)
        self.regions.append(region)
        return region

    def remove(self, name: str):
        self.regions = [r for r in self.regions if r.name != name]
        # Also remove from scan order
        self.scan_order = [n for n in self.scan_order if n != name]

    def get(self, name: str):
        return next((r for r in self.regions if r.name == name), None)

    def names(self):
        return [r.name for r in self.regions]

    # ── Scan order helpers ────────────────────────────────────
    def set_scan_order(self, order: list[str]):
        """Set the scan tour order (list of region names)."""
        self.scan_order = [n for n in order if self.get(n)]

    def get_scan_waypoints(self):
        """Return [(name, x, y, yaw), …] for the current scan order."""
        waypoints = []
        for name in self.scan_order:
            r = self.get(name)
            if r:
                waypoints.append((r.name, r.nav_point[0],
                                  r.nav_point[1], r.nav_yaw))
        return waypoints

    # ── File I/O ──────────────────────────────────────────────
    def save(self):
        data = {
            'dock_pose': self.dock_pose,
            'scan_order': self.scan_order,
            'regions': [r.to_dict() for r in self.regions],
        }
        with open(self.filepath, 'w') as f:
            json.dump(data, f, indent=2)

    def load(self):
        if not os.path.exists(self.filepath):
            return
        with open(self.filepath, 'r') as f:
            data = json.load(f)
        self.regions = [Region.from_dict(r) for r in data.get('regions', [])]
        self._color_idx = len(self.regions)
        self.dock_pose = data.get('dock_pose', None)
        self.scan_order = data.get('scan_order', [])
