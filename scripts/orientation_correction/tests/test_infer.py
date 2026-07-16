import os
from pathlib import Path

import numpy as np
import pytest
from conftest import marker_corner, marker_image
from PIL import Image

from orientation_correction import infer

_REAL_MODEL_PATH = Path(__file__).resolve().parent.parent / "models" / "best_model.onnx"
_REAL_PHOTO_ENV = "ORIENTATION_CORRECTION_TEST_PHOTO"
_REAL_PHOTO_EXPECTED_DEGREES_ENV = "ORIENTATION_CORRECTION_TEST_PHOTO_EXPECTED_DEGREES"


class _FakeInput:
    name = "input"


class FakeSession:
    """Duck-types the slice of onnxruntime.InferenceSession's interface infer.py uses, so
    predict_batch()'s batching/decision logic can be tested without the real ~80MB model."""

    def __init__(self, logits_by_index: list[np.ndarray]):
        self.logits_by_index = logits_by_index
        self.batch_sizes_seen: list[int] = []

    def get_inputs(self):
        return [_FakeInput()]

    def run(self, output_names, feed):
        batch = feed["input"]
        n = batch.shape[0]
        self.batch_sizes_seen.append(n)
        logits = np.stack(self.logits_by_index[:n])
        return [logits]


def test_rotate_op_for_degrees_mapping():
    # Verified empirically against PIL's own convention -- see docs/how-it-works.md.
    assert infer.rotate_op_for_degrees(0) is None
    assert infer.rotate_op_for_degrees(90) == Image.Transpose.ROTATE_270
    assert infer.rotate_op_for_degrees(180) == Image.Transpose.ROTATE_180
    assert infer.rotate_op_for_degrees(270) == Image.Transpose.ROTATE_90


def test_preprocess_output_shape_and_dtype():
    img = Image.new("RGB", (500, 500), (128, 64, 32))
    arr = infer.preprocess(img)
    assert arr.shape == (3, infer.MODEL_INPUT_SIZE, infer.MODEL_INPUT_SIZE)
    assert arr.dtype == np.float32


def test_preprocess_numeric_correctness_for_a_solid_color_image():
    color = (128, 64, 32)
    img = Image.new("RGB", (500, 500), color)
    arr = infer.preprocess(img)

    expected = (
        np.array(color, dtype=np.float32) / 255.0 - infer.IMAGENET_MEAN
    ) / infer.IMAGENET_STD
    for channel in range(3):
        assert np.allclose(arr[channel], expected[channel], atol=1e-3)


def test_load_image_for_inference_applies_exif_transpose(tmp_path):
    path = tmp_path / "a.jpg"
    img = marker_image(30, 60, "top-left")
    exif = img.getexif()
    exif[0x0112] = 6  # Orientation: viewer should render this rotated 90 CW
    img.save(path, format="JPEG", exif=exif, quality=95)

    loaded = infer.load_image_for_inference(path)

    assert loaded.mode == "RGB"
    assert marker_corner(loaded) == "top-right"


def test_load_image_for_inference_flattens_rgba_onto_white(tmp_path):
    path = tmp_path / "a.png"
    Image.new("RGBA", (10, 10), (0, 0, 0, 0)).save(path)

    loaded = infer.load_image_for_inference(path)

    assert loaded.mode == "RGB"
    assert loaded.getpixel((5, 5)) == (255, 255, 255)


def test_softmax_sums_to_one_and_preserves_argmax():
    logits = np.array([[1.0, 2.0, 3.0, 0.5]], dtype=np.float32)
    probs = infer._softmax(logits)
    assert np.isclose(probs.sum(), 1.0)
    assert int(np.argmax(probs)) == 2


def test_predict_batch_maps_classes_to_corrective_degrees(tmp_path):
    paths = [tmp_path / f"{i}.jpg" for i in range(4)]
    for p in paths:
        marker_image(60, 30, "top-left").save(p, format="JPEG", quality=95)

    logits = [
        np.array([10.0, 0.0, 0.0, 0.0], dtype=np.float32),
        np.array([0.0, 10.0, 0.0, 0.0], dtype=np.float32),
        np.array([0.0, 0.0, 10.0, 0.0], dtype=np.float32),
        np.array([0.0, 0.0, 0.0, 10.0], dtype=np.float32),
    ]
    session = FakeSession(logits)

    predictions, errors = infer.predict_batch(session, paths)

    assert errors == []
    assert [p.predicted_class for p in predictions] == [0, 1, 2, 3]
    assert [p.corrective_rotation_degrees for p in predictions] == [0, 90, 180, 270]
    assert [p.needs_correction for p in predictions] == [False, True, True, True]
    assert all(p.confidence > 0.99 for p in predictions)
    assert session.batch_sizes_seen == [4]


def test_predict_batch_reports_load_errors_without_aborting(tmp_path):
    bad = tmp_path / "bad.jpg"
    bad.write_bytes(b"not a real image")
    good = tmp_path / "good.jpg"
    marker_image(60, 30, "top-left").save(good, format="JPEG", quality=95)

    session = FakeSession([np.array([10.0, 0.0, 0.0, 0.0], dtype=np.float32)])

    predictions, errors = infer.predict_batch(session, [bad, good])

    assert len(predictions) == 1
    assert predictions[0].path == good
    assert len(errors) == 1
    assert errors[0][0] == bad


def test_predict_batch_returns_empty_for_all_unreadable(tmp_path):
    bad = tmp_path / "bad.jpg"
    bad.write_bytes(b"not a real image")
    session = FakeSession([])

    predictions, errors = infer.predict_batch(session, [bad])

    assert predictions == []
    assert len(errors) == 1
    assert session.batch_sizes_seen == []  # never called run() with an empty batch


def test_load_onnx_session_raises_for_missing_model(tmp_path):
    with pytest.raises(FileNotFoundError):
        infer.load_onnx_session(tmp_path / "nope.onnx")


@pytest.mark.skipif(
    not (os.environ.get(_REAL_PHOTO_ENV) and os.environ.get(_REAL_PHOTO_EXPECTED_DEGREES_ENV)),
    reason=(
        f"opt-in regression check against a real photo with a known-correct answer -- set "
        f"{_REAL_PHOTO_ENV}=/path/to/photo.jpg and "
        f"{_REAL_PHOTO_EXPECTED_DEGREES_ENV}=<0|90|180|270> locally to run it (requires the "
        f"real model at {_REAL_MODEL_PATH} too)"
    ),
)
def test_known_orientation_regression():
    """No real photo path is hardcoded in the repo -- point this at any photo with a
    manually-confirmed correct answer via environment variables. Originally exercised against
    the case documented in RESEARCH_SESSION_SUMMARY.md (a specific photo confirmed to need a
    90-degree clockwise correction)."""
    if not _REAL_MODEL_PATH.exists():
        pytest.skip(f"model not present at {_REAL_MODEL_PATH}")

    photo = Path(os.environ[_REAL_PHOTO_ENV])
    expected_degrees = int(os.environ[_REAL_PHOTO_EXPECTED_DEGREES_ENV])

    session = infer.load_onnx_session(_REAL_MODEL_PATH)
    predictions, errors = infer.predict_batch(session, [photo])

    assert errors == []
    assert predictions[0].corrective_rotation_degrees == expected_degrees
