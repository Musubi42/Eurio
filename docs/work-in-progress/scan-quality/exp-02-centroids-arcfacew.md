# exp-02-centroids-arcfacew — arcface_w vs val_mean

> Suite directe d'[`exp-01`](./exp-01-centroids.md) : 3e source de centroïdes
> disponible dans `compute_embeddings` (`--centroid-source arcface_w` =
> prototypes W de la tête ArcFace, L2-normalisés). Même corpus, même funnel.
> **État : terminée (2026-07-06).**

## 1. Hypothèse

Les prototypes ArcFace-W, appris explicitement comme centres de classe,
matchent mieux que la moyenne val.

## 2. Variable unique

Centroïdes `arcface_w` vs baseline `val_mean-5bf8edb0ad7d` — modèle tflite,
corpus, chemin (`fast`) identiques à exp-01.

## 3. Corpus

`9b1bc705525d`, n=73 (identique exp-01 — comparaison croisée exp-01↔exp-02 valide).

## 4. Résultat

| | val_mean | arcface_w | train_mean (exp-01, rappel) |
|---|---|---|---|
| **R@1 eq** | 0.6849 | 0.7397 (+5.5 pts) | **0.7671 (+8.2 pts)** |
| R@5 eq | 0.9315 | 0.9178 | 0.9178 |
| McNemar | — | 18 discordantes (11/7), **p=0.48** | 14 (10/4), p=0.18 |

Sortie : `ml/state/scan_corpus_runs/exp-02/arcface_w__9b1bc705525d/`.

## 5. Décision

| Étage | Verdict |
|---|---|
| **S0** | **no-go** — battu par train_mean sur les deux axes (delta plus faible, bascules moins nettes : 11 gagnées / 7 perdues) |

## 6. Verdict écrit

`arcface_w` améliore sur `val_mean` (+5.5 pts) mais reste derrière
`train_mean` (+8.2 pts) avec un signal apparié plus bruité (p=0.48 vs 0.18).
Cohérent avec le rationale documenté dans `compute_embeddings.py` (W dérive
quand la loss ArcFace → 0). **Non retenu** ; la piste centroïdes reste
`train_mean`, à re-répliquer sur corpus élargi (cf. exp-01 §9).
