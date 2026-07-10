"""Integration check against the real Milestone-0 spike library -- docs/tasks.md T3.1's DoD
asks for this explicitly. Uses a small sample (only assets with a resolvable local path, per
the Milestone 0 finding that most of this particular library's assets are cloud-only) rather
than the full 10,267-asset library, to keep the test fast while still exercising real
osxphotos.PhotoInfo.export() calls end to end.

Skipped entirely if this machine doesn't have that library (e.g. a fresh clone elsewhere).
"""

import itertools
import os
from pathlib import Path

import pytest

from photos_to_amazon_photos import stager
from photos_to_amazon_photos.library_reader import LibraryReader

SPIKE_LIBRARY = os.environ.get("PHOTOS_TEST_LIBRARY", "")
SAMPLE_SIZE = 15

pytestmark = pytest.mark.skipif(
    not SPIKE_LIBRARY or not Path(SPIKE_LIBRARY).is_dir(),
    reason="PHOTOS_TEST_LIBRARY not set or not present on this machine",
)


def _sample_assets(n=SAMPLE_SIZE):
    reader = LibraryReader(SPIKE_LIBRARY)
    available = (a for a in reader.iter_assets() if a.path is not None)
    return list(itertools.islice(available, n))


def test_second_run_stages_nothing_new(tmp_path):
    assets = _sample_assets()
    assert assets, "expected at least one asset with a resolvable path in the spike library"

    target_root = tmp_path / "target"
    tracking_path = target_root / "tracking.csv"

    summary1 = stager.run(SPIKE_LIBRARY, target_root, tracking_path, assets=assets)
    assert summary1.total() > 0
    assert summary1.counts[("photo", stager.COPIED)] > 0 or summary1.total() > 0

    summary2 = stager.run(SPIKE_LIBRARY, target_root, tracking_path, assets=assets)
    copied_second_time = sum(
        n for (_media_type, outcome), n in summary2.counts.items() if outcome == stager.COPIED
    )
    assert copied_second_time == 0
    assert summary2.total() == summary1.total()  # same assets, same components, all accounted for
