import struct

import pytest
from conftest import marker_corner, marker_image
from PIL import Image, ImageOps

from orientation_correction import correct, naming

RUN_TS = "20260715T120000"


def test_correct_image_creates_backup_with_original_bytes(tmp_path):
    path = tmp_path / "a.jpg"
    marker_image(60, 30, "top-left").save(path, format="JPEG", quality=95)
    original_bytes = path.read_bytes()

    backup = correct.correct_image(path, Image.Transpose.ROTATE_270, RUN_TS)

    assert backup == naming.backup_path_for(path, RUN_TS)
    assert backup.read_bytes() == original_bytes


def test_correct_image_rotates_pixels_in_place_jpeg(tmp_path):
    path = tmp_path / "a.jpg"
    marker_image(60, 30, "top-left").save(path, format="JPEG", quality=95)

    correct.correct_image(path, Image.Transpose.ROTATE_270, RUN_TS)  # 90 CW correction

    with Image.open(path) as im:
        assert marker_corner(im) == "top-right"


@pytest.mark.parametrize(
    ("rotate_op", "expected_corner"),
    [
        (Image.Transpose.ROTATE_270, "top-right"),  # 90 CW
        (Image.Transpose.ROTATE_180, "bottom-right"),  # 180
        (Image.Transpose.ROTATE_90, "bottom-left"),  # 90 CCW
    ],
)
def test_correct_image_rotation_directions_png(tmp_path, rotate_op, expected_corner):
    path = tmp_path / "a.png"
    marker_image(60, 30, "top-left").save(path, format="PNG")

    correct.correct_image(path, rotate_op, RUN_TS)

    with Image.open(path) as im:
        assert marker_corner(im) == expected_corner


