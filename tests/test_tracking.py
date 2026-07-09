from datetime import datetime

import pytest

from photos_to_amazon_photos.tracking import (
    Process,
    Skip,
    TrackingIndex,
    TrackingRow,
    load,
)

NOW = datetime(2026, 7, 10, 9, 30, 0)


def make_row(uuid="U1", component="single", status="", timestamp_processed=None, **kw):
    return TrackingRow(
        photo_uuid=uuid,
        component=component,
        status=status,
        timestamp_processed=timestamp_processed,
        **kw,
    )


def test_load_missing_file_returns_empty_index(tmp_path):
    index = load(tmp_path / "does-not-exist.csv")
    assert len(index) == 0


def test_decision_no_row_is_process():
    index = TrackingIndex()
    assert index.decision("U1", "single") == Process()


def test_decision_copied_with_timestamp_is_skip():
    index = TrackingIndex()
    index.upsert(make_row(status="copied", timestamp_processed=NOW))
    assert index.decision("U1", "single") == Skip("copied")


def test_decision_copied_without_timestamp_is_process():
    # Malformed/corrupt row -- can't be trusted, so it's reprocessed rather than trusted as done.
    index = TrackingIndex()
    index.upsert(make_row(status="copied", timestamp_processed=None))
    assert index.decision("U1", "single") == Process()


def test_decision_ignored_is_skip_regardless_of_timestamp():
    index = TrackingIndex()
    index.upsert(make_row(status="ignored"))
    assert index.decision("U1", "single") == Skip("ignored")


def test_decision_error_is_process():
    index = TrackingIndex()
    index.upsert(make_row(status="error", timestamp_processed=NOW))
    assert index.decision("U1", "single") == Process()


def test_decision_is_scoped_to_uuid_and_component():
    index = TrackingIndex()
    index.upsert(
        make_row(uuid="U1", component="key_image", status="copied", timestamp_processed=NOW)
    )
    assert index.decision("U1", "key_image") == Skip("copied")
    assert index.decision("U1", "live_bundle") == Process()
    assert index.decision("U2", "key_image") == Process()


def test_flush_then_load_round_trips(tmp_path):
    path = tmp_path / "tracking.csv"
    index = TrackingIndex()
    index.upsert(
        TrackingRow(
            photo_uuid="U1",
            component="single",
            source_library_path="/Volumes/Drive/Lib.photoslibrary",
            original_filename="IMG_1234.HEIC",
            target_relative_path="photos/2024/05/2024-05-14_IMG_1234_a1b2c3d4.HEIC",
            date_taken=datetime(2024, 5, 14, 12, 0, 0),
            date_source="photos_date",
            date_added_to_library=datetime(2024, 5, 15, 8, 0, 0),
            timestamp_processed=NOW,
            file_size_bytes=1234567,
            checksum_sha256="abc123",
            is_edited_version=True,
            media_type="photo",
            status="copied",
            ignore_reason="",
            notes="",
        )
    )
    index.upsert(
        TrackingRow(
            photo_uuid="U2",
            component="single",
            status="ignored",
            ignore_reason="inappropriate",
            media_type="photo",
        )
    )
    index.flush(path)

    reloaded = load(path)
    assert len(reloaded) == 2

    row1 = reloaded.get("U1", "single")
    assert row1.original_filename == "IMG_1234.HEIC"
    assert row1.date_taken == datetime(2024, 5, 14, 12, 0, 0)
    assert row1.date_added_to_library == datetime(2024, 5, 15, 8, 0, 0)
    assert row1.timestamp_processed == NOW
    assert row1.file_size_bytes == 1234567
    assert row1.is_edited_version is True
    assert row1.status == "copied"

    row2 = reloaded.get("U2", "single")
    assert row2.status == "ignored"
    assert row2.ignore_reason == "inappropriate"
    assert row2.is_edited_version is False
    assert row2.date_taken is None


def test_existing_file_loads_correctly_and_populates_decisions(tmp_path):
    path = tmp_path / "tracking.csv"
    index = TrackingIndex()
    index.upsert(make_row(uuid="U1", status="copied", timestamp_processed=NOW))
    index.flush(path)

    reloaded = load(path)
    assert reloaded.decision("U1", "single") == Skip("copied")


def test_flush_is_atomic_original_untouched_on_failure(tmp_path, monkeypatch):
    path = tmp_path / "tracking.csv"

    # Establish a known-good pre-existing file.
    original_index = TrackingIndex()
    original_index.upsert(make_row(uuid="ORIGINAL", status="copied", timestamp_processed=NOW))
    original_index.flush(path)
    original_content = path.read_text()

    # Now attempt a flush that fails partway through writing.
    failing_index = TrackingIndex()
    failing_index.upsert(make_row(uuid="U1", status="copied", timestamp_processed=NOW))
    failing_index.upsert(make_row(uuid="U2", status="copied", timestamp_processed=NOW))

    import csv as csv_module

    call_count = {"n": 0}
    real_writerow = csv_module.DictWriter.writerow

    def flaky_writerow(self, rowdict):
        call_count["n"] += 1
        if call_count["n"] == 2:
            raise RuntimeError("simulated interruption")
        return real_writerow(self, rowdict)

    monkeypatch.setattr(csv_module.DictWriter, "writerow", flaky_writerow)

    with pytest.raises(RuntimeError, match="simulated interruption"):
        failing_index.flush(path)

    # Original file must be byte-for-byte untouched.
    assert path.read_text() == original_content
    # No leftover temp files.
    assert list(tmp_path.glob(".tracking-*.tmp")) == []


def test_flush_creates_target_directory_if_missing(tmp_path):
    path = tmp_path / "nested" / "tracking.csv"
    index = TrackingIndex()
    index.upsert(make_row(uuid="U1"))
    index.flush(path)
    assert path.exists()
