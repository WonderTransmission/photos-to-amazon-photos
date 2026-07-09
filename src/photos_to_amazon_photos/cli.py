"""Argument parsing, orchestration, and run summary. See docs/design.md Section 8."""

import argparse
import logging
import sys
from pathlib import Path

LOG_LEVELS = ["DEBUG", "INFO", "WARNING", "ERROR"]


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


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s %(levelname)s %(message)s",
    )
    log = logging.getLogger("photos_to_amazon_photos")

    if not args.library_path.is_dir():
        parser.error(f"library_path does not exist or is not a directory: {args.library_path}")

    tracking_file = args.tracking_file or (args.target_root / "tracking.csv")
    log.debug("library_path=%s", args.library_path)
    log.debug("target_root=%s", args.target_root)
    log.debug("tracking_file=%s", tracking_file)
    log.debug("dry_run=%s", args.dry_run)

    log.error(
        "Staging is not yet implemented (Milestones 2-3 of docs/tasks.md). "
        "This is scaffolding only: argument parsing and validation succeeded."
    )
    return 1


if __name__ == "__main__":
    sys.exit(main())
