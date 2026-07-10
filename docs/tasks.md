# Tasks: Photos-to-Amazon-Photos Preparer

Status: Draft (v0.9) — under review
Phase: 3 of 3 (Requirements → Design → **Tasks**)

**v0.6 note:** Milestone 1 (T1.1, T1.2) is done — project scaffolding exists and is verified
working (`pip install -e .`, `--help`, `pytest`, `ruff`). See the repo root and `src/` for the
actual code.

**v0.7 note:** Milestone 2 (T2.1–T2.4, the four pure-computation core modules) is done — 37
tests passing total (33 new: 12 tracking, 6 date_resolver, 9 namer, 6 library_reader unit + 1
integration), ruff clean.

**v0.8 note:** Milestone 3 (T3.1, T3.2 — orchestration) is done, and fully exercised against
the real Milestone-0 spike library at full scale via the actual CLI, not just small samples or
fakes: a real run staged exactly the 1,025 available assets and gracefully handled 13,310
unavailable ones in under 6 minutes, zero crashes. 50 tests passing, ruff clean.

**v0.9 note:** Milestone 4 (testing/hardening) is done, modulo T4.2's real-target-library scale
gap (documented below, not blocking). T4.1's manual interrupt testing found and fixed a genuine
bug — see its entry for details; this is exactly what this milestone exists for. T4.3 confirmed
GPS/capture-date survive the copy with real GPS-tagged assets, both with and without exiftool.
53 tests passing, ruff clean. Milestone 5 (documentation) is next and is the last one in this
tasks doc.

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

**v0.4 note:** T0.3 is done — all 6 real target libraries validated (138,893 assets total).
Availability confirmed a non-issue (0.023% unavailable), the video `ismissing` bug confirmed
spike-library-specific, and NFR-6 downgraded from MUST to SHOULD after 3/6 real runs succeeded
with Photos.app open. Full results in design.md Section 11.6. **Milestone 0 is now fully
complete** — nothing blocks starting Milestone 1.

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

### T0.3 — Validate against the actual target library (the other Mac) — ✅ DONE

T0.1/T0.2 validated osxphotos *mechanics* (opening a library, `export()`, Live Photo pairing,
the date heuristic) — those are expected to generalize and don't need re-testing. What they
*didn't* validate, because the spike library turned out to be an unrepresentative
secondary/receiving Mac (design.md Section 11.4), is the **availability picture**: whether
`ismissing`/`path` behave normally for a large, personally-uploaded library the way NFR-7
currently assumes.

- `scripts/validate_library.sh` was run by the user against all 6 real target libraries on the
  external drive (not just one), with output collected in `scripts/validate_library_output.txt`.
  Covered T0.1's enumeration (classification counts, `ismissing`/`path` resolution rates by
  media type, UUID uniqueness) and T0.2's date-heuristic spot-check in one pass per library.
- The target libraries live on an **external drive** — the script accounted for this: it falls
  back to a direct `/Volumes` filesystem search if Spotlight-based discovery finds nothing
  (common when indexing is off for an external drive), and reports the volume's filesystem
  format. Confirmed APFS (NFR-8) — no filesystem risk.

DoD:
- [x] Availability rates measured on all 6 real target libraries: **confirmed a non-issue in
      practice** — only 32 of 138,893 assets (0.023%) unavailable. NFR-7 stays documented but
      isn't expected to meaningfully affect real usage.
- [x] design.md Section 11.6 updated with real results, closing out the item it was tracking.
- [x] Scale captured: 138,893 assets combined, largest single library 46,141 (55% Live Photos).
      Confirmed comfortably within NFR-3's (updated) streaming assumption.
- [x] (Beyond original DoD, but a direct consequence of the data) Video `ismissing` bug
      confirmed spike-library-specific (0.045% of real videos vs. 91% on the spike library) —
      design.md Section 5.5 updated.
