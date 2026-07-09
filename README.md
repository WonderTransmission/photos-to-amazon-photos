# photos-to-amazon-photos

Idempotent staging tool that pulls photos, videos, and Live Photos out of a local macOS
**Photos** library and copies the best available version of each into a plain, date-organized
directory tree — with original metadata (EXIF, GPS, capture date, etc.) intact — ready to
upload: still photos to **Amazon Photos**, video to **S3/Glacier**.

This project follows a spec-driven workflow. Each phase's document lives under [`docs/`](docs):

1. [Requirements](docs/requirements.md) — what the tool must do and why.
2. [Design](docs/design.md) — how it will do it.
3. [Tasks](docs/tasks.md) — the implementation breakdown, tracked against the design above.

## Status

Planning is complete and validated against real target libraries (see `docs/tasks.md`
Milestone 0). Implementation is underway — see `docs/tasks.md` for progress against the
milestone/task breakdown.

## Development

Requires Python 3.14+.

```sh
python3.14 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

```sh
pytest                  # run tests
ruff check .             # lint
ruff format .            # format
```

Once installed, the CLI is available as:

```sh
photos-to-amazon-photos --help
```
