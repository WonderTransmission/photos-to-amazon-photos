from pathlib import Path

from image_quality_detector import naming


def test_quarantine_path_for_nests_under_category_subdir():
    original = Path("/photos/2003/02/IMG_1234.JPG")
    dest = naming.quarantine_path_for(original, "blurry")
    assert dest == Path("/photos/2003/02/_quality_review/blurry/IMG_1234.JPG")


def test_quarantine_path_for_combined_category():
    original = Path("/photos/IMG_1234.JPG")
    dest = naming.quarantine_path_for(original, "dark+light")
    assert dest == Path("/photos/_quality_review/dark+light/IMG_1234.JPG")


def test_is_quarantine_path_recognizes_what_quarantine_path_for_produces():
    original = Path("/photos/IMG_1234.JPG")
    dest = naming.quarantine_path_for(original, "blurry")
    assert naming.is_quarantine_path(dest) is True
    assert naming.is_quarantine_path(original) is False


def test_is_quarantine_path_rejects_lookalike_filenames():
    # Must not false-positive on a real filename that happens to contain the dirname as a
    # substring without it actually being a path component.
    assert naming.is_quarantine_path(Path("/photos/_quality_review_notes.txt")) is False


def test_find_quarantined_none_when_absent(tmp_path):
    original = tmp_path / "a.jpg"
    original.write_bytes(b"x")
    assert naming.find_quarantined(original) is None


def test_find_quarantined_finds_it(tmp_path):
    original = tmp_path / "a.jpg"
    original.write_bytes(b"x")
    dest = naming.quarantine_path_for(original, "blurry")
    dest.parent.mkdir(parents=True)
    dest.write_bytes(b"moved bytes")
    original.unlink()

    assert naming.find_quarantined(original) == dest


def test_find_quarantined_does_not_match_a_different_file(tmp_path):
    (tmp_path / "a.jpg").write_bytes(b"x")
    other_dest = naming.quarantine_path_for(tmp_path / "b.jpg", "dark")
    other_dest.parent.mkdir(parents=True)
    other_dest.write_bytes(b"x")

    assert naming.find_quarantined(tmp_path / "a.jpg") is None
