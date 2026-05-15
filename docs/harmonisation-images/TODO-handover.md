# TODO — handover pour future session Claude

> Deux blocs de travail prêts à reprendre. Chacun est self-contained :
> contexte minimal + commandes exactes. Pour le contexte global, voir
> `PROGRESS.md`.

---

## Bloc A — Activer le module NixOS + setup pCloud (côté VPS)

**État actuel** : MinIO tourne via `docker compose` lancé manuellement
par `infra/minio/bootstrap.sh`. Si on reboot le VPS, **MinIO ne
remonte pas tout seul**. Le backup hebdo n'est pas armé.

**Objectif de ce bloc** : MinIO redémarre auto au boot, le timer
hebdo pousse vers pCloud avec notification ntfy.sh.

### Étape A.1 — Activer le module NixOS (5 min)

Le module est déjà écrit (`/opt/eurio/nix/eurio-vps.nix`) et
auto-conditionné par `hostname == "nixos"`.

Dans `/etc/nixos/configuration.nix`, ajouter une ligne :

```nix
{ ... }: {
  imports = [
    # ... autres imports existants ...
    /opt/eurio/nix/eurio-vps.nix
  ];
}
```

Puis :

```bash
sudo nixos-rebuild switch
sudo systemctl status eurio-minio eurio-backup.timer
# eurio-minio       active (exited)   — RemainAfterExit, OK
# eurio-backup.timer active            — next run = next Sun 03:00 UTC
```

Test reboot (optionnel mais recommandé) :

```bash
docker ps | grep eurio-minio   # noter container ID
sudo reboot
# attendre ~30s, se reconnecter
docker ps | grep eurio-minio   # nouveau container ID, status Up
mc ls eurio/                   # 3 buckets visibles
```

### Étape A.2 — Configurer pCloud (10 min)

Pré-requis : un compte pCloud (gratuit ou Premium).

```bash
# 1. OAuth interactif (génère /root/.config/rclone/rclone.conf)
sudo rclone config
# Réponses :
#   n               (new remote)
#   pcloud          (name)
#   27              (Pcloud)
#   <Enter>×2       (defaults pour client_id / client_secret)
#   n               (auto config — ouvre une URL OAuth)
#   <Enter>         (region : eu)
# Suivre l'URL OAuth, autoriser, revenir au shell, valider.

# 2. Vérifier
sudo rclone lsd pcloud:
# (vide la première fois, c'est normal)

# 3. Configurer ntfy
sudo mkdir -p /etc/eurio
# Choisir un topic random non-deviné par autrui (sécurité par obscurité)
TOPIC="eurio-backup-$(openssl rand -hex 6)"
echo "NTFY_TOPIC=${TOPIC}" | sudo tee /etc/eurio/backup.env
sudo chmod 600 /etc/eurio/backup.env
echo "Subscribe in ntfy app: https://ntfy.sh/${TOPIC}"

# 4. Test manuel du backup (lance immédiatement, pas attendre dimanche)
sudo systemctl start eurio-backup.service
sudo journalctl -u eurio-backup.service -f
# Quand tu vois "Backup done", check :
sudo rclone ls pcloud:eurio-backup/
# eurio-minio.tar  ~XX MiB  YYYY-MM-DD HH:MM:SS
```

Si le service échoue : `journalctl -xeu eurio-backup.service`. Erreurs
fréquentes : pCloud auth périmée (refaire `rclone config`), espace
disque insuffisant dans `/var/tmp`, NTFY_TOPIC absent.

### Étape A.3 — Test de restore (à faire 1× après A.2)

Voir `infra/backup/README.md` §"Test the backup *before* the disaster".
Sans ce test, on ne sait pas si le backup est réellement utilisable.

### Critères de fin

- [ ] `systemctl is-enabled eurio-minio` → `enabled`
- [ ] Reboot VPS → MinIO remonte sans intervention
- [ ] `systemctl list-timers eurio-backup.timer` → next run dimanche prochain
- [ ] Notification ntfy reçue après `systemctl start eurio-backup.service`
- [ ] Restore test extrait un .jpg lisible

---

## Bloc B — Rsync Mac → VPS (côté Mac)

