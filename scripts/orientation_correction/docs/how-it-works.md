# How orientation-correction works

Finds photos in a staged directory that are sideways or upside-down, and corrects them in
place, keeping a same-directory backup of every file it touches.

```
orientation-correct <input_dir>              # dry run: report + preview-links only
orientation-correct <input_dir> --apply       # actually back up and correct files
```

## Model

Detection uses the ONNX model from
[duartebarbosadev/deep-image-orientation-detection](https://github.com/duartebarbosadev/deep-image-orientation-detection)
(v2 release, MIT licensed) -- an EfficientNetV2-S fine-tuned to classify an image into one of
four buckets: 0°, 90°, 180°, or 270° of rotation relative to upright. It reports 98.82% accuracy
on its own validation set (COCO + a couple of Kaggle datasets + a personal photo collection --
see that repo's README for details). That number is **not** a guarantee for this archive's mix
of old scanned prints and consumer digital-camera photos, which is why this tool defaults to
dry-run and always produces a [preview-links](#preview-links) file for a manual pass.

The model file itself (`models/best_model.onnx`, ~80MB) is not committed here -- see
[`models/README.md`](../models/README.md) for how to get it. `--model-path` overrides the
default location if you keep it elsewhere.

### Why no dependency on the source repo or on torch/torchvision

This tool doesn't import `deep-image-orientation-detection`'s code or depend on torch/
torchvision at all -- `orientation_correction/infer.py` is a from-scratch reimplementation of
its `predict_onnx_batch.py` preprocessing, using only Pillow + numpy + onnxruntime. This works
because torchvision's `transforms.Resize`/`CenterCrop`, when given a PIL Image (as the source
repo's predict scripts do, prior to `ToTensor()`), just call PIL's own `Image.resize()`/
`Image.crop()` under the hood -- so reproducing those two calls directly is not an
approximation, it's the same operation with one less dependency layer:

```python
img = ImageOps.exif_transpose(img)                      # bake in any existing EXIF orientation
img = img.resize((416, 416), Image.BILINEAR)             # matches transforms.Resize((416, 416))
img = img.crop((16, 16, 400, 400))                        # matches transforms.CenterCrop(384)
arr = (np.asarray(img, dtype=np.float32) / 255.0 - IMAGENET_MEAN) / IMAGENET_STD
arr = arr.transpose(2, 0, 1)                               # HWC -> CHW
```

This also means the tool has no torch/torchvision dependency at all -- just `onnxruntime`,
`pillow`, `pillow-heif`, and `numpy`, all of which ship Python 3.14 wheels for macOS, so this
sub-project can use its own modern venv independent of the main package.

## Preprocessing basis: "as rendered", not "as stored"

Before anything else, `ImageOps.exif_transpose()` is applied -- both when the model judges an
image (`infer.py`) and when the correction is actually written (`correct.py`). This means the
model's decision, and the correction, are both based on how the photo would render in any
EXIF-aware viewer (Preview.app, Amazon Photos, etc.), not on the raw stored pixel grid. A photo
whose pixels are physically sideways but which carries a correct EXIF `Orientation` tag (so it
already displays correctly) is left alone -- exactly as it should be, since nothing is actually
wrong with it.

## Class → rotation mapping

The model predicts which of 4 rotations was applied to an originally-upright image; the
corrective action is the inverse of that:

| Predicted class | Meaning | Corrective rotation |
|---|---|---|
| 0 | already upright | none |
| 1 | rotated 90° | 90° clockwise |
| 2 | rotated 180° | 180° |
| 3 | rotated 270° | 90° counter-clockwise (= 270° clockwise) |

### Rotation direction (the part most likely to silently invert)

PIL's `Image.Transpose.ROTATE_90`/`ROTATE_270` constants follow the mathematical
(counter-clockwise-positive) convention, which is the *opposite* of what the names might suggest
at a glance -- `ROTATE_270` is the one that applies a 90°-**clockwise** correction, not
`ROTATE_90`. This was verified empirically (not assumed) with a synthetic marker image before
being wired into `infer.rotate_op_for_degrees()`:

```python
>>> img = <image with a marker in the top-left corner>
>>> img.transpose(Image.Transpose.ROTATE_270).<marker is now in the top-right corner>
```

Physically rotating a photo 90° clockwise moves its top-left corner to the top-right -- which is
exactly what `ROTATE_270` does, confirming the mapping. This is also locked in by
`tests/test_infer.py::test_rotate_op_for_degrees_mapping` and by a corner-marker round-trip test
in `tests/test_correct.py`, and was cross-checked against the real, previously-manually-confirmed
case from the original research session (a specific photo needing a 90°-clockwise correction --
see `tests/test_infer.py::test_known_orientation_regression`, which takes the real photo path via
an environment variable rather than a hardcoded path, so nothing real-archive-specific is
committed to this repo).

## What happens to a corrected file

For each image predicted as needing correction (and above `--min-confidence`, see below):

1. The original is renamed to `<filename>.orig.<run_timestamp>` in the same directory (one
   timestamp shared by every backup created in a given run).
2. The corrected pixels are written back to the original filename.
3. EXIF metadata (`DateTimeOriginal`, GPS, camera make/model, etc.) is preserved, but the
   `Orientation` tag is stripped -- it's already been baked into the pixels by step 2's
   `exif_transpose`, so leaving a stale tag behind would make a viewer double-rotate the result.
4. JPEG is re-encoded at `--jpeg-quality` (default 95); PNG is re-saved losslessly; HEIC is
   re-encoded at `--heif-quality` (default 90) via `pillow-heif`.

### Crash safety

The decode → rotate → re-encode work happens entirely into a temp file
(`.<filename>.orientation_tmp`) before anything at the real path is touched. Only once that
succeeds do two renames happen back-to-back: original → backup, then temp → original. Each
rename is a fast, near-instant filesystem metadata operation, which keeps the window in which an
interrupted run (crash, power loss, `kill -9`) could leave things inconsistent about as small as
it can practically be made without an OS-level transaction across two paths. If the slow part
(the encode) fails or raises for any reason, the original is completely untouched -- verified by
`tests/test_correct.py::test_correct_image_rolls_back_on_write_failure`.

The one residual gap: a crash landing in the few-microsecond window between the two renames could
leave the original filename briefly missing, with its corrected bytes sitting under the
`.orientation_tmp` name and the pre-correction bytes recoverable from the `.orig.*` backup. This
is exceedingly unlikely (needs a hard kill at that exact instant) and not specially handled in v1
-- if you ever see a stray `.<name>.orientation_tmp` file after an interrupted run, that's what
happened; rename it back manually.

### Idempotency / resuming a large run

Discovery (`discover.py`) skips any file already named like a backup, and the orchestrator
(`cli.py`) skips any file that already *has* a backup (i.e. was corrected by an earlier run)
before even running inference on it. This means:

- Backups are never mistaken for new images to scan.
- Re-running `--apply` on a partially-done (or fully-done) directory is fast and safe -- already-
  corrected files are skipped entirely, not re-rotated.
- There's no separate checkpoint/resume file; the filesystem state itself is the resume point.

## `--min-confidence`

Default `0.0` (off) -- matches the simple argmax behavior the model's own predict scripts use,
which is what the original research session validated manually. If spot-checks turn up false
positives, raising this (e.g. `--min-confidence 0.8`) causes borderline predictions to be left
untouched and listed in a separate "low confidence" section of the preview-links file for manual
review, rather than auto-corrected. In practice this doesn't fully eliminate false positives --
some wrong corrections come through confidently -- which is what
[reviewing and reverting false positives](#reviewing-and-reverting-false-positives) is for.

## Preview links

Every run (dry-run or `--apply`) writes a `preview-links-<run_timestamp>.sh` script to
`--log-dir` (default `logs/`, next to this doc). It groups flagged files by their containing
directory and writes an `open -a preview` command for each group, in three labeled sections:

- **Corrected** -- files actually rotated this run (`--apply` only).
- **Would be corrected** -- what a dry run found; re-run with `--apply` once these look right.
- **Low confidence** -- predicted as needing rotation but below `--min-confidence`; not touched
  either way, flagged for a human decision.

Run it (`bash logs/preview-links-<timestamp>.sh`) to pop open Preview.app on everything flagged,
directory by directory, so you can eyeball whether the correction (or the flag) makes sense
before trusting a large batch.

### Divider pages

A run over an archive with many subdirectories opens many separate Preview.app windows in quick
succession -- across three possible categories, per directory -- and it's easy to lose track of
which window is showing which category for which directory. To make that unambiguous, the
*first* file passed to each `open -a preview` command is a small divider image (`divider.py`,
built with Pillow alone -- no new dependency) stating the category and the full directory path
in large text, e.g.:

```
ORIENTATION REVIEW

Would be corrected (dry-run)

/Volumes/ExternalDrive/staging/photos/2003/02

52 file(s)
```

It's written as a **PNG, deliberately not a PDF**: Preview.app treats a PDF as a structurally
different kind of document from a batch of images -- even when passed on the same `open`
command line, it opens in its own separate window rather than joining the multi-image browsing
session, which defeats the point. A PNG is the same "kind" as the JPEGs/HEICs that follow it, so
Preview merges it into that same window as the very first thumbnail.

These are written to `--log-dir/dividers-<run_timestamp>/` (one image per category+directory
group, never inside the photo directory itself) and are pure review scaffolding -- nothing to
clean up before re-enabling Amazon Photos Backup, since they never touch the staged tree.

## Reviewing and reverting false positives

Every run also writes a `review-<run_timestamp>.txt` checklist next to the preview-links script
(only when something was actually flagged) -- one absolute path per line, covering everything in
the **Corrected** and **Would be corrected** sections above (not **Low confidence**, since those
were never touched either way -- there's nothing to revert).

The workflow:

1. Open the preview-links script to eyeball the results in Preview.app.
2. In the review checklist, **delete the line for every file that's actually fine.** Leave only
   the false positives. (In practice this is fast, since correctly-classified files are the
   majority -- there's usually only a handful of lines left.)
3. Run the command the checklist file itself tells you to (also shown here):
   ```sh
   python -m orientation_correction.revert logs/review-<timestamp>.txt
   ```
   or, if installed: `orientation-correct-revert logs/review-<timestamp>.txt`

For each remaining path, this:

- **If it was actually corrected** (`--apply` was used): restores the original bytes from its
  `.orig.*` backup back onto the real filename -- a single rename, which also consumes
  (removes) the backup. The wrongly-rotated bytes aren't kept around afterward; once restored,
  they have no value and keeping them would just be one more file type to clean up before
  re-enabling Amazon Photos Backup (see below).
- **If it was only a dry-run candidate** (nothing was ever written to disk): there's nothing to
  restore, so it's just added to the ignore list -- logged as "no backup found", which is
  expected and not an error in this case.
- **Either way**, the path is appended to a persistent ignore list (`ignore-list.txt` by
  default, next to `models/` -- override with `--ignore-list` on both commands, and keep them in
  sync). Every future `orientation-correct` run loads this file and skips anything on it, before
  even running inference -- this is what makes a reverted file stay fixed instead of getting
  flagged the same wrong way again on the next run.

The ignore list is a plain path list (see `ignore_list.py`), so it doesn't survive a rename or
move of the file -- the same limitation the main `photos-to-amazon-photos` tool's own
`tracking.csv`-based ignore workflow already accepts (see its README). It's gitignored, like
`logs/`, since it accumulates real archive file paths over time.

## Logging

Dual stdout + timestamped file (`logs/orientation-correction-<timestamp>.log`), so a run's
progress survives even if the terminal session is lost. Progress is logged at 5% milestones
(same pattern as the main tool's `stager.py`), so output stays roughly constant-length regardless
of how many images are being processed. Per-file errors (a corrupt or unreadable image, a failed
write) are logged and counted but never abort the run -- one bad file shouldn't cost you the rest
of a multi-thousand-photo batch.

## A note on the Amazon Photos Backup workflow

Per [`../../../docs/upload-setup.md`](../../../docs/upload-setup.md), the Amazon Photos desktop
app's Backup feature watches `target_root/photos/` and uploads anything new in it, with no
file-type filtering. Backup files this tool creates (`*.orig.*`) would get swept up and uploaded
as junk if Backup is watching the folder while this tool runs. **Run this tool before enabling
(or while temporarily disabling) Amazon Photos Backup** on a directory, verify the results via
the preview-links file, and clean up (or otherwise resolve) the `.orig.*` backups before turning
Backup on/back on.

## Known limitations

- Model accuracy is unproven on this specific archive's photo mix (old scans, various cameras);
  dry-run + preview-links is the intended safety net, not a formality.
- JPEG correction re-encodes (not a lossless pixel transform), so a corrected JPEG isn't
  byte-identical in compression artifacts to a lossless rotation -- mitigated by keeping the
  `.orig.*` backup and defaulting to a high quality (95).
- See [Crash safety](#crash-safety) for the narrow residual crash window between the two renames.
