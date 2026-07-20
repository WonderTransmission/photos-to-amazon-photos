"""Argument parsing and run orchestration.

Scans a directory for images, flags totally overexposed / totally underexposed / extremely
blurry photos via CleanVision, and either previews what would be flagged (dry-run, the default)
or quarantines the flagged files into a `_quality_review/<category>/` subfolder alongside each
one's original directory (--apply). Mirrors orientation_correction's scan / dry-run / --apply /
preview-links shape, minus the parts specific to actually correcting pixels.
"""

import argparse
import logging
import sys
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

from PIL import Image

from image_quality_detector import analyze, discover, ignore_list, preview_links, quarantine

LOG_LEVELS = ["DEBUG", "INFO", "WARNING", "ERROR"]
RUN_TIMESTAMP_FORMAT = "%Y%m%dT%H%M%S"

_DEFAULT_LOG_DIR = Path("logs")

DISCOVERED = "discovered"
SKIPPED_IGNORED = "skipped_ignored"
NO_ISSUES = "no_issues"
WOULD_QUARANTINE = "would_quarantine"
QUARANTINED = "quarantined"
ERROR = "error"

_OUTCOME_ORDER = [
    DISCOVERED,
    SKIPPED_IGNORED,
    NO_ISSUES,
    WOULD_QUARANTINE,
    QUARANTINED,
    ERROR,
]

_OWN_HANDLER_NAMES = ("image_quality_detector.stream", "image_quality_detector.file")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="image-quality-detect",
        description=(
            "Finds totally overexposed, totally underexposed, and extremely blurry photos "
            "under a directory and quarantines them into a _quality_review/<category>/ "
            "subfolder alongside each one's original location. Dry-run by default -- pass "
            "--apply to actually move files."
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
        help="Actually quarantine flagged files. Without this, only logs and preview-links "
        "are produced -- no files are moved.",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=1,
        help="Parallel worker processes for CleanVision's analysis (default: 1). CleanVision "
        "uses Python multiprocessing internally, which only works reliably when this tool is "
        "run as an installed command (not e.g. piped via `python -c`) -- leave at 1 if unsure.",
    )
    parser.add_argument(
        "--ignore-list",
        type=Path,
        default=ignore_list.DEFAULT_PATH,
        help=f"Path to the persistent ignore list of confirmed false positives (default: "
        f"{ignore_list.DEFAULT_PATH}, relative to the current directory). Populated via "
        "`python -m image_quality_detector.revert`.",
    )
    parser.add_argument(
        "--log-dir",
        type=Path,
        default=_DEFAULT_LOG_DIR,
        help=f"Root directory for run output (default: {_DEFAULT_LOG_DIR}, relative to the "
        "current directory). Each run creates its own timestamped subdirectory here, holding "
        "the run log, preview-links scripts, review checklist, and a dividers/ subdirectory.",
    )
    parser.add_argument(
        "--log-level",
        choices=LOG_LEVELS,
        default="INFO",
        help="Logging verbosity (default: INFO).",
    )
    return parser


def _setup_logging(run_dir: Path, log_level: str) -> Path:
    """Log to both stdout and a file in this run's own timestamped directory, so a run's progress
    survives even if the terminal session is lost before it can be checked. Manages the root
    logger's own-named handlers directly so repeated calls (tests, or a second run in one
    process) get a fresh file handler without disturbing anything else on the root logger."""
    run_dir.mkdir(parents=True, exist_ok=True)
    log_file = run_dir / "image-quality-detect.log"
    formatter = logging.Formatter("%(asctime)s %(levelname)s %(message)s")

    stream_handler = logging.StreamHandler(sys.stdout)
    stream_handler.setFormatter(formatter)
    stream_handler.name = "image_quality_detector.stream"

    file_handler = logging.FileHandler(log_file)
    file_handler.setFormatter(formatter)
    file_handler.name = "image_quality_detector.file"

    root = logging.getLogger()
    for handler in list(root.handlers):
        if handler.name in _OWN_HANDLER_NAMES:
            root.removeHandler(handler)
            handler.close()

    root.addHandler(stream_handler)
    root.addHandler(file_handler)
    root.setLevel(getattr(logging, log_level))

    return log_file


def _format_summary(counts: Counter, category_counts: Counter, dry_run: bool) -> str:
    label = "Dry-run summary" if dry_run else "Run summary"
    lines = [f"{label}:"]
    for outcome in _OUTCOME_ORDER:
        if counts.get(outcome):
            lines.append(f"  {outcome}: {counts[outcome]}")
    if category_counts:
        lines.append("Matched by category:")
        for key in sorted(category_counts, key=lambda k: (-category_counts[k], k)):
            lines.append(f"  {key}: {category_counts[key]}")
    return "\n".join(lines)


