# Phase 1 — Bring-up DINOv2 en lab

> Câbler un foundation embedder (DINOv2 par défaut, candidats alt :
> SigLIP, CLIP-mobile) en Python `ml/`, sans toucher Android. Mesurer
> sur la cohort existante. Cette phase débloque les deux usages
> attendus : **verifier** pour le harvest, et **backbone** pour le
> nouvel embedder on-device.

## Pré-requis

- [`lab-prod-refacto/phase-1-label-space.md`](../../work-in-progress/lab-prod-refacto/phase-1-label-space.md)
  appliquée — sinon les itérations multi-classes ne tournent pas
  proprement.
- Idéalement [`lab-prod-refacto/phase-2-isolation-artefacts.md`](../../work-in-progress/lab-prod-refacto/phase-2-isolation-artefacts.md)
  appliquée — sinon une expérimentation DINOv2 polluerait les
  artefacts singleton.

## Objectifs mesurables

À la fin de cette phase, on doit avoir :

1. Un module `ml/foundation/` qui expose un embedder DINOv2
   utilitaire (charge le modèle, encode une image → vecteur).
2. Un script `ml/scripts/bench_foundation_vs_canonical.py` qui
   prend les photos studio Numista comme ancres et les photos live
   tests existantes comme requêtes, et reporte R@1 / R@3 / spread.
3. Un nombre concret : **R@1 strict cohort `mix-zone-7-cls`** avec
   DINOv2 zero-shot (sans aucun fine-tuning), à comparer aux 57%
   live de test-2.
4. Une décision : **on continue avec DINOv2** (et phase 2 démarre)
   ou **on essaie une alt** (SigLIP, CLIP) avant.

## Pourquoi cette phase d'abord

Le verifier ([`auto-validator.md`](./auto-validator.md)) a besoin
d'un foundation embedder fiable. L'embedder on-device V2 a besoin
du même backbone. Si DINOv2 sous-performe sur euros (peu probable
mais à mesurer), tout le plan en aval doit pivoter. Mieux vaut le
savoir avant de construire 4 phases dessus.

## Périmètre code

Trois ajouts dans `ml/` :

```
ml/
├── foundation/
│   ├── __init__.py
│   ├── dinov2.py            # wrapper torch hub, encode(image) → vec
│   └── registry.py           # factory: get_embedder("dinov2-small")
├── scripts/
│   └── bench_foundation_vs_canonical.py
└── tests/
    └── test_foundation.py
```

Aucune modification de `train_embedder.py`, `compute_embeddings.py`,
`iteration_runner.py`. C'est volontaire : la phase 1 est une **mesure
side-channel**, pas une intégration.

## Choix techniques

### DINOv2

- Source : `torch.hub.load('facebookresearch/dinov2', 'dinov2_vits14')`
  (ou variante `vitb14` selon perf/coût).
- Pré-traitement : resize 224x224, normalisation ImageNet.
- Output : embedding 384-dim (vits14) ou 768-dim (vitb14).
- Inference CPU acceptable pour le verifier (latence non critique).
- Pas de fine-tuning à cette phase. Zero-shot only.

### Alternatives à benchmarker si DINOv2 sous-performe

| Modèle | Pourquoi essayer | Comment |
|---|---|---|
| **SigLIP** (`google/siglip-base-patch16-224`) | Embedding image+texte, parfois plus discriminant en fine-grained | HuggingFace `transformers` |
| **CLIP** (`openai/clip-vit-base-patch32`) | Référence historique, baseline | HuggingFace |
| **DINOv2 + registers** (`dinov2_vits14_reg`) | Variant plus stable sur fine-grained | Même hub |

Garder en tête : on cherche la **séparation entre eurio_id**, pas la
classification sémantique générique.

## Bench protocol

`bench_foundation_vs_canonical.py` :

1. Charge l'embedder (`--model dinov2-small`).
2. Pour chaque pièce du catalogue actif (cohort
   `mix-zone-7-cls`) :
   a. Encode la photo canonique Numista → ancre.
3. Pour chaque photo live tests existante (21 photos cohort `mix-
   zone-7-cls` test-2) :
   a. Encode la photo → query.
   b. Cosine similarity vs toutes les ancres.
   c. Note top-1, top-3, spread.
4. Aggrege : R@1 strict, R@3, mean_spread, confusions.
5. Output JSON `ml/output/foundation_bench/<model>_<timestamp>.json`.

Reporter le résultat dans le journal d'itération
`docs/training-pipeline/journal/dceb9f44-mix-zone-7-cls/dinov2-zeroshot.md`
(nouvelle entrée).

## Critères de décision

| R@1 strict zero-shot | Action |
|---|---|
| > 70% | DINOv2 valide pour verifier. Phase 2 démarre. |
| 50-70% | DINOv2 acceptable comme verifier strict (seuils élevés), mais essayer SigLIP en parallèle. |
| < 50% | Foundation seul ne suffit pas. Ré-arbitrer la stratégie globale (peut-être que le problème est plus proche-jumeaux que studio-wild). |

Note : 70% zero-shot, **sans aucun training**, sur un set qui a
défoncé l'ArcFace from-scratch à 57%, serait déjà une preuve forte
que l'approche est la bonne. La barre psychologique est là.

## Hors-scope phase 1

- **Fine-tuning ArcFace** sur DINOv2. Phase ultérieure du track
  on-device.
- **Distillation mobile**. Phase ultérieure.
- **Intégration dans `train_embedder.py`**. Pas tant qu'on n'a pas
  validé le choix.
- **Cache embeddings ancres**. À ajouter en phase 2 quand le
  verifier tourne sur du volume.

## Livrable

- Code `ml/foundation/` + script bench commités.
- Entrée journal pour les chiffres mesurés.
- Décision tranchée sur le foundation à utiliser.
- (Si décision = continuer) phase 2 du harvest peut démarrer.
