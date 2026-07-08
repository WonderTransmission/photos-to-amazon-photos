# photos-to-amazon-photos

Idempotent staging tool that pulls photos out of a local macOS **Photos** library and copies
the best available version of each into a plain, date-organized directory tree — with original
metadata (EXIF, GPS, capture date, etc.) intact — ready to upload to **Amazon Photos**.

This project follows a spec-driven workflow. Each phase's document lives under [`docs/`](docs):

1. [Requirements](docs/requirements.md) — what the tool must do and why.
2. [Design](docs/design.md) — how it will do it.
3. [Tasks](docs/tasks.md) — the implementation breakdown. **(current phase)**

No implementation exists yet; this repo currently contains planning documents only.

## Status

Planning complete, implementation not yet started. See [`docs/tasks.md`](docs/tasks.md) for the
ordered task list (starting with a compatibility/validation spike), [`docs/design.md`](docs/design.md)
for the design those tasks implement, and [`docs/requirements.md`](docs/requirements.md) for the
underlying spec.
