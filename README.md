# photos-to-amazon-photos

Idempotent staging tool that pulls photos out of a local macOS **Photos** library and copies
the best available version of each into a plain, date-organized directory tree — with original
metadata (EXIF, GPS, capture date, etc.) intact — ready to upload to **Amazon Photos**.

This project follows a spec-driven workflow. Each phase's document lives under [`docs/`](docs):

1. [Requirements](docs/requirements.md) — what the tool must do and why.
2. [Design](docs/design.md) — how it will do it. **(current phase)**
3. Tasks — the implementation breakdown. *(not yet written)*

No implementation exists yet; this repo currently contains planning documents only.

## Status

Draft / planning. See [`docs/design.md`](docs/design.md) for the current design and its
remaining open items, and [`docs/requirements.md`](docs/requirements.md) for the underlying
spec.
