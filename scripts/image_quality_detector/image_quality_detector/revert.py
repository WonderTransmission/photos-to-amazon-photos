"""Reverts confirmed false positives from a trimmed review checklist (see preview_links.py) and
adds them to the persistent ignore list, so future runs never re-flag them.

    python -m image_quality_detector.revert review-<timestamp>.txt
"""

import argparse
import logging
import sys
from collections import Counter
from pathlib import Path

from image_quality_detector import ignore_list, naming

log = logging.getLogger(__name__)

REVERTED = "reverted"
NO_QUARANTINE_FOUND = "no_quarantine_found"


def parse_review_file(path: Path) -> list[Path]:
    entries = []
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        entries.append(Path(line))
    return entries


def revert_entries(entries: list[Path], ignore_list_path: Path) -> Counter:
    """For each entry: if it has a quarantined copy, moves it back to its original filename
    (consuming the quarantine copy) and logs REVERTED. If not -- e.g. a dry-run candidate that
    was never actually quarantined -- logs NO_QUARANTINE_FOUND but still adds it to the ignore
    list, since the point is the same either way: a human looked at this file and said "don't
    flag this one again"."""
    counts: Counter = Counter()

    for entry in entries:
        path = entry.resolve()
        quarantined = naming.find_quarantined(path)
        if quarantined is None:
            log.warning(
                "No quarantined copy found for %s -- adding to ignore list without reverting",
                path,
            )
            counts[NO_QUARANTINE_FOUND] += 1
            continue

        quarantined.replace(path)
        log.info("Reverted %s from %s", path, quarantined)
        counts[REVERTED] += 1

    ignore_list.append(ignore_list_path, entries)
    return counts


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="image-quality-detect-revert",
        description=(
            "Reverts confirmed false positives from a trimmed review checklist (see "
            "preview_links.py) and adds them to the persistent ignore list so future runs "
            "never re-flag them."
        ),
    )
    parser.add_argument(
        "review_file",
        type=Path,
        help="Path to a review checklist with the confirmed-wrong lines left in it (everything "
        "else deleted).",
    )
    parser.add_argument(
        "--ignore-list",
        type=Path,
        default=ignore_list.DEFAULT_PATH,
        help=f"Path to the persistent ignore list (default: {ignore_list.DEFAULT_PATH}, "
        "relative to the current directory -- must match what you pass to image-quality-detect).",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    parser = build_parser()
    args = parser.parse_args(argv)

    if not args.review_file.is_file():
        parser.error(f"review_file does not exist: {args.review_file}")

    entries = parse_review_file(args.review_file)
    if not entries:
        log.info("No entries in %s -- nothing to do.", args.review_file)
        return 0

    counts = revert_entries(entries, args.ignore_list)

    print(f"Reverted: {counts[REVERTED]}")
    if counts[NO_QUARANTINE_FOUND]:
        print(
            "No quarantined copy found (added to ignore list anyway): "
            f"{counts[NO_QUARANTINE_FOUND]}"
        )
    print(f"Ignore list updated: {args.ignore_list}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
