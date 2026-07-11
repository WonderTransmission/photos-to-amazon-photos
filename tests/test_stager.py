from datetime import datetime
from pathlib import Path

import pytest

from photos_to_amazon_photos import stager, tracking
from photos_to_amazon_photos.library_reader import AssetView

DATE = datetime(2024, 5, 14, 12, 0, 0)
DATE_ADDED = datetime(2024, 5, 15, 8, 0, 0)


class FakePhoto:
    """Minimal stand-in for osxphotos.PhotoInfo, faithfully modeling the one behavior that
    matters here: passing live_photo=True to export() adds the motion file to the result."""

    def __init__(
        self,
        *,
        still=("export.HEIC", b"still bytes"),
        motion=("export.MOV", b"motion bytes"),
        raise_on_export=None,
    ):
        self.still = still
        self.motion = motion
        self.raise_on_export = raise_on_export
        self.export_calls = []

    def export(self, dest_dir, **kwargs):
        self.export_calls.append(dict(dest_dir=dest_dir, **kwargs))
        if self.raise_on_export is not None:
            raise self.raise_on_export
        out = []
        name, content = self.still
        p = Path(dest_dir) / name
        p.write_bytes(content)
        out.append(str(p))
        if kwargs.get("live_photo"):
            name, content = self.motion
            p = Path(dest_dir) / name
            p.write_bytes(content)
            out.append(str(p))
        return out


def make_asset(
    uuid="U1",
    media_type="photo",
    original_filename="IMG_0001.HEIC",
    hasadjustments=False,
    date=DATE,
    date_added=DATE_ADDED,
    date_original=DATE,
    still=("export.HEIC", b"still bytes"),
    motion=("export.MOV", b"motion bytes"),
    raise_on_export=None,
):
    photo = FakePhoto(still=still, motion=motion, raise_on_export=raise_on_export)
    asset = AssetView(
        uuid=uuid,
        media_type=media_type,
        original_filename=original_filename,
        hasadjustments=hasadjustments,
        date=date,
        date_added=date_added,
        date_original=date_original,
        path="/fake/path/" + original_filename,
        path_edited=None,
        _photo=photo,
    )
    return asset, photo


def test_idempotent_rerun_stages_nothing_new(tmp_path):
    target_root = tmp_path / "target"
    tracking_path = target_root / "tracking.csv"
    asset, photo = make_asset()

    summary1 = stager.run("/fake/lib", target_root, tracking_path, assets=[asset])
    assert summary1.counts[("photo", stager.COPIED)] == 1
    assert len(photo.export_calls) == 1

    summary2 = stager.run("/fake/lib", target_root, tracking_path, assets=[asset])
    assert summary2.counts[("photo", stager.COPIED)] == 0
    assert summary2.counts[("photo", stager.SKIPPED_COPIED)] == 1
    assert len(photo.export_calls) == 1  # export() not called again


def test_deleted_staged_file_not_restaged(tmp_path):
    target_root = tmp_path / "target"
    tracking_path = target_root / "tracking.csv"
    asset, photo = make_asset()

    stager.run("/fake/lib", target_root, tracking_path, assets=[asset])
    row = tracking.load(tracking_path).get(asset.uuid, tracking.SINGLE)
    staged_file = target_root / row.target_relative_path
    assert staged_file.exists()
    staged_file.unlink()  # simulate: user deleted it after uploading to Amazon Photos

    summary2 = stager.run("/fake/lib", target_root, tracking_path, assets=[asset])
    assert summary2.counts[("photo", stager.SKIPPED_COPIED)] == 1
    assert not staged_file.exists()  # confirmed NOT recreated
    assert len(photo.export_calls) == 1


def test_manually_ignored_row_not_restaged(tmp_path):
    target_root = tmp_path / "target"
    tracking_path = target_root / "tracking.csv"
    asset, photo = make_asset()

    # Simulate a user hand-editing tracking.csv per FR-9's documented workflow, without the
    # tool ever having run first.
    index = tracking.TrackingIndex()
    index.upsert(
        tracking.TrackingRow(
            photo_uuid=asset.uuid,
            component=tracking.SINGLE,
            status=tracking.IGNORED,
            ignore_reason="inappropriate",
            media_type="photo",
        )
    )
    index.flush(tracking_path)

    summary = stager.run("/fake/lib", target_root, tracking_path, assets=[asset])
    assert summary.counts[("photo", stager.SKIPPED_IGNORED)] == 1
    assert len(photo.export_calls) == 0
    assert not target_root.joinpath("photos").exists()


def test_failure_marks_error_and_continues(tmp_path):
    target_root = tmp_path / "target"
    tracking_path = target_root / "tracking.csv"
    failing_asset, _ = make_asset(uuid="FAIL", raise_on_export=RuntimeError("boom"))
    good_asset, _ = make_asset(uuid="GOOD")

    summary = stager.run(
        "/fake/lib", target_root, tracking_path, assets=[failing_asset, good_asset]
    )

    assert summary.counts[("photo", stager.ERROR)] == 1
    assert summary.counts[("photo", stager.COPIED)] == 1

    index = tracking.load(tracking_path)
    fail_row = index.get("FAIL", tracking.SINGLE)
    assert fail_row.status == tracking.ERROR
    assert "boom" in fail_row.notes

    good_row = index.get("GOOD", tracking.SINGLE)
    assert good_row.status == tracking.COPIED


