from datetime import datetime
from types import SimpleNamespace

from photos_to_amazon_photos.library_reader import (
    LIVE_PHOTO,
    PHOTO,
    VIDEO,
    _to_asset_view,
    classify,
)


def fake_photo(**overrides):
    defaults = dict(
        uuid="U1",
        ismovie=False,
        live_photo=False,
        original_filename="IMG_0001.HEIC",
        hasadjustments=False,
        date=datetime(2024, 5, 14, 12, 0, 0),
        date_added=datetime(2024, 5, 15, 8, 0, 0),
        path="/fake/path/IMG_0001.HEIC",
        path_edited=None,
    )
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


def test_classify_photo():
    assert classify(fake_photo()) == PHOTO


def test_classify_video():
    assert classify(fake_photo(ismovie=True)) == VIDEO


def test_classify_live_photo():
    assert classify(fake_photo(live_photo=True)) == LIVE_PHOTO


def test_video_takes_precedence_over_live_photo_flag():
    # Defensive: ismovie is checked first, matching docs/design.md Section 3's if/elif order.
    assert classify(fake_photo(ismovie=True, live_photo=True)) == VIDEO


def test_to_asset_view_maps_fields():
    photo = fake_photo(uuid="U2", hasadjustments=True)
    view = _to_asset_view(photo)
    assert view.uuid == "U2"
    assert view.media_type == PHOTO
    assert view.hasadjustments is True
    assert view.original_filename == "IMG_0001.HEIC"
    assert view.path == "/fake/path/IMG_0001.HEIC"
    assert view.date_added == datetime(2024, 5, 15, 8, 0, 0)


def test_asset_view_export_passes_through_to_photo():
    calls = []

    class FakePhoto:
        uuid = "U3"
        ismovie = False
        live_photo = False
        original_filename = "IMG_0002.HEIC"
        hasadjustments = False
        date = datetime(2024, 5, 14, 12, 0, 0)
        date_added = None
        path = "/fake/IMG_0002.HEIC"
        path_edited = None

        def export(self, dest, **kwargs):
            calls.append((dest, kwargs))
            return ["/fake/out/IMG_0002.HEIC"]

    view = _to_asset_view(FakePhoto())
    result = view.export("/tmp/out", edited=True, live_photo=False)

    assert result == ["/fake/out/IMG_0002.HEIC"]
    assert calls == [
        (
            "/tmp/out",
            {"filename": None, "edited": True, "live_photo": False, "exiftool": False},
        )
    ]
