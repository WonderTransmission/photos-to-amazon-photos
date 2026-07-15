"""The backup-filename convention, in one place so discover.py (which must exclude backups from
re-processing) and correct.py (which creates them) can't drift out of sync.
"""

import re
from pathlib import Path

BACKUP_TIMESTAMP_FORMAT = "%Y%m%dT%H%M%S"
_BACKUP_SUFFIX_RE = re.compile(r"\.orig\.\d{8}T\d{6}$")


def backup_path_for(original: Path, run_timestamp: str) -> Path:
    """<name> -> <name>.orig.<run_timestamp>, in the same directory as the original."""
    return original.with_name(f"{original.name}.orig.{run_timestamp}")


def is_backup_file(path: Path) -> bool:
    """True for anything named like a backup this tool created."""
    return bool(_BACKUP_SUFFIX_RE.search(path.name))


def find_existing_backup(original: Path) -> Path | None:
    """The most recent backup for `original`, if any prior run already corrected it."""
    matches = sorted(original.parent.glob(f"{original.name}.orig.*"))
    return matches[-1] if matches else None
