# `infra/minio/` — MinIO dev chain (S3-compatible storage)

> Source of truth for the dev image chain (Numista canonical, scraped
> raws, normalised crops). Replaces the per-machine filesystem layout
> documented in `docs/harmonisation-images/vision.md`.

## Layout

```
infra/minio/
├── data/                    ← mounted as /data in the container (gitignored)
│   ├── numista-canonical/   ← public Numista referential
│   ├── enrichment-raws/     ← raw scraped photos
│   └── enrichment-crops/    ← normalised crops (training input)
├── secrets/                 ← credentials, files only, mode 0600 (gitignored)
│   ├── minio_root_user
│   ├── minio_root_password
│   ├── eurio_app_user
│   └── eurio_app_password
├── policies/
│   └── eurio-app-policy.json   ← R/W on the 3 buckets, no admin
├── docker-compose.yml          ← MinIO + Traefik labels
├── bootstrap.sh                ← idempotent setup (run once, safe to re-run)
└── README.md                   ← this file
```

## First-time setup

Pre-reqs on the host:

- Docker + `docker compose` plugin
- A running Traefik container exposing the `traefik` external Docker network
  (this repo aligns with the existing `letsencryptresolver` cert resolver)
- DNS records `eurio-s3.musubi.dev` and `eurio-images.musubi.dev` pointed
  at this VPS (via Cloudflare; proxy ON)

Then:

```bash
cd /opt/eurio
./infra/minio/bootstrap.sh
```

The script prints the `eurio-app` credentials at the end. Copy them into
your `.envrc`:

```bash
# .envrc (gitignored)
export MINIO_ENDPOINT=https://eurio-s3.musubi.dev
export MINIO_ACCESS_KEY=eurio-app
export MINIO_SECRET_KEY=<long random string>
```

## Smoke tests

After bootstrap, from any machine with `mc` installed:

```bash
mc alias set eurio https://eurio-s3.musubi.dev "$MINIO_ACCESS_KEY" "$MINIO_SECRET_KEY"

# 1. List buckets
mc ls eurio/
# numista-canonical/  enrichment-raws/  enrichment-crops/

# 2. Public read (anonymous) on numista-canonical via the CDN host
echo hello-world > /tmp/t.txt
mc cp /tmp/t.txt eurio/numista-canonical/_smoke.txt
curl -sf https://eurio-images.musubi.dev/_smoke.txt    # → hello-world
mc rm eurio/numista-canonical/_smoke.txt

# 3. Private bucket rejects anonymous
mc cp /tmp/t.txt eurio/enrichment-crops/_smoke.txt
curl -I https://eurio-s3.musubi.dev/enrichment-crops/_smoke.txt   # → 403
mc rm eurio/enrichment-crops/_smoke.txt

# 4. Multipart upload works through Traefik
dd if=/dev/urandom of=/tmp/big.bin bs=1M count=100
mc cp /tmp/big.bin eurio/enrichment-crops/big.bin
mc ls eurio/enrichment-crops/big.bin    # → ~100 MiB
mc rm eurio/enrichment-crops/big.bin
rm /tmp/big.bin
```

## Operational notes

### Restart

```bash
cd /opt/eurio/infra/minio
docker compose restart
```

Or via the systemd unit (managed by `nix/eurio-vps.nix`):

```bash
sudo systemctl restart eurio-minio
```

### Logs

```bash
docker logs -f eurio-minio
```

### Console (admin GUI)

The MinIO console listens on `:9001` inside the container but is **not
exposed publicly** (no Traefik route). Tunnel locally if needed:

```bash
ssh -L 9001:127.0.0.1:9001 vps
# then open http://localhost:9001 in your browser
```

Login with `minio_root_user` / `minio_root_password` from `secrets/`.

### Restore from pCloud

```bash
# 1. Stop MinIO
sudo systemctl stop eurio-minio

# 2. Pull the latest backup
rclone copy pcloud:eurio-backup/eurio-minio.tar /tmp/

# 3. Wipe the existing data dir (after taking a side copy if doubt)
sudo rm -rf /opt/eurio/infra/minio/data/*

# 4. Extract
sudo tar -xf /tmp/eurio-minio.tar -C /opt/eurio/infra/minio/data/

# 5. Restart
sudo systemctl start eurio-minio
mc ls eurio/
```

## Why this lives in the repo (not /var/lib/)

The standard FHS location for MinIO data is `/var/lib/eurio-minio/`,
but we keep it under `/opt/eurio/infra/minio/data/` so that everything
about the project is observable from the repo root. The data is
git-ignored; only the `.do-not-delete` marker is committed to keep the
directory present after clone.

Trade-off: a careless `git clean -fdx` will preserve `data/` because
it's untracked-but-existing — git-clean only removes untracked files,
not the directory itself when it contains other untracked content.
However a manual `rm -rf infra/minio/data` will destroy MinIO. Treat
this directory like a database: backups are mandatory, see
`infra/backup/`.

## Anti-patterns

- ❌ Don't edit secrets manually after bootstrap — re-run `bootstrap.sh`
  with the existing files removed if you must rotate.
- ❌ Don't enable bucket versioning. The protection model is "weekly
  tarball + audit", not S3 native versioning.
- ❌ Don't expose port 9001 publicly via Traefik. Use SSH tunnel for
  the admin console.
- ❌ Don't store sensitive customer data here without encrypting first.
  V1 has no at-rest encryption.

## Related

- `docs/harmonisation-images/vision.md` — overall design
- `docs/harmonisation-images/chunk-1-minio-bootstrap.md` — original
  spec this dir implements
- `nix/eurio-vps.nix` — systemd service that manages this compose
- `infra/backup/` — weekly pCloud tarball
