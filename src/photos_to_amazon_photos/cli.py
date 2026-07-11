"""Argument parsing, orchestration, and run summary. See docs/design.md Section 8."""

import argparse
import logging
import subprocess
import sys
from datetime import datetime
from pathlib import Path

from photos_to_amazon_photos import stager

LOG_LEVELS = ["DEBUG", "INFO", "WARNING", "ERROR"]

_OUTCOME_ORDER = [
    stager.COPIED,
    stager.WOULD_STAGE,
    stager.SKIPPED_COPIED,
    stager.SKIPPED_IGNORED,
    stager.ERROR,
]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="photos-to-amazon-photos",
        description=(
            "Stage photos, videos, and Live Photos from a local macOS Photos library "
            "into a date-organized directory tree for upload to Amazon Photos "
            "(and S3/Glacier for video)."
        ),
    )
    parser.add_argument(
        "library_path",
        type=Path,
        help="Path to a single Photos library (.photoslibrary package).",
    )
    parser.add_argument(
        "target_root",
        type=Path,
        help="Root target directory to stage into (created if it does not exist).",
    )
    parser.add_argument(
        "--tracking-file",
        type=Path,
        default=None,
        help="Override the default tracking file location (<target_root>/tracking.csv).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Compute and log planned actions without writing any files or the tracking file.",
    )
    parser.add_argument(
        "--log-level",
        choices=LOG_LEVELS,
        default="INFO",
        help="Logging verbosity (default: INFO).",
    )
    return parser


_OWN_HANDLER_NAMES = ("photos_to_amazon_photos.stream", "photos_to_amazon_photos.file")


def _setup_logging(log_level: str) -> Path:
    """Log to both stdout and a timestamped file in the current directory, so a run's progress
    survives even if the terminal session is lost (e.g. the Mac shuts down unexpectedly) before
    it can be checked. Returns the log file path.

    Manages the root logger's handlers directly rather than using logging.basicConfig(), which
    only offers an all-or-nothing force=True that would strip out handlers other tools attach
    to the root logger (e.g. pytest's caplog fixture) -- this removes and closes only the
    handlers *this function* previously added (identified by name), so repeated calls (a second
    real run in a long-lived process, or simply the test suite) get a fresh, correctly-pointed
    file handler without disturbing anything else on the root logger.
    """
    log_file = Path.cwd() / f"photos-to-amazon-photos-{datetime.now():%Y%m%d-%H%M%S}.log"
    formatter = logging.Formatter("%(asctime)s %(levelname)s %(message)s")

    stream_handler = logging.StreamHandler(sys.stdout)
    stream_handler.setFormatter(formatter)
    stream_handler.name = "photos_to_amazon_photos.stream"

    file_handler = logging.FileHandler(log_file)
    file_handler.setFormatter(formatter)
    file_handler.name = "photos_to_amazon_photos.file"

    root = logging.getLogger()
    for handler in list(root.handlers):
        if handler.name in _OWN_HANDLER_NAMES:
            root.removeHandler(handler)
            handler.close()

    root.addHandler(stream_handler)
    root.addHandler(file_handler)
    root.setLevel(getattr(logging, log_level))

    return log_file


def _photos_app_running() -> bool:
    try:
        result = subprocess.run(["pgrep", "-x", "Photos"], capture_output=True)
        return result.returncode == 0
    except OSError:
        return False


def _format_summary(summary: stager.RunSummary, dry_run: bool) -> str:
    label = "Dry-run summary" if dry_run else "Run summary"
    media_types = sorted({media_type for media_type, _outcome in summary.counts})
    lines = [f"{label}:"]
    if not media_types:
        lines.append("  (nothing to do)")
    for media_type in media_types:
        parts = [
            f"{outcome}={summary.counts[(media_type, outcome)]}"
            for outcome in _OUTCOME_ORDER
            if summary.counts.get((media_type, outcome))
        ]
        lines.append(f"  {media_type}: " + ", ".join(parts))
    lines.append(f"  total: {summary.total()}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    log_file = _setup_logging(args.log_level)
    log = logging.getLogger("photos_to_amazon_photos")
    log.info("Logging to: %s", log_file)

    if not args.library_path.is_dir():
        parser.error(f"library_path does not exist or is not a directory: {args.library_path}")

    tracking_file = args.tracking_file or (args.target_root / "tracking.csv")
    log.debug("library_path=%s", args.library_path)
    log.debug("target_root=%s", args.target_root)
    log.debug("tracking_file=%s", tracking_file)
    log.debug("dry_run=%s", args.dry_run)

    if _photos_app_running():
        log.warning(
            "Photos.app appears to be running. Reading the Photos library while it's open is "
            "not officially supported by Apple, though limited empirical testing found no "
            "issues (docs/design.md Section 11.6). Recommended: quit Photos.app first, "
            "especially for a long run. Proceeding anyway."
        )

    try:
        summary = stager.run(
            args.library_path,
            args.target_root,
            tracking_file,
            dry_run=args.dry_run,
        )
    except Exception as e:
        # A failure here means the library itself couldn't be opened/read at all -- distinct
        # from FR-10's per-asset error handling inside stager.run(), which already contains
        # per-asset failures without raising. This is a precondition failure, not something to
        # retry per-asset.
        log.error("failed to open or read the library: %s", e)
        return 1

    summary_text = _format_summary(summary, args.dry_run)
    print(summary_text)
    # Always written to the log file too, regardless of --log-level -- this is the one thing
    # most worth having survive an unexpectedly-interrupted session (print() alone wouldn't
    # reach the file handler, since it doesn't go through the logging system).
    with log_file.open("a") as f:
        f.write(summary_text + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
