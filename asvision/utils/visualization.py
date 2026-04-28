"""
Visualisation Utilities
========================
Drawing helpers for annotating shelf images with bounding boxes, masks,
depth overlays, and gap highlights.

Design notes:
  • Shelf segmentation masks: translucent colour overlays + dashed bbox.
  • Product detections: labelled "Product" with rounded-corner (fillet)
    bounding boxes, colour-coded by depth.
  • Gaps: red translucent fill with rounded-corner border.
"""
from __future__ import annotations

import cv2
import numpy as np

# ── Colour Scheme (BGR) ────────────────────────────────────────────────
# Shelf mask palette — soft, distinct pastels
_SHELF_COLOURS = [
    (200, 180, 60),   # teal-blue
    (80, 200, 120),   # green
    (60, 160, 230),   # orange
    (220, 130, 80),   # steel blue
    (160, 100, 220),  # violet
    (60, 210, 210),   # gold
    (180, 120, 60),   # dark teal
    (130, 80, 200),   # magenta
]

# Product bbox colour ramp (near → far)
_PRODUCT_NEAR = np.array([80, 220, 100], dtype=np.float64)   # green  (front)
_PRODUCT_FAR  = np.array([60, 60, 230], dtype=np.float64)    # red    (back)

# Gap overlay
_GAP_FILL = (0, 0, 200)     # semi-transparent red fill
_GAP_BORDER = (0, 0, 255)   # solid red border


def _shelf_colour(idx: int) -> tuple[int, int, int]:
    return _SHELF_COLOURS[idx % len(_SHELF_COLOURS)]


# ── Rounded-Corner Rectangle ───────────────────────────────────────────

def _rounded_rect(
    img: np.ndarray,
    pt1: tuple[int, int],
    pt2: tuple[int, int],
    colour: tuple[int, int, int],
    thickness: int = 2,
    radius: int = 12,
    fill: bool = False,
) -> None:
    """Draw a rectangle with rounded corners (fillet).

    Parameters
    ----------
    img : canvas to draw on (modified in-place).
    pt1, pt2 : top-left and bottom-right corners.
    colour : BGR colour tuple.
    thickness : line thickness (-1 or ``fill=True`` for filled).
    radius : corner fillet radius in pixels.
    fill : if True, draw a filled rounded rectangle.
    """
    x1, y1 = pt1
    x2, y2 = pt2
    w, h = x2 - x1, y2 - y1
    r = min(radius, w // 2, h // 2, 30)  # clamp so fillet fits
    if r < 1:
        # fallback to plain rect
        cv2.rectangle(img, pt1, pt2, colour, thickness)
        return

    th = -1 if fill else thickness

    # Four corner circles
    cv2.ellipse(img, (x1 + r, y1 + r), (r, r), 180, 0, 90, colour, th, cv2.LINE_AA)
    cv2.ellipse(img, (x2 - r, y1 + r), (r, r), 270, 0, 90, colour, th, cv2.LINE_AA)
    cv2.ellipse(img, (x2 - r, y2 - r), (r, r), 0,   0, 90, colour, th, cv2.LINE_AA)
    cv2.ellipse(img, (x1 + r, y2 - r), (r, r), 90,  0, 90, colour, th, cv2.LINE_AA)

    if fill:
        # Fill the inner cross + corner rects
        cv2.rectangle(img, (x1 + r, y1), (x2 - r, y2), colour, -1)
        cv2.rectangle(img, (x1, y1 + r), (x1 + r, y2 - r), colour, -1)
        cv2.rectangle(img, (x2 - r, y1 + r), (x2, y2 - r), colour, -1)
    else:
        # Four edge lines connecting arcs
        cv2.line(img, (x1 + r, y1), (x2 - r, y1), colour, thickness, cv2.LINE_AA)
        cv2.line(img, (x1 + r, y2), (x2 - r, y2), colour, thickness, cv2.LINE_AA)
        cv2.line(img, (x1, y1 + r), (x1, y2 - r), colour, thickness, cv2.LINE_AA)
        cv2.line(img, (x2, y1 + r), (x2, y2 - r), colour, thickness, cv2.LINE_AA)


# ── Shelf Segmentation ─────────────────────────────────────────────────

def draw_shelf_masks(
    canvas: np.ndarray,
    shelves: list[dict],
    alpha: float = 0.30,
) -> np.ndarray:
    """Translucent shelf masks with label badges."""
    overlay = canvas.copy()
    for i, shelf in enumerate(shelves):
        colour = _shelf_colour(i)
        mask = shelf.get("mask")
        if mask is not None and mask.any():
            overlay[mask > 0] = colour

        x1, y1, x2, y2 = (int(v) for v in shelf["bbox"])

        # Dashed-style bbox (draw with thin line)
        _rounded_rect(canvas, (x1, y1), (x2, y2), colour, thickness=1, radius=8)

        # Label badge
        label = shelf["label"]
        (tw, th), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.55, 1)
        badge_x2 = x1 + tw + 12
        badge_y2 = y1 + th + 10
        _rounded_rect(canvas, (x1, y1), (badge_x2, badge_y2), colour,
                       fill=True, radius=6)
        cv2.putText(canvas, label, (x1 + 6, y1 + th + 5),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.55, (255, 255, 255), 1, cv2.LINE_AA)

    cv2.addWeighted(overlay, alpha, canvas, 1 - alpha, 0, canvas)
    return canvas


