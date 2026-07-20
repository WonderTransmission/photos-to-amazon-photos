"""A persistent, global list of files confirmed (by manual review) to be false positives --
loaded on every run so they're never re-flagged, and appended to by revert.py. One plain-text
file, one absolute path per line; blank lines and lines starting with '#' are ignored.
"""

from collections.abc import Iterable
from pathlib import Path

# Relative to the current working directory -- see cli.py's note on _DEFAULT_MODEL_PATH-style
# defaults for why (a __file__-based default breaks under a regular, non-editable install).
DEFAULT_PATH = Path("ignore-list.txt")

HEADER = (
    "# image-quality-detect ignore list -- one absolute path per line.\n"
    "# Files here are always skipped, even if not (or no longer) quarantined.\n"
    "# Populated by `python -m image_quality_detector.revert`; edit by hand if you like.\n"
)


def load(path: Path) -> set[Path]:
    if not path.exists():
        return set()

    entries = set()
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        entries.add(Path(line).resolve())
    return entries


def append(path: Path, new_entries: Iterable[Path]) -> set[Path]:
    """Merges new_entries into the ignore list at `path`, deduplicated, and returns the full
    resulting set."""
    existing = load(path)
    combined = existing | {p.resolve() for p in new_entries}

    lines = [HEADER] + [str(p) for p in sorted(combined)]
    path.write_text("\n".join(lines) + "\n")
    return combined