**État actuel** : `ml/state/sources/` (raws + crops scrapés) existe sur
le Mac mais **pas sur le VPS**. Le `migrate_to_minio.py` script tourne
sur le VPS et ne peut migrer que la data localement présente. Sans
rsync, seul le canonique Numista (`ml/datasets/`) sera migré.

**Objectif de ce bloc** : transférer les sources scrapées du Mac vers
le VPS en préservant les chemins, pour que la migration ait quelque
chose à pousser dans `enrichment-raws` et `enrichment-crops`.

### Étape B.1 — Configurer le script rsync (2 min)

Sur le **Mac** (pas le VPS), éditer `~/dev/eurio/infra/sync/rsync-from-mac.sh`
(ou le path équivalent côté Mac), lignes ~28-32 :

```bash
VPS_HOST="${VPS_HOST:-vps}"                 # ton SSH alias VPS
VPS_USER="${VPS_USER:-dontpanic}"           # user remote
MAC_REPO="${MAC_REPO:-${HOME}/dev/eurio}"   # path repo sur le Mac
```

Vérifier l'accès SSH : `ssh ${VPS_USER}@${VPS_HOST} "echo ok"` doit
répondre `ok` sans prompt.

### Étape B.2 — Dry-run (1 min)

```bash
~/dev/eurio/infra/sync/rsync-from-mac.sh
```

Lis la sortie : nombre de fichiers, taille totale. Si la liste te
paraît cohérente (pas de fichier inattendu, pas de répertoire vide
suspect), passe à B.3.

### Étape B.3 — Apply (variable, dépend du volume)

```bash
~/dev/eurio/infra/sync/rsync-from-mac.sh --apply
```

Estimation : ~5-30 min selon la taille de `ml/state/sources/`. Le flag
`--partial` fait que tu peux Ctrl+C et relancer sans perdre la progress.

Si tu veux un mirror exact (suppression côté VPS de fichiers absents
sur le Mac) :

```bash
~/dev/eurio/infra/sync/rsync-from-mac.sh --apply --delete
```

⚠️ `--delete` est destructif côté VPS — utiliser uniquement si tu sais
que le Mac est l'autorité.

### Étape B.4 — Confirmation (30 s)

Sur le VPS :

```bash
ls /opt/eurio/ml/state/sources/    # devrait lister ebay/, catawiki/, mock/, etc.
du -sh /opt/eurio/ml/state/sources/*/raw /opt/eurio/ml/state/sources/*/crops
```

### Critères de fin

- [ ] `/opt/eurio/ml/state/sources/` existe sur le VPS et contient
      au moins un sous-dossier `<source>/raw/` non vide
- [ ] `du -sh` côté Mac et côté VPS retournent des tailles très proches
      (les diffs viennent du fs, pas de fichiers manquants)
- [ ] Aucun warning rsync resté en suspens

### Après B → migration

Une fois le rsync OK, sur le VPS :

```bash
cd /opt/eurio/ml
../.venv/bin/python -m scripts.migrate_to_minio inventory
# inspecter docs/harmonisation-images/migration-manifest.jsonl

../.venv/bin/python -m scripts.migrate_to_minio upload
../.venv/bin/python -m scripts.migrate_to_minio db
../.venv/bin/python -m scripts.migrate_to_minio verify --sample-pct 5
go-task ml:migrate-lock-fs    # safety read-only sur le fs source
```

Garder le local fs read-only pendant 7 jours, puis exécuter le cleanup
documenté dans `chunk-8-cleanup-rollback.md`.

---

## Note pour la session Claude qui reprend

- Le contexte global vit dans `vision.md` + `PROGRESS.md`. Lis-les en
  diagonale avant d'attaquer un bloc.
- Les credentials MinIO sont dans `infra/minio/secrets/eurio_app_*` et
  dans `.envrc` (gitignored). Si MinIO n'est pas accessible : check
  `docker ps | grep eurio-minio`, puis `mc alias list eurio`.
- Les hostnames officiels sont `eurio-s3.musubi.dev` (S3 endpoint) et
  `eurio-images.musubi.dev` (CDN public, sert `numista-canonical/`).
- Si Cloudflare commence à râler (mode SSL, cert expiré), revérifier
  que les CNAME `eurio-s3` et `eurio-images` sont en proxy ON et que
  Universal SSL couvre encore `*.musubi.dev`.
