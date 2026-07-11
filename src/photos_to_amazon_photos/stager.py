"""Per-asset orchestration: skip-check -> export -> checksum -> tracking update.

See docs/design.md Section 9 (error handling) and Section 5.5 (availability check).
Implemented in docs/tasks.md T3.1.
"""

import hashlib
import logging
import shutil
import tempfile
from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from photos_to_amazon_photos import date_resolver, library_reader, namer, tracking
from photos_to_amazon_photos.library_reader import AssetView, LibraryReader
from photos_to_amazon_photos.tracking import TrackingRow

log = logging.getLogger(__name__)

FLUSH_EVERY = 200
PROGRESS_LOG_INTERVAL_PERCENT = 5
_MOTION_EXTENSIONS = {".mov", ".mp4"}

COPIED = "copied"
WOULD_STAGE = "would_stage"
SKIPPED_COPIED = "skipped_copied"
SKIPPED_IGNORED = "skipped_ignored"
ERROR = "error"


class AssetUnavailable(Exception):
    """Raised when export() returns no files -- see docs/design.md Section 5.5. Not a bug in
    this tool; the asset just isn't available locally right now."""


@dataclass
class RunSummary:
    counts: Counter = field(default_factory=Counter)

    def add(self, media_type: str, outcome: str, n: int = 1) -> None:
        self.counts[(media_type, outcome)] += n

    def total(self) -> int:
        return sum(self.counts.values())


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _live_photo_ignore_reason(index: tracking.TrackingIndex, uuid: str) -> str | None:
    """If either of a Live Photo's two rows is already marked ignored, the whole asset is
    treated as ignored -- docs/design.md Section 4: 'done as one logical operation by the
    stager', so a user doesn't have to remember to mark both rows themselves."""
    for component in (tracking.KEY_IMAGE, tracking.LIVE_BUNDLE):
        row = index.get(uuid, component)
        if row is not None and row.status == tracking.IGNORED:
            return row.ignore_reason
    return None


def _stage_component(
    asset: AssetView,
    component: str,
    target_root: Path,
    exiftool_available: bool,
    library_path_str: str,
) -> TrackingRow:
    date_taken, date_source, is_undated = date_resolver.resolve(
        asset.date, asset.date_added, asset.date_original
    )
    original_stem = Path(asset.original_filename).stem
    want_motion = component == tracking.LIVE_BUNDLE

    tmp_dir = Path(tempfile.mkdtemp(dir=target_root, prefix=".staging-"))
    try:
        exported = asset.export(
            tmp_dir,
            edited=asset.hasadjustments,
            live_photo=want_motion,
            exiftool=exiftool_available,
        )
        if not exported:
            raise AssetUnavailable("not available locally")

        moved = []  # (rel_path, size, checksum, is_motion)
        for p in exported:
            ext = Path(p).suffix
            rel = namer.target_path(
                asset.media_type, component, date_taken, is_undated, original_stem, asset.uuid, ext
            )
            final_path = target_root / rel
            final_path.parent.mkdir(parents=True, exist_ok=True)
            is_motion = ext.lower() in _MOTION_EXTENSIONS

            if final_path.exists():
                # The deterministic path is already occupied. This legitimately happens after
                # a crash: a prior run can move a file into place and then be killed before its
                # tracking row is ever flushed (found via docs/tasks.md T4.1's interrupt test).
                # Since the path is a pure function of (media_type, component, date, uuid, ext),
                # matching content here means "a previous run already finished this" -- adopt
                # it rather than erroring, so resume actually reaches eventual completion.
                # Content that DIFFERS is a genuine collision and still fails loudly rather
                # than silently overwriting (docs/design.md Section 5.4).
                existing_checksum = _sha256(final_path)
                new_checksum = _sha256(Path(p))
                if existing_checksum != new_checksum:
                    raise FileExistsError(
                        f"target already exists with different content: {final_path}"
                    )
                size = final_path.stat().st_size
                checksum = existing_checksum
                Path(p).unlink()
            else:
                shutil.move(str(p), str(final_path))
                size = final_path.stat().st_size
                checksum = _sha256(final_path)

            moved.append((rel, size, checksum, is_motion))

        if len(moved) == 1:
            rel_path, file_size, checksum, _ = moved[0]
        else:
            non_motion = [m for m in moved if not m[3]]
            rel_path, file_size, checksum, _ = non_motion[0] if non_motion else moved[0]

        return TrackingRow(
            photo_uuid=asset.uuid,
            component=component,
            source_library_path=library_path_str,
            original_filename=asset.original_filename,
            target_relative_path=str(rel_path),
            date_taken=date_taken,
            date_source=date_source,
            date_added_to_library=asset.date_added,
            timestamp_processed=datetime.now(),
            file_size_bytes=file_size,
            checksum_sha256=checksum,
            is_edited_version=asset.hasadjustments,
            media_type=asset.media_type,
            status=tracking.COPIED,
        )
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


