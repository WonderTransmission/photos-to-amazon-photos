#!/usr/bin/env bash
#
# Remediates assets misplaced under _undated/ by the date-heuristic bug (see docs/tasks.md
# "PV1"). Finds tracking.csv rows with status=copied whose target_relative_path lives directly
# under a _undated/ directory, deletes those files (and, for a Live Photo's live_bundle row,
# its paired .mov/.MOV too), and clears the tracking rows so a normal re-run of the tool
# reprocesses them with the fixed heuristic into their correct dated folders.
#
# Safe by default: without --apply, this only REPORTS what it would do. Nothing is deleted or
# changed until you explicitly pass --apply. When --apply is used, tracking.csv is backed up
# (timestamped, alongside the original) before anything is touched.
#
# Usage:
#   bash remediate_undated.sh <target_root> [--tracking-file PATH] [--apply]
#
# Examples:
#   bash remediate_undated.sh /Volumes/Storage/photos_staging/Photos_2017-2024          # dry run
#   bash remediate_undated.sh /Volumes/Storage/photos_staging/Photos_2017-2024 --apply  # for real
#
# After a successful --apply run, re-run the normal tool against the same library/target_root
# to reprocess the cleared assets.

set -euo pipefail

REPO_URL="git+https://github.com/WonderTransmission/photos-to-amazon-photos.git"

TARGET_ROOT="${1:-}"
if [ -z "$TARGET_ROOT" ] || [ ! -d "$TARGET_ROOT" ]; then
  echo "Usage: bash remediate_undated.sh <target_root> [--tracking-file PATH] [--apply]"
  echo "  target_root must be an existing directory (the same one you staged into)."
  exit 1
fi
shift

PYBIN="$(command -v python3.14 || command -v python3)"
echo "Using Python: $PYBIN ($($PYBIN --version))"

VENV_DIR="$(mktemp -d)/venv"
"$PYBIN" -m venv "$VENV_DIR"
"$VENV_DIR/bin/pip" install -q --upgrade pip
echo "Installing the actual fixed package from the public repo..."
"$VENV_DIR/bin/pip" install -q "$REPO_URL"

trap 'rm -rf "$(dirname "$VENV_DIR")"' EXIT

"$VENV_DIR/bin/python" - "$TARGET_ROOT" "$@" <<'PYEOF'
import argparse
import shutil
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path

from photos_to_amazon_photos import tracking

parser = argparse.ArgumentParser()
parser.add_argument("target_root", type=Path)
parser.add_argument("--tracking-file", type=Path, default=None)
parser.add_argument("--apply", action="store_true")
args = parser.parse_args(sys.argv[1:])

tracking_path = args.tracking_file or (args.target_root / "tracking.csv")
if not tracking_path.exists():
    print(f"No tracking file found at {tracking_path}")
    sys.exit(1)

index = tracking.load(tracking_path)

affected = [
    row
    for row in index.rows()
    if row.status == tracking.COPIED and Path(row.target_relative_path).parent.name == "_undated"
]

if not affected:
    print("No affected rows found -- nothing currently staged under _undated/ with status=copied.")
    sys.exit(0)


def paired_motion_path(still_path: Path) -> Path | None:
    for ext in (".mov", ".MOV"):
        candidate = still_path.with_suffix(ext)
        if candidate.exists():
            return candidate
    return None


files_to_delete = []
total_bytes = 0
for row in affected:
    still = args.target_root / row.target_relative_path
    if still.exists():
        files_to_delete.append(still)
        total_bytes += still.stat().st_size
    if row.component == tracking.LIVE_BUNDLE:
        motion = paired_motion_path(still)
        if motion is not None:
            files_to_delete.append(motion)
            total_bytes += motion.stat().st_size

print(f"Found {len(affected)} tracking row(s) under _undated/ with status=copied.")
by_media_type = Counter(row.media_type for row in affected)
for media_type, count in sorted(by_media_type.items()):
    print(f"  {media_type}: {count} row(s)")
print(f"-> {len(files_to_delete)} file(s) to delete, {total_bytes / 1e6:.1f} MB total.")

print("\nSample of affected rows (up to 15):")
for row in affected[:15]:
    print(f"  {row.photo_uuid} ({row.component})  {row.target_relative_path}")
if len(affected) > 15:
    print(f"  ... and {len(affected) - 15} more")

if not args.apply:
    print("\nDRY RUN -- nothing was changed.")
    print("Re-run with --apply to actually delete these files and clear their tracking rows.")
    sys.exit(0)

backup_path = tracking_path.with_name(f"{tracking_path.name}.bak-{datetime.now():%Y%m%dT%H%M%S}")
shutil.copy2(tracking_path, backup_path)
print(f"\nBacked up tracking file to: {backup_path}")

deleted_count = 0
freed_bytes = 0
for f in files_to_delete:
    try:
        size = f.stat().st_size
        f.unlink()
        deleted_count += 1
        freed_bytes += size
    except OSError as e:
        print(f"  WARNING: failed to delete {f}: {e}")

for row in affected:
    index.remove(row.photo_uuid, row.component)
index.flush(tracking_path)

print(f"\nDeleted {deleted_count} file(s), freed {freed_bytes / 1e6:.1f} MB.")
print(f"Cleared {len(affected)} tracking row(s).")
print("\nNow re-run the normal tool against the same library and this target_root to reprocess")
print("these assets into their correct dated folders.")
PYEOF
