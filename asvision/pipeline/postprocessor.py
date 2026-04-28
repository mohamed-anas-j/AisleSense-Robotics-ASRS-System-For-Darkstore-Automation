"""
YOLO Post-processing  (Accuracy-focused rewrite)
=================================================
Handles both raw (``model.export(format='onnx')``) and end-to-end
(``nms=True``) ONNX exports for YOLO detection and YOLO-seg.

Format detection heuristic
--------------------------
* **Raw**: ``output0`` has shape ``[1, K, N]`` where K < N
  (channels < prediction count).
* **End-to-end** (e2e): ``output0`` has shape ``[1, N, K]``
  where K < N (each row is one detection).

Key accuracy improvements over the original:
  1.  Proper e2e segmentation parser for ``(1, 300, 38)`` + protos.
  2.  Morphological cleanup on final instance masks.
  3.  Better NMS — per-class with validated IoU.
  4.  Accurate box-crop of upsampled masks before un-letterboxing.
"""
from __future__ import annotations

import cv2
import numpy as np

from config import NUM_MASK_COEFFS


# ═══════════════════════════════ HELPERS ═════════════════════════════════

def _sigmoid(x: np.ndarray) -> np.ndarray:
    return 1.0 / (1.0 + np.exp(-np.clip(x, -88, 88)))


def _xywh_to_xyxy(boxes: np.ndarray) -> np.ndarray:
    """[cx,cy,w,h] → [x1,y1,x2,y2]"""
    out = np.empty_like(boxes)
    half_w = boxes[:, 2] / 2
    half_h = boxes[:, 3] / 2
    out[:, 0] = boxes[:, 0] - half_w
    out[:, 1] = boxes[:, 1] - half_h
    out[:, 2] = boxes[:, 0] + half_w
    out[:, 3] = boxes[:, 1] + half_h
    return out


# ═══════════════════════════════ NMS ════════════════════════════════════

def nms(
    boxes: np.ndarray,
    scores: np.ndarray,
    iou_threshold: float,
) -> np.ndarray:
    """Greedy NMS.  Returns *indices* of kept detections."""
    if len(boxes) == 0:
        return np.array([], dtype=int)

    x1, y1, x2, y2 = boxes.T
    areas = (x2 - x1) * (y2 - y1)
    order = scores.argsort()[::-1]
    keep: list[int] = []

    while order.size > 0:
        i = order[0]
        keep.append(int(i))
        if order.size == 1:
            break
        rest = order[1:]
        xx1 = np.maximum(x1[i], x1[rest])
        yy1 = np.maximum(y1[i], y1[rest])
        xx2 = np.minimum(x2[i], x2[rest])
        yy2 = np.minimum(y2[i], y2[rest])
        inter = np.maximum(0.0, xx2 - xx1) * np.maximum(0.0, yy2 - yy1)
        iou = inter / (areas[i] + areas[rest] - inter + 1e-6)
        order = rest[iou <= iou_threshold]

    return np.array(keep, dtype=int)


def _multiclass_nms(
    boxes: np.ndarray,
    class_scores: np.ndarray,
    iou_threshold: float,
) -> np.ndarray:
    """Per-class NMS.  *class_scores* shape ``[M, nc]``."""
    nc = class_scores.shape[1]
    keep_set: set[int] = set()
    for c in range(nc):
        sc = class_scores[:, c]
        mask = sc > 0
        if not mask.any():
            continue
        idxs = np.where(mask)[0]
        k = nms(boxes[idxs], sc[idxs], iou_threshold)
        keep_set.update(idxs[k].tolist())
    return np.array(sorted(keep_set), dtype=int) if keep_set else np.array([], dtype=int)


# ═══════════════════════════ BOX RESCALE ════════════════════════════════

def rescale_boxes(
    boxes: np.ndarray,
    scale: float,
    pad_x: int,
    pad_y: int,
    orig_w: int,
    orig_h: int,
) -> np.ndarray:
    """Map boxes from letterboxed input space → original image coords."""
    if len(boxes) == 0:
        return boxes.copy()
    out = boxes.astype(np.float64).copy()
    out[:, [0, 2]] = (out[:, [0, 2]] - pad_x) / scale
    out[:, [1, 3]] = (out[:, [1, 3]] - pad_y) / scale
    out[:, [0, 2]] = np.clip(out[:, [0, 2]], 0, orig_w)
    out[:, [1, 3]] = np.clip(out[:, [1, 3]], 0, orig_h)
    return out.astype(np.float32)


# ═══════════════════════ RAW-FORMAT PARSERS ═════════════════════════════

