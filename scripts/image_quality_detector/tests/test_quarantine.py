import pytest

from image_quality_detector import naming, quarantine


def test_quarantine_image_moves_file_to_category_subdir(tmp_path):
    path = tmp_path / "a.jpg"
    path.write_bytes(b"original bytes")

    dest = quarantine.quarantine_image(path, "blurry")

    assert dest == tmp_path / "_quality_review" / "blurry" / "a.jpg"
    assert dest.read_bytes() == b"original bytes"
    assert not path.exists()


def test_quarantine_image_creates_combined_category_subdir(tmp_path):
    path = tmp_path / "a.jpg"
    path.write_bytes(b"x")

    dest = quarantine.quarantine_image(path, "dark+light")

    assert dest.parent.name == "dark+light"
    assert dest.exists()


def test_quarantine_image_raises_if_destination_already_exists(tmp_path):
    path = tmp_path / "a.jpg"
    path.write_bytes(b"new")
    dest = naming.quarantine_path_for(path, "blurry")
    dest.parent.mkdir(parents=True)
    dest.write_bytes(b"stale leftover")

    with pytest.raises(FileExistsError):
        quarantine.quarantine_image(path, "blurry")

    # neither file should have been touched by the failed attempt
    assert path.read_bytes() == b"new"
    assert dest.read_bytes() == b"stale leftover"
