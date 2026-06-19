# `infra/backup/` — Backup chiffré MinIO → pCloud

> Backup off-site de la data MinIO (DB + crops + raws + canonical) vers pCloud,
> chiffré côté client avec `rclone crypt`. Le secret est une clé Age dédiée,
> qui ne touche jamais le store Nix ni le repo. La logique vit dans le repo
> (portable d'un serveur à l'autre), seul le runtime est sur le serveur.

## TL;DR opérationnel

```bash
# One-time, sur un nouveau serveur :
./infra/backup/eurio-backup.sh keygen    # génère ~/.config/eurio-backup/age-key.txt
                                         # → SAUVEGARDER dans Bitwarden + papier !

# Récurrent :
./infra/backup/eurio-backup.sh run       # backup 4 buckets vers pcloud_crypt:
./infra/backup/eurio-backup.sh verify    # check --one-way + sha256 DB
```

## Pourquoi ce design

- **Logique dans le repo** (`infra/backup/`) — pas dans `/etc/nixos` ni dans un
  ailleurs serveur-spécifique. Si on change de serveur : `git clone` + restaurer
  la clé Age depuis Bitwarden + recréer `rclone.conf` = repartis.
- **Chiffrement côté client** — pCloud est sécurisé et nous appartient, mais on
  ne fait pas confiance au stockage cloud par principe. `rclone crypt` chiffre
  avant l'upload, déchiffre après le download. pCloud ne voit que des bytes.
- **Noms de fichiers en CLAIR** (`filename_encryption = off`) — trade-off
  délibéré : on accepte que pCloud voie `eurio-db/eurio.db`, on gagne la
  lisibilité (debug, restauration partielle) et un README clair.
- **Clé Age dédiée** — séparée de la clé Age utilisée par SOPS pour
  `secrets/dev.env`. Si la clé dev fuite, le backup reste safe (et vice-versa).
- **Clé jamais dans le store** — vit à `~/.config/eurio-backup/age-key.txt`
  (mode 400), lue au runtime par le wrapper qui exporte les env vars rclone.
  Le `rclone.conf` ne contient PAS le password.

## Architecture

```
┌─────────────────┐                    ┌──────────────────────────────────┐
│  MinIO (S3)     │                    │  pCloud (compte US)              │
│  4 buckets      │                    │  backups/serverOimNix/Eurio/     │
│                 │   ── rclone copy ──▶│  ├─ eurio-db/...   (CHIFFRÉ)    │
│                 │      via crypt     │  ├─ enrichment-...  (CHIFFRÉ)    │
└─────────────────┘                    │  └─ README-RESTORE.md  (CLAIR)   │
                                       └──────────────────────────────────┘
       ▲                                              ▲
       │                                              │
       └─────────── eurio-backup.sh run ──────────────┘
                          │
                          │ lit la clé Age
                          ▼
              ~/.config/eurio-backup/age-key.txt
                  (mode 400, hors store, hors repo)
                  ← sauvegarde Bitwarden + papier
```

## Setup d'un nouveau serveur (procédure complète)

### 1. Prérequis NixOS

`rclone` et `age` doivent être disponibles. Au choix :
- Importer le module `nix/eurio-vps.nix` dans la config NixOS du serveur
  (ajoute `rclone`, `age`, `curl` en `environment.systemPackages`), OU
- Le script `eurio-backup.sh` se re-exec dans `nix shell nixpkgs#rclone
  nixpkgs#age` automatiquement si les binaires manquent (lent au 1er run).

### 2. Cloner le repo

```bash
git clone git@codeberg.org:Musubi42/Eurio.git /opt/eurio
cd /opt/eurio
```

### 3. Configurer rclone

```bash
mkdir -p ~/.config/rclone
# Coller les sections [pcloud] [pcloud_crypt] [minio] depuis rclone.conf.example
$EDITOR ~/.config/rclone/rclone.conf
# Pour pcloud : générer le token via `rclone authorize pcloud` sur une machine
# avec navigateur, puis coller le blob dans rclone.conf.
# Pour minio : récupérer les creds root depuis infra/minio/secrets/.
```

### 4. Restaurer (ou générer) la clé Age

**Si c'est un nouveau setup** :
```bash
./infra/backup/eurio-backup.sh keygen
# → affiche la clé. La copier dans Bitwarden + papier IMMÉDIATEMENT.
```

**Si on restaure un setup existant** :
```bash
mkdir -p ~/.config/eurio-backup && chmod 700 ~/.config/eurio-backup
$EDITOR ~/.config/eurio-backup/age-key.txt
# → coller le contenu depuis Bitwarden
chmod 400 ~/.config/eurio-backup/age-key.txt
```

### 5. Test

```bash
./infra/backup/eurio-backup.sh rclone lsd pcloud_crypt:
# → doit lister les buckets en clair (eurio-db, enrichment-crops, …)
```

### 6. Premier backup

```bash
./infra/backup/eurio-backup.sh run
./infra/backup/eurio-backup.sh verify
./infra/backup/eurio-backup.sh upload-readme
```

## Automation (optionnel — module Nix)

Le module `nix/eurio-vps.nix` définit un `systemd.timers.eurio-backup`
hebdomadaire (dimanche 03:00 UTC). Pour l'activer :

```nix
# /etc/nixos/configuration.nix
imports = [ /opt/eurio/nix/eurio-vps.nix ];
```

Le module reste dormant tant qu'il n'est pas importé.

## Restauration

Voir `README-RESTORE.md` (uploadé en clair sur pCloud).

## Trade-offs

- **Pas de retention multi-snapshot** — `rclone copy` est append/overwrite :
  un objet supprimé côté source n'est pas supprimé côté backup (bénin), un
  objet modifié écrase. Si on a besoin de versioning, ajouter `--backup-dir`
  ou passer à un outil dédié (restic, borg).
- **Salt déterministe** — le `password2` rclone est dérivé du `password`
  (`sha256(secret+"-salt")`). Avantage : 1 secret à protéger. Inconvénient :
  pas d'isolation cryptographique entre password et salt. Acceptable pour ce
  usage (secret unique de toute façon).
- **Pas de notification ntfy** (présente dans la version V1 weekly tarball)
  — réintroduisable trivialement dans le wrapper si besoin opérationnel.
- **Pas de re-encryption à la rotation de clé** — si la clé Age est compromise,
  il faut générer une nouvelle clé ET re-uploader tout le backup (rclone
  crypt n'a pas de notion de rotation). Pour un perso, accepté.
