# Chunk 7 — Backup pCloud (tar hebdo écrasé)

> Snapshot hebdomadaire des 3 buckets MinIO vers pCloud.
> 1 tarball complet écrasé chaque dimanche. Pas de versioning.
> Pré-requis : chunk 1 livré.

## Objectif

À la fin du chunk :

- Tous les dimanches à 03:00 UTC, le VPS produit `eurio-minio.tar` qui contient les 3 buckets MinIO et le pousse vers pCloud, **écrasant** le tar de la semaine précédente.
- En cas d'échec, alerte ntfy.sh.
- Test de restauration documenté (manuel, mensuel).

Décision (vision §"Décisions actées" #7) : **pas de rétention multi-semaine**, pas de snapshots datés. Une seule archive vivante. La data sur S3 ne contient pas d'user data ; le risque de découvrir une corruption 4 semaines après est faible vs la simplicité opérationnelle gagnée.

## Pré-requis

- Chunk 1 livré (MinIO opérationnel, dockerisé).
- Compte pCloud actif, `rclone config` fait sur le VPS.
- Disque VPS avec ~50 GB libres temporairement (création du tar local avant push).

## Décisions actées

1. **1 tarball complet** (les 3 buckets ensemble), pas par-bucket. Restauration trivialement complète.
2. **Écrasement** : `pcloud:eurio-backup/eurio-minio.tar` est overwrite chaque semaine. Pas de timestamp dans le nom.
3. **Encryption** : pas en V1. Si jamais sensible plus tard, ajouter `crypt:` rclone.
4. **Alerte** : ntfy.sh sur succès et échec.

## Implémentation

### 7.1 Script `/etc/eurio/backup.sh`

```bash
#!/usr/bin/env bash
set -euo pipefail

DATE=$(date -u +%FT%TZ)
LOG=/var/log/eurio-backup.log
TAR=/var/tmp/eurio-minio.tar
NTFY_URL="https://ntfy.sh/${NTFY_TOPIC:?}"

notify() { curl -sf -d "$1" "$NTFY_URL" >/dev/null || true; }
trap 'notify "❌ Backup eurio FAILED $DATE"; exit 1' ERR

{
  echo "=== Backup start $DATE ==="

  # tar les 3 buckets MinIO directement depuis le filesystem du container
  # (le volume MinIO est /var/lib/eurio-minio/data)
  tar cf "$TAR" -C /var/lib/eurio-minio/data \
      numista-canonical enrichment-raws enrichment-crops

  ls -lh "$TAR"

  # Push vers pCloud, écrase le précédent
  rclone copyto "$TAR" "pcloud:eurio-backup/eurio-minio.tar" \
      --progress --stats=30s

  rm -f "$TAR"
  echo "=== Backup done $DATE ==="
  notify "✅ Backup eurio OK $DATE ($(rclone size pcloud:eurio-backup/eurio-minio.tar | grep -oP '[0-9.]+ [KMG]?B'))"
} >> "$LOG" 2>&1
```

**Pourquoi tar du filesystem MinIO directement** : MinIO stocke les objets de façon transparente sous `<data>/<bucket>/<key>`. Tar du data dir = backup fidèle, pas besoin d'API S3 pour itérer. Restauration = `tar xf` dans un dir, puis MinIO repointé dessus.

### 7.2 NixOS wiring

`/etc/nixos/eurio-backup.nix` :

```nix
{ pkgs, ... }: {
  systemd.services.eurio-backup = {
    description = "Backup MinIO to pCloud";
    serviceConfig = {
      Type = "oneshot";
      User = "root";   # tar du data dir nécessite root
      ExecStart = "/etc/eurio/backup.sh";
      EnvironmentFile = "/etc/eurio/backup.env";  # NTFY_TOPIC
    };
    path = [ pkgs.rclone pkgs.curl pkgs.gnutar ];
  };

  systemd.timers.eurio-backup = {
    description = "Weekly backup MinIO → pCloud";
    wantedBy = [ "timers.target" ];
    timerConfig = {
      OnCalendar = "Sun 03:00 UTC";
      Persistent = true;
    };
  };
}
```

`Persistent = true` rejoue si VPS down au moment prévu.

### 7.3 Test de restauration (manuel, mensuel)

```bash
# 1. Download le tar depuis pCloud
mkdir -p /tmp/eurio-restore-test
rclone copy pcloud:eurio-backup/eurio-minio.tar /tmp/eurio-restore-test/

# 2. Extract dans un dir temporaire
tar xf /tmp/eurio-restore-test/eurio-minio.tar -C /tmp/eurio-restore-test/extracted/

# 3. Sanity check
du -sh /tmp/eurio-restore-test/extracted/*
# Doit lister les 3 buckets avec une taille cohérente

# 4. Vérifier qu'un objet random est lisible
file /tmp/eurio-restore-test/extracted/numista-canonical/numista/*/obverse.jpg | head
```

Si jamais ça échoue → on sait avant le désastre.

### 7.4 Procédure de restore en désastre

Si le VPS perd MinIO :

1. Réinstaller MinIO docker (chunk 1).
2. Stopper le container : `docker compose -f /etc/eurio/minio/docker-compose.yml down`.
3. Vider `/var/lib/eurio-minio/data/`.
4. `tar xf eurio-minio.tar -C /var/lib/eurio-minio/data/`.
5. Restart : `docker compose up -d`.
6. Vérifier `mc ls`.

## Critères d'acceptation

- [ ] Premier run manuel termine sans erreur (peut prendre 1-2h pour ~50 GB)
- [ ] `rclone ls pcloud:eurio-backup/` montre `eurio-minio.tar` avec date récente
- [ ] systemd.timer actif, `systemctl list-timers` affiche prochaine exécution dimanche
- [ ] Notification ntfy.sh reçue à la fin
- [ ] Test de restauration : tar extractable, objets lisibles

## Gotchas

- **Disque VPS pour tar intermédiaire** : si les 3 buckets pèsent 50 GB, le tar pèse pareil → 50 GB libres requis. Surveiller `df -h /var/tmp`. Si saturation : pipe direct `tar cf - ... | rclone rcat ...` (pas de fichier intermédiaire).
- **Token pCloud rotation** : se révoque parfois. Regen tous les ~6 mois ou utiliser un token long-lived.
- **Atomicité** : un upload MinIO concurrent au tar produit un fichier potentiellement partiel dans le backup. Acceptable (la semaine suivante rattrape, et un upload partiel d'un .png se voit immédiatement).
- **Egress pCloud** : pCloud Premium a un download cap (~500 GB/mois). Si on doit restorer, vérifier avant.
- **Container MinIO running pendant tar** : OK, MinIO n'a pas de fichier `.lock` exclusif sur les objets. Lecture concurrente safe.

## Anti-objectifs

- ❌ Pas de backup quotidien. Hebdo suffit.
- ❌ Pas de rétention multi-semaine, pas de snapshots datés. 1 archive vivante.
- ❌ Pas de "real-time replication". Trop coûteux, pas le bon problème.
- ❌ Pas de backup secondaire (autre cloud). Une destination V1.
- ❌ Pas d'encryption V1 (data non sensible).
- ❌ Pas de tar par-bucket. Une archive globale.