def _write_error_filenames(run_dir: Path, error_paths: list[Path]) -> Path | None:
    """One path per line for every file that failed this run (decode or quarantine failure
    alike), so a large run's handful of failures don't have to be picked out of the full log by
    hand. Returns None (and writes nothing) if nothing failed."""
    if not error_paths:
        return None
    output_path = run_dir / "error_filenames.txt"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text("\n".join(str(p) for p in error_paths) + "\n")
    return output_path


def run(
    args: argparse.Namespace, log: logging.Logger, run_timestamp: str
) -> tuple[Counter, Counter]:
    run_dir = args.log_dir / run_timestamp
    counts: Counter = Counter()
    category_counts: Counter = Counter()
    flagged_paths: list[Path] = []
    by_category: dict[str, list[Path]] = defaultdict(list)
    error_paths: list[Path] = []

    all_images = discover.discover_images(args.input_dir)
    counts[DISCOVERED] = len(all_images)
    log.info("Discovered %d image(s) under %s", len(all_images), args.input_dir)

    ignored = ignore_list.load(args.ignore_list)
    to_check = all_images
    if ignored:
        before = len(to_check)
        to_check = [p for p in to_check if p.resolve() not in ignored]
        counts[SKIPPED_IGNORED] = before - len(to_check)
        if counts[SKIPPED_IGNORED]:
            log.info(
                "Skipping %d image(s) on the ignore list (%s)",
                counts[SKIPPED_IGNORED],
                args.ignore_list,
            )

    if not to_check:
        log.info("Nothing left to check.")
        return counts, category_counts

    results, load_errors = analyze.analyze_images(to_check, n_jobs=args.workers)

    for path, exc in load_errors:
        log.error("Failed to analyze %s: %s", path, exc)
        counts[ERROR] += 1
        error_paths.append(path)

    for result in results:
        if not result.has_issue:
            counts[NO_ISSUES] += 1
            continue

        category_counts[result.category_key] += 1

        if not args.apply:
            counts[WOULD_QUARANTINE] += 1
            flagged_paths.append(result.path)
            by_category[result.category_key].append(result.path)
            log.debug("Would quarantine %s (%s)", result.path, result.category_key)
            continue

        try:
            dest = quarantine.quarantine_image(result.path, result.category_key)
            counts[QUARANTINED] += 1
            flagged_paths.append(result.path)
            by_category[result.category_key].append(dest)
            log.debug("Quarantined %s -> %s", result.path, dest)
        except Exception as exc:  # noqa: BLE001 - one bad file must not abort the run
            log.error("Failed to quarantine %s: %s", result.path, exc)
            counts[ERROR] += 1
            error_paths.append(result.path)

    divider_dir = run_dir / "dividers"
    mode = "quarantined" if args.apply else "would-quarantine"
    preview_link_paths = preview_links.write_preview_links(
        run_dir, mode=mode, by_category=by_category, divider_dir=divider_dir
    )
    if preview_link_paths:
        for path in preview_link_paths:
            log.info("Preview-links script written to: %s", path)
    else:
        log.info("Nothing flagged this run -- no preview-links scripts written.")

    review_path = run_dir / "review.txt"
    wrote_review = preview_links.write_review_checklist(
        review_path,
        flagged=flagged_paths,
        revert_command=f"python -m image_quality_detector.revert {review_path} "
        f"--ignore-list {args.ignore_list}",
    )
    if wrote_review:
        log.info(
            "Review checklist written to: %s -- delete the lines for files that are genuinely "
            "bad, then run the revert command shown inside it on what's left",
            review_path,
        )

    error_filenames_path = _write_error_filenames(run_dir, error_paths)
    if error_filenames_path:
        log.info("Failed file paths written to: %s", error_filenames_path)

    return counts, category_counts


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    run_timestamp = datetime.now().strftime(RUN_TIMESTAMP_FORMAT)
    run_dir = args.log_dir / run_timestamp
    log_file = _setup_logging(run_dir, args.log_level)
    log = logging.getLogger("image_quality_detector")
    log.info("Logging to: %s", log_file)
    log.info("Mode: %s", "APPLY (files will be quarantined)" if args.apply else "DRY RUN")

    if not args.input_dir.is_dir():
        parser.error(f"input_dir does not exist or is not a directory: {args.input_dir}")

    Image.MAX_IMAGE_PIXELS = None  # staged archive photos are trusted, not untrusted uploads

    try:
        counts, category_counts = run(args, log, run_timestamp)
    except Exception as e:
        log.error("Run failed: %s", e)
        return 1

    summary_text = _format_summary(counts, category_counts, dry_run=not args.apply)
    print(summary_text)
    with log_file.open("a") as f:
        f.write(summary_text + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
