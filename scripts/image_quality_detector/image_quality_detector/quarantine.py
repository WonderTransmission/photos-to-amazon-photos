"""Moves a flagged image into its quarantine location. Unlike orientation-correction there's
nothing to "fix" about a blurry or over/under-exposed photo, so --apply here just relocates the
file out of the staged tree (see naming.py) rather than rewriting pixels in place.
"""

import os
from pathlib import Path

from image_quality_detector import naming


def quarantine_image(path: Path, category_key: str) -> Path:
    """Moves `path` to naming.quarantine_path_for(path, category_key) and returns the
    destination. A pre-existing file at the destination is treated as an error rather than
    silently overwritten -- it should never happen in normal operation (discover.py never
    re-surfaces an already-quarantined file), so if it does, something unexpected is going on and
    is worth surfacing rather than papering over."""
    dest = naming.quarantine_path_for(path, category_key)
    if dest.exists():
        raise FileExistsError(f"Quarantine destination already exists: {dest}")

    dest.parent.mkdir(parents=True, exist_ok=True)
    os.replace(path, dest)
    return dest
