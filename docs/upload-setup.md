# Uploading to Amazon Photos

Amazon Photos has no public upload API (see [requirements.md Section 8](requirements.md#8-amazon-photos-upload-strategy)
for why this tool doesn't try to automate the upload itself). Instead, this tool's job ends at
producing a correct, deduplicated staging folder — the actual upload is handed off to the
official **Amazon Photos desktop app**'s built-in **Backup** feature, which watches a folder and
automatically uploads anything added to it.

This only applies to `<target_root>/photos/`. See [Section 10 of design.md](design.md#10-upload-handoff-strategy-per-target-subdirectory)
for the other two output directories:

| Directory | Destination |
|---|---|
| `photos/` | Amazon Photos — this page |
| `video/` | S3/Glacier — a separate process, not covered here or automated by this tool |
| `live_photo/` | Undecided — staged only, no automated handoff yet |

## One-time setup

1. Install the Amazon Photos desktop app (search "Amazon Photos" — it's available for macOS
   from Amazon) and sign in with your Amazon account.
2. Open the app's **Backup** tab.
3. Choose **Add a folder to backup** and select `<target_root>/photos/` (the exact path you
   passed as `target_root` when running this tool, plus `/photos`).
4. Set your preferred backup recurrence and file type filters. Since this tool only ever writes
   image files into `photos/`, the file-type filter doesn't need to exclude anything.

From this point on, the Backup feature watches that folder continuously (or on whatever
schedule you set) and uploads anything new in it — including future runs of this tool, as long
as they keep writing into the same `target_root/photos/`.

## Day-to-day workflow

1. Run `photos-to-amazon-photos` (see the [README](../README.md#usage)) to stage new photos.
2. Let the Amazon Photos desktop app pick them up and upload (automatic, per the schedule set
   above — or trigger it manually from the app if you don't want to wait).
3. Once you've confirmed a photo actually made it into Amazon Photos (check the web app or the
   desktop app's own upload status), it's safe to delete the local copy from `photos/`.
   `tracking.csv` remembers it as `copied` regardless of whether the file is still there, so
   future runs won't re-stage it — see the README's note on idempotency.

There's no need to keep `photos/` around as a permanent archive — its job is just to be a
staging area between this tool and the Amazon Photos Backup feature. Your originals stay safely
in the Photos library the whole time; this tool never modifies or deletes anything there.
