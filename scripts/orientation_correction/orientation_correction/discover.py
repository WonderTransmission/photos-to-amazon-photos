"""Finds candidate image files under an input directory."""

import logging
from pathlib import Path

from orientation_correction.naming import is_backup_file

log = logging.getLogger(__name__)

IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".heic"}


def discover_images(root: Path) -> list[Path]:
    """Recursively finds png/jpg/jpeg/heic files (case-insensitive) under root, sorted for
    deterministic ordering. Skips this tool's own backup files, so a re-run over an
    already-corrected directory doesn't treat a backup as a fresh candidate."""
    images: list[Path] = []
    skipped_backups = 0

    for path in root.rglob("*"):
        if not path.is_file():
            continue
        if is_backup_file(path):
            skipped_backups += 1
            continue
        if path.suffix.lower() in IMAGE_EXTENSIONS:
            images.append(path)

    images.sort()
    if skipped_backups:
        log.info("Skipped %d existing backup file(s) under %s", skipped_backups, root)
    return images