def run(
    library_path: str | Path,
    target_root: str | Path,
    tracking_path: str | Path,
    *,
    dry_run: bool = False,
    assets: Iterable[AssetView] | None = None,
) -> RunSummary:
    """Stage one Photos library into target_root. `assets` is an injection point for tests --
    production callers (cli.py) never pass it, letting this open a real LibraryReader."""
    target_root = Path(target_root)
    library_path_str = str(library_path)
    tracking_index = tracking.load(tracking_path)
    summary = RunSummary()

    exiftool_available = shutil.which("exiftool") is not None
    if exiftool_available:
        log.info("exiftool found -- Photos-only metadata (keywords/persons) will be embedded")
    else:
        log.warning(
            "exiftool not found on PATH -- keywords/persons will not be embedded; "
            "capture date/GPS/camera EXIF is still preserved"
        )

    if not dry_run:
        target_root.mkdir(parents=True, exist_ok=True)

    if assets is None:
        assets = LibraryReader(library_path_str).iter_assets()
    # Materialized rather than iterated lazily so total_assets is known for progress logging --
    # cheap in practice, since osxphotos's own db.photos() call (what iter_assets() wraps) has
    # already loaded every asset's metadata into memory internally regardless of how it's
    # consumed here; this doesn't add a new memory cost.
    assets = list(assets)
    total_assets = len(assets)

    processed_count = 0
    last_logged_percent = 0
    for asset_index, asset in enumerate(assets, start=1):
        if asset.media_type == library_reader.LIVE_PHOTO:
            components = [tracking.KEY_IMAGE, tracking.LIVE_BUNDLE]
            ignore_reason = _live_photo_ignore_reason(tracking_index, asset.uuid)
        else:
            components = [tracking.SINGLE]
            ignore_reason = None

        for component in components:
            if ignore_reason is not None:
                existing = tracking_index.get(asset.uuid, component)
                if not dry_run and (existing is None or existing.status != tracking.IGNORED):
                    tracking_index.upsert(
                        TrackingRow(
                            photo_uuid=asset.uuid,
                            component=component,
                            source_library_path=library_path_str,
                            original_filename=asset.original_filename,
                            date_added_to_library=asset.date_added,
                            timestamp_processed=datetime.now(),
                            media_type=asset.media_type,
                            status=tracking.IGNORED,
                            ignore_reason=ignore_reason,
                        )
                    )
                summary.add(asset.media_type, SKIPPED_IGNORED)
                continue

            decision = tracking_index.decision(asset.uuid, component)
            if isinstance(decision, tracking.Skip):
                summary.add(asset.media_type, f"skipped_{decision.reason}")
                continue

            if dry_run:
                summary.add(asset.media_type, WOULD_STAGE)
                continue

            processed_count += 1
            try:
                row = _stage_component(
                    asset, component, target_root, exiftool_available, library_path_str
                )
                tracking_index.upsert(row)
                summary.add(asset.media_type, COPIED)
            except Exception as e:
                log.error("failed to stage %s (%s): %s", asset.uuid, component, e)
                tracking_index.upsert(
                    TrackingRow(
                        photo_uuid=asset.uuid,
                        component=component,
                        source_library_path=library_path_str,
                        original_filename=asset.original_filename,
                        date_added_to_library=asset.date_added,
                        timestamp_processed=datetime.now(),
                        media_type=asset.media_type,
                        status=tracking.ERROR,
                        notes=str(e)[:500],
                    )
                )
                summary.add(asset.media_type, ERROR)

            if processed_count % FLUSH_EVERY == 0:
                tracking_index.flush(tracking_path)
                log.info("progress: %d processed, tracking file flushed", processed_count)

        # Percentage-of-library progress, independent of FLUSH_EVERY above: that one only
        # counts actual staging attempts, which barely moves on a mostly-idempotent re-run
        # (nearly everything Skip()s). This counts assets iterated regardless of outcome, so it
        # still gives useful feedback -- "still working, not hung" -- on that kind of run too.
        # Logged at fixed percentage milestones rather than a fixed asset count so the number of
        # log lines stays reasonable (~20) regardless of library size, from a few hundred assets
        # to tens of thousands.
        if total_assets:
            percent = (asset_index * 100) // total_assets
            milestone = (percent // PROGRESS_LOG_INTERVAL_PERCENT) * PROGRESS_LOG_INTERVAL_PERCENT
            if milestone > last_logged_percent:
                last_logged_percent = milestone
                log.info("Progress: %d%% (%d/%d assets)", milestone, asset_index, total_assets)

    if not dry_run:
        tracking_index.flush(tracking_path)

    return summary
