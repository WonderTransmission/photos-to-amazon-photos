# Design: Photos-to-Amazon-Photos Preparer

Status: Draft (v0.1) — under review
Phase: 2 of 3 (Requirements → **Design** → Tasks)

This document describes *how* [`requirements.md`](requirements.md) gets implemented. It
resolves the requirements doc's deferred open questions (2, 3, 6) and gives the current status
of the still-open one (4). Requirement IDs (FR-n, NFR-n, G-n, NG-n) are referenced throughout
for traceability.

## 1. Architecture Overview

A single-process, single-run CLI tool with five collaborating pieces:

```
cli.py            → argument parsing, orchestration, run summary
library_reader.py → wraps osxphotos.PhotosDB; enumerates + classifies assets (read-only)
date_resolver.py  → capture-date vs. fallback-date heuristic (FR-5 / Section 7)
namer.py          → deterministic target filename/path computation
tracking.py       → tracking.csv read/write, idempotency index, atomic flush
stager.py         → per-asset orchestration: skip-check → export → checksum → tracking update
```

`stager.py` is the only module that touches the filesystem inside `target_root`; every other
module is pure computation. This keeps the idempotency/skip logic (FR-7) testable without
needing a real Photos library or real files.

### Library access approach

The tool uses **osxphotos as a Python library** (`osxphotos.PhotosDB`, `PhotoInfo` objects),
not its bundled CLI (`osxphotos export`). The CLI's `export` command is a good bulk tool but
owns its own opinionated directory/naming/skip-logic; this project needs full per-asset control
to compute custom target paths, run its own idempotency check *before* touching the filesystem,
and stage a Live Photo to two locations at once. Using the library gives that control while
still delegating the actual byte-level export (including original-vs-edited selection and
optional exiftool-based metadata enrichment) to `PhotoInfo.export()`, rather than reimplementing
that logic.

## 2. Dependencies

