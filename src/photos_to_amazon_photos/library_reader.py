"""Read-only wrapper around osxphotos.PhotosDB: enumerate and classify assets.

See docs/design.md Section 3 (classification) and Section 5.1 (version selection).
Implemented in docs/tasks.md T2.4.
"""

from collections.abc import Iterator
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import osxphotos

PHOTO = "photo"
VIDEO = "video"
LIVE_PHOTO = "live_photo"


@dataclass(frozen=True)
class AssetView:
    """Everything downstream modules need about one Photos asset, decoupled from osxphotos's
    own object model. `_photo` is kept for the one thing that can't reasonably be flattened
    into simple fields: triggering the actual export (docs/design.md Section 5.1)."""

    uuid: str
    media_type: str  # "photo" | "video" | "live_photo"
    original_filename: str
    hasadjustments: bool
    date: datetime
    date_added: datetime | None
    path: str | None
    path_edited: str | None
    _photo: Any

    def export(
        self,
        dest_dir: str | Path,
        *,
        filename: str | None = None,
        edited: bool = False,
        live_photo: bool = False,
        exiftool: bool = False,
    ) -> list[str]:
        """Thin passthrough to PhotoInfo.export() -- see docs/design.md Section 7 for the
        confirmed call shape. Returns the list of exported file paths (empty if unavailable,
        per docs/design.md Section 5.5 -- callers must not rely on `path`/`ismissing` alone)."""
        return self._photo.export(
            str(dest_dir),
            filename=filename,
            edited=edited,
            live_photo=live_photo,
            exiftool=exiftool,
        )


def classify(photo: Any) -> str:
    """Media type classification -- docs/design.md Section 3."""
    if photo.ismovie:
        return VIDEO
    if photo.live_photo:
        return LIVE_PHOTO
    return PHOTO


def _to_asset_view(photo: Any) -> AssetView:
    return AssetView(
        uuid=photo.uuid,
        media_type=classify(photo),
        original_filename=photo.original_filename,
        hasadjustments=photo.hasadjustments,
        date=photo.date,
        date_added=photo.date_added,
        path=photo.path,
        path_edited=photo.path_edited,
        _photo=photo,
    )


class LibraryReader:
    """Read-only access to one Photos library. Never calls anything on PhotosDB/PhotoInfo that
    mutates the library (FR-2/NFR-5)."""

    def __init__(self, library_path: str | Path):
        self.library_path = str(library_path)
        self._db = osxphotos.PhotosDB(self.library_path)

    def iter_assets(self) -> Iterator[AssetView]:
        for photo in self._db.photos():
            yield _to_asset_view(photo)
