import logging
from datetime import datetime

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


def test_nonexistent_library_path_exits_nonzero(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    missing = tmp_path / "does-not-exist.photoslibrary"
    target = tmp_path / "target"
    with pytest.raises(SystemExit) as exc_info:
        main([str(missing), str(target)])
    assert exc_info.value.code == 2


def test_invalid_library_directory_fails_gracefully(tmp_path, monkeypatch, caplog):
    # A directory that exists but isn't actually a Photos library -- osxphotos.PhotosDB()
    # will fail to open it. Should be a clean error + exit 1, not an uncaught traceback.
    monkeypatch.chdir(tmp_path)
    library = tmp_path / "Library.photoslibrary"
    library.mkdir()
    target = tmp_path / "target"
    with caplog.at_level(logging.ERROR):
        result = main([str(library), str(target)])
    assert result == 1
    assert "failed to open or read the library" in caplog.text


def test_successful_run_prints_summary_and_returns_zero(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
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
    monkeypatch.chdir(tmp_path)
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
    monkeypatch.chdir(tmp_path)
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
    monkeypatch.chdir(tmp_path)
    library = tmp_path / "Library.photoslibrary"
    library.mkdir()
    target = tmp_path / "target"

    monkeypatch.setattr(cli.stager, "run", lambda *a, **kw: stager.RunSummary())
    monkeypatch.setattr(cli, "_photos_app_running", lambda: False)

    with caplog.at_level(logging.WARNING):
        main([str(library), str(target)])

    assert "Photos.app appears to be running" not in caplog.text


def test_log_file_created_in_cwd_with_timestamp_name(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    library = tmp_path / "Library.photoslibrary"
    library.mkdir()
    target = tmp_path / "target"

    monkeypatch.setattr(cli.stager, "run", lambda *a, **kw: stager.RunSummary())
    monkeypatch.setattr(cli, "_photos_app_running", lambda: False)

    main([str(library), str(target)])

    log_files = list(tmp_path.glob("photos-to-amazon-photos-*.log"))
    assert len(log_files) == 1


def test_log_file_contains_log_lines_and_final_summary(tmp_path, monkeypatch):
    """The whole point of this feature: if the terminal session is lost (e.g. an unexpected
    shutdown), the log file alone should show both what happened during the run AND whether it
    completed -- the final summary specifically, since that's printed via print(), not logged,
    so it needs to be explicitly written to the file too."""
    monkeypatch.chdir(tmp_path)
    library = tmp_path / "Library.photoslibrary"
    library.mkdir()
    target = tmp_path / "target"

    fake_summary = stager.RunSummary()
    fake_summary.add("photo", stager.COPIED, 5)
    monkeypatch.setattr(cli.stager, "run", lambda *a, **kw: fake_summary)
    monkeypatch.setattr(cli, "_photos_app_running", lambda: True)  # exercise a real log line

    result = main([str(library), str(target)])
    assert result == 0

    log_file = next(tmp_path.glob("photos-to-amazon-photos-*.log"))
    content = log_file.read_text()
    assert "Photos.app appears to be running" in content  # a normal logged line
    assert "Run summary" in content and "copied=5" in content  # the print()-only summary too


def test_repeated_main_calls_get_independent_log_files(tmp_path, monkeypatch):
    # Guards against logging.basicConfig() silently no-op'ing on the second call because the
    # root logger already has handlers from the first -- would otherwise make every run after
    # the first in a long-lived process (or a test suite) silently write to the FIRST run's log
    # file instead of its own. Timestamps are faked (rather than relying on two real main()
    # calls landing in different wall-clock seconds, which two fast successive calls in a test
    # can't guarantee) to deterministically produce two distinct filenames.
    monkeypatch.chdir(tmp_path)
    library = tmp_path / "Library.photoslibrary"
    library.mkdir()
    target = tmp_path / "target"

    monkeypatch.setattr(cli.stager, "run", lambda *a, **kw: stager.RunSummary())
    monkeypatch.setattr(cli, "_photos_app_running", lambda: False)

    timestamps = iter([datetime(2026, 1, 1, 12, 0, 0), datetime(2026, 1, 1, 12, 0, 1)])

    class FakeDateTime:
        @staticmethod
        def now():
            return next(timestamps)

    monkeypatch.setattr(cli, "datetime", FakeDateTime)

    main([str(library), str(target)])
    main([str(library), str(target)])

    log_files = sorted(tmp_path.glob("photos-to-amazon-photos-*.log"))
    assert len(log_files) == 2
    for f in log_files:
        assert "Run summary" in f.read_text()
