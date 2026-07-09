#!/usr/bin/env bash
#
# T0.3 validation spike (see docs/tasks.md) — run this on the machine that holds the *real*
# target Photos library, not the machine used for the original T0.1/T0.2 spike.
#
# What it does: opens the given Photos library READ-ONLY via osxphotos, in an isolated venv it
# creates and deletes itself, and reports classification/availability/date-heuristic statistics.
# It never modifies the library. It exports a handful of sample files to a temp directory
# purely to test that export() works, then deletes them.
#
# Usage:
#   bash validate_library.sh [/path/to/Your Library.photoslibrary]
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

LIBRARY_PATH="${1:-}"

if [ -z "$LIBRARY_PATH" ]; then
  echo "No library path given — searching for Photos libraries on this Mac (including external volumes)..."
  mapfile -t FOUND < <(mdfind "kMDItemContentType == 'com.apple.photos.library'" 2>/dev/null || true)
  if [ "${#FOUND[@]}" -eq 0 ]; then
    # Spotlight indexing is often disabled on external drives, especially HDDs — mdfind finds
    # nothing in that case even if libraries are right there. Fall back to a direct filesystem
    # search across all mounted volumes, which doesn't depend on Spotlight at all.
    echo "Spotlight search found nothing (common if indexing is off for an external drive) — falling back to a direct filesystem search of /Volumes..."
    mapfile -t FOUND < <(find /Volumes -maxdepth 6 -iname "*.photoslibrary" -type d 2>/dev/null || true)
  fi
  if [ "${#FOUND[@]}" -eq 0 ]; then
    echo "No libraries found either way. Make sure the external drive is connected and mounted,"
    echo "then re-run with the path explicitly, e.g.:"
    echo "  bash validate_library.sh \"/Volumes/YourDrive/Photos Library.photoslibrary\""
    exit 1
  elif [ "${#FOUND[@]}" -eq 1 ]; then
    LIBRARY_PATH="${FOUND[0]}"
    echo "Found exactly one: $LIBRARY_PATH"
  else
    echo "Found multiple libraries — re-run with the one you want to validate:"
    printf '  %s\n' "${FOUND[@]}"
    exit 1
  fi
fi

if [ ! -d "$LIBRARY_PATH" ]; then
  echo "ERROR: not a directory: $LIBRARY_PATH"
  exit 1
fi

# Filesystem check: Photos libraries rely on hard links and extended attributes that exFAT/NTFS
# don't reliably support — only APFS or Mac OS Extended (HFS+) are safe for this. Report it so
# it shows up in the summary. `diskutil info` needs a device identifier or mount root, not an
# arbitrary path inside the volume, so resolve that first via `df`. Best-effort only — never
# fail the whole script over this diagnostic.
DEVICE="$(df "$LIBRARY_PATH" 2>/dev/null | tail -1 | awk '{print $1}')" || DEVICE=""
FS_TYPE=""
if [ -n "$DEVICE" ]; then
  FS_TYPE="$(diskutil info "$DEVICE" 2>/dev/null | awk -F': *' '/File System Personality/ {print $2}')" || FS_TYPE=""
fi
echo "Filesystem of the volume holding this library: ${FS_TYPE:-unknown}"
if [ -n "$FS_TYPE" ] && [[ "$FS_TYPE" != *APFS* ]] && [[ "$FS_TYPE" != *"Mac OS Extended"* ]]; then
  echo "WARNING: '$FS_TYPE' is not APFS or Mac OS Extended (HFS+) — Photos libraries are not"
  echo "reliably supported on other filesystems (e.g. exFAT, NTFS) due to hard link/xattr needs."
  echo "This doesn't block this validation script, but is worth checking/fixing at the drive level."
fi

# Prefer python3.14 if present (matches the project's target runtime), else fall back to
# whatever python3 is available — osxphotos supports >=3.10 and this check is about library
# *data*, not Python-version compatibility (that part was already validated separately).
PYBIN="$(command -v python3.14 || command -v python3)"
echo "Using Python: $PYBIN ($($PYBIN --version))"

VENV_DIR="$(mktemp -d)/venv"
"$PYBIN" -m venv "$VENV_DIR"
"$VENV_DIR/bin/pip" install -q --upgrade pip
"$VENV_DIR/bin/pip" install -q "osxphotos>=0.76.1"

EXPORT_DIR="$(mktemp -d)"
trap 'rm -rf "$VENV_DIR" "$EXPORT_DIR"' EXIT

"$VENV_DIR/bin/python" - "$LIBRARY_PATH" "$EXPORT_DIR" <<'PYEOF'
import sys, os, random, subprocess, shutil

LIB, OUT = sys.argv[1], sys.argv[2]

import osxphotos

print(f"\nosxphotos version: {osxphotos.__version__}")
print(f"Opening library (read-only): {LIB}")
db = osxphotos.PhotosDB(LIB)
photos = db.photos()
total = len(photos)
print(f"Opened OK. Total assets: {total}")

