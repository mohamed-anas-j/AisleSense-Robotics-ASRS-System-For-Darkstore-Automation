"""
Stage 3 – Depth Estimator  (accuracy-focused rewrite)
======================================================
Uses *Depth Anything V2 Large* (ONNX) to produce a depth map.
Auto-downloads from HuggingFace if the local file is missing.

Critical accuracy fix
---------------------
Depth Anything V2 outputs **inverse / relative depth** where **larger
values = closer** to the camera.  For retail shelf analytics we need the
opposite convention (larger = farther back on the shelf).  This module
**inverts** the normalised depth so that:

    0.0  →  front edge of the shelf (closest to camera)
    1.0  →  back wall              (farthest from camera)

Per-item depth is extracted as the **median** of the inner 60 % of the
bounding-box ROI (avoids background bleed at the edges).
"""
from __future__ import annotations

import os
import cv2
import numpy as np

from config import DEPTH_MODEL_PATH, DEPTH_HF_REPO, DEPTH_HF_FILENAME, DEPTH_INPUT_SIZE
from pipeline.session_manager import create_session, destroy_session, get_model_input_size
from pipeline.preprocessor import preprocess_depth


def ensure_model() -> str:
    """Return a valid local path, downloading if necessary."""
    if os.path.isfile(DEPTH_MODEL_PATH):
        return DEPTH_MODEL_PATH

    try:
        from huggingface_hub import hf_hub_download

        downloaded = hf_hub_download(
            repo_id=DEPTH_HF_REPO,
            filename=DEPTH_HF_FILENAME,
            local_dir=os.path.dirname(DEPTH_MODEL_PATH),
        )
        if os.path.isfile(downloaded) and downloaded != DEPTH_MODEL_PATH:
            os.makedirs(os.path.dirname(DEPTH_MODEL_PATH), exist_ok=True)
            if not os.path.isfile(DEPTH_MODEL_PATH):
                os.symlink(os.path.abspath(downloaded), DEPTH_MODEL_PATH)
        return DEPTH_MODEL_PATH if os.path.isfile(DEPTH_MODEL_PATH) else downloaded
    except Exception as exc:
        raise FileNotFoundError(
            f"Depth model not found at {DEPTH_MODEL_PATH} and HuggingFace "
            f"download failed: {exc}"
        ) from exc


def _inner_roi(
    depth_map: np.ndarray,
    bbox: list[float],
    shrink: float = 0.2,
) -> np.ndarray:
    """Extract the inner portion of a bbox ROI (shrink edges by *shrink*
    fraction on each side) to avoid background-pixel contamination.

    Falls back to the full ROI if the inner crop is too small.
    """
    h, w = depth_map.shape[:2]
    x1, y1, x2, y2 = int(bbox[0]), int(bbox[1]), int(bbox[2]), int(bbox[3])
    bw, bh = x2 - x1, y2 - y1
    margin_x = int(bw * shrink)
    margin_y = int(bh * shrink)
    ix1 = max(x1 + margin_x, 0)
    iy1 = max(y1 + margin_y, 0)
    ix2 = min(x2 - margin_x, w)
    iy2 = min(y2 - margin_y, h)

    if ix2 > ix1 and iy2 > iy1:
        return depth_map[iy1:iy2, ix1:ix2]

    # Fallback: full bbox
    x1c, y1c = max(x1, 0), max(y1, 0)
    x2c, y2c = min(x2, w), min(y2, h)
    return depth_map[y1c:y2c, x1c:x2c]


def run(
    image: np.ndarray,
    provider: str,
    items: list[dict],
) -> tuple[np.ndarray, list[dict]]:
    """Generate a depth map and annotate each item with median depth.

    Returns
    -------
    depth_map : ndarray [H, W] float32, 0 = front, 1 = back (inverted)
    items     : same list with ``depth_median`` filled in
    """
    orig_h, orig_w = image.shape[:2]
    model_path = ensure_model()

    # ── Session lifecycle ───────────────────────────────────────────────
    session = create_session(model_path, provider)
    try:
        input_size = get_model_input_size(session, DEPTH_INPUT_SIZE)
        blob = preprocess_depth(image, input_size)

        input_name = session.get_inputs()[0].name
        outputs = session.run(None, {input_name: blob})
    finally:
        destroy_session(session)
        session = None  # type: ignore[assignment]

    # ── Parse depth map ─────────────────────────────────────────────────
    depth_raw = outputs[0]
    while depth_raw.ndim > 2:
        depth_raw = depth_raw[0]

    # Resize to original image
    interp = cv2.INTER_AREA if depth_raw.shape[0] > orig_h else cv2.INTER_LINEAR
    depth_map = cv2.resize(depth_raw.astype(np.float32), (orig_w, orig_h),
                           interpolation=interp)

    # Normalise to [0, 1]
    d_min, d_max = float(depth_map.min()), float(depth_map.max())
    if d_max - d_min > 1e-6:
        depth_map = (depth_map - d_min) / (d_max - d_min)
    else:
        depth_map = np.zeros_like(depth_map)

    # *** INVERT ***  Depth Anything: high = close → we need high = far
    depth_map = 1.0 - depth_map

    # ── Per-item depth (inner-ROI median) ───────────────────────────────
    for item in items:
        roi = _inner_roi(depth_map, item["bbox"])
        item["depth_median"] = float(np.median(roi)) if roi.size > 0 else 0.0

    return depth_map, items
