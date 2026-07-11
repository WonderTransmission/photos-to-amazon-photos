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
- v2 (Milestone 0 fix, superseded): uses `PhotoInfo.date_original` instead of `date` for the
  comparison, with a 2-second threshold. `date_original` is set from EXIF at import time and,
  critically, falls back to *exactly* mirroring `date_added` (matching to the microsecond) only
  when there was no EXIF date at all. Validated at the time against a 681-asset sample of
  *locally available* assets only -- but a follow-up verification run (using
  `scripts/verify_date_heuristic_fix.sh` against the same library's full 10,267 assets, not
  just the available subset) found the 2-second window was still too loose: 64 assets --
  disproportionately videos, and exclusively assets not stored locally -- have genuine EXIF
  dates with a real (non-import-fallback) gap as small as 0.348s, apparently because cloud-only
  synced metadata goes through a faster/lighter processing path than a fully-downloaded local
  import. A 2-second window caught some of these as false positives, the same failure mode as
  v1 just with a much smaller blast radius.
- v3 (this version): same signal (`date_original` vs. `date_added`), but the threshold is
  dropped to 100 milliseconds. The real distinguishing signal was never "how close," it's
  "exact microsecond-precision copy vs. a genuinely independent value" -- verified across the
  *entire* 10,267-asset library (not just the locally-available subset): every single
  known-no-EXIF case sits at an exact 0.000s gap, and every single known-has-EXIF case, even the
  fast cloud-sync ones, sits at 0.348s or more. 100ms leaves a >3x safety margin below that
  floor while still being comfortably above 0, guarding against exact-equality brittleness
  (e.g. serialization/rounding edge cases) without reintroducing a window wide enough to catch
  real data.
"""

from datetime import datetime, timedelta
from typing import NamedTuple

UNDATED_THRESHOLD = timedelta(milliseconds=100)

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
