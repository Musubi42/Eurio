# Phase 0 — Audit suggestions Dino

- Banque : `2eur_all` — 546 ancres, encodeur `dinov2-vitl14`, bâtie le 2026-06-11T07:57:59+00:00
- Set labellisé : 478 crops décidés en review (`review_queue.status='done'` + `decided_eurio_id`)
- Sans prédiction Dino persistée : 2 (0.4%)

## P1 — Couverture de scope (vraie pièce dans la banque ?)

- In-scope : 478 (100.0%)
- Hors-scope : 0 (0.0%)
  - dont courantes (is_commemorative=0) : 0
  - dont commémo absentes de la banque : 0

> ⚠️ Biais de sélection : le pipeline ne prédit/enqueue que les listings ciblés 2€ commémo. Les lots de courantes (cas kickoff) sont encore majoritairement `open` — le % hors-scope réel en production est plus haut que sur ce set décidé.

## Recall (sur crops avec prédiction)

| Segment | n | global@1 | global@5 | bande pays @1/@5 | UI@1 | UI@5 |
|---|---|---|---|---|---|---|
| Tous (avec prédiction) | 476 | 76.1% | 87.4% | 87.4% / 95.2% (n=476) | 87.4% | 95.2% |
| In-scope (vérité dans banque) | 476 | 76.1% | 87.4% | 87.4% / 95.2% (n=476) | 87.4% | 95.2% |
| Hors-scope | 0 | — | — | — | — | — | — |

## P2 — Effet du biais pays (in-scope uniquement)

| Segment | n | global@1 | global@5 | bande pays @1/@5 | UI@1 | UI@5 |
|---|---|---|---|---|---|---|
| Pays vérité == pays cible | 475 | 76.2% | 87.6% | 87.6% / 95.4% (n=475) | 87.6% | 95.4% |
| Pays vérité ≠ pays cible | 1 | 0.0% | 0.0% | 0.0% / 0.0% (n=1) | 0.0% | 0.0% |
| Pas de pays cible | 0 | — | — | — | — | — | — |

> Sur « vérité ≠ cible », la bande pays ne peut PAS contenir la bonne pièce (filtre dur) : l'écart UI vs global mesure le coût du biais. La part « ≠ » va croître avec les lots multi-pays.

## Segments

| Segment | n | global@1 | global@5 | bande pays @1/@5 | UI@1 | UI@5 |
|---|---|---|---|---|---|---|
| Commémo (vérité) | 434 | 78.1% | 88.2% | 89.2% / 95.2% (n=434) | 89.2% | 95.2% |
| Courante (vérité) | 42 | 54.8% | 78.6% | 69.0% / 95.2% (n=42) | 69.0% | 95.2% |
| Face = obverse | 430 | 74.7% | 86.0% | 86.3% / 94.7% (n=430) | 86.3% | 94.7% |
| Face = unknown/None | 46 | 89.1% | 100.0% | 97.8% / 100.0% (n=46) | 97.8% | 100.0% |
| Crop < 200px | 0 | — | — | — | — | — | — |
| Crop ≥ 200px | 476 | 76.1% | 87.4% | 87.4% / 95.2% (n=476) | 87.4% | 95.2% |

## P3/P5 — Sims top1 et spread (global, in-scope)

- top1_sim quand top1 **correct** : n=362 min=0.593 p25=0.777 med=0.825 p75=0.863 max=0.945
- top1_sim quand top1 **faux**    : n=114 min=0.462 p25=0.641 med=0.721 p75=0.788 max=0.931
- top1_sim **hors-scope** (toujours faux) : —
- spread quand top1 correct : n=362 min=0.001 p25=0.050 med=0.097 p75=0.158 max=0.413
- spread quand top1 faux    : n=114 min=0.000 p25=0.005 med=0.011 p75=0.023 max=0.091
- spread **hors-scope** : —

## P5 — Si on s'abstenait sous un seuil top1_sim ?

| seuil | couverture (≥ seuil) | précision top1 au-dessus | % hors-scope éliminé |
|---|---|---|---|
| 0.70 | 85.5% | 83.8% | — |
| 0.74 | 76.3% | 87.1% | — |
| 0.78 | 63.0% | 88.7% | — |
| 0.80 | 54.4% | 91.1% | — |
| 0.82 | 43.9% | 91.4% | — |
| 0.84 | 32.4% | 90.3% | — |
| 0.86 | 23.3% | 90.1% | — |

### …et avec un seuil sur le spread (top1−top2) ?

| seuil spread | couverture (≥ seuil) | précision top1 au-dessus | % hors-scope éliminé | % de top1 corrects perdus |
|---|---|---|---|---|
| 0.01 | 87.0% | 84.8% | — | 3.0% |
| 0.02 | 76.7% | 91.2% | — | 8.0% |
| 0.03 | 70.2% | 94.3% | — | 13.0% |
| 0.04 | 63.2% | 97.7% | — | 18.8% |
| 0.05 | 58.2% | 97.8% | — | 25.1% |
| 0.07 | 47.1% | 99.6% | — | 38.4% |

