"""Deterministic target filename/path computation, including Live Photo pairing.

See docs/design.md Section 5.4. Implemented in docs/tasks.md T2.3.

Returns paths relative to target_root -- this module has no notion of target_root itself,
keeping it pure computation and independently testable (docs/design.md Section 1).
"""

from datetime import datetime
from pathlib import Path

PHOTOS_DIR = "photos"
VIDEO_DIR = "video"
LIVE_PHOTO_DIR = "live_photo"
UNDATED_DIR = "_undated"

SINGLE = "single"
KEY_IMAGE = "key_image"
LIVE_BUNDLE = "live_bundle"


def _top_dir(media_type: str, component: str) -> str:
    if component == KEY_IMAGE:
        return PHOTOS_DIR
    if component == LIVE_BUNDLE:
        return LIVE_PHOTO_DIR
    if component == SINGLE:
        if media_type == "photo":
            return PHOTOS_DIR
        if media_type == "video":
            return VIDEO_DIR
        raise ValueError(f"unexpected media_type {media_type!r} for component=single")
    raise ValueError(f"unknown component {component!r}")


def _date_subdir(date_taken: datetime, is_undated: bool) -> str:
    if is_undated:
        return UNDATED_DIR
    return f"{date_taken:%Y}/{date_taken:%m}"


def _filename(date_taken: datetime, original_stem: str, uuid: str, ext: str) -> str:
    return f"{date_taken:%Y-%m-%d}_{original_stem}_{uuid[:8]}{ext}"


def target_path(
    media_type: str,
    component: str,
    date_taken: datetime,
    is_undated: bool,
    original_stem: str,
    uuid: str,
    ext: str,
) -> Path:
    """Compute the target path for one staged output, relative to target_root.

    `ext` must include the leading dot (e.g. ".HEIC"). Calling this twice with the same
    inputs except for `ext` (e.g. once for a Live Photo's still, once for its .mov) yields
    matching basenames with different extensions -- that's the Live Photo pairing convention,
    and it falls out of this naming scheme without any special-case logic.
    """
    top = _top_dir(media_type, component)
    date_part = _date_subdir(date_taken, is_undated)
    filename = _filename(date_taken, original_stem, uuid, ext)
    return Path(top) / date_part / filename
