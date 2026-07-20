# photos-to-amazon-photos

Idempotent staging tool that pulls photos, videos, and Live Photos out of a local macOS
**Photos** library and copies the best available version of each into a plain, date-organized
directory tree — with original metadata (EXIF, GPS, capture date, etc.) intact — ready to
upload: still photos to **Amazon Photos**, video to **S3/Glacier**.

This project followed a spec-driven workflow. Each phase's document lives under [`docs/`](docs),
and is worth reading for the reasoning behind the tool's design, not just the "what":

1. [Requirements](docs/requirements.md) — what the tool must do and why.
2. [Design](docs/design.md) — how it does it, including several findings from testing against
   real Photos libraries that changed the original design.
3. [Tasks](docs/tasks.md) — the implementation breakdown, with real results recorded against
   each task (test counts, real timing/memory numbers, bugs found and fixed).

## Status

Functional. All planning and implementation milestones are done — see `docs/tasks.md` for the
full history, including two real-world findings worth knowing about: a crash-recovery bug found
and fixed via manual interrupt testing (T4.1), and a precondition (NFR-6, "quit Photos.app
first") that was downgraded from required to recommended after empirical testing.

## Installation

Requires **Python 3.14+**.

```sh
git clone git@github.com:WonderTransmission/photos-to-amazon-photos.git
cd photos-to-amazon-photos
python3.14 -m venv .venv
source .venv/bin/activate
pip install .
```

Optional, but recommended — without it, GPS/capture-date EXIF still survives the copy, but
Photos-only metadata (keywords, named persons) won't be embedded:

```sh
brew install exiftool
```

## Usage

```sh
photos-to-amazon-photos "/Users/you/Pictures/Photos Library.photoslibrary" /path/to/target
```

This processes **one library per run** — point it at another library (optionally sharing the
same `target_root`) as a separate invocation. Preview what a run would do first, with zero
filesystem writes:

```sh
photos-to-amazon-photos "/Users/you/Pictures/Photos Library.photoslibrary" /path/to/target --dry-run
```

Full option list: `photos-to-amazon-photos --help`. The notable ones:

| Flag | Effect |
|---|---|
| `--dry-run` | Compute and log the plan; touches nothing on disk. |
| `--tracking-file PATH` | Override the default `<target_root>/tracking.csv` location. |
| `--log-level {DEBUG,INFO,WARNING,ERROR}` | Verbosity (default `INFO`). The run summary always prints regardless of this setting. |

Every run also writes a timestamped log file (`photos-to-amazon-photos-YYYYMMDD-HHMMSS.log`) in
whatever directory you ran the command from, mirroring everything printed to the terminal —
including the final run summary, even if `--log-level` would otherwise suppress it. This is
specifically so you can tell whether a run completed (and what happened) even if you can't check
the terminal afterward, e.g. the Mac went to sleep or shut down unexpectedly before you got back
to it.

### Before running

- **iCloud originals must already be downloaded locally.** The tool never triggers an iCloud
  download itself (doing so would require driving Photos.app, which conflicts with the next
  point). If "Optimize Mac Storage" is on, or content was never explicitly saved into your
  library (e.g. Shared Albums content you only ever previewed), those assets will show up as
  `error`/"not available locally" in the tracking file and are retried automatically on future
  runs — see [design.md Section 11.5](docs/design.md#115-precondition-originals-must-be-available-locally-before-running).
- **Quitting Photos.app first is recommended, not required.** It's not officially supported by
  Apple to read the library while Photos.app is open, but real testing against 6 real libraries
  found no issues across 3 runs performed with it open — see
  [design.md Section 11.6](docs/design.md#116-t03-results-validated-against-the-actual-target-library).
  If it's open, you'll get a one-line warning; the run proceeds either way.
- **If your library is on an external drive**, it needs to be mounted, and should be formatted
  APFS or Mac OS Extended (HFS+) — Photos libraries aren't reliably supported on exFAT/NTFS.

### What you get

```
target/
├── photos/
│   ├── 2021/
│   │   └── 03/
│   │       └── 2021-03-09_IMG_7360_A41172E9.jpeg
│   └── _undated/
│       └── 2022-05-20_Screenshot 2022-05-20 at 2.52.02 PM_ADDFE6AB.jpeg
├── video/
│   └── 2020/
│       └── 01/
│           └── 2020-01-18_IMG_0433_39B083DB.mp4
├── live_photo/
│   └── 2024/
│       └── 09/
│           ├── 2024-09-18_IMG_5923_1AF55F6D.jpeg
│           └── 2024-09-18_IMG_5923_1AF55F6D.mov
└── tracking.csv
```

- `photos/` — still images, including the key/still image of every Live Photo. This is what
  you point Amazon Photos at — see [Uploading to Amazon Photos](docs/upload-setup.md).
- `video/` — standalone videos, destined for S3/Glacier (not automated by this tool).
- `live_photo/` — each Live Photo in full (still + `.mov`, sharing a basename so the pairing is
  recognizable by convention alone). Upload destination for this one is still undecided —
  currently just staged.
- `_undated/` (inside each of the above) — anything without a reliable capture date, so it
  doesn't pollute a real month's folder with a wrong guess.
- `tracking.csv` — the authoritative record of what's been processed. Re-running the tool is
  always safe: anything already marked `copied` is skipped, whether or not the file is still
  there (you can delete staged files after uploading them — the tool won't recreate them).

### Ignoring a photo

There's no CLI command for this yet — hand-edit `tracking.csv` (a plain CSV, safe to open in
any spreadsheet app or text editor):

1. Find the row for the photo (by `original_filename`, or `photo_uuid` if you know it).
2. Set its `status` column to `ignored`. Optionally fill in `ignore_reason`.
3. If the row doesn't exist yet (you haven't run the tool since seeing this photo), add one —
   at minimum `photo_uuid` and `component` (`single` for a normal photo/video) and `status`.

Future runs will skip it permanently, without touching the source library. For a Live Photo,
marking *either* of its two rows (`key_image` or `live_bundle`) ignored is enough — the tool
automatically treats the whole Live Photo as ignored and marks the other row to match.

## Utilities

Standalone tools that operate on staged output, under [`scripts/`](scripts):

- [`orientation_correction`](scripts/orientation_correction/README.md) — detects and corrects
  sideways/upside-down photos in a staged directory.
- [`image_quality_detector`](scripts/image_quality_detector/README.md) — finds totally
  overexposed, totally underexposed, and extremely blurry photos in a staged directory and
  quarantines them for review.

## Development

```sh
python3.14 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

```sh
pytest                                          # run tests
PHOTOS_TEST_LIBRARY="/path/to/Your Library.photoslibrary" pytest   # also run the integration
                                                                    # tests against a real library
ruff check .             # lint
ruff format .            # format
```
