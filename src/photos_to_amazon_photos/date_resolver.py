"""Capture-date vs. library-added-fallback heuristic.

See docs/design.md Section 5.2. Implemented in docs/tasks.md T2.2.

Revision history:

- v1 (Milestone 0): compared `date` against `date_added` with a 60-second window, on the theory
  that a `date` close to `date_added` meant Photos had no real capture date and fell back to the
  import timestamp. Validated against 36 real assets at the time -- but that sample didn't
  include recently-synced photos, where "added to library" can legitimately happen within
  seconds of capture via iCloud Photos. On real production libraries this produced false
  positives: genuinely EXIF-dated photos landing in `_undated/` just because they were
  captured and synced quickly. Confirmed at ~79% false-positive rate on a real sample.
- v2 (this version): uses `PhotoInfo.date_original` instead of `date` for the comparison.
  osxphotos sets `date_original` from EXIF at import time, and -- critically -- falls back to
  *exactly* mirroring `date_added` (matching to the microsecond) only when there was no EXIF
  date at all. Real photos with genuine EXIF, even ones synced within seconds of capture, never
  coincidentally match `date_added` to the microsecond. This eliminates the false-positive
  class entirely rather than trying to tune a time-window threshold: verified against a real
  681-asset sample, the "no EXIF" cases cluster at an exact 0.000s gap while every genuine-EXIF
  case (even fast-synced ones) starts at 4.4s and up, with no overlap. UNDATED_THRESHOLD is kept
  small (not turned into an exact-equality check) purely as a safety margin against
  floating-point/timezone-conversion jitter, not because the boundary is expected to matter.
"""

from datetime import datetime, timedelta
from typing import NamedTuple

UNDATED_THRESHOLD = timedelta(seconds=2)

PHOTOS_DATE = "photos_date"
LIBRARY_ADDED = "library_added"


class DateResolution(NamedTuple):
    date_taken: datetime
    date_source: str
    is_undated: bool


def resolve(date: datetime, date_added: datetime | None, date_original: datetime) -> DateResolution:
    if date_added is None:
        date_source = PHOTOS_DATE
    elif abs(date_original - date_added) < UNDATED_THRESHOLD:
        date_source = LIBRARY_ADDED
    else:
        date_source = PHOTOS_DATE

    return DateResolution(
        date_taken=date,
        date_source=date_source,
        is_undated=date_source == LIBRARY_ADDED,
    )
