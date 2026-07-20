import logging

from image_quality_detector import cli, ignore_list
from image_quality_detector.analyze import QualityResult

RUN_TS = "20260717T120000"


def _make_args(tmp_path, **overrides):
    input_dir = overrides.pop("input_dir", tmp_path)
    parser = cli.build_parser()
    args = parser.parse_args([str(input_dir)])
    args.log_dir = tmp_path / "logs"
    args.ignore_list = tmp_path / "ignore-list.txt"
    for key, value in overrides.items():
        setattr(args, key, value)
    return args


def _fake_analyze(mapping, errors=()):
    """mapping: {filename: (category, ...)}. Files not present in mapping get an empty match
    set (no issue). Files listed in `errors` get reported as decode failures instead."""

    def fake(paths, issue_types=None, *, n_jobs=1):
        results = []
        failed = []
        for path in paths:
            if path.name in errors:
                failed.append((path, ValueError("simulated decode failure")))
                continue
            results.append(QualityResult(path=path, matched=frozenset(mapping.get(path.name, ()))))
        return results, failed

    return fake


def test_run_skips_files_on_the_ignore_list(tmp_path, monkeypatch):
    a = tmp_path / "a.jpg"
    b = tmp_path / "b.jpg"
    a.write_bytes(b"x")
    b.write_bytes(b"x")

    ignore_path = tmp_path / "ignore-list.txt"
    ignore_list.append(ignore_path, [a])

    monkeypatch.setattr(
        cli.analyze, "analyze_images", _fake_analyze({"a.jpg": ("blurry",), "b.jpg": ("blurry",)})
    )

    args = _make_args(tmp_path, ignore_list=ignore_path)
    log = logging.getLogger("test_run_skips_ignored")

    counts, _ = cli.run(args, log, RUN_TS)

    assert counts[cli.SKIPPED_IGNORED] == 1
    assert counts[cli.DISCOVERED] == 2
    # only b was actually analyzed
    assert counts[cli.WOULD_QUARANTINE] == 1


def test_run_writes_review_checklist_when_something_is_flagged(tmp_path, monkeypatch):
    a = tmp_path / "a.jpg"
    a.write_bytes(b"x")

    monkeypatch.setattr(cli.analyze, "analyze_images", _fake_analyze({"a.jpg": ("blurry",)}))

    args = _make_args(tmp_path)
    log = logging.getLogger("test_run_writes_review_checklist")

    cli.run(args, log, RUN_TS)

    review_file = args.log_dir / RUN_TS / "review.txt"
    assert review_file.exists()
    assert str(a) in review_file.read_text()


def test_run_writes_no_review_checklist_when_nothing_flagged(tmp_path, monkeypatch):
    a = tmp_path / "a.jpg"
    a.write_bytes(b"x")

    monkeypatch.setattr(cli.analyze, "analyze_images", _fake_analyze({}))

    args = _make_args(tmp_path)
    log = logging.getLogger("test_run_no_review_checklist")

    cli.run(args, log, RUN_TS)

    assert not (args.log_dir / RUN_TS / "review.txt").exists()


def test_run_dry_run_does_not_move_files(tmp_path, monkeypatch):
    a = tmp_path / "a.jpg"
    a.write_bytes(b"x")

    monkeypatch.setattr(cli.analyze, "analyze_images", _fake_analyze({"a.jpg": ("dark",)}))

    args = _make_args(tmp_path)
    log = logging.getLogger("test_run_dry_run_no_move")

    counts, category_counts = cli.run(args, log, RUN_TS)

    assert a.exists()
    assert counts[cli.WOULD_QUARANTINE] == 1
    assert category_counts["dark"] == 1


def test_run_apply_quarantines_flagged_files(tmp_path, monkeypatch):
    a = tmp_path / "a.jpg"
    a.write_bytes(b"x")

    monkeypatch.setattr(cli.analyze, "analyze_images", _fake_analyze({"a.jpg": ("dark", "light")}))

    args = _make_args(tmp_path, apply=True)
    log = logging.getLogger("test_run_apply_quarantines")

    counts, category_counts = cli.run(args, log, RUN_TS)

    assert not a.exists()
    dest = tmp_path / "_quality_review" / "dark+light" / "a.jpg"
    assert dest.exists()
    assert counts[cli.QUARANTINED] == 1
    assert category_counts["dark+light"] == 1


