# `nix/` — NixOS modules shipped with this repo

These modules can be imported from a host's `/etc/nixos/configuration.nix`
to set up systemd units that this project depends on.

## `eurio-vps.nix`

Defines two services:

- `eurio-minio.service` — wraps the docker compose at `infra/minio/`
- `eurio-backup.service` + `.timer` — weekly tarball push to pCloud

### How to enable on the VPS

In `/etc/nixos/configuration.nix`:

```nix
{ ... }: {
  imports = [ /opt/eurio/nix/eurio-vps.nix ];

  # Optional: override the defaults
  # eurio.vps.backup.onCalendar = "Sun 04:00 UTC";
}
```

Then:

```bash
sudo nixos-rebuild switch
sudo systemctl status eurio-minio eurio-backup.timer
```

### Default activation

The module auto-activates on hosts whose `networking.hostName` equals
`"nixos"`. On other hosts, importing the module is a no-op unless you
explicitly set `eurio.vps.enable = true;`. This protects you from
accidentally booting MinIO on a laptop that happens to import the
module.

### Pre-reqs the module assumes

- `virtualisation.docker.enable = true;` (the module sets this default)
- A running Traefik with the `traefik` external Docker network
- DNS records for `eurio-s3.musubi.dev` + `eurio-images.musubi.dev`
- `/etc/eurio/backup.env` with at least `NTFY_TOPIC=…` (mode 0600)
- `/root/.config/rclone/rclone.conf` configured for the `pcloud` remote

The first three are pre-existing on the VPS. The last two need a
one-time manual setup, see `infra/backup/README.md`.

### Why a NixOS module instead of a plain `systemd` unit file

Two reasons:

1. **Trace-ability** — the module lives next to the rest of the project
   in this repo. If you ever wonder "what installed `eurio-minio.service`?"
   the answer is `git log nix/eurio-vps.nix`.
2. **Reproducibility** — you can re-create the VPS from scratch by
   cloning the repo and pointing your config at this file. No hidden
   state in `/etc/nixos/`.
