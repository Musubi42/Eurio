# RESULTS — Stratégie B (détection géométrique du rebord externe)

> Mesuré sur le banc partagé (`ml/bench/crop_recovery/`), jeux D1/D2/D3 figés.
> Probe **gelée** (oracle, τ=0,55). B **n'appelle jamais la probe** (géométrie pure → tourne
> aussi on-device). Code : `ml/bench/crop_recovery/strategy_b.py`.
> JSON : `state/crop_recovery/run_B_bimetal_rim.json`. Session 2026-06-15.

## TL;DR

- **Le diagnostic B0 est vérifié et plus dur qu'annoncé** : la détection se rabat sur le
  **motif central** (pas le disque interne) → la pièce entière fait **≈ 3,0× r_hint**.
  `detect_bbox_refine` échoue car (1) son plafond `2,6× r_hint` est **sous** le rebord et
  (2) il se cale sur le **joint bimétal** (1,77×, très contrasté), pas sur le rebord externe.
- **B implémenté** = silhouette métal/fond (recentre + redimensionne) + secours joint→rebord,
  100% géométrique, fallback = garder le hint (aucune dégradation).
- **B récupère 38% de D2 EMU/globe**, gardes D3 tenues (D3a 100%, D3b 0%), IoU D1 0,606.
- **⚠️ CORRECTION (comparaison avec A) : mon « plafond ~51% » était FAUX.** A:score_search
  récupère **86%** avec des crops **corrects** (vérifié visuellement). Head-to-head D2 :
  both=115, **A-only=148, B-only=0**, neither=42 → B est un **sous-ensemble strict de A**, et
  le vrai irrécupérable n'est que **~14%** (pas 49%). Mon oracle de plafond plafonnait le
  rayon à 4× r_hint — fatal car **r_hint est souvent un point minuscule** (médiane 0,055×
  petit-côté) : la vraie pièce est à **8× r_hint en médiane** sur les cas que B rate.
- **Cause racine de l'échec de B** : B **ancre tout sur r_hint** (ROI 3,6×, plafond 4,5×).
  Quand la détection accroche un point minuscule, la pièce est **hors de la ROI de B** → B ne
  peut pas la voir. Défaut **réparable** (ré-ancrer sur l'échelle absolue de l'image), pas un
  plafond. **Sur ce corpus, A domine ; B tel quel est dominé.**
- B garde un intérêt **on-device** (zéro probe, D3b 0%) mais doit être ré-ancré pour être
  compétitif. A est **serveur-only** (26 appels DINO/cas) et **viole D3b (4% > 2%)**.

## B0 — Pourquoi `detect_bbox_refine` échoue ici (vérifié sur données réelles)

Mesuré sur les EMU/globe de D2 (`/tmp/b0_diag*.py`, 80–305 cas) :

1. **La détection accroche le MOTIF CENTRAL, pas le disque interne.** Le rayon qui maximise
   la probe (oracle, sweep centré) = **3,0× r_hint** (médiane). La pièce entière est ~3× le
   crop prod — pire que les 2,2–2,6× estimés en session 2.
2. **`detect_bbox_refine` ne PEUT pas rendre ce rebord** : plafond `_REFINE_R_CEIL = 2,6×
   r_hint` < rebord réel (3×). Même détecté, `_accept` le rejette.
3. **Il se cale sur le joint bimétal** : rayon médian rendu **1,77× r_hint** = anneau
   argent↔or (fort contraste), pas le rebord externe argent↔fond (faible contraste).
   Distribution méthode (60 cas) : hough 36 / contour 15 / hint_kept 9.

| estimateur (échantillon EMU/globe) | ratio r/r_hint (méd.) | % pass τ=0,55 |
|---|---|---|
| oracle = sweep **centré** argmax-score | 3,0 | 50% |
| **silhouette** (Otsu métal/fond, **recentré**) | 3,4 | **56%** |
| joint→rebord (×1/0,70) | 3,0 | 41% |

→ Le **recentrage** (silhouette) bat le sweep centré. ⚠️ Ces % (50/56/41) **sous-estiment** le
récupérable : le sweep ne montait qu'à 3,4× r_hint, or quand r_hint est un éclat la pièce est
à 8×+ (cf. comparaison A). Le ratio médian 3,0× est trompeur — la variance de r_hint est énorme.

## B1/B2 — Stratégie implémentée

`recrop()` retourne 0–2 candidats **géométriques** (coords natives), jamais la probe :
- ① **`B:silhouette`** (primaire) : Otsu métal/fond dans une ROI 3,6×r_hint ; **fitEllipse**
  sur les contours externes → centre + rayon (`major/2`) du rebord. Recentre + rescale.
  Garde = **axis_ratio ≥ 0,62** (rond) + concentricité au hint + plancher/plafond de rayon.
