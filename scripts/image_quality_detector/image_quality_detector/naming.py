"""The quarantine-path convention, in one place so discover.py (which must exclude quarantined
files from re-processing), quarantine.py (which creates them), and revert.py (which must find
them again from an original path) can't drift out of sync.

A flagged file is moved from `<dir>/<name>` to `<dir>/_quality_review/<category>/<name>` --
alongside the original directory rather than into one global bucket, so preview-links grouping by
directory (see preview_links.py) still reflects where each photo actually lives, and so a re-scan
naturally never re-discovers it (it's simply no longer at its original path).
"""

from pathlib import Path

QUARANTINE_DIRNAME = "_quality_review"


def quarantine_path_for(original: Path, category_key: str) -> Path:
    """<dir>/<name> -> <dir>/_quality_review/<category_key>/<name>."""
    return original.parent / QUARANTINE_DIRNAME / category_key / original.name


def is_quarantine_path(path: Path) -> bool:
    """True for anything already living under a _quality_review directory this tool created."""
    return QUARANTINE_DIRNAME in path.parts


def find_quarantined(original: Path) -> Path | None:
    """The quarantined copy of `original`, if a prior --apply run already moved it there. Globs
    across category subdirectories rather than requiring the caller to know which category it
    was flagged under -- a file can only be quarantined under one category at a time, since
    quarantining removes it from `original`'s path entirely."""
    matches = sorted(original.parent.glob(f"{QUARANTINE_DIRNAME}/*/{original.name}"))
    return matches[-1] if matches else None
