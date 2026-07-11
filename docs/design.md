# Design: Photos-to-Amazon-Photos Preparer

Status: v0.9 — describes a shipped v1.0 tool, plus post-release additions (Sections 6, 8, 11.3)
Phase: 2 of 3 (Requirements → **Design** → Tasks)

This document describes *how* [`requirements.md`](requirements.md) gets implemented. It
resolves the requirements doc's deferred open questions (2, 3, 6) and gives the current status
of the still-open one (4). Requirement IDs (FR-n, NFR-n, G-n, NG-n) are referenced throughout
for traceability.

**v0.2 note:** the tasks doc's Milestone 0 spike (T0.1/T0.2) has been run against a real
library, ahead of full implementation, since it was cheap to do and several of this document's
open risks depended on it. Findings are folded in throughout, especially
[Section 5.2](#52-date-resolution--the-undated-heuristic), [Section 5.5](#55-asset-availability-check-not-ismissing),
and [Section 11](#11-risks--mitigations).

**v0.3 note:** the library used for that spike turned out to be a poor stand-in for the tool's
actual target — see [Section 11.4](#114-library-composition-this-spike-library-was-not-representative)
onward. Two of the spike's conclusions (the iCloud Shared Photo Library hypothesis, and "disable
Optimize Mac Storage" as the fix for missing originals) were wrong and have been corrected in
place, with the reasoning kept visible rather than silently rewritten. The mechanics-level
findings (osxphotos compatibility, `export()` behavior, the date heuristic, the video
`ismissing` bug) are unaffected and expected to generalize.

**v0.4 note:** T0.3 (re-validating against the real target libraries) is complete — see
[Section 11.6](#116-t03-results-validated-against-the-actual-target-library) for full results.
Everything 11.4–11.5 flagged as uncertain is now resolved with real data: availability is a
non-issue in practice (0.023% unavailable across 138,893 assets), the video `ismissing` bug is
confirmed spike-library-specific, and NFR-6 is downgraded from a hard precondition to a
recommendation based on 3 successful real runs with Photos.app open. No open items remain from
the original compatibility/availability risk thread.

**v0.6 note (post-v1.0):** a real production run against the actual 46,141-asset target library
surfaced a genuine bug in the date/undated heuristic — ~1,000 assets with correct embedded dates
were misrouted to `_undated/`. Root-caused, fixed as v2, and re-validated (681 real assets) far
more rigorously than the original Milestone 0 spike.

**v0.7 note (post-v1.0, continued):** v2's validation had its own gap — it only checked
locally-available assets. A verification script written specifically to re-check any fix against
a real library (`scripts/verify_date_heuristic_fix.sh`) caught v2 still misclassifying 64
cloud-only assets (mostly videos) *before* it reached the user's actual target library. Fixed
again as v3 (100ms threshold instead of 2s), this time validated against the complete
10,267-asset library with zero unexpected misclassifications. See
[Section 5.2](#52-date-resolution--the-undated-heuristic) and
[Section 11.3](#113-date-heuristic-accuracy--revised-twice-after-real-production-false-positives)
for the full story, including what the validation methodology got wrong both times. The fix
remains forward-only; already-staged files aren't retroactively moved — see tasks.md's
post-v1.0 section for remediation options.

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
| `osxphotos` (MIT, PyPI) | Photos library access | Pin to `>=0.76.1` (confirmed `requires-python >=3.10,<=3.14`, i.e. Python 3.14-compatible). See [Section 11.1](#111-osxphotos--macos-tahoe-compatibility--validated-but-not-on-a-representative-library) for compatibility status. |
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

**v1 heuristic (Milestone 0, since superseded — kept here for history):** compared `photo.date`
against `photo.date_added` with a 60-second window, on the theory that a `date` close to
`date_added` meant no real capture date existed. Validated at the time against 36 real assets
(30 with camera EXIF, 6 screenshots) with 100% agreement. That sample didn't happen to include
recently-synced photos, and the assumption doesn't hold for them: a photo captured on a device
with iCloud Photos actively syncing can be added to the library within seconds of capture, so
`date` and `date_added` land close together *even when the photo has a completely legitimate
EXIF capture date*. Running against a real 46,141-asset production library surfaced this: ~1,000
assets misrouted to `_undated/` despite having correct embedded dates. A rigorous recheck against
this project's own real spike-library data (681 available assets) found the v1 heuristic's
false-positive rate among its "undated" classifications was **~79%** (27 of 34).

**v2/v3 heuristic (current — see the revision note below for why v2's threshold changed):** uses
`PhotoInfo.date_original` instead of `date` for the comparison. osxphotos sets `date_original`
from EXIF at import time, and — critically — falls back to *exactly* mirroring `date_added`
(matching to the microsecond) only when there was no EXIF date at all:

```
if photo.date_added is None:
    date_source = "photos_date"   # no fallback signal to compare against; trust date as-is
elif abs(photo.date_original - photo.date_added) < UNDATED_THRESHOLD:   # 100ms as of v3
    date_source = "library_added" # date_original is a pure copy of date_added: no real EXIF date existed
else:
    date_source = "photos_date"

date_taken = photo.date   # still `date`, not `date_original` -- see below
is_undated = (date_source == "library_added")
```

`date_taken` (what actually gets used for the folder/filename) still comes from `photo.date`,
not `photo.date_original` — `date` is Photos' *current* value, which reflects any date the user
has manually corrected in Photos.app, while `date_original` is frozen at import time. We want
the folder to reflect the user's corrected date if they ever fixed one; we only want
`date_original` for deciding *whether a real signal ever existed*, which correction wouldn't
change (`date_original` isn't touched by later user edits, so it stays a reliable "was this
EXIF-or-equivalent at import" signal even for later-corrected assets — no such assets were
observed in the validation library, so this is reasoned, not independently confirmed).

**Re-validated** against the same real library used for the original Milestone 0 spike, this
time rigorously (all 681 available assets, not just a 36-asset sample), cross-checked two
independent ways:

- Ground truth via `PhotoInfo.exif_info.date` (Photos' own record of whether real EXIF date
  metadata existed at import): of 681 assets, exactly 22 had no real EXIF-or-equivalent signal;
  659 did.
- Ground truth via the `date_original`/`date_added` gap itself: exactly 6 assets showed a gap of
  **precisely 0.000 seconds** (down to the microsecond) — these are the true "Photos had nothing,
  fell back to import time" cases. Every other asset in this 681-asset (locally-available-only)
  subset had a gap of **4.42 seconds** or more — a clean split, *within that subset*. This
  validation had a gap of its own — see below.
- The discrepancy between the two ground truths (22 vs. 6) is fully explained, not a bug: 16
  screenshots/PNGs have no camera EXIF (correctly `exif_info.date is None`) but Photos still
  derives an accurate `date`/`date_original` for them from OS-level metadata, matching the
  original Milestone 0 finding for screenshots specifically. These showed gaps of exactly 4 or 5
  *hours* (14400s / 18000s — a timezone-handling quirk, not real capture-time jitter) between
  `date_original` and `date_added` — nowhere near any threshold considered for this heuristic, so
  they were never actually at risk of misclassification. Locked in as an explicit regression
  test regardless.
- Running the fixed `date_resolver.resolve()` (v2, 2-second threshold) against the whole
  681-asset *locally-available* set: 34 → 6 assets flagged undated, matching the true
  no-signal-at-all count. This looked like a clean, complete validation at the time.

**v2's validation gap, found by `scripts/verify_date_heuristic_fix.sh` before it ever reached
production data:** that 681-asset validation set was implicitly filtered to `path is not None`
(locally-available assets), because that's what the original Milestone 0 spike happened to
export against. Running the same before/after comparison against the library's **full 10,267
assets** (not the locally-available subset) surfaced 64 assets — disproportionately videos, and
*exclusively* assets not stored locally — with genuine EXIF dates and a real
`date_original`/`date_added` gap as small as **0.348 seconds**, apparently because cloud-only
synced metadata goes through a lighter/faster processing path than a fully-downloaded local
import. v2's 2-second threshold caught some of these as new false positives — the same failure
mode as v1, just with a much smaller blast radius, and one that never showed up in the narrower
validation set.

**v3 (current): threshold dropped to 100 milliseconds.** Re-verified against the *entire*
10,267-asset library this time: every known-no-EXIF case still sits at an exact 0.000s gap, and
every known-has-EXIF case — including the fast cloud-sync ones — sits at 0.348s or more. 100ms
leaves a >3x margin below that floor. Running the actual v3 code against all 10,267 assets:
35 → 6 flagged undated, **zero** unexpected new flags this time. `scripts/verify_date_heuristic_fix.sh`
is kept in the repo specifically so this same check can be (and should be) re-run against any
other real library before trusting the heuristic there, rather than assuming a fix validated on
one library's data generalizes.

**Lesson for future changes to this heuristic**, recorded because it bit this fix twice: a
validation sample — even a real, non-trivial one — can look like 100% agreement while quietly
excluding an entire category of data (here: cloud-only assets) that behaves differently. Prefer
checking against the full available dataset over a filtered/curated sample when the check is
cheap enough to run that way (this one is — pure metadata reads, no exports).

**Known limitation, not yet resolved:** this fix is not retroactive. Assets already staged under
an earlier heuristic version with `status=copied` in `tracking.csv` are not reprocessed by
re-running the tool — FR-7's skip rule applies regardless of which heuristic version produced
the row. Moving already-misplaced files requires either manually clearing their tracking rows
(and the stray files) so they get reprocessed, or accepting them as correctly-dated-but-wrong-folder
until a dedicated remediation path exists (see tasks.md's post-v1.0 section).

### 5.3 Photos.app concurrency check (resolves the "may revisit in design" note on NFR-6)

The research for this design turned up no documented prohibition on reading the library while
Photos.app is open, only an unrelated note that some album-related features expect the library
being read to be Photos' currently-open (default) library. Given that, and per the requirements
doc's decision not to pursue *enforcement*, the design adds one small, low-risk touch: at
startup, `cli.py` runs a non-blocking check (`pgrep -x Photos`, ignoring failures) and — if
Photos.app appears to be running — logs a **warning**, not an error, recommending it be quit,
then proceeds.

**Update after T0.3:** NFR-6 was downgraded from a hard "MUST quit" to a "SHOULD quit"
recommendation — see [Section 11.6](#116-t03-results-validated-against-the-actual-target-library)
for the evidence. This section's design doesn't change at all: it was already a non-blocking
warning, never an enforced gate, so it was already consistent with a "SHOULD," not a "MUST."
What changes is just how confidently that warning can be worded/justified.

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
  uniqueness at write time in the unlikely event of a collision. **Refined during Milestone 4's
  T4.1 interrupt testing**: a target path already being occupied isn't automatically a genuine
  collision — a crash can legitimately leave a file successfully staged with no tracking row
  ever flushed for it, and the next run would otherwise hit its own output and error forever,
  never reaching completion. The stager now compares checksums: matching content means "a prior
  interrupted run already finished this," and it's adopted rather than erroring; content that
  actually differs still fails loudly (`status=error`) rather than silently overwriting.
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

**Update after T0.3:** confirmed this bug pattern is specific to the original spike library's
Shared Albums content, not a general osxphotos/macOS Tahoe issue. Across the real target
libraries (138,893 assets, 4,427 videos), it occurred **twice** (0.045% of videos), vs. 421 of
462 (91%) on the spike library. The attempt-and-verify design here stays exactly as-is — it's
correct regardless of how often the underlying flag is wrong, and costs nothing extra — but it's
now understood as a rare-edge-case safety net rather than a fix for a systemic problem.

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
- **Progress logging (post-v1.0 addition):** independent of the `FLUSH_EVERY`-based flush cadence
  above, which counts actual staging *attempts* (`Process()` outcomes) and can barely move
  during a mostly-idempotent re-run (nearly everything `Skip()`s), `stager.run()` also logs
  `"Progress: N% (i/total assets)"` at fixed percentage milestones (every 5%, ~20 lines total)
  as it iterates every asset regardless of outcome — giving "still working, not hung" feedback
  even on a run where the flush-based counter rarely fires. Milestones are percentage-based
  rather than a fixed asset count specifically so the number of log lines stays reasonable
  (~20) whether the library has a few hundred assets or tens of thousands, rather than scaling
  with library size. Requires knowing the total asset count upfront, so `assets` is materialized
  into a list rather than iterated lazily — a no-op cost in practice, since osxphotos's own
  `db.photos()` call (what `LibraryReader.iter_assets()` wraps) already loads every asset's
  metadata into memory internally regardless of how it's consumed here.

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

**Dual logging (post-v1.0 addition, no new flag):** every run writes a timestamped log file
(`photos-to-amazon-photos-YYYYMMDD-HHMMSS.log`) in the current working directory, mirroring
everything sent to stdout — added after real usage surfaced a concrete need: knowing whether an
unattended run completed if the Mac becomes unavailable (sleep, shutdown, crash) before the
terminal can be checked. Implemented as two `logging` handlers (stream + file) sharing one
formatter, rather than via `logging.basicConfig(force=True)`, specifically so it doesn't strip
out handlers other tooling (e.g. a test runner's log capture) may have attached to the root
logger — only handlers this function previously added itself are replaced. The final run
summary is explicitly written to the log file in addition to being `print()`-ed, since `print()`
doesn't go through the logging system and would otherwise be the one piece of output most worth
having survive an interrupted session that the file would miss.

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

### 11.1 osxphotos & macOS Tahoe compatibility — validated, but not on a representative library

Python 3.14 support is confirmed (osxphotos 0.76.1, `requires-python >=3.10,<=3.14`). The
Milestone 0 spike additionally validated actual behavior against a real library on this machine
(macOS Tahoe 26.5, Photos v11, `~/Pictures/Photos Library.photoslibrary`): `PhotosDB` opened
cleanly, all 10,267 assets enumerated with **zero errors**, all `uuid` values unique,
`date`/`date_added`/`path`/`path_edited`/`hasadjustments`/`ismovie`/`live_photo` all returned
sane values, and `export()` was exercised successfully for photos and Live Photos (including
correct dual-file `.mov` companion export matching
[Section 5.4](#54-filename-generation--live-photo-pairing)'s pairing design exactly). One real
gap was found and addressed as a design change, not a blocker — see
[Section 5.5](#55-asset-availability-check-not-ismissing). `path_edited` specifically went
unexercised by real data (this library has zero edited assets), so that branch remains validated
only by code inspection.

**Important caveat added after this section was first written:** the library used for this spike
turned out to be a poor stand-in for the tool's actual intended input. It's a secondary/receiving
Mac where the user rarely imports their own photos — see
[Section 11.4](#114-library-composition-this-spike-library-was-not-representative) — while the
real target is multiple large libraries on a different Mac, populated by photos the user
personally uploaded. The mechanics validated here (opening the library, `export()`, Live Photo
pairing, UUID stability) are generic osxphotos behavior and transferred cleanly. The
availability/local-storage findings in 11.4–11.5 did *not* transfer, as suspected — see
[Section 11.6](#116-t03-results-validated-against-the-actual-target-library) for the real
results, now validated directly against the actual target libraries.

**No fallback (sqlite3 direct access, alternate library) needed** based on what's been tested so
far — osxphotos on this Python 3.14 / macOS Tahoe 26.5 combination is sound.

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

### 11.3 Date heuristic accuracy — revised twice after real production false-positives

Originally: validated against 36 real assets (30 with camera EXIF, 6 screenshots) with
independent ground truth, 100% agreement, `UNDATED_THRESHOLD = 60` seconds (v1). **That
validation was real but incomplete** — the 36-asset sample didn't include recently-synced
photos, the specific case v1 got wrong. A real 46,141-asset production run surfaced ~1,000
misclassified assets. Root-caused and fixed as v2 (`date_original` instead of `date`, 2-second
threshold), re-validated against 681 real assets with two independent ground truths, zero
false positives/negatives — looked complete at the time.

**It wasn't.** That 681-asset set was implicitly filtered to locally-available assets only.
Checking the same library's full 10,267 assets (via `scripts/verify_date_heuristic_fix.sh`,
written specifically so this check could be run against *other* real libraries before trusting
the heuristic there) found 64 more false positives v2 still caught — disproportionately videos,
exclusively cloud-only assets, with real gaps as small as 0.348s. Fixed as v3 (100ms threshold),
re-validated against the full 10,267-asset library this time: zero unexpected misclassifications
in either direction. Full writeup in [Section 5.2](#52-date-resolution--the-undated-heuristic).

**Lesson, learned twice on this same heuristic:** a validation sample — even a real,
non-trivial, seemingly-complete one — can look like 100% agreement while quietly excluding an
entire category of data that behaves differently. Prefer checking against the *full* available
real dataset over a filtered/curated sample whenever the check is cheap enough to run that way
(this one is: pure metadata reads, no file exports needed).

### 11.4 Library composition: this spike library was not representative

The spike found that ~95% of the spike library (9,544 of 10,267 assets — photos, videos, *and*
Live Photos) lives under a "cloudsharing" storage scope with `shared=True` and a
`cloud_owner_hashed_id` that varies across several distinct values, with only ~7% (723 assets:
670 via "Shared with You"/Messages syndication + 53 clearly local-only) sitting outside it.

The original writeup here hypothesized this was an **iCloud Shared Photo Library** (Apple's
multi-person merged-library feature). **That hypothesis was wrong.** The user subsequently
clarified that iCloud Photos sync has never been enabled on this Mac's library at all — which
rules out iCloud Shared Photo Library specifically, since that feature requires iCloud Photos
sync to be on. The far more likely explanation, consistent with iCloud Photos being off: this
content is from **Shared Albums and/or "Shared with You"** (Messages) — both features operate
independently of the main iCloud Photos sync toggle, are inherently cloud-hosted by design
(recipients get previews, not automatic full local copies), and would produce exactly this
`shared=True` / varying-contributor-hash / mostly-not-local pattern regardless of any Optimize
Storage setting. (osxphotos exposes no usable "who shared this" display name — `owner` is
always `None`, only an anonymized per-contributor hash.)

Practically, this means: **this Mac's library is a secondary/receiving library, not the user's
primary photo collection.** Only ~53 assets (16MB) are genuinely local, personally-imported
content here. The user's real target is a different Mac, with multiple large libraries built
from photos they personally uploaded — a much simpler situation, **confirmed** to have no Shared
Albums involvement by T0.3 (see
[Section 11.6](#116-t03-results-validated-against-the-actual-target-library)).

**Decision (still stands regardless of the corrected hypothesis): the tool stages shared/synced
content as-is, with no filtering by contributor**, if and when it's encountered on any library
this tool is pointed at. No design change follows from this beyond documenting it —
[NG](requirements.md#3-non-goals-v1)-consistent, since per-contributor filtering was never a
requirement.

### 11.5 Precondition: originals must be available locally before running

93% of assets in the spike library are `ismissing=True`, with only small local thumbnails
(measured: 342×257px, ~50KB) cached — nowhere near FR-3's "highest quality" bar. **The original
writeup here attributed this to iCloud Photos' "Optimize Mac Storage" being enabled, and
recommended disabling it as the fix. That was wrong** — the user confirmed that setting is
already disabled (and iCloud Photos sync itself was never enabled) on this Mac, yet the
originals are still not local. Consistent with [Section 11.4](#114-library-composition-this-spike-library-was-not-representative)'s
corrected explanation: this is very likely Shared Albums/Shared-with-You content that was never
explicitly saved into the personal library, which "Optimize Mac Storage" has no effect on either
way — that setting only governs a user's own synced library.

Regardless of the specific cause, the underlying constraint stands: getting a real original for
an asset that isn't already local requires osxphotos's `download_missing`/PhotoKit path, which
drives Photos.app via AppleScript — i.e., **requires Photos.app to be running**, directly
conflicting with NFR-6. Explicitly decided: **the tool will not do this.** Instead, NFR-7 (in
requirements.md) is now phrased as an outcome, not a specific settings fix: *every asset staged
must already have its original available locally at run time; how a user gets there is
environment-specific and outside the tool's concern.* Getting there for *this particular
library's* shared content might mean saving items into the personal library, or might not be
straightforwardly achievable at all for content never explicitly saved — that's fine, since it's
not the representative case anyway.

If some assets remain unavailable at run time regardless of precondition, [Section 5.5](#55-asset-availability-check-not-ismissing)'s
attempt-and-verify design already handles it gracefully: `status=error`, retried automatically on
the next run, no special-casing needed.

### 11.6 T0.3 results: validated against the actual target library

Everything in 11.4–11.5 was a property of an unrepresentative test library, not a general
finding about this tool's input. T0.3 re-ran the equivalent checks (via
`scripts/validate_library.sh`, run by the user) against all 6 real target libraries on the
external drive — the actual intended input for this tool. Results:

**Scale:** 138,893 assets total across the 6 libraries (largest single library: 46,141, of
which 25,206 — 55% — are Live Photos). Bigger than NFR-3's original "tens of thousands" framing
assumed; NFR-3 updated accordingly.

**Availability — confirmed a non-issue.** Only 32 of 138,893 assets (0.023%) were
`ismissing=True`; every library showed effectively 100% resolvable-path rates. This directly
confirms the user's stated expectation ("I uploaded these myself, the originals are there") and
resolves the residual uncertainty this whole sub-thread (11.4–11.6) was tracking. NFR-7 stays
documented as a precondition — it's real, cheap to state, and FR-10's retry handling makes any
straggler harmless — but it's now clear it won't meaningfully affect real usage.

**Video `ismissing` bug — confirmed spike-library-specific**, not a general osxphotos/Tahoe
issue. 2 occurrences out of 4,427 real videos (0.045%), vs. 421/462 (91%) on the spike library.
See [Section 5.5](#55-asset-availability-check-not-ismissing)'s update.

**Edited-asset coverage, finally real.** 11,652 edited assets across these libraries (the spike
library had zero). Export succeeded with zero errors across all libraries and categories tested,
giving much better indirect confidence in the `path_edited` branch — though still not a
*specifically targeted* positive test (the script's export sample wasn't chosen to guarantee
hitting an edited asset). Worth a specifically-targeted check in T3.1 even so, just with much
lower risk now than when this was flagged with zero real edited-asset data available at all.

**Live Photo export confirmed working at real scale**, including the 2017-2024 library where
they're the majority media type (25,206 of 46,141 assets) — no failures in any of the three
libraries where Live Photos were present and export-tested.

**Date heuristic held up on a much larger, independent dataset**: 5 of the 6 libraries got the
ground-truth spot check (the first didn't have `exiftool` installed yet), each sampling 15 real
assets — 15/15, 15/15, 15/15, 14/15, 15/15 consistent. Reinforces [Section 5.2](#52-date-resolution--the-undated-heuristic)'s
original validation on a completely different, much larger dataset.

**NFR-6 (Photos.app concurrency) — downgraded from MUST to SHOULD.** Photos.app was running
during 3 of the 6 validation runs (`pre_2006`, `2025-now`, `2017-2024`), and all three completed
with zero errors and successful test exports. This is real evidence against treating "quit
Photos.app first" as a hard precondition — but it's a limited test (enumeration plus 2 sample
exports per category, not a full run processing tens of thousands of files over potentially
hours, which is a different risk profile for a database Photos.app might be actively writing
to). The user's call, made explicitly rather than left implicit: downgrade to a recommendation.
[Section 5.3](#53-photosapp-concurrency-check-resolves-the-may-revisit-in-design-note-on-nfr-6)'s
non-blocking-warning design required no change — it was already exactly this shape.

**Practical note, not a design change:** the external drive had ~205GB free while already
holding ~842GB across these 6 libraries. Worth keeping in mind whenever `target_root`'s location
is decided (still open, doesn't block anything) — staging a large batch at once could get tight
if it also lands on this drive.

## 12. Non-Functional Design Notes

- **Streaming (NFR-3):** `db.photos()` is iterated one asset at a time; the tool never
  materializes a full list of exported files in memory. The only full-library-sized in-memory
  structure is the tracking index (`(uuid, component) → row`), which is small (a struct of
  short strings/numbers per row) — confirmed comfortably sufficient at the real target scale
  (up to ~46,000 assets in a single library, ~139,000 combined across the full set, per T0.3).
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
| 2. Exact `_undated/` detection rule | [Section 5.2](#52-date-resolution--the-undated-heuristic): `date` vs. `date_added` heuristic, **validated** on two independent real datasets (spike library + all 6 real target libraries, T0.3). |
| 3. Filename/collision scheme + Live Photo tracking-schema gap | [Section 5.4](#54-filename-generation--live-photo-pairing) (naming) + [Section 4](#4-tracking-schema-finalized) (`component` column). |
| 6. Upload destination for `live_photo/` | Resolved as manual/undecided — [Section 10](#10-upload-handoff-strategy-per-target-subdirectory). |
| 4. osxphotos compatibility | **Fully resolved.** Python 3.14: supported. macOS Tahoe 26.5: mechanics validated ([Section 11.1](#111-osxphotos--macos-tahoe-compatibility--validated-but-not-on-a-representative-library)); availability characteristics validated against the real target libraries ([Section 11.6](#116-t03-results-validated-against-the-actual-target-library)) — no fallback needed anywhere. |
| NFR-6 "may revisit in design" (Photos.app concurrency) | [Section 5.3](#53-photosapp-concurrency-check-resolves-the-may-revisit-in-design-note-on-nfr-6) / [Section 11.6](#116-t03-results-validated-against-the-actual-target-library): downgraded from MUST to SHOULD after T0.3 showed 3/6 real runs succeeded with Photos.app open. Non-blocking warning design unchanged. |
| *(new, found during the spike)* Video `ismissing` unreliability | [Section 5.5](#55-asset-availability-check-not-ismissing): don't pre-filter on `ismissing`; attempt-and-verify via `export()`, folded into existing FR-10 error handling. **Confirmed spike-library-specific** by T0.3 (0.045% of real videos vs. 91% on the spike library) — design kept as a cheap safety net regardless. |
| *(new, found during the spike, then corrected, then confirmed)* Spike library composition | [Section 11.4](#114-library-composition-this-spike-library-was-not-representative): initially misdiagnosed as an iCloud Shared Photo Library; corrected to Shared Albums/Shared-with-You content on a non-representative secondary Mac; **confirmed non-representative** by T0.3's real-library results. |
| *(new, found during the spike, then corrected, then confirmed)* Local-availability precondition | [Section 11.5](#115-precondition-originals-must-be-available-locally-before-running) / [Section 11.6](#116-t03-results-validated-against-the-actual-target-library): NFR-7 rewritten to an outcome-based precondition, then **confirmed a non-issue in practice** — 0.023% unavailable across 138,893 real assets. |

## 14. Still Open for the Tasks Doc

- `path_edited` remains validated only indirectly (zero errors across 11,652 real edited assets
  during T0.3's export tests, but not via a test specifically targeted at an edited asset).
  Low remaining risk; worth a specifically-targeted check in T3.1 regardless, now that libraries
  with edited assets are known to be available to test against.
- `target_root`'s location (same external drive as the source libraries, vs. the Mac's internal
  disk) is still undecided by the user. Doesn't block any design or implementation work — FR-1
  already accepts any path — but worth revisiting before a real production run given the
  external drive's limited free space relative to the source libraries' combined size
  ([Section 11.6](#116-t03-results-validated-against-the-actual-target-library)).
