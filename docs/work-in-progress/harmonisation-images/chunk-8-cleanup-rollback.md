# Chunk 8 — Cleanup + rollback

> Documenter et automatiser : suppression définitive du filesystem
> local + colonne `storage_path_legacy` après le délai de safety, et
> procédure de rollback. Pré-requis : chunks 3, 4, 5 livrés et stables.

## Objectif

À la fin du chunk :

- Procédure documentée pour supprimer les dossiers locaux après les 7 jours de safety.
- Procédure de rollback documentée + script si désastre découvert pendant le délai.
- Procédure d'orphan cleanup côté MinIO (objets sans ligne DB).
- Vérif sha256 périodique (drift detection).

## Composantes

### 8.1 Cleanup filesystem local (J+7)

Après chunk 3, les dossiers source sont en read-only pendant 7 jours. À J+7, si rien n'a explosé :

```bash
go-task ml:migrate-cleanup-local
```

Wraps :

```bash
# 1. Vérif : aucune ligne DB ne pointe vers fs absolu
sqlite3 ml/state/training.db <<EOF
SELECT COUNT(*) FROM image_assets   WHERE storage_path LIKE '/%';
SELECT COUNT(*) FROM source_images  WHERE storage_path LIKE '/%';
EOF
# attendu : 0, 0

# 2. Vérif : MinIO contient bien tout (sample 5%)
go-task ml:migrate-verify -- --sample-pct=5

# 3. Drop la colonne legacy
sqlite3 ml/state/training.db <<EOF
ALTER TABLE image_assets   DROP COLUMN storage_path_legacy;
ALTER TABLE source_images  DROP COLUMN storage_path_legacy;
EOF

# 4. Supprime le filesystem local
chmod -R u+w ml/datasets ml/state/sources
rm -rf ml/datasets ml/state/sources/*/raw ml/state/sources/*/crops

# 5. Mark dans migrations_log
sqlite3 ml/state/training.db \
  "UPDATE migrations_log SET notes = 'fs cleanup done $(date -u +%FT%TZ)' \
   WHERE name = 'fs_to_minio_2026_05'"
```

Avec `prompt: yes` du go-task pour éviter les exécutions accidentelles.

### 8.2 Rollback complet (urgence ≤ J+7)

Si dans les 7 jours après chunk 3 on découvre une catastrophe et que `storage_path_legacy` + filesystem sont encore là :

```bash
go-task ml:migrate-rollback
```

Wraps :

```sql
BEGIN;
UPDATE image_assets   SET storage_path = storage_path_legacy
  WHERE storage_path_legacy IS NOT NULL;
UPDATE source_images  SET storage_path = storage_path_legacy
  WHERE storage_path_legacy IS NOT NULL;
UPDATE migrations_log SET notes = 'rolled back at ' || datetime('now')
  WHERE name = 'fs_to_minio_2026_05';
COMMIT;
```

Puis :

```bash
chmod -R u+w ml/datasets ml/state/sources
```

Le code Eurio repose à nouveau sur fs comme avant. **MinIO reste intact** — on peut re-tenter la migration plus tard une fois le bug fixé.

Pré-requis pour que le rollback marche :
- `ml/datasets/` + `ml/state/sources/` encore présents et lisibles
- `storage_path_legacy` non drop
- Manifest `migration-manifest.jsonl` conservé (commit dans git, sert de vérif)

### 8.3 Orphan cleanup MinIO

Au fil du temps, des objets MinIO peuvent devenir orphelins :
- Asset rejected → DELETE en DB → fichier MinIO traîne
- Run cancelled mid-write
- Bug pipeline qui upload puis crash

Script `ml/scripts/orphan_cleanup.py` :

```python
def find_orphans(bucket: str, store) -> list[str]:
    minio_keys = set(_list_all_keys(bucket))
    db_keys = set(_list_db_keys_for_bucket(bucket, store))
    return list(minio_keys - db_keys)

def delete_orphans(bucket: str, keys: list[str], dry_run: bool = True, age_days: int = 7):
    for k in keys:
        meta = _stat(bucket, k)
        if (datetime.utcnow() - meta.last_modified).days < age_days:
            continue   # safety : ne supprime pas les jeunes
        if dry_run:
            print(f"[DRY] would delete {bucket}/{k}")
        else:
            _delete(bucket, k)
```

```yaml
ml:minio-orphans:list:
  cmds: [python -m ml.scripts.orphan_cleanup list]
ml:minio-orphans:delete:
  cmds: [python -m ml.scripts.orphan_cleanup delete --age-days=7]
  prompt: "Sure ?"
```

Pas de timer auto V1. On tourne à la main, on observe 2-3 mois, on automatise quand on a confiance.

### 8.4 Vérif sha256 périodique (drift detection)

Une fois par mois :

```bash
go-task ml:minio-verify -- --sample-pct=2
```

Tire 2 % des `image_assets`, recompute sha256 du contenu MinIO, compare avec `image_assets.sha256` (déjà en DB selon schéma). Si mismatch → alerte ntfy.sh.

C'est le filet de sécurité contre la corruption silencieuse côté MinIO ou pCloud restore.

## Critères d'acceptation

- [ ] `ml:migrate-cleanup-local` testé en dry-run, supprime bien dossiers source quand confirmé, drop la colonne legacy
- [ ] `ml:migrate-rollback` documenté + script écrit (pas exécuté tant que pas de désastre)
- [ ] `ml:minio-orphans:list` retourne 0 orphelins juste après chunk 3
- [ ] `ml:minio-verify --sample-pct=2` passe sans mismatch

## Gotchas

- **Filesystem fantôme Mac** : `rm -rf` peut ne pas libérer l'espace immédiatement (Time Machine snapshots). Si le disque reste plein : `tmutil deletelocalsnapshots /`.
- **Manifest persistance** : `migration-manifest.jsonl` doit rester commité dans `docs/harmonisation-images/`. C'est la trace historique de la migration et le double check du rollback.
- **Rollback partiel** : si on rollback puis re-migre plus tard, le pipeline complet (inventory → upload → db) est idempotent → safe à re-tourner.
- **Orphan cleanup race condition** : si une pipeline upload puis prend 30 s pour commit la ligne DB, et qu'on tourne `orphan_cleanup` entre les deux, on supprime un fichier valide. Le `--age-days=7` couvre largement ce cas.

## Anti-objectifs

- ❌ Pas d'auto-cleanup orphelins en V1.
- ❌ Pas de rollback "hot" (sans interruption). Si rollback : stop pipelines, ré-écrit DB, relance.
- ❌ Pas de "soft delete" en MinIO. Suppression définitive (la rétention est dans le tar pCloud).
- ❌ Pas de vérification 100 % sha256 à chaque cleanup. Sample 2 %.

## Quand exécuter les procédures

| Procédure | Trigger | Fréquence |
|---|---|---|
| `migrate-cleanup-local` | J+7 après chunk 3, audit OK | One-shot |
| `migrate-rollback` | Désastre découvert ≤ J+7 | Si désastre |
| `minio-orphans:list` | Manuel | Mensuel |
| `minio-orphans:delete` | Après revue de la liste | Mensuel après 2-3 mois d'observation |
| `minio-verify` | Manuel ou cron mensuel | Mensuel |

## Mémoires liées

- `feedback_no_debt` — pas de soft migration, hard cut puis cleanup ferme
- `feedback_chunk_audit_flow` — chunk 8 ferme la boucle quand 4 et 5 sont stables
