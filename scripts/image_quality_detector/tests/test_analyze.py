"""Integration tests against the real CleanVision library (no fixtures/mocks) -- these are the
ones that actually verify the blurry/dark/light/duplicate classification behaves the way the
rest of the package assumes it does."""

import numpy as np
from PIL import Image

from image_quality_detector import analyze


def _save(img: Image.Image, path):
    img.save(path, format="JPEG", quality=95)


def _random_image(seed=0, size=(200, 200), low=60, high=200):
    rng = np.random.default_rng(seed)
    return rng.integers(low, high, size=(size[1], size[0], 3), dtype=np.uint8)


def test_analyze_images_flags_a_pure_black_image_as_dark(tmp_path):
    path = tmp_path / "black.jpg"
    _save(Image.new("RGB", (200, 200), (0, 0, 0)), path)

    results, duplicate_sets, errors = analyze.analyze_images([path])

    assert errors == []
    assert duplicate_sets == {}
    assert len(results) == 1
    assert "dark" in results[0].matched
    assert results[0].has_issue is True
    assert results[0].category_key == "dark"


def test_analyze_images_flags_a_pure_white_image_as_light(tmp_path):
    path = tmp_path / "white.jpg"
    _save(Image.new("RGB", (200, 200), (255, 255, 255)), path)

    results, duplicate_sets, errors = analyze.analyze_images([path])

    assert errors == []
    assert len(results) == 1
    assert "light" in results[0].matched


def test_analyze_images_does_not_flag_a_normal_looking_photo(tmp_path):
    path = tmp_path / "normal.jpg"
    _save(Image.fromarray(_random_image()), path)

    results, duplicate_sets, errors = analyze.analyze_images([path])

    assert errors == []
    assert results[0].has_issue is False
    assert results[0].category_key == ""


def test_analyze_images_reports_unreadable_files_as_errors_not_exceptions(tmp_path):
    good = tmp_path / "good.jpg"
    _save(Image.new("RGB", (200, 200), (0, 0, 0)), good)
    bad = tmp_path / "bad.jpg"
    bad.write_bytes(b"not a real image")

    results, duplicate_sets, errors = analyze.analyze_images([good, bad])

    assert len(errors) == 1
    assert errors[0][0] == bad
    assert isinstance(errors[0][1], Exception)
    assert [r.path for r in results] == [good]


def test_analyze_images_returns_empty_when_all_files_unreadable(tmp_path):
    bad = tmp_path / "bad.jpg"
    bad.write_bytes(b"not a real image")

    results, duplicate_sets, errors = analyze.analyze_images([bad])

    assert results == []
    assert duplicate_sets == {}
    assert len(errors) == 1


def test_analyze_images_only_runs_requested_checks(tmp_path):
    # A pure-black image would normally be flagged "dark" -- but it's not in `checks`.
    path = tmp_path / "black.jpg"
    _save(Image.new("RGB", (200, 200), (0, 0, 0)), path)

    results, duplicate_sets, errors = analyze.analyze_images([path], checks=("blurry",))

    assert errors == []
    assert results[0].has_issue is False


def test_analyze_images_finds_exact_duplicate_set(tmp_path):
    a = tmp_path / "a.jpg"
    b = tmp_path / "b.jpg"
    _save(Image.fromarray(_random_image()), a)
    b.write_bytes(a.read_bytes())  # byte-identical copy

    unrelated = tmp_path / "unrelated.jpg"
    _save(Image.fromarray(_random_image(seed=99)), unrelated)

    results, duplicate_sets, errors = analyze.analyze_images(
        [a, b, unrelated], checks=("exact_duplicates",)
    )

    assert errors == []
    # duplicate membership is never folded into QualityResult.matched -- that's the caller's job
    assert all(r.matched == frozenset() for r in results)
    assert list(duplicate_sets.keys()) == ["exact_duplicates"]
    (group,) = duplicate_sets["exact_duplicates"]
    assert set(group) == {a, b}


def test_analyze_images_finds_near_duplicate_set(tmp_path):
    a = tmp_path / "a.jpg"
    base = _random_image()
    _save(Image.fromarray(base), a)

    near = base.copy()
    near[0:5, 0:5] = 255
    b = tmp_path / "b.jpg"
    _save(Image.fromarray(near), b)

    unrelated = tmp_path / "unrelated.jpg"
    _save(Image.fromarray(_random_image(seed=99)), unrelated)

    results, duplicate_sets, errors = analyze.analyze_images(
        [a, b, unrelated], checks=("near_duplicates",)
    )

    assert errors == []
    assert list(duplicate_sets.keys()) == ["near_duplicates"]
    (group,) = duplicate_sets["near_duplicates"]
    assert set(group) == {a, b}


def test_analyze_images_omits_duplicate_categories_with_no_matches(tmp_path):
    a = tmp_path / "a.jpg"
    b = tmp_path / "b.jpg"
    _save(Image.fromarray(_random_image(seed=1)), a)
    _save(Image.fromarray(_random_image(seed=2)), b)

    results, duplicate_sets, errors = analyze.analyze_images(
        [a, b], checks=("exact_duplicates", "near_duplicates")
    )

    assert errors == []
    assert duplicate_sets == {}
