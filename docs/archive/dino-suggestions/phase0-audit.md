# Phase 0 — Audit suggestions Dino

- Banque : `2eur_commemo` — 508 ancres, encodeur `dinov2-vits14`, bâtie le 2026-06-02T23:17:18+00:00
- Set labellisé : 478 crops décidés en review (`review_queue.status='done'` + `decided_eurio_id`)
- Sans prédiction Dino persistée : 3 (0.6%)

## P1 — Couverture de scope (vraie pièce dans la banque ?)

- In-scope : 436 (91.2%)
- Hors-scope : 42 (8.8%)
  - dont courantes (is_commemorative=0) : 42
  - dont commémo absentes de la banque : 0

> ⚠️ Biais de sélection : le pipeline ne prédit/enqueue que les listings ciblés 2€ commémo. Les lots de courantes (cas kickoff) sont encore majoritairement `open` — le % hors-scope réel en production est plus haut que sur ce set décidé.

## Recall (sur crops avec prédiction)

| Segment | n | global@1 | global@5 | bande pays @1/@5 | UI@1 | UI@5 |
|---|---|---|---|---|---|---|
| Tous (avec prédiction) | 475 | 48.8% | 65.3% | 67.2% / 82.7% (n=473) | 66.9% | 82.7% |
| In-scope (vérité dans banque) | 433 | 53.6% | 71.6% | 73.8% / 90.7% (n=431) | 73.4% | 90.8% |
| Hors-scope | 42 | 0.0% | 0.0% | 0.0% / 0.0% (n=42) | 0.0% | 0.0% |

## P2 — Effet du biais pays (in-scope uniquement)

| Segment | n | global@1 | global@5 | bande pays @1/@5 | UI@1 | UI@5 |
|---|---|---|---|---|---|---|
| Pays vérité == pays cible | 430 | 54.0% | 71.6% | 74.0% / 90.9% (n=430) | 74.0% | 90.9% |
| Pays vérité ≠ pays cible | 1 | 0.0% | 0.0% | 0.0% / 0.0% (n=1) | 0.0% | 0.0% |
| Pas de pays cible | 2 | 0.0% | 100.0% | — / — (n=0) | 0.0% | 100.0% |

> Sur « vérité ≠ cible », la bande pays ne peut PAS contenir la bonne pièce (filtre dur) : l'écart UI vs global mesure le coût du biais. La part « ≠ » va croître avec les lots multi-pays.

## Segments

| Segment | n | global@1 | global@5 | bande pays @1/@5 | UI@1 | UI@5 |
|---|---|---|---|---|---|---|
| Commémo (vérité) | 433 | 53.6% | 71.6% | 73.8% / 90.7% (n=431) | 73.4% | 90.8% |
| Face = obverse | 387 | 50.1% | 68.2% | 70.6% / 89.6% (n=385) | 70.3% | 89.7% |
| Face = unknown/None | 46 | 82.6% | 100.0% | 100.0% / 100.0% (n=46) | 100.0% | 100.0% |
| Crop < 200px | 0 | — | — | — | — | — | — |
| Crop ≥ 200px | 433 | 53.6% | 71.6% | 73.8% / 90.7% (n=431) | 73.4% | 90.8% |

## P3/P5 — Sims top1 et spread (global, in-scope)

- top1_sim quand top1 **correct** : n=232 min=0.261 p25=0.787 med=0.836 p75=0.870 max=0.969
- top1_sim quand top1 **faux**    : n=201 min=0.226 p25=0.689 med=0.761 p75=0.823 max=0.898
- top1_sim **hors-scope** (toujours faux) : n=42 min=0.569 p25=0.778 med=0.834 p75=0.851 max=0.903
- spread quand top1 correct : n=232 min=0.000 p25=0.024 med=0.047 p75=0.074 max=0.154
- spread quand top1 faux    : n=201 min=0.000 p25=0.003 med=0.010 p75=0.021 max=0.099
- spread **hors-scope** : n=42 min=0.000 p25=0.002 med=0.006 p75=0.014 max=0.045

## P5 — Si on s'abstenait sous un seuil top1_sim ?

| seuil | couverture (≥ seuil) | précision top1 au-dessus | % hors-scope éliminé |
|---|---|---|---|
| 0.70 | 83.4% | 55.1% | 14.3% |
| 0.74 | 74.3% | 57.2% | 19.0% |
| 0.78 | 62.9% | 60.5% | 26.2% |
| 0.80 | 54.7% | 63.8% | 38.1% |
| 0.82 | 45.7% | 64.5% | 38.1% |
| 0.84 | 35.2% | 64.7% | 52.4% |
| 0.86 | 22.3% | 72.6% | 78.6% |

### …et avec un seuil sur le spread (top1−top2) ?

| seuil spread | couverture (≥ seuil) | précision top1 au-dessus | % hors-scope éliminé | % de top1 corrects perdus |
|---|---|---|---|---|
| 0.01 | 67.2% | 64.9% | 66.7% | 10.8% |
| 0.02 | 50.7% | 74.3% | 83.3% | 22.8% |
| 0.03 | 41.5% | 81.7% | 90.5% | 30.6% |
| 0.04 | 33.3% | 83.5% | 92.9% | 43.1% |
| 0.05 | 25.3% | 91.7% | 100.0% | 52.6% |
| 0.07 | 14.3% | 94.1% | 100.0% | 72.4% |

