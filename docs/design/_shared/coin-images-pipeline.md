# Pipeline images pièces

> Comment on récupère, stocke et sert les images de pièces dans Eurio.

## Statut actuel (2026-04-16)

- **367 coins** avec Numista ID (12.5% du catalogue de 2938)
- **367 coins** avec images Numista dans Supabase Storage
- **~322 types** uniques Numista (2 faces x 2 tailles = ~1288 fichiers WebP)
- **56 cas ambigus** en attente de review manuelle
- **2571 coins** restants sans Numista ID (dénominations 1c→1€)

## Historique des opérations

### Phase 0 — Fix scan (2026-04-16) ✅

**Problème** : le ML sortait des Numista type IDs (87, 135, etc.) mais `findByNumistaId()` retournait toujours null car `cross_refs` ne contenait que des URLs Wikipedia.

**Fix** : ajout de `"numista_id": <int>` dans `cross_refs` pour les 5 types ML.

| Numista ID | Pièce | Coins matchés | Résultat |
|---|---|---|---|
| 87 | 1€ Espagne Juan Carlos I | 16 (1999-2014) | ✅ |
| 111 | 1€ Allemagne Aigle | 4 (2002-2005) | ✅ |
| 135 | 1€ Italie Vitruve | 23 (2002-2024) | ✅ |
| 159 | 1€ Portugal Sceau royal | 6 (2002-2007) | ✅ |
| 226447 | 2€ Allemagne 2020 Kniefall | 1 | ✅ |

**Total** : 50 coins enrichis, 0 API call (mapping hardcodé).
**Script** : `ml/enrich_from_numista.py`
**Validation** : scan fonctionne, fiche s'affiche dans l'app.

### Phase 1 — Images 5 types ML (2026-04-16) ✅

**Action** : fetch images officielles depuis Numista API → resize → upload Supabase Storage.

- **5 appels API** Numista (`GET /types/{id}`)
- **10 images** téléchargées (5 types x 2 faces)
- **20 fichiers WebP** uploadés (10 images x 2 tailles : 400px + 120px)
- Bucket `coin-images` créé (public, WebP only, 512 KB max)
- 50 coins patchés avec URLs Storage dans `images` JSONB

**Script** : `ml/enrich_from_numista.py --images`
**Validation** : images visibles dans l'admin + app Android.

### Phase 2 — Batch matching 2EUR (2026-04-16) ✅

**Action** : matcher les 441 types 2EUR de `coin_catalog.json` vers le referential.

| Méthode | Matchs | Description |
|---|---|---|
| Exact key (country+face+year+commemo) | 145 | 1 seul candidat → match direct |
| Theme matching (fuzzy word overlap) | 210 | Mots communs entre nom Numista et thème referential |
| **Total matchés** | **355** | |
| Déjà enrichi (Phase 0) | 1 | Kniefall |
| Ambigus (review manuelle) | 56 | Noms trop différents, exportés en JSON |
| Absents du referential | 29 | Commémos communes EU (Treaty of Rome, etc.) |

**0 appel API** — matching purement local.
**Script** : `ml/batch_match_numista.py --review`
**Résultat** : `ml/datasets/numista_review_queue.json` généré pour les 56 cas ambigus.

### Phase 2b — Batch images 2EUR (2026-04-16) ✅

**Action** : fetch images pour tous les types avec numista_id mais sans images Storage.

- **117 appels API** Numista (les ~200 autres avaient déjà des images BCE/legacy)
- **~234 images** téléchargées du CDN Numista
- **~468 fichiers WebP** uploadés (117 types x 2 faces x 2 tailles)
- **0 échec** sur les 117 types

**Script** : `ml/batch_fetch_images.py`
**Validation** : dans l'admin, filtre "2€ + Avec image" → toutes les commémos matchées ont leurs photos.

### Phase 3 — Dénominations 1c→1€ (à faire)

**Objectif** : enrichir les 2571 coins restants (192 combos pays x dénomination).

**Stratégie prévue** :
- Recherche API par pays + dénomination : `GET /types?q=1 euro&issuer=italy`
- 24 pays x 7 dénominations = ~168 recherches + ~400 get_type
- Budget estimé : ~500-900 API calls
- Étaler sur 1-2 mois si quota 2000 calls/mois

**Statut** : en attente de quotas Numista.

### Review manuelle — 56 cas ambigus (à faire)

**Objectif** : résoudre les 56 cas où le matching automatique n'a pas pu trancher.

**Cause** : noms trop différents entre Numista et referential. Exemple :
- Numista "political rights" vs Referential "30 years since 18 became legal age"
- Numista "the legend of charlemagne" vs Referential "charlemagne"

**Plan** : page admin "Coin Arbitrage" pour résoudre visuellement (prompt préparé pour session dédiée).
**Données** : `ml/datasets/numista_review_queue.json`

## Architecture

