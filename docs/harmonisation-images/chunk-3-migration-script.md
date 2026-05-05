# Chunk 3 — Script one-shot migration fs → MinIO

> Le jour J : on déplace toutes les images locales vers MinIO, on ré-écrit
> les `storage_key` en DB, on vérifie l'intégrité, on bascule le code en
> mode "MinIO only". Hard cut. Pré-requis : chunks 1 et 2 livrés.

## Objectif

Un script `ml/scripts/migrate_to_minio.py` qui, en une commande :

1. Inventorie tous les fichiers locaux et leurs lignes DB associées.
2. Upload vers MinIO en parallèle (pool de workers).
3. Met à jour les `storage_key` en DB (transactionnel).
4. Vérifie l'intégrité par sha256 sur N% des fichiers (sample).
5. Produit un rapport (combien de fichiers, total bytes, durée, échecs).

À la fin :
- DB pointe vers MinIO uniquement.
- Filesystem local conservé en lecture-seule pendant 7 jours (sécurité).
- Le code Eurio (API ML, scrape, training) parle MinIO.

## Pré-requis

- Chunk 1 livré (MinIO + buckets up).
- Chunk 2 livré (`storage_key` en place dans le schéma, module `ml/storage/`).
- Backup pCloud existe avant de tourner (au cas où le script foire avant la fin).
- Credentials MinIO `eurio-app` configurés via direnv (`.envrc` / `pass`).

## Décisions à acter

1. **Upload parallèle** : combien de workers ? Default 8. Sur un VPS Hetzner ça sature pas le réseau du Mac.
2. **Sample size pour vérif sha256** : 5 % avec un floor à 100 fichiers. Au-delà de 1000 fichiers vérifiés, le coût n'apporte plus rien.
3. **Délai de safety filesystem** : 7 jours avant suppression — pendant ces 7 jours le code lit MinIO (donc tout fonctionne) mais le fs local reste là, on peut rollback en re-rewritant les `storage_key`.

## Implémentation

### 3.1 Inventaire (dry-run)

```bash
go-task ml:migrate-inventory
```

Lit la DB, liste tous les `(table, id, storage_key, fs_path_legacy)` où `fs_path_legacy` est le chemin filesystem absolu calculé depuis `storage_key` + base path `ml/datasets` (ou ce qui était la convention legacy).

Output : `migration-manifest.jsonl`, une ligne par fichier :
```json
{"table": "image_assets", "id": "abc...", "storage_key": "ebay/run-1/abc.png",
 "fs_path": "/Users/musubi42/.../ebay/run-1/abc.png", "size": 184392, "sha256": "..."}
```

Calcule sha256 à ce moment (long, mais une seule fois). Détecte aussi :
- Fichiers en DB mais absents sur disque → `--report-missing`
- Fichiers sur disque mais pas en DB → `--report-orphans`

### 3.2 Upload (parallèle, idempotent)

```bash
go-task ml:migrate-upload -- --workers=8 --manifest=migration-manifest.jsonl
```

Pour chaque entrée du manifeste :
- Si `mc stat eurio/<bucket>/<storage_key>` existe et que sha256 match → skip (idempotent : le script peut tourner 2 fois si interrompu).
- Sinon, `boto3.upload_file()` avec ContentType correct, ContentLength = size.
- Marque `uploaded_at` dans le manifeste enrichi.

Rapport en cours : `tqdm` avec ETA, nombre de fichiers/sec, bytes/sec.

### 3.3 DB update (transactionnel)

```bash
go-task ml:migrate-db
```

Une seule transaction SQL :
```sql
BEGIN;
-- Vérifie qu'aucun storage_key n'est NULL ou n'a un chemin fs absolu
SELECT COUNT(*) FROM image_assets WHERE storage_key LIKE '/%' OR storage_key IS NULL;
-- (doit être 0 — sinon ABORT)

-- Tag de migration (pour rollback)
CREATE TABLE IF NOT EXISTS migrations_log (
  name TEXT PRIMARY KEY,
  applied_at TEXT NOT NULL,
  rows_affected INTEGER NOT NULL
);
INSERT INTO migrations_log VALUES ('fs_to_minio_2026_05', datetime('now'), 0);
COMMIT;
```

(En réalité les `storage_key` ont déjà été ré-écrits par chunk 2 ; cette étape ne fait que sceller la migration.)

### 3.4 Vérification sha256 (sample)

