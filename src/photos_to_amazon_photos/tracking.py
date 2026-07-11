"""tracking.csv read/write, idempotency index, atomic flush.

See docs/design.md Section 4 (schema) and Section 6 (idempotency/crash safety).
Implemented in docs/tasks.md T2.1.
"""

import csv
import os
import tempfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import NamedTuple

SINGLE = "single"
KEY_IMAGE = "key_image"
LIVE_BUNDLE = "live_bundle"

COPIED = "copied"
IGNORED = "ignored"
ERROR = "error"

FIELDNAMES = [
    "photo_uuid",
    "component",
    "source_library_path",
    "original_filename",
    "target_relative_path",
    "date_taken",
    "date_source",
    "date_added_to_library",
    "timestamp_processed",
    "file_size_bytes",
    "checksum_sha256",
    "is_edited_version",
    "media_type",
    "status",
    "ignore_reason",
    "notes",
]


def _dt_to_str(dt: datetime | None) -> str:
    return "" if dt is None else dt.isoformat()


def _str_to_dt(s: str) -> datetime | None:
    return datetime.fromisoformat(s) if s else None


def _str_to_int(s: str) -> int | None:
    return int(s) if s else None


@dataclass
class TrackingRow:
    photo_uuid: str
    component: str
    source_library_path: str = ""
    original_filename: str = ""
    target_relative_path: str = ""
    date_taken: datetime | None = None
    date_source: str = ""
    date_added_to_library: datetime | None = None
    timestamp_processed: datetime | None = None
    file_size_bytes: int | None = None
    checksum_sha256: str = ""
    is_edited_version: bool = False
    media_type: str = ""
    status: str = ""
    ignore_reason: str = ""
    notes: str = ""

    @property
    def key(self) -> tuple[str, str]:
        return (self.photo_uuid, self.component)

    def to_csv_dict(self) -> dict[str, str]:
        return {
            "photo_uuid": self.photo_uuid,
            "component": self.component,
            "source_library_path": self.source_library_path,
            "original_filename": self.original_filename,
            "target_relative_path": self.target_relative_path,
            "date_taken": _dt_to_str(self.date_taken),
            "date_source": self.date_source,
            "date_added_to_library": _dt_to_str(self.date_added_to_library),
            "timestamp_processed": _dt_to_str(self.timestamp_processed),
            "file_size_bytes": "" if self.file_size_bytes is None else str(self.file_size_bytes),
            "checksum_sha256": self.checksum_sha256,
            "is_edited_version": "true" if self.is_edited_version else "false",
            "media_type": self.media_type,
            "status": self.status,
            "ignore_reason": self.ignore_reason,
            "notes": self.notes,
        }

    @classmethod
    def from_csv_dict(cls, row: dict[str, str]) -> TrackingRow:
        return cls(
            photo_uuid=row["photo_uuid"],
            component=row["component"],
            source_library_path=row.get("source_library_path") or "",
            original_filename=row.get("original_filename") or "",
            target_relative_path=row.get("target_relative_path") or "",
            date_taken=_str_to_dt(row.get("date_taken") or ""),
            date_source=row.get("date_source") or "",
            date_added_to_library=_str_to_dt(row.get("date_added_to_library") or ""),
            timestamp_processed=_str_to_dt(row.get("timestamp_processed") or ""),
            file_size_bytes=_str_to_int(row.get("file_size_bytes") or ""),
            checksum_sha256=row.get("checksum_sha256") or "",
            is_edited_version=(row.get("is_edited_version") or "").strip().lower() == "true",
            media_type=row.get("media_type") or "",
            status=row.get("status") or "",
            ignore_reason=row.get("ignore_reason") or "",
            notes=row.get("notes") or "",
        )


class Skip(NamedTuple):
    reason: str


class Process(NamedTuple):
    pass


Decision = Skip | Process


class TrackingIndex:
    """In-memory index of tracking rows, keyed by (photo_uuid, component). See load()/flush()
    for disk I/O -- this class itself does no I/O."""

    def __init__(self, rows: dict[tuple[str, str], TrackingRow] | None = None):
        self._rows: dict[tuple[str, str], TrackingRow] = dict(rows or {})

    def __len__(self) -> int:
        return len(self._rows)

    def get(self, photo_uuid: str, component: str) -> TrackingRow | None:
        return self._rows.get((photo_uuid, component))

    def decision(self, photo_uuid: str, component: str) -> Decision:
        """Implements FR-7's skip/process rules."""
        row = self.get(photo_uuid, component)
        if row is None:
            return Process()
        if row.status == IGNORED:
            return Skip("ignored")
        if row.status == COPIED and row.timestamp_processed is not None:
            return Skip("copied")
        return Process()

    def upsert(self, row: TrackingRow) -> None:
        self._rows[row.key] = row

    def remove(self, photo_uuid: str, component: str) -> None:
        """Remove a row, if present -- e.g. to force reprocessing on the next run (used by
        remediation tooling; not part of normal staging, which never removes rows). No-op if
        the row doesn't exist."""
        self._rows.pop((photo_uuid, component), None)

    def rows(self) -> list[TrackingRow]:
        return list(self._rows.values())

    def flush(self, path: Path) -> None:
        """Atomic write-temp-then-os.replace. On any failure, the temp file is removed and the
        file at `path` (if it existed) is left completely untouched -- see docs/design.md
        Section 6."""
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_name = tempfile.mkstemp(dir=path.parent, prefix=".tracking-", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=FIELDNAMES)
                writer.writeheader()
                for row in self._rows.values():
                    writer.writerow(row.to_csv_dict())
            os.replace(tmp_name, path)
        except BaseException:
            os.unlink(tmp_name)
            raise


def load(path: Path) -> TrackingIndex:
    path = Path(path)
    if not path.exists():
        return TrackingIndex()
    with path.open(newline="") as f:
        reader = csv.DictReader(f)
        rows = {}
        for raw_row in reader:
            row = TrackingRow.from_csv_dict(raw_row)
            rows[row.key] = row
    return TrackingIndex(rows)
