# Chunk 4 — Mac fetch on-demand + LRU 5 GB

> Sur le Mac (admin web + review queue), on n'a que 500 GB de stockage.
> On fetch les images à la volée depuis MinIO et on garde un LRU disk
> cache borné. Pré-requis : chunk 3 livré.

## Objectif

Quand l'utilisateur ouvre la review queue ou la page Coin Detail, les images se chargent en < 200 ms en cold cache, < 30 ms en warm. Le cache disque ne dépasse jamais 5 GB. Pas de gestion manuelle.

## Architecture

```
Browser <─── <img src="..."> ───┐
                                │
            ┌────────── API ML ─┴────────┐
            │  GET /sources/{src}/assets │
            │       /{id}/file           │
            │   ─► 302 redirect          │
            │      vers signed URL       │
            └────────────┬───────────────┘
                         │
                         ▼
                ┌─── MinIO via Cloudflare ───┐
                │   s3.eurio.com/enrichment/ │
                └────────────┬───────────────┘
                             │
                             ▼
                  ┌─ LRU disk cache Mac ─┐
                  │ ~/.cache/eurio/lru/  │
                  │ max 5 GB             │
                  └──────────────────────┘
```

**Note importante** : la première stratégie est de laisser le **browser cache HTTP** faire le travail (Cloudflare → MinIO retourne `Cache-Control: max-age=3600` etc.). Cela couvre 80 % du besoin sans rien implémenter côté Python.

Le LRU disk cache local est utile pour :
- Les scripts Python qui itèrent sur des assets en local (analyse, tests, debug)
- Le cas où le browser cache est purgé (user CMD+Shift+R)
- Les dev workflows en notebook Jupyter

Si la review queue marche déjà bien avec juste le browser cache HTTP → ne pas implémenter le LRU local côté Python. Audit visuel d'abord.

## Pré-requis

- Chunk 3 livré (MinIO en source de vérité).
- Module `ml/storage/` avec `storage_url(..., signed=True)` opérationnel.

## Décisions à acter

1. **TTL signed URLs** : 1 h par défaut. Trop court = fetch refait constamment, trop long = lien volé reste valide. 1 h est un sweet spot.
2. **Taille LRU** : 5 GB par défaut, configurable via `EURIO_CACHE_MAX_GB`.
3. **Redirect 302 vs JSON `{url}`** : 302. Pas de changement front (cf. chunk 2 §"Fonction utilitaire").

## Implémentation

### 4.1 API ML : redirect 302 sur asset endpoint

`ml/api/sources_routes.py` (modifier l'existant) :

```python
@router.get("/{source_id}/assets/{asset_id}/file")
def get_asset_file(source_id: str, asset_id: str):
    conn = _store()._connection()
    row = conn.execute(
        "SELECT a.storage_key, s.source FROM image_assets a "
        "JOIN source_images s ON s.id = a.source_image_id "
        "WHERE a.id = ? AND s.source = ?",
        (asset_id, source_id),
    ).fetchone()
    if row is None or not row["storage_key"]:
        raise HTTPException(status_code=404, detail="Asset not found.")

    bucket = bucket_for_asset(row["source"])
    url = storage_url(row["storage_key"], bucket, signed=True, expires_seconds=3600)
    return RedirectResponse(url=url, status_code=302)
```

Le navigateur suit le 302, télécharge depuis MinIO, et cache (HTTP cache standard).

### 4.2 Module LRU disk cache (Python)

```python
# ml/storage/lru_cache.py
from pathlib import Path
import hashlib, json, os, time

CACHE_DIR = Path(os.environ.get("EURIO_CACHE_DIR",
                                 Path.home() / ".cache" / "eurio" / "lru"))
MAX_GB = float(os.environ.get("EURIO_CACHE_MAX_GB", "5"))

def fetch(storage_key: str, bucket: str) -> Path:
    """Renvoie un chemin local vers l'objet, le téléchargeant depuis
    MinIO si pas encore en cache. Évince si nécessaire."""
    h = hashlib.sha1(f"{bucket}/{storage_key}".encode()).hexdigest()
    obj_dir = CACHE_DIR / "objects"
    obj_dir.mkdir(parents=True, exist_ok=True)
    target = obj_dir / h

    if target.exists():
        # Touch atime pour LRU eviction
        os.utime(target, (time.time(), target.stat().st_mtime))
        return target

    _evict_if_needed()
    _download_to(target, bucket, storage_key)
    return target

def _evict_if_needed():
    obj_dir = CACHE_DIR / "objects"
    files = sorted(obj_dir.glob("*"), key=lambda p: p.stat().st_atime)
    total = sum(f.stat().st_size for f in files)
    max_bytes = MAX_GB * 1024**3
    while total > max_bytes and files:
        victim = files.pop(0)
        total -= victim.stat().st_size
        victim.unlink()
```

Simple. Pas de DB sidecar — `os.atime` suffit. Cache `objects/` plat, hash SHA1 en nom de fichier.

### 4.3 CLI utility

```bash
go-task ml:cache-stats   # affiche taille, n_files
go-task ml:cache-purge   # rm -rf ~/.cache/eurio/lru/
```

## Critères d'acceptation

- [ ] L'endpoint `/sources/{src}/assets/{id}/file` retourne 302 vers une URL signed valide.
- [ ] Le browser sur `/review` charge les crops sans erreur, deuxième load < 30 ms (browser cache).
- [ ] LRU implémenté + tests unitaires (eviction quand > max, atime updated on hit).
- [ ] Pas de regression visible sur la review queue (compare temps de load avant/après).

## Gotchas

- **Redirects 302 et `<img>`** : les browsers suivent les 302 sur les `<img>` sans souci. Si jamais on voit du CORS, c'est probablement une erreur de configuration MinIO (mettre `*` ou l'origine admin en CORS sur le bucket).
- **Signed URL leak via referer** : pas grave, les images Numista canoniques sont publiques de toute façon, et les URLs signées expirent en 1 h pour les privées.
- **Fichiers > 50 MB** : pas dans notre cas (crops ~200 KB max, raws ~5 MB max). Si un jour on a des images haute résolution, vérifier que le LRU 5 GB tient toujours.
- **Mac dort, signed URL expire** : si le user laisse la page ouverte 2h et reclique sur un thumb, le signed URL est expiré → 403. Le browser refera la requête à l'API ML qui regénérera un signed URL. Pas un bug, juste à vérifier que le cycle passe.

## Anti-objectifs

- ❌ Pas de FUSE mount (`rclone mount`). On fetch via HTTP, point.
- ❌ Pas de cache permanent. Le LRU est borné, le cache HTTP est borné. Jamais de "tout télécharger localement".
- ❌ Pas d'offline mode. Si MinIO est down, l'admin Mac ne marche pas. C'est OK — c'est de l'admin, pas de la prod.
- ❌ Pas de prefetch agressif "tous les crops de la review queue dès l'ouverture". On fetch quand l'image est dans le viewport.
