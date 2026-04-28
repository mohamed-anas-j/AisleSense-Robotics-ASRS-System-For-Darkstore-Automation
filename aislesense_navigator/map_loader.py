"""
AisleSense Region Navigator — Map Loader

Loads a ROS2 navigation map (PGM image + YAML metadata) and provides
coordinate transforms between pixel space and map‑frame meters.
"""
import os
import yaml
from PIL import Image


class MapData:
    """Holds a loaded navigation map and its coordinate metadata."""

    def __init__(self, yaml_path: str):
        self.yaml_path = os.path.abspath(yaml_path)
        self.yaml_dir = os.path.dirname(self.yaml_path)

        with open(self.yaml_path, 'r') as f:
            meta = yaml.safe_load(f)

        # Resolve PGM path relative to the YAML file
        self.image_file = os.path.join(self.yaml_dir, meta['image'])
        self.resolution = float(meta['resolution'])        # m / pixel
        self.origin = [float(v) for v in meta['origin']]   # [x, y, θ]
        self.negate = int(meta.get('negate', 0))
        self.occupied_thresh = float(meta.get('occupied_thresh', 0.65))
        self.free_thresh = float(meta.get('free_thresh', 0.25))

        # Load PGM
        self.image = Image.open(self.image_file)
        self.width, self.height = self.image.size

    # ── Coordinate transforms ─────────────────────────────────
    def pixel_to_map(self, px: float, py: float):
        """Pixel (col, row with 0,0 top‑left) → map‑frame metres."""
        mx = px * self.resolution + self.origin[0]
        my = (self.height - 1 - py) * self.resolution + self.origin[1]
        return (mx, my)

    def map_to_pixel(self, mx: float, my: float):
        """Map‑frame metres → pixel (col, row)."""
        px = (mx - self.origin[0]) / self.resolution
        py = self.height - 1 - (my - self.origin[1]) / self.resolution
        return (px, py)

    def get_display_image(self) -> Image.Image:
        """Return an RGB PIL Image ready for display."""
        return self.image.convert('RGB')
