# AisleSense Models

This directory contains the ONNX model files required for the vision pipeline. These files are **not included in the repository** due to their size.

## Required Models

### 1. Shelf Segmentation Model
- **File:** `shelf_seg.onnx`
- **Description:** YOLO11x-seg trained for shelf instance segmentation
- **Download:** [Provide download link or instructions]
- **Size:** ~200 MB

### 2. Product Detection Model
- **File:** `prod_detect.onnx`
- **Description:** YOLO11x trained for retail product detection
- **Download:** [Provide download link or instructions]
- **Size:** ~130 MB

### 3. Depth Estimation Model
- **File:** `depth_anything_v2_large.onnx`
- **Source:** Hugging Face - `onnx-community/depth-anything-v2-large`
- **Auto-download:** The application will automatically download this model on first run
- **Size:** ~1.3 GB

### Alternative: Manual Depth Model Download

```bash
# Install huggingface_hub
pip install huggingface_hub

# Download the model
from huggingface_hub import hf_hub_download
hf_hub_download(
    repo_id="onnx-community/depth-anything-v2-large",
    filename="onnx/model.onnx",
    local_dir="./models/",
    local_dir_use_symlinks=False
)
```

## Directory Structure

```
models/
├── README.md                           # This file
├── .gitkeep                           # Preserves directory in Git
├── shelf_seg.onnx                     # Download required
├── prod_detect.onnx                   # Download required
└── onnx/
    └── model.onnx                     # Auto-downloaded (depth model)
```

## Training Your Own Models

If you want to train custom models:

1. **Shelf Segmentation:** Use YOLO11x-seg with annotated shelf images
2. **Product Detection:** Use YOLO11x with labeled product bounding boxes
3. **Export to ONNX:** Use Ultralytics export functionality

```python
from ultralytics import YOLO

# Load your trained model
model = YOLO('path/to/your/model.pt')

# Export to ONNX
model.export(format='onnx', simplify=True)
```

## Troubleshooting

- **Model not found:** Ensure files are in the correct directory with exact names
- **ONNX Runtime errors:** Verify you have `onnxruntime` or `onnxruntime-gpu` installed
- **Out of memory:** The pipeline loads models sequentially to manage VRAM usage
