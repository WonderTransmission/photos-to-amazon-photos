from orientation_correction import discover, naming


def _touch(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"not a real image, discovery only looks at the filename")


def test_discover_images_matches_supported_extensions_case_insensitively(tmp_path):
    for name in ["a.png", "b.jpg", "c.jpeg", "d.heic", "E.PNG", "F.JPG", "G.JPEG", "H.HEIC"]:
        _touch(tmp_path / name)

    found = discover.discover_images(tmp_path)

    assert {p.name for p in found} == {
        "a.png", "b.jpg", "c.jpeg", "d.heic", "E.PNG", "F.JPG", "G.JPEG", "H.HEIC",
    }


def test_discover_images_ignores_unsupported_extensions(tmp_path):
    _touch(tmp_path / "a.jpg")
    _touch(tmp_path / "notes.txt")
    _touch(tmp_path / "video.mov")
    _touch(tmp_path / ".DS_Store")

    found = discover.discover_images(tmp_path)

    assert [p.name for p in found] == ["a.jpg"]


def test_discover_images_recurses_into_subdirectories(tmp_path):
    _touch(tmp_path / "top.jpg")
    _touch(tmp_path / "2003" / "02" / "nested.jpg")

    found = discover.discover_images(tmp_path)

    assert {p.name for p in found} == {"top.jpg", "nested.jpg"}


def test_discover_images_excludes_backup_files(tmp_path):
    original = tmp_path / "a.jpg"
    _touch(original)
    backup = naming.backup_path_for(original, "20260715T120000")
    _touch(backup)

    found = discover.discover_images(tmp_path)

    assert found == [original]


def test_discover_images_returns_empty_list_for_no_images(tmp_path):
    _touch(tmp_path / "notes.txt")

    assert discover.discover_images(tmp_path) == []


def test_discover_images_sorted_deterministically(tmp_path):
    for name in ["c.jpg", "a.jpg", "b.jpg"]:
        _touch(tmp_path / name)

    found = discover.discover_images(tmp_path)

    assert [p.name for p in found] == ["a.jpg", "b.jpg", "c.jpg"]
