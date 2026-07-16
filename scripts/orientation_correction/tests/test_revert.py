import pytest
from PIL import Image

from orientation_correction import correct, ignore_list, naming, revert
from tests.conftest import marker_corner, marker_image

RUN_TS = "20260715T120000"


def test_parse_review_file_skips_blank_lines_and_comments(tmp_path):
    review = tmp_path / "review.txt"
    a = tmp_path / "a.jpg"
    b = tmp_path / "b.jpg"
    review.write_text(f"# header\n\n{a}\n# a comment\n{b}\n\n")

    assert revert.parse_review_file(review) == [a, b]


def test_revert_entries_restores_original_and_consumes_backup(tmp_path):
    path = tmp_path / "a.jpg"
    marker_image(60, 30, "top-left").save(path, format="JPEG", quality=95)
    correct.correct_image(path, Image.Transpose.ROTATE_270, RUN_TS)  # now (wrongly) corrected
    backup = naming.find_existing_backup(path)
    assert backup is not None

    ignore_path = tmp_path / "ignore-list.txt"
    counts = revert.revert_entries([path], ignore_path)

    assert counts[revert.REVERTED] == 1
    assert not backup.exists()  # consumed by the revert
    with Image.open(path) as im:
        assert marker_corner(im) == "top-left"  # back to the pre-correction orientation


def test_revert_entries_adds_to_ignore_list(tmp_path):
    path = tmp_path / "a.jpg"
    marker_image(60, 30, "top-left").save(path, format="JPEG", quality=95)
    correct.correct_image(path, Image.Transpose.ROTATE_270, RUN_TS)

    ignore_path = tmp_path / "ignore-list.txt"
    revert.revert_entries([path], ignore_path)

    assert path.resolve() in ignore_list.load(ignore_path)


def test_revert_entries_without_a_backup_still_adds_to_ignore_list(tmp_path):
    path = tmp_path / "never_corrected.jpg"
    marker_image(60, 30, "top-left").save(path, format="JPEG", quality=95)
    original_bytes = path.read_bytes()

    ignore_path = tmp_path / "ignore-list.txt"
    counts = revert.revert_entries([path], ignore_path)

    assert counts[revert.NO_BACKUP_FOUND] == 1
    assert counts[revert.REVERTED] == 0
    assert path.read_bytes() == original_bytes  # untouched
    assert path.resolve() in ignore_list.load(ignore_path)


def test_main_end_to_end(tmp_path, capsys):
    path = tmp_path / "a.jpg"
    marker_image(60, 30, "top-left").save(path, format="JPEG", quality=95)
    correct.correct_image(path, Image.Transpose.ROTATE_270, RUN_TS)

    review = tmp_path / "review.txt"
    review.write_text(f"{path}\n")
    ignore_path = tmp_path / "ignore-list.txt"

    exit_code = revert.main([str(review), "--ignore-list", str(ignore_path)])

    assert exit_code == 0
    with Image.open(path) as im:
        assert marker_corner(im) == "top-left"
    assert path.resolve() in ignore_list.load(ignore_path)
    out = capsys.readouterr().out
    assert "Reverted: 1" in out


def test_main_errors_on_missing_review_file(tmp_path):
    with pytest.raises(SystemExit) as exc_info:
        revert.main([str(tmp_path / "nope.txt")])
    assert exc_info.value.code == 2  # argparse.error() exits 2