def test_correct_image_preserves_png_alpha_transparency(tmp_path):
    path = tmp_path / "a.png"
    img = Image.new("RGBA", (40, 20), (0, 0, 0, 0))
    for x in range(8):
        for y in range(8):
            img.putpixel((x, y), (255, 0, 0, 255))
    img.save(path, format="PNG")

    correct.correct_image(path, Image.Transpose.ROTATE_270, RUN_TS)

    with Image.open(path) as im:
        assert im.mode == "RGBA"
        assert marker_corner(im) == "top-right"
        assert im.getpixel((im.size[0] // 2, im.size[1] // 2))[3] == 0  # still transparent


def test_correct_image_heic_round_trip(tmp_path):
    path = tmp_path / "a.heic"
    marker_image(60, 30, "top-left").save(path, quality=90)

    correct.correct_image(path, Image.Transpose.ROTATE_90, RUN_TS)  # 90 CCW correction

    with Image.open(path) as im:
        assert marker_corner(im) == "bottom-left"


def test_correct_image_no_rotation_is_a_no_op_geometrically(tmp_path):
    path = tmp_path / "a.jpg"
    marker_image(60, 30, "top-left").save(path, format="JPEG", quality=95)

    correct.correct_image(path, None, RUN_TS)

    with Image.open(path) as im:
        assert marker_corner(im) == "top-left"
    assert correct.already_corrected(path)


def test_correct_image_preserves_exif_but_strips_orientation_tag(tmp_path):
    path = tmp_path / "a.jpg"
    img = marker_image(40, 20, "top-left")
    exif = img.getexif()
    exif[0x0112] = 6  # Orientation
    exif[0x9003] = "2003:02:04 12:00:00"  # DateTimeOriginal
    img.save(path, format="JPEG", exif=exif, quality=95)

    correct.correct_image(path, Image.Transpose.ROTATE_270, RUN_TS)

    with Image.open(path) as im:
        result_exif = im.getexif()
        assert result_exif.get(0x0112) is None
        assert result_exif.get(0x9003) == "2003:02:04 12:00:00"


def test_correct_image_rolls_back_on_write_failure(tmp_path, monkeypatch):
    path = tmp_path / "a.jpg"
    marker_image(60, 30, "top-left").save(path, format="JPEG", quality=95)
    original_bytes = path.read_bytes()

    def boom(*args, **kwargs):
        raise OSError("simulated failure")

    monkeypatch.setattr(correct, "_save", boom)

    with pytest.raises(OSError):
        correct.correct_image(path, Image.Transpose.ROTATE_270, RUN_TS)

    assert path.exists()
    assert path.read_bytes() == original_bytes
    assert correct.already_corrected(path) is False
    tmp_marker = path.with_name(f".{path.name}.orientation_tmp")
    assert not tmp_marker.exists()


def test_save_drops_exif_and_retries_after_a_struct_error(tmp_path, monkeypatch):
    """Some real-world EXIF blocks (seen from an older Sanyo camera) contain a tag Pillow can't
    losslessly re-serialize -- a struct.error, not an OSError, so it needs its own fallback
    distinct from the mode-conversion retry above. Simulated here via monkeypatching, since it
    depends on a specific malformed EXIF structure that isn't practical to construct by hand."""
    path = tmp_path / "a.jpg"
    marker_image(60, 30, "top-left").save(path, format="JPEG", quality=95)
    dest = tmp_path / "out.jpg"

    real_save = Image.Image.save
    calls = []

    def flaky_save(self, fp, **kwargs):
        calls.append(kwargs)
        if "exif" in kwargs:
            raise struct.error("'L' format requires 0 <= number <= 4294967295")
        return real_save(self, fp, **kwargs)

    monkeypatch.setattr(Image.Image, "save", flaky_save)

    with Image.open(path) as img:
        correct._save(img, dest, "JPEG", b"fake exif bytes", 95, 90)

    assert dest.exists()
    assert len(calls) == 2
    assert "exif" in calls[0]
    assert "exif" not in calls[1]


def test_save_reraises_struct_error_when_no_exif_was_involved(tmp_path, monkeypatch):
    """If a struct.error happens for some other reason (not the EXIF fallback's business),
    don't silently swallow it -- only retry when dropping EXIF is actually a plausible fix."""
    path = tmp_path / "a.jpg"
    marker_image(60, 30, "top-left").save(path, format="JPEG", quality=95)
    dest = tmp_path / "out.jpg"

    def always_fails(self, fp, **kwargs):
        raise struct.error("unrelated failure")

    monkeypatch.setattr(Image.Image, "save", always_fails)

    with Image.open(path) as img, pytest.raises(struct.error):
        correct._save(img, dest, "JPEG", None, 95, 90)


def test_correct_image_succeeds_without_exif_after_a_struct_error(tmp_path, monkeypatch):
    """End-to-end: a struct.error while embedding EXIF must not cost the whole correction --
    the file still ends up rotated, just without its original EXIF."""
    path = tmp_path / "a.jpg"
    img = marker_image(60, 30, "top-left")
    exif = img.getexif()
    exif[0x9003] = "2003:02:04 12:00:00"
    img.save(path, format="JPEG", exif=exif, quality=95)

    real_save = Image.Image.save

    def flaky_save(self, fp, **kwargs):
        if "exif" in kwargs:
            raise struct.error("'L' format requires 0 <= number <= 4294967295")
        return real_save(self, fp, **kwargs)

    monkeypatch.setattr(Image.Image, "save", flaky_save)

    correct.correct_image(path, Image.Transpose.ROTATE_270, RUN_TS)

    with Image.open(path) as im:
        assert marker_corner(im) == "top-right"  # correction still applied
        assert im.getexif().get(0x9003) is None  # EXIF lost, not fabricated


def test_correct_image_unsupported_extension_touches_nothing(tmp_path):
    path = tmp_path / "a.gif"
    path.write_bytes(b"not really a gif, extension is what matters here")

    with pytest.raises(ValueError, match="Unsupported image extension"):
        correct.correct_image(path, Image.Transpose.ROTATE_270, RUN_TS)

    assert path.exists()
    assert correct.already_corrected(path) is False


def test_already_corrected_false_before_and_true_after(tmp_path):
    path = tmp_path / "a.jpg"
    marker_image(60, 30, "top-left").save(path, format="JPEG", quality=95)

    assert correct.already_corrected(path) is False

    correct.correct_image(path, Image.Transpose.ROTATE_270, RUN_TS)

    assert correct.already_corrected(path) is True


def test_correct_image_source_respects_existing_exif_orientation(tmp_path):
    """The corrective rotation is applied on top of what a viewer would already show (i.e. after
    baking in any pre-existing EXIF orientation tag), matching infer.py's judgment basis."""
    path = tmp_path / "a.jpg"
    # Physically-stored pixels have the marker at top-left, but an EXIF Orientation of 6 means a
    # viewer renders it as if rotated 90 CW -- so the marker should visually render at top-right
    # before any correction is applied.
    img = marker_image(30, 60, "top-left")
    exif = img.getexif()
    exif[0x0112] = 6
    img.save(path, format="JPEG", exif=exif, quality=95)

    with Image.open(path) as raw:
        as_rendered = ImageOps.exif_transpose(raw)
        assert marker_corner(as_rendered) == "top-right"

    # No further corrective rotation needed -- confirm a rotate_op of None just bakes in the
    # existing EXIF transpose and normalizes the tag away.
    correct.correct_image(path, None, RUN_TS)

    with Image.open(path) as im:
        assert im.getexif().get(0x0112) is None
        assert marker_corner(im) == "top-right"
