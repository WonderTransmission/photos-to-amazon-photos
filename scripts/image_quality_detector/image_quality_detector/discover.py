"""Finds candidate image files under an input directory."""

import logging
from pathlib import Path

from image_quality_detector.naming import is_quarantine_path

log = logging.getLogger(__name__)

IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".heic"}


def discover_images(root: Path) -> list[Path]:
    """Recursively finds png/jpg/jpeg/heic files (case-insensitive) under root, sorted for
    deterministic ordering. Skips anything already living under a _quality_review directory, so a
    re-run over an already-quarantined tree doesn't treat a quarantined file as a fresh
    candidate."""
    images: list[Path] = []
    skipped_quarantined = 0

    for path in root.rglob("*"):
        if not path.is_file():
            continue
        if is_quarantine_path(path):
            skipped_quarantined += 1
            continue
        if path.suffix.lower() in IMAGE_EXTENSIONS:
            images.append(path)

    images.sort()
    if skipped_quarantined:
        log.info("Skipped %d already-quarantined file(s) under %s", skipped_quarantined, root)
    return images
