# Chunk 3 — Migration scripts (3 inventaires)

> Le jour J : on déplace toutes les images locales vers MinIO, on
> ré-écrit les `storage_path` en DB, on vérifie l'intégrité, on bascule
> le code en mode "MinIO only". Hard cut. Pré-requis : chunks 1 et 2
> livrés.

## Objectif

À la fin du chunk :

- Les 3 catégories d'images sont dans MinIO (canonique → `numista-canonical`, raws → `enrichment-raws`, crops → `enrichment-crops`).
- DB : tous les `storage_path` portent une clé S3 relative au bucket. 0 chemin fs absolu.
- Filesystem local en read-only pendant 7 jours, puis supprimé (chunk 8).
- Le code Eurio (API ML, scrape, training) lit MinIO via `local_path()` (cache read-through, chunk 4).

## Trois inventaires distincts

| Catégorie | Source filesystem | Bucket cible | Clé cible |
|---|---|---|---|
| **Canonique Numista** | `ml/datasets/<numista_id>/{obverse,reverse}.jpg` | `numista-canonical` | `numista/<numista_id>/<face>.jpg` |
| **Enrichment crops** | `ml/state/sources/<src>/crops/<shard>/<source_ref>__c<idx>.png` | `enrichment-crops` | `<source>/<run_id>/<asset_id>.png` |
| **Enrichment raws** | `ml/state/sources/<src>/raw/<shard>/<source_ref>.<ext>` | `enrichment-raws` | `<source>/<run_id>/<source_image_id>.<ext>` |

**Hors scope** : `ml/cache/augmentation_sources/`, `ml/debug_captures/`. Ces dossiers restent locaux (vision §P5).

## Pré-requis

- Chunk 1 livré (MinIO + 3 buckets up).
- Chunk 2 livré (module `ml/storage/`, format des clés figé).
- Backup VPS existant avant de tourner (au cas où le script foire).
- Credentials MinIO `eurio-app` configurés via direnv.
- Plus aucun pipeline scrape / training en cours (lock manuel sur les machines).

## Décisions actées

1. **Ordre** : canonique d'abord (le plus simple), puis raws, puis crops. Si crops foire on a déjà la base.
2. **Workers parallèle** : 8 (default). Ne sature pas le réseau Mac.
3. **Sample sha256 verify** : 5 % avec floor 100 fichiers, ceil 1000.
4. **Lock fs** : 7 jours.
5. **Pas de migration "lazy"** : tout en une session, fail-fast si erreur globale.

## Implémentation

Le tout vit dans `ml/scripts/migrate_to_minio.py` avec sous-commandes :

```bash
go-task ml:migrate-inventory   # build le manifest
go-task ml:migrate-upload      # push vers MinIO (idempotent)
go-task ml:migrate-db          # réécrit storage_path en DB
go-task ml:migrate-verify      # sample sha256
go-task ml:migrate-lock-fs     # chmod a-w sur les dossiers source
```

### 3.1 Inventaire (one-shot, génère le manifest)

```bash
go-task ml:migrate-inventory
```

Le script :

1. Scanne `ml/datasets/` → ajoute lignes `category=canonical`.
2. SELECT `source_images` → ajoute lignes `category=raw`.
3. SELECT `image_assets` → ajoute lignes `category=crop`.
4. Pour chaque entrée, calcule sha256 + size, dérive la clé S3 cible.
5. Détecte les divergences :
   - Fichier absent sur disque → `--report-missing`
   - Fichier sur disque sans ligne DB → `--report-orphans`
6. Output : `docs/harmonisation-images/migration-manifest.jsonl` (commit dans git).

Format :

```json
{"category": "canonical", "numista_id": "68395", "face": "obverse",
 "fs_path": "/Users/.../ml/datasets/68395/obverse.jpg",
 "bucket": "numista-canonical", "storage_key": "numista/68395/obverse.jpg",
 "size": 184392, "sha256": "abc..."}

{"category": "crop", "table": "image_assets", "id": "uuid-...",
 "fs_path": "/Users/.../ml/state/sources/ebay/crops/ab/xxx__c0.png",
 "bucket": "enrichment-crops", "storage_key": "ebay/run-uuid/uuid-....png",
 "size": 12345, "sha256": "..."}
```

Le manifest sert de **source de vérité du mapping fs → S3** et de **filet de rollback** (chunk 8).

### 3.2 Upload (idempotent, parallèle)

```bash
go-task ml:migrate-upload
```

Pour chaque entrée du manifest :

