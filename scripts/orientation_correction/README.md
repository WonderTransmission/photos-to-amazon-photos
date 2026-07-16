# orientation-correction

Detects sideways/upside-down photos under a directory and corrects them in place, backing up
each original alongside it first. Built to run against staged output from the main
`photos-to-amazon-photos` tool, before handing that folder off to Amazon Photos Backup.

See [`docs/how-it-works.md`](docs/how-it-works.md) for how detection and correction actually
work (model, preprocessing, rotation-direction mapping, crash safety, idempotency) — this README
just covers getting it running.

## Installation

Requires **Python 3.14+**. This is a self-contained sub-project with its own venv, independent
of the main package's dependencies (onnxruntime/pillow-heif are heavy and specialized).

```sh
cd scripts/orientation_correction
python3.14 -m venv .venv
source .venv/bin/activate
pip install .
```

You also need the ONNX model file, which isn't committed here (~80MB binary) — see
[`models/README.md`](models/README.md) for how to get it and where to put it.

## Usage

Dry run first — reports what it would do and writes a preview-links file, without touching any
files:

```sh
orientation-correct /path/to/staged/photos
```

Once you've spot-checked the results (see [preview links](docs/how-it-works.md#preview-links) in
how-it-works.md — each Preview.app window opens on a divider page naming its category and
directory, so it's obvious what you're looking at even across many subdirectories), actually
apply the corrections:

```sh
orientation-correct /path/to/staged/photos --apply
```

Full option list: `orientation-correct --help`. The notable ones:

| Flag | Effect |
|---|---|
| `--apply` | Actually back up and correct files. Without it, dry-run only. |
| `--min-confidence FLOAT` | Below this model confidence, a flagged image is left untouched and listed for manual review instead of auto-corrected (default `0.0`, off). |
| `--model-path PATH` | Override the default `models/best_model.onnx` location. |
| `--log-dir PATH` | Where the run log, preview-links, and review checklist are written (default `logs/`). |
| `--ignore-list PATH` | Persistent list of confirmed false positives to always skip (default `ignore-list.txt`). |
| `--log-level {DEBUG,INFO,WARNING,ERROR}` | Verbosity (default `INFO`). |

### Found a false positive?

Every run writes a `review-<timestamp>.txt` checklist alongside the preview-links script. Delete
the lines for files that are actually fine, leaving only the wrong ones, then:

```sh
orientation-correct-revert logs/review-<timestamp>.txt
```

This restores each listed file from its backup and adds it to a persistent ignore list, so
future runs never flag it again. See
[reviewing and reverting false positives](docs/how-it-works.md#reviewing-and-reverting-false-positives)
for the details.

### Before running

- **Pause Amazon Photos Backup** on any folder you're about to correct — see the
  [caveat in how-it-works.md](docs/how-it-works.md#a-note-on-the-amazon-photos-backup-workflow).
- **On macOS Tahoe (26.x)**, set System Settings → Desktop & Dock → Windows → *Prefer tabs when
  opening documents* to *Always* — otherwise the preview-links script's divider pages open in
  their own separate windows instead of alongside the photos they're labeling. See
  [the Tahoe note in how-it-works.md](docs/how-it-works.md#macos-tahoe-one-more-setting-needed-for-this-to-actually-work).
- Try a small subdirectory with `--apply` first, run the generated preview-links script, and
  confirm the corrections look right before scaling up to a full archive.

## Development

```sh
cd scripts/orientation_correction
python3.14 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

```sh
pytest       # run tests (all fixtures generated on the fly, no real photos needed)
ruff check .  # lint
```

An opt-in regression test checks a real photo against a known-correct answer — see
`tests/test_infer.py::test_known_orientation_regression` for the environment variables it reads;
it's skipped by default since it needs a real photo path and the downloaded model.
