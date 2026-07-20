"""Integration tests against the real CleanVision library (no fixtures/mocks) -- these are the
ones that actually verify the blurry/dark/light classification behaves the way the rest of the
package assumes it does."""

import numpy as np
from PIL import Image

from image_quality_detector import analyze


def _save(img: Image.Image, path):
    img.save(path, format="JPEG", quality=95)


def test_analyze_images_flags_a_pure_black_image_as_dark(tmp_path):
    path = tmp_path / "black.jpg"
    _save(Image.new("RGB", (200, 200), (0, 0, 0)), path)

    results, errors = analyze.analyze_images([path])

    assert errors == []
    assert len(results) == 1
    assert "dark" in results[0].matched
    assert results[0].has_issue is True
    assert results[0].category_key == "dark"


def test_analyze_images_flags_a_pure_white_image_as_light(tmp_path):
    path = tmp_path / "white.jpg"
    _save(Image.new("RGB", (200, 200), (255, 255, 255)), path)

    results, errors = analyze.analyze_images([path])

    assert errors == []
    assert len(results) == 1
    assert "light" in results[0].matched


def test_analyze_images_does_not_flag_a_normal_looking_photo(tmp_path):
    path = tmp_path / "normal.jpg"
    rng = np.random.default_rng(0)
    arr = rng.integers(60, 200, size=(200, 200, 3), dtype=np.uint8)
    _save(Image.fromarray(arr), path)

    results, errors = analyze.analyze_images([path])

    assert errors == []
    assert results[0].has_issue is False
    assert results[0].category_key == ""


def test_analyze_images_reports_unreadable_files_as_errors_not_exceptions(tmp_path):
    good = tmp_path / "good.jpg"
    _save(Image.new("RGB", (200, 200), (0, 0, 0)), good)
    bad = tmp_path / "bad.jpg"
    bad.write_bytes(b"not a real image")

    results, errors = analyze.analyze_images([good, bad])

    assert len(errors) == 1
    assert errors[0][0] == bad
    assert isinstance(errors[0][1], Exception)
    assert [r.path for r in results] == [good]


def test_analyze_images_returns_empty_when_all_files_unreadable(tmp_path):
    bad = tmp_path / "bad.jpg"
    bad.write_bytes(b"not a real image")

    results, errors = analyze.analyze_images([bad])

    assert results == []
    assert len(errors) == 1
