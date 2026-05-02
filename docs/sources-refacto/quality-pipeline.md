# Pipeline qualité photos

> Comment on filtre les images bruitées (eBay, Catawiki) avant de les
> exposer au training. Sans ce filtre, les sources marchand/enchères
> sont du poison.

## Pourquoi

Une image Numista canonique est utilisable directement. Une image
listing eBay peut être :
- une pièce vue de loin dans une main, lumière jaune
- 50 pièces sur un tapis vert (lot), aucune isolable
- une photo floue prise au flash
- une capture d'écran d'un site tiers (logo, watermark)
- une image de qualité acceptable, **utilisable**

On ne fait pas confiance aux titres ni aux vendeurs. On qualifie
**chaque image** par un score automatique, et on flag
`training_eligible = true` seulement les bonnes.

## Étapes du score

Chaque image fetched passe la chaîne suivante, dans l'ordre :

### 1. Sanity check basique

- Format valide (JPEG/PNG/WebP), pas corrompu
- Dimensions ≥ 200×200 (rejet en dessous, `quality_reason='too_small'`)
- Aspect ratio ∈ [0.5, 2.0] (rejet sinon)
- Pas une image presque uniforme (variance pixel > seuil)

### 2. Détection pièce

Réutilise le pipeline existant : YOLO11-nano + Hough circles en
parallèle, comme côté scan (cf. `docs/research/detection-pipeline-unified.md`).

- Si **0 cercle détecté** → `quality_reason='no_coin_detected'`, score 0.
- Si **>1 cercle détecté** → marque `multi_coin=true`, score réduit
  (lot/collage), mais on garde si crop ambigu — l'image peut être
  un display avec une pièce dominante centrale.
- Si **1 cercle clair, ratio raisonnable** → continue.

### 3. Crop & netteté

- Crop sur le cercle dominant + padding 10%.
- Calcul **variance du Laplacien** sur le crop → métrique netteté.
- Seuil bas → `quality_reason='low_sharpness'`, score réduit.

### 4. Face detection (obverse vs reverse)

Heuristique simple :
- Symétries verticales fortes + texte radial → `face='obverse'` (côté commun euros)
- Carte ou symbole national → `face='reverse'`
- Ambigu → `face='unknown'`

Cette étape n'affecte pas `training_eligible` mais remplit la colonne
`face` qui sert au split obverse/reverse côté training.

### 5. Score final

```
quality_score =
    0.4 * coin_detection_confidence
  + 0.3 * sharpness_score_normalized
  + 0.2 * crop_centering_score
  + 0.1 * resolution_score
```

`training_eligible = quality_score >= 0.55` (seuil empirique à ajuster).

Toutes les composantes sont logguées dans `raw_payload.quality` pour
re-derivation sans refetch.

## Quand le pipeline tourne

- **Inline pendant le fetch** pour les images "premium" (Numista,
  MdP, BCE, NumisCorner, CGB) — ces sources passent à >95%, pas
  besoin de batch séparé.
- **Asynchrone** pour les sources bruitées (eBay, Catawiki) — le
  fetcher écrit `training_eligible=false, quality_score=null` puis
  un worker `ml:quality:score-pending` traite par batch. Permet de
  ne pas bloquer le run prix sur l'inférence YOLO.

## Re-scoring

Quand on change le seuil ou la chaîne de scoring :

```
go-task ml:quality:rescore -- --source ebay --since 2026-01-01
```

Met à jour `quality_score` et `training_eligible` sans refetch. Le
script lit `image_assets`, charge les fichiers depuis `storage_path`,
re-applique la chaîne, update.

## Intégration training (lab)

Dans `ml/training/prepare_dataset.py`, le filtre par défaut devient :

```python
SELECT * FROM image_assets
WHERE eurio_id IN (...)
  AND training_eligible = true
  AND (variant_kind != 'in_hand' OR include_in_hand)
```

Un flag `--source-mix=numista,ebay,catawiki` permet d'ajuster la
distribution par itération. Cible naturelle : 30% canonical + 70%
in_hand pour matcher la distribution scan en prod.

## Ce qu'on ne fait PAS

- **Pas d'humain dans la loop** dans le V1. Le flag
  `training_eligible` est purement algorithmique.
- **Pas de classification fine** (closeup vs wide, jour vs nuit) au
  V1. Si nécessaire plus tard, on ajoute des tags via une nouvelle
  étape, pas en complexifiant le score.
- **Pas de ML supervisé pour le score**. Heuristiques et CV
  classique suffisent. Si on veut affiner, on regarde un classifier
  léger entraîné sur quelques centaines d'exemples taggés à la main —
  refacto séparée.

## Anti-poison Catawiki/eBay

Cas particuliers à traiter dur :
- **Multi-coin lots** : flag `multi_coin=true`, exclus de
  `training_eligible` même si score haut.
- **Watermarks détectés** : OCR léger sur les coins de l'image, si
  texte type "© ... / numista.com / cgb.fr" hors zone pièce →
  `quality_reason='watermark'`, exclus.
- **Captures d'écran** : ratio + bords droits + couleurs flat →
  heuristique simple, à voir si nécessaire en pratique.