| Dependency | Role | Notes |
|---|---|---|
| Python 3.14 | Runtime | Per NFR-1. |
| `osxphotos` (MIT, PyPI) | Photos library access | Pin to `>=0.76.1` (confirmed `requires-python >=3.10,<=3.14`, i.e. Python 3.14-compatible). See [Section 11.1](#111-osxphotos--macos-tahoe-compatibility) for the remaining macOS Tahoe risk. |
| `exiftool` (external binary, not pip-installable) | Optional metadata enrichment | Only needed to embed Photos-only metadata (keywords, persons) per FR-4's "SHOULD". Detected at startup via `shutil.which`; its absence degrades gracefully, it is not a hard dependency. |
| Python standard library | Everything else | `csv`, `hashlib`, `pathlib`, `argparse`, `logging`, `dataclasses`, `shutil`, `subprocess` (for the optional Photos.app check). No other third-party packages. |

## 3. Media Type Classification

For each `PhotoInfo` returned by `db.photos()`:

```
if photo.ismovie:        media_type = "video"
elif photo.live_photo:   media_type = "live_photo"
else:                    media_type = "photo"
```

A `live_photo` asset produces **two staged outputs** (Section 4/5.4): its key image under
`photos/`, and the full bundle (key image + `.mov` motion component) under `live_photo/`. A
plain `photo` or `video` asset produces exactly one staged output.

## 4. Tracking Schema (finalized)

Extends the requirements doc's FR-6 table with one new column, `component`, which resolves the
schema gap flagged there (a Live Photo needs two rows, not one):

| Column | Description |
|---|---|
| `photo_uuid` | Photos library's stable UUID. Part of the primary key. |
| `component` | `single` (plain photo/video — one row, one output) \| `key_image` (a Live Photo's still, staged under `photos/`) \| `live_bundle` (a Live Photo's full asset, staged under `live_photo/`). **Primary key is `(photo_uuid, component)`.** |
| `source_library_path` | Unchanged from requirements doc. |
| `original_filename` | Unchanged. |
| `target_relative_path` | Now unambiguous: exactly one path per row, since each row is one staged output. |
| `date_taken` | Unchanged. |
| `date_source` | `exif` \| `library_added` — see [Section 5.2](#52-date-resolution--the-undated-heuristic). |
| `date_added_to_library` | Unchanged. |
| `timestamp_processed` | Unchanged. |
| `file_size_bytes` | Unchanged. |
| `checksum_sha256` | Unchanged. |
| `is_edited_version` | Unchanged (`hasadjustments`). |
| `media_type` | `photo` \| `video` \| `live_photo`. Same for both rows of a Live Photo — `component` is what distinguishes them. |
| `status` | Unchanged: `copied` \| `ignored` \| `error`. |
| `ignore_reason` | Unchanged. |
| `notes` | Unchanged. |

A plain photo/video's single row always has `component=single`. Ignoring a Live Photo means
setting `status=ignored` on *both* its rows (`key_image` and `live_bundle`) — done as one
logical operation by the stager, keyed off `photo_uuid`.

## 5. Core Algorithms

### 5.1 Current-version selection (FR-3)

```
source_path = photo.path_edited if photo.hasadjustments else photo.path
```

Passed to `PhotoInfo.export()` (not read/copied manually) so osxphotos handles the correct
byte-level export (RAW+JPEG pairs, edit rendering, etc.) rather than this tool re-deriving it.

### 5.2 Date resolution & the "undated" heuristic

Per the requirements doc's Section 7 finding: `PhotoInfo.date` is never `None` (Photos always
assigns *something*), but osxphotos exposes no flag distinguishing a true EXIF capture date
from a library-import fallback. `PhotoInfo.date_added` (when the asset was added to the Photos
library) is available separately and can itself be `None`.

Heuristic:

```
if photo.date_added is None:
    date_source = "exif"          # no fallback signal to compare against; trust date as-is
elif abs(photo.date - photo.date_added) < UNDATED_THRESHOLD:   # default: 60 seconds
    date_source = "library_added" # date looks like an import-time fallback, not a real capture time
else:
    date_source = "exif"

date_taken = photo.date
is_undated = (date_source == "library_added")
```

`is_undated` assets are routed to `_undated/` instead of `YYYY/MM/` (FR-5); `date_source` is
recorded either way for auditability.

**This heuristic is inferred, not documented upstream behavior** — it needs empirical
validation against a real library before being trusted. That validation is the tasks doc's
first implementation task, run alongside the macOS Tahoe compatibility spike
([Section 11.1](#111-osxphotos--macos-tahoe-compatibility)). `UNDATED_THRESHOLD` is a tunable
constant (not a CLI flag — keeping the CLI surface minimal per NG4), expected to be adjusted
based on that spike's findings.

### 5.3 Photos.app concurrency check (resolves the "may revisit in design" note on NFR-6)

The research for this design turned up no documented prohibition on reading the library while
Photos.app is open, only an unrelated note that some album-related features expect the library
being read to be Photos' currently-open (default) library. Given that, and per the requirements
doc's decision not to pursue *enforcement*, the design adds one small, low-risk touch: at
startup, `cli.py` runs a non-blocking check (`pgrep -x Photos`, ignoring failures) and — if
Photos.app appears to be running — logs a **warning**, not an error, recommending it be quit,
then proceeds. NFR-6 remains a documented precondition; this is a nudge, not a gate.

### 5.4 Filename generation & Live Photo pairing

Deterministic filename, independent of directory placement:

```
<date_taken:%Y-%m-%d>_<original_stem>_<uuid[:8]><ext>
```

Example: `2024-05-14_IMG_1234_a1b2c3d4.HEIC`.

- The date prefix is included even though the file already lives in a `YYYY/MM/` folder,
  because Amazon Photos (and S3/Glacier) uploads don't necessarily preserve directory structure
  in their own UI — encoding the date in the filename itself keeps that context after upload.
- The 8-hex-char UUID fragment guarantees deterministic, collision-resistant uniqueness across
  repeated runs, without the ugliness of a full UUID. Collision probability at realistic
  personal-library sizes (tens of thousands of assets) is negligible; the stager still asserts
  uniqueness at write time and fails loudly (marks that row `status=error`) rather than silently
  overwriting, in the unlikely event of a collision.
- Extension is preserved as-is from the exported file (no transcoding — consistent with FR-3's
  "highest quality").

**Live Photo pairing convention:** under `live_photo/`, the key image and its `.mov` motion
component share the same basename, differing only in extension — e.g.
`2024-05-14_IMG_1234_a1b2c3d4.HEIC` + `2024-05-14_IMG_1234_a1b2c3d4.MOV`. This mirrors Apple's
own native Live Photo pairing convention (same basename, image + `.mov`), so the pairing is
recognizable by convention alone, not just via the tracking file.

The `photos/` copy of a Live Photo's key image is a **separate physical file**, not a hardlink
to the `live_photo/` copy — the two are staged for different destinations and may be deleted
independently at different times (e.g., after the Amazon Photos upload but before any
live_photo-destination decision is made). Duplicate disk usage is an accepted tradeoff for that
independence.

## 6. Idempotency & Crash Safety (FR-7)

- On startup, `tracking.py` loads `tracking.csv` (if present) into an in-memory dict keyed by
  `(photo_uuid, component)`.
- Per FR-7: a row with `status=copied` is skipped regardless of whether the file still exists on
  disk; a row with `status=ignored` is always skipped; a row with `status=error`, or no row at
  all, is (re)processed.
- The tracking file is flushed to disk periodically during the run (every 200 processed assets,
  a tunable constant) via write-temp-then-`os.replace`, not only at the end — bounding how much
  work an interruption (crash, Ctrl-C, power loss) can lose, per NFR-4. A full rewrite (not an
  append) is used each flush: at realistic personal-library sizes the whole CSV is small enough
  (low tens of MB at most) that a full rewrite is cheap, and it avoids partial-last-line
  corruption edge cases that append-based crash safety would need to guard against separately.
- A final flush always happens at normal run completion.

## 7. Metadata Preservation Strategy (FR-4)

- Original embedded EXIF/GPS/camera metadata is preserved automatically, because the staged
  file is `PhotoInfo.export()`'s output of the *original file bytes* (or Photos' own edit
  rendering for edited assets) — not a re-encode. No extra work needed for this part of FR-4.
- Photos-only metadata not embedded in the source file (keywords, persons, album membership) is
  a "SHOULD," not a "MUST," in the requirements doc. The design honors it opportunistically: if
  `exiftool` is found on `PATH` at startup, it's passed through to `PhotoInfo.export()`'s own
  exiftool integration to write that metadata into IPTC/XMP fields on the staged copy. If not
  found, the tool logs one warning at run start ("exiftool not found — keywords/persons will not
  be embedded; capture date/GPS/camera EXIF is still preserved") and proceeds without it. This
  is a deliberate soft-degrade, consistent with FR-4's "SHOULD" and the project's general
  error-tolerance philosophy (FR-10).
- The exact `PhotoInfo.export()` keyword arguments (for custom filenames, edited-vs-original
  selection, live-photo companion export, and exiftool passthrough) will be confirmed against
  the pinned osxphotos version during implementation — this design doc fixes the *behavior*
  contract, not the exact call signature. If `export()` can't target a fully custom filename
  directly, the stager exports to a temp name in the target directory and renames it to the
  computed deterministic name — still a single atomic step from the tracking file's perspective.

## 8. CLI Interface (FR-1)

```
photos-to-amazon-photos <library_path> <target_root> [--tracking-file PATH] [--dry-run] [--log-level LEVEL]
```

- `library_path`, `target_root`: required positionals, per FR-1.
- `--tracking-file`: override the default `<target_root>/tracking.csv` location. Optional,
  small addition — no new behavior, just where the file lives.
- `--dry-run`: compute and log every planned action (copy / skip-already-processed /
  skip-ignored / error) without writing any files or touching the tracking file. Given this
  tool operates on irreplaceable personal photos, a safe preview mode before the first real run
  against a library is worth the small addition, despite the general preference for a minimal
  CLI surface.
- `--log-level`: standard `DEBUG`/`INFO`/`WARNING`/`ERROR`, default `INFO`.

No other flags in v1 — consistent with NG4 (CLI only, no GUI) and avoiding flags that aren't
directly required by the requirements doc.

## 9. Error Handling (FR-10)

Each asset's processing (source resolution → export → checksum → tracking update) is wrapped in
a single try/except at the `stager.py` level. On any exception: log asset UUID + filename +
exception, write/update its tracking row(s) with `status=error` and a truncated exception
message in `notes`, and continue to the next asset — never abort the run. A Live Photo's two
rows are handled as two independent attempts; one can succeed (`copied`) while the other fails
(`error`) without blocking either.

At the end of the run (and once per periodic flush, at `INFO` level), print a summary: counts
of copied / already-processed (skipped) / ignored (skipped) / errored, broken out by
`media_type`.

## 10. Upload Handoff Strategy (per target subdirectory)

| Directory | Destination | Automation |
|---|---|---|
| `photos/` | Amazon Photos | Point the Amazon Photos desktop app's "Backup" (watch-folder) feature at `<target_root>/photos/`. See requirements doc [Section 8](requirements.md#8-amazon-photos-upload-strategy). |
| `video/` | S3/Glacier | Not automated by this tool ([NG6](requirements.md#3-non-goals-v1)) — a separate, unspecified process consumes this directory. |
| `live_photo/` | Undecided | Staged only. No automated handoff designed for v1 (resolved as "manual/undecided" — requirements doc open question 6). Revisit if/when a destination is chosen. |

## 11. Risks & Mitigations

### 11.1 osxphotos & macOS Tahoe compatibility

Python 3.14 support is confirmed (osxphotos 0.76.1, `requires-python >=3.10,<=3.14`) — no
longer a risk. macOS Tahoe (26.x) support is still only partial upstream ("most features work
on 26.1 but osxphotos does not yet fully support 26.x," per upstream docs as of this writing).

Mitigation: the tasks doc's first task is a compatibility spike — open the target library
read-only with the pinned osxphotos version on this machine's actual macOS Tahoe 26.5 / Photos
v11, enumerate a handful of real assets, and confirm `date`, `date_added`, `path`/`path_edited`,
`live_photo`, and `ismovie` all behave as expected — *before* building the rest of the tool on
top of them. Fallback options if it doesn't pan out, in preference order: (a) pin to a newer
osxphotos patch/pre-release that specifically targets 26.x if one exists by then, (b) as a last
resort, direct read-only `sqlite3` access to the Photos library's internal database — far more
fragile (undocumented, version-specific schema) and only worth pursuing if osxphotos is
genuinely a dead end.

### 11.2 UUID stability

`PhotoInfo.uuid` is the library's own asset identifier and the tracking file's primary key
component, but its long-term stability (e.g., across an iCloud Photos re-sync or a library
migration) is not contractually documented by Apple or osxphotos. No incident reports of UUIDs
changing were found during research, so it's treated as stable in practice. If it ever isn't,
the worst case is a previously-staged asset being reprocessed and re-copied under a new UUID —
low-probability, low-severity (a duplicate file, not data loss or corruption), and not worth
additional dedup complexity for v1 (consistent with [NG3](requirements.md#3-non-goals-v1)).

### 11.3 Date heuristic accuracy

Covered in [Section 5.2](#52-date-resolution--the-undated-heuristic) — flagged there as needing
empirical validation, bundled into the same first-task spike as 11.1.

## 12. Non-Functional Design Notes

- **Streaming (NFR-3):** `db.photos()` is iterated one asset at a time; the tool never
  materializes a full list of exported files in memory. The only full-library-sized in-memory
  structure is the tracking index (`(uuid, component) → row`), which is small (a struct of
  short strings/numbers per row) even at tens of thousands of assets.
- **Interruptibility (NFR-4):** guaranteed by the periodic-flush design in
  [Section 6](#6-idempotency--crash-safety-fr-7) — an interrupted run loses at most the assets
  processed since the last flush, and picks them up again (via `status` still being absent or
  `error`) on the next run.
- **Read-only source access (NFR-5 / FR-2):** enforced simply by never calling any
  osxphotos/PhotosDB method that mutates the library — the tool only ever reads `PhotoInfo`
  attributes and calls `export()`, which writes to `target_root`, never back into the library.

## 13. Traceability: Requirements Open Questions → Design Resolution

| Requirements doc item | Resolution |
|---|---|
| 2. Exact `_undated/` detection rule | [Section 5.2](#52-date-resolution--the-undated-heuristic): `date` vs. `date_added` heuristic, pending validation spike. |
| 3. Filename/collision scheme + Live Photo tracking-schema gap | [Section 5.4](#54-filename-generation--live-photo-pairing) (naming) + [Section 4](#4-tracking-schema-finalized) (`component` column). |
| 6. Upload destination for `live_photo/` | Resolved as manual/undecided — [Section 10](#10-upload-handoff-strategy-per-target-subdirectory). |
| 4. osxphotos compatibility | Python 3.14: resolved (supported). macOS Tahoe 26.x: still open, mitigation plan in [Section 11.1](#111-osxphotos--macos-tahoe-compatibility). |
| NFR-6 "may revisit in design" (Photos.app concurrency) | [Section 5.3](#53-photosapp-concurrency-check-resolves-the-may-revisit-in-design-note-on-nfr-6): non-blocking warning added, precondition still documented, not enforced. |

## 14. Still Open for the Tasks Doc

- Exact `PhotoInfo.export()` call signature to use (Section 7's caveat) — a coding-time detail,
  not a design blocker.
- `UNDATED_THRESHOLD` value (default proposed: 60 seconds) — to be tuned by the validation
  spike (Section 5.2 / 11.1).
- Whether the macOS Tahoe compatibility spike surfaces any osxphotos gaps serious enough to
  require revisiting this design (Section 11.1's fallback options).