```
Numista API GET /types/{id}
  → obverse.picture + reverse.picture (URLs CDN Numista, ~500KB-1.5MB)
  → download via httpx
  → resize Pillow (LANCZOS)
  → encode WebP (400px detail q82 + 120px thumb q78)
  → upload Supabase Storage (bucket coin-images, public)
  → URL publique dans coins.images JSONB
  → export_catalog_snapshot.py extrait image_obverse_url / image_reverse_url
  → Android CoinEntity.imageObverseUrl → Coil AsyncImage
```

### Stockage

| Composant | Rôle |
|---|---|
| Supabase Storage `coin-images/` | Bucket public, WebP only, 512 KB max/fichier |
| `coins.images` JSONB | URLs des images par eurio_id (format dict) |
| `catalog_snapshot.json` | Embarqué dans l'APK, contient les URLs |
| Coil (Android) | Cache mémoire + disque, chargement async |

### Structure Storage

```
coin-images/
  {numista_id}/
    obverse-400.webp    # detail (scan modal, page détail)
    obverse-120.webp    # thumbnail (grille coffre)
    reverse-400.webp
    reverse-120.webp
```

Un dossier par **Numista type ID** (= un design), pas par eurio_id.
Tous les millésimes partageant le même design pointent vers les mêmes fichiers.

### Format images

| Taille | Largeur | WebP quality | Poids typique | Usage |
|---|---|---|---|---|
| detail | 400px | 82 | 30-45 KB | Scan modal, page détail |
| thumb | 120px | 78 | 3-4 KB | Grille coffre, listes |

### Schéma `coins.images` JSONB

```json
{
  "obverse": "https://<project>.supabase.co/storage/v1/object/public/coin-images/135/obverse-400.webp",
  "obverse_thumb": "https://<project>.supabase.co/storage/v1/object/public/coin-images/135/obverse-120.webp",
  "reverse": "https://<project>.supabase.co/storage/v1/object/public/coin-images/135/reverse-400.webp",
  "reverse_thumb": "https://<project>.supabase.co/storage/v1/object/public/coin-images/135/reverse-120.webp"
}
```

Note : `export_catalog_snapshot.py` extrait `obverse` et `reverse` (detail 400px). Les thumbs sont dans Storage mais pas encore exposées dans le snapshot Android.

## Scripts

| Script | Rôle | API calls | Quand l'utiliser |
|---|---|---|---|
| `ml/enrich_from_numista.py` | Enrichir les 5 types ML (hardcodé) + images | 5 | Première fois, ou quand on retrain le ML |
| `ml/batch_match_numista.py` | Matcher coin_catalog.json → referential | 0 | Après un import_numista.py qui ajoute des types |
| `ml/batch_fetch_images.py` | Fetch/resize/upload images en batch | 1 par type | Après un batch_match qui ajoute des numista_ids |
| `ml/import_numista.py` | Importer des types depuis Numista API search | variable | Phase 3 (nouvelles dénominations) |

### Workflow type

```bash
# 1. Matcher les types connus (0 API call)
go-task -d ml batch-match

# 2. Fetch images pour les types matchés
go-task -d ml batch-images

# 3. Regénérer le snapshot Android
go-task android:snapshot

# 4. Rebuild l'APK
go-task android:build
```

## Quotas et contraintes

### Supabase free tier

| Ressource | Limite | Utilisé (2026-04-16) | Estimé 3000 coins |
|---|---|---|---|
| Database | 0.5 GB | ~39 MB (8%) | ~50 MB |
| Storage | 1 GB | ~30 MB (~1288 fichiers) | ~240 MB |
| Egress | 5 GB/mois | ~23 MB | ~80 MB (10 users actifs) |
| Image Transforms | indisponible | N/A | resize fait côté Python |

### Numista API

| Ressource | Limite | Utilisé cette session |
|---|---|---|
| Quota mensuel | ~2000 calls | ~122 calls (5 + 117) |
| `GET /types/{id}` | 1 call | Retourne image URLs + metadata |
| CDN images | pas de quota API | Délai 0.3-0.5s respecté |

## Sujets futurs

### Images par année / millésime

Numista fournit une image par **type** (design), pas par année. Les pièces standard d'un même type sont identiques visuellement à l'année gravée près. Pour des images spécifiques par millésime, il faudrait une autre source. Non bloquant pour la v1.

### Thumbnail dans le snapshot Android

Le snapshot ne contient que l'URL detail (400px). Pour exposer les thumbs (120px) :
- Ajouter `image_obverse_thumb_url` dans `export_catalog_snapshot.py`, `CatalogSnapshot.kt`, `CoinEntity.kt`
- Utiliser le thumb dans les grilles, le detail dans les modales

À faire quand on aura des vrais users et que la bande passante comptera.

### Cache et prefetch Android

Coil gère automatiquement le cache mémoire + disque. Un user qui scanne la même pièce 10 fois ne la télécharge qu'une fois. Prefetch optionnel à évaluer plus tard.

### Admin "Coin Arbitrage"

Page dédiée pour résoudre visuellement les 56 cas ambigus. Affiche côte à côte la pièce Numista et les candidats eurio_id avec images. Session dédiée prévue.
