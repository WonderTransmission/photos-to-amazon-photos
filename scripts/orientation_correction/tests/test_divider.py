from pathlib import Path

from PIL import Image, ImageDraw

from orientation_correction import divider


def test_write_divider_creates_a_valid_png(tmp_path):
    output = tmp_path / "divider.png"

    divider.write_divider(
        output, category="Corrected", directory=Path("/photos/2003/02"), file_count=52
    )

    assert output.exists()
    # A plain image, not a PDF, is deliberate: Preview.app treats a PDF as a structurally
    # different document from a batch of images (even passed on the same `open` command line),
    # so it always opens it in a separate window. A PNG is the same "kind" as the photos that
    # follow it, so Preview merges it into the same multi-image browsing window instead.
    with Image.open(output) as img:
        assert img.format == "PNG"
        assert img.size == divider._PAGE_SIZE


def test_write_divider_creates_parent_directories(tmp_path):
    output = tmp_path / "nested" / "dividers" / "divider-001.png"

    divider.write_divider(output, category="Corrected", directory=Path("/a/b"), file_count=1)

    assert output.exists()


def test_wrap_path_splits_long_paths_on_slash_boundaries():
    img = Image.new("RGB", (400, 100), "white")
    draw = ImageDraw.Draw(img)
    font = divider._load_font(20)

    long_path = "/Volumes/ExternalDrive/some/deeply/nested/staging/area/photos/2003/02"
    lines = divider._wrap_path(long_path, font, draw, max_width=200)

    assert len(lines) > 1
    # every line must actually fit within max_width
    for line in lines:
        assert draw.textlength(line, font=font) <= 200
    # rejoining the lines (they were split exactly at '/' boundaries) reconstructs the original
    assert "/".join(lines) == long_path


def test_wrap_path_short_path_stays_on_one_line():
    img = Image.new("RGB", (400, 100), "white")
    draw = ImageDraw.Draw(img)
    font = divider._load_font(20)

    lines = divider._wrap_path("/a/b", font, draw, max_width=2000)

    assert lines == ["/a/b"]


def test_load_font_falls_back_when_no_candidates_exist(monkeypatch):
    monkeypatch.setattr(divider, "_REGULAR_FONT_CANDIDATES", ["/nonexistent/font.ttf"])
    monkeypatch.setattr(divider, "_BOLD_FONT_CANDIDATES", ["/nonexistent/bold.ttf"])

    # must not raise, even with no real font files available
    font = divider._load_font(30)
    assert font is not None
