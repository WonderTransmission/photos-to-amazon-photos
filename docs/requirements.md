# Requirements: Photos-to-Amazon-Photos Preparer

Status: Draft (v0.4) — under review
Phase: 1 of 3 (Requirements → Design → Tasks)

## 1. Purpose

Provide a repeatable, idempotent way to pull photos, videos, and Live Photos out of a local
macOS **Photos** library (Photos v11 / macOS Tahoe 26.5) and stage them — with original
metadata intact — into a plain directory tree, split by media type, for onward upload:
still photos to **Amazon Photos**, videos to **S3/Glacier**. The tool itself does not need to
perform any upload; it needs to produce a clean, deduplicated, well-organized "staging" folder
that separate upload mechanisms (automated or manual) can consume.

## 2. Goals

- G1: Extract the best available version of every asset (photo, video, Live Photo) in a single
  Photos library into a target directory, preserving embedded metadata (EXIF, GPS/geolocation,
  capture date, etc.).
- G2: Be safe to re-run repeatedly against the same library/target pair without re-copying
  photos that have already been handled (idempotent).
- G3: Track, in a single human-readable/editable file, what has been processed, so that staged
  files can later be deleted (after upload) without the tool forgetting they were handled.
- G4: Support a manual review workflow where specific photos can be permanently excluded
  (e.g., inappropriate content) without deleting them from the source library.
- G5: Never modify or put at risk the source Photos library. Read-only access only.

## 3. Non-Goals (v1)

