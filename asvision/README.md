# AisleSense — Offline Retail Auditing Base Station

AisleSense is a hardware-agnostic, offline image-processing application for grocery shelf auditing. It runs a 4-stage ONNX machine learning pipeline on high-resolution shelf images and produces actionable retail analytics through a Streamlit dashboard.

## Pipeline Stages

| # | Stage | Model | Purpose |
|---|-------|-------|---------|
| 1 | Shelf Segmentation | `shelf_seg.onnx` (YOLO11x-seg) | Detect physical shelf levels and polygon masks |
| 2 | Product Detection | `prod_detect.onnx` (YOLO11x) | Locate individual product bounding boxes |
| 3 | Depth Estimation | Depth Anything V2 Large | Generate metric depth map for Z-axis analysis |
| 4 | Text Verification | EasyOCR | Extract brands, prices, and expiry dates |

> Models are executed **sequentially** with explicit session destruction between stages to stay within 4 GB VRAM.

## Analytics

- **Gap Detection** — shelf regions with no products where depth indicates a deep void
- **Restock Volume Estimation** — empty void space in front of pushed-back items
- **Planogram Compliance** — detected items checked against expected shelf layouts
- **Orphaned Item Flagging** — items whose OCR text mismatches their shelf category
- **Expiry Date Tracking (FEFO)** — dates approaching within 30 days are flagged
- **Share of Shelf (SOS)** — pixel-width ratio per brand across all shelves

## Project Structure

```
asvision/
├── app.py                       # Streamlit entry point
├── config.py                    # Paths, thresholds, mock planogram data
├── requirements.txt
├── models/
│   ├── shelf_seg.onnx
│   └── prod_detect.onnx
├── pipeline/
│   ├── session_manager.py       # ONNX session lifecycle + VRAM cleanup
│   ├── preprocessor.py          # Letterbox resize, ImageNet normalisation
│   ├── postprocessor.py         # NMS, output parsing, mask reconstruction
│   ├── shelf_segmenter.py       # Stage 1
│   ├── item_detector.py         # Stage 2
│   ├── depth_estimator.py       # Stage 3 (auto-downloads from HuggingFace)
│   └── text_verifier.py         # Stage 4
├── analytics/
│   └── retail_analytics.py      # All business-logic KPIs
└── utils/
    └── visualization.py         # Annotation, heatmaps, gap highlights
```

## Setup (Conda)

### 1. Create the environment

```bash
conda create -n asvision python=3.11 -y
conda activate asvision
```

### 2. Install dependencies

**CPU-only:**

```bash
pip install -r requirements.txt
```

**With CUDA (GPU) support:**

```bash
# Install CUDA-enabled ONNX Runtime instead of the CPU version
pip install onnxruntime-gpu>=1.17.0

# Install the rest
pip install streamlit>=1.30.0 opencv-python>=4.9.0 numpy>=1.24.0 \
    Pillow>=10.0.0 easyocr>=1.7.0 huggingface-hub>=0.20.0 \
    pandas>=2.0.0 scipy>=1.11.0
```

> When using GPU, select **CUDAExecutionProvider** in the sidebar dropdown.

### 3. Place models

Ensure ONNX model weights are in the `models/` directory:

```
models/
├── shelf_seg.onnx       # YOLO11x-seg for shelf segmentation
└── prod_detect.onnx     # YOLO11x for product detection
```

The **Depth Anything V2 Large** model is downloaded automatically from HuggingFace on first run. To pre-download it manually:

```bash
conda activate asvision
python -c "from pipeline.depth_estimator import ensure_model; ensure_model()"
```

### 4. Run

```bash
conda activate asvision
streamlit run app.py
```

The dashboard opens at `http://localhost:8501`.

## Usage

1. Upload one or more shelf images via the sidebar.
2. Select the execution provider (CPU or CUDA).
3. Adjust confidence, IoU, and depth-gap thresholds as needed.
4. Click **Run Pipeline** — progress bars track each stage.
5. Review KPIs, annotated images, depth heatmaps, and data tables.

## Environment Management

```bash
# List packages in the environment
conda list -n asvision

# Update all pip packages
conda activate asvision && pip install -r requirements.txt --upgrade

# Remove the environment
conda deactivate
conda env remove -n asvision
```

## Requirements

- Python 3.10+
- 4 GB+ VRAM (GPU) or 16 GB+ RAM (CPU-only)
- Models: `shelf_seg.onnx`, `prod_detect.onnx` in `models/`
- Internet connection on first run (to download the depth model)
