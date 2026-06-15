# PLAN — Stratégie B (chunks)

> Pré-requis : le **banc partagé (Chunk 0)** existe et expose l'interface `recrop()` + les
> jeux D1/D2/D3. Sinon, le construire d'abord (cf. `../BENCHMARK.md`).

## Chunk B0 — Comprendre POURQUOI `detect_bbox_refine` échoue ici
- Diagnostiquer sur les EMU/globe : pourquoi le rim-refine actuel ne grossit pas (contour
  noyé ? Hough ne voit pas le rebord externe ? plancher/plafond ?). Visualiser.
- **Livrable** : note courte + cas illustrés. Oriente B1.

## Chunk B1 — Détecteur de rebord externe (silhouette + bimétal)
- `recrop()` : sur ROI large autour du `hint`, détecter le **cercle externe** (silhouette
  métal/fond ; modèle 2-anneaux `denom_geometry` ; Hough plus-grand-cercle-centré durci).
  Concentricité + circularité + plancher `r ≥ r_hint`. Fallback = hint.
- **Mesure** : **D1** (IoU vs cercle humain) + **D2** récupération.

## Chunk B2 — Robustesse fond encombré / capsule / non-bimétal
- Gérer capsule/coincard, fonds texturés, pièces non-bimétal (retomber sur silhouette/Hough).
- **Mesure** : D2 slice « autres » + taux de fallback.

## Chunk B3 — Gardes lots & non-régression
- Garde voisin-aware (pas de fusion 2 pièces), pas de régression sur D3c (device).
- **Mesure** : **D3** complet (rétention success, fragments coupés, géométrie device).

## Chunk B4 — Run de banc complet + RESULTS.md
- Lancer B sur D1 + D2 + D3, écrire le JSON + `RESULTS.md`.
- **Mesure** : tableau final, prêt pour le front et l'évaluateur hybride.

## (Optionnel B5) Portage scan on-device
- Si B gagne / entre dans l'hybride : porter la logique géométrique dans
  `SnapNormalizer.kt` (parité Python↔Kotlin). À cadrer après le banc.
