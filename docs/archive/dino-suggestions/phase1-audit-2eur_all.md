# Phase 0 — Audit suggestions Dino

- Banque : `2eur_all` — 546 ancres, encodeur `dinov2-vits14`, bâtie le 2026-06-11T00:15:34+00:00
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
| Tous (avec prédiction) | 476 | 55.9% | 73.5% | 74.8% / 92.2% (n=476) | 74.8% | 92.2% |
| In-scope (vérité dans banque) | 476 | 55.9% | 73.5% | 74.8% / 92.2% (n=476) | 74.8% | 92.2% |
| Hors-scope | 0 | — | — | — | — | — | — |

## P2 — Effet du biais pays (in-scope uniquement)

| Segment | n | global@1 | global@5 | bande pays @1/@5 | UI@1 | UI@5 |
|---|---|---|---|---|---|---|
| Pays vérité == pays cible | 475 | 56.0% | 73.7% | 74.9% / 92.4% (n=475) | 74.9% | 92.4% |
| Pays vérité ≠ pays cible | 1 | 0.0% | 0.0% | 0.0% / 0.0% (n=1) | 0.0% | 0.0% |
| Pas de pays cible | 0 | — | — | — | — | — | — |

> Sur « vérité ≠ cible », la bande pays ne peut PAS contenir la bonne pièce (filtre dur) : l'écart UI vs global mesure le coût du biais. La part « ≠ » va croître avec les lots multi-pays.

## Segments

| Segment | n | global@1 | global@5 | bande pays @1/@5 | UI@1 | UI@5 |
|---|---|---|---|---|---|---|
| Commémo (vérité) | 434 | 56.2% | 74.2% | 76.0% / 92.2% (n=434) | 76.0% | 92.2% |
| Courante (vérité) | 42 | 52.4% | 66.7% | 61.9% / 92.9% (n=42) | 61.9% | 92.9% |
| Face = obverse | 430 | 53.0% | 70.7% | 72.1% / 91.4% (n=430) | 72.1% | 91.4% |
| Face = unknown/None | 46 | 82.6% | 100.0% | 100.0% / 100.0% (n=46) | 100.0% | 100.0% |
| Crop < 200px | 0 | — | — | — | — | — | — |
| Crop ≥ 200px | 476 | 55.9% | 73.5% | 74.8% / 92.2% (n=476) | 74.8% | 92.2% |

## P3/P5 — Sims top1 et spread (global, in-scope)

- top1_sim quand top1 **correct** : n=266 min=0.574 p25=0.801 med=0.841 p75=0.872 max=0.969
- top1_sim quand top1 **faux**    : n=210 min=0.414 p25=0.729 med=0.785 p75=0.834 max=0.896
- top1_sim **hors-scope** (toujours faux) : —
- spread quand top1 correct : n=266 min=0.000 p25=0.023 med=0.045 p75=0.069 max=0.160
- spread quand top1 faux    : n=210 min=0.000 p25=0.003 med=0.008 p75=0.018 max=0.146
- spread **hors-scope** : —

## P5 — Si on s'abstenait sous un seuil top1_sim ?

| seuil | couverture (≥ seuil) | précision top1 au-dessus | % hors-scope éliminé |
|---|---|---|---|
| 0.70 | 90.1% | 60.1% | — |
| 0.74 | 82.4% | 62.2% | — |
| 0.78 | 69.3% | 66.4% | — |
| 0.80 | 60.5% | 69.8% | — |
| 0.82 | 50.8% | 71.5% | — |
| 0.84 | 38.9% | 73.5% | — |
| 0.86 | 25.6% | 82.8% | — |

### …et avec un seuil sur le spread (top1−top2) ?

| seuil spread | couverture (≥ seuil) | précision top1 au-dessus | % hors-scope éliminé | % de top1 corrects perdus |
|---|---|---|---|---|
| 0.01 | 69.3% | 72.1% | — | 10.5% |
| 0.02 | 52.3% | 81.9% | — | 23.3% |
| 0.03 | 43.5% | 87.9% | — | 31.6% |
| 0.04 | 34.9% | 88.6% | — | 44.7% |
| 0.05 | 26.1% | 93.5% | — | 56.4% |
| 0.07 | 14.3% | 97.1% | — | 75.2% |

