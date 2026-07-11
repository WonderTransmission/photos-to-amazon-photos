from datetime import datetime, timedelta

from photos_to_amazon_photos.date_resolver import (
    LIBRARY_ADDED,
    PHOTOS_DATE,
    UNDATED_THRESHOLD,
    resolve,
)

BASE = datetime(2024, 5, 14, 12, 0, 0)


def test_no_date_added_trusts_date_as_is():
    result = resolve(BASE, None, BASE)
    assert result.date_taken == BASE
    assert result.date_source == PHOTOS_DATE
    assert result.is_undated is False


def test_date_original_equals_date_added_is_undated():
    # The real "no EXIF" signature: date_original mirrors date_added exactly.
    result = resolve(BASE, BASE, BASE)
    assert result.date_source == LIBRARY_ADDED
    assert result.is_undated is True


def test_date_original_far_from_date_added_is_trusted():
    date_added = BASE - timedelta(days=400)
    result = resolve(BASE, date_added, BASE)
    assert result.date_source == PHOTOS_DATE
    assert result.is_undated is False


def test_boundary_exactly_at_threshold_is_not_undated():
    # Strictly-less-than comparison: a diff exactly equal to the threshold should NOT count
    # as an import-time fallback.
    date_added = BASE - UNDATED_THRESHOLD
    result = resolve(BASE, date_added, BASE)
    assert result.date_source == PHOTOS_DATE
    assert result.is_undated is False


def test_boundary_just_inside_threshold_is_undated():
    date_added = BASE - (UNDATED_THRESHOLD - timedelta(milliseconds=1))
    result = resolve(BASE, date_added, BASE)
    assert result.date_source == LIBRARY_ADDED
    assert result.is_undated is True


def test_result_is_tuple_unpackable():
    date_taken, date_source, is_undated = resolve(BASE, None, BASE)
    assert date_taken == BASE
    assert date_source == PHOTOS_DATE
    assert is_undated is False


def test_date_taken_uses_date_not_date_original():
    # date_taken should reflect Photos' current `date` (which may be user-corrected), not
    # necessarily date_original -- they're allowed to differ, and date_taken tracks `date`.
    date_original = BASE - timedelta(days=1000)  # a very different "original" EXIF value
    result = resolve(BASE, BASE - timedelta(days=1), date_original)
    assert result.date_taken == BASE


def test_fast_icloud_sync_with_real_exif_is_not_undated():
    """Regression test for a real production bug: a photo captured and synced via iCloud
    Photos within seconds can have `date` very close to `date_added`, even though it has a
    completely legitimate embedded EXIF capture date. The old heuristic (comparing `date` to
    `date_added` with a 60s window) misclassified these as undated -- confirmed at a ~79%
    false-positive rate on a real library. Using `date_original` fixes it: real EXIF dates
    never coincidentally match `date_added` to the microsecond, even when synced fast."""
    capture_time = datetime(2018, 6, 9, 21, 8, 21, 429000)
    added_time = capture_time + timedelta(seconds=20)  # synced ~20s after capture
    result = resolve(capture_time, added_time, date_original=capture_time)
    assert result.date_source == PHOTOS_DATE
    assert result.is_undated is False
    assert result.date_taken == capture_time


def test_screenshot_with_no_exif_but_derived_date_is_not_undated():
    """Regression test for a real, verified case: screenshots have no camera EXIF, but Photos
    still derives an accurate `date`/`date_original` for them from OS-level metadata (matching
    the capture timestamp embedded in their filename -- see design.md Section 5.2's original
    validation). On a real library, these showed a multi-HOUR gap between date_original and
    date_added (a timezone-handling quirk specific to synced/shared content, confirmed across
    16 real screenshot/PNG assets), never anywhere near the 2s threshold -- so they were never
    actually at risk of misclassification, but this locks the behavior in explicitly."""
    date_original = datetime(2022, 5, 20, 14, 52, 15, 400838)
    added_time = date_original - timedelta(hours=4)  # real observed pattern: exact 4h/5h offset
    result = resolve(date_original, added_time, date_original)
    assert result.date_source == PHOTOS_DATE
    assert result.is_undated is False


def test_no_gap_between_exact_zero_and_the_smallest_real_gap():
    """Real production data (681 available real assets) showed a completely clean split: every
    genuine no-EXIF-and-no-independent-signal case sits at an EXACT 0.000s gap, and every case
    with any real signal (EXIF or otherwise) starts at 4.42s and up -- nothing in between.
    UNDATED_THRESHOLD sits comfortably inside that gap; this pins the boundary behavior."""
    added_time = datetime(2024, 1, 1, 0, 0, 0)
    just_under = resolve(added_time, added_time, added_time + timedelta(milliseconds=1999))
    just_over = resolve(added_time, added_time, added_time + timedelta(milliseconds=2001))
    assert just_under.is_undated is True
    assert just_over.is_undated is False
