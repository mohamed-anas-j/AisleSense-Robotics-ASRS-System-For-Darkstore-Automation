"""
Stage 2 – Item (Product) Detector  (accuracy-focused rewrite)
=============================================================
Loads ``prod_detect.onnx`` (YOLO11x), detects individual product bounding
boxes, and assigns each to a shelf.

Improvements over v1:
  • Reads model input size at runtime (no hard-coded 640).
  • Shelf assignment uses **IoU overlap** between item bbox and shelf mask,
    falling back to centre-point containment, then nearest-centroid.
"""
from __future__ import annotations

import numpy as np

from config import PROD_DETECT_MODEL, YOLO_INPUT_SIZE, SHELF_OVERLAP_MIN
from pipeline.session_manager import create_session, destroy_session, get_model_input_size
from pipeline.preprocessor import preprocess_yolo
from pipeline.postprocessor import parse_yolo_outputs


# ── Shelf assignment helpers ────────────────────────────────────────────

def _bbox_mask_overlap(bbox: list[float], mask: np.ndarray) -> float:
    """Fraction of *bbox* area that overlaps *mask* (binary, uint8)."""
    h, w = mask.shape[:2]
    x1, y1, x2, y2 = int(bbox[0]), int(bbox[1]), int(bbox[2]), int(bbox[3])
    x1, y1 = max(x1, 0), max(y1, 0)
    x2, y2 = min(x2, w), min(y2, h)
    if x2 <= x1 or y2 <= y1:
        return 0.0
    roi = mask[y1:y2, x1:x2]
    bbox_area = (x2 - x1) * (y2 - y1)
    if bbox_area == 0:
        return 0.0
    return float(roi.sum()) / bbox_area


def _assign_shelf(bbox: list[float], shelves: list[dict]) -> str | None:
    """Assign an item to the best-matching shelf.

    Priority:
      1. Highest bbox-mask overlap (if ≥ SHELF_OVERLAP_MIN).
      2. Centre-point inside mask.
      3. Nearest shelf centroid (vertical distance).
    """
    if not shelves:
        return None

    # 1 — overlap-based
    best_overlap = 0.0
    best_label: str | None = None
    for shelf in shelves:
        ov = _bbox_mask_overlap(bbox, shelf["mask"])
        if ov > best_overlap:
            best_overlap = ov
            best_label = shelf["label"]
    if best_overlap >= SHELF_OVERLAP_MIN:
        return best_label

    # 2 — centre-point containment
    cx = (bbox[0] + bbox[2]) / 2
    cy = (bbox[1] + bbox[3]) / 2
    for shelf in shelves:
        mask = shelf["mask"]
        ix, iy = int(round(cx)), int(round(cy))
        if 0 <= ix < mask.shape[1] and 0 <= iy < mask.shape[0] and mask[iy, ix] > 0:
            return shelf["label"]

    # 3 — nearest centroid
    best_dist = float("inf")
    for shelf in shelves:
        sy = (shelf["bbox"][1] + shelf["bbox"][3]) / 2
        d = abs(cy - sy)
        if d < best_dist:
            best_dist = d
            best_label = shelf["label"]
    return best_label


# ── Public API ──────────────────────────────────────────────────────────

def run(
    image: np.ndarray,
    provider: str,
    conf_threshold: float,
    iou_threshold: float,
    shelves: list[dict],
) -> list[dict]:
    """Detect products and return a list of item dicts.

    Each dict:
        id, bbox, confidence, class_id, shelf_label, depth_median (None)
    """
    orig_h, orig_w = image.shape[:2]

    # ── Session lifecycle ───────────────────────────────────────────────
    session = create_session(PROD_DETECT_MODEL, provider)
    try:
        input_size = get_model_input_size(session, YOLO_INPUT_SIZE)
        blob, scale, pad_x, pad_y = preprocess_yolo(image, input_size)

        input_name = session.get_inputs()[0].name
        outputs = session.run(None, {input_name: blob})
    finally:
        destroy_session(session)
        session = None  # type: ignore[assignment]

    # ── Parse ───────────────────────────────────────────────────────────
    result = parse_yolo_outputs(
        outputs,
        conf_threshold=conf_threshold,
        iou_threshold=iou_threshold,
        is_seg=False,
        input_size=input_size,
        orig_h=orig_h,
        orig_w=orig_w,
        scale=scale,
        pad_x=pad_x,
        pad_y=pad_y,
    )
    boxes, scores, class_ids = result

    # ── Build item list ─────────────────────────────────────────────────
    items: list[dict] = []
    for i in range(len(scores)):
        bbox = boxes[i].tolist()
        items.append({
            "id": i,
            "bbox": bbox,
            "confidence": float(scores[i]),
            "class_id": int(class_ids[i]),
            "label": "Product",
            "shelf_label": _assign_shelf(bbox, shelves),
            "depth_median": None,
        })

    return items