def test_live_photo_stages_key_image_and_live_bundle_with_pairing(tmp_path):
    target_root = tmp_path / "target"
    tracking_path = target_root / "tracking.csv"
    asset, photo = make_asset(
        uuid="LP1", media_type="live_photo", original_filename="IMG_9999.HEIC"
    )

    summary = stager.run("/fake/lib", target_root, tracking_path, assets=[asset])

    assert summary.counts[("live_photo", stager.COPIED)] == 2
    assert len(photo.export_calls) == 2
    assert sorted(c["live_photo"] for c in photo.export_calls) == [False, True]

    index = tracking.load(tracking_path)
    key_row = index.get("LP1", tracking.KEY_IMAGE)
    bundle_row = index.get("LP1", tracking.LIVE_BUNDLE)
    assert key_row.status == tracking.COPIED
    assert bundle_row.status == tracking.COPIED
    assert key_row.target_relative_path.startswith("photos/")
    assert bundle_row.target_relative_path.startswith("live_photo/")

    bundle_still = target_root / bundle_row.target_relative_path
    assert bundle_still.exists()
    paired_motion = bundle_still.with_suffix(".MOV")
    assert paired_motion.exists()


def test_live_photo_ignore_propagates_to_both_components(tmp_path):
    target_root = tmp_path / "target"
    tracking_path = target_root / "tracking.csv"

    # Only the key_image row was hand-marked ignored -- the stager should still treat the
    # whole asset as ignored (docs/design.md Section 4).
    index = tracking.TrackingIndex()
    index.upsert(
        tracking.TrackingRow(
            photo_uuid="LP1",
            component=tracking.KEY_IMAGE,
            status=tracking.IGNORED,
            ignore_reason="inappropriate",
            media_type="live_photo",
        )
    )
    index.flush(tracking_path)

    asset, photo = make_asset(uuid="LP1", media_type="live_photo")
    summary = stager.run("/fake/lib", target_root, tracking_path, assets=[asset])

    assert summary.counts[("live_photo", stager.SKIPPED_IGNORED)] == 2
    assert len(photo.export_calls) == 0

    reloaded = tracking.load(tracking_path)
    bundle_row = reloaded.get("LP1", tracking.LIVE_BUNDLE)
    assert bundle_row is not None
    assert bundle_row.status == tracking.IGNORED
    assert bundle_row.ignore_reason == "inappropriate"


def test_empty_export_result_marks_error_not_available(tmp_path):
    target_root = tmp_path / "target"
    tracking_path = target_root / "tracking.csv"

    class EmptyExportPhoto:
        def export(self, dest_dir, **kwargs):
            return []

    asset = AssetView(
        uuid="U1",
        media_type="photo",
        original_filename="IMG_0001.HEIC",
        hasadjustments=False,
        date=DATE,
        date_added=None,
        date_original=DATE,
        path=None,
        path_edited=None,
        _photo=EmptyExportPhoto(),
    )
    summary = stager.run("/fake/lib", target_root, tracking_path, assets=[asset])
    assert summary.counts[("photo", stager.ERROR)] == 1
    row = tracking.load(tracking_path).get("U1", tracking.SINGLE)
    assert row.notes == "not available locally"


def test_dry_run_writes_nothing(tmp_path):
    target_root = tmp_path / "target"
    tracking_path = target_root / "tracking.csv"
    asset, photo = make_asset()

    summary = stager.run("/fake/lib", target_root, tracking_path, dry_run=True, assets=[asset])

    assert summary.counts[("photo", stager.WOULD_STAGE)] == 1
    assert len(photo.export_calls) == 0
    assert not target_root.exists()
    assert not tracking_path.exists()


def test_orphaned_staged_file_with_matching_content_is_adopted_not_errored(tmp_path):
    """Found via the T4.1 interrupt test: a crash can leave a file successfully moved into
    place with no tracking row ever flushed for it. Resume must adopt matching content rather
    than erroring forever on a collision -- otherwise the tool never reaches eventual
    completion for that asset."""
    target_root = tmp_path / "target"
    tracking_path = target_root / "tracking.csv"
    target_root.mkdir(parents=True)
    asset, _ = make_asset(uuid="U1")

    # Stage directly, bypassing all tracking bookkeeping -- simulates the file having been
    # moved into place right before a SIGKILL, with no row ever recorded.
    orphan_row = stager._stage_component(
        asset, tracking.SINGLE, target_root, exiftool_available=False, library_path_str="/fake/lib"
    )
    assert (target_root / orphan_row.target_relative_path).exists()

    # Resume with a fresh AssetView/FakePhoto for the same uuid -- matching how a real
    # osxphotos re-export independently reproduces identical bytes for the same asset
    # (verified directly against the real spike library: export() is deterministic given the
    # same settings).
    asset2, photo2 = make_asset(uuid="U1")
    summary = stager.run("/fake/lib", target_root, tracking_path, assets=[asset2])

    assert summary.counts[("photo", stager.COPIED)] == 1
    assert summary.counts[("photo", stager.ERROR)] == 0
    row = tracking.load(tracking_path).get("U1", tracking.SINGLE)
    assert row.status == tracking.COPIED
    assert row.checksum_sha256 == orphan_row.checksum_sha256


def test_genuine_collision_with_different_content_still_errors(tmp_path):
    target_root = tmp_path / "target"
    target_root.mkdir(parents=True)
    asset1, _ = make_asset(uuid="U1", still=("export.HEIC", b"content A"))
    stager._stage_component(
        asset1, tracking.SINGLE, target_root, exiftool_available=False, library_path_str="/fake/lib"
    )

    asset2, _ = make_asset(uuid="U1", still=("export.HEIC", b"content B, genuinely different"))
    with pytest.raises(FileExistsError, match="different content"):
        stager._stage_component(
            asset2,
            tracking.SINGLE,
            target_root,
            exiftool_available=False,
            library_path_str="/fake/lib",
        )
