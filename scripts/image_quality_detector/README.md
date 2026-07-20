# image-quality-detector

Finds totally overexposed, totally underexposed, extremely blurry, and (optionally) duplicate
photos under a directory and quarantines them for review. Built to run against staged output
from the main `photos-to-amazon-photos` tool, before handing that folder off to Amazon Photos
Backup -- so these don't get backed up alongside everything else. Uses
[CleanVision](https://github.com/cleanlab/cleanvision)'s issue checks, at CleanVision's own
default thresholds.

## Installation

Requires **Python 3.14+**. This is a self-contained sub-project with its own venv, independent
of the main package's dependencies.

```sh
cd scripts/image_quality_detector
python3.14 -m venv .venv
source .venv/bin/activate
pip install .
```

## Usage

Dry run first -- reports what it would flag and writes a preview-links script per issue
category, without touching any files:

```sh
image-quality-detect /path/to/staged/photos
```

Open the generated `preview-links-*.sh` scripts (see below) to eyeball the flagged photos in
Preview.app -- each group's first image is a divider naming its category and directory. Once
they look right, actually quarantine them:

```sh
image-quality-detect /path/to/staged/photos --apply
```

There's nothing to "correct" about a blurry or over/under-exposed photo the way there is for a
sideways one, so `--apply` doesn't rewrite any pixels -- it just moves each flagged file from
`<dir>/<name>` to `<dir>/_quality_review/<category>/<name>`, out of the tree that gets backed up.
A file matching more than one check (e.g. both dark and blurry) goes to a combined category
folder like `_quality_review/dark+blurry/`.

Full option list: `image-quality-detect --help`. The notable ones:

| Flag | Effect |
|---|---|
| `--apply` | Actually quarantine flagged files. Without it, dry-run only. |
| `--checks LIST` | Comma-separated checks to run, from `blurry`, `dark`, `light`, `exact_duplicates`, `near_duplicates` (default: `blurry,dark,light`). |
| `--workers N` | Parallel worker processes for CleanVision's analysis (default: 1 -- CleanVision's multiprocessing only works reliably when this tool is run as the installed command, not e.g. piped through `python -c`). |
| `--log-dir PATH` | Root directory for run output (default `logs/`) -- each run gets its own timestamped subdirectory here with the run log, preview-links scripts, review checklist, `error_filenames.txt`, and a `dividers/` subdirectory. |
| `--ignore-list PATH` | Persistent list of confirmed false positives to always skip (default `ignore-list.txt`). |
| `--log-level {DEBUG,INFO,WARNING,ERROR}` | Verbosity (default `INFO`). |

### Checks

- `blurry`, `dark`, `light` — run by default. Each is a per-image check: CleanVision scores one
  file at a time, and a flagged file is quarantined on its own.
- `exact_duplicates`, `near_duplicates` — opt in with `--checks`, e.g.
  `--checks blurry,dark,light,exact_duplicates,near_duplicates`. These flag a *set* of matching
  files, not one offending file, so there's no single file to act on until something decides
  which member(s) to keep. This tool keeps the first file in each set (sorted path order) where
  it is, and treats every other member of that set as flagged -- so `--apply` quarantines all
  but one copy per set. A file that's simultaneously, say, blurry and the non-kept half of a
  duplicate pair goes to a combined folder like `_quality_review/blurry+exact_duplicates/`.

### Found a false positive?

Every run writes a `review.txt` checklist in that run's own directory, alongside the
preview-links scripts. Delete the lines for files that are genuinely bad, leaving only the wrong
ones, then:

```sh
image-quality-detect-revert logs/<run_timestamp>/review.txt
```

If the file was quarantined (`--apply`), this moves it back to its original location. Either
way, it's added to the persistent ignore list so future runs never flag it again.

### Before running

- **Pause Amazon Photos Backup** on any folder you're about to run `--apply` against, same
  caveat as `orientation_correction`.
- Try a small subdirectory with `--apply` first, run the generated preview-links script(s), and
  confirm the results look right before scaling up to a full archive.

## Development

```sh
cd scripts/image_quality_detector
python3.14 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

```sh
pytest       # run tests (all fixtures generated on the fly, no real photos needed)
ruff check .  # lint
```
