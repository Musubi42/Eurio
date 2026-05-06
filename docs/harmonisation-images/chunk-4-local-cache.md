# Chunk 4 — Cache local read-through (lib commune)

> Le code applicatif n'appelle jamais MinIO directement. Il appelle
> `local_path(bucket, storage_key)` qui télécharge à la demande dans un
> cache local et retourne un path filesystem. Une seule lib partagée
> Mac admin + PC training. Pré-requis : chunk 3 livré.

## Objectif

À la fin du chunk :

- Module `ml/storage/local_cache.py` expose `local_path(bucket, storage_key) -> Path`.
- Sur **Mac** : LRU borné 5 GB (`EURIO_CACHE_MAX_GB=5`), eviction par `os.atime`.
- Sur **PC training** : pas de borne par défaut, mais cache scoped par `run_id` géré au-dessus (chunk 5 wire ce comportement par-dessus la même lib).
- L'API ML (`/sources/.../assets/.../file`) répond `302 → signed URL` pour le browser admin.
- Tests unitaires : eviction quand cache > max, atime updated on hit, throw si MinIO down.

## Architecture

```
Application code (training, admin scripts, API ML proxy)
        │
        │  local_path(bucket, key) → Path
        ▼
┌─ ml/storage/local_cache.py ─────────────┐
│  if exists(cache_dir/bucket/key):       │
│      touch atime → return path          │
│  else:                                  │
│      evict_if_over_max()                │
│      download via boto3                 │
│      return path                        │
└──────────┬──────────────────────────────┘
           ▼
   MinIO via s3.eurio.musubi.dev
```

**Browser admin** (Vercel) : pas de cache local Python. L'API ML redirect 302 vers signed URL ; browser cache HTTP fait le job.

## Pré-requis

- Chunk 3 livré (DB pointe vers MinIO).
- Module `ml/storage/__init__.py` (chunk 2) avec `bucket_for_asset`, `signed_url`.

## Décisions actées

