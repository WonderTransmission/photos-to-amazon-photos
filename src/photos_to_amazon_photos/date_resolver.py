"""Capture-date vs. library-added-fallback heuristic.

See docs/design.md Section 5.2. Implemented in docs/tasks.md T2.2.

osxphotos exposes no flag distinguishing a true, asset-specific capture date from a
library-import fallback. This heuristic infers it by comparing an asset's `date` against its
`date_added`: if they're within UNDATED_THRESHOLD of each other, `date` looks like it's just the
import timestamp, not a real capture date. UNDATED_THRESHOLD=60s was validated in the Milestone 0
spike (docs/design.md Section 5.2) against 36 real assets with independent ground truth.
"""

from datetime import datetime, timedelta
from typing import NamedTuple

UNDATED_THRESHOLD = timedelta(seconds=60)

PHOTOS_DATE = "photos_date"
LIBRARY_ADDED = "library_added"


class DateResolution(NamedTuple):
    date_taken: datetime
    date_source: str
    is_undated: bool


def resolve(date: datetime, date_added: datetime | None) -> DateResolution:
    if date_added is None:
        date_source = PHOTOS_DATE
    elif abs(date - date_added) < UNDATED_THRESHOLD:
        date_source = LIBRARY_ADDED
    else:
        date_source = PHOTOS_DATE

    return DateResolution(
        date_taken=date,
        date_source=date_source,
        is_undated=date_source == LIBRARY_ADDED,
    )