```bash
go-task ml:migrate-verify -- --sample-pct=5
```

Tire 5 % des assets aléatoirement, télécharge depuis MinIO, recompute sha256, compare avec le manifeste. Si mismatch → ALERTE rouge, rollback prep.

### 3.5 Sécurité fs lock

```bash
go-task ml:migrate-lock-fs
```

Fait `chmod -R a-w /Users/musubi42/Documents/Musubi42/Eurio/ml/datasets` (read-only sur le filesystem local). Le code MinIO continue de tourner. Si on a oublié quelque chose dans 7 jours, le filesystem est encore lisible.

### 3.6 Cleanup final (J+7)

```bash
go-task ml:migrate-cleanup
```

`rm -rf ml/datasets/`. Définitif. À tourner manuellement après validation que rien n'est cassé pendant 7 jours.

## Tâches go-task à ajouter

```yaml
# ml/Taskfile.yml (extrait)
tasks:
  migrate-inventory:
    desc: Build migration manifest with sha256
    cmds: [python ml/scripts/migrate_to_minio.py inventory]
  migrate-upload:
    desc: Upload all images to MinIO (idempotent)
    cmds: [python ml/scripts/migrate_to_minio.py upload {{.CLI_ARGS}}]
  migrate-db:
    desc: Seal storage_key migration in DB
    cmds: [python ml/scripts/migrate_to_minio.py seal-db]
  migrate-verify:
    desc: sha256 sample verification (default 5%)
    cmds: [python ml/scripts/migrate_to_minio.py verify {{.CLI_ARGS}}]
  migrate-lock-fs:
    desc: chmod a-w on local datasets (7-day safety)
    cmds: [chmod -R a-w {{.ROOT}}/ml/datasets]
  migrate-cleanup:
    desc: Final delete of local datasets (run J+7 after verify)
    cmds: [rm -rf {{.ROOT}}/ml/datasets]
    prompt: "Sure ? This deletes the local datasets folder. Type yes."
```

## Critères d'acceptation

- [ ] Manifest généré pour 100 % des `image_assets.storage_key` non-null + tous les `source_images.storage_key`
- [ ] Upload : 100 % des fichiers du manifeste présents en MinIO avec sha256 match
- [ ] DB : 0 `storage_key` avec `/` en tête, 0 NULL
- [ ] Verify sample 5 % : 0 mismatch
- [ ] Code Eurio (API ML, scrape, training) tourne contre MinIO sans erreur pendant ≥ 24h
- [ ] Filesystem local en read-only après lock-fs
- [ ] Migration_log row inséré

## Gotchas

- **Idempotence cruciale** : le script doit pouvoir reprendre après interruption (Mac qui dort, réseau qui tombe). Stratégie : skip si `mc stat` existe + sha256 match. Sinon réupload.
- **Ordering** : si `image_assets.source_image_id` pointe vers une `source_image` dont l'image n'a pas encore été uploadée, c'est OK — la DB peut faire référence à un objet MinIO qui n'est pas encore visible. Mais il faut s'assurer qu'à la fin, **tout** est uploadé avant de marquer la migration sealed.
- **Chemins legacy** : si certains `storage_path` legacy contiennent des espaces, accents, etc., bien tester la roundtrip Path → key → URL.
- **Pas de retry infini** : si un fichier échoue 3 fois, on log et on continue. Rapport final liste les échecs. L'humain décide.
- **Si MinIO down pendant le upload** : le script s'arrête, repren­dre quand MinIO est back. NE PAS tenter de fallback filesystem.

## Procédure de rollback (si désastre)

Si dans les 7 jours qui suivent on découvre une catastrophe :

1. Le filesystem local est encore là (lecture seule).
2. Re-ré-écrire `storage_key` → chemin filesystem absolu via un petit script inverse.
3. `chmod -R u+w ml/datasets` pour relâcher le lock.
4. Continuer comme avant le J.

C'est la raison du délai 7 jours.

## Anti-objectifs

- ❌ Pas de migration "lente" (1 fichier/sec) — pool de workers en parallèle.
- ❌ Pas de mode dry-run mock-only. Le manifeste est réel + uploads réels (juste idempotents).
- ❌ Pas de double écriture pendant la migration. Le code n'écrit nulle part jusqu'à ce que la migration soit sealed.
- ❌ Pas de tentative de "sync continu" entre fs et MinIO post-migration. Hard cut.
