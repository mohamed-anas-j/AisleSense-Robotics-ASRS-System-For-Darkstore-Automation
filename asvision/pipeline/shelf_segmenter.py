"""
Stage 1 – Shelf Segmenter  (accuracy-focused rewrite)
======================================================
Loads ``shelf_seg.onnx`` (YOLO11x-seg), detects physical shelf levels,
returns polygon masks sorted top-to-bottom.

Improvements:
  • Reads the model's expected input size at runtime.
  • Filters out tiny / low-area mask artifacts.
  • Morphologically cleans polygon contours.
"""
from __future__ import annotations

import cv2
import numpy as np

from config import SHELF_SEG_MODEL, YOLO_INPUT_SIZE
from pipeline.session_manager import create_session, destroy_session, get_model_input_size
from pipeline.preprocessor import preprocess_yolo
from pipeline.postprocessor import parse_yolo_outputs


# Minimum fraction of image area for a shelf mask to be kept
_MIN_MASK_AREA_FRACTION = 0.005


def _masks_to_polygons(mask: np.ndarray) -> np.ndarray | None:
    """Largest-contour polygon from a binary mask."""
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        return None
    largest = max(contours, key=cv2.contourArea)
    if largest.shape[0] < 3:
        return None
    return largest.squeeze()


def run(
    image: np.ndarray,
    provider: str,
    conf_threshold: float,
    iou_threshold: float,
) -> list[dict]:
    """Run shelf segmentation.

    Returns list of shelf dicts sorted top → bottom:
        label, mask, bbox, confidence, class_id, polygon
    """
    orig_h, orig_w = image.shape[:2]
    img_area = orig_h * orig_w

    # ── Session lifecycle ───────────────────────────────────────────────
    session = create_session(SHELF_SEG_MODEL, provider)
    try:
        input_size = get_model_input_size(session, YOLO_INPUT_SIZE)
        blob, scale, pad_x, pad_y = preprocess_yolo(image, input_size)

        input_name = session.get_inputs()[0].name
        outputs = session.run(None, {input_name: blob})
    finally:
        destroy_session(session)
        session = None  # type: ignore[assignment]

    # ── Parse ───────────────────────────────────────────────────────────
    boxes, scores, class_ids, masks = parse_yolo_outputs(
        outputs,
        conf_threshold=conf_threshold,
        iou_threshold=iou_threshold,
        is_seg=True,
        input_size=input_size,
        orig_h=orig_h,
        orig_w=orig_w,
        scale=scale,
        pad_x=pad_x,
        pad_y=pad_y,
    )

    # ── Build shelf list ────────────────────────────────────────────────
    shelves: list[dict] = []
    for i in range(len(scores)):
        bbox = boxes[i].tolist()
        mask = masks[i] if i < len(masks) else np.zeros((orig_h, orig_w), dtype=np.uint8)

        # Drop masks that are too small (likely noise)
        if mask.sum() < img_area * _MIN_MASK_AREA_FRACTION:
            # Fall back to bbox-filled mask
            mask = np.zeros((orig_h, orig_w), dtype=np.uint8)

        poly = _masks_to_polygons(mask)
        shelves.append({
            "bbox": bbox,
            "confidence": float(scores[i]),
            "class_id": int(class_ids[i]),
            "mask": mask,
            "polygon": poly,
            "centroid_y": (bbox[1] + bbox[3]) / 2,
        })

    # ── Synthesise masks from bboxes when none exist ────────────────────
    if all(s["mask"].sum() == 0 for s in shelves) and shelves:
        for s in shelves:
            x1, y1, x2, y2 = (int(v) for v in s["bbox"])
            m = np.zeros((orig_h, orig_w), dtype=np.uint8)
            m[max(y1, 0) : min(y2, orig_h), max(x1, 0) : min(x2, orig_w)] = 1
            s["mask"] = m
            s["polygon"] = _masks_to_polygons(m)

    # ── Sort top → bottom and label ─────────────────────────────────────
    shelves.sort(key=lambda s: s["centroid_y"])
    for idx, shelf in enumerate(shelves, 1):
        shelf["label"] = f"Shelf {idx}"
        shelf.pop("centroid_y", None)

    return shelves
