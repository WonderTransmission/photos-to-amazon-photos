import logging

import numpy as np
from conftest import marker_image
from test_infer import FakeSession

from orientation_correction import cli, ignore_list

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


def test_run_skips_files_on_the_ignore_list(tmp_path, monkeypatch):
    a = tmp_path / "a.jpg"
    b = tmp_path / "b.jpg"
    marker_image(60, 30, "top-left").save(a, format="JPEG", quality=95)
    marker_image(60, 30, "top-left").save(b, format="JPEG", quality=95)

    ignore_path = tmp_path / "ignore-list.txt"
    ignore_list.append(ignore_path, [a])

    # class 1 -> needs 90 CW correction, high confidence -- would flag both if not ignored
    session = FakeSession([np.array([0.0, 10.0, 0.0, 0.0], dtype=np.float32)])
    monkeypatch.setattr(cli.infer, "load_onnx_session", lambda path: session)

    args = _make_args(tmp_path, ignore_list=ignore_path)
    log = logging.getLogger("test_run_skips_ignored")

    counts = cli.run(args, log, RUN_TS)

    assert counts[cli.SKIPPED_IGNORED] == 1
    assert counts[cli.DISCOVERED] == 2
    # only b was actually run through inference
    assert counts[cli.WOULD_CORRECT] == 1


def test_run_writes_review_checklist_when_something_is_flagged(tmp_path, monkeypatch):
    a = tmp_path / "a.jpg"
    marker_image(60, 30, "top-left").save(a, format="JPEG", quality=95)

    session = FakeSession([np.array([0.0, 10.0, 0.0, 0.0], dtype=np.float32)])
    monkeypatch.setattr(cli.infer, "load_onnx_session", lambda path: session)

    args = _make_args(tmp_path)
    log = logging.getLogger("test_run_writes_review_checklist")

    cli.run(args, log, RUN_TS)

    review_file = args.log_dir / RUN_TS / "review.txt"
    assert review_file.exists()
    assert str(a) in review_file.read_text()


def test_run_writes_no_review_checklist_when_nothing_flagged(tmp_path, monkeypatch):
    a = tmp_path / "a.jpg"
    marker_image(60, 30, "top-left").save(a, format="JPEG", quality=95)

    # class 0 -> already upright, nothing to flag
    session = FakeSession([np.array([10.0, 0.0, 0.0, 0.0], dtype=np.float32)])
    monkeypatch.setattr(cli.infer, "load_onnx_session", lambda path: session)

    args = _make_args(tmp_path)
    log = logging.getLogger("test_run_no_review_checklist")

    cli.run(args, log, RUN_TS)

    assert not (args.log_dir / RUN_TS / "review.txt").exists()


def test_run_places_all_output_under_the_runs_own_directory(tmp_path, monkeypatch):
    """The point of this whole layout: everything a run produces -- log, preview-links
    script(s), review checklist, dividers -- lands under one timestamped directory, with
    dividers further nested in their own subdirectory beneath that."""
    a = tmp_path / "a.jpg"
    marker_image(60, 30, "top-left").save(a, format="JPEG", quality=95)

    session = FakeSession([np.array([0.0, 10.0, 0.0, 0.0], dtype=np.float32)])
    monkeypatch.setattr(cli.infer, "load_onnx_session", lambda path: session)

    args = _make_args(tmp_path)
    log = logging.getLogger("test_run_single_directory")

    cli.run(args, log, RUN_TS)

    run_dir = args.log_dir / RUN_TS
    assert (run_dir / "preview-links-would-correct.sh").exists()
    assert (run_dir / "review.txt").exists()
    assert (run_dir / "dividers").is_dir()
    assert list((run_dir / "dividers").glob("*.png"))
    # nothing from this run leaked into a sibling directory
    assert list(args.log_dir.iterdir()) == [run_dir]


def test_main_places_all_output_under_one_timestamped_run_directory(tmp_path, monkeypatch):
    photos_dir = tmp_path / "photos"
    photos_dir.mkdir()
    marker_image(60, 30, "top-left").save(photos_dir / "a.jpg", format="JPEG", quality=95)

    model_path = tmp_path / "fake_model.onnx"
    model_path.write_bytes(b"existence check only, never actually loaded")

    session = FakeSession([np.array([0.0, 10.0, 0.0, 0.0], dtype=np.float32)])
    monkeypatch.setattr(cli.infer, "load_onnx_session", lambda path: session)

    log_dir = tmp_path / "logs"
    exit_code = cli.main(
        [
            str(photos_dir),
            "--model-path",
            str(model_path),
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

    assert (run_dir / "orientation-correction.log").exists()
    assert (run_dir / "preview-links-would-correct.sh").exists()
    assert (run_dir / "review.txt").exists()
    assert (run_dir / "dividers").is_dir()
    assert list((run_dir / "dividers").glob("*.png"))
