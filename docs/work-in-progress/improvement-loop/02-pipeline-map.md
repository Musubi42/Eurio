# Carte de la pipeline data — où entrent les crops, où exclure les déchets

> Référence pour la boucle d'amélioration. Établie le 2026-06-30 par exploration
> du code (`ml/`, `admin/packages/studio-local/`). Chemins `file:line` indicatifs
> (vérifier avant d'éditer).

## Vue d'ensemble

```
cohort.eurio_ids
  └─ classes_for_eurio_ids → COALESCE(design_group_id, eurio_id)   [training/eval/class_resolver.py]
       └─ BAKE  generate_for_iteration                            [training/iteration_augmentations.py]
            sources/classe, par priorité :
              1. obverse canonique Numista (FS datasets/<nid>/obverse.*)
              2. crops eBay  WHERE training_eligible=1   ◀── LE FILTRE D'INCLUSION
              3. refs officielles BCE / EUR-Lex JO (coin_canonical_images)
            → augmente ceil(100/seed)× → datasets/<nid>/augmentations/<iid>/
            → symlinks staging datasets/iterations/<iid>/<class_id>/
       └─ prepare_dataset --prebaked-staging-dir (train) + eval_real_norm (val)  [training/prepare_dataset.py]
       └─ ArcFace train → lab/iterations/<iid>/{checkpoints,embeddings,tflite}
       └─ evaluate_real_photos vs datasets/eval_real_norm/ (device snaps held-out) [training/eval/evaluate_real_photos.py]
            → R@1 strict/eq · per_coin · confusion_matrix · top_confusions
       └─ build_cohort_bundle → app cohortTest (on-device A/B)     [scripts/build_cohort_bundle.py]
```

## Le filtre d'inclusion training — **un seul gate** : `image_assets.training_eligible`

Deux consommateurs, deux filtres légèrement différents — **attention** :

| Consommateur | Filtre exact | Utilisé par |
|---|---|---|
| **Bake lab** (`iteration_augmentations.py:129-141`) | `source='ebay' AND eurio_id=? AND training_eligible=1 AND storage_status='present'` | **les itérations lab** (ce qui tourne aujourd'hui) |
| Export legacy (`scripts/build_arcface_dataset.py:117-130`) | `resolution_status='manual' AND eurio_id NOT NULL AND face!='reverse' AND face_value=2.0` | pipeline DB→disk historique |

> ⚠️ **Le bake lab ne filtre PAS par `face`.** Un crop `training_eligible=1`
> entre dans le train quelle que soit sa face (obverse / unknown / reverse).
> En pratique `training_eligible=1` est posé à la validation review (qui implique
> en général un avers), mais des crops `face='unknown'` eligible existent et sont
> inclus. Sur l'itération 1 c'est bénin (ils sont propres) — mais c'est un point
> de fuite potentiel à garder en tête (un crop reverse validé par erreur
> polluerait). Décision ouverte : ajouter `AND (face IS NULL OR face!='reverse')`
> au bake lab pour aligner sur l'export legacy.

## Où brancher l'exclusion d'un déchet (déjà câblé, réversible)

Flipper `training_eligible` à 0 suffit — le prochain bake le drop automatiquement
(idempotent, re-compte la couverture). Points d'entrée existants :

| Action | Endpoint | Effet |
|---|---|---|
| **Reject (déchet)** | `POST /review-queue/{id}/reject` | `resolution_status='rejected'`, `training_eligible=0`, `quality_reason∈{not_a_coin,too_low_quality,…}` |
| **Exclude (bench)** | `POST /runs/{run_id}/crops/exclude` | `training_eligible=0`, `quality_reason='too_tilted'`, garde status/eurio_id |
| **Restore** | `POST /review-queue/restore` | `rejected → needs_review`, `training_eligible=1` |
| Validate | `POST /review-queue/{id}/decide` | `resolution_status='manual'`, `training_eligible=1`, pose `eurio_id/face` |
| Re-flag | `POST /coins/assets/reflag-needs-review` | rouvre des crops déjà résolus en `needs_review` (+ upsert review_queue) |

Pour un crop **déjà validé** (pas dans une file ouverte), deux endpoints
asset-level existent désormais (livrés `26e164d`, servent le Jeu d'entraînement) :

| Action | Endpoint | Effet |
|---|---|---|
| **Toggle train** | `POST /lab/assets/{id}/training-eligible {eligible}` | flippe `training_eligible` (pose/efface `quality_reason='manual_triage'`), garde status/eurio_id |
| **Réassigner** | `POST /lab/assets/{id}/reassign {eurio_id}` | change `image_assets.eurio_id` (valide la pièce cible contre `coins`), garde `training_eligible`/face/status ; l'asset saute de classe |
| Recalcul Dino | `POST /review-queue/asset/{id}/dino-suggestions/recompute` | force `predict_and_persist_kinds` (écrase la prédiction périmée) |

> **Fuite du gate bake — toujours ouverte.** Le bake lab n'exclut pas `face=reverse`
> (cf. §filtre ci-dessus). L'anneau du Jeu d'entraînement *surface* maintenant les
> reverse (ambre) et les `unknown` (pointillés), mais un reverse éligible entre
> encore dans le train. Fix propre = P2 (re-détecter la face sur les `unknown`)
> puis P3 (ajouter `AND (face IS NULL OR face != 'reverse')` au bake) — cf.
> `README.md` §Suite.

## Lister les crops d'une classe (pour les afficher)

- **`GET /coins/{eurio_id}/assets?include_unresolved=true&limit=&offset=`**
  (`ml/serving/coin_assets_routes.py:164`). Retourne `CoinAsset` avec
  `file_url=/sources/{source}/assets/{id}/file`, `face`, `variant_kind`,
  `resolution_status`, `width/height`. **Scope = eurio_id exact**, pas de rollup
  design_group.
- `GET /review-queue/rejected?cohort_id=&limit=` — browser des déchets existant
  (précédent réutilisable).
- `GET /coins/enrichment-counts` — `{eurio_id: count}`.
- Pour la **maille design_group** : pas d'endpoint direct ; réutiliser le pattern
  `design_group_lot_scope()` + `COALESCE(design_group_id, eurio_id)` (déjà utilisé
  par `_coin_tail` et `/review-queue/lots?design_group=`).

## Servir une image de crop

Front → **route streaming backend** (read-through cache MinIO), pas de presigned
côté UI :
- `GET /sources/{source_id}/assets/{asset_id}/file` → `image/png` (crops,
  bucket `enrichment-crops`).
- `GET /sources/{source_id}/raws/{source_image_id}/file` → `image/jpeg` (raws).
- Helper serveur : `shared/storage/local_cache.local_path(bucket, key)` (download
  on miss + retry/backoff + `mark_missing_in_storage` sur 404 confirmé).
- Front : `promoteUrl()` préfixe `ML_API` (`:8042`) au `file_url` relatif
  (`useReviewApi.ts`, `useCoinAssets.ts`). Cache-bust `?v=` après re-crop.

Buckets MinIO : `numista-canonical` (public CDN `eurio-images.musubi.dev`),
`enrichment-raws` (privé), **`enrichment-crops`** (privé, crops training). Clés
crops partitionnées `enrichment-crops/{source}/{run_id}/{asset_id}.png` —
**pas** par classe ; la classe vit dans `image_assets.eurio_id`.

## Données de confusion déjà produites (pour DIAGNOSE)

`evaluate_real_photos.py::_aggregate` persiste dans `benchmark_runs` :
- `per_coin` : R@1/3/5 par eurio_id ground-truth.
- `per_condition` / `per_zone` : par lumière/angle/distance/état.
- `confusion_matrix` : `ground_truth → predicted_top1 → count`.
- `top_confusions` : pires misses (spread le plus faible) avec top-3 + photo path.

Et `confusion_map.py` (pré-training, DINOv2) : zones vert/orange/rouge des
quasi-jumeaux catalogue-wide → drive le filtrage `--zones` du bench.

## Front lab — surfaces existantes (cf. `03-crop-triage-ux`)

- Page cohorte : `/lab/cohorts/:id` → `CohortDetailPage.vue`, drawer C3
  `CohortDrawerEbay.vue` (les lignes funnel par classe : listings → … → validés
  → rejetés ; boutons Reviewer N / Recropper N / Rescraper / crops).
- Bouton « crops » → `/bench/runs/<run>?eurio_id=#crop` (audit forensique, pas une
  galerie propre).
- **Galerie crops par classe existante** : `EnrichmentGallery.vue` à
  `/coins/:eurio_id` (grid thumbs, status rings, multi-select, « Renvoyer en
  review », re-crop in-place). Mais : per-eurio_id, accessible une pièce à la
  fois, hors contexte lab. **C'est le composant à ré-exploiter** pour INSPECT.
