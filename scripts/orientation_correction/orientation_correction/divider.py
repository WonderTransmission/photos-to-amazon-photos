"""Generates a simple divider page (a PNG, via Pillow -- no extra dependency) announcing a
preview-links group's category and directory. Written as a plain image rather than a PDF
specifically so Preview.app treats it as just another image and merges it into the same
multi-image browsing window as the photos that follow, instead of opening it in a separate PDF
viewer window (PDF is a structurally different document type to Preview.app, even when passed on
the same `open` command line as a batch of images). See docs/how-it-works.md.
"""

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

_PAGE_SIZE = (1650, 1275)  # landscape, roughly letter-sized at 150dpi
_MARGIN = 100
_LINE_SPACING = 1.3

# Tried in order; falls back to Pillow's bundled scalable default font if none of these exist
# (e.g. running somewhere other than macOS), so this never hard-fails over a missing font file.
_REGULAR_FONT_CANDIDATES = [
    "/System/Library/Fonts/Supplemental/Arial.ttf",
    "/Library/Fonts/Arial.ttf",
]
_BOLD_FONT_CANDIDATES = [
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
    "/Library/Fonts/Arial Bold.ttf",
]


def _load_font(size: int, *, bold: bool = False) -> ImageFont.ImageFont:
    for candidate in _BOLD_FONT_CANDIDATES if bold else _REGULAR_FONT_CANDIDATES:
        try:
            return ImageFont.truetype(candidate, size)
        except OSError:
            continue
    return ImageFont.load_default(size=size)


def _wrap_path(
    path_str: str, font: ImageFont.ImageFont, draw: ImageDraw.ImageDraw, max_width: int
) -> list[str]:
    """Wraps a filesystem path on '/' boundaries (rather than mid-word) so a long directory path
    never overflows the page width."""
    segments = path_str.split("/")
    lines: list[str] = []
    # None, not "", marks "nothing accumulated yet" -- an absolute path's first segment (the
    # bit before its leading "/") is itself an empty string, which would otherwise be
    # indistinguishable from "not started".
    current: str | None = None
    for segment in segments:
        candidate = segment if current is None else f"{current}/{segment}"
        if current is None or draw.textlength(candidate, font=font) <= max_width:
            current = candidate
        else:
            lines.append(current)
            current = segment
    if current is not None:
        lines.append(current)
    return lines


def write_divider(output_path: Path, *, category: str, directory: Path, file_count: int) -> None:
    img = Image.new("RGB", _PAGE_SIZE, "white")
    draw = ImageDraw.Draw(img)
    max_width = _PAGE_SIZE[0] - 2 * _MARGIN

    label_font = _load_font(36)
    category_font = _load_font(72, bold=True)
    path_font = _load_font(40)
    count_font = _load_font(32)

    y = _MARGIN
    draw.text((_MARGIN, y), "ORIENTATION REVIEW", font=label_font, fill="black")
    y += int(36 * _LINE_SPACING) + 30

    draw.text((_MARGIN, y), category, font=category_font, fill="black")
    y += int(72 * _LINE_SPACING) + 20

    for line in _wrap_path(str(directory), path_font, draw, max_width):
        draw.text((_MARGIN, y), line, font=path_font, fill="black")
        y += int(40 * _LINE_SPACING)

    y += 20
    draw.text((_MARGIN, y), f"{file_count} file(s)", font=count_font, fill="black")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    img.save(output_path, "PNG")