def test_run_places_all_output_under_the_runs_own_directory(tmp_path, monkeypatch):
    a = tmp_path / "a.jpg"
    a.write_bytes(b"x")

    monkeypatch.setattr(cli.analyze, "analyze_images", _fake_analyze({"a.jpg": ("blurry",)}))

    args = _make_args(tmp_path)
    log = logging.getLogger("test_run_single_directory")

    cli.run(args, log, RUN_TS)

    run_dir = args.log_dir / RUN_TS
    assert (run_dir / "preview-links-blurry-would-quarantine.sh").exists()
    assert (run_dir / "review.txt").exists()
    assert (run_dir / "dividers").is_dir()
    assert list((run_dir / "dividers").glob("*.png"))
    # nothing from this run leaked into a sibling directory
    assert list(args.log_dir.iterdir()) == [run_dir]


def test_main_places_all_output_under_one_timestamped_run_directory(tmp_path, monkeypatch):
    photos_dir = tmp_path / "photos"
    photos_dir.mkdir()
    (photos_dir / "a.jpg").write_bytes(b"x")

    monkeypatch.setattr(cli.analyze, "analyze_images", _fake_analyze({"a.jpg": ("blurry",)}))

    log_dir = tmp_path / "logs"
    exit_code = cli.main(
        [
            str(photos_dir),
            "--log-dir",
            str(log_dir),
            "--ignore-list",
            str(tmp_path / "ignore-list.txt"),
        ]
    )

    assert exit_code == 0

    run_dirs = list(log_dir.iterdir())
    assert len(run_dirs) == 1  # one run -> one directory, no stray sibling files
    run_dir = run_dirs[0]

    assert (run_dir / "image-quality-detect.log").exists()
    assert (run_dir / "preview-links-blurry-would-quarantine.sh").exists()
    assert (run_dir / "review.txt").exists()
    assert (run_dir / "dividers").is_dir()
    assert list((run_dir / "dividers").glob("*.png"))


def test_write_error_filenames_returns_none_when_nothing_failed(tmp_path):
    assert cli._write_error_filenames(tmp_path, []) is None
    assert not (tmp_path / "error_filenames.txt").exists()


def test_write_error_filenames_writes_one_path_per_line(tmp_path):
    a = tmp_path / "a.jpg"
    b = tmp_path / "b.jpg"

    output = cli._write_error_filenames(tmp_path, [a, b])

    assert output == tmp_path / "error_filenames.txt"
    assert output.read_text() == f"{a}\n{b}\n"


def test_run_writes_error_filenames_for_a_decode_failure(tmp_path, monkeypatch):
    good = tmp_path / "good.jpg"
    good.write_bytes(b"x")
    bad = tmp_path / "bad.jpg"
    bad.write_bytes(b"not a real image")

    monkeypatch.setattr(
        cli.analyze, "analyze_images", _fake_analyze({"good.jpg": ("blurry",)}, errors={"bad.jpg"})
    )

    args = _make_args(tmp_path)
    log = logging.getLogger("test_run_error_filenames_decode_failure")

    counts, _ = cli.run(args, log, RUN_TS)

    assert counts[cli.ERROR] == 1
    error_file = args.log_dir / RUN_TS / "error_filenames.txt"
    assert error_file.exists()
    assert str(bad) in error_file.read_text()
    assert str(good) not in error_file.read_text()


def test_run_writes_error_filenames_for_a_quarantine_failure(tmp_path, monkeypatch):
    a = tmp_path / "a.jpg"
    a.write_bytes(b"x")

    monkeypatch.setattr(cli.analyze, "analyze_images", _fake_analyze({"a.jpg": ("blurry",)}))

    def boom(*args, **kwargs):
        raise OSError("simulated quarantine failure")

    monkeypatch.setattr(cli.quarantine, "quarantine_image", boom)

    args = _make_args(tmp_path, apply=True)
    log = logging.getLogger("test_run_error_filenames_quarantine_failure")

    counts, _ = cli.run(args, log, RUN_TS)

    assert counts[cli.ERROR] == 1
    error_file = args.log_dir / RUN_TS / "error_filenames.txt"
    assert error_file.read_text() == f"{a}\n"
    # a failed quarantine attempt shouldn't put the file on the review checklist -- there's
    # nothing to revert, and it wasn't a human judgment call
    review_file = args.log_dir / RUN_TS / "review.txt"
    assert not review_file.exists() or str(a) not in review_file.read_text()


def test_run_writes_no_error_filenames_file_when_nothing_failed(tmp_path, monkeypatch):
    a = tmp_path / "a.jpg"
    a.write_bytes(b"x")

    monkeypatch.setattr(cli.analyze, "analyze_images", _fake_analyze({"a.jpg": ("blurry",)}))

    args = _make_args(tmp_path)
    log = logging.getLogger("test_run_no_error_filenames")

    cli.run(args, log, RUN_TS)

    assert not (args.log_dir / RUN_TS / "error_filenames.txt").exists()
