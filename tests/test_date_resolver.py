from datetime import datetime, timedelta

from photos_to_amazon_photos.date_resolver import (
    LIBRARY_ADDED,
    PHOTOS_DATE,
    UNDATED_THRESHOLD,
    resolve,
)

BASE = datetime(2024, 5, 14, 12, 0, 0)


def test_no_date_added_trusts_date_as_is():
    result = resolve(BASE, None)
    assert result.date_taken == BASE
    assert result.date_source == PHOTOS_DATE
    assert result.is_undated is False


def test_date_equals_date_added_is_undated():
    result = resolve(BASE, BASE)
    assert result.date_source == LIBRARY_ADDED
    assert result.is_undated is True


def test_date_far_from_date_added_is_trusted():
    date_added = BASE - timedelta(days=400)
    result = resolve(BASE, date_added)
    assert result.date_source == PHOTOS_DATE
    assert result.is_undated is False


def test_boundary_exactly_at_threshold_is_not_undated():
    # Strictly-less-than comparison: a diff exactly equal to the threshold should NOT count
    # as an import-time fallback.
    date_added = BASE - UNDATED_THRESHOLD
    result = resolve(BASE, date_added)
    assert result.date_source == PHOTOS_DATE
    assert result.is_undated is False


def test_boundary_just_inside_threshold_is_undated():
    date_added = BASE - (UNDATED_THRESHOLD - timedelta(seconds=1))
    result = resolve(BASE, date_added)
    assert result.date_source == LIBRARY_ADDED
    assert result.is_undated is True


def test_result_is_tuple_unpackable():
    date_taken, date_source, is_undated = resolve(BASE, None)
    assert date_taken == BASE
    assert date_source == PHOTOS_DATE
    assert is_undated is False
