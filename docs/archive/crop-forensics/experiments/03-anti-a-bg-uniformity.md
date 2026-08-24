# Expérience 03 — Anti-A : bg_uniformity + near_white_ratio (S4)

**Date** : 2026-05-26  
**Théorie** : 01 (anti-A via fond extérieur ou luminosité intérieure)  
**Verdict** : ❌ Refuted

---

## Objectif

Tester si un signal de fond / luminosité discrimine cat A (strip numérique,
sticker) de cat D (pièce sur fond propre) — indépendamment du composite.

---

## Setup — tentative 1 : bg_uniformity

**Signal** : `std(pixels gris hors disque inscrit dans le crop 224×224)`.  
Hypothèse : fond bruité (digits autour) → std élevé = cat A ; fond uni = std
faible = cat D.

**Résultat** :

| Métrique | Valeur |
|---|---|
| bg_uniformity = 0 | **80.9 %** des 1 678 crops |
| p90 | 0.13 |
| max | 36.43 |

**Cause d'échec** : `normalize_snap` applique un hard mask circulaire (fond →
noir) sur TOUS les crops avant stockage. Le fond extérieur est uniformément 0
→ std = 0. Signal dégénéré sur ce run.

---

## Setup — tentative 2 : near_white_ratio (révisée)

**Signal** : fraction de pixels avec V > 220 (HSV) DANS le disque intérieur
(80 % du rayon). Proxy pour "fond blanc/papier visible à l'intérieur du crop".

**Hypothèse révisée** : strip numérique = blanc dominant (papier blanc +
quelques digits noirs). Pièce = métallique, pas blanc pur.

**Sidecar** : `ml/state/crop_scores/059dc8d9…_bg.json` (champ
`near_white_ratio`).

**Distribution** :

| Percentile | near_white_ratio |
|---|---|
| min | 0.000 |
| p10 | 0.000 |
| median | 0.024 |
| p90 | 0.403 |
| max | 0.964 |

---

## Mesure visuelle — TOP 10

Inspection du zoom `expe04_top10_zoom.png` (near_white_ratio 0.96 → 0.87) :

| Rang | Score | Catégorie visuelle | Notes |
|---|---|---|---|
| 1 | 0.964 | **A** | Fond à pois décoratifs, pas une pièce |
| 2 | 0.963 | D (FP) | Pièce dorée surexposée, blanchie |
| 3 | 0.962 | D (FP) | Idem |
| 4 | 0.937 | D (FP) | Pièce argentée très claire sur fond blanc |
| 5 | 0.927 | D (FP) | Pièce dorée/bimétal |
| 6 | 0.921 | D (FP) | Pièce cuivrée sur fond clair |
| 7 | 0.896 | D (FP) | Pièce overexposée |
| 8 | 0.896 | D (FP) | Pièce sur fond blanc |
| 9 | 0.800 | D (FP) | Pièce pâle sur fond blanc |
| 10 | 0.871 | Inconclu | Fond très clair, structure ambiguë |

**Cat A dans TOP 10 : 1/10 ≈ 10 %**. Seuil win = ≥ 80 % → **FAIL**.

---

## Cause racine

Les pièces euro photographiées avec flash ou sur lightbox ont V >> 220 sur les
zones métalliques (spéculaires). near_white_ratio ne discrimine pas
"blanc de papier" vs "blanc de métal réfléchissant". Le signal est corrélé à
l'exposition photographique, pas au type d'objet.

---

## Verdict

❌ **Théorie 01 refuted** — les deux proxies de fond/luminosité échouent :

1. `bg_uniformity` : dégénéré (normalize_snap masque toujours le fond en noir).
2. `near_white_ratio` : trop de faux positifs cat D (surexposés). TOP-30 ≈ 10 %
   cat A, loin du seuil 80 %.

---

## Action

- Théorie 01 marquée ❌ dans plan.md.
- Passer à **S5 — anti-B via Hough on raw** (`bbox_vs_max_hough_circle`).
- **Backlog** : OCR léger sur bbox (digits = strip) reste une piste viable pour
  anti-A si S5 réussit et qu'on veut ensuite clore anti-A.
