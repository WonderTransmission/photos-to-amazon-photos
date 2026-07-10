"""Real interrupt/resume test -- docs/tasks.md T4.1. Launches a genuine OS subprocess against
a small sample of real, available assets from the spike library, SIGKILLs it mid-run (a true
process kill, not a Python-level exception -- no cleanup code runs at all), then resumes and
verifies no duplication/corruption and eventual completion. Exercises NFR-4.

This test exists because a manual run of exactly this scenario found a real bug: a crash could
leave a file successfully staged with no tracking row ever flushed for it, and resuming would
then error forever on a path collision rather than reaching completion. Fixed in stager.py
(checksum-match adoption) and covered by a faster, deterministic regression test in
test_stager.py. This test is the slower, real-OS-process version of the same scenario.

Skipped entirely if the spike library isn't present on this machine.
"""

import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest

from photos_to_amazon_photos import tracking

SPIKE_LIBRARY = "/Users/YOUR_USERNAME/Pictures/Photos Library.photoslibrary"

pytestmark = pytest.mark.skipif(
    not Path(SPIKE_LIBRARY).is_dir(),
    reason="spike library not present on this machine",
)

_DRIVER = """
import itertools, sys
from photos_to_amazon_photos.library_reader import LibraryReader
from photos_to_amazon_photos import stager

lib, target, tracking_path, n = sys.argv[1], sys.argv[2], sys.argv[3], int(sys.argv[4])
reader = LibraryReader(lib)
available = (a for a in reader.iter_assets() if a.path is not None)
assets = list(itertools.islice(available, n))
stager.run(lib, target, tracking_path, assets=assets)
"""


def _launch(target_root, tracking_path, n=8):
    return subprocess.Popen(
        [
            sys.executable,
            "-c",
            _DRIVER,
            SPIKE_LIBRARY,
            str(target_root),
            str(tracking_path),
            str(n),
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def test_sigkill_mid_run_then_resume_reaches_completion_without_duplication(tmp_path):
    target_root = tmp_path / "target"
    tracking_path = target_root / "tracking.csv"

    proc = _launch(target_root, tracking_path)
    time.sleep(1.0)  # let it make some real progress
    proc.send_signal(signal.SIGKILL)
    proc.wait(timeout=10)

    # State right after the kill must not be corrupted, even though it's incomplete.
    copied_before = set()
    if tracking_path.exists():
        index = tracking.load(tracking_path)  # must not raise -- proves no corrupt CSV
        for row in index.rows():
            if row.status == tracking.COPIED:
                staged = target_root / row.target_relative_path
                assert staged.exists()
                assert staged.stat().st_size > 0
                copied_before.add(row.key)

    # Resume: same driver, same sample, run to actual completion this time.
    proc2 = _launch(target_root, tracking_path)
    proc2.wait(timeout=60)
    assert proc2.returncode == 0

    final_index = tracking.load(tracking_path)
    final_rows = final_index.rows()
    assert final_rows

    # No duplicate target paths.
    copied_paths = [r.target_relative_path for r in final_rows if r.status == tracking.COPIED]
    assert len(copied_paths) == len(set(copied_paths))

    # Everything copied before the kill is still copied after resume -- not lost or reverted.
    for key in copied_before:
        row = final_index.get(*key)
        assert row is not None
        assert row.status == tracking.COPIED

    # Eventual completion: every row reached a terminal status, nothing left in limbo.
    for row in final_rows:
        assert row.status in (tracking.COPIED, tracking.ERROR, tracking.IGNORED)
