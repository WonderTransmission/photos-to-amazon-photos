import pytest

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


def test_valid_args_parse_but_staging_not_yet_implemented(tmp_path):
    library = tmp_path / "Library.photoslibrary"
    library.mkdir()
    target = tmp_path / "target"
    assert main([str(library), str(target)]) == 1
