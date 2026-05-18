# PROGRESS — harmonisation des images

> Journal court de l'avancement réel, en complément de `README.md`
> (plan figé) et `vision.md` (cible). À tenir à jour à chaque fois
> qu'un chunk avance ou qu'on découvre une décision hors-doc.

## État global

| Chunk | Statut | Notes |
|---|---|---|
| 1 — MinIO docker bootstrap | **✅ live** | Container `eurio-minio` running, 3 buckets, user `eurio-app`. Smoke tests 1-4 verts. Hostnames : `eurio-s3.musubi.dev` / `eurio-images.musubi.dev` (renommés vs doc d'origine pour rester sous CF Universal SSL). |
| 2 — Schéma DB + format storage_key | **✅ live** | `storage_path` = S3 key partout dans les paths scrape (SS-1/SS-2 commit `b8977b9`). |
| 3 — Migration scripts | **⚠️ DEPRECATED** | `ml/scripts/migrate_to_minio.py` conservé en utility récup mais affiche un banner DEPRECATED — le scrape écrit désormais write-through. |
| 4 — Cache local read-through | **✅ live** | `local_path()` + `upload_through()` actifs. Hook 404 chunk 9 intégré. |
| 5 — Pre-fetch run-scoped training | ⏳ pending | Dépend de 4 stable. |
| 6 — Publication Supabase | ⏳ pending | Indépendant de 3, peut partir en parallèle. |
| 7 — Backup pCloud | **🟡 script + module Nix prêts** | `infra/backup/backup-minio-to-pcloud.sh` + `nix/eurio-vps.nix`. Manque : `rclone config` interactif côté VPS + `/etc/eurio/backup.env` avec NTFY_TOPIC. |
| 8 — Cleanup + rollback | ⏳ pending | À déclencher J+7 après la migration. |
| 9 — Cascade sync MinIO ↔ DB ↔ cache | **🟢 code prêt, à tester** | `ml/storage/cascade.py` + hook 404 dans `local_cache.py` + script `ml/scripts/cascade_sync.py` + tests `tests/test_storage_cascade.py` + colonne `storage_status` dans `schema.sql`. À tester E2E quand il y aura des assets dans MinIO. |

## Décisions hors-doc actées en session

### 2026-05-16 — SS-0/1/2 scrape write-through (commit `b8977b9`)

- **SS-0 (wipe)** : `ml/state/sources/` rm -rf (407 MB), 6657 rows DELETE
  dans `source_images`/`image_assets`/`discovery_log`/`source_runs`. On
  repart greenfield, plus de legacy FS à migrer.
- **SS-1 (write-through)** : `ml/sources/_base/steps/download.py` et
  `detect_crop.py` poussent directement dans MinIO via
  `storage.local_cache.upload_through()`. `storage_path` = S3 key (jamais
  un FS path absolu). Pré-génération de `asset_id` côté code pour bâtir
  la S3 key avant l'INSERT (idempotent).
- **SS-2 (read-through)** : tous les `Path(storage_path)` downstream
  sont devenus `local_path(bucket, key)`. Concerne `detect_crop.py`,
  `auto_validate.py`, `api/sources_routes.py`, `api/review_queue_routes.py`.
  `recrop_ebay_orphans.py` → stub déprécié (cascade_sync gère).
- **SS-3 (cette session)** : tests réparés (conftest stube `_s3_client`
  en MagicMock par défaut, test_storage_cascade skip si botocore absent,
  test_orchestrator passe au cache root au lieu de `_STORAGE_ROOT`),
  `migrate_to_minio.py` banner DEPRECATED sur stderr, fix bootstrap
  store.py (skip ALTER si table absente — fresh DB), fix nanoseconde
  dans `local_path()` (atime touch ne corrompait l'mtime que via
  float→ns).
- **Block-until-reconnect** : `upload_through()` retry exponential
  backoff 17 min (delays 2/5/15/30/60/120/300/600s). Au-delà,
  RuntimeError → l'orchestrateur compte l'item en `n_errors`.
- **`migrate_to_minio.py`** garde sa CLI complète mais imprime un banner
  DEPRECATED sur stderr à chaque invocation. Utility récup uniquement.

### 2026-05-15

- **Hostnames renommés** : `s3.eurio.musubi.dev` → `eurio-s3.musubi.dev`,
  `images.eurio.musubi.dev` → `eurio-images.musubi.dev`. Raison : le
  Universal SSL Cloudflare (gratuit) couvre `*.musubi.dev` mais pas
  `*.eurio.musubi.dev` (multi-niveau). Tous les fichiers config + docs
  alignés.
- **MinIO data dans le repo** (`infra/minio/data/`, gitignored, marker
  `.do-not-delete` versionné). Décision portée par l'utilisateur :
  "tout ce qui concerne ce projet doit être visible depuis le repo".
  Trade-off documenté dans `infra/minio/README.md` §"Why this lives in
  the repo".
- **Cascade MinIO → DB → cache** ajoutée comme chunk 9 (hors plan
  initial). Politique : NULL + colonne `storage_status` plutôt que
  DELETE de row. Combo réactif (404) + périodique (audit script).
- **Policy `eurio-app`** étend `s3:ListAllMyBuckets` au niveau compte
  (sinon `mc ls eurio/` est `Access Denied`).
- **Module NixOS auto-conditionné** par `hostname == "nixos"` pour
  qu'importer le fichier sur une autre machine soit un no-op.

### Chunk 9 — décisions hors-doc (2026-05-15 session 2)

- `storage_path` reste **inchangé** quand on marque une row missing
  (au lieu de NULL). SQLite ne peut pas trivialement drop le NOT NULL
  sur `image_assets.storage_path`, et garder la "dernière clé connue"
  facilite l'audit/debug. Le code lecteur doit checker
  `storage_status = 'present'` avant d'utiliser `storage_path`.
- Le script `cascade_sync` ne supprime **jamais** d'objet MinIO. Les
  orphelins MinIO restent du ressort manuel (chunk 8.3). Évite le
  scénario "le sync efface des données par erreur".
- Le hook 404 dans `local_cache.local_path()` ne se déclenche que sur
  un vrai 404/NoSuchKey. Une erreur réseau transitoire **ne marque pas**
  la row (sinon, un blip Cloudflare flippe toute la DB).
- Override DB path via `EURIO_TRAINING_DB` env var (utile pour les tests).

### Choses à NE PAS oublier

- Si on renomme l'hôte du VPS, mettre à jour `eurio.vps.enable` dans
  `nix/eurio-vps.nix` (default basé sur `hostname == "nixos"`).
- Le cert Let's Encrypt pour les 2 hostnames est émis par Traefik via
  `letsencryptresolver` (HTTP challenge). Si on ajoute des sous-domaines
  plus tard, vérifier que Traefik a accès au port 80 public.
- La policy actuelle accorde `s3:DeleteObject`. Si on veut un mode
  "append-only" pour la chaîne training, créer une seconde policy
  read-only et un user `eurio-train` dédié.

## Smoke tests passés (2026-05-15, par Claude depuis le VPS)

```
✅ mc ls eurio/                                    → 3 buckets
✅ curl https://eurio-images.musubi.dev/<key>     → 200 + payload
✅ curl https://eurio-s3.musubi.dev/<priv>/x      → 403 anon
✅ 50 MB multipart upload + download              → sha256 MATCH
```

Pas encore testé :
- [ ] Reboot du VPS → MinIO remonte tout seul (nécessite l'activation
      du module NixOS d'abord)
- [ ] Backup script de bout en bout vers pCloud (nécessite rclone configuré)
- [ ] Migration Numista canonique (856 MB) depuis `ml/datasets/`

## Prochaines actions concrètes

### Côté serveur (à enchaîner quand tu as 5 min, indépendant)

1. **Activer le module NixOS** :
   ```nix
   # /etc/nixos/configuration.nix
   imports = [ /opt/eurio/nix/eurio-vps.nix ];
   ```
   ```bash
   sudo nixos-rebuild switch
   sudo systemctl status eurio-minio eurio-backup.timer
   ```

2. **Configurer pCloud** (interactif) :
   ```bash
   sudo rclone config           # ajoute remote 'pcloud'
   sudo mkdir -p /etc/eurio
   echo "NTFY_TOPIC=eurio-backup-<random>" | sudo tee /etc/eurio/backup.env
   sudo chmod 600 /etc/eurio/backup.env
   sudo systemctl start eurio-backup.service   # test manuel
   ```

### Côté Mac (à enchaîner quand tu veux)

3. **Sync les sources scrapées Mac → VPS** :
   ```bash
   # depuis le Mac
   $EDITOR ~/dev/eurio/infra/sync/rsync-from-mac.sh   # set VPS_HOST
   ~/dev/eurio/infra/sync/rsync-from-mac.sh           # dry-run
   ~/dev/eurio/infra/sync/rsync-from-mac.sh --apply
   ```

### Côté code (mes prochains commits)

4. **Cascade chunk 9** (en parallèle de la migration) :
   - Hook 404 dans `local_cache.local_path()`
   - Helper `delete_asset_cascade(...)` dans `ml/storage/__init__.py`
   - Schéma DB : ajouter `storage_status` aux 2 tables
   - Script `ml/scripts/cascade_sync.py` (audit + repair)

5. **Migration Numista canonique** (déjà sur le VPS, rapide) :
   ```bash
   cd /opt/eurio/ml
   ../.venv/bin/python -m scripts.migrate_to_minio inventory
   ../.venv/bin/python -m scripts.migrate_to_minio upload --category canonical
   # pas de DB rewrite pour les canoniques (pas de row image_assets)
   ```

6. **Wiring routes API** (`sources_routes.py`) : remplacer les
   `FileResponse(p)` par `RedirectResponse(signed_url(...))`.

7. **Wiring pipelines scrape** (`download.py`, `detect_crop.py`) :
   écrire directement dans MinIO au lieu de `ml/state/sources/`.

8. **Migration sources** (après rsync) :
   ```bash
   ../.venv/bin/python -m scripts.migrate_to_minio upload --category raw
   ../.venv/bin/python -m scripts.migrate_to_minio upload --category crop
   ../.venv/bin/python -m scripts.migrate_to_minio db
   ../.venv/bin/python -m scripts.migrate_to_minio verify --sample-pct 10
   ```

## Trade-offs explicites

- **Cert Let's Encrypt via Traefik** (pas Cloudflare Origin Cert) :
  rotation auto, mais nécessite que le port 80 reste joignable par
  Let's Encrypt à travers Cloudflare (CF proxy passe le HTTP-01 par
  défaut). Si on coupe le port 80 un jour, basculer sur DNS-01.
- **Pas de monitoring MinIO** V1 : on s'appuie sur `docker logs`
  + ntfy.sh pour le backup. Suffisant pour V1.
- **Pas de quotas par bucket** : les disques VPS ont 173 GB libres,
  largement de marge. Si le scrape explose, on saura via `df`.
