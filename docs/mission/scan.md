# Mission — Scan

> Index : [`README.md`](./README.md) · Stratégie : [`product-strategy.md`](./product-strategy.md)

## Objectif

Un **scan on-device fiable** : pointer la caméra sur une commémo 2€, l'identifier
(R@1 élevé en conditions wild) et la proposer au coffre. C'est la **porte d'entrée**
de tout le produit — sans scan qui marche, aucune proposition de valeur ne tombe.

## Acquis

- Pipeline scan fonctionnelle : YOLO11-nano + OpenCV Hough en parallèle → merge IoU →
  rerank ArcFace → consensus buffer (cf. `docs/research/detection-pipeline-unified.md`).
- Isolation lab/prod, label space `eurio_id` strict, **obverse-only** (cf. `features/`).
- `CropConfig` paramétrable + app build `cohortTest` (5 conditions × 4 photos, auto-advance).
- Baseline à battre (test-1 v2) : **R@1 strict 92.86 % studio / 85.7 % live**.

## Reste à faire (étapes)

1. **🔴 340 captures device** — cohorte `mix-zone-17`, 5 conditions × 4 photos × 17 coins.
   *Seul vrai prérequis dur ; manuel (Raphaël), demande lieu + lumière.*
2. **Sweep ablation crop** — margin {2,5,10,15}% × edge {hard, feathered, none} @224,
   hold-out = les captures. Tranche le format de crop optimal.
3. **Cutover format** — mirror du gagnant dans `SnapNormalizer.kt`, re-crop des raws eBay.
4. **Train ArcFace v2** — sur (Numista canonique augmenté ∪ wild eBay), GPU 1080 Ti.
   *Pivot DINOv2 envisagé (cf. `features/model.md`).*
5. **Bench** — R@1 sur les cohortes capture (hold-out).
6. **Deploy** — export LiteRT, embeddings pré-calculés, packagé dans l'APK.

## Dépendances souples

- Les captures débloquent ablation + bench. **Mais** le reste tourne en parallèle :
  scrape eBay, enrichissement, et toute la mission App n'attendent pas le scan parfait.
- Couverture wild des classes (scrape eBay piloté manuellement) alimente le training.

## Done quand

Nouvelle version Android shippable, scan fiable en conditions réelles, écart studio↔live
acceptable.

## Détail / exécution

`docs/roadmap.md` (J0→J7, tracker legacy), `docs/features/`, `docs/training-pipeline/`,
`docs/scan-normalization/`, chantier ablation dans `roadmap.md §ablation format crop`.
Memories : `project_crop_format_ablation`, `project_phase1_decisions`, `feedback_crop_deferred_until_bench`.
