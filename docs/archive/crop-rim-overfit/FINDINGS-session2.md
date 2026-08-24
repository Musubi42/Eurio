> # ⚠️ CORRECTION (session 3) — la conclusion de ce doc est FAUSSE
> Ce doc conclut « c'est la probe, pas le crop ». **C'est l'inverse : c'est bien le CROP**
> (le HANDOFF d'origine avait raison). Le contrefactuel ci-dessous est **bancal** : il prend
> la **bbox YOLO comme pièce entière**, or sur le bimétal à motif central la détection se
> rabat sur le **disque interne** → la « pièce pleine » testée était encore le disque.
> Preuve décisive : les **crops validés-main** de l'EMU/globe scorent **0,87 / passent 86%**
> sur la probe actuelle ; un **balayage de rayon** fait monter le score 0,19→0,76 (pièce
> entière ≈ 2× le rayon détecté). **La probe va bien.** Suite et solution :
> `docs/work-in-progress/crop-recovery/VISION.md`. Le reste ci-dessous est conservé pour
> l'historique + l'outillage (`measure_crop_undercrop.py` reste utile), mais **ignorer la
> conclusion**.

# FINDINGS — Session 2 (2026-06-15) : le diagnostic du HANDOFF est RÉFUTÉ par la mesure

> Suite de `HANDOFF.md`. La session 1 affirmait : *« c'est un problème de crop, pas de
> gate ni de probe ; ne PAS ré-entraîner la probe d'abord ; un crop plein-rebord
> remonterait mécaniquement le score »*. **On a construit la mesure manquante et
> testé cette thèse. Elle est fausse sur tous les axes.** Doctrine respectée :
> benchmark-first, label-free, aucun entraînement lourd (Mac). Travail NON committé.

---

## 0. TL;DR (corrigé)

Sur le run `fa8a9af939ce43e6a3eee6842ecae170` (AT/2009 EMU + AT/2012 « 10 ans euro cash »,
341/562 zero_crops) :

1. **L'undercrop est réel** (~50 % des vraies pièces croppent < 0,85·rebord), étage de
   **sélection** (`_hough_refine_in_roi`) = 1er coupable.
2. **MAIS le crop n'est PAS la cause des faux négatifs.** Cropper la MÊME pièce
   plein-rebord (r = r_bbox YOLO) ne récupère que **~10 %** au gate. Le contrôle
   `success` (221 coins des MÊMES designs qui passent) a un undercrop **identique** (63 %).
3. **La probe préfère les crops SERRÉS** : sur `success`, serré → score 0,80 / passe 77 %,
   plein → 0,62 / passe 52 % (**Pearson −0,27**). La thèse « plein-rebord = meilleur score »
   est **à l'envers**.
4. **Vraie cause = la probe fragment est OOD sur ces commémo.** Plein-rebord, par design :
   **EMU 2009 score médian 0,044 → passe 2 %** ; AT-2012 globe 0,314 → 15 %. Ce sont de
   vrais 2€ **propres et bien cadrés** que la probe classe « fragment » (voir montage
   `_worst_scored.png` : score 0,008–0,05 sur des globes pleins nets).

→ **Le déblocage des zero_crops, c'est la PROBE, pas le crop.** Le fix crop reste utile
pour l'**identification** aval (ArcFace), pas pour le rappel du gate.

---

## 1. La mesure manquante (outils livrés, label-free, réutilisables)

| Outil | Rôle |
|---|---|
| hook `trace` dans `detect_circles_multi` (`vision/normalize_snap.py`) | enregistre le rayon à **chaque étage** (bbox→hough→polish→rim). OFF par défaut, zéro impact prod/persistance. |
| `ml/scripts/measure_crop_undercrop.py` | métrique **sans label** `r_final / r_bbox` (la bbox YOLO borne la vraie pièce) ; décompo par étage ; **contrefactuel** plein-rebord ; corrélation au score gate ; `--min-bbox-frac` filtre le bruit YOLO@0.10 ; montages `--debug-pairs`. |
| `ml/scripts/measure_photo_difficulty.py` | netteté/glare/contraste zero_crops vs success (cheap, pas de modèle). |

Pourquoi c'est mieux que `measure_fragment_gate` (session 1) : celui-ci mesurait le
**symptôme** (scores vs τ) et exigeait un œil humain pour juger le crop. Ici la **cause**
(undercrop) est quantifiée sans label, ET le **contrefactuel** teste directement la thèse
du handoff au lieu de la supposer.

---

## 2. Les chiffres (vraies pièces, `bbox_frac > 0.10`)

> ⚠️ Piège découvert : YOLO@0.10 (census) sort ~6 bboxes/image, p50 `r_bbox/short = 0,04`
> = surtout du bruit (texte/motif). **Toujours filtrer `--min-bbox-frac ≥ 0.10`** pour
> parler des vraies pièces, sinon la stat undercrop est polluée.

- **Undercrop** : 49 % < 0,85 · 15 % sévère < 0,70. Décompo du rétrécissement chez les
  undercrops : **sélection 54 %**, polish 39 %, rim-refine 7 %.
- **Contrefactuel** (crop plein-rebord du même coin) : détecté passe gate **0 %**, plein
  **8–11 %** ; récupère **~10 %** (11/~110). Δ score médian ≈ 0.
- **Contrôle `success`** (mêmes designs, passent) : undercrop 63 % (identique) ;
  serré 0,80/77 % vs plein 0,62/52 % ; **Pearson(ratio,score) = −0,27**.
- **Score plein-rebord par design** : EMU 2009 **0,044** (passe 2 %), AT-2012 **0,314** (15 %).
- **Photo** : zero_crops PAS plus flous (netteté médiane 1090 vs 934 success).

Artefacts : `ml/state/crop_undercrop/{_worst_scored.png, _debug_pairs.png, *.json}`.

---

## 3. Le fix crop livré (flag, OFF par défaut, census-only)

Deux leviers expérimentaux dans `normalize_snap.py`, **aucun effet sans variable d'env**
(R0 : pas de changement prod silencieux) :

| Flag | Effet | Mesuré |
|---|---|---|
| `EURIO_CROP_BBOX_FLOOR=0.85` | plancher `r ≥ 0.85·r_bbox` (ancre YOLO) | undercrop **49 %→26 %**, sévère **15 %→0 %** |
| `EURIO_CROP_OUTER_SELECT=1` | hough_refine prend le plus grand cercle centré | **aucun effet** (Δ+1) |

Leçon : le rebord externe n'est souvent **même pas un candidat Hough** (faible contraste
laiton/fond) → « préférer le plus grand » ne sert à rien ; **ancrer sur la bbox YOLO** est
le seul levier qui marche. Le fix vaut pour l'**ID aval**, pas le gate (cf. §0.3).

