import pytest

from image_quality_detector import ignore_list, quarantine, revert


def test_parse_review_file_skips_blank_lines_and_comments(tmp_path):
    review = tmp_path / "review.txt"
    a = tmp_path / "a.jpg"
    b = tmp_path / "b.jpg"
    review.write_text(f"# header\n\n{a}\n# a comment\n{b}\n\n")

    assert revert.parse_review_file(review) == [a, b]


def test_revert_entries_restores_original_and_consumes_quarantine_copy(tmp_path):
    path = tmp_path / "a.jpg"
    path.write_bytes(b"original bytes")
    dest = quarantine.quarantine_image(path, "blurry")  # now (wrongly) quarantined

    ignore_path = tmp_path / "ignore-list.txt"
    counts = revert.revert_entries([path], ignore_path)

    assert counts[revert.REVERTED] == 1
    assert not dest.exists()  # consumed by the revert
    assert path.read_bytes() == b"original bytes"


def test_revert_entries_adds_to_ignore_list(tmp_path):
    path = tmp_path / "a.jpg"
    path.write_bytes(b"x")
    quarantine.quarantine_image(path, "blurry")

    ignore_path = tmp_path / "ignore-list.txt"
    revert.revert_entries([path], ignore_path)

    assert path.resolve() in ignore_list.load(ignore_path)


def test_revert_entries_without_a_quarantine_copy_still_adds_to_ignore_list(tmp_path):
    path = tmp_path / "never_quarantined.jpg"
    path.write_bytes(b"original bytes")

    ignore_path = tmp_path / "ignore-list.txt"
    counts = revert.revert_entries([path], ignore_path)

    assert counts[revert.NO_QUARANTINE_FOUND] == 1
    assert counts[revert.REVERTED] == 0
    assert path.read_bytes() == b"original bytes"  # untouched
    assert path.resolve() in ignore_list.load(ignore_path)


def test_main_end_to_end(tmp_path, capsys):
    path = tmp_path / "a.jpg"
    path.write_bytes(b"original bytes")
    quarantine.quarantine_image(path, "blurry")

    review = tmp_path / "review.txt"
    review.write_text(f"{path}\n")
    ignore_path = tmp_path / "ignore-list.txt"

    exit_code = revert.main([str(review), "--ignore-list", str(ignore_path)])

    assert exit_code == 0
    assert path.read_bytes() == b"original bytes"
    assert path.resolve() in ignore_list.load(ignore_path)
    out = capsys.readouterr().out
    assert "Reverted: 1" in out


def test_main_errors_on_missing_review_file(tmp_path):
    with pytest.raises(SystemExit) as exc_info:
        revert.main([str(tmp_path / "nope.txt")])
    assert exc_info.value.code == 2  # argparse.error() exits 2
