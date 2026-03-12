"""
AisleSense Vision — Configuration
=================================
Model paths, preprocessing constants, detection thresholds, and
reference data for the retail shelf auditing pipeline.
"""
import os

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
MODELS_DIR = os.path.join(BASE_DIR, "models")

SHELF_SEG_MODEL = os.path.join(MODELS_DIR, "shelf_seg.onnx")
PROD_DETECT_MODEL = os.path.join(MODELS_DIR, "prod_detect.onnx")
DEPTH_MODEL_PATH = os.path.join(MODELS_DIR, "depth_anything_v2_large.onnx")

# HuggingFace depth model download config
DEPTH_HF_REPO = "onnx-community/depth-anything-v2-large"
DEPTH_HF_FILENAME = "onnx/model.onnx"

# ---------------------------------------------------------------------------
# YOLO preprocessing  (fallback values; overridden at runtime from model)
# ---------------------------------------------------------------------------
YOLO_INPUT_SIZE = 640
NUM_MASK_COEFFS = 32

# ---------------------------------------------------------------------------
# Depth model preprocessing (ImageNet normalisation)
# ---------------------------------------------------------------------------
DEPTH_INPUT_SIZE = 518
IMAGENET_MEAN = [0.485, 0.456, 0.406]
IMAGENET_STD = [0.229, 0.224, 0.225]

# ---------------------------------------------------------------------------
# Default detection thresholds (tuned for YOLO11x / YOLO11x-seg)
#
# High-capacity "x" models produce confident, clean predictions.
# A 0.35 confidence floor filters low-quality false positives without
# discarding genuine detections.  IoU 0.50 prevents adjacent products
# from being suppressed in dense shelf scenes while merging true
# duplicates.  Depth gap cutoff 0.65 is a reasonable starting point
# for most standard gondola shelving.
# ---------------------------------------------------------------------------
DEFAULT_CONF_THRESHOLD = 0.35
DEFAULT_IOU_THRESHOLD = 0.50
DEFAULT_DEPTH_GAP_CUTOFF = 0.65

# ---------------------------------------------------------------------------
# Shelf-to-item assignment
# ---------------------------------------------------------------------------
SHELF_OVERLAP_MIN = 0.20  # Minimum bbox-mask IoU to assign an item to a shelf

# ---------------------------------------------------------------------------
# Restock estimation constants
# ---------------------------------------------------------------------------
SHELF_DEPTH_CM = 45  # Typical gondola shelf depth in centimetres

# ---------------------------------------------------------------------------
# Expiry tracking configuration
# ---------------------------------------------------------------------------
EXPIRY_ALERT_DAYS = 30

# ---------------------------------------------------------------------------
# Reference planogram (shelf label → expected brand keywords)
# ---------------------------------------------------------------------------
MOCK_PLANOGRAM: dict[str, list[str]] = {
    "Shelf 1": ["coca-cola", "pepsi", "sprite", "fanta", "7up", "mountain dew"],
    "Shelf 2": ["lays", "doritos", "pringles", "cheetos", "ruffles", "tostitos"],
    "Shelf 3": ["oreo", "chips ahoy", "nutter butter", "ritz", "triscuit", "wheat thins"],
    "Shelf 4": ["tide", "gain", "downy", "bounce", "oxiclean", "persil"],
    "Shelf 5": ["colgate", "crest", "sensodyne", "listerine", "oral-b"],
}

# ---------------------------------------------------------------------------
# Shelf category assignments
# ---------------------------------------------------------------------------
SHELF_CATEGORIES: dict[str, str] = {
    "Shelf 1": "beverages",
    "Shelf 2": "snacks",
    "Shelf 3": "cookies & crackers",
    "Shelf 4": "cleaning supplies",
    "Shelf 5": "oral care",
}

CATEGORY_KEYWORDS: dict[str, list[str]] = {
    "beverages": ["cola", "pepsi", "sprite", "juice", "water", "soda", "drink", "tea", "coffee"],
    "snacks": ["chips", "lays", "doritos", "pringles", "cheetos", "popcorn", "nuts"],
    "cookies & crackers": ["oreo", "cookie", "cracker", "biscuit", "ritz", "wafer"],
    "cleaning supplies": ["tide", "detergent", "cleaner", "bleach", "soap", "downy", "gain"],
    "oral care": ["toothpaste", "colgate", "crest", "mouthwash", "listerine", "brush"],
}
