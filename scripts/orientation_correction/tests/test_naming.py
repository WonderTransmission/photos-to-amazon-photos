from pathlib import Path

from orientation_correction import naming


def test_backup_path_for_appends_orig_and_timestamp():
    original = Path("/photos/2003/02/IMG_1234.JPG")
    backup = naming.backup_path_for(original, "20260715T120000")
    assert backup == Path("/photos/2003/02/IMG_1234.JPG.orig.20260715T120000")


def test_is_backup_file_recognizes_what_backup_path_for_produces():
    original = Path("/photos/IMG_1234.JPG")
    backup = naming.backup_path_for(original, "20260715T120000")
    assert naming.is_backup_file(backup) is True
    assert naming.is_backup_file(original) is False


def test_is_backup_file_rejects_lookalikes():
    # Must not false-positive on a real filename that happens to contain ".orig." without a
    # well-formed timestamp suffix, or on a plain image file.
    assert naming.is_backup_file(Path("vacation.orig.notes.jpg")) is False
    assert naming.is_backup_file(Path("IMG_1234.JPG")) is False


def test_find_existing_backup_none_when_absent(tmp_path):
    original = tmp_path / "a.jpg"
    original.write_bytes(b"x")
    assert naming.find_existing_backup(original) is None


def test_find_existing_backup_finds_it(tmp_path):
    original = tmp_path / "a.jpg"
    original.write_bytes(b"x")
    backup = naming.backup_path_for(original, "20260715T120000")
    backup.write_bytes(b"original bytes")

    assert naming.find_existing_backup(original) == backup


def test_find_existing_backup_returns_most_recent(tmp_path):
    original = tmp_path / "a.jpg"
    original.write_bytes(b"x")
    older = naming.backup_path_for(original, "20260101T000000")
    newer = naming.backup_path_for(original, "20260715T120000")
    older.write_bytes(b"older")
    newer.write_bytes(b"newer")

    assert naming.find_existing_backup(original) == newer


def test_find_existing_backup_does_not_match_a_different_file(tmp_path):
    (tmp_path / "a.jpg").write_bytes(b"x")
    other_backup = naming.backup_path_for(tmp_path / "b.jpg", "20260715T120000")
    other_backup.write_bytes(b"x")

    assert naming.find_existing_backup(tmp_path / "a.jpg") is None