- [x] (Beyond original DoD) NFR-6 downgraded from MUST to SHOULD after 3 of 6 real runs
      succeeded with Photos.app open — requirements.md and design.md Sections 5.3/11.6 updated.
      This was an explicit user decision, not an automatic conclusion from the data alone.

**Milestone 0 is now complete.** All three tasks done, no blockers remain for Milestone 1.

## Milestone 1 — Project Scaffolding

### T1.1 — Python project setup — ✅ DONE

- `pyproject.toml`: package metadata, `requires-python = ">=3.14"`, `osxphotos` pinned per
  T0.1's outcome, `pytest` as a dev dependency.
- Package layout: `src/photos_to_amazon_photos/` with the modules from design.md Section 1.
- Console entry point (`photos-to-amazon-photos = ...:main`) matching the CLI in design.md
  Section 8.

DoD:
- [x] `pip install -e .` succeeds; `photos-to-amazon-photos --help` runs and prints usage.
      `cli.py` implements the full FR-1/Section 8 argument surface (both positionals, all three
      options) and validates `library_path` exists. The five other modules
      (`library_reader.py`, `date_resolver.py`, `namer.py`, `tracking.py`, `stager.py`) exist as
      documented stubs, each pointing at the design.md section and task that implements it —
      `main()` currently logs "not yet implemented" and exits 1 after successful arg validation,
      rather than silently doing nothing or pretending to work.

### T1.2 — Dev tooling — ✅ DONE

- Pick and configure a formatter/linter (e.g., `ruff`) and confirm `pytest` runs.
- Document the `test` / `lint` / `format` commands in the README (a `Makefile` is optional, not
  required).

DoD:
- [x] `pytest` runs — 4 real tests in `tests/test_cli.py` (not placeholders): `--help` exits 0
      and prints usage, missing required args exits 2, a nonexistent `library_path` exits 2, and
      valid args parse successfully but correctly report "not yet implemented" (exit 1). All 4
      pass.
- [x] `ruff check .` and `ruff format --check .` both pass clean on the scaffolded skeleton.
- [x] README updated with install/test/lint/format instructions.

## Milestone 2 — Core Modules

These four modules are pure computation — none of them write inside `target_root` (design.md
Section 1) — so build and unit-test them independently before wiring up orchestration.

### T2.1 — `tracking.py` — ✅ DONE

- Implements the schema in design.md Section 4 (all columns including `component`; composite
  key `(photo_uuid, component)`).
- `load(path) -> TrackingIndex`: parses an existing `tracking.csv` if present, empty index if
  not.
- `TrackingIndex.decision(uuid, component) -> Skip(reason) | Process`: implements FR-7's
  skip/process rules.
- `TrackingIndex.upsert(row)`: updates in-memory state.
- `TrackingIndex.flush(path)`: atomic write-temp-then-`os.replace`, per design.md Section 6.

