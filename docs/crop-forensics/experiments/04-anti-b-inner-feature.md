# Expérience 04 — Anti-B : inner_feature_score (S5)

**Date** : 2026-05-27
**Théorie** : 02 (Hough relancé sur le RAW + comparaison au bbox courant)
**Verdict** : ❌ Refuted comme anti-B *spécifique* — le signal flag B et C ensemble.

---

## Objectif

Tester si `raw_max_hough_circle_diameter / bbox_max_dim` discrimine cat B
(undercrop bimétal sur feature interne) du reste.

Hypothèse : sur une vraie cat B, le bbox courant est petit, mais en relançant
Hough sur le raw complet on retrouve la pièce entière → ratio >> 1.

## Setup

**Script** : `ml/scripts/crop_exp/score_crops_inner.py`.

Pour chaque image_asset :
1. Charge le raw natif.
2. Downscale à 1024 sur le short side, blur médian.
3. HoughCircles permissif (`param1=80, param2=30, rmin=8%, rmax=48%`).
4. Filtre **les cercles qui contiennent le centre du bbox courant** (sinon
   dans un album multi-pièces on flaggerait n'importe quoi).
5. Retient le plus grand → `raw_max_circle_diameter`.
6. `inner_feature_score = raw_max_circle_diameter / max(bbox.w, bbox.h)`.

**Scope** : restreint à **DE / 2 € / 2010** (221 assets, 74 raws), groupe
identifié dans `vision.md` comme foyer historique du bug bimétal.

**Sidecar** : `ml/state/crop_scores/059dc8d9…_inner_de_2010.json`.

**Sampler** : `scripts/crop_exp/sampler_inner.py` → TOP 30 / BOTTOM 30.

---

## Distribution

| Métrique | Valeur |
|---|---|
| min | 0.99 |
| p10 | 2.23 |
| median | 3.82 |
| p90 | 5.09 |
| max | 6.09 |
| score ≥ 1.3 | 219 / 221 (99.1 %) |
| score ≥ 2.0 | 211 / 221 (95.5 %) |

→ **Signal saturé**. Cohérent avec "DE-2010 = 73 % undercrops" (backlog
plan.md). Comme threshold binaire, inutile. Reste à mesurer comme *ranking*.

---

## Mesure visuelle

Screenshot `ml/state/crop_scores/expe05_inner_de2010.png` (3840×7444 px,
splittée en `_panelA_bottom30.png` et `_panelB_top30.png`).

### TOP 30 (score 4.7 → 6.1)

Distribution catégorielle approximative :

| Catégorie | Count | Notes |
|---|---|---|
| C (album multi-pièces) | ~22 | bbox correct sur 1 coin, Hough trouve un cercle plus large couvrant la planche ou un objet décoratif |
| B (vrai undercrop bimétal) | ~4 | macro shots DE-2010 avec bbox tiny sur le ring intérieur ou millésime |
| D (bien cropé, single coin) | ~3 | faux positifs où Hough fitte sur un bord parasite |
| A | 0 | filtré par la contrainte "circle contient bbox center" |
| Inconclu | 1 | ambigu |

**Cat B dans TOP-30 ≈ 13 %**. Seuil win = ≥ 80 % → **FAIL** (très loin).

### BOTTOM 30 (score 0.99 → ~1.7)

| Catégorie | Count | Notes |
|---|---|---|
| D (single coin bien cadré) | ~24 | bbox approxime déjà la pièce, ratio ≈ 1 |
| C (couples / sets compact) | ~4 | bbox correct sur une des coin, Hough sature au cap |
| Autres / inconclu | ~2 | |

→ BOTTOM se comporte conformément à l'hypothèse : "score ≈ 1 ⇒ bbox déjà
collé à la pièce". OK pour un sort default si on voulait mettre le best en
haut, mais le composite v1 fait déjà ça.

---

## Cause d'échec

Le filtre "circle contains bbox center" écarte bien cat A (strip — pas de
grand cercle contenant le bbox) mais **ne sait pas distinguer** :

- une vraie cat B (bbox = inner feature d'une pièce qui contient légitimement
  le bbox) ;
- une cat C (bbox = pièce K dans un album ; Hough trouve un cercle plus
  large autour de la planche, du décor, ou d'un coin adjacent dont la
  position fait que ledit cercle contient *par hasard* le centre du bbox).

Dans un album, les raws ont énormément de candidates Hough (chaque coin
génère sa propre détection) et le maxRadius cap (~48 %) garantit qu'il y
aura toujours un grand cercle plausible. La probabilité qu'un de ces grands
cercles englobe géométriquement le bbox d'une coin centrale est élevée.

C'est exactement l'antinomie A vs B vs C des findings/01 : **un signal
unique ne peut pas séparer les 3** sans s'appuyer sur un attribut externe.

---

## Verdict

❌ **Théorie 02 refuted comme anti-B pur**.

Le score discrimine bien "bbox-fit-coin" (BOTTOM cat D) de
"bbox-tiny-vs-grosse-zone" (TOP B+C mélangés), mais le mélange B+C est
exactement ce qu'on voulait éviter (cf. evolution-log 2026-05-26 entry 1 :
"composite × area_ratio échoue car B et C ont tous deux area_ratio bas").

---

## Action / Piste suivante

Le signal **reste exploitable conditionnellement** : si on le croise avec
`source_images.is_lot_suspected`, on isole probablement cat B (puisque cat
C aura `is_lot_suspected=1`).

→ Nouvelle session **S6 — inner_feature_score × is_lot_suspected** : ne
garder que les raws non-lot, re-sampler TOP-30. Si cat B y monte ≥ 80 %,
théorie 02 est *partiellement validée* (anti-B uniquement sur singles).

Sinon, anti-B reste open. Backlog : OCR sur bbox (digits = anti-A),
re-rank Hough candidates en upstream (modif `_hough_refine_in_roi` —
hors-scope post-filter, mais cf. fix prédit dans theories/02).
