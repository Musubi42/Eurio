# NixOS module — Eurio VPS services (MinIO + weekly pCloud backup chiffré).
#
# Imported from /etc/nixos/configuration.nix via absolute path :
#
#     imports = [ /opt/eurio/nix/eurio-vps.nix ];
#
# Conditioned on `config.networking.hostName == "nixos"` so importing this
# on another host is a no-op (override via `eurio.vps.enable = true;`).
#
# Services installés :
#
#   eurio-minio.service       oneshot wrapper around `docker compose up -d`
#   eurio-backup.service      ./infra/backup/eurio-backup.sh run (rclone crypt)
#   eurio-backup.timer        weekly trigger (default: Sun 03:00 UTC)
#
# Le backup utilise `rclone crypt` avec une clé Age dédiée à
# `~/.config/eurio-backup/age-key.txt` (mode 400, jamais dans le store).
# Voir infra/backup/README.md.
#
# Le module reste dormant tant qu'il n'est pas importé.

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
        actual VPS) and false elsewhere.
      '';
    };

    repoRoot = lib.mkOption {
      type = lib.types.path;
      default = repoRoot;
      description = "Absolute path to the Eurio repo on this host.";
    };

    backup = {
      enable = lib.mkOption {
        type = lib.types.bool;
        default = true;
        description = "Activer le timer hebdomadaire de backup pCloud.";
      };

      user = lib.mkOption {
        type = lib.types.str;
        default = "dontpanic";
        description = ''
          Utilisateur qui exécute le backup. Doit avoir :
          - ~/.config/eurio-backup/age-key.txt (mode 400)
          - ~/.config/rclone/rclone.conf avec [pcloud], [pcloud_crypt], [minio]
          Pas besoin d'accès au volume MinIO : on lit via l'API S3.
        '';
      };

      onCalendar = lib.mkOption {
        type = lib.types.str;
        default = "Sun 03:00 UTC";
        description = "systemd OnCalendar pour le backup hebdomadaire.";
      };
    };
  };

  config = lib.mkIf cfg.enable {

    # ── Pre-reqs ──────────────────────────────────────────────────────────
    virtualisation.docker.enable = lib.mkDefault true;

    # Outils utilisés par le module et l'usage ad-hoc.
    environment.systemPackages = with pkgs; [
      docker
      docker-compose
      rclone
      age
      curl
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
    # Le service appelle `eurio-backup.sh run` depuis le repo. Le script
    # lit la clé Age dans le HOME de l'utilisateur configuré, configure
    # les env vars rclone et exec rclone copy pour chaque bucket.
    systemd.services.eurio-backup = lib.mkIf cfg.backup.enable {
      description = "Backup MinIO → pCloud chiffré (rclone crypt + Age)";
      after = [ "eurio-minio.service" "network-online.target" ];
      wants = [ "network-online.target" ];
      requires = [ "eurio-minio.service" ];
      path = [ pkgs.rclone pkgs.age pkgs.coreutils pkgs.gawk pkgs.gnused pkgs.gnugrep pkgs.bash ];

      serviceConfig = {
        Type = "oneshot";
        User = cfg.backup.user;
        WorkingDirectory = cfg.repoRoot;
        ExecStart = "${cfg.repoRoot}/infra/backup/eurio-backup.sh run";
        StandardOutput = "journal";
        StandardError = "journal";
      };
    };

    systemd.timers.eurio-backup = lib.mkIf cfg.backup.enable {
      description = "Trigger hebdomadaire du backup pCloud d'Eurio";
      wantedBy = [ "timers.target" ];
      timerConfig = {
        OnCalendar = cfg.backup.onCalendar;
        Persistent = true;  # rejoue si le VPS était down au moment prévu
      };
    };
  };
}
