import logging

import numpy as np

from orientation_correction import cli, ignore_list
from tests.conftest import marker_image
from tests.test_infer import FakeSession


def _make_args(tmp_path, **overrides):
    input_dir = overrides.pop("input_dir", tmp_path)
    parser = cli.build_parser()
    args = parser.parse_args([str(input_dir)])
    args.log_dir = tmp_path / "logs"
    args.ignore_list = tmp_path / "ignore-list.txt"
    for key, value in overrides.items():
        setattr(args, key, value)
    args.log_dir.mkdir(parents=True, exist_ok=True)  # normally cli.main() does this
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

    counts = cli.run(args, log)

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

    cli.run(args, log)

    review_files = list(args.log_dir.glob("review-*.txt"))
    assert len(review_files) == 1
    assert str(a) in review_files[0].read_text()


def test_run_writes_no_review_checklist_when_nothing_flagged(tmp_path, monkeypatch):
    a = tmp_path / "a.jpg"
    marker_image(60, 30, "top-left").save(a, format="JPEG", quality=95)

    # class 0 -> already upright, nothing to flag
    session = FakeSession([np.array([10.0, 0.0, 0.0, 0.0], dtype=np.float32)])
    monkeypatch.setattr(cli.infer, "load_onnx_session", lambda path: session)

    args = _make_args(tmp_path)
    log = logging.getLogger("test_run_no_review_checklist")

    cli.run(args, log)

    assert list(args.log_dir.glob("review-*.txt")) == []