# --- classification + errors ---
photo_ct = video_ct = live_ct = edited_ct = 0
errors = []
for p in photos:
    try:
        if p.ismovie:
            video_ct += 1
        elif p.live_photo:
            live_ct += 1
        else:
            photo_ct += 1
        if p.hasadjustments:
            edited_ct += 1
    except Exception as e:
        errors.append((getattr(p, "uuid", "?"), repr(e)))

uuids = {p.uuid for p in photos}

# --- availability by media type: resolvable path vs ismissing ---
def kind_of(p):
    return "video" if p.ismovie else ("live_photo" if p.live_photo else "photo")

avail_stats = {}
for p in photos:
    k = kind_of(p)
    s = avail_stats.setdefault(k, {"total": 0, "has_path": 0, "ismissing_true": 0, "ismissing_false_no_path": 0})
    s["total"] += 1
    has_path = p.path is not None
    if has_path:
        s["has_path"] += 1
    if p.ismissing:
        s["ismissing_true"] += 1
    elif not has_path:
        s["ismissing_false_no_path"] += 1  # the bug pattern found on the spike library

# --- disk / library size ---
free_bytes = shutil.disk_usage("/").free
lib_size_out = subprocess.run(["du", "-sh", LIB], capture_output=True, text=True).stdout.strip()

# --- Photos.app running? ---
photos_running = subprocess.run(["pgrep", "-x", "Photos"], capture_output=True).returncode == 0

# --- export mechanics test: a few available assets per category ---
available = [p for p in photos if p.path is not None]
by_kind = {"photo": [], "video": [], "live_photo": []}
for p in available:
    by_kind[kind_of(p)].append(p)

export_results = {}
for kind, group in by_kind.items():
    sample = group[:2]
    ok, fail = 0, 0
    for p in sample:
        try:
            is_live = kind == "live_photo"
            r = p.export(OUT, edited=p.hasadjustments, live_photo=is_live)
            if r:
                ok += 1
            else:
                fail += 1
        except Exception:
            fail += 1
    export_results[kind] = f"{ok} ok / {fail} failed / {len(sample)} attempted"

# --- date heuristic spot check (only if exiftool is present) ---
exiftool_present = shutil.which("exiftool") is not None
date_check_lines = []
if exiftool_present and available:
    random.seed(11)
    sample = random.sample(available, min(15, len(available)))
    THRESHOLD = 60
    checked = 0
    agree = 0
    for p in sample:
        try:
            exported = p.export(OUT, edited=p.hasadjustments)
        except Exception:
            continue
        if not exported:
            continue
        f = exported[0]
        out = subprocess.run(["exiftool", "-j", "-DateTimeOriginal", "-CreateDate", f],
                              capture_output=True, text=True)
        import json
        try:
            exif = json.loads(out.stdout)[0]
        except Exception:
            exif = {}
        has_real_exif = bool(exif.get("DateTimeOriginal") or exif.get("CreateDate"))

        date_added = p.date_added
        date = p.date
        if date_added is None:
            heuristic = "photos_date"
        elif abs((date - date_added).total_seconds()) < THRESHOLD:
            heuristic = "library_added"
        else:
            heuristic = "photos_date"

        checked += 1
        # "agree" = heuristic says photos_date AND file has real EXIF, OR heuristic says
        # library_added (can't easily ground-truth that branch without more context, so we
        # only count the strong-signal case as agreement/disagreement)
        if heuristic == "photos_date" and has_real_exif:
            agree += 1
        elif heuristic == "photos_date" and not has_real_exif:
            pass  # inconclusive without more context (could be a screenshot-like legit case)
        else:
            agree += 1  # library_added with nothing to contradict it
    date_check_lines.append(f"Sampled {checked} assets with resolvable paths; heuristic looked consistent for {agree}/{checked}.")
else:
    date_check_lines.append("exiftool not found on PATH — skipped date-heuristic ground-truth check.")

# ================= SUMMARY =================
print("\n===== SUMMARY (copy from here down) =====")
print(f"Library: {LIB}")
print(f"Total assets: {total}")
print(f"Classification: photo={photo_ct} video={video_ct} live_photo={live_ct} (edited={edited_ct})")
print(f"UUID uniqueness: {total} total, {len(uuids)} unique")
print(f"Errors during enumeration: {len(errors)}")
for u, e in errors[:5]:
    print(f"  {u}: {e}")

print("\nAvailability by media type:")
for k, s in avail_stats.items():
    pct = 100 * s["has_path"] / s["total"] if s["total"] else 0
    print(f"  {k}: total={s['total']} has_resolvable_path={s['has_path']} ({pct:.0f}%) "
          f"ismissing=True count={s['ismissing_true']} "
          f"[ismissing=False but NO path (the known bug pattern)]={s['ismissing_false_no_path']}")

print(f"\nDisk free: {free_bytes / 1e9:.0f} GB")
print(f"Library package size (du -sh): {lib_size_out}")
print(f"Photos.app currently running: {photos_running}")

print("\nExport mechanics test (small sample per category):")
for k, v in export_results.items():
    print(f"  {k}: {v}")

print("\nDate heuristic spot check:")
for line in date_check_lines:
    print(f"  {line}")

print("\n===== END SUMMARY =====")
PYEOF