DoD:
- [x] Unit tests: missing file loads empty; existing file loads correctly; `status=copied` →
      skip; `status=ignored` → skip; `status=error` → reprocess; no row → process; `flush` is
      atomic (no partial file visible under a simulated interruption); write-then-load
      round-trips to the same rows. 12 tests in `tests/test_tracking.py`, all passing —
      including one extra beyond the listed DoD: `status=copied` with a missing/malformed
      `timestamp_processed` is treated as unreliable and reprocessed (FR-7's literal wording),
      and one confirming `flush()` creates the target directory if missing.

### T2.2 — `date_resolver.py` — ✅ DONE

- Implements the heuristic from design.md Section 5.2, using T0.2's validated
  `UNDATED_THRESHOLD`.
- `resolve(date, date_added) -> (date_taken, date_source, is_undated)`.

DoD:
- [x] Unit tests covering: `date_added is None`; `date == date_added`; `date` far from
      `date_added`; the boundary exactly at `UNDATED_THRESHOLD` (and just inside it, to pin down
      the strict-inequality behavior). 6 tests in `tests/test_date_resolver.py`, all passing.
      Implemented as a `NamedTuple` so callers can use either tuple-unpacking (matching the
      design doc's literal signature) or named attributes.

### T2.3 — `namer.py` — ✅ DONE

- Implements design.md Section 5.4: filename format, `YYYY/MM/` + `_undated/` path computation
  per media type, Live Photo same-basename pairing under `live_photo/`.
- `target_path(media_type, component, date_taken, is_undated, original_stem, uuid, ext) -> Path`.

DoD:
- [x] Unit tests: normal photo path; video path; Live Photo `key_image` + `live_bundle` pairing
      (same basename, correct extensions, correct subdirectories); undated routing to
      `_undated/`; determinism (same inputs → same output across repeated calls). 9 tests in
      `tests/test_namer.py`, all passing. The Live Photo pairing requirement falls directly out
      of the naming formula (same inputs except `ext` → same basename) rather than needing
      dedicated pairing logic — verified explicitly by a test calling `target_path()` twice.

### T2.4 — `library_reader.py` — ✅ DONE

- Wraps `osxphotos.PhotosDB(library_path)`, strictly read-only (FR-2/NFR-5).
- `iter_assets() -> Iterator[AssetView]`: yields a small dataclass per `PhotoInfo` exposing only
  what downstream modules need (uuid, media_type per design.md Section 3's classification,
  source path(s), `hasadjustments`, `date`, `date_added`, original filename) — decouples the
  rest of the tool from osxphotos's own object model. `AssetView` also carries a thin
  `export()` passthrough to the underlying `PhotoInfo` (needed for T3.1; kept minimal, no
  orchestration logic here).

DoD:
- [x] Unit tests for the classification logic (Section 3) using fixture/fake `PhotoInfo`-like
      objects, independent of a real library. 6 tests in `tests/test_library_reader.py`.
- [x] Integration check against the T0.1 sample library — **substituted** an automated
      regression check for the literal "manual count in Photos.app" the DoD asked for, since
      that's a GUI step no automated test can perform: `tests/test_library_reader_integration.py`
      opens the real spike library and asserts `LibraryReader`'s classification counts match the
      exact numbers independently confirmed via raw osxphotos during the Milestone 0 spike
      (photo=5737, video=462, live_photo=4068, 10267 total, all UUIDs unique). Skipped
      automatically on any machine without that library (e.g. a fresh clone).

## Milestone 3 — Orchestration

### T3.1 — `stager.py` — ✅ DONE

- Wires T2.1–T2.4 together per design.md Sections 5–7 and 9: for each asset, compute its
  component(s) → tracking decision → export via `PhotoInfo.export()` (per T0.1's confirmed
  usage pattern) → checksum → optional metadata enrichment (exiftool if present, per Section 7)
  → tracking upsert — all wrapped in per-asset error handling (FR-10).
- Exiftool detection (`shutil.which("exiftool")`) done once at stager init, logged once.
- Depends on: T0.1, T2.1–T2.4.
- Extra design decision made during implementation, not pre-specified: Live Photo ignore
  propagates across both `key_image`/`live_bundle` rows (design.md Section 4's "done as one
  logical operation by the stager") — if a user hand-marks either row ignored, the stager
  treats the whole asset as ignored and writes the sibling row to match, rather than requiring
  both to be marked by hand.

DoD:
- [x] Integration test against the T0.1 sample library into a scratch target dir: run twice back
      to back — the second run stages nothing new (idempotency, FR-7) and reports all-skipped.
      `tests/test_stager_integration.py` (real library, 15-asset sample of available-path
      assets). Also validated at **full scale**: a real run against the entire 10,267-asset
      library via the actual CLI staged exactly the 1,025 available assets (688 live_photo +
      296 photo + 41 video components — matching the T0.1/T0.3 "available" counts exactly) and
      gracefully errored the other 13,310 in 5m49s wall time, exit code 0, zero crashes.
- [x] Test: deleting a staged file after a successful run, then re-running, does **not**
      re-stage it (FR-7's filesystem-vs-tracking-file rule). `test_deleted_staged_file_not_restaged`.
- [x] Test: manually marking a row `ignored` in `tracking.csv`, then re-running, does **not**
      re-stage it (FR-9). `test_manually_ignored_row_not_restaged`.
- [x] Test: a simulated per-asset failure marks that row `status=error` and does not abort the
      run (FR-10). `test_failure_marks_error_and_continues`.
- [x] (Beyond DoD) Live Photo dual-export + basename pairing verified end to end, both with
      fakes (`test_live_photo_stages_key_image_and_live_bundle_with_pairing`) and via a manual
      real-library run (inspected the actual staged `.jpeg`/`.mov` pairs on disk).
- [x] (Beyond DoD) Ignore-propagation across a Live Photo's two rows
      (`test_live_photo_ignore_propagates_to_both_components`), empty-export-result handling
      (`test_empty_export_result_marks_error_not_available`), and dry-run writing nothing
      (`test_dry_run_writes_nothing`).

### T3.2 — `cli.py` — ✅ DONE

- Argument parsing per design.md Section 8 (`library_path`, `target_root`, `--tracking-file`,
  `--dry-run`, `--log-level`) — already done in T1.1.
- Photos.app non-blocking warning check (design.md Section 5.3).
- `--dry-run` mode: runs the same decision logic as T3.1 but skips the actual export/write/
  tracking-flush steps, logging what *would* happen.
- Run summary printing (FR-10): counts by status × media_type, via `print()` so it's always
  visible regardless of `--log-level`.
- Depends on: T3.1.
- Extra robustness added during implementation: `stager.run()` is wrapped in a try/except so a
  library that can't be opened at all (distinct from FR-10's per-asset error handling, which
  already can't raise) fails with a clean message and exit 1, not an uncaught traceback.

DoD:
- [x] `--dry-run` against the T0.1 sample library (full 10,267 assets, via the real CLI):
      produced `live_photo: would_stage=8136, photo: would_stage=5737, video: would_stage=462,
      total: 14335` with zero filesystem writes (target dir did not exist afterward) — exit 0.
- [x] A real run (full library, via the real CLI), followed by inspecting `photos/`, `video/`,
      `live_photo/`, and `tracking.csv`: file counts cross-checked exactly against the tracking
      CSV's status breakdown (`photos/`=640 = 296 single + 344 key_image; `live_photo/`=688 =
      344×2 paired still+`.mov`; `video/`=41), `_undated/` correctly populated for assets
      without a trustworthy date, all 14,335 tracking rows accounted for.
- [x] The Photos.app-open warning fires when Photos.app is running, and the run still completes
      (non-blocking) — verified via `test_photos_app_warning_logged_when_running` (mocked, since
      the check needs to be deterministic in tests) and confirmed non-blocking by design (a plain
      `log.warning()`, no gate).

**Milestone 3 is now complete.** 50 tests total, ruff clean. This is the first milestone where
the tool actually stages real files — and it was fully exercised against the real Milestone-0
spike library at full scale, not just small samples.

## Milestone 4 — Testing & Hardening

### T4.1 — End-to-end idempotency test — ✅ DONE, found and fixed a real bug

Full run → interrupt mid-run (kill the process) → re-run → verify no duplicate/corrupt output
and eventual completion. Exercises NFR-4 directly.

- **Found a real gap via manual `kill -9` testing**: a crash can leave a file successfully
  moved into its final deterministic path with no tracking row ever flushed for it (e.g. killed
  before the first periodic flush). On resume, the old behavior treated the pre-existing file as
  a hard collision and errored — forever, since every retry hits the same collision. That
  directly violates "eventual completion."
- **Fixed** in `stager.py`'s `_stage_component()`: when the computed target path already
  exists, compare checksums between the fresh export and the existing file. Matching content
  means a prior interrupted run already finished this exact file — adopt it (no re-move, no
  error). Content that genuinely differs still fails loudly rather than silently overwriting,
  preserving design.md Section 5.4's original intent for true collisions.
- Verified `PhotoInfo.export()` is deterministic (same settings -> byte-identical output across
  repeated calls) before trusting the checksum-match approach — confirmed directly against the
  real spike library.
- Two regression tests added: `test_orphaned_staged_file_with_matching_content_is_adopted_not_errored`
  and `test_genuine_collision_with_different_content_still_errors` (fast, deterministic, fakes).
- Plus the real thing: `tests/test_interrupt_recovery.py` launches a genuine OS subprocess
  against a small real sample (8 available assets from the spike library), sends actual
  `SIGKILL` (no Python cleanup code runs at all), then resumes and verifies no duplication, no
  corrupted tracking CSV, previously-copied files stay copied, and every row reaches a terminal
  status. Passes.

### T4.2 — Large-library smoke test — partially done; real target library not reachable from here

Run against the largest real target library — `Photos_2017-2024.photoslibrary`, 46,141 assets
(55% Live Photos), confirmed via T0.3 — to sanity check NFR-3 (memory stays bounded — spot-check
with e.g. `/usr/bin/time -l`) and get a real sense of expected runtime. If feasible, a full run
across all 6 libraries into one shared `target_root`/tracking file (~139,000 assets combined) is
an even better real-world test, since that's the realistic usage pattern implied by the
libraries' date-range naming.

- **Constraint discovered while starting this task**: the actual named library lives on the
  external drive attached to the user's *other* Mac (T0.3), which isn't mounted or reachable
  from this environment. Ran the memory/runtime smoke test against the spike library instead
  (10,267 assets, real data, just not the literal named target) — full run under `/usr/bin/time
  -l`: **295.8s wall time, 369MB peak memory footprint (508MB max RSS)** for 14,335 total
  component attempts (1,025 real copies + 13,310 fast-failing "not available" attempts). Memory
  stayed well bounded, consistent with the streaming design (NFR-3) — no sign of unbounded
  growth.
- **Not done**: the 46K/139K-asset real-scale run and its memory/runtime numbers specifically.
  This would need the user to either run the tool themselves on the other Mac, or provide
  access. Deliberately not asking for this proactively right now — a full real run there means
  real disk usage and real files created before Milestone 5 has even documented where
  `target_root` should live or how to wire up the Amazon Photos Backup folder. The user's actual
  first real production run (once they're ready, after Milestone 5) will be a far more
  meaningful validation of this than a smoke test requested in isolation.

### T4.3 — Metadata spot-check — ✅ DONE

Manually inspect a handful of staged files' EXIF (`exiftool` or `mdls`) to confirm GPS/capture
date survived the copy (FR-4), exercising both the exiftool-present and exiftool-absent paths.

- Found 3 real assets in the spike library with genuine GPS coordinates (the library has zero
  real keywords or named persons anywhere, confirmed by an exhaustive scan — same finding as the
  Milestone 0 spike, so the keyword/person exiftool-enrichment path still has no positive
  real-data test available; the mechanism itself was already confirmed to run without error in
  Milestone 0).
- Staged with `exiftool_available=True`: `exiftool` readback matched the source GPS coordinates
  exactly (e.g. source `(40.7739, -74.3989)` -> staged file's `GPSLatitude`/`GPSLongitude` of
  `40°46'26.05"N`/`74°23'55.91"W`, which convert back to the same value), plus correct
  `DateTimeOriginal` and camera `Make`/`Model`.
- Staged the **same kind of asset with `exiftool_available=False`**: GPS and capture date still
  present and correct, confirming FR-4's "MUST" (embedded EXIF preservation via direct byte
  copy) is fully independent of the optional exiftool "SHOULD" enrichment.
- Cross-checked one file with `mdls` too, per the DoD's suggested alternative tool: it returned
  null/wrong values, but that's `/tmp` not being Spotlight-indexed and the file being
  milliseconds old — an artifact of the indexing lag, not a real metadata gap (`exiftool` reads
  embedded bytes directly with no such lag, and already gave the authoritative, correct answer).

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
