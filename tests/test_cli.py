import logging

import pytest

from photos_to_amazon_photos import cli, stager
from photos_to_amazon_photos.cli import main


def test_help_exits_zero(capsys):
    with pytest.raises(SystemExit) as exc_info:
        main(["--help"])
    assert exc_info.value.code == 0
    assert "library_path" in capsys.readouterr().out


def test_missing_required_args_exits_nonzero(capsys):
    with pytest.raises(SystemExit) as exc_info:
        main([])
    assert exc_info.value.code == 2


def test_nonexistent_library_path_exits_nonzero(tmp_path, capsys):
    missing = tmp_path / "does-not-exist.photoslibrary"
    target = tmp_path / "target"
    with pytest.raises(SystemExit) as exc_info:
        main([str(missing), str(target)])
    assert exc_info.value.code == 2


def test_invalid_library_directory_fails_gracefully(tmp_path, caplog):
    # A directory that exists but isn't actually a Photos library -- osxphotos.PhotosDB()
    # will fail to open it. Should be a clean error + exit 1, not an uncaught traceback.
    library = tmp_path / "Library.photoslibrary"
    library.mkdir()
    target = tmp_path / "target"
    with caplog.at_level(logging.ERROR):
        result = main([str(library), str(target)])
    assert result == 1
    assert "failed to open or read the library" in caplog.text


def test_successful_run_prints_summary_and_returns_zero(tmp_path, monkeypatch, capsys):
    library = tmp_path / "Library.photoslibrary"
    library.mkdir()
    target = tmp_path / "target"

    fake_summary = stager.RunSummary()
    fake_summary.add("photo", stager.COPIED, 3)
    fake_summary.add("photo", stager.ERROR, 1)
    monkeypatch.setattr(cli.stager, "run", lambda *a, **kw: fake_summary)
    monkeypatch.setattr(cli, "_photos_app_running", lambda: False)

    result = main([str(library), str(target)])

    assert result == 0
    out = capsys.readouterr().out
    assert "Run summary" in out
    assert "copied=3" in out
    assert "error=1" in out
    assert "total: 4" in out


def test_dry_run_flag_is_passed_through(tmp_path, monkeypatch):
    library = tmp_path / "Library.photoslibrary"
    library.mkdir()
    target = tmp_path / "target"

    calls = []

    def fake_run(library_path, target_root, tracking_file, *, dry_run=False):
        calls.append(dry_run)
        return stager.RunSummary()

    monkeypatch.setattr(cli.stager, "run", fake_run)
    monkeypatch.setattr(cli, "_photos_app_running", lambda: False)

    main([str(library), str(target), "--dry-run"])

    assert calls == [True]


def test_photos_app_warning_logged_when_running(tmp_path, monkeypatch, caplog):
    library = tmp_path / "Library.photoslibrary"
    library.mkdir()
    target = tmp_path / "target"

    monkeypatch.setattr(cli.stager, "run", lambda *a, **kw: stager.RunSummary())
    monkeypatch.setattr(cli, "_photos_app_running", lambda: True)

    with caplog.at_level(logging.WARNING):
        result = main([str(library), str(target)])

    assert result == 0  # non-blocking -- the run still completes
    assert "Photos.app appears to be running" in caplog.text


def test_no_photos_app_warning_when_not_running(tmp_path, monkeypatch, caplog):
    library = tmp_path / "Library.photoslibrary"
    library.mkdir()
    target = tmp_path / "target"

    monkeypatch.setattr(cli.stager, "run", lambda *a, **kw: stager.RunSummary())
    monkeypatch.setattr(cli, "_photos_app_running", lambda: False)

    with caplog.at_level(logging.WARNING):
        main([str(library), str(target)])

    assert "Photos.app appears to be running" not in caplog.text