- Si l'objet existe en MinIO **et** son metadata `x-amz-meta-sha256` matche le manifest → skip.
- Sinon, `boto3.upload_file()` en single-part (force `Config(multipart_threshold=10*1024**3)` pour rester en single-part jusqu'à 10 GB), avec `Metadata={'sha256': ...}` et `ContentType` correct.
- Pour `numista-canonical` : ajouter `Metadata={'cache-control': 'public, max-age=604800, immutable'}`.

Idempotent : si le script crash, on relance, ça reprend.

### 3.3 DB update (transactionnel)

```bash
go-task ml:migrate-db
```

Une seule transaction :

```sql
BEGIN;

-- Backup safety : copier storage_path actuel dans une colonne archive
ALTER TABLE image_assets   ADD COLUMN storage_path_legacy TEXT;
ALTER TABLE source_images  ADD COLUMN storage_path_legacy TEXT;
UPDATE image_assets   SET storage_path_legacy = storage_path;
UPDATE source_images  SET storage_path_legacy = storage_path;

-- Réécrire storage_path en clé S3
-- (les UPDATE sont générés depuis le manifest, batch par 500)
UPDATE image_assets  SET storage_path = '<storage_key>' WHERE id = '<id>';
UPDATE source_images SET storage_path = '<storage_key>' WHERE id = '<id>';

-- Sanity check
SELECT COUNT(*) FROM image_assets   WHERE storage_path LIKE '/%';  -- doit être 0
SELECT COUNT(*) FROM source_images  WHERE storage_path LIKE '/%';  -- doit être 0

INSERT INTO migrations_log (name, applied_at, rows_affected)
  VALUES ('fs_to_minio_2026_05', datetime('now'), <total>);

COMMIT;
```

`storage_path_legacy` reste 7 jours puis est dropé au chunk 8.

### 3.4 Vérification sha256 (sample)

```bash
go-task ml:migrate-verify -- --sample-pct=5
```

Tire 5 % du manifest, télécharge depuis MinIO, recompute sha256, compare. Si mismatch → ALERTE rouge, rollback prep.

### 3.5 Lock filesystem

```bash
go-task ml:migrate-lock-fs
```

```bash
chmod -R a-w ml/datasets
chmod -R a-w ml/state/sources/*/raw
chmod -R a-w ml/state/sources/*/crops
```

Le code MinIO continue de tourner. Si on a oublié quelque chose dans 7 jours, le filesystem est encore lisible (juste pas écrivable).

## Tâches go-task à ajouter

```yaml
ml:migrate-inventory:
  desc: Build migration manifest with sha256 (3 categories)
  cmds: [python -m ml.scripts.migrate_to_minio inventory]
ml:migrate-upload:
  desc: Upload all images to MinIO (idempotent)
  cmds: [python -m ml.scripts.migrate_to_minio upload {{.CLI_ARGS}}]
ml:migrate-db:
  desc: Rewrite storage_path → S3 key, archive legacy
  cmds: [python -m ml.scripts.migrate_to_minio db]
ml:migrate-verify:
  desc: sha256 sample verification (default 5%)
  cmds: [python -m ml.scripts.migrate_to_minio verify {{.CLI_ARGS}}]
ml:migrate-lock-fs:
  desc: chmod a-w on local dirs (7-day safety)
  cmds: [python -m ml.scripts.migrate_to_minio lock-fs]
```

## Critères d'acceptation

- [ ] Manifest généré pour les 3 catégories, commité dans `docs/harmonisation-images/migration-manifest.jsonl`
- [ ] Upload : 100 % des entrées présentes en MinIO avec `x-amz-meta-sha256` qui matche
- [ ] DB : 0 `storage_path` avec `/` en tête, 0 NULL non-attendu
- [ ] `storage_path_legacy` archive les anciens chemins
- [ ] Verify sample 5 % : 0 mismatch
- [ ] Code Eurio (API ML, scrape, training) tourne contre MinIO sans erreur pendant ≥ 24h
- [ ] Filesystem source en read-only après lock-fs
- [ ] `migrations_log` row inséré

## Gotchas

- **Idempotence** : skip si objet existe **et** sha256 metadata matche. Pas de skip basé sur ETag (multipart casse l'égalité ETag = MD5).
- **`run_id` NULL** : convention `'no-run'` dans la clé S3, documenté dans le code.
- **Source case-sensitivity** : normaliser `source_images.source` en lowercase avant de construire la clé.
- **Caractères spéciaux dans `source_ref`** : on n'utilise jamais `source_ref` dans la clé S3 (on prend `source_images.id` ou `image_assets.id`, qui sont des UUIDs). Donc safe par construction.
- **Si MinIO down pendant upload** : le script s'arrête, reprendre quand back. Pas de fallback fs.

## Procédure de rollback (si désastre ≤ J+7)

1. Le filesystem local est encore là (lecture seule).
2. `UPDATE ... SET storage_path = storage_path_legacy` (un seul SQL).
3. `chmod -R u+w ml/datasets ml/state/sources` pour relâcher le lock.
4. Continuer comme avant le J.

C'est la raison du `storage_path_legacy` + délai 7 jours.

## Anti-objectifs

- ❌ Pas de migration "lente" (1 fichier/sec). Pool de workers parallèle.
- ❌ Pas de double écriture pendant la migration. Le code n'écrit nulle part jusqu'à ce que la migration soit sealed.
- ❌ Pas de "sync continu" entre fs et MinIO post-migration. Hard cut.
- ❌ Pas de migration des augmentations (`ml/cache/`) ni des debug captures (`ml/debug_captures/`).
