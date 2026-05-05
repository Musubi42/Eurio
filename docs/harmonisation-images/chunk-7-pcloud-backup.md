# Chunk 7 — Backup pCloud (systemd.timer)

> Snapshot hebdomadaire des 3 buckets MinIO vers pCloud, avec rétention
> 4 semaines glissantes. Pré-requis : chunk 1 livré.

## Objectif

À la fin du chunk :
- Tous les dimanches à 03:00 UTC, le VPS pousse l'état complet de MinIO vers pCloud.
- 2 niveaux de backup : `latest/` (mirror synced) et `snapshots/<YYYY-MM-DD>/` (datés).
- Rétention auto : `snapshots/` plus vieux que 28 jours sont supprimés.
- En cas d'échec, alerte (email ou ntfy.sh).

## Pré-requis

- Chunk 1 livré (MinIO opérationnel).
- Compte pCloud actif avec credentials (`rclone config` configuré).
- Décision sur la nature du VPS : NixOS module-able ou Linux générique.

## Décisions à acter

1. **NixOS module vs systemd.timer user** :
   - Si VPS NixOS `nixos-rebuild`-managé → module Nix.
   - Sinon → service systemd "system-level" classique.
2. **Taux de rétention** : 4 snapshots hebdo (1 mois). Suffit pour rattraper une corruption qu'on n'aurait pas détectée pendant 3 semaines.
3. **Type de backup** :
   - Option A : `rclone sync` direct MinIO → pCloud (chaque image individuelle copiée). Lent à 100k fichiers.
   - Option B : tarball par bucket (`tar` puis upload). Rapide, mais restauration partielle = pénible.
   - **Reco** : Option A pour `latest/` (sync incrémental rapide après le premier). Option B (tarball) pour les snapshots datés (1 archive / dimanche, atomique, restore complet trivial).
4. **Alerte** : ntfy.sh (gratuit, simple POST HTTP). Email via mailgun aussi possible.

## Implémentation

### 7.1 Config rclone

Sur le VPS :

```bash
rclone config
# > minio
#   type: s3
#   provider: Minio
#   endpoint: http://localhost:9000
#   access_key_id: $ROOT_USER
#   secret_access_key: $ROOT_PWD
#
# > pcloud
#   type: pcloud
#   token: ...
```

Test :
```bash
rclone ls minio:numista-canonical | head
rclone ls pcloud:eurio-backup
```

### 7.2 Script de backup

```bash
#!/usr/bin/env bash
# /etc/eurio/backup.sh
set -euo pipefail

DATE=$(date +%F)
LOG=/var/log/eurio-backup/$DATE.log
mkdir -p $(dirname $LOG)

NTFY_URL="https://ntfy.sh/eurio-backup-secret-channel"

notify() {
  curl -s -d "$1" "$NTFY_URL" || true
}

trap 'notify "❌ Backup eurio FAILED $(date)"; exit 1' ERR

{
  echo "=== Backup start $DATE ==="

  # 1. latest/ — sync incrémental (rapide après la 1ère fois)
  for bucket in numista-canonical enrichment source-images; do
    rclone sync "minio:$bucket" "pcloud:eurio-backup/latest/$bucket" \
      --transfers=8 --checkers=16 --stats=1m
  done

  # 2. snapshots/<date> — tarball atomique par bucket
  for bucket in numista-canonical enrichment source-images; do
    rclone tarball "minio:$bucket" \
      "pcloud:eurio-backup/snapshots/$DATE/$bucket.tar" || \
    {
      # rclone tarball n'existe pas : workaround via local tar + upload
      TMPTAR=/tmp/$bucket-$DATE.tar
      rclone copy "minio:$bucket" /tmp/$bucket-$DATE/
      tar cf $TMPTAR -C /tmp/$bucket-$DATE/ .
      rclone copyto $TMPTAR "pcloud:eurio-backup/snapshots/$DATE/$bucket.tar"
      rm -rf /tmp/$bucket-$DATE/ $TMPTAR
    }
  done

  # 3. rétention : delete snapshots > 28 jours
  rclone delete "pcloud:eurio-backup/snapshots/" --min-age 28d

  echo "=== Backup done $DATE ==="
  notify "✅ Backup eurio OK $DATE"
} >> $LOG 2>&1
```

