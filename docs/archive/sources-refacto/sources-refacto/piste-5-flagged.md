# Piste 5 — kickoff retrain YOLO rim-tight

> Ce doc sert d'**input** à une session future qui attaquera le retrain
> du détecteur YOLO. Tant qu'il n'est pas attaqué, Raphaël y dépose les
> cas problématiques rencontrés en review queue.

## Pourquoi ce sprint existe

État actuel (chunks M1 → M3 livrés 2026-05-04, voir `listing-crop-roadmap.md`) :
pipeline YOLOv8-nano + Hough refine clamped + radial gradient polish + structure guard.
Estimé par Raphaël à **90-95% de crops corrects** sur la review queue eBay
(check manuel post-recrop).

Ce qui plafonne sans retrain :
- **Recall miss** : YOLO ne voit pas certaines pièces (low contrast, angle, fond atypique).
- **False positives** : YOLO classe certains objets non-pièces (stickers/hologrammes ont été partiellement filtrés par le `low_structure` guard, mais d'autres faux positifs peuvent rester).
- **Bbox biaisée** : YOLO a appris "pièce visuelle = pièce + capsule + ombre", la bbox surestime systématiquement de ~15%.
- **Bad rim** : sur certaines coincards, le polish + Hough ne convergent pas vers le rim métallique exact.

La VRAIE solution : **réannoter un dataset rim-tight** (bboxes serrées sur le rim métallique uniquement, pas la capsule) et retrain `coin_detector`.

## Ce qu'il faut accomplir dans le sprint piste 5

1. **Setup outil annotation** — Roboflow / Label Studio / CVAT. Choisir un, faire un projet "coin_detector_v2_rim_tight".
2. **Constituer un dataset diversifié** — viser 200-500 images annotées rim-tight, en couvrant les axes de variation listés ci-dessous.
3. **Retrain YOLOv8n** — `ml/training/train_detector.py` est déjà câblé, il suffira de pointer sur le nouveau dataset YAML.
4. **Validation** — re-runner `ml/scripts/bench_listing_detection.py` avec le nouveau modèle, vérifier 0 régression sur le golden set.
5. **Promote** — remplacer `ml/output/detection/coin_detector/weights/best.pt` (avec backup du current).
6. **Re-cleanup + re-recrop** sur eBay.

## Axes de diversité visés pour le training set

À partir des cas flagués ci-dessous + du corpus existant, équilibrer :

- **Conditionnement** : libre / capsule plastique / blister rigide / coincard texte / coincard photo
- **Multiplicité** : 1 pièce / 2 pièces / 3+ pièces
- **Fond** : uniforme clair / uniforme sombre / texturé (cuir, bois, tissu) / paysage (coincard) / motif décoratif
- **Lumière** : studio / flash / ambiante / contre-jour
- **Angle** : face / léger tilt / fort tilt
- **Pièce** : neuve / usée / patinée / bimétal / monométal
- **Cas adverses** : présence de stickers/hologrammes/codes-barres / présence de motifs ronds dans le fond (arches, étoiles, sablier)

## Outils d'aide pour la session future

- **Bench visuel** : `ml/scripts/bench_listing_detection.py` — déjà calibré sur 8 lots golden. Étendre `GOLDEN_LOTS` avec les `source_ref` de la liste flagguée ci-dessous → on a un avant/après immédiat sur les cas sensibles.
- **Stats globales** : `ml/scripts/measure_listing_radius_distribution.py` — tourne sur tout le corpus, donne distrib `r/short`. Utile pour valider qu'aucune régression de seuil n'arrive avec le nouveau modèle.
- **Script de re-promote** : à écrire dans le sprint, pour basculer le `best.pt` proprement avec rollback possible.

## Prérequis ML training

- Dataset YOLOv8 format : `images/{train,val}/`, `labels/{train,val}/` avec `data.yaml`.
- GPU recommandé (Mac M4 MPS marche, 1080 Ti aussi). 50-100 epochs typiques.
- Réutiliser le hyperparams de `train_detector.py` (déjà tunés pour le single-class coin).

## Cas flaggés (à compléter par Raphaël)

> **Format** : un bloc `## listing_key` par cas. Tag obligatoire, contexte recommandé.
> Tags valides : `recall_miss` · `false_positive` · `bad_bbox` · `bad_rim`

### Exemples connus (du golden set, déjà fixés ou non par M3)

#### ebay_v1|136929255254|0
- **tag** : recall_miss
- **contexte** : pièce 2€ Andorra inclinée sur petit support transparent, fond cuir noir, low contrast
- **note** : YOLO retourne 0 bbox sur img0. Sur img1 (autre angle) : 1 bbox conf=0.08 (sub-threshold). Cas typique de pièce dark-on-dark + perspective.

#### ebay_v1|117142786358|0
- **tag** : false_positive
- **contexte** : sticker hologramme `SAMMLERPOSTEN` sur le verso d'une coincard
- **note** : actuellement filtré par `low_structure` guard (lap_meanabs=27 < 32). Mais le guard est un patch — un détecteur retrainé devrait nativement ne pas classer ces stickers comme pièces.

### Cas à flagger (Raphaël ajoute ici au fil de la review)

<!--
Template à copier :

#### ebay_v1|XXXXX|N
- **tag** : recall_miss | false_positive | bad_bbox | bad_rim
- **contexte** : description visuelle 1 ligne
- **note** : ce qui ne va pas
- (optionnel) screenshot : flagged-screens/NN.png
-->


## Notes pour la future session

Quand cette session ouvre, lire en priorité :
1. Ce doc (kickoff)
2. `listing-crop-roadmap.md` (historique des chunks M1-M3, contexte technique)
3. `ml/scan/normalize_snap.py` section listing pipeline (l'état du code à beat)
4. Mémoire MEMORY.md : tags `project_arcface_design_group_label`, `project_data_referential`

Première action recommandée : étendre `GOLDEN_LOTS` du bench avec tous les `source_ref` taggés ci-dessus, lancer le bench → on a une vue d'ensemble du baseline qu'il faut battre.
