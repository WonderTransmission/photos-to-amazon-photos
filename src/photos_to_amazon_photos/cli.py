"""Argument parsing, orchestration, and run summary. See docs/design.md Section 8."""

import argparse
import logging
import subprocess
import sys
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

    print(_format_summary(summary, args.dry_run))
    return 0


if __name__ == "__main__":
    sys.exit(main())
