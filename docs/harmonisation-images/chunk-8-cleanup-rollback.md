# Chunk 8 — Cleanup + rollback procedures

> Documenter et automatiser : suppression définitive du filesystem
> local après le délai de safety, et procédures de rollback en cas
> de désastre. Pré-requis : chunks 3, 4, 5 livrés et stables.

## Objectif

À la fin du chunk :
- Procédure documentée pour supprimer `ml/datasets/` local après les 7 jours de safety.
- Procédure de rollback documentée + script si désastre découvert pendant le délai.
- Procédure d'orphan cleanup côté MinIO (objets sans ligne DB) automatisée.

## Composantes

### 8.1 Cleanup filesystem local (J+7 ou J+30)

Après chunk 3, le filesystem local `ml/datasets/` est en read-only pendant 7 jours (configurable). À J+7, si rien n'a explosé :

```bash
go-task ml:migrate-cleanup-local
```

Wraps :
```bash
# 1. Vérif : aucune ligne DB ne pointe vers fs absolu
sqlite3 ml/state/training.db \
  "SELECT COUNT(*) FROM image_assets WHERE storage_key LIKE '/%'"
# attendu : 0

# 2. Vérif : MinIO contient bien tout (sample 5%)
go-task ml:migrate-verify -- --sample-pct=5

# 3. Supprime le filesystem local
chmod -R u+w ml/datasets
rm -rf ml/datasets

# 4. Mark dans migrations_log
sqlite3 ml/state/training.db \
  "UPDATE migrations_log SET notes = 'fs cleanup done $(date)' WHERE name = 'fs_to_minio_2026_05'"
```

Avec un `prompt: yes` du go-task pour éviter les exécutions accidentelles.

### 8.2 Rollback complet (urgence)

Si dans les 7 jours après chunk 3 on découvre une catastrophe (corruption MinIO, perte de fichiers, etc.) et que le filesystem local existe encore :

```bash
go-task ml:migrate-rollback
```

Wraps un script `ml/scripts/migrate_rollback.py` qui :
1. Re-écrit en DB les `storage_key` legacy → chemins filesystem absolus
2. `chmod -R u+w ml/datasets` (relâche le lock read-only)
3. Marque dans `migrations_log` : `rolled_back_at = now()`
4. Le code Eurio repose sur fs comme avant.

Note importante : le rollback **n'efface pas MinIO**. Les buckets restent là, on peut re-tenter la migration plus tard une fois le bug fixé.

Pré-requis pour que le rollback marche :
- `ml/datasets/` encore présent et lisible
- Le manifeste `migration-manifest.jsonl` du chunk 3 a été conservé (il contient le mapping `storage_key` ↔ `fs_path`).

### 8.3 Orphan cleanup MinIO

Au fil du temps, des objets MinIO peuvent devenir orphelins (pas de ligne DB qui y réfère) :
- Asset rejected → supprimé en DB → fichier MinIO traîne
- Run cancelled mid-write → fichier uploadé mais ligne DB jamais commit
- Bug pipeline qui upload puis crash

Script mensuel `ml/scripts/orphan_cleanup.py` :

```python
def find_orphans(bucket: str, store: Store) -> list[str]:
    """Liste les keys MinIO qui n'ont pas de ligne DB correspondante."""
    minio_keys = set(_list_all_keys(bucket))
    db_keys = set(_list_db_keys_for_bucket(bucket, store))
    return list(minio_keys - db_keys)

def delete_orphans(bucket: str, keys: list[str], dry_run: bool = True):
    if dry_run:
        for k in keys: print(f"[DRY] would delete {bucket}/{k}")
        return
    # Délai de safety : ne supprime que les orphelins > 7 jours
    for k in keys:
        meta = _stat(bucket, k)
        if (now - meta.last_modified).days < 7: continue
        _delete(bucket, k)
```

Tâche go-task :
```yaml
ml:minio-orphans:list:
  cmds: [python -m ml.scripts.orphan_cleanup list]
ml:minio-orphans:delete:
  cmds: [python -m ml.scripts.orphan_cleanup delete --age-days=7]
  prompt: "Sure ?"
```

Pas de timer auto en V1 — on tourne à la main, on observe pendant 2-3 mois, on automatise quand on a confiance.

### 8.4 Vérif sha256 périodique (drift detection)

Une fois par mois :

```bash
go-task ml:minio-verify -- --sample-pct=2
```

Tire 2% des `image_assets`, recompute sha256 du contenu MinIO, compare avec `image_assets.sha256` (déjà en DB selon schéma). Si mismatch → alerte ntfy.sh comme pour le backup.

C'est le filet de sécurité contre la corruption silencieuse côté MinIO ou pCloud.

## Critères d'acceptation

- [ ] `go-task ml:migrate-cleanup-local` testé en dry-run, supprime bien `ml/datasets/` quand confirmé
- [ ] `go-task ml:migrate-rollback` documenté + script écrit (mais pas exécuté tant que pas de désastre)
- [ ] `go-task ml:minio-orphans:list` retourne 0 orphelins juste après chunk 3
- [ ] `go-task ml:minio-verify -- --sample-pct=2` passe sans mismatch

## Gotchas

- **Filesystem fantôme** : sur Mac, parfois `rm -rf` ne libère pas l'espace disque immédiatement (Time Machine snapshots). Si le disque reste plein, `tmutil deletelocalsnapshots /`.
- **Manifest persistance** : le `migration-manifest.jsonl` du chunk 3 doit être versionné (commit dans git, ~1 MB). C'est le seul moyen de rollback proprement.
- **Rollback partiel** : si on rollback une fois mais qu'on re-tente la migration ensuite, le DB doit être ré-aligné. Le script `migrate_to_minio.py upload` est idempotent → re-tourner le pipeline complet (inventory → upload → seal-db) est safe.
- **Orphan cleanup et race condition** : si une pipeline upload un fichier puis prend 30s pour commit la ligne DB, et qu'on tourne `orphan_cleanup` entre les deux, on supprime un fichier valide. Le délai 7j de safety couvre largement ce cas.

## Anti-objectifs

- ❌ Pas d'auto-cleanup orphelins en V1. On observe d'abord.
- ❌ Pas de rollback "hot" (sans interruption). Si on rollback, on stoppe les pipelines, on re-écrit la DB, on relance.
- ❌ Pas de "soft delete" en MinIO. Quand on supprime, c'est définitif (la rétention est aux snapshots pCloud).
- ❌ Pas de vérification 100% sha256 à chaque cleanup — sample 2 %. Au-delà ça coûte trop cher en bande passante VPS.

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
- `feedback_chunk_audit_flow` — chunk 8 ne ferme la boucle que quand 4 et 5 sont stables