Re-mesurer un variant :
```bash
EURIO_CROP_BBOX_FLOOR=0.85 .venv/bin/python -m scripts.measure_crop_undercrop \
  --run fa8a9af939ce43e6a3eee6842ecae170 --no-score --min-bbox-frac 0.10
```

---

## 4. Recommandations (≠ HANDOFF session 1)

1. **Prioriser la PROBE, pas le crop.** Déblocage réel des zero_crops :
   - ré-entraîner `state/fragment_face_probe.npz` en **incluant ces commémo** (EMU 2009,
     globe 2012) comme positifs « face » — données dispo : les 221 `success` + les
     plein-rebord validables (étape **PC**, 1080 Ti) ;
   - **ou** router les détections coin-like à score bas vers **review** au lieu d'auto-reject
     (ne pas perdre de vrais 2€ en silence).
2. **Adopter le fix crop (`bbox-floor`) pour la qualité d'ID**, indépendamment du gate —
   mais alors **re-scorer/ré-entraîner la probe sur des crops plein-rebord** (elle a appris
   sur des crops serrés marge 0,02 → un crop plus plein la fait chuter, cf. Pearson −0,27).
3. **Découpler le crop du gate et le crop d'identification** si on garde la probe serrée :
   gate sur un crop standardisé, identification sur le crop plein.
4. **Ne PAS** refaire la chasse « stratégie A→D » du handoff comme si le crop était la cause :
   c'est un vrai bug mais un **mauvais levier** pour le problème posé.

---

## 5. État git / fichiers touchés (NON committé)

**Modifié** : `ml/vision/normalize_snap.py` (hook `trace` ; flags `EURIO_CROP_OUTER_SELECT`,
`EURIO_CROP_BBOX_FLOOR` ; helpers `_census_outer_select` / `_census_bbox_floor`).
**Nouveaux** : `ml/scripts/measure_crop_undercrop.py`, `ml/scripts/measure_photo_difficulty.py`,
ce doc. À discuter avec le PO avant commit (cf. doctrine chunk + audit).
