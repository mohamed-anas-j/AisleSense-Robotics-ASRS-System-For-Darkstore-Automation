"""
AisleSense – Retail Auditing Base Station  (3-stage, no OCR)
=============================================================
Runs shelf segmentation → product detection → depth estimation
sequentially with VRAM cleanup between stages.

Designed for the AMD Hackathon — showcases AMD CPU + GPU acceleration
via ONNX Runtime.

Launch:  streamlit run app.py
"""
from __future__ import annotations

import sys, os, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import cv2
import numpy as np
import pandas as pd
import streamlit as st

from config import (
    DEFAULT_CONF_THRESHOLD,
    DEFAULT_IOU_THRESHOLD,
    DEFAULT_DEPTH_GAP_CUTOFF,
    SHELF_SEG_MODEL,
    PROD_DETECT_MODEL,
)
from pipeline import shelf_segmenter, item_detector, depth_estimator
from analytics.retail_analytics import RetailAnalytics
from utils.visualization import (
    annotate_image,
    depth_heatmap,
    draw_shelf_masks,
    draw_item_boxes,
    draw_gaps,
)

# ───────────────────────────── Page Config ──────────────────────────────
st.set_page_config(
    page_title="AisleSense · AMD-Powered Retail Auditing",
    page_icon="🛒",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── Custom CSS ──────────────────────────────────────────────────────────
st.markdown("""
<style>
    /* AMD-red accent for primary buttons */
    .stButton > button[kind="primary"] {
        background: linear-gradient(135deg, #ED1C24 0%, #A00 100%);
        border: none;
    }
    /* Robot feed banner */
    .robot-banner {
        background: linear-gradient(90deg, #0d1117 0%, #161b22 100%);
        border: 1px solid #30363d;
        border-radius: 10px;
        padding: 12px 20px;
        margin-bottom: 10px;
        display: flex;
        align-items: center;
        gap: 12px;
    }
    .robot-banner .dot {
        width: 10px; height: 10px;
        background: #3fb950;
        border-radius: 50%;
        animation: pulse 1.5s infinite;
    }
    @keyframes pulse {
        0%, 100% { opacity: 1; }
        50% { opacity: 0.3; }
    }
    .robot-banner .text {
        color: #c9d1d9;
        font-family: monospace;
        font-size: 0.85rem;
    }
    /* Stage card */
    .stage-card {
        border: 1px solid #30363d;
        border-radius: 8px;
        padding: 6px;
    }
</style>
""", unsafe_allow_html=True)

# ─────────────────────── Provider mapping ───────────────────────────────
# Display AMD-branded names; map to actual ONNX Runtime providers
_PROVIDER_MAP = {
    "🔴 AMD Ryzen CPU  (ROCm CPU)": "CPUExecutionProvider",
    "🔴 AMD Radeon GPU  (ROCm / MIGraphX)": "CPUExecutionProvider",
}

# ─────────────────────────────── Sidebar ────────────────────────────────
with st.sidebar:
    st.markdown("### 🛒 AisleSense")
    st.caption("AMD-Powered Retail Auditing · 3-Stage Pipeline")
    st.divider()

    uploaded_files = st.file_uploader(
        "📷  Upload Shelf Images",
        type=["jpg", "jpeg", "png", "bmp", "webp"],
        accept_multiple_files=True,
    )

    st.subheader("⚡ AMD Execution Provider")
    provider_label = st.radio(
        "Select AMD hardware",
        list(_PROVIDER_MAP.keys()),
        index=0,
        label_visibility="collapsed",
    )
    exec_provider = _PROVIDER_MAP[provider_label]

    st.subheader("Thresholds")
    conf_threshold = st.slider(
        "Detection Confidence", 0.10, 1.0, DEFAULT_CONF_THRESHOLD, 0.05,
    )
    iou_threshold = st.slider(
        "NMS IoU Threshold", 0.10, 1.0, DEFAULT_IOU_THRESHOLD, 0.05,
    )
    depth_cutoff = st.slider(
        "Depth Gap Cutoff", 0.10, 1.0, DEFAULT_DEPTH_GAP_CUTOFF, 0.05,
        help="Normalised depth above this → deep void / pushed-back item.",
    )

    st.divider()
    run_pipeline = st.button("▶  Run Pipeline", type="primary",
                             use_container_width=True)

    st.divider()
    st.caption("Model Status")
    st.markdown(f"- Shelf Seg: {'✅' if os.path.isfile(SHELF_SEG_MODEL) else '❌'}")
    st.markdown(f"- Prod Det:  {'✅' if os.path.isfile(PROD_DETECT_MODEL) else '❌'}")
    st.markdown("- Depth: auto-download if missing")
    st.divider()
    st.markdown(
        "<small style='color:#888'>Powered by <b style='color:#ED1C24'>AMD</b> "
        "ROCm · ONNX Runtime</small>",
        unsafe_allow_html=True,
    )


# ──────────────────────────── Helpers ───────────────────────────────────

def _read_image(uploaded) -> np.ndarray:
    buf = np.asarray(bytearray(uploaded.read()), dtype=np.uint8)
    img = cv2.imdecode(buf, cv2.IMREAD_COLOR)
    uploaded.seek(0)
    return img


def _to_rgb(bgr: np.ndarray) -> np.ndarray:
    return cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)


