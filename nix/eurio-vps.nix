# NixOS module — ordonnancement du staging de sauvegarde Eurio.
#
# ⚠️ NE PAS importer par chemin absolu. Le système du VPS est construit par un
# flake, et un flake est hermétique :
#
#     imports = [ /opt/eurio/nix/eurio-vps.nix ];
#     → error: access to absolute path '/opt/eurio/nix/eurio-vps.nix'
#              is forbidden in pure evaluation mode
#
# Import correct, dans /etc/nixos/flake.nix :
#
#     inputs.eurio-nix = { url = "path:/opt/eurio/nix"; flake = false; };
#     outputs = inputs@{ ..., eurio-nix, ... }:
#       modules = [ ... "${eurio-nix}/eurio-vps.nix" ];
#
# On cible `/opt/eurio/nix` et non la racine du dépôt : seuls ces quelques Ko
# sont copiés dans le store, là où la racine pèse plusieurs Go (staging inclus).
# Après toute modification de ce fichier : `nix flake update eurio-nix` puis
# `nixos-rebuild switch`.
#
# Conditionné sur `config.networking.hostName == "nixos"` : l'importer sur un
# autre hôte est un no-op (forçable via `eurio.vps.enable = true;`).
#
# Services installés :
#
#   eurio-backup-stage.service   `eurio-backup.sh stage`   — 02:00 UTC
#   eurio-backup-verify.service  `eurio-backup.sh verify`  — 02:30 UTC
#
# Pourquoi un service NixOS déclaratif plutôt qu'un cron : il survit à une
# réinstallation, et il est versionné avec le code qu'il lance. C'est la
# réponse directe au constat du 2026-08-14 — le dispositif précédent existait,
# fonctionnait, et n'avait simplement jamais été branché.
#
# Pourquoi 02:00 / 02:30 : les jobs Duplicati démarrent à 03:00 UTC. Le staging
# doit être terminé et vérifié AVANT que Duplicati ne le ramasse.
#
# Ce module ne parle pas au distant. Duplicati est le moteur unique : transport,
# chiffrement, rétention, historique. Voir
# docs/work-in-progress/backup-pipeline/ARCHITECTURE.md §4.
#
# ⚠️ Ce module ne gère PAS MinIO. Une version antérieure définissait un
# `eurio-minio.service` dont l'`ExecStop` faisait `docker compose down` : tout
# `systemctl stop`, toute désactivation future du module aurait coupé MinIO —
# et avec lui eurio-api, eurio-review et le miroir. MinIO tourne très bien sans
# systemd ; on ne lui ajoute pas un interrupteur qu'on n'a pas demandé.
#
# Le module reste dormant tant qu'il n'est pas importé.

{ config, lib, pkgs, ... }:

let
  cfg = config.eurio.vps;
  script = "${cfg.repoRoot}/infra/backup/eurio-backup.sh";

  # Les deux unités partagent leur environnement : même utilisateur, mêmes
  # outils, même répertoire. Seule la commande change.
  commonService = {
    after = [ "docker.service" "network-online.target" ];
    wants = [ "network-online.target" ];
    # `curl` porte les quatre anneaux de notification. Son absence de cette
    # liste rendait TOUTE alerte muette en exécution automatique (2026-08-16) :
    # les URLs répondaient 200 depuis un shell, « INJOIGNABLE » sous systemd.
    path = with pkgs; [ docker python3 rclone curl coreutils util-linux gawk gnused gnugrep bash nix ];
    serviceConfig = {
      Type = "oneshot";
      User = cfg.user;
      WorkingDirectory = cfg.repoRoot;
      StandardOutput = "journal";
      StandardError = "journal";
    };
  };
