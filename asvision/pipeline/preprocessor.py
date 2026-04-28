"""
Image Pre-processing Utilities
===============================
Letterbox resize for YOLO and ImageNet normalisation for Depth Anything.

Key accuracy detail:
  • Uses INTER_AREA when shrinking (anti-aliased down-sample) and
    INTER_LINEAR when enlarging.  This matches Ultralytics's own
    high-quality path and avoids aliasing artefacts on dense shelves.
"""
import cv2
import numpy as np

from config import DEPTH_INPUT_SIZE, IMAGENET_MEAN, IMAGENET_STD


# ── YOLO letterbox ──────────────────────────────────────────────────────

def letterbox(
    image: np.ndarray,
    target_size: int = 640,
    colour: tuple[int, int, int] = (114, 114, 114),
) -> tuple[np.ndarray, float, int, int]:
    """Aspect-preserving resize + centre-padding.

    Returns (canvas, scale, pad_x, pad_y).
    """
    h, w = image.shape[:2]
    scale = min(target_size / h, target_size / w)
    new_w, new_h = int(round(w * scale)), int(round(h * scale))

    # Quality interpolation: AREA for shrink, LINEAR for enlarge
    interp = cv2.INTER_AREA if scale < 1.0 else cv2.INTER_LINEAR
    resized = cv2.resize(image, (new_w, new_h), interpolation=interp)

    canvas = np.full((target_size, target_size, 3), colour, dtype=np.uint8)
    pad_y = (target_size - new_h) // 2
    pad_x = (target_size - new_w) // 2
    canvas[pad_y : pad_y + new_h, pad_x : pad_x + new_w] = resized

    return canvas, scale, pad_x, pad_y


def preprocess_yolo(
    image: np.ndarray,
    input_size: int = 640,
) -> tuple[np.ndarray, float, int, int]:
    """Return ``(blob [1,3,H,W] float32, scale, pad_x, pad_y)``."""
    canvas, scale, pad_x, pad_y = letterbox(image, input_size)

    # BGR → RGB, [0-255] → [0-1], HWC → CHW
    blob = canvas[:, :, ::-1].astype(np.float32) / 255.0
    blob = np.ascontiguousarray(blob.transpose(2, 0, 1)[np.newaxis])
    return blob, scale, pad_x, pad_y


# ── Depth model (ImageNet normalisation) ────────────────────────────────

def preprocess_depth(
    image: np.ndarray,
    input_size: int = DEPTH_INPUT_SIZE,
) -> np.ndarray:
    """Return ``blob [1, 3, H, W]`` normalised with ImageNet statistics."""
    interp = cv2.INTER_AREA if max(image.shape[:2]) > input_size else cv2.INTER_CUBIC
    resized = cv2.resize(image, (input_size, input_size), interpolation=interp)

    rgb = resized[:, :, ::-1].astype(np.float32) / 255.0

    mean = np.array(IMAGENET_MEAN, dtype=np.float32).reshape(1, 1, 3)
    std  = np.array(IMAGENET_STD,  dtype=np.float32).reshape(1, 1, 3)
    normalised = (rgb - mean) / std

    blob = np.ascontiguousarray(normalised.transpose(2, 0, 1)[np.newaxis])
    return blob
