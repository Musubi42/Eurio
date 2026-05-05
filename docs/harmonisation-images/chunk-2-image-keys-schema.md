# Chunk 2 — Schéma DB clés storage

> Définir le format des clés S3 et adapter le schéma DB. Ne touche pas
> encore aux données — c'est purement structurel. Pré-requis pour
> chunks 3, 6.

## Objectif

À la fin du chunk :
- `image_assets.storage_path` est renommé `storage_key` et porte une **clé S3** (chemin relatif au bucket), pas un chemin filesystem absolu.
- Le bucket associé est dérivable de la sémantique de la ligne (pas une colonne séparée → pas de désynchro possible).
- Une fonction utilitaire `storage_url(storage_key, kind)` génère l'URL absolue (signed ou publique selon le bucket).

Aucune donnée n'est encore migrée — c'est le sujet du chunk 3.

## Convention de nommage des clés

Format général : `<source>/<group>/<asset>.<ext>`

Le bucket est implicite selon la source.

### `numista-canonical` (bucket public)

```
numista/<numista_id>/<face>.png
ex : numista/68395/obverse.png
     numista/68395/reverse.png
     numista/68395/edge.png      (rare)
```

`numista_id` est stable (ne change jamais). `face` ∈ {obverse, reverse, edge, detail}. Toutes les images du référentiel Numista vivent ici.

### `enrichment` (bucket privé, signed URLs)

```
<source>/<run_id>/<asset_id>.<ext>
ex : ebay/2026-04-12_andorra-2eur/611c7bb820d746ea8b85cf8047170e1b.png
     catawiki/2026-04-15_silent-run/9d7e...
     mock/dev-2026-05-01/abc123.png
```

`source` = `image_assets.source` (ebay, catawiki, mdp, lmdlp, mock). `run_id` = `source_runs.id` ou date+slug si pas de run formel. `asset_id` = `image_assets.id` (UUID).

**Pourquoi `run_id` dans la clé** : permet `mc rm --recursive eurio/enrichment/ebay/<run_id>/` pour purger un run entier sans toucher au reste. Aussi : grouping naturel pour debug et backup-by-prefix.

### `source-images` (bucket privé)

Photos originales avant crop (raw downloads) :

```
<source>/<run_id>/<source_image_id>.<ext>
ex : ebay/2026-04-12_andorra-2eur/raw-uuid-xyz.jpg
```

Une `source_image` peut avoir N `image_assets` (crops) — la liaison est en DB (`image_assets.source_image_id`). Le bucket sépare les raws des crops pour permettre une suppression sélective des raws si besoin de reclaim de l'espace plus tard (les crops suffisent au training).

## Migration du schéma

### Avant (aujourd'hui)

```sql
CREATE TABLE image_assets (
  ...
  storage_path TEXT NOT NULL,  -- chemin filesystem absolu, machine-spécifique
  ...
);

CREATE TABLE source_images (
  ...
  storage_path TEXT,  -- idem
  ...
);
```

### Après

```sql
ALTER TABLE image_assets RENAME COLUMN storage_path TO storage_key;
ALTER TABLE source_images RENAME COLUMN storage_path TO storage_key;
```

Sémantique de `storage_key` :
- Format `<source>/<run_id>/<asset_id_or_face>.<ext>` (cf. ci-dessus)
- Pas de slash en tête ni en queue
- Pas d'URL absolue (pas de `https://...`, pas de `s3://...`)

Le bucket est dérivé :
- `image_assets` → bucket `enrichment`, sauf si `source = 'numista'` → `numista-canonical`
- `source_images` → bucket `source-images`

## Fonction utilitaire `storage_url`

Côté Python (`ml/storage/`, nouveau module) :

```python
# ml/storage/__init__.py
from typing import Literal

BucketKind = Literal["numista-canonical", "enrichment", "source-images"]

def bucket_for_asset(source: str) -> BucketKind:
    if source == "numista":
        return "numista-canonical"
    return "enrichment"

def storage_url(
    storage_key: str,
    bucket: BucketKind,
    *,
    signed: bool = False,
    expires_seconds: int = 3600,
) -> str:
    """Construit l'URL absolue pour un storage_key.

    - bucket public (numista-canonical) → URL CDN directe via images.eurio.com
    - bucket privé → URL signée (signed=True requis)
    """
    if bucket == "numista-canonical":
        return f"https://images.eurio.com/{storage_key}"
    if not signed:
        raise ValueError(f"bucket {bucket} requires signed=True")
    return _s3_client().generate_presigned_url(
        "get_object",
        Params={"Bucket": bucket, "Key": storage_key},
        ExpiresIn=expires_seconds,
    )
```

Côté API ML, l'endpoint qui sert un asset (aujourd'hui `GET /sources/{source}/assets/{asset_id}/file`) doit basculer :
- soit redirect 302 vers l'URL signée (front suit le redirect, browser cache HTTP fait le job)
- soit retourner une réponse JSON `{ url: "..." }` que le front consomme (plus de boulot front)

**Reco V1** : redirect 302 — pas de breaking change côté front, tous les `<img src="">` continuent de marcher.

## Critères d'acceptation

- [ ] Migration SQL appliquée sur la DB locale (training.db)
- [ ] `state/schema.sql` mis à jour pour refléter `storage_key`
- [ ] Module `ml/storage/` créé avec `bucket_for_asset` + `storage_url`
- [ ] Tests unitaires sur `storage_url` (3 cas : Numista public, enrichment signé, missing-signed-flag → raise)
- [ ] Aucun chemin absolu en DB (vérification : `SELECT storage_key FROM image_assets WHERE storage_key LIKE '/%'` doit retourner 0 rows après chunk 3)

## Gotchas

- **SQLite ALTER TABLE RENAME COLUMN** est OK depuis 3.25.0 (2018). Vérifier la version embarquée.
- **Le code existant** qui lit `storage_path` casse — donc cette migration doit être faite **avant** que la migration de chunk 3 ne tourne, sinon l'app down. Ordre :
  1. Branche : ajout colonne `storage_key`, copie `storage_path` → `storage_key`, code lit les 2.
  2. Tourner chunk 3 (migration).
  3. Drop `storage_path`.
- **JSON dans `bbox_json`, `candidate_eurio_ids_json`** etc. : ces colonnes ne contiennent PAS de chemin storage à priori. Vérifier avec un grep avant migration. Si jamais oui → liste à part dans le script de migration.

## Anti-objectifs

- ❌ Pas de colonne `bucket` séparée dans `image_assets`. Le bucket est dérivé de `source`, sinon désynchro garantie.
- ❌ Pas d'URL absolue stockée en DB. La DB porte la clé, le code construit l'URL. Si on swap MinIO→AWS, on ne touche pas la DB.
- ❌ Pas de format de clé "à la main" (genre concat eurio_id + timestamp). Toujours dériver d'identifiants stables existants (`numista_id`, `run_id`, `asset_id`).
