# Chunk 9 — Cascade sync MinIO ↔ DB ↔ cache

> Si on supprime un objet côté MinIO (admin GUI, `mc rm`, expiration
> manuelle), la suppression doit se propager : la row DB pointant vers
> l'objet est marquée orpheline, et le fichier copié dans le cache local
> est purgé. Symétrique : si une row DB est supprimée par l'admin, on
> supprime aussi l'objet MinIO et le fichier cache.
>
> Ajouté hors plan initial : la doc d'origine ne couvrait que
> `orphan_cleanup` côté MinIO (objets sans DB), pas le sens DB → manquant
> côté MinIO ni l'invalidation cache. Ce chunk ferme la boucle.

## Pourquoi ce chunk

Vision §"Architecture cible" pose MinIO comme source de vérité dev.
Mais en pratique, **trois couches** doivent rester cohérentes :

1. **MinIO** (source de vérité)
2. **SQLite DB** (`storage_path` = clé S3)
3. **Cache local** (`~/.cache/eurio/<bucket>/<key>` — Mac admin et runs PC)

Sans cascade, chaque suppression hors-bande crée un état incohérent :

| Action utilisateur | Sans cascade | Avec cascade |
|---|---|---|
| `mc rm enrichment-crops/ebay/<rid>/<aid>.png` | row DB pointe dans le vide → 404 silencieux à l'accès, debug pénible | row DB marquée `missing_in_storage`, cache local purgé |
| Admin clique "supprimer" sur un asset dans `/review` | DELETE de row + DELETE objet MinIO + purge cache | idem (déjà géré côté admin si on le code une fois proprement) |
| Cache stale après une overwrite MinIO | training utilise une vieille copie | cache invalidé par sha256 mismatch |