# ── Product Detections ──────────────────────────────────────────────────

def _depth_colour(depth: float | None) -> tuple[int, int, int]:
    """Interpolate green → red based on normalised depth."""
    if depth is None:
        return (80, 220, 100)  # default green
    t = min(max(depth, 0.0), 1.0)
    c = (_PRODUCT_NEAR * (1 - t) + _PRODUCT_FAR * t).astype(int)
    return (int(c[0]), int(c[1]), int(c[2]))


def draw_item_boxes(
    canvas: np.ndarray,
    items: list[dict],
    show_depth: bool = True,
) -> np.ndarray:
    """Product bounding boxes with rounded corners, depth-coloured,
    labelled as 'Product'."""
    for item in items:
        x1, y1, x2, y2 = [int(v) for v in item["bbox"]]
        depth = item.get("depth_median")
        colour = _depth_colour(depth)

        # Rounded bbox
        _rounded_rect(canvas, (x1, y1), (x2, y2), colour, thickness=2, radius=10)

        # Build label
        conf = item.get("confidence", 0)
        label = f'Product {conf:.0%}'
        if show_depth and depth is not None:
            label += f'  d={depth:.2f}'

        # Label badge (pill-shape background)
        (tw, th), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.42, 1)
        badge_pt1 = (x1, y1 - th - 10)
        badge_pt2 = (x1 + tw + 10, y1)
        # Clamp to image top
        if badge_pt1[1] < 0:
            badge_pt1 = (x1, y1)
            badge_pt2 = (x1 + tw + 10, y1 + th + 10)
            text_org = (x1 + 5, y1 + th + 5)
        else:
            text_org = (x1 + 5, y1 - 5)

        _rounded_rect(canvas, badge_pt1, badge_pt2, colour, fill=True, radius=5)
        cv2.putText(canvas, label, text_org,
                    cv2.FONT_HERSHEY_SIMPLEX, 0.42, (255, 255, 255), 1, cv2.LINE_AA)

    return canvas


# ── Depth Heat-Map ──────────────────────────────────────────────────────

def depth_heatmap(depth_map: np.ndarray) -> np.ndarray:
    """Normalised depth → INFERNO heatmap."""
    d8 = (depth_map * 255).clip(0, 255).astype(np.uint8)
    return cv2.applyColorMap(d8, cv2.COLORMAP_INFERNO)


# ── Gap Overlays ────────────────────────────────────────────────────────

def draw_gaps(canvas: np.ndarray, gaps: list[dict]) -> np.ndarray:
    """Highlight gaps with translucent red fill and rounded border."""
    for gap in gaps:
        x1, y1 = int(gap["gap_x1"]), int(gap["gap_y1"])
        x2, y2 = int(gap["gap_x2"]), int(gap["gap_y2"])

        # Translucent fill
        overlay = canvas.copy()
        _rounded_rect(overlay, (x1, y1), (x2, y2), _GAP_FILL,
                       fill=True, radius=8)
        cv2.addWeighted(overlay, 0.25, canvas, 0.75, 0, canvas)

        # Solid rounded border
        _rounded_rect(canvas, (x1, y1), (x2, y2), _GAP_BORDER,
                       thickness=2, radius=8)

        # Label
        sev = gap.get("severity", "")
        depth_val = gap.get("depth_value")
        label = f'GAP {sev}'
        if depth_val is not None:
            label += f'  d={depth_val:.2f}'
        (tw, th), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.45, 1)
        badge_pt1 = (x1, y1 - th - 8)
        badge_pt2 = (x1 + tw + 10, y1)
        if badge_pt1[1] < 0:
            badge_pt1 = (x1, y2)
            badge_pt2 = (x1 + tw + 10, y2 + th + 8)
            text_org = (x1 + 5, y2 + th + 3)
        else:
            text_org = (x1 + 5, y1 - 4)

        _rounded_rect(canvas, badge_pt1, badge_pt2, _GAP_BORDER,
                       fill=True, radius=4)
        cv2.putText(canvas, label, text_org,
                    cv2.FONT_HERSHEY_SIMPLEX, 0.45, (255, 255, 255), 1, cv2.LINE_AA)

    return canvas


# ── Full Annotation Composite ──────────────────────────────────────────

def annotate_image(
    image: np.ndarray,
    shelves: list[dict],
    items: list[dict],
    depth_map: np.ndarray | None,
    gaps: list[dict] | None = None,
) -> np.ndarray:
    """Full annotation: shelf masks → product boxes → gap overlays."""
    canvas = image.copy()
    canvas = draw_shelf_masks(canvas, shelves)
    canvas = draw_item_boxes(canvas, items, show_depth=(depth_map is not None))
    if gaps:
        canvas = draw_gaps(canvas, gaps)
    return canvas
