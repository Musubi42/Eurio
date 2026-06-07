# Expérience 05 — Anti-B sur singles uniquement (S6)

**Date** : 2026-05-27
**Théorie** : 02 (Hough sur raw) — variante conditionnelle "singles only".
**Verdict** : ❌ Marginal. Filtre singles nettoie le bruit album mais
TOP-30 cat B ≈ 35-45 %, encore loin du seuil 80 %.

---

## Objectif

Reprendre `inner_feature_score` (S5) mais en **restreignant aux raws
single** pour exclure l'antinomie B-vs-C constatée en S5. Hypothèse :
sans pollution album, TOP-30 capture cat B (vrai undercrop bimétal).

---

## Setup

Deux filtres testés :

| Filtre | Cardinalité (DE/2010) | Logique |
|---|---|---|
| `is_lot_suspected = 0` | 167/221 (76 %) | flag heuristique du pipeline |
| `n_crops_detected = 1` | 30/221 (14 %) | exactement 1 cercle détecté par le producer |

**Scripts** : `ml/scripts/crop_exp/sampler_inner_singles.py` (option
`--filter not-lot | n-crops-1`).

**Sidecar** réutilisé : `crop_scores/059dc8d9…_inner_de_2010.json` (pas
de recalcul Hough, seul le tri change).

---

## Distribution

### `is_lot_suspected=0` (167 raws)

| Métrique | Valeur |
|---|---|
| min | 0.99 |
| median | 3.57 |
| max | 6.09 |
| ≥ 1.3 | 165 / 167 (98.8 %) |

→ Pas de changement notable vs S5. Signal toujours saturé.

### `n_crops_detected=1` (30 raws)

| Métrique | Valeur |
|---|---|
| min | 1.16 |
| median | 2.71 |
| max | 5.77 |
| ≥ 2.0 | 24 / 30 (80 %) |

→ Distribution *moins* saturée (médian descend de 3.8 → 2.7) car les
vrais singles ont souvent un bbox déjà collé à la pièce. Le score >> 1
ne survit que sur de vrais macros.

---

## Mesure visuelle

Screenshots : `ml/state/crop_scores/expe06_inner_de2010_singles.png`
(filtre not-lot) + `expe06b_truesingles.png` (filtre n_crops=1, splittés
en panelA/panelB).

### Filtre `not-lot` (TOP-30)

Toujours dominé par cat C — les **collector folders** et **présentation
sets** ont `is_lot_suspected=0` (pas de cluster de cercles détectés à
l'apply, le producer voit 1 coin focal entouré de décor stylisé).

Décompte estimé sur TOP-30 :

| Catégorie | Count | Notes |
|---|---|---|
| C (collector folder / présentation) | ~20 | l'album n'est pas flaggé `lot` car layout stylisé, peu de detected circles |
| B (vrai cat B bimétal macro) | ~5-7 | macro shots avec bbox sur inner ring |
| D ou ambigu | ~3-5 | |

→ `is_lot_suspected` est **trop lenient** pour ce job. Pas d'amélioration
matérielle vs S5.

### Filtre `n_crops_detected=1` (TOP-30 ≡ tous les 30 raws, triés desc)

Beaucoup plus propre — exclut les folders multi-cercles. Sur les 10
premiers (score 5.0 → 5.8) :

| Rang | Score | Catégorie |
|---|---|---|
| 1-6 | 5.6-5.8 | ~4-5 cat B (macro bimétal, bbox sur inner ring), 1-2 cas single-coin avec bbox tight |
| 7-10 | 5.0-5.4 | ~2-3 cat B, 1-2 mild undercrop sur single |

Sur TOP-30 entier :

| Catégorie | Count estimé |
|---|---|
| B fort (bbox clairement sur inner feature) | 10-12 |
| Mild undercrop (bbox un peu petit) | 8-10 |
| Tight crop / cat D | 6-8 |
| Inconclu | 2-4 |

→ **cat B fort ≈ 33-40 %** sur TOP-30. Loin du seuil 80 %.

BOTTOM-30 (== mêmes 30 triés ascendant, scores 1.16 → ~5.7) : les
premiers cards (score ≈ 1) sont des cat D bien cadrées. Cohérent.

---

## Cause d'échec

Le score `inner_feature_score` est un **proxy d'undercrop général**, pas
un détecteur de "bimétal inner ring" spécifique. Sur les vrais singles :

- Score ≥ 5 corrèle avec macro shots (gros zoom sur la pièce) où le
  producer a vu un cercle intérieur ; OUI cat B en majorité MAIS aussi
  des cas mixtes (bbox petit sur coin in-capsule).
- Score 2-4 corrèle avec mild undercrop indiscernable de "crop OK".
- Score ≈ 1 = bbox déjà collé.

Le score ne sépare pas "bbox sur inner ring d'une vraie pièce visible"
(cat B strict) de "bbox sur une partie d'une pièce single bien
photographiée" (cat D un peu serré). Les deux ont un grand cercle
plausible dans le raw.

Pour un anti-B *spécifique*, il faudrait un signal qui mesure
**l'incohérence rim**: "y a-t-il une vraie rim manquante autour du
crop ?" (gradient circulaire à un radius supérieur au bbox). Plus
sophistiqué.

---

## Verdict

❌ **Théorie 02 morte comme post-filter anti-B**, même sur singles
filtrés.

Le signal `inner_feature_score` reste utile comme **proxy d'undercrop
général** (corrèle visuellement avec la qualité de cadrage), mais ne
remplit pas la promesse "discriminer cat B avec ≥ 80 % de précision".

---

## Action / Prochaines pistes

1. **Théorie 02 archivée** (refuted globalement). Marquer dans
   `theories/02-inner-feature-detection.md` et plan.md.
2. **Backlog priorisé** :
   - **OCR léger sur bbox** (anti-A — digits = strip). Test ciblé sur les
     raws non-pièce identifiés visuellement dans le run V.3.
   - **Re-rank Hough upstream** (modif `_hough_refine_in_roi` dans
     `normalize_snap.py`) — hors-scope "post-filter pur" mais peut-être
     nécessaire pour fixer cat B à la source. À discuter avec Raphaël.
3. **Acceptance** : si on accepte que cat A et cat B sont durs à séparer
   du reste sans modifier le producer, le chantier crop-forensics
   pourrait se clore sur le composite v1 comme tri par défaut (déjà
   livré en S2) + bench bookmark pour review manuelle. Décision produit.
