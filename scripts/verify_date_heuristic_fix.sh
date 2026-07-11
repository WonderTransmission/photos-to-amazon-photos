#!/usr/bin/env bash
#
# Verifies the date-heuristic fix (see docs/tasks.md "PV1") against a REAL library, using the
# actual fixed photos_to_amazon_photos.date_resolver code -- not a reimplementation.
#
# What it does: opens the given Photos library READ-ONLY via osxphotos, in an isolated venv it
# creates and deletes itself, and reports how many assets the OLD heuristic (date vs date_added,
# 60s window) vs. the NEW heuristic (date_original vs date_added, 2s window) would flag as
# undated -- plus the raw gap distribution near the threshold, so you can see the same kind of
# clean-split evidence used to validate the fix in the first place, but on YOUR real data. Pure
# metadata reads -- no files are exported, nothing is written anywhere, the library is never
# modified.
#
# Usage:
#   bash verify_date_heuristic_fix.sh [/path/to/Your Library.photoslibrary]
#
# If you don't pass a path, the script tries to auto-discover Photos libraries on this Mac and
# asks you to re-run with one of them if it finds more than one.
#
# Before running: if this fails with a permissions-looking error opening the library, grant
# "Full Disk Access" to Terminal (or whichever app you're running this from) in
# System Settings > Privacy & Security > Full Disk Access, then try again.
#
# When it's done, copy everything from the "===== SUMMARY" line down and share it back.

set -euo pipefail

REPO_URL="git+https://github.com/WonderTransmission/photos-to-amazon-photos.git"

LIBRARY_PATH="${1:-}"

if [ -z "$LIBRARY_PATH" ]; then
  echo "No library path given — searching for Photos libraries on this Mac (including external volumes)..."
  mapfile -t FOUND < <(mdfind "kMDItemContentType == 'com.apple.photos.library'" 2>/dev/null || true)
  if [ "${#FOUND[@]}" -eq 0 ]; then
    echo "Spotlight search found nothing (common if indexing is off for an external drive) — falling back to a direct filesystem search of /Volumes..."
    mapfile -t FOUND < <(find /Volumes -maxdepth 6 -iname "*.photoslibrary" -type d 2>/dev/null || true)
  fi
  if [ "${#FOUND[@]}" -eq 0 ]; then
    echo "No libraries found either way. Re-run with the path explicitly, e.g.:"
    echo "  bash verify_date_heuristic_fix.sh \"/Volumes/YourDrive/Photos_2017-2024.photoslibrary\""
    exit 1
  elif [ "${#FOUND[@]}" -eq 1 ]; then
    LIBRARY_PATH="${FOUND[0]}"
    echo "Found exactly one: $LIBRARY_PATH"
  else
    echo "Found multiple libraries — re-run with the one you want to check:"
    printf '  %s\n' "${FOUND[@]}"
    exit 1
  fi
fi

if [ ! -d "$LIBRARY_PATH" ]; then
  echo "ERROR: not a directory: $LIBRARY_PATH"
  exit 1
fi

PYBIN="$(command -v python3.14 || command -v python3)"
echo "Using Python: $PYBIN ($($PYBIN --version))"

VENV_DIR="$(mktemp -d)/venv"
"$PYBIN" -m venv "$VENV_DIR"
"$VENV_DIR/bin/pip" install -q --upgrade pip
echo "Installing the actual fixed package from the public repo (not a reimplementation)..."
"$VENV_DIR/bin/pip" install -q "$REPO_URL"

trap 'rm -rf "$(dirname "$VENV_DIR")"' EXIT

"$VENV_DIR/bin/python" - "$LIBRARY_PATH" <<'PYEOF'
import sys

LIB = sys.argv[1]

import osxphotos
from photos_to_amazon_photos import date_resolver
from datetime import timedelta

print(f"\nphotos_to_amazon_photos date_resolver.UNDATED_THRESHOLD = {date_resolver.UNDATED_THRESHOLD}")
print(f"Opening library (read-only): {LIB}")
db = osxphotos.PhotosDB(LIB)
photos = db.photos()
print(f"Opened OK. Total assets: {len(photos)}")

OLD_THRESHOLD = timedelta(seconds=60)

old_undated_uuids = set()
new_undated_uuids = set()
gaps_near_boundary = []  # (gap_seconds, has_real_exif, filename) for gap < 120s
checked = 0

for p in photos:
    if p.date_added is None:
        continue
    checked += 1

    if abs(p.date - p.date_added) < OLD_THRESHOLD:
        old_undated_uuids.add(p.uuid)

    result = date_resolver.resolve(p.date, p.date_added, p.date_original)
    if result.is_undated:
        new_undated_uuids.add(p.uuid)

    gap = abs(p.date_original - p.date_added).total_seconds()
    if gap < 120:
        has_real_exif = p.exif_info is not None and p.exif_info.date is not None
        gaps_near_boundary.append((gap, has_real_exif, p.original_filename, p.uuid))

fixed = old_undated_uuids - new_undated_uuids       # false positives eliminated
newly_flagged = new_undated_uuids - old_undated_uuids  # should normally be empty -- flag if not
still_undated = old_undated_uuids & new_undated_uuids  # genuinely undated both ways

gaps_near_boundary.sort()

print("\n===== SUMMARY (copy from here down) =====")
print(f"Library: {LIB}")
print(f"Total assets checked: {checked}")
print(f"Flagged undated by OLD heuristic (date vs date_added, 60s): {len(old_undated_uuids)}")
print(f"Flagged undated by NEW heuristic (date_original vs date_added, 2s): {len(new_undated_uuids)}")
print(f"  -> false positives eliminated by the fix: {len(fixed)}")
print(f"  -> still (genuinely) flagged undated by both: {len(still_undated)}")
print(f"  -> flagged undated by NEW but NOT by OLD (should normally be 0 -- investigate if not): {len(newly_flagged)}")

if newly_flagged:
    print("\nUNEXPECTED: assets newly flagged undated that weren't before:")
    for p in photos:
        if p.uuid in newly_flagged:
            print(f"  {p.uuid}  {p.original_filename}  date={p.date}  date_added={p.date_added}  date_original={p.date_original}")

print(f"\nGap distribution near the threshold (all assets with gap < 120s, {len(gaps_near_boundary)} of them):")
print(f"{'gap_sec':>10}  {'has_exif':>8}  filename")
for gap, has_exif, filename, uuid in gaps_near_boundary[:60]:
    print(f"{gap:>10.3f}  {str(has_exif):>8}  {filename}")
if len(gaps_near_boundary) > 60:
    print(f"  ... and {len(gaps_near_boundary) - 60} more (truncated)")

print("\nSample of specific assets fixed (previously undated, now correctly dated), up to 10:")
count = 0
for p in photos:
    if p.uuid in fixed:
        print(f"  {p.uuid}  {p.original_filename}  date={p.date}")
        count += 1
        if count >= 10:
            break

print("\n===== END SUMMARY =====")
PYEOF
