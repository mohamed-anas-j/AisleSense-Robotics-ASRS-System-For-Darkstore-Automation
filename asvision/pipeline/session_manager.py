"""
ONNX Session Manager
====================
Creates and destroys ``onnxruntime.InferenceSession`` instances one at
a time to stay within a 4 GB VRAM budget.  Also provides a helper to
read the expected spatial input size directly from a loaded model.
"""
import gc
import onnxruntime as ort


def create_session(model_path: str, provider: str) -> ort.InferenceSession:
    """Create an ONNX Runtime inference session with the specified execution provider."""
    providers = [provider]
    if provider == "CUDAExecutionProvider":
        providers.append("CPUExecutionProvider")

    opts = ort.SessionOptions()
    opts.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
    opts.intra_op_num_threads = 0          # let ORT pick
    opts.log_severity_level = 3            # suppress verbose logs

    return ort.InferenceSession(model_path, sess_options=opts, providers=providers)


def destroy_session(session: ort.InferenceSession | None) -> None:
    """Release an ONNX session and reclaim GPU/CPU memory."""
    if session is not None:
        del session
    gc.collect()
    try:
        import torch
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
    except ImportError:
        pass


def get_model_input_size(session: ort.InferenceSession, fallback: int = 640) -> int:
    """Read the spatial (H or W) size from the first model input.

    Works for shapes like ``[1, 3, H, W]``.  Dynamic/symbolic dims return
    *fallback*.
    """
    shape = session.get_inputs()[0].shape
    if len(shape) >= 4:
        h = shape[2]
        if isinstance(h, int) and h > 0:
            return h
    return fallback
