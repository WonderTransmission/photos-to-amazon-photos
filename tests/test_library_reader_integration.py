"""Integration check against a real library -- docs/tasks.md T2.4's DoD asks for classification
counts to be cross-checked against a manual count in Photos.app. That's a GUI step no automated
test can perform. As a substitute with equivalent verification value: this regression-checks
LibraryReader's classification against the exact counts independently confirmed via raw osxphotos
during the Milestone 0 spike (docs/design.md Section 11.1) for this same library --
photo=5737 video=462 live_photo=4068, 10267 total, 0 errors.

Skipped entirely if this machine doesn't have that library (e.g. a fresh clone elsewhere).
"""

import os

import pytest

from photos_to_amazon_photos.library_reader import LIVE_PHOTO, PHOTO, VIDEO, LibraryReader

SPIKE_LIBRARY = os.environ.get("PHOTOS_TEST_LIBRARY", "")

pytestmark = pytest.mark.skipif(
    not SPIKE_LIBRARY or not __import__("pathlib").Path(SPIKE_LIBRARY).is_dir(),
    reason="PHOTOS_TEST_LIBRARY not set or not present on this machine",
)


def test_classification_counts_match_milestone_0_spike():
    reader = LibraryReader(SPIKE_LIBRARY)
    counts = {PHOTO: 0, VIDEO: 0, LIVE_PHOTO: 0}
    total = 0
    uuids = set()
    for asset in reader.iter_assets():
        counts[asset.media_type] += 1
        uuids.add(asset.uuid)
        total += 1

    assert total == 10267
    assert counts[PHOTO] == 5737
    assert counts[VIDEO] == 462
    assert counts[LIVE_PHOTO] == 4068
    assert len(uuids) == 10267  # UUID uniqueness, same check as the spike
