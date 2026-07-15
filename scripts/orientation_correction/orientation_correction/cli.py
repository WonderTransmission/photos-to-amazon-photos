"""Argument parsing and run orchestration. See docs/how-it-works.md."""

import argparse
import logging
import sys
from collections import Counter
from collections.abc import Iterator
from datetime import datetime
from pathlib import Path

from PIL import Image

from orientation_correction import correct, discover, infer, naming, preview_links

LOG_LEVELS = ["DEBUG", "INFO", "WARNING", "ERROR"]
PROGRESS_LOG_INTERVAL_PERCENT = 5

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_DEFAULT_MODEL_PATH = _PROJECT_ROOT / "models" / "best_model.onnx"
_DEFAULT_LOG_DIR = _PROJECT_ROOT / "logs"

DISCOVERED = "discovered"
SKIPPED_ALREADY_CORRECTED = "skipped_already_corrected"
NO_ACTION_NEEDED = "no_action_needed"
WOULD_CORRECT = "would_correct"
CORRECTED = "corrected"
LOW_CONFIDENCE_FLAGGED = "low_confidence_flagged"
ERROR = "error"

_OUTCOME_ORDER = [
    DISCOVERED,
    SKIPPED_ALREADY_CORRECTED,
    NO_ACTION_NEEDED,
    WOULD_CORRECT,
    CORRECTED,
    LOW_CONFIDENCE_FLAGGED,
    ERROR,
]

_OWN_HANDLER_NAMES = ("orientation_correction.stream", "orientation_correction.file")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="orientation-correct",
        description=(
            "Detects sideways/upside-down photos under a directory and corrects them in place, "
            "backing up each original alongside it first. Dry-run by default -- pass --apply to "
            "actually modify files."
        ),
    )
    parser.add_argument(
        "input_dir",
        type=Path,
        help="Directory to scan recursively for png/jpg/jpeg/heic images.",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Actually back up and correct files. Without this, only logs and preview-links "
        "are produced -- no files are modified.",
    )
    parser.add_argument(
        "--model-path",
        type=Path,
        default=_DEFAULT_MODEL_PATH,
        help=f"Path to the ONNX orientation model (default: {_DEFAULT_MODEL_PATH}).",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=16,
        help="Images per inference batch (default: 16).",
    )
    parser.add_argument(
        "--jpeg-quality",
        type=int,
        default=correct.DEFAULT_JPEG_QUALITY,
        help=f"JPEG re-encode quality, 1-95 (default: {correct.DEFAULT_JPEG_QUALITY}).",
    )
    parser.add_argument(
        "--heif-quality",
        type=int,
        default=correct.DEFAULT_HEIF_QUALITY,
        help=f"HEIC re-encode quality, 1-100 (default: {correct.DEFAULT_HEIF_QUALITY}).",
    )
    parser.add_argument(
        "--min-confidence",
        type=float,
        default=0.0,
        help="Minimum model confidence (0-1) required to auto-correct a flagged image. Images "
        "predicted as needing rotation but below this are left untouched and listed separately "
        "in the preview-links file for manual review. Default 0.0 (no filtering).",
    )
    parser.add_argument(
        "--log-dir",
        type=Path,
        default=_DEFAULT_LOG_DIR,
        help=f"Where to write the run log and preview-links file (default: {_DEFAULT_LOG_DIR}).",
    )
    parser.add_argument(
        "--log-level",
        choices=LOG_LEVELS,
        default="INFO",
        help="Logging verbosity (default: INFO).",
    )
    return parser


def _setup_logging(log_dir: Path, log_level: str, run_timestamp: str) -> Path:
    """Log to both stdout and a timestamped file, so a run's progress survives even if the
    terminal session is lost before it can be checked. Mirrors photos_to_amazon_photos.cli's
    approach: manages the root logger's own-named handlers directly so repeated calls (tests, or
    a second run in one process) get a fresh file handler without disturbing anything else on
    the root logger."""
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / f"orientation-correction-{run_timestamp}.log"
    formatter = logging.Formatter("%(asctime)s %(levelname)s %(message)s")

    stream_handler = logging.StreamHandler(sys.stdout)
    stream_handler.setFormatter(formatter)
    stream_handler.name = "orientation_correction.stream"

    file_handler = logging.FileHandler(log_file)
    file_handler.setFormatter(formatter)
    file_handler.name = "orientation_correction.file"

    root = logging.getLogger()
    for handler in list(root.handlers):
        if handler.name in _OWN_HANDLER_NAMES:
            root.removeHandler(handler)
            handler.close()

    root.addHandler(stream_handler)
    root.addHandler(file_handler)
    root.setLevel(getattr(logging, log_level))

    return log_file


def _chunks(items: list[Path], size: int) -> Iterator[list[Path]]:
    for start in range(0, len(items), size):
        yield items[start : start + size]