### 7.3 Wiring NixOS (si NixOS module)

```nix
# /etc/nixos/modules/eurio-backup.nix
{ config, pkgs, ... }: {
  systemd.services.eurio-backup = {
    description = "Backup MinIO buckets to pCloud";
    serviceConfig = {
      Type = "oneshot";
      User = "eurio";
      ExecStart = "/etc/eurio/backup.sh";
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

`Persistent = true` rejoue si le VPS était down au moment prévu.

### 7.4 Wiring systemd classique (si pas NixOS)

`/etc/systemd/system/eurio-backup.service` :
```ini
[Unit]
Description=Backup MinIO to pCloud

[Service]
Type=oneshot
User=eurio
ExecStart=/etc/eurio/backup.sh
```

`/etc/systemd/system/eurio-backup.timer` :
```ini
[Unit]
Description=Weekly backup

[Timer]
OnCalendar=Sun 03:00 UTC
Persistent=true

[Install]
WantedBy=timers.target
```

```bash
systemctl enable --now eurio-backup.timer
```

### 7.5 Test de restauration (mensuel)

Une fois par mois, test que le backup est restorable :

```bash
# Choisir un snapshot aléatoire
SNAP=$(rclone lsf pcloud:eurio-backup/snapshots/ | shuf -n 1)
mkdir -p /tmp/restore-test
rclone copy pcloud:eurio-backup/snapshots/$SNAP /tmp/restore-test/

# Vérif : tar tf et taille raisonnable
tar tf /tmp/restore-test/*.tar | head
du -sh /tmp/restore-test/
```

Si jamais ça échoue, on sait avant le désastre.

## Critères d'acceptation

- [ ] Premier run manuel du backup termine sans erreur (peut prendre plusieurs heures à la 1ère fois selon la taille).
- [ ] Snapshots `latest/` et `snapshots/<YYYY-MM-DD>/` présents en pCloud.
- [ ] systemd.timer actif et planifié hebdo.
- [ ] Notification ntfy.sh reçue à la fin.
- [ ] Test de restauration : on peut télécharger un snapshot et lire des fichiers dedans.

## Gotchas

- **Bandwidth pCloud** : la 1ère fois c'est tout le contenu (~50 GB+). Ensuite c'est incrémental sur `latest/` mais les snapshots tarballs sont chacun la totalité → coût bandwidth récurrent. Vérifier le quota pCloud (premium = 2 TB).
- **Token pCloud** : se révoque parfois. Renouveler tous les ~6 mois ou utiliser un token permanent (à demander à pCloud).
- **Atomicité** : si MinIO reçoit un upload pendant le backup, c'est OK — le sync incrémental rattrape la semaine suivante. Pas de lock global.
- **Disk space VPS pour tarballs intermédiaires** : si MinIO fait 50 GB, le tarball aussi. Vérifier que `/tmp` (ou le disque local) a la place. Sinon, mode "stream tar to rclone copyto" sans fichier intermédiaire.
- **Encryption** : le contenu MinIO n'est pas chiffré sur pCloud. Si tu veux du chiffrement at-rest pCloud, ajouter `crypt:` dans rclone (passphrase). Reco : pas en V1, pas critique pour des images.

## Anti-objectifs

- ❌ Pas de backup quotidien. Hebdo suffit pour ce type de data (le risque d'écrire une image et de la perdre dans les 7 jours est très faible).
- ❌ Pas de "real-time replication" vers pCloud. Trop coûteux en bandwidth, pas le bon problème.
- ❌ Pas de backup sur 2 destinations différentes (pCloud + un autre). Une suffit V1.
- ❌ Pas de versioning à l'intérieur des tarballs. La rétention 4 semaines fait office.