- ② **`B:bimetal_joint`** (secours) : cercle Hough le plus contrasté centré = joint argent/or,
  rebord prédit `R = r_joint / 0,70`. Robuste si le fond ne contraste pas ; muet sur monométal.
- **Fallback** : rien trouvé → liste vide → le harness garde le baseline (aucune dégradation).

**Itérations mesurées (pourquoi ces choix) :**
- Le garde `fill` vs **cercle-englobant** (minEnclosingCircle) **tuait le rappel** (76%→22%) :
  un arc de rebord part. + une pointe parasite gonfle le cercle englobant alors que le fit
  reste rond. Remplacé par **axis_ratio (fitEllipse)** → rappel silhouette 11%→57%, D2 14%→38%.
- **La calibration de rayon n'apporte rien** : best-radius autour du centre silhouette = 64%
  vs 60% au rayon `major/2` (médiane du meilleur multiplicateur = 1,00). Le cercle silhouette
  est géométriquement juste → on n'ajoute pas de rayons (ce serait du ressort de A).

## Résultats banc — run complet `B:bimetal_rim` (τ=0,55)

| jeu | métrique | **B** | baseline | cible/garde | verdict |
|---|---|---|---|---|---|
| **D2** récupération EMU/globe | % pass après recrop | **38%** | 0% | ≥70% | ❌ (A fait 86%, voir comparaison) |
| **D1** gold géométrie (post-fix hint) | IoU médian | **0,799** | 0,67 | ≥0,80 | ⚠️ ≈ cible (0,606 avant fix bug D1) |
| D1 — % IoU ≥ 0,8 | — | 50% | — | — | — |
| **D3a** rétention success | % rétention | **100%** | 100% | ≥98% | ✅ |
| **D3b** fragments | % faux-accept | **0%** | 0% | ≤2% | ✅ |

Détail D2 (run D2-only, 305 cas) : silhouette se déclenche 174× (57%), **passe 57%** quand
déclenchée (médiane score 0,70) ; joint se déclenche 116×, passe 26%. Choix harness : 124
silhouette / 73 joint / 108 baseline.

**D1 (IoU 0,799 post-fix, ≈ cible 0,80)** : après correction du bug hint (§Bug D1), B passe
de 0,606 à **0,799** — quasi à la cible. Reste un léger plafond : (a) le `gold_circle` est le
**cercle inscrit du rectangle humain**, un peu plus serré que le rebord réel → un crop-rebord
correct plafonne en IoU contre cette vérité ; (b) sur les « autres » (non EMU/globe), B
grossit parfois un peu. L'écart résiduel avec A (0,868) tient au même angle mort r_hint.

## Comparaison A ↔ B ↔ hybride (évaluateur `--hybrid`, scores cachés, pas de re-run)

`.venv/bin/python -m scripts.run_crop_recovery_bench --hybrid run_A_score_search.json,run_B_bimetal_rim.json`

> ⚠️ **D1 corrigé** (bug hint partagé sur planches multi-pièces, cf. §« Bug D1 » plus bas) :
> les IoU D1 ci-dessous sont **post-fix** (hint par pièce). Avant fix : A 0,765 / B 0,606 —
> déflatés car 19% des cas D1 partageaient le hint dominant.

| métrique | **A:score_search** | **B:bimetal_rim** | **hybride A∪B (argmax)** |
|---|---|---|---|
| D2 récup EMU/globe | **86%** | 38% | **86%** |
| D1 IoU médian (post-fix) | **0,868** ✅ | 0,799 | **0,878** ✅ |
| D1 % IoU ≥ 0,8 (post-fix) | 67% | 50% | **70%** |
| D1 IoU baseline (post-fix) | 0,67 | 0,67 | 0,67 |
| D3a rétention | 100% | 100% | 100% |
| D3b faux-accept | **4% ❌** | **0% ✅** | **4% ❌** |
| coût | 26 DINO/cas (**serveur**) | 0 — géométrie (**on-device**) | serveur |

> Post-fix : **A clears la cible IoU** (0,868), l'**hybride** la dépasse et atteint **70% de
> cas IoU≥0,8** ; **B est juste sous** (0,799). Le fix a levé A 0,765→0,868 et B 0,606→0,799.
> Conclusions inchangées : A domine la récup (86% vs 38%, B reste sous-ensemble strict) ;
> seul **B respecte D3b** et tourne **on-device**.

