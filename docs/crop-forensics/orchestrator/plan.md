# Plan — sessions à exécuter

> **Fichier mutable.** À chaque fin de session, mets à jour les statuts
> et ajoute les sessions découvertes. Pas plus d'**un objectif par
> session**.
>
> Statuts : ⬜ pending · 🟡 in-progress · ✅ done · ❌ refuted · ⏸ paused

## Sessions

### S1 ✅ Composite scorer is_coin (théorie 04)

Verdict : asymétrique. TOP 83 % cat D, BOTTOM 30 % A+B.
→ [experiments/01](../experiments/01-composite-scorer-ab-d.md)

### S2 ✅ Brancher composite = tri par défaut UI

Backend : `_load_composite_scores` + sort `score_desc/asc`. Frontend :
badge `s 0-100` sur cards + 2 boutons sort.
→ commit `5a5184d`

### S3 ✅ Unified score v2 (composite × area_ratio_factor)

Verdict : marginal. TOP 85 % D (+2), BOTTOM 27 % A+B (-3). Théorie 04
refuted. Scoring global échoue car B et C ont tous deux area_ratio bas.
→ [experiments/02](../experiments/02-unified-score-v2.md)

### S4 ⬜ Anti-A dédié — bg_uniformity (théorie 01)

**Objectif** : tester si `std(extérieur du disque inscrit dans le crop)`
discrimine cat A (strip numérique, sticker = fond bruité) de cat D
(pièce sur fond clean).

**Setup** :
- Calculer `bg_uniformity` = écart-type des pixels gris dans l'anneau
  extérieur du crop 224×224 (zone hors disque inscrit). Faible = clean,
  élevé = bruyant.
- Persister dans `crop_scores/{run}_bg.json` (NOUVEAU sidecar, additif).
- Sampler bottom/top sur `bg_uniformity` croissant (= clean d'abord).

**Mesure** : sur 30 bottom (clean bg) vs 30 top (bruyant bg), combien
d'images dans chaque catégorie ? Seuil cible :
- ≥ 80 % des bruyants sont cat A → win
- < 20 % des clean sont cat A → win

**Action si win** : exposer `bg_uniformity` comme 2e signal indépendant
côté API + badge `bg ↑` sur card. Combiner avec composite faible
(`composite < 0.2 AND bg_uniformity > seuil`) pour reject auto cat A.

**Action si lose** : refute théorie 01, tue le signal.

### S5 ⬜ Anti-B dédié — bbox_vs_max_hough_circle (théorie 02)

**Objectif** : tester si "relancer Hough sur le RAW entier et comparer
au bbox courant" capture cat B (undercrop bimétal).

**Setup** :
- Pour chaque image_asset avec is_undercrop_suspect = True ET composite
  haut (≥ 0.5), relancer Hough sur le raw.
- Si le plus gros cercle plausible (radius >= max bbox dim × 1.3) existe,
  on flag "probable inner feature".
- Persister `inner_feature_score` dans `crop_scores/{run}_bbox.json`.

**Mesure** : top-30 inner_feature_score → combien sont cat B
authentiques (bimétal bien cropé sur intérieur) ? Cible ≥ 80 %.

### S6 ⬜ Reject auto à 2 thresholds indépendants

Pré-requis : S4 OU S5 win.

**Objectif** : poser un `auto_reject_reason` calculé côté backend en
combinant les 2 signaux :
- `composite < 0.2 AND bg_uniformity > t_bg` → `reject: not_a_coin`
- `area_ratio < 0.05 AND inner_feature_score > t_inner` → `reject: undercrop_b`

**UI** : ajouter sort `reject_first` + filter `auto_rejects_only`.
**Pas de modification de la DB** (pas de status auto-rejected) — seulement
calcul dérivé. Le pipeline ingère, l'orchestrateur affiche.

### S7 ⬜ Adopter v2 comme default sort (au choix)

Si on veut pousser le tri v2 (composite × area_ratio_factor) dans le
backend. Petit changement : `_load_composite_scores` lit le sidecar
`_v2.json` si présent, sinon `.json`. Pas urgent — v1 est déjà OK.

### S8 ⏸ Théorie 03 — area_ratio noisy

Marqué pausée : on a déjà appris en S3 que area_ratio est utile mais
insuffisant seul. À reprendre seulement si on veut un seuil adaptatif
par cat de raw (album vs single).

## Backlog (idées non-priorisées)

- OCR léger sur la bbox pour détecter cat A (digits = strip)
- Couleur dominante : bronze/cuivre/argent → metal, sinon flag
- Périodicité radiale : un strip a une période courte, une pièce non
- Adaptive area_ratio threshold selon raw dimensions / aspect
- Crop quality histogram par groupe (DE-2010 a 73 % undercrops vs FR-2018 38 %)
