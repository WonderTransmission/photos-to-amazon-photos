# Tasks: Photos-to-Amazon-Photos Preparer

Status: Draft (v0.4) — under review
Phase: 3 of 3 (Requirements → Design → **Tasks**)

**v0.2 note:** Milestone 0 (T0.1, T0.2) has been executed against a real library on this
machine, ahead of the rest of implementation — see results inline below and the full writeup in
design.md (Sections 5.2, 5.5, 11.1–11.6). Two new, unplanned findings came out of it and were
folded into the spec: requirements.md NFR-7 (a new precondition) and design.md Section 5.5 (a
design change to how asset availability is checked). Milestones 1+ are unaffected in structure,
though T3.1/T3.2/T4.3 gained a couple of specific follow-up checks noted below.

**v0.3 note:** the library used for that spike turned out to be a secondary/receiving Mac, not
representative of the tool's actual target (the user's other Mac, with multiple large
personally-uploaded libraries). Two spike conclusions were wrong and corrected in design.md
(the iCloud Shared Photo Library hypothesis, and "disable Optimize Mac Storage" as the fix for
missing originals) — see design.md Sections 11.4–11.6. Added **T0.3** below to re-run the
availability-relevant parts of this spike against the real target library before Milestone 1's
scaffolding work depends on assumptions that haven't actually been tested on representative
data.

This document breaks [`design.md`](design.md) down into ordered, mostly-independent
implementation tasks, grouped into milestones. Milestones are sequential (later ones assume
earlier ones are done); tasks within a milestone are largely parallelizable except where a
dependency is called out. Each task's Definition of Done (DoD) references the requirement
(`FR-n`, `NFR-n`, ...) or design section it implements, for traceability back through the spec.

## Milestone 0 — Compatibility & Validation Spike (blocking; do first)

design.md Section 11.1 flags two unresolved risks that could change downstream module design if
they fail — settle both before writing any other code.

### T0.1 — osxphotos / macOS Tahoe compatibility spike — ✅ DONE

- Install pinned osxphotos (`>=0.76.1`) under Python 3.14 on this machine (macOS Tahoe 26.5).
- Open a real (or a copy of a real) Photos v11 library read-only via `osxphotos.PhotosDB`.
- Enumerate a sample of assets (mix of photos, videos, Live Photos, edited and unedited) and
  confirm `date`, `date_added`, `path`, `path_edited`, `hasadjustments`, `ismovie`,
  `live_photo`, and `uuid` all return sane values.
- Confirm the exact `PhotoInfo.export()` call shape available in this version (custom filename
  support, edited-vs-original selection, live-photo companion export, exiftool passthrough) —
  design.md Section 7 deferred this exact signature to implementation time.

DoD:
- [x] Confirmed working end-to-end: opened the real target library (10,267 assets), zero errors,
      all UUIDs unique, `export()` validated for photos and Live Photos (dual-file pairing
      confirmed correct). No fallback needed.
- [x] `PhotoInfo.export()` usage pattern documented in design.md Section 7.
- [x] (Unplanned, discovered during the spike) `ismissing` found unreliable for videos — design
      changed to attempt-and-verify via `export()` instead of pre-filtering; see design.md
      Section 5.5. Folded into T3.1's DoD below.
- [x] (Unplanned, later corrected) ~95% of the library turned out to be Shared Albums/Shared-
      with-You content on a non-representative secondary Mac, not this user's real photo
      collection, and 93% of assets weren't locally available for a reason unrelated to
      "Optimize Mac Storage" (that was already disabled). Both findings corrected in place —
      design.md Sections 11.4–11.6, requirements.md NFR-7 — and superseded by **T0.3** below,
      which re-validates against the actual representative library.
- [ ] Known gap, not blocking: `path_edited` unexercised by real data (zero edited assets in
      this library) — re-check opportunistically in T3.1 if an edited asset becomes available.
- [ ] Known gap, not blocking: `exiftool=True` passthrough ran without error but had no real
      keywords/named-persons in the sample to positively confirm embedded output — re-check in
      T3.1/T4.3 against an asset that has real keywords or named persons.

### T0.2 — Date heuristic validation — ✅ DONE

- Using the same sample from T0.1, compute the `date` vs. `date_added` heuristic (design.md
  Section 5.2) for each asset and cross-check against ground truth (raw file EXIF
  `DateTimeOriginal` via `exiftool`, and filename-embedded timestamps for screenshots) whether
  the resulting `_undated/` classification looks correct.
- Tune `UNDATED_THRESHOLD` (default proposed: 60 seconds) based on findings.

DoD:
- [x] Heuristic validated against 36 real assets (30 with camera EXIF, 6 screenshots) — 100%
      agreement with independent ground truth. Full methodology and results in design.md
      Section 5.2.