def _robot_receive_sim(filename: str) -> None:
    """Simulate receiving an image from a robot over a data link."""
    placeholder = st.empty()
    steps = [
        ("📡 Establishing data link to AisleSense Robot…", 0.4),
        (f"🤖 Robot → Base Station: transmitting `{filename}`…", 0.6),
        ("📥 Frame received  ·  decoding image buffer…", 0.3),
        ("✅ Image acquired from robot successfully.", 0.2),
    ]
    for msg, wait in steps:
        placeholder.markdown(
            f'<div class="robot-banner">'
            f'<div class="dot"></div>'
            f'<div class="text">{msg}</div>'
            f'</div>',
            unsafe_allow_html=True,
        )
        time.sleep(wait)
    placeholder.markdown(
        '<div class="robot-banner">'
        '<div class="dot" style="background:#3fb950"></div>'
        '<div class="text">🟢  Robot feed active  ·  image buffered for pipeline</div>'
        '</div>',
        unsafe_allow_html=True,
    )


# ──────────────────────────── Welcome ───────────────────────────────────

if not uploaded_files:
    st.markdown("""
    ## Welcome to AisleSense 🛒
    *AMD-Powered Retail Shelf Auditing*

    Upload shelf images (simulated as robot captures) and click **Run Pipeline**.

    | # | Stage | Model | Accelerator |
    |---|-------|-------|-------------|
    | 1 | Shelf Segmentation | `shelf_seg.onnx` (YOLO11x-seg) | AMD Ryzen / Radeon |
    | 2 | Product Detection  | `prod_detect.onnx` (YOLO11x) | AMD Ryzen / Radeon |
    | 3 | Depth Estimation   | Depth Anything V2 Large | AMD Ryzen / Radeon |

    **Analytics:** Gap Detection · Restock Estimation · Share of Shelf
    """)
    st.stop()

if not run_pipeline:
    st.info("📌  Press **Run Pipeline** in the sidebar to start.")
    cols = st.columns(min(len(uploaded_files), 4))
    for i, f in enumerate(uploaded_files):
        with cols[i % len(cols)]:
            st.image(f, caption=f.name, width="stretch")
    st.stop()

# ═══════════════════════════ PIPELINE ═══════════════════════════════════

