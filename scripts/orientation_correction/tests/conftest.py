"""Shared test helpers. All fixture images are generated on the fly -- nothing under tests/ is a
committed binary, so there's no risk of a real (or even realistic-looking) photo ending up in
the repo.
"""

from PIL import Image

MARKER_COLOR = (255, 0, 0)


def marker_image(width: int, height: int, corner: str = "top-left") -> Image.Image:
    """A white image with an unambiguous colored square in one corner, for tracking where
    content ends up after a rotation. `width != height` so corner identity survives a 90-degree
    swap of the image's own dimensions."""
    img = Image.new("RGB", (width, height), "white")
    offsets = {
        "top-left": (0, 0),
        "top-right": (width - 8, 0),
        "bottom-left": (0, height - 8),
        "bottom-right": (width - 8, height - 8),
    }
    ox, oy = offsets[corner]
    for x in range(ox, ox + min(8, width)):
        for y in range(oy, oy + min(8, height)):
            img.putpixel((x, y), MARKER_COLOR)
    return img


def marker_corner(img: Image.Image, tolerance: int = 60) -> str:
    """Inverse of marker_image: which corner (if any) the colored marker is now in. Uses a
    tolerance rather than exact equality since lossy formats (JPEG) shift pixel values slightly
    on re-encode."""
    w, h = img.size
    corners = {
        "top-left": (2, 2),
        "top-right": (w - 3, 2),
        "bottom-left": (2, h - 3),
        "bottom-right": (w - 3, h - 3),
    }
    for name, (x, y) in corners.items():
        px = img.getpixel((x, y))
        r, g, b = px[:3]
        if r > 255 - tolerance and g < tolerance and b < tolerance:
            return name
    return "unknown"