- NG1: The tool will **not** perform the Amazon Photos upload itself via a reverse-engineered
  or unofficial API. See [Section 8](#8-amazon-photos-upload-strategy) for the chosen approach.
- NG2: The tool will **not** merge/dedupe across multiple Photos libraries in a single run.
  Each library is processed independently, one run per library ([FR-1](#fr-1-cli-invocation)).
- NG3: The tool will **not** attempt perceptual/visual duplicate detection across distinct
  Photos assets (i.e., the same picture imported twice under two different UUIDs). It dedupes
  only at the Photos-asset level (see [FR-8](#fr-8-uniqueness--deduplication)).
- NG4: No GUI. CLI only.
- NG5: No concurrent runs against the same target directory (single-writer assumption).
- NG6: The tool will **not** upload the staged `video/` contents to S3/Glacier. That upload is
  a separate process outside this tool's scope; this tool only stages video files into a
  dedicated directory for that separate process to consume.

## 4. Definitions

| Term | Meaning |
|---|---|
| Asset | A single item in the Photos library, identified by a stable, library-scoped UUID. Can be a photo, a video, or a Live Photo. |
| Current version | The version of an asset Photos would show/export today — the edited version if the user has edited it, otherwise the original. |
| Live Photo | A Photos asset made of two parts: a still "key" image and a short paired video/motion component. |
| Key image | The still-image component of a Live Photo — what you'd see if Live Photo motion were turned off. |
| Target directory | The root output directory passed on the CLI; staged copies and the tracking file live here. Split into media-type subdirectories — see [FR-5](#fr-5-target-directory-structure). |
| Tracking file | The CSV at the root of the target directory recording what has been processed. |
| Staged asset | A file (or set of files, for a Live Photo) copied into the target directory tree, ready for upload. |

## 5. Functional Requirements

### FR-1: CLI invocation

The tool MUST be invoked as a command taking exactly two required arguments:

1. Path to a single Photos library (`.photoslibrary` package).
2. Path to a root target directory (created if it does not exist).

The tool MUST process exactly one library per invocation. Processing multiple libraries
requires multiple independent invocations, optionally sharing the same target directory and
tracking file.

### FR-2: Source access is read-only

The tool MUST NOT write to, modify, or otherwise mutate the source Photos library or its
package contents under any circumstances, including on error paths.

### FR-3: Select highest-quality current version

For each asset, the tool MUST export the **current version** as Photos.app would show it —
i.e., the user's edited/adjusted version if one exists, otherwise the original — at full
resolution/quality (not a thumbnail/preview-quality rendition). This applies uniformly to
photos, videos, and both components of a Live Photo.

### FR-4: Preserve metadata in the copy

The staged copy MUST retain, embedded in the file itself (not only in the tracking CSV):

- Capture date/time
- GPS / geolocation (when present on the asset)
- Camera make/model and other standard EXIF fields present on the source
- Orientation

Where the Photos library holds metadata that is not embedded in the original file itself
(e.g., keywords, persons/faces, album membership), the tool SHOULD write that metadata into
the copy's EXIF/IPTC/XMP fields where a reasonable mapping exists. Anything that cannot be
embedded MAY instead be recorded in the tracking file (see [FR-6](#fr-6-tracking-file)).

### FR-5: Target directory structure

The target directory MUST be split at the top level by media type, since each type is staged
for a different downstream destination:

```
<target_root>/
  photos/
    2024/
      01/
        <staged still images for Jan 2024>
      05/
        <staged still images for May 2024>
    2025/
      ...
    _undated/
      <staged still images with no reliable capture date>
  video/
    2024/
      ...
    _undated/
  live_photo/
    2024/
      ...
    _undated/
  tracking.csv
```

- `photos/` — still images: normal photos, plus the **key image** of every Live Photo. This is
  the directory intended to feed Amazon Photos (see [Section 8](#8-amazon-photos-upload-strategy)).
- `video/` — standalone video assets. Staged for a separate S3/Glacier upload process
  ([NG6](#3-non-goals-v1)); not related to the Amazon Photos flow.
- `live_photo/` — the Live Photo asset in its entirety (i.e., including its motion/video
  component), kept separate from both `photos/` and `video/` so a Live Photo's key image can be
  treated as a normal photo while the full Live Photo is preserved intact elsewhere. Its
  upload destination is not yet decided — see [Section 9](#9-open-questions--assumptions).
- Within each of `photos/`, `video/`, and `live_photo/`, staged files MUST be organized by
  **capture date** using the same `YYYY/MM/` + `_undated/` scheme (see
  [Section 7](#7-date-availability) for how "capture date" is determined and what happens when
  it's unreliable). Two-level nesting (`YYYY/MM/`) keeps per-directory file counts manageable
  for large libraries without creating excessive top-level clutter. The `_undated/` bucket
  (leading underscore so it sorts to the top, clearly distinct from a year) holds assets for
  which no reliable capture date could be determined.
- Filenames within each media-type subtree MUST be unique across that subtree and MUST be
  deterministic — the same source asset MUST map to the same target filename across repeated
  runs. The exact naming scheme (e.g., handling of filename collisions, whether to embed a
  UUID fragment, how a Live Photo's paired files are named/kept together under `live_photo/`)
  is a **design-phase decision**, not fixed here.

### FR-6: Tracking file

A single CSV file MUST live at `<target_root>/tracking.csv` and MUST act as the durable,
authoritative record of what has been processed. One row per Photos asset. Proposed columns:

| Column | Description |
|---|---|
| `photo_uuid` | Photos library's stable UUID for the asset. Primary key. |
| `source_library_path` | Path to the `.photoslibrary` this asset came from, for audit/debugging across multiple libraries feeding the same target dir. |
| `original_filename` | Filename as known to Photos. |
| `target_relative_path` | Path of the staged file, relative to `target_root` (empty if not currently staged). A Live Photo stages to two locations (key image under `photos/`, full asset under `live_photo/`) — resolved in design.md Section 4 by adding a `component` column and making the primary key `(photo_uuid, component)`, giving each row exactly one path. |
| `date_taken` | ISO 8601 capture date used to place the file (see [Section 7](#7-date-availability)). |
| `date_source` | `photos_date` \| `library_added` — whether `date_taken` is a trustworthy, asset-specific date (which may come from camera EXIF, or from another source Photos trusts, e.g. a screenshot's own capture timestamp) or an import-time fallback. Makes the "can we guarantee a date" tradeoff auditable. Validated in design.md Section 5.2. |
| `date_added_to_library` | When the asset was imported into Photos. |
| `timestamp_processed` | When this row was created/last handled by the tool (the "timestamp added" from the original ask). |
| `file_size_bytes` | Size of the staged file at copy time. |
| `checksum_sha256` | Checksum of the staged file, for integrity verification and future dedup work. |
| `is_edited_version` | Boolean — whether the staged copy is the edited version vs. the original. |
| `media_type` | `photo` \| `video` \| `live_photo`. Determines which top-level subdirectory ([FR-5](#fr-5-target-directory-structure)) the asset is staged under. |
| `status` | `copied` \| `ignored` \| `error`. Deliberately richer than a plain boolean flag — see [FR-7](#fr-7-idempotent-re-run-behavior). |
| `ignore_reason` | Free text, populated when `status=ignored` (e.g., "inappropriate", "duplicate", "corrupt source"). |
| `notes` | Free text, optional. |

### FR-7: Idempotent re-run behavior

On each run, the tool MUST load the existing tracking file (if present) before touching the
filesystem, keyed by `photo_uuid`. For each asset in the source library:

- If a row exists with `status=copied` and a populated `timestamp_processed`: **skip**. This
  holds regardless of whether the staged file still physically exists in the target directory
  (it may have been deleted after a successful upload to its destination — Amazon Photos for
  `photos/`, S3/Glacier for `video/`, etc.) — the tracking file, not the filesystem, is the
  source of truth for "has this been handled."
- If a row exists with `status=ignored`: **skip**, permanently, until the row is manually
  edited.
- If a row exists with `status=error`, or no row exists at all: **process** the asset (copy +
  write/update its row).

Writes to the tracking file MUST be crash-safe (e.g., write-temp-then-rename, or an
append-friendly format) such that an interrupted run does not corrupt previously recorded
rows.

### FR-8: Uniqueness & deduplication

Each Photos asset (identified by `photo_uuid`) MUST be staged at most once. Photos' own data
model already guarantees UUIDs are unique per asset, so no additional dedup logic is required
to avoid double-processing the same asset within or across runs. Detection of *visually*
duplicate photos that exist as separate Photos assets (distinct UUIDs) is out of scope for v1
([NG3](#3-non-goals-v1)); `checksum_sha256` is captured specifically to make that analysis
possible later without re-touching the source library.

### FR-9: Ignore / exclusion workflow

An asset MUST be excludable from staging (e.g., inappropriate content) by setting
`status=ignored` on its tracking row. For v1, this is done by directly editing `tracking.csv`;
a dedicated CLI command for marking rows ignored is a candidate future enhancement
([Section 10](#10-future-enhancements)).

### FR-10: Error handling

A failure processing one asset MUST NOT abort the run. The tool MUST log the error, mark that
asset's row `status=error` (so it is retried on the next run), and continue with the remaining
assets. The tool MUST print a run summary at the end: counts of copied / already-processed
(skipped) / ignored (skipped) / errored.

## 6. Non-Functional Requirements

- NFR-1: Implemented in Python 3.14+.
- NFR-2: Must run on macOS Tahoe (26.5) against Photos v11 libraries.
- NFR-3: Must handle libraries in the tens-of-thousands-of-photos range without unbounded
  memory growth (e.g., stream/iterate rather than materializing the whole library in memory).
- NFR-4: Idempotent and safe to interrupt (Ctrl-C, crash, power loss) at any point without
  requiring manual cleanup before the next run.
- NFR-5: Read-only with respect to the source library at all times ([FR-2](#fr-2-source-access-is-read-only)).
- NFR-6: Photos.app MUST be quit before running the tool. Reading the Photos library database
  while Photos.app is open is not officially supported by Apple, so this is documented as a
  hard precondition rather than something the tool works around. Whether the tool actively
  detects and enforces this (vs. relying on documentation alone) is a design-phase decision.
- NFR-7: iCloud Photos' "Optimize Mac Storage" MUST be disabled, and the library MUST have
  finished downloading all originals locally, before running the tool. Discovered during the
  design phase's compatibility spike (design.md Section 11.5): getting a real original for an
  asset that isn't stored locally requires driving Photos.app via AppleScript/PhotoKit, which
  conflicts with NFR-6 — so the tool does not attempt to download anything itself. This is a
  one-time, user-performed setup step outside the tool, not something the CLI automates or
  checks. Assets still unavailable at run time despite this are handled as an ordinary per-asset
  error (FR-10) and retried automatically on the next run.

## 7. Date Availability

Every asset in a Photos library has a `date` property, and it is never null — Photos assigns
one at import time even when no capture-date metadata (e.g., EXIF `DateTimeOriginal`) exists
on the source file. So a date is technically always available, but it isn't always a real
*capture* date — it can be a fallback such as the library-import timestamp, or in some cases a
placeholder value.

Decision: use the asset's date for foldering, but track its provenance via `date_source`
(FR-6). Assets whose date is clearly not a trustworthy capture date (fallback/placeholder,
exact detection rule TBD in design) are routed to `_undated/` instead of a year/month folder,
so they're easy to spot and don't pollute a real month's folder with a wrong date. This will
need a small validation spike during the design phase against the actual library.

## 8. Amazon Photos Upload Strategy

Amazon Photos does not offer a public API for uploading. Two automation paths were considered:

1. **Unofficial/reverse-engineered client libraries** (session-cookie based). Rejected for v1:
   fragile against Amazon-side changes, and carries Terms-of-Service risk for something meant
   to run unattended and repeatedly.
2. **Amazon Photos desktop app's built-in "Backup" feature** (Selected). The official desktop
   app can watch a designated folder and automatically upload anything added to it. This tool
   is designed to hand off cleanly to that feature: point the Backup folder at
   `<target_root>/photos/`, and newly staged photos are picked up and uploaded without any
   custom upload code. Manual upload via the web UI/app remains a fallback at all times.

This applies to `photos/` only. `video/` is staged for a separate S3/Glacier process, not
Amazon Photos ([NG6](#3-non-goals-v1)). Where `live_photo/` fits is still open — see
[Section 9](#9-open-questions--assumptions).

This keeps the tool's responsibility scoped to "produce a correct, deduplicated staging
folder" and avoids taking on upload-reliability and ToS risk.

## 9. Open Questions / Assumptions

**Resolved:**

1. ~~Scope: still images only for v1?~~ **Resolved:** v1 handles all three media types, split
   into separate top-level directories ([FR-5](#fr-5-target-directory-structure)): still photos
   (`photos/`, feeding Amazon Photos), videos (`video/`, feeding a separate S3/Glacier process,
   out of scope per [NG6](#3-non-goals-v1)), and Live Photos in their entirety (`live_photo/`,
   upload destination still open — see below). A Live Photo's key/still image is additionally
   staged into `photos/` like a normal photo.
5. ~~Photos.app running concurrently?~~ **Resolved:** documented as a hard precondition —
   Photos.app MUST be quit before running the tool ([NFR-6](#6-non-functional-requirements)).
   Not pursuing runtime detection/enforcement as a requirement for v1; may revisit in design.
2. ~~Exact `_undated/` detection rule?~~ **Resolved in [design doc](design.md)**: a heuristic
   comparing `date` to `date_added` (no API-provided "is this a real capture date" flag exists
   upstream), pending empirical validation — see design doc Section 5.2 and the tasks doc's
   compatibility/validation spike.
3. ~~Filename/collision scheme?~~ **Resolved in [design doc](design.md)**: deterministic
   `date_taken + original stem + short UUID fragment` naming, with a `component` column added
   to the tracking schema to represent a Live Photo's two staged locations — see design doc
   Section 4 and 5.4.
6. ~~Upload destination for `live_photo/`?~~ **Resolved:** manual/undecided for v1. `live_photo/`
   is staged only; no automated upload handoff (Amazon Photos or S3/Glacier) is designed for it.
   This may change in a future revision once a destination is chosen.
4. ~~osxphotos compatibility?~~ **Resolved:** Python 3.14 confirmed supported upstream
   (osxphotos 0.76.1, `requires-python >=3.10,<=3.14`). macOS Tahoe 26.5 / Photos v11
   compatibility **validated directly against the real target library** as part of the design
   phase's Milestone 0 spike (design.md Section 11.1) — opened cleanly, all 10,267 assets
   enumerated with zero errors, export mechanics (including Live Photo dual-file export)
   confirmed working. No fallback needed. The spike surfaced two new findings, captured as
   NFR-7 (above) and design.md Sections 11.4–11.5, but neither is an osxphotos compatibility
   problem — both are library-content/iCloud-sync realities the tool now explicitly accounts
   for.

No items remain in "still open, TBD" as of this revision — see design.md for any residual,
lower-stakes items being tracked into the tasks doc.

## 10. Future Enhancements (explicitly out of scope for v1)

- CLI subcommand to mark an asset `ignored` by UUID/filename instead of hand-editing the CSV.
- Cross-asset perceptual duplicate detection using `checksum_sha256` (exact duplicates) and/or
  perceptual hashing (near duplicates).
- Multi-library merge/consolidation tooling.
- Direct automated upload to Amazon Photos, if/when an official API becomes available.
- Automated upload of `video/` (and possibly `live_photo/`) contents to S3/Glacier — currently
  a separate, unspecified manual/external process.
