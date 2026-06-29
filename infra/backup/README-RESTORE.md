# Eurio — guide de restauration du backup pCloud

> **Tu lis ce fichier parce que tu as perdu le serveur Eurio et que tu veux
> récupérer la data.** Suis les étapes dans l'ordre. ~30 min si tout va bien.

## Ce qu'il y a sur ce backup

`backups/serverOimNix/Eurio/` contient 4 dossiers. Le **canonique** vient du
conteneur `eurio-api` (Model B / R2 : la DB n'est plus dans MinIO) ; les 3 autres
sont des buckets MinIO d'images :

| Dossier               | Contenu                                          | Source        | Taille approx |
|-----------------------|--------------------------------------------------|---------------|---------------|
| `eurio-db/`           | SQLite **canonique** (`eurio.db` + `.sha256`)    | conteneur VPS | ~200 MiB      |
| `enrichment-crops/`   | Crops images du pipeline d'enrichissement        | MinIO         | ~620 MiB      |
| `enrichment-raws/`    | Raws images du pipeline                          | MinIO         | ~3 GiB        |
| `numista-canonical/`  | Référentiel Numista (pages HTML, JSON, médias)   | MinIO         | ~80 MiB       |

**Noms de fichiers/dossiers en clair, contenu chiffré** (rclone crypt).

## Ce dont tu as besoin pour déchiffrer

**La clé Age dédiée backup Eurio.** Trois copies existent (au moins une suffit) :

1. **Bitwarden** — entry "Eurio backup Age key" (compte raphaelthi59@gmail.com)
2. **Papier** — coffre / dossier physique, ligne `AGE-SECRET-KEY-1...`
3. **Sur l'ancien serveur** si toujours accessible : `~/.config/eurio-backup/age-key.txt`

**Sans cette clé, le backup est IRRÉCUPÉRABLE.** C'est volontaire.

## Procédure

### 1. Installer les outils

```bash
# NixOS
nix profile install nixpkgs#rclone nixpkgs#age

# macOS
brew install rclone age

# Debian/Ubuntu
sudo apt install rclone age
```

### 2. Cloner le repo Eurio (la logique de backup vit dans le repo)

```bash
git clone git@codeberg.org:Musubi42/Eurio.git
cd Eurio
```

### 3. Restaurer la clé Age sur disque

```bash
mkdir -p ~/.config/eurio-backup && chmod 700 ~/.config/eurio-backup
# Coller le contenu de l'entry Bitwarden (ou du papier) dans :
$EDITOR ~/.config/eurio-backup/age-key.txt
chmod 400 ~/.config/eurio-backup/age-key.txt
```

Le fichier doit ressembler à :
```
# created: 2026-06-17T...
# public key: age1...
AGE-SECRET-KEY-1QQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQ
```

### 4. Configurer rclone

Crée `~/.config/rclone/rclone.conf` avec ces sections (template :
`infra/backup/rclone.conf.example` dans le repo) :

```ini
[pcloud]
type = pcloud
hostname = api.pcloud.com
token = <obtenir via `rclone authorize pcloud` sur une machine avec navigateur>

[pcloud_crypt]
type = crypt
remote = pcloud:backups/serverOimNix/Eurio
filename_encryption = off
directory_name_encryption = false
suffix = none
# pas de password — fourni au runtime par eurio-backup.sh
```

### 5. Vérifier l'accès chiffré

```bash
./infra/backup/eurio-backup.sh rclone lsd pcloud_crypt:
# → doit lister 4 dossiers en clair : eurio-db, enrichment-crops, …
# Si rien ne s'affiche ou erreur de déchiffrement : clé Age incorrecte.
```

### 6. Restaurer localement

```bash
mkdir -p ./restore
for b in eurio-db enrichment-crops enrichment-raws numista-canonical; do
  ./infra/backup/eurio-backup.sh rclone copy "pcloud_crypt:$b" "./restore/$b/" \
    --fast-list --transfers 8 --progress
done
```

### 7. (Si tu remontes un serveur Eurio complet)

**Canonique `eurio.db`** → restaurer dans le volume du conteneur `eurio-api`
(writer unique, Model B), **pas** dans MinIO :

```bash
# Vérifier l'intégrité du backup avant restauration
sha256sum ./restore/eurio-db/eurio.db        # doit == contenu de eurio.db.sha256
# Placer le fichier là où eurio-api le monte (cf. infra/eurio-api/docker-compose.yml,
# volume EURIO_DB_PATH → /var/lib/eurio/eurio.db), conteneur arrêté :
docker cp ./restore/eurio-db/eurio.db eurio-api:/var/lib/eurio/eurio.db
```

**Images** → ré-injecter dans MinIO (cf. `infra/minio/README.md` §"Restore") :

```bash
cd infra/minio && ./bootstrap.sh        # recrée buckets + creds
for b in enrichment-crops enrichment-raws numista-canonical; do
  ./infra/backup/eurio-backup.sh rclone copy "./restore/$b/" "minio:$b/"
done
```

Si tu n'as pas le `rclone.conf` de l'ancien serveur, regénère les creds via
`infra/minio/bootstrap.sh` qui génère un nouveau set.

## Sanity post-restauration

```bash
# Taille (doit matcher l'original aux KiB près)
./infra/backup/eurio-backup.sh rclone size pcloud_crypt:eurio-db

# DB lisible ?
nix shell nixpkgs#sqlite --command sqlite3 ./restore/eurio-db/eurio.db \
  "select count(*) from sqlite_master where type='table';"
```

## Si quelque chose ne va pas

- **"Couldn't decrypt"** au `rclone lsd` → clé Age incorrecte. Vérifier le
  format (`AGE-SECRET-KEY-1...`, sans espace ni newline parasite).
- **Token pCloud expiré** → `rclone reconnect pcloud:` ou regénérer via
  `rclone authorize pcloud`.
- **Différence de taille source/restauration** → comparer `rclone size` côté
  pCloud chiffré et déchiffré. La différence doit être négligeable (overhead
  crypt = 32 octets par objet).

## Méta

- **Date de création de ce backup** : voir le timestamp côté pCloud du dossier
  `backups/serverOimNix/Eurio/`.
- **Commit du repo Eurio au moment du backup** : tracké dans les commits du
  repo `git@codeberg.org:Musubi42/Eurio.git` (branche par défaut).
- **Repo canonique du code** : Codeberg (GitHub déprécié depuis 2026-06-17).