def parse_detection_raw(
    output: np.ndarray,
    conf_threshold: float,
    iou_threshold: float,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Parse raw detection ``output0  [1, 4+nc, N]``.

    Returns (boxes [M,4] in input coords, scores [M], class_ids [M]).
    """
    pred = output[0].T                          # [N, 4+nc]
    nc = pred.shape[1] - 4
    if nc <= 0:
        return np.empty((0, 4), np.float32), np.empty(0, np.float32), np.empty(0, int)

    boxes_xywh   = pred[:, :4]
    class_scores = pred[:, 4:]

    max_scores = class_scores.max(axis=1)
    mask = max_scores >= conf_threshold
    if not mask.any():
        return np.empty((0, 4), np.float32), np.empty(0, np.float32), np.empty(0, int)

    boxes_xywh   = boxes_xywh[mask]
    class_scores = class_scores[mask]
    max_scores   = max_scores[mask]
    class_ids    = class_scores.argmax(axis=1)
    boxes        = _xywh_to_xyxy(boxes_xywh)

    keep = _multiclass_nms(boxes, class_scores, iou_threshold)
    return boxes[keep], max_scores[keep], class_ids[keep]


def parse_segmentation_raw(
    output0: np.ndarray,
    output1: np.ndarray,
    conf_threshold: float,
    iou_threshold: float,
    mask_coeffs_count: int = NUM_MASK_COEFFS,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Parse raw seg ``output0 [1, 4+nc+32, N]``.

    Returns (boxes, scores, class_ids, mask_coeffs).
    """
    pred = output0[0].T                     # [N, 4+nc+32]
    nc = pred.shape[1] - 4 - mask_coeffs_count
    if nc <= 0:
        nc = max(1, pred.shape[1] - 4)
        mask_coeffs_count = 0

    boxes_xywh   = pred[:, :4]
    class_scores = pred[:, 4 : 4 + nc]
    mask_c       = pred[:, 4 + nc : 4 + nc + mask_coeffs_count] if mask_coeffs_count else None

    max_scores = class_scores.max(axis=1)
    mask = max_scores >= conf_threshold
    if not mask.any():
        z = np.empty((0, 4), np.float32)
        return z, np.empty(0), np.empty(0, int), np.empty((0, mask_coeffs_count))

    boxes_xywh   = boxes_xywh[mask]
    class_scores = class_scores[mask]
    max_scores   = max_scores[mask]
    class_ids    = class_scores.argmax(axis=1)
    if mask_c is not None:
        mask_c = mask_c[mask]

    boxes = _xywh_to_xyxy(boxes_xywh)
    keep  = _multiclass_nms(boxes, class_scores, iou_threshold)

    mc = mask_c[keep] if mask_c is not None else np.empty((len(keep), 0))
    return boxes[keep], max_scores[keep], class_ids[keep], mc


# ═════════════════════ END-TO-END PARSERS ═══════════════════════════════

def _parse_e2e_matrix(
    out: np.ndarray,
    conf_threshold: float,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray | None]:
    """Parse ``[N, K]`` where each row is ``[x1,y1,x2,y2, score, cls, …mc]``.

    Filters out padding rows (score ≤ threshold).
    """
    if out.ndim == 3 and out.shape[0] == 1:
        out = out[0]

    valid = out[:, 4] > conf_threshold
    out = out[valid]
    if len(out) == 0:
        return (np.empty((0, 4), np.float32), np.empty(0, np.float32),
                np.empty(0, int), None)

    boxes     = out[:, :4].astype(np.float32)
    scores    = out[:, 4].astype(np.float32)
    class_ids = out[:, 5].astype(int)
    mc        = out[:, 6:].astype(np.float32) if out.shape[1] > 6 else None
    return boxes, scores, class_ids, mc


def parse_e2e_detection(
    outputs: list[np.ndarray],
    conf_threshold: float = 0.0,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Parse e2e detection outputs (various layouts)."""

    # Single matrix [1, N, K] or [N, K]
    if len(outputs) >= 1:
        o = outputs[0]
        if o.ndim == 3 and o.shape[0] == 1:
            o = o[0]
        if o.ndim == 2 and o.shape[1] >= 6:
            boxes, scores, cids, _ = _parse_e2e_matrix(o, conf_threshold)
            return boxes, scores, cids

    # Multi-tensor: (num, boxes, scores, classes)
    if len(outputs) >= 4:
        n = int(outputs[0].flatten()[0])
        return (outputs[1][0, :n].astype(np.float32),
                outputs[2][0, :n].astype(np.float32),
                outputs[3][0, :n].astype(int))

    raise ValueError(f"Unrecognised e2e detection layout: {[o.shape for o in outputs]}")


def parse_e2e_segmentation(
    outputs: list[np.ndarray],
    conf_threshold: float = 0.0,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray | None]:
    """Parse e2e segmentation.

    Expected:
        output0  ``[1, N, 6+32]`` — detections + mask coeffs
        output1  ``[1, 32, mh, mw]`` — mask prototypes

    Returns ``(boxes, scores, class_ids, mask_coeffs, protos)``.
    """
    boxes, scores, cids, mc = _parse_e2e_matrix(outputs[0], conf_threshold)

    protos = None
    if len(outputs) >= 2:
        protos = outputs[1]
        if protos.ndim == 4 and protos.shape[0] == 1:
            protos = protos[0]          # → [32, mh, mw]

    if mc is None or (mc.ndim == 2 and mc.shape[1] == 0):
        mc = np.empty((len(scores), 0), np.float32)

    return boxes, scores, cids, mc, protos


# ═══════════════════ MASK PROTOTYPE PROCESSING ══════════════════════════

def process_mask_protos(
    protos: np.ndarray,
    mask_coeffs: np.ndarray,
    boxes_input: np.ndarray,
    input_size: int,
    orig_h: int,
    orig_w: int,
    scale: float,
    pad_x: int,
    pad_y: int,
) -> list[np.ndarray]:
    """Combine mask coefficients with prototypes to produce per-instance
    binary masks at original image resolution.

    Parameters
    ----------
    protos       : ``[C, mh, mw]``
    mask_coeffs  : ``[M, C]``
    boxes_input  : ``[M, 4]`` x1y1x2y2 in *letterboxed* input coords
    """
    if mask_coeffs.size == 0 or protos.size == 0:
        return []

    c, mh, mw = protos.shape

    # Prototype-to-mask linear combination + sigmoid
    raw = _sigmoid(mask_coeffs @ protos.reshape(c, -1))   # [M, mh*mw]
    raw = raw.reshape(-1, mh, mw)                          # [M, mh, mw]

    valid_h = int(round(orig_h * scale))
    valid_w = int(round(orig_w * scale))

    masks_out: list[np.ndarray] = []
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))

    for i in range(raw.shape[0]):
        # Up-sample proto → input resolution
        mask_full = cv2.resize(raw[i], (input_size, input_size),
                               interpolation=cv2.INTER_LINEAR)

        # Crop to bbox (in input coords) to suppress out-of-box noise
        bx1, by1 = max(int(boxes_input[i, 0]), 0), max(int(boxes_input[i, 1]), 0)
        bx2, by2 = min(int(boxes_input[i, 2]), input_size), min(int(boxes_input[i, 3]), input_size)

        cropped = np.zeros_like(mask_full)
        cropped[by1:by2, bx1:bx2] = mask_full[by1:by2, bx1:bx2]

        # Remove letterbox padding
        unpadded = cropped[pad_y : pad_y + valid_h, pad_x : pad_x + valid_w]
        if unpadded.size == 0:
            masks_out.append(np.zeros((orig_h, orig_w), dtype=np.uint8))
            continue

        # Resize to original image resolution
        final = cv2.resize(unpadded, (orig_w, orig_h),
                           interpolation=cv2.INTER_LINEAR)

        # Threshold + morphological cleanup for smooth edges
        binary = (final > 0.5).astype(np.uint8)
        binary = cv2.morphologyEx(binary, cv2.MORPH_CLOSE, kernel)
        binary = cv2.morphologyEx(binary, cv2.MORPH_OPEN, kernel)

        masks_out.append(binary)

    return masks_out


# ═════════════════════ UNIFIED DISPATCHER ═══════════════════════════════

def parse_yolo_outputs(
    outputs: list[np.ndarray],
    conf_threshold: float,
    iou_threshold: float,
    is_seg: bool = False,
    input_size: int = 640,
    orig_h: int = 0,
    orig_w: int = 0,
    scale: float = 1.0,
    pad_x: int = 0,
    pad_y: int = 0,
):
    """Auto-detect output format and return parsed results.

    Detection → ``(boxes_orig, scores, class_ids)``
    Segmentation → ``(boxes_orig, scores, class_ids, masks)``
    """
    out0 = outputs[0]

    # ── Format detection ────────────────────────────────────────────────
    # Raw:  [1, channels, predictions]  where channels < predictions
    # E2E:  [1, detections, cols]       where cols < detections
    is_raw = (out0.ndim == 3 and out0.shape[0] == 1 and out0.shape[1] < out0.shape[2])

    if is_raw:
        # ── RAW ─────────────────────────────────────────────────────────
        if is_seg and len(outputs) >= 2:
            protos = outputs[1][0]
            boxes, scores, cids, mc = parse_segmentation_raw(
                out0, outputs[1], conf_threshold, iou_threshold,
            )
            masks = process_mask_protos(
                protos, mc, boxes, input_size,
                orig_h, orig_w, scale, pad_x, pad_y,
            )
            boxes = rescale_boxes(boxes, scale, pad_x, pad_y, orig_w, orig_h)
            return boxes, scores, cids, masks

        boxes, scores, cids = parse_detection_raw(out0, conf_threshold, iou_threshold)
        boxes = rescale_boxes(boxes, scale, pad_x, pad_y, orig_w, orig_h)
        return (boxes, scores, cids, []) if is_seg else (boxes, scores, cids)

    # ── END-TO-END ──────────────────────────────────────────────────────
    if is_seg:
        boxes, scores, cids, mc, protos = parse_e2e_segmentation(
            outputs, conf_threshold,
        )
        if protos is not None and mc.shape[1] > 0:
            masks = process_mask_protos(
                protos, mc, boxes, input_size,
                orig_h, orig_w, scale, pad_x, pad_y,
            )
        else:
            masks = []
        boxes = rescale_boxes(boxes, scale, pad_x, pad_y, orig_w, orig_h)
        return boxes, scores, cids, masks

    boxes, scores, cids = parse_e2e_detection(outputs, conf_threshold)
    boxes = rescale_boxes(boxes, scale, pad_x, pad_y, orig_w, orig_h)
    return boxes, scores, cids
