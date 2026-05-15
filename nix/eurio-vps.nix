# NixOS module — Eurio VPS services (MinIO + weekly pCloud backup).
#
# Imported from /etc/nixos/configuration.nix via absolute path:
#
#     imports = [ /opt/eurio/nix/eurio-vps.nix ];
#
# Conditioned on `config.networking.hostName == "nixos"` so importing
# this on another host is a no-op (you can override by setting
# `eurio.vps.enable = true;` explicitly in your configuration).
#
# The two services this module installs:
#
#   eurio-minio.service       oneshot wrapper around `docker compose up -d`
#   eurio-backup.service      tar + rclone push to pCloud
#   eurio-backup.timer        weekly trigger (Sun 03:00 UTC)
#
# Spec: docs/harmonisation-images/chunk-{1,7}-*.md

{ config, lib, pkgs, ... }:

let
  cfg = config.eurio.vps;
  repoRoot = "/opt/eurio";
in
{
  options.eurio.vps = {
    enable = lib.mkOption {
      type = lib.types.bool;
      default = config.networking.hostName == "nixos";
      description = ''
        Whether to enable the Eurio VPS services (MinIO + backup).
        Defaults to true on the host whose hostname is "nixos" (the
        actual VPS) and false elsewhere — so importing this module
        on a non-VPS NixOS host is a no-op.
      '';
    };

    repoRoot = lib.mkOption {
      type = lib.types.path;
      default = repoRoot;
      description = "Absolute path to the Eurio repo on this host.";
    };

    backup = {
      onCalendar = lib.mkOption {
        type = lib.types.str;
        default = "Sun 03:00 UTC";
        description = "systemd OnCalendar expression for the weekly backup.";
      };

      envFile = lib.mkOption {
        type = lib.types.path;
        default = /etc/eurio/backup.env;
        description = ''
          EnvironmentFile loaded by the backup service.
          Must define NTFY_TOPIC at minimum. Mode 0600.
        '';
      };
    };
  };

  config = lib.mkIf cfg.enable {

    # ── Pre-reqs ──────────────────────────────────────────────────────────
    # Docker (the compose plugin ships with the docker package).
    virtualisation.docker.enable = lib.mkDefault true;

    # Tools used by the systemd units (kept inside the unit's `path` so we
    # don't pollute the global system PATH unnecessarily, but listed here
    # also for ease of ad-hoc shells).
    environment.systemPackages = with pkgs; [
      docker
      docker-compose   # only the plugin is needed but the binary is handy
      rclone
      curl
      gnutar
    ];

    # ── eurio-minio.service ───────────────────────────────────────────────
    systemd.services.eurio-minio = {
      description = "Eurio MinIO (docker compose at ${cfg.repoRoot}/infra/minio)";
      after = [ "docker.service" "network-online.target" ];
      wants = [ "docker.service" "network-online.target" ];
      wantedBy = [ "multi-user.target" ];
      path = [ pkgs.docker pkgs.docker-compose ];

      serviceConfig = {
        Type = "oneshot";
        RemainAfterExit = true;
        WorkingDirectory = "${cfg.repoRoot}/infra/minio";
        ExecStart  = "${pkgs.docker}/bin/docker compose -f ${cfg.repoRoot}/infra/minio/docker-compose.yml up -d";
        ExecStop   = "${pkgs.docker}/bin/docker compose -f ${cfg.repoRoot}/infra/minio/docker-compose.yml down";
        ExecReload = "${pkgs.docker}/bin/docker compose -f ${cfg.repoRoot}/infra/minio/docker-compose.yml up -d --force-recreate";
      };
    };

    # ── eurio-backup.service + timer ──────────────────────────────────────
    systemd.services.eurio-backup = {
      description = "Tar MinIO buckets + push to pCloud";
      after = [ "eurio-minio.service" "network-online.target" ];
      wants = [ "network-online.target" ];
      requires = [ "eurio-minio.service" ];
      path = [ pkgs.rclone pkgs.curl pkgs.gnutar pkgs.coreutils pkgs.gawk ];

      serviceConfig = {
        Type = "oneshot";
        User = "root";   # tar of the MinIO data dir (root-owned files)
        EnvironmentFile = cfg.backup.envFile;
        ExecStart = "${cfg.repoRoot}/infra/backup/backup-minio-to-pcloud.sh";
      };
    };

    systemd.timers.eurio-backup = {
      description = "Weekly backup of Eurio MinIO to pCloud";
      wantedBy = [ "timers.target" ];
      timerConfig = {
        OnCalendar = cfg.backup.onCalendar;
        Persistent = true;   # rejoue si VPS down au moment prévu
      };
    };

    # ── Log rotation (the backup script appends to /var/log/eurio-backup.log) ─
    services.logrotate.settings."eurio-backup" = {
      files = [ "/var/log/eurio-backup.log" ];
      frequency = "monthly";
      rotate = 3;
      compress = true;
      missingok = true;
      notifempty = true;
    };
  };
}