L'utilisateur a explicité (session 2026-05-15) qu'il ne *prévoit* pas
de supprimer depuis MinIO directement (tout passera par l'admin), mais
qu'il veut une garantie de cohérence quoi qu'il arrive.

## Objectif

À la fin du chunk :

1. Une nouvelle colonne `storage_status` existe sur `image_assets` et
   `source_images` (`'present' | 'missing_in_storage' | 'removed_via_admin'`).
2. `local_cache.local_path()` traite les 404 MinIO en :
   - purgeant la copie cache locale (si présente)
   - marquant la row DB `storage_status='missing_in_storage'`
     (`storage_path` reste inchangé pour l'audit)
   - levant `FileNotFoundError` (pas de fallback)
3. Un script `ml/scripts/cascade_sync.py` audite périodiquement la
   parité MinIO ↔ DB et applique les diffs.
4. Le pipeline scrape (`download.py`, `detect_crop.py`) écrit
   directement dans MinIO **et** met à jour la DB dans la même
   transaction logique (idempotence par sha256).
5. La fonction `delete_asset(asset_id)` exposée à l'admin :
   `DELETE objet MinIO + UPDATE storage_status='removed_via_admin' +
   storage_path=NULL + purge cache`.

## Décisions actées

1. **Marquer plutôt que DELETE** : on garde la row et on positionne un
   statut. La colonne `storage_path` est **laissée intacte** (la
   "dernière clé S3 connue") pour l'audit. SQLite ne supporte pas
   trivialement `ALTER COLUMN ... DROP NOT NULL` sur `image_assets`,
   et la sémantique "clé connue mais objet absent" est plus utile que
   "clé NULL" pour debug. Le code lecteur doit checker
   `storage_status = 'present'` avant d'utiliser `storage_path`.
2. **Statut `removed_via_admin` distinct de `missing_in_storage`** : le
   premier est intentionnel, le second est un drift à investiguer.
   `cascade_sync` ne doit *jamais* "réparer" un `removed_via_admin`.
3. **Cache local invalidé sur 404 ou sha256 mismatch**, pas via TTL.
   Un objet présent en cache et présent en MinIO avec le même sha256
   reste indéfiniment valide (jusqu'à éviction LRU).
4. **`cascade_sync` est manuel, pas auto** en V1. Cron envisagé V2
   après 2-3 mois d'observation (cf chunk 8 §8.3).
5. **Pas de webhook MinIO bucket notification**. Trop d'infra pour
   le bénéfice. La cascade réactive (sur 404) couvre le cas online ;
   le sync périodique couvre les drifts silencieux.
6. **Cascade côté pipeline scrape** : si `upload_file` MinIO réussit
   mais le commit DB échoue → orphelin côté MinIO, capturé par
   `orphan_cleanup` (chunk 8). L'inverse (commit DB OK, upload KO) est
   évité par l'ordre : upload d'abord, puis commit.

## Schéma DB

Migration ajoutée par `ml/scripts/cascade_sync.py migrate-schema` :

```sql
ALTER TABLE image_assets
  ADD COLUMN storage_status TEXT NOT NULL DEFAULT 'present'
  CHECK (storage_status IN ('present', 'missing_in_storage', 'removed_via_admin'));

ALTER TABLE source_images
  ADD COLUMN storage_status TEXT NOT NULL DEFAULT 'present'
  CHECK (storage_status IN ('present', 'missing_in_storage', 'removed_via_admin'));

CREATE INDEX IF NOT EXISTS idx_image_assets_storage_status
  ON image_assets(storage_status) WHERE storage_status != 'present';

CREATE INDEX IF NOT EXISTS idx_source_images_storage_status
  ON source_images(storage_status) WHERE storage_status != 'present';
```

Les indexes partiels accélèrent les listings d'orphelins sans coûter
sur le 99 % de rows `present`.

## Implémentation

### 9.1 Hook 404 dans `local_cache.local_path()`

Modification de `ml/storage/local_cache.py` :

```python
from botocore.exceptions import ClientError

def local_path(bucket: Bucket, storage_key: str) -> Path:
    target = _cache_root() / bucket / storage_key
    if target.exists():
        os.utime(target, (time.time(), target.stat().st_mtime))
        return target

    if _max_gb() > 0:
        _evict_if_needed()

    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(target.suffix + ".tmp")
    try:
        _client().download_file(bucket, storage_key, str(tmp))
    except ClientError as e:
        tmp.unlink(missing_ok=True)
        if e.response["Error"]["Code"] in ("404", "NoSuchKey", "NotFound"):
            # MinIO confirms the object no longer exists.
            # Cascade: mark the DB row + nothing else to purge from cache
            # (we never wrote it).
            _mark_missing_in_storage(bucket, storage_key)
        raise FileNotFoundError(
            f"{bucket}/{storage_key} not found in MinIO: {e}"
        ) from e
    except Exception as e:
        tmp.unlink(missing_ok=True)
        # Network errors etc. — do NOT mark missing (transient).
        raise FileNotFoundError(
            f"Cannot fetch {bucket}/{storage_key}: {e}"
        ) from e
    os.replace(tmp, target)
    return target


def _mark_missing_in_storage(bucket: Bucket, storage_key: str) -> None:
    """Update DB row(s) whose storage_path equals this S3 key.

    Best-effort — if DB unreachable, log and continue (the FileNotFoundError
    is the user-visible signal). The next `cascade_sync audit` will catch up.
    """
    import logging, sqlite3
    from pathlib import Path
    db_path = Path(__file__).resolve().parents[1] / "state" / "training.db"
    if not db_path.exists():
        return
    try:
        conn = sqlite3.connect(str(db_path), timeout=2.0)
        with conn:
            for table in ("image_assets", "source_images"):
                conn.execute(
                    f"""UPDATE {table}
                          SET storage_status = 'missing_in_storage',
                              storage_path = NULL
                        WHERE storage_path = ?
                          AND storage_status = 'present'""",
                    (storage_key,),
                )
        conn.close()
    except Exception:  # noqa: BLE001
        logging.warning(
            "Failed to mark %s/%s as missing_in_storage", bucket, storage_key,
            exc_info=True,
        )
```

### 9.2 Suppression côté admin — `delete_asset(asset_id)`

Nouvelle fonction utilitaire dans `ml/storage/__init__.py` :

```python
def delete_asset_cascade(
    bucket: Bucket,
    storage_key: str,
    table: str,        # "image_assets" | "source_images"
    row_id: str,
    *,
    reason: str = "removed_via_admin",
) -> None:
    """Delete from MinIO + cache + mark row.

    Idempotent: if the object is already gone from MinIO, no error.
    The row is marked even if MinIO deletion fails (the next sync will
    repair if needed).
    """
    import sqlite3
    from pathlib import Path
    from . import local_cache

    # 1. Delete from MinIO (idempotent — MinIO returns 204 even if absent).
    try:
        _client().delete_object(Bucket=bucket, Key=storage_key)
    except Exception:  # noqa: BLE001
        # Don't swallow but don't block: the periodic sync catches orphans.
        import logging
        logging.warning("MinIO delete failed for %s/%s", bucket, storage_key,
                        exc_info=True)

    # 2. Purge cache copy if present.
    cached = local_cache._cache_root() / bucket / storage_key
    if cached.exists():
        cached.unlink(missing_ok=True)

    # 3. Mark row.
    db_path = Path(__file__).resolve().parents[1] / "state" / "training.db"
    conn = sqlite3.connect(str(db_path))
    with conn:
        conn.execute(
            f"""UPDATE {table}
                  SET storage_status = ?,
                      storage_path = NULL
                WHERE id = ?""",
            (reason, row_id),
        )
    conn.close()
```

L'API admin (`ml/api/sources_routes.py` route DELETE asset, à
implémenter quand l'UI le demande) appelle cette fonction.

### 9.3 Script `cascade_sync.py` (audit + repair périodique)

`ml/scripts/cascade_sync.py` :

```bash
python -m scripts.cascade_sync migrate-schema   # ajout des colonnes
python -m scripts.cascade_sync audit            # liste les drifts (read-only)
python -m scripts.cascade_sync repair           # applique les corrections
python -m scripts.cascade_sync purge-cache      # purge cache files dont sha256 ne matche plus MinIO
```

Sous-commandes :

- **`migrate-schema`** : ajoute la colonne `storage_status` (idempotent)
- **`audit`** : pour chaque bucket, liste :
  - `db_rows_missing_in_minio` : rows avec `storage_status='present'`
    mais `head_object` retourne 404 → à marquer
  - `minio_objects_missing_in_db` : objets MinIO sans row DB (alias
    de l'orphan_cleanup chunk 8.3 — on l'inclut ici pour avoir une
    seule commande qui fait le check des deux sens)
  - `cache_files_stale` : fichiers dans `~/.cache/eurio/` dont le
    sha256 ne matche pas le `Metadata.sha256` MinIO → à purger
- **`repair`** : applique les marquages (NULL + status) côté DB + purge
  cache. **Ne supprime pas les objets MinIO orphelins** (ça reste
  manuel via chunk 8.3, sécurité).
- **`purge-cache`** : sous-commande dédiée pour le LRU forcé sans
  toucher la DB

Exemple sortie audit :

```
== Bucket: enrichment-crops ==
  DB rows missing in MinIO   :   3
    image_assets uuid-abc... → ebay/run-x/uuid-abc.png
    image_assets uuid-def... → ebay/run-y/uuid-def.png
    image_assets uuid-ghi... → catawiki/run-z/uuid-ghi.png
  MinIO objects missing in DB:   1
    catawiki/run-orphan/uuid-jkl.png  (uploaded 2026-05-10, age 5d)
  Cache files stale          :   0

Run with `repair` to mark the 3 DB rows as missing_in_storage and purge stale cache.
MinIO orphans not touched (use `ml:minio-orphans:delete` after manual review).
```

### 9.4 Wiring tasks

```yaml
# Taskfile.yml (ml/) — section "Local cache"
cascade-sync:migrate:
  desc: "Ajoute les colonnes storage_status (one-shot, idempotent)."
  cmds:
    - "{{.VENV}}/python -m scripts.cascade_sync migrate-schema"

cascade-sync:audit:
  desc: "Liste les drifts MinIO ↔ DB ↔ cache (read-only)."
  cmds:
    - "{{.VENV}}/python -m scripts.cascade_sync audit {{.CLI_ARGS}}"

cascade-sync:repair:
  desc: "Applique les marquages 'missing_in_storage' + purge cache stale."
  prompt: "This will mark DB rows as missing and purge cache. Continue?"
  cmds:
    - "{{.VENV}}/python -m scripts.cascade_sync repair {{.CLI_ARGS}}"
```

## Critères d'acceptation

- [ ] Colonnes `storage_status` créées sur les 2 tables, default `'present'`
- [ ] `local_path()` testé contre une clé absente : marque la row,
      laisse FileNotFoundError remonter
- [ ] `delete_asset_cascade()` testé : MinIO down → marque row quand
      même, log warning
- [ ] `cascade_sync audit` retourne `0/0/0` sur un état nominal post-migration
- [ ] `cascade_sync repair` est idempotent (un 2e run ne change rien)
- [ ] Documentation : `infra/minio/README.md` mentionne `cascade_sync`
      dans la section ops

## Gotchas

- **Race condition `local_path` ↔ `repair`** : si un client lit pendant
  qu'un repair tourne, la row peut être NULL juste avant qu'on lise
  `storage_path`. Acceptable — le `local_path` rate, l'utilisateur
  retry, voit l'état cohérent.
- **`_mark_missing_in_storage` en parallèle** : 2 process qui tapent
  la même row → SQLite serializing avec timeout 2s. Si conflit, log
  et passe. Pas critique : un sync ultérieur rattrape.
- **DB path hardcodé** : `_mark_missing_in_storage` calcule
  `parents[1]/state/training.db`. Si la DB déménage, à mettre à jour.
  Pas de config externe en V1 (pas besoin).
- **Statut `removed_via_admin` jamais "annulé"** : si un opérateur
  veut ré-uploader un asset supprimé, il faut faire une nouvelle row
  (la suppression admin est sémantiquement définitive). Les rows
  marquées sont gardées pour l'audit, pas pour le rollback.

## Anti-objectifs

- ❌ Pas de webhook MinIO bucket notification.
- ❌ Pas de cron auto sur `cascade_sync repair` en V1. Manuel, observation.
- ❌ Pas de "self-heal" qui ré-upload un objet manquant depuis le fs
  legacy (qui sera supprimé au chunk 8 de toute façon).
- ❌ Pas de DELETE de row côté DB. Toujours NULL + statut.
- ❌ Pas de TTL sur le cache. Invalidation par 404 ou sha256 mismatch
  uniquement.

## Mémoires liées

- `feedback_no_debt` — pas de fallback silencieux, on throw + on marque
- `project_eurio_stack` — la cascade renforce la cohérence dev sans
  toucher la chaîne prod (Supabase Storage)
