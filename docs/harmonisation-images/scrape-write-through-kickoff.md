# Scrape write-through MinIO — kickoff (handover)

> Destiné à la prochaine session Claude Code. Self-contained : contexte
> minimal + plan d'attaque + repères techniques. Rédigé 2026-05-16 post
> SS-0 wipe.

---

## 1. Pourquoi

Aujourd'hui, le scrape eBay (et tous les autres adaptateurs dans
`ml/sources/<src>/`) écrit dans le filesystem local
(`ml/state/sources/<src>/...`). MinIO n'est touché que par le batch
one-shot `scripts/migrate_to_minio.py`, qui est désormais utilisé en
**outil utility** uniquement (récup d'urgence).

Conséquence du statu quo : un scrape lancé sur Mac/PC/VPS ne pousse
PAS automatiquement dans MinIO. Risque de perte (panne disque, oubli
de batch), pas de partage cross-machine, contraire à la vision
`docs/harmonisation-images/vision.md`.

**Objectif** : tout scrape future écrit directement dans MinIO
(buckets `enrichment-raws` et `enrichment-crops`) avec
`storage_path = S3 key` (pas FS path).

## 2. État au démarrage (post SS-0)

| Élément | État |
|---|---|
| `ml/state/training.db` tables scrape | wipées (6657 rows DELETE) |
| `ml/state/sources/` | rm -rf (407 MB supprimés) |
| Référentiel coins Supabase | 656 coins 2€ × 25 pays (post refetch) |
| Anciens eurio_ids dans MinIO | aucun (jamais migré batch) |
| MinIO VPS | up, buckets `numista-canonical` / `enrichment-raws` / `enrichment-crops` |
| `migrate_to_minio.py` | à marquer DEPRECATED mais conserver |
| Bloc B TODO-handover.md (rsync Mac→VPS) | **annulé** — plus de legacy à migrer |
| Bloc A TODO-handover.md (NixOS + pCloud) | toujours pertinent, séparé |

## 3. Décisions actées (utilisateur, 2026-05-16)

1. **Scope** : Phase 1+2 refacto complet — `storage_path` devient S3 key partout, downstream consumers passent via `local_path(bucket, key)` read-through cache.
2. **Locations scrape** : Mac, PC, VPS (potentiellement cron). MinIO accessible via `eurio-s3.musubi.dev`.
3. **MinIO down pendant scrape** : block-until-reconnect (retry exponential backoff). Pas de fallback FS path.
4. **Vieux scrapes locaux** : wipe complet (déjà fait en SS-0). On repart greenfield.
5. **migrate_to_minio.py** : DEPRECATED tag, garder comme utility récup.

## 4. Plan en 5 chunks (SS-0 done, SS-1..SS-4 todo)

| Chunk | Description | Durée |
|---|---|---:|
| ✅ **SS-0** | Wipe SQLite scrape tables + state/sources/ (6657 rows + 407 MB) | done 2026-05-16 |
| ✅ **SS-1** | Write-through : download.py + detect_crop.py + dedup.py + storage.py | done 2026-05-16 |
| ✅ **SS-2** | Read-through : detect_crop (raws) + auto_validate + api/sources_routes + api/review_queue_routes | done 2026-05-16 |
| **SS-3** | Tests + DEPRECATED migrate_to_minio.py + Taskfile + docs | ~2h |
| **SS-4** | Live test mini eBay scrape | ~30min |

### Fichiers modifiés (SS-1 + SS-2)

| Fichier | Change |
|---|---|
| `ml/storage/local_cache.py` | + `cache_path_for(bucket, key)`, `upload_through(bucket, key, data, block_on_disconnect=True)` avec retry exponential 17 min |
| `ml/sources/_base/storage.py` | Rewrite : suppression `raw_path/crop_path/storage_root/write_atomic` (FS), ajout `raw_key/crop_key/raw_cache_path/crop_cache_path/bucket_for_raws/bucket_for_crops` |
| `ml/sources/_base/dedup.py` | `ImageAssetRow.id` new field (pre-generated uuid for write-through) |
| `ml/sources/_base/steps/download.py` | Réécriture : adapter écrit en cache → upload_through MinIO → storage_path = S3 key + storage_status='present' |
| `ml/sources/_base/steps/detect_crop.py` | Read raws via `local_path("enrichment-raws", key)`. Write crops via cache + upload_through. Pre-gen asset_id pour storage_key. UPDATE storage_status='present' post-upsert |
| `ml/sources/_base/steps/auto_validate.py` | Read crops via `local_path("enrichment-crops", key)` |
| `ml/api/sources_routes.py` | `/sources/.../assets/.../file` et `/sources/.../raws/.../file` → local_path() au lieu de FileResponse(Path) |
| `ml/api/review_queue_routes.py` | `_compute_detections` lit raw via local_path() |
| `ml/scripts/recrop_ebay_orphans.py` | `_cleanup_orphan_crop_files` → DEPRECATED stub (cascade_sync audit handles MinIO orphans) |

## 5. Architecture cible

### 5.1 — Storage keys (pure strings, pas Path)

```python
# ml/sources/_base/storage.py — refactored
def raw_key(source: str, run_id: str, source_image_id: str, ext: str = "jpg") -> str:
    """S3 key for an enrichment-raws object."""
    return f"{source}/{run_id}/{source_image_id}.{ext}"

def crop_key(source: str, run_id: str, asset_id: str) -> str:
    """S3 key for an enrichment-crops object."""
    return f"{source}/{run_id}/{asset_id}.png"
```

Aucune notion de FS path dans le module — `local_path()` du cache se
charge de la résolution disque.

### 5.2 — Write-through helper (nouveau)

À ajouter dans `ml/storage/local_cache.py` :

```python
def upload_through(bucket: Bucket, storage_key: str, data: bytes,
                   *, block_on_disconnect: bool = True) -> Path:
    """Save bytes to cache AND upload to MinIO.

    1. Write to local cache path = local_path target.
    2. Upload to MinIO with retry backoff if block_on_disconnect.
    3. Return the cache Path (already populated for immediate downstream use).

    Raises only after exponential backoff exhausts (or if block_on_disconnect=False
    and the first attempt fails).
    """
    # ... boto3 put_object + retry loop ...
```

### 5.3 — Adapter contract

Garder `download_raw(item, dest: Path)` mais `dest` est désormais le
chemin **cache local** (pas state/sources). Adapter écrit là, framework
upload ensuite.

```python
# Step run_download (refactored)
key = raw_key(source, run_id, sid, ext)
cache_path = local_cache._cache_root() / "enrichment-raws" / key
cache_path.parent.mkdir(parents=True, exist_ok=True)
res = adapter.download_raw(item, cache_path)   # adapter writes to cache
upload_through("enrichment-raws", key, cache_path.read_bytes())  # push S3

UPDATE source_images SET
    storage_path = key,           # S3 key, not FS path
    storage_status = 'present',
    sha256=..., bytes=..., width=..., height=...
WHERE id = sid;
```

### 5.4 — Read-through pour downstream

Tous les `Path(storage_path)` actuels doivent devenir
`local_path(bucket, storage_path)` :

| Fichier | Lignes à toucher |
|---|---|
| `ml/sources/_base/steps/detect_crop.py` | 89, 119–120 |
| `ml/sources/_base/steps/auto_validate.py` | 359 |
| `ml/api/coin_assets_routes.py` | grep storage_path |
| `ml/api/review_queue_routes.py` | idem |
| `ml/api/sources_routes.py` | idem |
| `ml/scripts/recrop_ebay_orphans.py` | 72, 75, 77 |
| `ml/scripts/cascade_sync.py` | déjà OK (manipule juste les strings) |

### 5.5 — Detect_crop write side

```python
# Avant : crop_p = crop_path(source_id, source_ref, crop_index)
# Après :
asset_id = generate_asset_id()  # pré-allouer pour la S3 key
key = crop_key(source_id, run.run_id, asset_id)
cache_path = local_cache._cache_root() / "enrichment-crops" / key
cv2.imwrite(str(cache_path), result.image)
upload_through("enrichment-crops", key, cache_path.read_bytes())

# DB : image_assets.storage_path = key, storage_status = 'present'
```

⚠️ Subtilité : aujourd'hui `image_assets.id` est généré par `upsert_image_asset`
(uuid v7). Pour faire un S3 key qui inclut l'asset_id, soit on génère
l'id côté code AVANT upsert, soit on stocke le path après l'insert (mais
ça nécessite un UPDATE post-upsert qui complique l'idempotence). Plan :
générer l'asset_id côté code.

## 6. Block-until-reconnect (MinIO down)

Logique :

```python
import time
def upload_with_retry(bucket, key, data, max_attempts=8):
    delays = [2, 5, 15, 30, 60, 120, 300, 600]   # 17 minutes total
    for attempt, delay in enumerate(delays[:max_attempts], 1):
        try:
            _client().put_object(Bucket=bucket, Key=key, Body=data)
            return
        except (BotoCoreError, ClientError) as e:
            if attempt == max_attempts:
                raise
            logger.warning(f"MinIO upload retry {attempt}/{max_attempts} in {delay}s: {e}")
            time.sleep(delay)
```

17 minutes de retry suffisent pour un VPS reboot. Au-delà, on stoppe
le scrape (RuntimeError → l'orchestrateur le note dans
`source_runs.error_summary`).

## 7. Tests à mettre à jour

- `tests/test_ebay_adapter.py` — adapter contract reste à peu près le
  même (download_raw écrit sur disque), mais sample `dest` doit
  pointer vers le cache mock.
- `tests/test_orchestrator.py` — orchestrateur dummy doit injecter
  un MinIO mock (boto stubber ou moto).
- `tests/test_storage_cascade.py` — vérifier que `storage_path` est
  bien une S3 key, pas un FS path absolu.
- Nouveau `tests/test_upload_through.py` — couvre block-until-reconnect.

## 8. Critères de fin

- [ ] Lancement `ml:src:ebay -- --eurio-id fr-2025-2eur-...` sur Mac
      → tous les raws sont dans `enrichment-raws` bucket MinIO
      → tous les crops dans `enrichment-crops`
- [ ] DB rows `source_images.storage_path` matchent les S3 keys
- [ ] Aucun fichier dans `ml/state/sources/` (le répertoire n'existe
      même plus)
- [ ] Cache local sous `~/.cache/eurio/enrichment-raws/...` rempli
      pendant le scrape (read-through downstream)
- [ ] Coupure MinIO en plein scrape → retry block → reprise quand
      MinIO revient
- [ ] `migrate_to_minio.py` modifié pour afficher un banner DEPRECATED
      au lancement (mais fonctionnel)
- [ ] `tests/` passent (pytest -v ml/tests/)

## 9. Points de vigilance

- **Adapter Mock** (`ml/sources/_mock/adapter.py`) — utilisé par les
  tests, doit aussi être migré (pas de S3 réel — peut bypasser
  upload via flag test, ou utiliser moto).
- **API admin** (`ml/api/coin_assets_routes.py` et siblings) — la
  vue admin web doit afficher les crops. Aujourd'hui elle sert le
  fichier local. Demain → presigned URL via `signed_url(bucket, key)`.
- **`ml/scripts/recrop_ebay_orphans.py`** — script utilitaire de
  cleanup, manipule les fichiers FS. Sera à adapter ou retirer.
- **Performance** : chaque scrape = N appels `put_object` synchrones.
  Pour 1000 listings (raw+crop) = 2000 calls. À ~50ms RTT vers VPS,
  ~100s overhead. Acceptable mais possibilité d'optimiser via batch
  upload (ThreadPoolExecutor, 16 workers comme migrate_to_minio).

## 10. Référentiel (pour la session reprise)

- Vision : `docs/harmonisation-images/vision.md`
- Read-through cache : `docs/harmonisation-images/chunk-4-local-cache.md`
- Schéma keys : `docs/harmonisation-images/chunk-2-image-keys-schema.md`
- Cascade : `docs/harmonisation-images/chunk-9-cascade-sync.md`
- Migration batch (DEPRECATED) : `docs/harmonisation-images/chunk-3-migration-script.md`
- TODO infra annexe : `docs/harmonisation-images/TODO-handover.md`
  (bloc A toujours valide, bloc B annulé)

## 11. Numista refetch (pour contexte)

La session précédente a regen le référentiel 2€ propre :
- 656 coins / 25 pays / 3308 mint_releases / 7000 prices
- 28 variants en `needs_review` (à traiter dans UI admin)
- Voir `docs/research/numista-clean-refetch-progress.md`

Le scrape eBay relancé après SS-4 doit ciblera les nouveaux eurio_ids
post-refetch (les anciens slugs sont morts).

---

*Bon courage. Si quelque chose dans ce doc s'avère faux pendant
l'implémentation, mettre à jour ce fichier en priorité avant de
coder — il sera relu par toutes les sessions futures.*