**Head-to-head D2** (305 cas) : both=115, **A-only=148, B-only=0**, neither=42. → **B est un
sous-ensemble strict de A** : il ne récupère rien qu'A ne récupère, et A récupère 148 cas de
plus. Le **vrai irrécupérable = 42 (~14%)** (coincards/proof/tilt, vérifiés visuellement),
**pas 49%**.

**Pourquoi B perd (cause racine, vérifiée)** : sur les 148 cas B-rate/A-passe, A choisit un
rayon **médian 8,1× r_hint** (70% au-delà du plafond 4,5× de B) et **r_hint = point minuscule**
(médiane 0,055× petit-côté ; 68% < 0,08). La détection accroche un éclat du motif → la pièce
est **hors de la ROI 3,6×r_hint de B**. Les crops d'A à grand rayon sont **corrects** (audit
`/tmp/cmp_a_big.png` : pièces entières bien cadrées, le hint rouge est un point). Donc **mon
oracle « plafond ~51% » était faux** : il plafonnait le rayon à 4× r_hint.

**Le D1 gold (vrai bon crop humain) passe 97%** → la probe est saine ; ce n'est pas elle le
facteur limitant, c'est l'**ancrage sur r_hint** de B.

## Bug D1 — hint partagé sur les planches multi-pièces (trouvé via la vue par-raw, 2026-06-15)

**Symptôme** (repéré à l'œil dans la vue par image brute) : une planche de 7 pièces affichait
**7 crops identiques** (la même pièce), scores 0,93 ×7, IoU 0,91 pour 1 cas et 0,00 pour les 6
autres.

**Cause** : `build_d1` ne passait pas de `hint_of` → il retombait sur `detect_hint` (détection
**dominante** de toute l'image). Les N image_assets d'une planche recevaient donc **le même
hint** (la pièce dominante). `recrop(raw, hint)` étant **mono-pièce**, il sortait N fois le même
crop. Touchait **89/458 cas D1 (19%)**, 20 planches. (D2 = single-coin, intact ; D3a déjà
correct via `hint_of` = bbox du crop accepté.)

**Effet** : IoU D1 **déflaté des deux côtés** (les N−1 cas non-dominants scoraient IoU≈0). Le
classement A>B tenait (même biais), mais l'absolu était faux.

**Fix** (`build_d1`, `hint_of`) : re-détection multi-pièces (`detect_circles_multi`, cachée par
raw) → la détection prod **la plus proche du gold de CHAQUE pièce** (fallback = hint dégradé
centré sur la pièce si aucune détection proche). Vérifié : la planche 7-pièces a maintenant
**7 hints distincts** (dist 0–8 px au gold) ; 436/458 cas usent une vraie détection, 22 le
fallback. **Après fix** : B IoU D1 **0,606 → 0,799**, A **0,765 → 0,868** (clears la cible),
hybride **0,790 → 0,878** ; baseline D1 0,29 → 0,67.

**Leçon** ([[feedback-handoff-quality]]) : la vue par-raw a servi d'**auditeur** — un crop
répété N fois saute aux yeux là où une métrique agrégée le noie. Sans elle, l'IoU D1 serait
resté faussement bas et la conclusion « B sous la cible IoU » fausse.

## Verdict & pistes

- **Sur ce corpus, A domine ; B tel quel est dominé** (sous-ensemble strict). L'« avantage IoU
  géométrique » espéré pour B ne se matérialise pas (A 0,765 > B 0,606) car B ne voit même pas
  la pièce quand r_hint est un éclat.
- **Réparer B (si on veut une option on-device)** : **dé-ancrer de r_hint**. ROI = plein cadre
  ou fraction absolue de l'image ; hypothèses de rayon en **fraction du petit-côté** (comme les
  `_RADIUS_ABS_FRAC` d'A), pas en multiples de r_hint. La silhouette Otsu+fitEllipse reste
  valable, mais à l'échelle image. C'est le vrai chunk B « robustesse » à faire.
- **Côté serveur**, **A (ou l'hybride)** est le candidat — 86% récup, IoU 0,79. **Mais il faut
  régler D3b (4% > 2%)** : borner la plausibilité (rayon/centre) ou pré-filtrer les fragments.
  L'hybride n'ajoute que +0,025 d'IoU sur A et hérite du même 4% → pas d'intérêt net vs A seul
  tant que B n'est pas réparé.
- **Joint→rebord** bruité (26%) : 1er cercle Hough ≠ toujours le joint ; valider par couleur
  LAB (`denom_geometry`). Marginal tant que l'ancrage r_hint n'est pas réglé.
- **On-device** : la logique silhouette est portable dans `SnapNormalizer.kt`, mais **seulement
  après** le dé-ancrage (sinon elle hérite du même angle mort).