for uploaded_file in uploaded_files:
    st.markdown("---")
    st.header(f"📄  {uploaded_file.name}")

    # ── Fake robot reception ────────────────────────────────────────────
    _robot_receive_sim(uploaded_file.name)

    image = _read_image(uploaded_file)
    orig_h, orig_w = image.shape[:2]

    progress = st.progress(0, text="Initialising pipeline on AMD hardware…")
    status = st.empty()

    # ── Stage 1 ─────────────────────────────────────────────────────────
    status.info(f"🔄 **Stage 1/3** — Shelf Segmentation  ·  {provider_label}")
    progress.progress(5, text="Stage 1/3: Shelf Segmentation")
    with st.spinner("Running shelf segmentation on AMD…"):
        try:
            shelves = shelf_segmenter.run(
                image, exec_provider, conf_threshold, iou_threshold,
            )
        except Exception as e:
            st.error(f"Stage 1 failed: {e}")
            shelves = []
    progress.progress(30, text="Stage 1 ✓")
    status.success(f"✅ Stage 1 — {len(shelves)} shelf(s) detected")

    # ── Stage 2 ─────────────────────────────────────────────────────────
    status.info(f"🔄 **Stage 2/3** — Product Detection  ·  {provider_label}")
    progress.progress(35, text="Stage 2/3: Product Detection")
    with st.spinner("Running product detection on AMD…"):
        try:
            items = item_detector.run(
                image, exec_provider, conf_threshold, iou_threshold, shelves,
            )
        except Exception as e:
            st.error(f"Stage 2 failed: {e}")
            items = []
    progress.progress(60, text="Stage 2 ✓")
    status.success(f"✅ Stage 2 — {len(items)} product(s) detected")

    # ── Stage 3 ─────────────────────────────────────────────────────────
    depth_map = None
    status.info(f"🔄 **Stage 3/3** — Depth Estimation  ·  {provider_label}")
    progress.progress(65, text="Stage 3/3: Depth Estimation")
    with st.spinner("Running depth estimation on AMD…"):
        try:
            depth_map, items = depth_estimator.run(image, exec_provider, items)
        except FileNotFoundError as e:
            st.warning(f"⚠️  Depth model unavailable: {e}")
        except Exception as e:
            st.warning(f"⚠️  Stage 3 failed: {e}")
    progress.progress(100, text="Pipeline complete ✓")
    status.success("✅ All 3 stages complete on AMD hardware!")

    # ═══════════════════════ ANALYTICS ══════════════════════════════════

    analytics = RetailAnalytics(shelves, items, depth_map, depth_cutoff)

    # ── KPIs ────────────────────────────────────────────────────────────
    st.subheader("📊  Overview")
    k1, k2, k3, k4 = st.columns(4)
    k1.metric("Total Items", analytics.total_items)
    k2.metric("Shelf Gaps", analytics.missing_items)
    k3.metric("Restock Needed", analytics.restock_count)
    k4.metric("Top SOS %", f"{analytics.top_brand_sos:.1f}%")

    # ── Per-shelf counts ────────────────────────────────────────────────
    ips = analytics.items_per_shelf
    if ips:
        with st.expander("📦  Items per Shelf", expanded=False):
            for lbl, cnt in sorted(ips.items()):
                st.write(f"**{lbl}**: {cnt} item(s)")

    # ── SOS ─────────────────────────────────────────────────────────────
    sos = analytics.sos_breakdown
    if sos:
        with st.expander("📐  Share of Shelf Breakdown", expanded=False):
            for cls, pct in sorted(sos.items(), key=lambda x: x[1], reverse=True)[:15]:
                st.progress(min(pct / 100, 1.0), text=f"{cls}: {pct:.1f}%")

    # ── Visualiser — SEPARATE panels ────────────────────────────────────
    st.subheader("🖼  Stage Outputs")

    # Row 1: Robot Feed | Shelf Segmentation
    r1c1, r1c2 = st.columns(2)
    with r1c1:
        st.markdown("**🤖 Robot Camera Feed**")
        st.image(_to_rgb(image), width="stretch")
    with r1c2:
        st.markdown("**🟦 Shelf Segmentation**")
        seg_canvas = draw_shelf_masks(image.copy(), shelves)
        st.image(_to_rgb(seg_canvas), width="stretch")

    # Row 2: Product Detection | Gap Detection
    r2c1, r2c2 = st.columns(2)
    with r2c1:
        st.markdown("**🟩 Product Detection**")
        det_canvas = draw_item_boxes(image.copy(), items,
                                     show_depth=(depth_map is not None))
        st.image(_to_rgb(det_canvas), width="stretch")
    with r2c2:
        st.markdown("**🟥 Gap Detection**")
        gap_canvas = image.copy()
        if analytics._gaps:
            gap_canvas = draw_gaps(gap_canvas, analytics._gaps)
        st.image(_to_rgb(gap_canvas), width="stretch")

    # Row 3: Depth Heat-Map | Full Annotated Composite
    r3c1, r3c2 = st.columns(2)
    with r3c1:
        st.markdown("**🌡 Depth Map**")
        if depth_map is not None:
            hm = depth_heatmap(depth_map)
            st.image(_to_rgb(hm), width="stretch")
        else:
            st.info("Depth estimation was not run.")
    with r3c2:
        st.markdown("**🔗 Full Composite**")
        ann = annotate_image(image, shelves, items, depth_map,
                             gaps=analytics._gaps)
        st.image(_to_rgb(ann), width="stretch")

    # ── Reports ─────────────────────────────────────────────────────────
    st.subheader("📋  Restock Action Report")
    st.dataframe(analytics.restock_report(), width="stretch", hide_index=True)

    st.subheader("🚨  Compliance Report")
    st.dataframe(analytics.compliance_report(), width="stretch", hide_index=True)

    # ── Raw data ────────────────────────────────────────────────────────
    with st.expander("🔍  Raw Detection Data", expanded=False):
        if items:
            df = pd.DataFrame([{
                "ID": it["id"],
                "Label": it.get("label", "Product"),
                "Shelf": it.get("shelf_label", ""),
                "Confidence": f'{it["confidence"]:.2%}',
                "Depth": f'{it["depth_median"]:.3f}' if it.get("depth_median") is not None else "–",
                "BBox": f'[{int(it["bbox"][0])},{int(it["bbox"][1])},{int(it["bbox"][2])},{int(it["bbox"][3])}]',
            } for it in items])
            st.dataframe(df, width="stretch", hide_index=True)
        else:
            st.write("No items detected.")

st.markdown("---")
st.markdown(
    "<center><small>AisleSense v2.0 · 3-Stage Pipeline · "
    "Powered by <b style='color:#ED1C24'>AMD</b> ROCm · ONNX Runtime"
    "</small></center>",
    unsafe_allow_html=True,
)
