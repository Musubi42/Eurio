# Chunk 2 — Schéma DB + format storage_key

> Définir le format des clés S3 et préparer le code à les consommer.
> La colonne reste nommée `storage_path` (cosmétique), seule sa
> sémantique change. Pré-requis pour chunks 3, 6.

## Objectif

À la fin du chunk :

- Le format des clés S3 est figé pour les 3 catégories (canonique, crops, raws).
- Un module `ml/storage/` expose deux fonctions : `bucket_for(...)` (donne le bucket d'une ligne DB) et `local_path(...)` (renvoie un path filesystem local, downloadant depuis MinIO si besoin).
- La colonne DB `storage_path` est documentée comme portant désormais une **clé S3 relative au bucket**, pas un chemin fs absolu.

Aucune donnée n'est encore migrée — c'est le sujet du chunk 3.

## Format des clés (figé)

### `numista-canonical` (public)

```
numista/<numista_id>/<face>.jpg
```

- `numista_id` : stable, jamais réutilisé.
- `face` ∈ `{obverse, reverse}` (le CHECK actuel du schéma reste tel quel).
- Extension `.jpg` (les canoniques sont en JPG aujourd'hui).

### `enrichment-crops` (privé)

```
<source>/<run_id>/<asset_id>.png
```

- `source` ∈ `{ebay, catawiki, mdp, lmdlp, mock, ...}` = `source_images.source`
- `run_id` = `image_assets.run_id` (UUID) ou `'no-run'` si null
- `asset_id` = `image_assets.id` (UUID)
- Extension `.png` (les crops sont en PNG, normalisés via le pipeline).

### `enrichment-raws` (privé)

```
<source>/<run_id>/<source_image_id>.<ext>
```

- `source_image_id` = `source_images.id`
- `ext` dérivée du content-type d'origine (`.jpg`, `.png`, `.webp`).

## Mapping ligne DB → bucket

| Ligne | Bucket | Comment |
|---|---|---|
| `image_assets` avec `source_images.source = 'numista'` | `numista-canonical` | rare en pratique, edge case |
| `image_assets` (autres sources) | `enrichment-crops` | cas courant |
| `source_images` | `enrichment-raws` | toutes |

Un asset Numista canonique typique (référentiel `ml/datasets/`) **n'a pas** de ligne `image_assets` aujourd'hui — il est référencé via `coin_catalog` côté admin/Android. Le chunk 3 traite cette catégorie séparément (inventaire dédié).

## Module `ml/storage/`

### `ml/storage/__init__.py`

```python
from typing import Literal
from pathlib import Path

Bucket = Literal["numista-canonical", "enrichment-crops", "enrichment-raws"]

def bucket_for_asset(source: str) -> Bucket:
    if source == "numista":
        return "numista-canonical"
    return "enrichment-crops"

def bucket_for_source_image() -> Bucket:
    return "enrichment-raws"

def public_url(storage_key: str) -> str:
    """Pour les objets `numista-canonical` uniquement. Pas de signature."""
    return f"https://images.eurio.musubi.dev/{storage_key}"

def signed_url(bucket: Bucket, storage_key: str, expires_seconds: int = 21600) -> str:
    """6 h par défaut. Pour les buckets privés."""
    if bucket == "numista-canonical":
        raise ValueError("Use public_url() for numista-canonical")
    return _s3_client().generate_presigned_url(
        "get_object",
        Params={"Bucket": bucket, "Key": storage_key},
        ExpiresIn=expires_seconds,
    )
```

### `ml/storage/local_cache.py` (read-through)

Détaillé au chunk 4. La signature publique est :

```python
def local_path(bucket: Bucket, storage_key: str) -> Path:
    """Renvoie un path local. Download depuis MinIO si pas en cache.
    Throw si MinIO inaccessible. Aucun fallback fs legacy."""
```

Tout le code applicatif (training, admin API ML, scripts) appelle `local_path(...)`. Aucun appel direct boto3 dans la business logic.

## Schéma DB — pas de migration de schéma V1

**Décision** : on **ne renomme pas** la colonne. `storage_path` reste son nom. Sa valeur change de forme (chemin fs absolu → clé S3 relative). C'est purement sémantique.

Pourquoi : 17 fichiers Python lisent/écrivent `storage_path`. Un rename = bruit massif sans gain (le nom reste lisible, la doc explicite la sémantique). On évite la double-écriture transitoire que P6 interdit.

`docs/design/_shared/data-contracts.md` (à mettre à jour au chunk 3 quand la migration est sealed) :

> `image_assets.storage_path` : clé S3 relative au bucket, format `<source>/<run_id>/<asset_id>.png`. Le bucket est dérivé via `bucket_for_asset(source_images.source)`. Ne contient ni `/` en tête, ni `https://`, ni `s3://`.

## Critères d'acceptation

- [ ] Module `ml/storage/__init__.py` exporte `bucket_for_asset`, `bucket_for_source_image`, `public_url`, `signed_url`
- [ ] Tests unitaires : 3 cas pour `bucket_for_asset` (numista, ebay, mock), assertion `signed_url("numista-canonical", ...)` raise
- [ ] `local_path()` stub en place avec signature, impl complète au chunk 4
- [ ] Aucun changement à la table SQL — schéma identique, seule la sémantique de `storage_path` change
- [ ] `docs/design/_shared/data-contracts.md` mentionne la nouvelle sémantique (à valider au chunk 3 cleanup, mais le wording est préparé ici)

## Gotchas

- **`run_id` peut être NULL** dans `image_assets` (legacy). Convention : utiliser le sentinel `'no-run'` dans la clé S3 pour ces lignes. Documenté dans la fonction qui construit la clé (au chunk 3).
- **Asset_id avec caractères spéciaux** : `image_assets.id` est un UUID, donc safe. Pas de besoin d'escape.
- **`source_images.source` peut diverger** d'une convention attendue (typo, casse). Au chunk 3 on normalise toutes les sources en lowercase avant de construire la clé.

## Anti-objectifs

- ❌ Pas de colonne `bucket` séparée. Le bucket est dérivé de `source`.
- ❌ Pas d'URL absolue stockée en DB.
- ❌ Pas de rename SQL. La colonne reste `storage_path`.
- ❌ Pas de format de clé "à la main". Toujours dériver d'identifiants stables existants.
