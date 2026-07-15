"""ONNX-based orientation classification.

Ports the preprocessing + inference technique from duartebarbosadev/deep-image-orientation-
detection's predict_onnx_batch.py (MIT licensed) without depending on torch/torchvision --
torchvision's transforms.Resize/CenterCrop operate directly on PIL Images before ToTensor(), so
the exact same preprocessing is reproducible with plain PIL + numpy. See docs/how-it-works.md.
"""

import logging
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import onnxruntime
from PIL import Image, ImageOps

try:
    import pillow_heif

    pillow_heif.register_heif_opener()
except ImportError:
    pass

log = logging.getLogger(__name__)

# The ONNX model (EfficientNetV2-S) was trained at 384x384, with a resize-then-center-crop that
# leaves a 32px margin cropped away on each pair of edges -- must match training exactly.
MODEL_INPUT_SIZE = 384
RESIZE_SIZE = MODEL_INPUT_SIZE + 32

IMAGENET_MEAN = np.array([0.485, 0.456, 0.406], dtype=np.float32)
IMAGENET_STD = np.array([0.229, 0.224, 0.225], dtype=np.float32)

# Class index -> degrees the image must be rotated CLOCKWISE to become upright. Inverse of the
# rotation the source model applied to generate training data (config.py / config.CLASS_MAP in
# deep-image-orientation-detection). Verified against the confirmed baby-photo case in
# RESEARCH_SESSION_SUMMARY.md (predicted class 1 / "90 Clockwise" was visually correct).
CORRECTIVE_ROTATION_CW_DEGREES = {0: 0, 1: 90, 2: 180, 3: 270}

# PIL Image.transpose op needed to apply each corrective rotation. PIL's ROTATE_90/ROTATE_270
# constants follow the mathematical (counter-clockwise-positive) convention, so a 90-degree
# *clockwise* correction is ROTATE_270, not ROTATE_90 -- verified empirically (see
# docs/how-it-works.md "Rotation direction" section) rather than assumed from memory.
_ROTATE_OP_BY_DEGREES = {
    0: None,
    90: Image.Transpose.ROTATE_270,
    180: Image.Transpose.ROTATE_180,
    270: Image.Transpose.ROTATE_90,
}

PREFERRED_ONNX_PROVIDERS = [
    "CUDAExecutionProvider",
    "MpsExecutionProvider",
    "ROCmExecutionProvider",
    "CoreMLExecutionProvider",
    "CPUExecutionProvider",
]


@dataclass(frozen=True)
class Prediction:
    path: Path
    predicted_class: int
    confidence: float
    corrective_rotation_degrees: int

    @property
    def needs_correction(self) -> bool:
        return self.corrective_rotation_degrees != 0


def rotate_op_for_degrees(degrees: int) -> Image.Transpose | None:
    """The PIL transpose op that applies a `degrees`-clockwise correction, or None for 0."""
    return _ROTATE_OP_BY_DEGREES[degrees]


def load_image_for_inference(path: Path) -> Image.Image:
    """Loads an image the same way the source model's predict scripts do: respect any existing
    EXIF orientation tag first (the model predicts on the image *as rendered*, matching what a
    normal EXIF-aware viewer like Preview.app would show), then flatten to RGB."""
    with Image.open(path) as img:
        img = ImageOps.exif_transpose(img)

        if img.mode in ("RGB", "L"):
            return img.convert("RGB")

        rgba = img.convert("RGBA")
        background = Image.new("RGB", rgba.size, (255, 255, 255))
        background.paste(rgba, mask=rgba)
        return background


def preprocess(img: Image.Image) -> np.ndarray:
    """Reproduces transforms.Resize((416,416)) -> CenterCrop(384) -> ToTensor() ->
    Normalize(ImageNet mean/std) using only PIL + numpy. Returns a (3, 384, 384) float32 array
    in CHW order, ready to be stacked into a batch."""
    resized = img.resize((RESIZE_SIZE, RESIZE_SIZE), Image.BILINEAR)

    margin = (RESIZE_SIZE - MODEL_INPUT_SIZE) // 2
    cropped = resized.crop((margin, margin, margin + MODEL_INPUT_SIZE, margin + MODEL_INPUT_SIZE))

    arr = np.asarray(cropped, dtype=np.float32) / 255.0  # HWC, [0, 1]
    arr = (arr - IMAGENET_MEAN) / IMAGENET_STD
    return arr.transpose(2, 0, 1)  # CHW


def load_onnx_session(model_path: Path) -> onnxruntime.InferenceSession:
    if not model_path.exists():
        raise FileNotFoundError(
            f"ONNX model not found at {model_path}. See models/README.md for how to obtain it."
        )

    available = onnxruntime.get_available_providers()
    chosen = next((p for p in PREFERRED_ONNX_PROVIDERS if p in available), "CPUExecutionProvider")
    log.info("Loading ONNX model from %s using provider: %s", model_path, chosen)

    session = onnxruntime.InferenceSession(str(model_path), providers=[chosen])

    actual = session.get_providers()[0]
    if chosen != actual and actual == "CPUExecutionProvider":
        log.warning(
            "Requested provider '%s' unavailable at session creation time; fell back to CPU.",
            chosen,
        )
    return session


def _softmax(logits: np.ndarray) -> np.ndarray:
    shifted = logits - logits.max(axis=1, keepdims=True)
    exp = np.exp(shifted)
    return exp / exp.sum(axis=1, keepdims=True)


def predict_batch(
    session: onnxruntime.InferenceSession, paths: list[Path]
) -> tuple[list[Prediction], list[tuple[Path, Exception]]]:
    """Runs inference on a batch of image paths. Images that fail to load/decode are reported
    separately rather than raising, so one corrupt file doesn't abort the whole batch."""
    valid_paths: list[Path] = []
    tensors: list[np.ndarray] = []
    errors: list[tuple[Path, Exception]] = []

    for path in paths:
        try:
            img = load_image_for_inference(path)
            tensors.append(preprocess(img))
            valid_paths.append(path)
        except Exception as exc:  # noqa: BLE001 - any decode failure is reported, not fatal
            errors.append((path, exc))

    if not tensors:
        return [], errors

    input_batch = np.stack(tensors).astype(np.float32)
    input_name = session.get_inputs()[0].name
    (logits,) = session.run(None, {input_name: input_batch})
    probs = _softmax(logits)
    predicted_classes = np.argmax(probs, axis=1)

    predictions = [
        Prediction(
            path=path,
            predicted_class=int(cls),
            confidence=float(probs[i, cls]),
            corrective_rotation_degrees=CORRECTIVE_ROTATION_CW_DEGREES[int(cls)],
        )
        for i, (path, cls) in enumerate(zip(valid_paths, predicted_classes))
    ]
    return predictions, errors
