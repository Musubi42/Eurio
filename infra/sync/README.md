# `infra/sync/` — Mac dev → VPS one-shot transfer

Before the `migrate_to_minio` script can hash + upload images, the
images must physically be on the same machine that runs the script
(this VPS). If you've been scraping on your Mac, this directory holds
the rsync runbook.

## When you run this

**Once**, before `migrate_to_minio inventory` (chunk 3 of the
harmonisation plan). After that, all new scrapes go directly to MinIO
via the updated pipeline (`download.py` / `detect_crop.py` write to S3
through the same `local_path()` lib used for reads).

## How

From your **Mac** (not the VPS):

```bash
# 1. Edit the SSH alias / repo paths in the script (top of the file)
$EDITOR ~/dev/eurio/infra/sync/rsync-from-mac.sh

# 2. Dry-run (default)
~/dev/eurio/infra/sync/rsync-from-mac.sh

# 3. Apply
~/dev/eurio/infra/sync/rsync-from-mac.sh --apply

# 4. Optional: mirror (delete VPS-side files absent on Mac)
~/dev/eurio/infra/sync/rsync-from-mac.sh --apply --delete
```

The script transfers:

- `ml/datasets/` — canonical Numista images
- `ml/state/sources/` — scraped raws + crops (the bulk of the data)

It **deliberately skips**:

- `ml/cache/` — augmentations, transient by design (vision §P5)
- `ml/state/training.db*` — per-machine, conflicting writes if shared
- `ml/state/sources_runs.json` — per-machine state (sources-refacto D-06)

## After rsync

On the VPS:

```bash
cd /opt/eurio/ml
../.venv/bin/python -m scripts.migrate_to_minio inventory
../.venv/bin/python -m scripts.migrate_to_minio upload
../.venv/bin/python -m scripts.migrate_to_minio db
../.venv/bin/python -m scripts.migrate_to_minio verify --sample-pct 10
```

(or via go-task `ml:migrate-{inventory,upload,db,verify}`).

Once verified, lock the local fs as a safety net:

```bash
go-task ml:migrate-lock-fs
```

After 7 days of stable operation, `chunk-8-cleanup-rollback.md` can
remove the local copy entirely.

## Why rsync and not just upload-from-Mac

Two reasons:

1. The VPS already has a fast public link to MinIO (same network), so
   uploading from the VPS to MinIO is much faster than uploading
   directly from the Mac through Cloudflare.
2. Hashing + DB rewrite need to run on the same machine that holds
   the SQLite DB. Splitting the script across machines would make
   the workflow brittle.

## Trade-off you accept

The transfer happens once. If you re-scrape on the Mac after this,
the files don't auto-sync. Either:

- re-run this script, or
- (better) point the Mac scraper at the VPS MinIO directly via the
  same `MINIO_ACCESS_KEY` / `MINIO_SECRET_KEY` env vars. The whole
  point of the harmonisation is that machine identity stops mattering.