- [x] Final `UNDATED_THRESHOLD` value: **60 seconds**, confirmed as-is, no tuning needed.
- [x] Terminology fix carried back into the spec: `date_source` value renamed from `exif` to
      `photos_date` (requirements.md FR-6, design.md Section 4/5.2) since the trustworthy branch
      isn't always camera-EXIF-derived (screenshots proved this concretely).

### T0.3 — Validate against the actual target library (the other Mac) — blocking for Milestone 1

T0.1/T0.2 validated osxphotos *mechanics* (opening a library, `export()`, Live Photo pairing,
the date heuristic) — those are expected to generalize and don't need re-testing. What they
*didn't* validate, because the spike library turned out to be an unrepresentative
secondary/receiving Mac (design.md Section 11.4), is the **availability picture**: whether
`ismissing`/`path` behave normally for a large, personally-uploaded library the way NFR-7
currently assumes.

- **Underway:** `scripts/validate_library.sh` was written for this — self-contained, read-only,
  self-cleaning, run by the user on the target Mac with output pasted back. Covers T0.1's
  enumeration (classification counts, `ismissing`/`path` resolution rates by media type, UUID
  uniqueness) and T0.2's date-heuristic spot-check in one pass.
- The target libraries live on an **external drive** — the script accounts for this: it falls
  back to a direct `/Volumes` filesystem search if Spotlight-based discovery finds nothing
  (common when indexing is off for an external drive), and reports the volume's filesystem
  format (APFS/HFS+ expected and confirmed by the user for this drive; NFR-8 — exFAT/NTFS
  wouldn't reliably support a Photos library at all, independent of this tool).
- Specifically check: what fraction of assets have a resolvable `path` without any extra setup
  (the expectation, per the user, is "originals are there" since they uploaded them personally)?
  Does the video `ismissing`-unreliability bug (design.md Section 5.5) also show up here, or was
  it specific to the spike library's Shared Albums content?

DoD:
- [ ] Availability rates measured on the real target library; NFR-7 either confirmed as a
      non-issue in practice (originals genuinely local, precondition trivially satisfied) or
      refined again based on what's actually found — no more hypothesizing from a
      non-representative library.
- [ ] design.md Section 11.6 updated with real results, closing out the "still open" item it
      currently tracks.
- [ ] If library size here is significantly larger than the spike library (10,267 assets),
      capture rough scale (asset count) to sanity-check NFR-3's streaming assumption is still
      comfortably sufficient.

## Milestone 1 — Project Scaffolding

### T1.1 — Python project setup

- `pyproject.toml`: package metadata, `requires-python = ">=3.14"`, `osxphotos` pinned per
  T0.1's outcome, `pytest` as a dev dependency.
- Package layout: `src/photos_to_amazon_photos/` with the modules from design.md Section 1.
- Console entry point (`photos-to-amazon-photos = ...:main`) matching the CLI in design.md
  Section 8.

DoD:
- [ ] `pip install -e .` succeeds; `photos-to-amazon-photos --help` runs and prints usage.

### T1.2 — Dev tooling

- Pick and configure a formatter/linter (e.g., `ruff`) and confirm `pytest` runs.
- Document the `test` / `lint` / `format` commands in the README (a `Makefile` is optional, not
  required).

DoD:
- [ ] `pytest` runs (even with zero tests) with no configuration errors.
- [ ] Lint command runs clean on the scaffolded skeleton.

## Milestone 2 — Core Modules

These four modules are pure computation — none of them write inside `target_root` (design.md
Section 1) — so build and unit-test them independently before wiring up orchestration.

### T2.1 — `tracking.py`

- Implements the schema in design.md Section 4 (all columns including `component`; composite
  key `(photo_uuid, component)`).
- `load(path) -> TrackingIndex`: parses an existing `tracking.csv` if present, empty index if
  not.
- `TrackingIndex.decision(uuid, component) -> Skip(reason) | Process`: implements FR-7's
  skip/process rules.
- `TrackingIndex.upsert(row)`: updates in-memory state.
- `TrackingIndex.flush(path)`: atomic write-temp-then-`os.replace`, per design.md Section 6.

DoD:
- [ ] Unit tests: missing file loads empty; existing file loads correctly; `status=copied` →
      skip; `status=ignored` → skip; `status=error` → reprocess; no row → process; `flush` is
      atomic (no partial file visible under a simulated interruption); write-then-load
      round-trips to the same rows.

### T2.2 — `date_resolver.py`

- Implements the heuristic from design.md Section 5.2, using T0.2's validated
  `UNDATED_THRESHOLD`.
- `resolve(date, date_added) -> (date_taken, date_source, is_undated)`.

DoD:
- [ ] Unit tests covering: `date_added is None`; `date == date_added`; `date` far from
      `date_added`; the boundary exactly at `UNDATED_THRESHOLD`.

### T2.3 — `namer.py`

- Implements design.md Section 5.4: filename format, `YYYY/MM/` + `_undated/` path computation
  per media type, Live Photo same-basename pairing under `live_photo/`.
- `target_path(media_type, component, date_taken, is_undated, original_stem, uuid, ext) -> Path`.

DoD:
- [ ] Unit tests: normal photo path; video path; Live Photo `key_image` + `live_bundle` pairing
      (same basename, correct extensions, correct subdirectories); undated routing to
      `_undated/`; determinism (same inputs → same output across repeated calls).

### T2.4 — `library_reader.py`

- Wraps `osxphotos.PhotosDB(library_path)`, strictly read-only (FR-2/NFR-5).
- `iter_assets() -> Iterator[AssetView]`: yields a small dataclass per `PhotoInfo` exposing only
  what downstream modules need (uuid, media_type per design.md Section 3's classification,
  source path(s), `hasadjustments`, `date`, `date_added`, original filename) — decouples the
  rest of the tool from osxphotos's own object model.

DoD:
- [ ] Unit tests for the classification logic (Section 3) using fixture/fake `PhotoInfo`-like
      objects, independent of a real library.
- [ ] Manual/integration check against the T0.1 sample library: classification counts
      (photo/video/live_photo) match a manual count in Photos.app for a small test album.

## Milestone 3 — Orchestration

### T3.1 — `stager.py`

- Wires T2.1–T2.4 together per design.md Sections 5–7 and 9: for each asset, compute its
  component(s) → tracking decision → export via `PhotoInfo.export()` (per T0.1's confirmed
  usage pattern) → checksum → optional metadata enrichment (exiftool if present, per Section 7)
  → tracking upsert — all wrapped in per-asset error handling (FR-10).
- Exiftool detection (`shutil.which("exiftool")`) done once at stager init, logged once.
- Depends on: T0.1, T2.1–T2.4.

DoD:
- [ ] Integration test against the T0.1 sample library into a scratch target dir: run twice back
      to back — the second run stages nothing new (idempotency, FR-7) and reports all-skipped.
- [ ] Test: deleting a staged file after a successful run, then re-running, does **not**
      re-stage it (FR-7's filesystem-vs-tracking-file rule).
- [ ] Test: manually marking a row `ignored` in `tracking.csv`, then re-running, does **not**
      re-stage it (FR-9).
- [ ] Test: a simulated per-asset failure marks that row `status=error` and does not abort the
      run (FR-10).

### T3.2 — `cli.py`

- Argument parsing per design.md Section 8 (`library_path`, `target_root`, `--tracking-file`,
  `--dry-run`, `--log-level`).
- Photos.app non-blocking warning check (design.md Section 5.3).
- `--dry-run` mode: runs the same decision logic as T3.1 but skips the actual export/write/
  tracking-flush steps, logging what *would* happen.
- Run summary printing (FR-10): counts by status × media_type.
- Depends on: T3.1.

DoD:
- [ ] `--dry-run` against the T0.1 sample library produces a sane plan with zero filesystem
      writes (target dir untouched; `tracking.csv` untouched or absent).
- [ ] A real run, followed by inspecting `photos/`, `video/`, `live_photo/`, and `tracking.csv`,
      matches expectations for the sample library.
- [ ] The Photos.app-open warning fires when Photos.app is running, and the run still completes
      (non-blocking, per design.md Section 5.3).

## Milestone 4 — Testing & Hardening

### T4.1 — End-to-end idempotency test

Full run → interrupt mid-run (kill the process) → re-run → verify no duplicate/corrupt output
and eventual completion. Exercises NFR-4 directly.

### T4.2 — Large-library smoke test

Run against the largest available real library (or a synthetic one of similar size) to sanity
check NFR-3 (memory stays bounded — spot-check with e.g. `/usr/bin/time -l`) and get a real
sense of expected runtime.

### T4.3 — Metadata spot-check

Manually inspect a handful of staged files' EXIF (`exiftool` or `mdls`) to confirm GPS/capture
date survived the copy (FR-4), exercising both the exiftool-present and exiftool-absent paths.

## Milestone 5 — Documentation & Handoff

### T5.1 — README usage section

Install instructions (Python 3.14, optional `exiftool` via Homebrew), example invocation,
example resulting directory tree, a note on quitting Photos.app first (NFR-6), and the
ignore-a-photo workflow (hand-edit `tracking.csv`, FR-9).

### T5.2 — Amazon Photos Backup folder setup notes

Short walkthrough (README section or `docs/upload-setup.md`) of pointing the Amazon Photos
desktop app's Backup feature at `<target_root>/photos/`, per design.md Section 10.

## Explicitly Not in This Tasks Doc

Everything in requirements.md [Section 10](requirements.md#10-future-enhancements) (Future
Enhancements) — a CLI ignore subcommand, perceptual dedup, multi-library merge tooling,
automated Amazon/S3 upload, etc. — stays out of scope for this implementation pass. Revisit only
once v1 is working end-to-end.