in
{
  options.eurio.vps = {
    enable = lib.mkOption {
      type = lib.types.bool;
      default = config.networking.hostName == "nixos";
      description = ''
        Activer l'ordonnancement du staging de sauvegarde Eurio.
        Vrai par défaut sur l'hôte dont le hostname est "nixos" (le VPS).
      '';
    };

    repoRoot = lib.mkOption {
      type = lib.types.path;
      default = "/opt/eurio";
      description = "Chemin absolu du dépôt Eurio sur cet hôte.";
    };

    user = lib.mkOption {
      type = lib.types.str;
      default = "dontpanic";
      description = ''
        Utilisateur qui produit le staging. Doit pouvoir :
        - parler au démon Docker (snapshot des bases par `docker exec`) ;
        - lire ~/.config/rclone/rclone.conf (remote `minio` pour le miroir) ;
        - écrire dans ''${repoRoot}/infra/backup/staging/.
      '';
    };

    stageOnCalendar = lib.mkOption {
      type = lib.types.str;
      default = "*-*-* 02:00:00 UTC";
      description = "Quand produire le staging. Doit précéder Duplicati (03:00 UTC).";
    };

    verifyOnCalendar = lib.mkOption {
      type = lib.types.str;
      default = "*-*-* 02:30:00 UTC";
      description = "Quand vérifier les invariants. Entre le staging et Duplicati.";
    };

    drillOnCalendar = lib.mkOption {
      type = lib.types.str;
      default = "*-01,04,07,10-05 04:00:00 UTC";
      description = ''
        Quand rejouer l'exercice de restauration complet. Trimestriel par
        défaut (5 janvier / avril / juillet / octobre), après la fenêtre de
        sauvegarde : l'exercice tape la même destination pCloud et n'a aucune
        raison de courir contre le job Duplicati de 03:00.
      '';
    };
  };

  config = lib.mkIf cfg.enable {

    # `mkDefault` : on déclare une dépendance, on n'impose rien à un hôte qui
    # aurait déjà sa propre configuration Docker.
    virtualisation.docker.enable = lib.mkDefault true;

    environment.systemPackages = with pkgs; [ rclone ];

    # ── Production du staging ─────────────────────────────────────────────
    systemd.services.eurio-backup-stage = commonService // {
      description = "Eurio — production du staging de sauvegarde";
      serviceConfig = commonService.serviceConfig // {
        ExecStart = "${script} stage";
        # Le miroir MinIO du premier run prend ~13 min ; les suivants ~2 min.
        # La borne protège la fenêtre avant Duplicati sans être serrée.
        TimeoutStartSec = "45min";
      };
    };

    systemd.timers.eurio-backup-stage = {
      description = "Déclencheur quotidien du staging Eurio";
      wantedBy = [ "timers.target" ];
      timerConfig = {
        OnCalendar = cfg.stageOnCalendar;
        # Rejoue si la machine était éteinte à l'heure prévue. Un staging en
        # retard vaut mieux qu'un staging sauté — et l'invariant de fraîcheur
        # signalera de toute façon un staging trop vieux.
        Persistent = true;
      };
    };

    # ── Vérification des invariants ───────────────────────────────────────
    # Unité SÉPARÉE, et pas un `ExecStartPost` du staging : les deux échouent
    # pour des raisons différentes et appellent des actions différentes.
    # « Le staging n'a pas tourné » est un problème d'infrastructure ;
    # « verify est rouge » est un problème de données. Les confondre dans une
    # seule unité rendrait l'alerting du lot 5 incapable de les distinguer.
    systemd.services.eurio-backup-verify = commonService // {
      description = "Eurio — vérification des invariants du staging";
      after = commonService.after ++ [ "eurio-backup-stage.service" ];
      serviceConfig = commonService.serviceConfig // {
        ExecStart = "${script} verify";
        TimeoutStartSec = "20min";
      };
    };

    systemd.timers.eurio-backup-verify = {
      description = "Déclencheur quotidien de la vérification Eurio";
      wantedBy = [ "timers.target" ];
      timerConfig = {
        OnCalendar = cfg.verifyOnCalendar;
        Persistent = true;
      };
    };

    # ── Exercice de restauration ──────────────────────────────────────────
    # Les deux unités ci-dessus vérifient que la sauvegarde est CRÉDIBLE.
    # Celle-ci vérifie qu'elle est RESTAURABLE — ce n'est pas la même question,
    # et seule la seconde répond à « le VPS est perdu, est-ce que je récupère
    # Eurio ? ». Elle clone le dépôt, reconstruit les images, rapatrie depuis
    # pCloud, remonte une stack isolée et lui demande de servir la donnée.
    #
    # Pourquoi l'ordonnancer plutôt que le laisser en rituel humain : la case
    # « Monthly DR Test » de /opt/stacks/oim-duplicati/BACKUP_STRATEGY.md n'a
    # jamais été cochée depuis novembre 2025. Un rituel trimestriel non
    # ordonnancé ne se fait pas — c'est la pathologie même de ce chantier.
    #
    # Elle a besoin de plus que les deux autres : `git` et `openssh` pour
    # cloner Codeberg, `sops`/`age` pour les secrets du clone, `nix` pour le
    # duplicati-cli du jour J, `docker` pour construire et remonter.
    systemd.services.eurio-backup-drill = commonService // {
      description = "Eurio — exercice de restauration complet (trimestriel)";
      path = commonService.path ++ (with pkgs; [ git openssh sops age docker-compose ]);
      serviceConfig = commonService.serviceConfig // {
        ExecStart = "${cfg.repoRoot}/infra/backup/drill/run-drill.sh all";
        # Mesuré le 2026-08-19 : 28 min de bout en bout (index 11 min,
        # restauration 10 min, le reste local). La borne laisse la marge d'un
        # pCloud lent sans laisser un exercice bloqué occuper le disque.
        TimeoutStartSec = "3h";
      };
    };

    systemd.timers.eurio-backup-drill = {
      description = "Déclencheur trimestriel de l'exercice de restauration Eurio";
      wantedBy = [ "timers.target" ];
      timerConfig = {
        OnCalendar = cfg.drillOnCalendar;
        Persistent = true;
        # Le seul timer des trois qui a besoin d'être dispersé : il tire un
        # jour fixe à heure fixe, et rien d'autre ne dépend de son instant.
        RandomizedDelaySec = "30min";
      };
    };
  };
}
