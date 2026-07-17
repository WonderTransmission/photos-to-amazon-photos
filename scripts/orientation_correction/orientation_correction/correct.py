"""Applies a corrective rotation to an image in place.

Backs up the original alongside it (same directory, `<name>.orig.<run_timestamp>`), then writes
the corrected pixels back to the original filename. See docs/how-it-works.md ("Crash safety")
for why the encode happens before anything on disk is touched.
"""

import logging
import os
import struct
from pathlib import Path

from PIL import Image, ImageOps

from orientation_correction import naming

try:
    import pillow_heif

    pillow_heif.register_heif_opener()
except ImportError:
    pass

log = logging.getLogger(__name__)

_FORMAT_BY_SUFFIX = {
    ".jpg": "JPEG",
    ".jpeg": "JPEG",
    ".png": "PNG",
    ".heic": "HEIF",
}

DEFAULT_JPEG_QUALITY = 95
DEFAULT_HEIF_QUALITY = 90


def _format_for(path: Path) -> str:
    fmt = _FORMAT_BY_SUFFIX.get(path.suffix.lower())
    if fmt is None:
        raise ValueError(f"Unsupported image extension: {path.suffix!r} ({path})")
    return fmt


def _load_and_rotate(
    path: Path, rotate_op: Image.Transpose | None
) -> tuple[Image.Image, bytes | None]:
    """Bakes in any existing EXIF orientation (matching what infer.py judged the image on, per
    docs/how-it-works.md), applies the additional corrective rotation, and returns the result
    plus EXIF bytes to re-embed -- with the orientation tag already stripped by exif_transpose,
    so a viewer never double-rotates."""
    with Image.open(path) as raw:
        raw.load()
        baseline = ImageOps.exif_transpose(raw)

    corrected = baseline.transpose(rotate_op) if rotate_op is not None else baseline
    exif = baseline.getexif()
    exif_bytes = exif.tobytes() if len(exif) else None
    return corrected, exif_bytes


def _save(
    img: Image.Image,
    dest: Path,
    fmt: str,
    exif_bytes: bytes | None,
    jpeg_quality: int,
    heif_quality: int,
) -> None:
    kwargs: dict = {"format": fmt}
    if fmt == "JPEG":
        kwargs["quality"] = jpeg_quality
    elif fmt == "HEIF":
        kwargs["quality"] = heif_quality
    if exif_bytes and fmt in ("JPEG", "HEIF"):
        kwargs["exif"] = exif_bytes

    try:
        img.save(dest, **kwargs)
    except struct.error as exc:
        # Some real-world EXIF blocks (seen from an older Sanyo camera) have a tag Pillow can't
        # losslessly re-serialize -- e.g. a LONG-typed field ending up negative at write time,
        # which struct.pack("L", ...) rejects. This is a Pillow round-trip limitation on
        # particular EXIF structures, not something under our control, and struct.error isn't an
        # OSError so it wasn't caught by the fallback below. Getting the orientation right
        # matters more than preserving every EXIF tag, so retry without embedding EXIF at all
        # rather than losing the whole file's correction over unrelated metadata.
        if "exif" in kwargs:
            log.warning(
                "Dropping EXIF for %s after a struct-pack error re-embedding it (%s)", dest, exc
            )
            kwargs.pop("exif")
            img.save(dest, **kwargs)
        else:
            raise
    except OSError:
        # A handful of source modes (e.g. palette PNGs) aren't writable in every target format --
        # fall back to RGB rather than failing the whole file over a color-mode mismatch.
        log.warning("Save of %s failed in mode %s, retrying as RGB", dest, img.mode)
        img.convert("RGB").save(dest, **kwargs)


def already_corrected(path: Path) -> bool:
    """True if a backup already exists for this file (from an earlier --apply run) -- lets
    re-runs skip files they've already fixed instead of rotating them again."""
    return naming.find_existing_backup(path) is not None


def correct_image(
    path: Path,
    rotate_op: Image.Transpose | None,
    run_timestamp: str,
    *,
    jpeg_quality: int = DEFAULT_JPEG_QUALITY,
    heif_quality: int = DEFAULT_HEIF_QUALITY,
) -> Path:
    """Corrects `path` in place and returns the backup path it created.

    Ordering: decode + rotate + re-encode happen first, into a temp file, without touching
    `path` at all -- if that fails, the original is untouched. Only once the corrected bytes are
    safely on disk do we do the two renames (original -> backup, temp -> original), each a fast
    metadata-only operation. This keeps the window in which a mid-run crash could leave things
    inconsistent as small as practically possible (see docs/how-it-works.md).
    """
    fmt = _format_for(path)
    backup_path = naming.backup_path_for(path, run_timestamp)
    tmp_path = path.with_name(f".{path.name}.orientation_tmp")

    try:
        corrected_img, exif_bytes = _load_and_rotate(path, rotate_op)
        with corrected_img:
            _save(corrected_img, tmp_path, fmt, exif_bytes, jpeg_quality, heif_quality)

        os.replace(path, backup_path)
        os.replace(tmp_path, path)
    except Exception:
        if tmp_path.exists():
            tmp_path.unlink(missing_ok=True)
        raise

    return backup_path
