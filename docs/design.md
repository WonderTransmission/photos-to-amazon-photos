# Design: Photos-to-Amazon-Photos Preparer

Status: Draft (v0.2) — under review
Phase: 2 of 3 (Requirements → **Design** → Tasks)

This document describes *how* [`requirements.md`](requirements.md) gets implemented. It
resolves the requirements doc's deferred open questions (2, 3, 6) and gives the current status
of the still-open one (4). Requirement IDs (FR-n, NFR-n, G-n, NG-n) are referenced throughout
for traceability.

**v0.2 note:** the tasks doc's Milestone 0 spike (T0.1/T0.2) has been run against the real
target library, ahead of full implementation, since it was cheap to do and several of this
document's open risks depended on it. Findings are folded in throughout, especially
[Section 5.2](#52-date-resolution--the-undated-heuristic), [Section 5.5](#55-asset-availability-check-not-ismissing),
and [Section 11](#11-risks--mitigations).

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
| `date_source` | `photos_date` \| `library_added` — see [Section 5.2](#52-date-resolution--the-undated-heuristic). (Renamed from an earlier `exif`/`library_added` draft — see that section for why.) |
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
assigns *something*), but osxphotos exposes no flag distinguishing a true capture date from a
library-import fallback. `PhotoInfo.date_added` (when the asset was added to the Photos
library) is available separately and can itself be `None`.

Heuristic:

```
if photo.date_added is None:
    date_source = "photos_date"   # no fallback signal to compare against; trust date as-is
elif abs(photo.date - photo.date_added) < UNDATED_THRESHOLD:   # 60 seconds, validated below
    date_source = "library_added" # date looks like an import-time fallback, not a real capture time
else:
    date_source = "photos_date"

date_taken = photo.date
is_undated = (date_source == "library_added")
```

`is_undated` assets are routed to `_undated/` instead of `YYYY/MM/` (FR-5); `date_source` is
recorded either way for auditability.

**Naming note:** the earlier draft of this heuristic called the "trustworthy" branch `exif`.
Validation (below) showed that's slightly wrong — Photos assigns accurate per-asset dates from
sources other than camera EXIF too (e.g., screenshots have no `DateTimeOriginal` tag at all, but
`photo.date` reliably matches the capture timestamp embedded in their filename). The column value
is renamed `photos_date` to mean "Photos has a specific, trustworthy timestamp for this asset,
regardless of source," as distinct from `library_added` ("Photos fell back to when it was
imported").

**Validated** against the real target library (macOS Tahoe 26.5, Photos v11, 10,267 assets) as
part of the tasks doc's Milestone 0 spike:

- 30 randomly-sampled photos/videos with genuine camera EXIF: heuristic classified all 30 as
  `photos_date`, and all 30 independently had a real embedded `DateTimeOriginal`/`CreateDate`
  confirmed via `exiftool` — 100% agreement with ground truth.
- 6 screenshots (the archetypal "no camera EXIF" case): 5 were classified `photos_date` and 1
  `library_added`. Cross-checking the 5 against their filename-embedded timestamps (macOS
  screenshot filenames encode the exact capture time, e.g. `Screenshot 2022-05-20 at 2.52.02
  PM.jpeg`) confirmed `photo.date` matched within seconds for all 5 — genuinely accurate dates,
  correctly *not* routed to `_undated/` despite having no camera EXIF. The 1 classified
  `library_added` had no such correlation — a genuine fallback case, correctly caught.
- `UNDATED_THRESHOLD = 60` seconds is confirmed as a reasonable default: every genuine-date case
  in the sample differed from `date_added` by minutes to years; the one genuine fallback case
  matched `date_added` closely enough to trigger the threshold correctly.

No further tuning identified as necessary from this sample. See [Section 11.3](#113-date-heuristic-accuracy)
for residual caveats.

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

### 5.5 Asset availability check: not `ismissing`

The original plan was to pre-filter on `PhotoInfo.ismissing` (or `incloud`/`iscloudasset`) to
decide whether an asset's bytes are actually available locally before attempting export. The
Milestone 0 spike found this flag **unreliable specifically for video assets**: across all 462
videos in the target library, `ismissing` reported `False` for every single one, yet only 41
(~9%) actually had a resolvable local path — the other 421 had no video file anywhere on disk
(only a `.poster.jpg` still-frame and a thumbnail derivative), despite not being flagged
missing. Photos and Live Photos didn't show this discrepancy in the sample tested.

**Design decision:** don't use `ismissing`/`incloud`/`iscloudasset` as a gate on whether to
attempt an asset at all. Instead, **always call `PhotoInfo.export()` and treat its actual
result as the source of truth**: a non-empty result means success, an empty result or exception
means the asset isn't currently available. This isn't a special case — it's exactly FR-10's
existing per-asset error handling (mark `status=error`, log, continue, retry automatically on
the next run), just triggered by an empty export result in addition to a thrown exception. No
new status value or code path is needed.

This also means `--dry-run` ([Section 8](#8-cli-interface-fr-1)) can't perfectly predict
availability without actually attempting export — its "planned" output for an asset should be
read as "will attempt," not an availability guarantee, and this is called out in that section.

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
  error-tolerance philosophy (FR-10). Spot-checked in the Milestone 0 spike: `export(...,
  exiftool=True, use_persons_as_keywords=True)` ran without error and produced valid files, but
  this library's sampled assets had no real keywords and only unnamed (`_UNKNOWN_`) detected
  faces, so no positive case of an actually-embedded keyword was observed — the mechanism works,
  but wasn't exercised end-to-end with real data. Worth a targeted re-check in T3.1/T4.3 against
  an asset that has real keywords or named persons.
- `PhotoInfo.export()`'s signature is confirmed (osxphotos 0.76.1):
  `export(dest, filename=None, edited=False, live_photo=False, exiftool=False, ...)` — no direct
  custom-filename-with-extension-control parameter suited to this project's deterministic naming
  ([Section 5.4](#54-filename-generation--live-photo-pairing)) beyond passing `filename=`
  outright (usable, but the caller must get the extension right per the docstring's warning).
  Confirmed via the spike: `edited=photo.hasadjustments` and `live_photo=True/False` behave
  exactly as expected, including correct dual-file export for Live Photos. The stager exports to
  a temp name and renames to the computed deterministic name if passing `filename=` directly
  proves awkward in practice — either way, a single atomic step from the tracking file's
  perspective.

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
  CLI surface. Caveat, per [Section 5.5](#55-asset-availability-check-not-ismissing): since
  local availability can only be confirmed by actually attempting export, `--dry-run`'s output
  for an asset means "would attempt this," not a guarantee it will succeed.
- `--log-level`: standard `DEBUG`/`INFO`/`WARNING`/`ERROR`, default `INFO`.

No other flags in v1 — consistent with NG4 (CLI only, no GUI) and avoiding flags that aren't
directly required by the requirements doc.

## 9. Error Handling (FR-10)

Each asset's processing (source resolution → export → checksum → tracking update) is wrapped in
a single try/except at the `stager.py` level. On any exception, **or on `export()` returning an
empty result** (per [Section 5.5](#55-asset-availability-check-not-ismissing) — this is the
normal signal for "not currently available locally," not just a Python exception): log asset
UUID + filename + reason, write/update its tracking row(s) with `status=error` and a note in
`notes` (exception message, or `"not available locally"` for an empty export result), and
continue to the next asset — never abort the run. A Live Photo's two rows are handled as two
independent attempts; one can succeed (`copied`) while the other fails (`error`) without
blocking either.

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

### 11.1 osxphotos & macOS Tahoe compatibility — validated

Python 3.14 support is confirmed (osxphotos 0.76.1, `requires-python >=3.10,<=3.14`). The
Milestone 0 spike additionally validated actual behavior against the real target library on
this machine (macOS Tahoe 26.5, Photos v11): `PhotosDB` opened cleanly, all 10,267 assets
enumerated with **zero errors**, all `uuid` values unique, `date`/`date_added`/`path`/
`path_edited`/`hasadjustments`/`ismovie`/`live_photo` all returned sane values, and `export()`
was exercised successfully for photos and Live Photos (including correct dual-file `.mov`
companion export matching [Section 5.4](#54-filename-generation--live-photo-pairing)'s pairing
design exactly). One real gap was found and addressed as a design change, not a blocker — see
[Section 5.5](#55-asset-availability-check-not-ismissing). `path_edited` specifically went
unexercised by real data (this library has zero edited assets: `hasadjustments` is `False` for
all 10,267), so that specific branch remains validated only by code inspection, not a live test
— low risk given how simple the branch is, but worth a specific check during T3.1's
implementation if/when an edited asset becomes available to test against.

**Overall: no fallback (sqlite3 direct access, alternate library) needed.** osxphotos on this
Python 3.14 / macOS Tahoe 26.5 combination is sound for this project's purposes.

### 11.2 UUID stability

`PhotoInfo.uuid` is the library's own asset identifier and the tracking file's primary key
component, but its long-term stability (e.g., across an iCloud Photos re-sync or a library
migration) is not contractually documented by Apple or osxphotos. No incident reports of UUIDs
changing were found during research, so it's treated as stable in practice. If it ever isn't,
the worst case is a previously-staged asset being reprocessed and re-copied under a new UUID —
low-probability, low-severity (a duplicate file, not data loss or corruption), and not worth
additional dedup complexity for v1 (consistent with [NG3](requirements.md#3-non-goals-v1)).
The spike's uniqueness check (10,267 assets, 10,267 unique UUIDs) is consistent with this being
a non-issue in practice, at least at a single point in time.

### 11.3 Date heuristic accuracy — validated

Covered in [Section 5.2](#52-date-resolution--the-undated-heuristic): validated against 36 real
assets (30 with camera EXIF, 6 screenshots) with independent ground truth, 100% agreement.
`UNDATED_THRESHOLD = 60` seconds confirmed as a reasonable default; no further tuning identified.

### 11.4 Library composition: most of this library is a multi-contributor iCloud Shared Photo Library

The spike found that ~95% of the target library (9,544 of 10,267 assets — photos, videos, *and*
Live Photos) lives under a "cloudsharing" storage scope with `shared=True` and a
`cloud_owner_hashed_id` that varies across several distinct values — the signature of an **iCloud
Shared Photo Library with multiple contributors**, not solely this user's own captures. Only
~7% (723 assets: 670 via "Shared with You"/Messages syndication + 53 clearly local-only) sits
outside that shared scope. osxphotos exposes no usable "who added this" display name (`owner` is
always `None`); only an anonymized per-contributor hash.

**Decision (explicitly made, not assumed): the tool stages this content as-is, with no filtering
by contributor.** No design change follows from this beyond documenting it — [NG](requirements.md#3-non-goals-v1)-consistent,
since per-contributor filtering was never a requirement and isn't being added now. Noted here so
it's not mistaken for an oversight: this tool's "your Photos library" input may, for some users,
legitimately include content contributed by other people in a shared library, and staging
everything is the intended v1 behavior.

### 11.5 Precondition: originals must be downloaded locally before running

93% of assets in the target library are `ismissing=True` (this overlaps heavily but not
completely with 11.4's shared-library content), because iCloud Photos' "Optimize Mac Storage" is
enabled — only small local thumbnails (measured: 342×257px, ~50KB) are cached for these, nowhere
near FR-3's "highest quality" bar.

Getting real originals for a missing asset requires osxphotos's `download_missing`/PhotoKit
path, which drives Photos.app via AppleScript — i.e., **requires Photos.app to be running**,
directly conflicting with NFR-6. Explicitly decided: **the tool will not do this.** Instead, a
new precondition (parallel to NFR-6, added to requirements.md as NFR-7): *iCloud "Optimize Mac
Storage" must be disabled and the library must have finished downloading all originals locally
before running the tool.* This is a one-time, user-performed setup step (via System
Settings/Photos.app, outside this tool entirely), not something the CLI automates or checks.
Disk space is not a practical constraint for this target machine (987GB free vs. a 5.7GB library
today, mostly thumbnail cache).

**Residual uncertainty:** it isn't confirmed whether disabling "Optimize Mac Storage" fully
downloads *shared*-library content (11.4) the same way it does the user's own primary library —
Shared Library sync may follow different rules. This isn't a blocker: if some assets are still
unavailable at run time despite the precondition being followed, [Section 5.5](#55-asset-availability-check-not-ismissing)'s
attempt-and-verify design already handles it gracefully — `status=error`, retried automatically
on the next run, no special-casing needed. Worth a note in the T5.1 README (once real originals
are downloading) if this turns out to be a real, persistent gap rather than a transient one.

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
| 2. Exact `_undated/` detection rule | [Section 5.2](#52-date-resolution--the-undated-heuristic): `date` vs. `date_added` heuristic, **validated** against the real library. |
| 3. Filename/collision scheme + Live Photo tracking-schema gap | [Section 5.4](#54-filename-generation--live-photo-pairing) (naming) + [Section 4](#4-tracking-schema-finalized) (`component` column). |
| 6. Upload destination for `live_photo/` | Resolved as manual/undecided — [Section 10](#10-upload-handoff-strategy-per-target-subdirectory). |
| 4. osxphotos compatibility | **Fully resolved**: Python 3.14 supported; macOS Tahoe 26.5 **validated** against the real library ([Section 11.1](#111-osxphotos--macos-tahoe-compatibility-validated)) — no fallback needed. |
| NFR-6 "may revisit in design" (Photos.app concurrency) | [Section 5.3](#53-photosapp-concurrency-check-resolves-the-may-revisit-in-design-note-on-nfr-6): non-blocking warning added, precondition still documented, not enforced. |
| *(new, found during the spike)* Video `ismissing` unreliability | [Section 5.5](#55-asset-availability-check-not-ismissing): don't pre-filter on `ismissing`; attempt-and-verify via `export()`, folded into existing FR-10 error handling. |
| *(new, found during the spike)* Library is majority multi-contributor Shared content | [Section 11.4](#114-library-composition-most-of-this-library-is-a-multi-contributor-icloud-shared-photo-library): explicitly staged as-is, no filtering added. |
| *(new, found during the spike)* iCloud-only originals not usable at "highest quality" | [Section 11.5](#115-precondition-originals-must-be-downloaded-locally-before-running): new precondition (NFR-7 in requirements.md) — user disables Optimize Mac Storage and waits for local sync; tool does not download anything itself. |

## 14. Still Open for the Tasks Doc

- Whether the residual uncertainty in [Section 11.5](#115-precondition-originals-must-be-downloaded-locally-before-running)
  (does disabling Optimize Mac Storage fully resolve local availability for *shared*-library
  content specifically) turns out to be a real, persistent gap once tested — no design change
  needed either way, but worth confirming empirically before/during T3.1 and noting in T5.1's
  README if it's a real limitation users should expect.
- `path_edited` remains validated only by code inspection, not a live test, since this library
  currently has zero edited assets ([Section 11.1](#111-osxphotos--macos-tahoe-compatibility-validated)).
  Worth a specific check in T3.1 if/when an edited asset is available to test against.