def _format_summary(counts: Counter, dry_run: bool) -> str:
    label = "Dry-run summary" if dry_run else "Run summary"
    lines = [f"{label}:"]
    for outcome in _OUTCOME_ORDER:
        if counts.get(outcome):
            lines.append(f"  {outcome}: {counts[outcome]}")
    return "\n".join(lines)


def run(args: argparse.Namespace, log: logging.Logger) -> Counter:
    counts: Counter = Counter()
    corrected_paths: list[Path] = []
    would_correct_paths: list[Path] = []
    low_confidence_paths: list[Path] = []

    all_images = discover.discover_images(args.input_dir)
    counts[DISCOVERED] = len(all_images)
    log.info("Discovered %d image(s) under %s", len(all_images), args.input_dir)

    to_infer = [p for p in all_images if not correct.already_corrected(p)]
    counts[SKIPPED_ALREADY_CORRECTED] = len(all_images) - len(to_infer)
    if counts[SKIPPED_ALREADY_CORRECTED]:
        log.info(
            "Skipping %d image(s) already corrected by a previous run",
            counts[SKIPPED_ALREADY_CORRECTED],
        )

    if not to_infer:
        log.info("Nothing left to check.")
        return counts

    session = infer.load_onnx_session(args.model_path)
    run_timestamp = datetime.now().strftime(naming.BACKUP_TIMESTAMP_FORMAT)

    total = len(to_infer)
    processed = 0
    last_logged_percent = 0

    for batch in _chunks(to_infer, args.batch_size):
        predictions, errors = infer.predict_batch(session, batch)

        for path, exc in errors:
            log.error("Failed to process %s: %s", path, exc)
            counts[ERROR] += 1

        for pred in predictions:
            if not pred.needs_correction:
                counts[NO_ACTION_NEEDED] += 1
                continue

            if pred.confidence < args.min_confidence:
                log.warning(
                    "Low confidence (%.2f < %.2f) for %s -- flagged for manual review, not "
                    "auto-corrected",
                    pred.confidence,
                    args.min_confidence,
                    pred.path,
                )
                counts[LOW_CONFIDENCE_FLAGGED] += 1
                low_confidence_paths.append(pred.path)
                continue

            rotate_op = infer.rotate_op_for_degrees(pred.corrective_rotation_degrees)

            if not args.apply:
                counts[WOULD_CORRECT] += 1
                would_correct_paths.append(pred.path)
                log.debug(
                    "Would correct %s (%d deg CW, confidence %.2f)",
                    pred.path,
                    pred.corrective_rotation_degrees,
                    pred.confidence,
                )
                continue

            try:
                correct.correct_image(
                    pred.path,
                    rotate_op,
                    run_timestamp,
                    jpeg_quality=args.jpeg_quality,
                    heif_quality=args.heif_quality,
                )
                counts[CORRECTED] += 1
                corrected_paths.append(pred.path)
                log.debug(
                    "Corrected %s (%d deg CW, confidence %.2f)",
                    pred.path,
                    pred.corrective_rotation_degrees,
                    pred.confidence,
                )
            except Exception as exc:  # noqa: BLE001 - one bad file must not abort the run
                log.error("Failed to correct %s: %s", pred.path, exc)
                counts[ERROR] += 1

        processed += len(batch)
        percent = (processed * 100) // total
        milestone = (percent // PROGRESS_LOG_INTERVAL_PERCENT) * PROGRESS_LOG_INTERVAL_PERCENT
        if milestone > last_logged_percent:
            last_logged_percent = milestone
            log.info("Progress: %d%% (%d/%d images)", milestone, processed, total)

    preview_links_path = args.log_dir / f"preview-links-{run_timestamp}.sh"
    preview_links.write_preview_links(
        preview_links_path,
        corrected=corrected_paths,
        would_correct=would_correct_paths,
        low_confidence=low_confidence_paths,
    )
    log.info("Preview-links script written to: %s", preview_links_path)

    return counts


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    run_timestamp = datetime.now().strftime(naming.BACKUP_TIMESTAMP_FORMAT)
    log_file = _setup_logging(args.log_dir, args.log_level, run_timestamp)
    log = logging.getLogger("orientation_correction")
    log.info("Logging to: %s", log_file)
    log.info("Mode: %s", "APPLY (files will be modified)" if args.apply else "DRY RUN")

    if not args.input_dir.is_dir():
        parser.error(f"input_dir does not exist or is not a directory: {args.input_dir}")

    if not args.model_path.exists():
        log.error(
            "ONNX model not found at %s -- see models/README.md for how to obtain it.",
            args.model_path,
        )
        return 1

    Image.MAX_IMAGE_PIXELS = None  # staged archive photos are trusted, not untrusted uploads

    try:
        counts = run(args, log)
    except Exception as e:
        log.error("Run failed: %s", e)
        return 1

    summary_text = _format_summary(counts, dry_run=not args.apply)
    print(summary_text)
    with log_file.open("a") as f:
        f.write(summary_text + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