1. **Path cache** : `~/.cache/eurio/<bucket>/<storage_key>`.
2. **TTL signed URL** : 6 h (vision §"Décisions actées" #10).
3. **Borne LRU Mac** : 5 GB par défaut, `EURIO_CACHE_MAX_GB` override.
4. **Pas de borne par défaut sur PC** : `MAX_GB=0` = unbounded, le cache run-scoped (chunk 5) gère le cycle de vie.
5. **Atomic write** : `<path>.tmp` puis `os.replace`.

## Implémentation

### 4.1 Lib core `ml/storage/local_cache.py`

```python
from __future__ import annotations
import os, time
from pathlib import Path

import boto3
from botocore.exceptions import ClientError

from ml.storage import Bucket  # type alias from chunk 2

CACHE_ROOT = Path(os.environ.get(
    "EURIO_CACHE_ROOT",
    Path.home() / ".cache" / "eurio",
))
MAX_GB = float(os.environ.get("EURIO_CACHE_MAX_GB", "0"))  # 0 = unbounded

_s3 = None

def _client():
    global _s3
    if _s3 is None:
        _s3 = boto3.client(
            "s3",
            endpoint_url="https://s3.eurio.musubi.dev",
            aws_access_key_id=os.environ["MINIO_ACCESS_KEY"],
            aws_secret_access_key=os.environ["MINIO_SECRET_KEY"],
        )
    return _s3


def local_path(bucket: Bucket, storage_key: str) -> Path:
    """Renvoie un path local. Download depuis MinIO si pas en cache.
    Throw si MinIO inaccessible. Aucun fallback fs legacy."""
    target = CACHE_ROOT / bucket / storage_key
    if target.exists():
        os.utime(target, (time.time(), target.stat().st_mtime))
        return target

    if MAX_GB > 0:
        _evict_if_needed()

    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(target.suffix + ".tmp")
    try:
        _client().download_file(bucket, storage_key, str(tmp))
    except ClientError as e:
        tmp.unlink(missing_ok=True)
        raise FileNotFoundError(f"{bucket}/{storage_key} not in MinIO: {e}") from e
    os.replace(tmp, target)
    return target


def _evict_if_needed() -> None:
    if not CACHE_ROOT.exists():
        return
    files = []
    for f in CACHE_ROOT.rglob("*"):
        if f.is_file():
            st = f.stat()
            files.append((st.st_atime, f, st.st_size))
    files.sort(key=lambda t: t[0])
    total = sum(s for _, _, s in files)
    max_bytes = int(MAX_GB * 1024**3)
    while total > max_bytes and files:
        _, victim, sz = files.pop(0)
        victim.unlink()
        total -= sz


def cache_stats() -> dict:
    if not CACHE_ROOT.exists():
        return {"n_files": 0, "size_bytes": 0, "max_gb": MAX_GB}
    n, sz = 0, 0
    for f in CACHE_ROOT.rglob("*"):
        if f.is_file():
            n += 1
            sz += f.stat().st_size
    return {"n_files": n, "size_bytes": sz, "max_gb": MAX_GB}
```

### 4.2 Wrapper applicatif

`ml/storage/__init__.py` :

```python
def asset_local_path(asset_row, source: str) -> Path:
    """Prend une row image_assets + sa source (via JOIN), retourne path local."""
    bucket = bucket_for_asset(source)
    return local_path(bucket, asset_row["storage_path"])

def source_image_local_path(si_row) -> Path:
    return local_path("enrichment-raws", si_row["storage_path"])
```

### 4.3 API ML : 302 redirect pour le front admin

`ml/api/sources_routes.py` (modifier l'existant) :

```python
from fastapi.responses import RedirectResponse
from ml.storage import bucket_for_asset, signed_url

@router.get("/{source_id}/assets/{asset_id}/file")
def get_asset_file(source_id: str, asset_id: str):
    conn = _store()._connection()
    row = conn.execute(
        "SELECT a.storage_path, s.source FROM image_assets a "
        "JOIN source_images s ON s.id = a.source_image_id "
        "WHERE a.id = ?", (asset_id,),
    ).fetchone()
    if row is None or not row["storage_path"]:
        raise HTTPException(404, "Asset not found.")
    bucket = bucket_for_asset(row["source"])
    url = signed_url(bucket, row["storage_path"])
    return RedirectResponse(url=url, status_code=302)
```

### 4.4 Tâches go-task

```yaml
ml:cache-stats:
  desc: Show local cache size + n_files
  cmds: [python -c "from ml.storage.local_cache import cache_stats; import json; print(json.dumps(cache_stats(), indent=2))"]
ml:cache-purge:
  desc: Wipe local cache
  cmds: [rm -rf ~/.cache/eurio]
  prompt: "Sure ?"
```

## Critères d'acceptation

- [ ] `local_path(bucket, key)` télécharge au 1er appel, lit du cache au 2e
- [ ] Tests unitaires :
  - Write atomique (pas de fichier partiel si interruption)
  - `_evict_if_needed` retire les plus vieux quand `MAX_GB` dépassé
  - `local_path` raise `FileNotFoundError` si clé absente / MinIO down
- [ ] Endpoint API ML répond 302 vers signed URL valide (TTL 6h)
- [ ] Browser sur `/review` charge les crops, 2e load < 30 ms (browser cache HTTP)
- [ ] Pas de regression sur la review queue vs avant migration

## Gotchas

- **Signed URL expirée pendant pageview long** : le browser refait la requête à l'API ML qui régénère. Pas un bug, vérifier le cycle.
- **`noatime` mount option** : désactive `atime`. Sur Mac/PC perso a priori non, mais vérifier `mount | grep noatime`. Sinon `_evict_if_needed` tape sur `mtime`.
- **Concurrent download du même asset** : 2 process écrivent dans `<path>.tmp` puis `os.replace`. La 2e écrase la 1ère, pas de corruption.
- **Boto3 retries** : par défaut 3 retries avec backoff. OK pour un MinIO occasionnellement lent.

## Anti-objectifs

- ❌ Pas de FUSE mount.
- ❌ Pas de fallback fs legacy. Si MinIO down → throw.
- ❌ Pas de DB sidecar pour le LRU. `os.atime` suffit.
- ❌ Pas de prefetch agressif "tous les crops dès l'ouverture review queue".
