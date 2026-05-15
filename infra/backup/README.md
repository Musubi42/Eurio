# `infra/backup/` — Weekly pCloud snapshot of MinIO

> Single tarball, overwritten every Sunday 03:00 UTC. No versioning, no
> multi-week retention. Spec: `docs/harmonisation-images/chunk-7-pcloud-backup.md`.

## What runs

A systemd unit + timer (defined in `nix/eurio-vps.nix`) calls
`backup-minio-to-pcloud.sh` every Sunday 03:00 UTC. The script:

1. Sanity-checks the 3 bucket dirs exist under `infra/minio/data/`.
2. Verifies enough free space in `/var/tmp` to stage the tarball.
3. `tar cf eurio-minio.tar numista-canonical enrichment-raws enrichment-crops`.
4. `rclone copyto … pcloud:eurio-backup/eurio-minio.tar` (overwrite).
5. Removes the local tarball.
6. Pings ntfy.sh on success / failure.

The script is idempotent and safe to re-run on demand:

```bash
sudo /opt/eurio/infra/backup/backup-minio-to-pcloud.sh
```

## One-time setup (VPS)

### 1. Install rclone (NixOS)

Already in nixpkgs:

```nix
environment.systemPackages = [ pkgs.rclone pkgs.curl pkgs.gnutar ];
```

(or rely on `path = [ pkgs.rclone pkgs.curl pkgs.gnutar ]` inside the
systemd unit, as `nix/eurio-vps.nix` does).

### 2. Configure pCloud auth

```bash
sudo rclone config
# n   (new remote)
# pcloud   (name)
# 27  (Pcloud)
# (defaults; OAuth flow will open a URL, follow it, paste back)
```

This writes `/root/.config/rclone/rclone.conf` with the OAuth token.
**Do NOT commit this file.** A redacted template is provided as
`rclone.conf.example`.

### 3. Configure ntfy topic + check timer

`/etc/eurio/backup.env` (created manually, mode 0600):

```ini
NTFY_TOPIC=eurio-backup-<random-suffix>
```

Subscribe with the ntfy mobile app (or `curl -s ntfy.sh/<topic>/json`)
to receive success / failure notifications.

```bash
sudo systemctl enable --now eurio-backup.timer
systemctl list-timers eurio-backup.timer
```

## Manual restore

See `infra/minio/README.md` §"Restore from pCloud".

## Test the backup *before* the disaster

Once a month (or after touching anything related):

```bash
mkdir -p /tmp/eurio-restore-test/extracted
rclone copy pcloud:eurio-backup/eurio-minio.tar /tmp/eurio-restore-test/
tar -xf /tmp/eurio-restore-test/eurio-minio.tar -C /tmp/eurio-restore-test/extracted/

# Sanity
du -sh /tmp/eurio-restore-test/extracted/*
file /tmp/eurio-restore-test/extracted/numista-canonical/numista/*/obverse.jpg | head

rm -rf /tmp/eurio-restore-test/
```

If this fails, you find out *before* you actually need the backup.

## Trade-offs (chosen on purpose)

- **Single archive, no retention** : if a corruption ships in a Sunday
  backup and stays unnoticed for 2 weeks, we lose old copies. Acceptable
  because (a) the data is dev assets, not user data; (b) corruption is
  visible at the next read; (c) the simplicity is worth more than rolling
  history.
- **Weekly cadence** : daily would mean ~4× the pCloud egress for little
  practical gain — scrape data accrues slowly.
- **No encryption** : V1 data is non-sensitive. If we add user data
  later, layer rclone `crypt:` over `pcloud:`.
- **No secondary destination** : V1. If pCloud goes down, we have a
  problem. Risk accepted in exchange for ops simplicity.
