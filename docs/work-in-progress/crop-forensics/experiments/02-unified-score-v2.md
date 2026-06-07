# Expérience 02 — Unified score v2 (composite × area_ratio_factor)

> Suite directe de [expé 01](./01-composite-scorer-ab-d.md). Verdict
> **marginal** : v2 améliore le sort par confiance mais n'atteint
> toujours pas le seuil 70 % A+B sur BOTTOM. Conclusion : 2 signaux
> orthogonaux (composite + area_ratio) doivent être appliqués
> **séparément** comme thresholds, pas multipliés en composite global.

## But

Expé 01 a découvert un cas non couvert : les UNDERCROP SUSPECTS (cat B,
crop tiny sur le rim d'un macro shot bimétal) gardent un composite v1
haut (rim + metal présents dans le crop 224) malgré que le crop soit
trop petit par rapport au raw. On veut pénaliser ces cas en intégrant
`area_ratio` (bbox_area / min(raw)²) au score.

## Setup

`ml/scripts/crop_exp/score_crops_v2.py` :

```
area_ratio_factor = clip(area_ratio / 0.15, 0, 1)
unified_score    = composite_v1 × area_ratio_factor
```

- Seuil 0.15 calibré : median area_ratio cohorte V.3 ≈ 0.12, donc
  punir les < 0.15 marque clairement les "tiny crops".
- Préserve `composite_v1` intact dans le sidecar v2 pour A/B compare.
- Sidecar : `state/crop_scores/{run_id}_v2.json` (1 678 records).

Distribution `unified_score` cohorte V.3 :
- min 0.053  ·  p10 0.146  ·  median 0.277  ·  p90 0.822  ·  max 0.948

vs v1 :
- min 0.29  ·  p10 0.61  ·  median 0.82  ·  p90 0.93  ·  max 0.96

→ v2 spread beaucoup plus large, le multiplicateur tire des tops vers
le milieu (sain).

## Mesure

`sampler_v2.py` → HTML BOTTOM/TOP 30 par unified_score. Inspection
fullPage screenshot via chrome-devtools.

## Résultat

| Panel | Cat A | Cat B | Cat C | Cat D | A+B | D |
|---|---:|---:|---:|---:|---|---|
| BOTTOM 30 | ~3 | ~5 | ~15 | ~5 | **~27 %** | — |
| TOP 30    | ~0 | ~0 | ~5  | ~25 | — | **~85 %** |

vs expé 01 (v1) :
- BOTTOM A+B v1 = 30 % → v2 = 27 % (légère régression, dans le bruit)
- TOP D v1 = 83 % → v2 = 85 % (marginale amélioration)

**Pas de breakthrough**. Le BOTTOM reste dominé par cat C (albums
multi-pièces avec bbox isolant 1 coin = area_ratio bas mais crop OK).

## Analyse — pourquoi

Cat B (undercrop bimétal) et cat C (album multi) ont **tous les deux**
un area_ratio bas. Multiplier `composite × area_ratio_factor` les
pénalise ensemble, sans pouvoir discriminer. Or :
- Cat B = mauvais crop (à rejeter)
- Cat C = bon crop ambigu (à router en review_lot, déjà fait par pipeline)

Donc le seuil unifié n'arrive pas à les séparer.

## Verdict — marginal

v2 est légèrement mieux que v1 pour le TOP sort (raisonable amélioration
85 % vs 83 % D), mais ne corrige pas le BOTTOM (A+B = 27 % vs 30 %, sous
le seuil 70 %).

## Action

1. **Adopter v2 comme nouveau default sort** dans le panel Crop UI :
   modeste mais consistant gain sur TOP.
2. **Abandonner l'approche "score global"** pour le reject auto. À la
   place, exposer les 2 signaux indépendants côté UI/backend :
   - `composite_score < 0.2` → flag suspect cat A (pas une pièce)
   - `area_ratio < 0.05` → flag suspect cat B (undercrop bimétal)
   Les 2 thresholds sont déjà tous deux dans le payload backend
   (`composite_score`, `area_ratio`, `is_undercrop_suspect`).
3. Cat C reste géré par le pipeline routing (`review_lot` si
   `multi_coin_photo` ou `is_lot_suspected`). Hors-scope crop forensics.
4. **Théorie 01 (non-coin-circles via bg_uniformity)** non testée — à
   garder en lice si on veut spécifiquement chasser cat A au-delà du
   filtre composite.

## Data préservée

- `crop_scores/{run_id}.json` (v1 composite, intact)
- `crop_scores/{run_id}_v2.json` (v1 + area_ratio + unified, additif)
- `crop_scores/expe02_v2.png` (screenshot inspection)

Permet de re-comparer A/B futurs si on revient sur l'approche unifiée.
