from datetime import datetime
from pathlib import Path

import pytest

from photos_to_amazon_photos.namer import target_path

DATE = datetime(2024, 5, 14, 12, 0, 0)
UUID = "a1b2c3d4-1111-2222-3333-444455556666"


def test_normal_photo_path():
    p = target_path("photo", "single", DATE, False, "IMG_1234", UUID, ".HEIC")
    assert p == Path("photos/2024/05/2024-05-14_IMG_1234_a1b2c3d4.HEIC")


def test_video_path():
    p = target_path("video", "single", DATE, False, "IMG_0001", UUID, ".mp4")
    assert p == Path("video/2024/05/2024-05-14_IMG_0001_a1b2c3d4.mp4")


def test_live_photo_key_image_goes_under_photos():
    p = target_path("live_photo", "key_image", DATE, False, "IMG_5678", UUID, ".HEIC")
    assert p == Path("photos/2024/05/2024-05-14_IMG_5678_a1b2c3d4.HEIC")


def test_live_photo_bundle_still_and_video_share_basename():
    still = target_path("live_photo", "live_bundle", DATE, False, "IMG_5678", UUID, ".HEIC")
    motion = target_path("live_photo", "live_bundle", DATE, False, "IMG_5678", UUID, ".MOV")
    assert still.parent == motion.parent == Path("live_photo/2024/05")
    assert still.stem == motion.stem
    assert still.suffix == ".HEIC"
    assert motion.suffix == ".MOV"


def test_undated_routes_to_undated_dir():
    p = target_path("photo", "single", DATE, True, "Screenshot", UUID, ".jpeg")
    assert p == Path("photos/_undated/2024-05-14_Screenshot_a1b2c3d4.jpeg")


def test_undated_video():
    p = target_path("video", "single", DATE, True, "IMG_0002", UUID, ".mov")
    assert p == Path("video/_undated/2024-05-14_IMG_0002_a1b2c3d4.mov")


def test_deterministic_same_inputs_same_output():
    args = ("photo", "single", DATE, False, "IMG_1234", UUID, ".HEIC")
    assert target_path(*args) == target_path(*args)


def test_unknown_component_raises():
    with pytest.raises(ValueError):
        target_path("photo", "bogus", DATE, False, "IMG_1234", UUID, ".HEIC")


def test_single_component_with_live_photo_media_type_raises():
    # "single" only makes sense for plain photo/video; a live_photo asset must be split into
    # key_image/live_bundle components upstream (stager.py, T3.1), not passed as "single".
    with pytest.raises(ValueError):
        target_path("live_photo", "single", DATE, False, "IMG_1234", UUID, ".HEIC")
