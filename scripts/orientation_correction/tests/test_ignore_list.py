from orientation_correction import ignore_list


def test_load_returns_empty_set_when_file_missing(tmp_path):
    assert ignore_list.load(tmp_path / "nope.txt") == set()


def test_append_then_load_round_trips(tmp_path):
    path = tmp_path / "ignore.txt"
    a = tmp_path / "a.jpg"
    b = tmp_path / "sub" / "b.jpg"

    ignore_list.append(path, [a, b])

    assert ignore_list.load(path) == {a.resolve(), b.resolve()}


def test_append_is_idempotent(tmp_path):
    path = tmp_path / "ignore.txt"
    a = tmp_path / "a.jpg"

    ignore_list.append(path, [a])
    ignore_list.append(path, [a])

    assert ignore_list.load(path) == {a.resolve()}
    # one entry, not duplicated
    non_comment_lines = [
        line for line in path.read_text().splitlines() if line.strip() and not line.startswith("#")
    ]
    assert len(non_comment_lines) == 1


def test_append_merges_with_existing_entries(tmp_path):
    path = tmp_path / "ignore.txt"
    a = tmp_path / "a.jpg"
    b = tmp_path / "b.jpg"

    ignore_list.append(path, [a])
    ignore_list.append(path, [b])

    assert ignore_list.load(path) == {a.resolve(), b.resolve()}


def test_load_ignores_blank_lines_and_comments(tmp_path):
    path = tmp_path / "ignore.txt"
    a = (tmp_path / "a.jpg").resolve()
    path.write_text(f"# a comment\n\n{a}\n\n# another\n")

    assert ignore_list.load(path) == {a}
