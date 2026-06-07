# Listing crop quality — roadmap & suivi

> Vision et tracker pour la qualité du crop des sources `listing` (eBay et co).
> Court terme : assainir les crops actuels sans retrainer. Long terme :
> avoir un détecteur dédié au rim métallique, pas à l'objet "pièce + capsule".

## Contexte (TL;DR)

La pipeline actuelle `normalize_listing` (chunk 1 livré 2026-05-04) :
**YOLO single-class → Hough refine intra-ROI → fallback `yolo+bbox`**.

La détection (= localisation) est bonne. Le **crop final** est souvent
trop large : il englobe pièce + capsule + ombre, parce que :

1. **YOLO surestime systématiquement** — entraîné avec des bboxes "pièce
   visuelle" qui incluent capsule et ombres, son `min(bw,bh)/2` n'est pas
   le rim métallique.
2. **Hough refine vote parfois pour le bord de la capsule** plutôt que le
   rim, surtout quand la capsule a un contour plus contrasté (lumière
   sur plastique transparent).
3. Le cercle inscrit dans la bbox YOLO (= fallback) reproduit le biais.

Conséquence ArcFace : crop 224×224 = ~50% pièce / ~50% capsule+fond. Le
signal d'embedding est dominé par le contexte, pas par la pièce.

## Vision — pistes par horizon

| # | Piste | Horizon | Coût | Impact attendu |
|---|---|---|---|---|
| **1** | **Raffinage par gradient radial** sur le rim candidat | court | 1 chunk (~2h) | gros — règle ~80% des cas visibles |
| 2 | Cascade de refine (Hough strict → loose → Otsu+contour intra-ROI → bbox-shrink) | court | 1 chunk (~3h) | moyen — robustifie les cas atypiques |
| 3 | Bbox-shrink calibré empiriquement sur GT manuelle | court | 1 chunk + annot | moyen — patch le biais YOLO sans le retrainer |
| 4 | Pré-classification de l'image (libre/capsulée/coincard/lot) → routing | moyen | gros | faible isolé, bon en combinaison |
| 5 | **Retrain YOLO avec annotations rim-tight** | long | sprint dédié (annot 200-500 images + train) | gros et propre — solution sans dette |

### Stratégie

1. Pistes **1 → 2 → 3** en court terme : CV déterministe, pas de modèle
   supplémentaire, chaque piste validable en isolation sur le review UI.
2. Piste **5** en background, à planifier quand 1+2+3 plafonnent. C'est
   la solution sans dette technique.
3. Piste **4** rangée — à ressortir uniquement si on découvre des classes
   de photos qu'aucune CV déterministe n'attrape.

### Critère de réussite

Sur un échantillon de 30 lots variés (single, capsulée, coincard, multi-coin) :
- 90%+ des crops accepted ont un rim métallique qui touche les bords du
  crop 224×224 (= ratio rim_diameter / 224 ≥ 0.95).
- Sur 5-10 crops mesurés manuellement, écart `r_predicted / r_true` ≤ 5%.

## Suivi — log par milestone

### M0 — état initial (2026-05-04)

- Hough nu sur listings → soupe de cercles sur texte/motifs (cf. lot Andorra Cimera). Inutilisable.

### M1 — YOLO + Hough refine + clamp bbox + seuils calibrés (2026-05-04)

- Implém YOLO+Hough refine dans `ml/scan/normalize_snap.py::detect_circles_multi`.
- Fix A : clamp `r ≤ max(bw, bh)/2` après refine (pas d'expansion au-delà de la bbox YOLO sur les arches/courbes de fond).
- Fix B : seuils calibrés sur distrib `r/short` du corpus (n=3664 bboxes, p90=0.091, p75=0.047).
  - `_LISTING_RMIN_FRAC_STRICT = 0.08` (était 0.10) — récupère les pièces multi-coincard borderline.
  - `_YOLO_BBOX_MIN_RADIUS_FRAC = 0.7` (était 0.5) — coupe le bruit visuel sub-rim_strict.
- Script de mesure : `ml/scripts/measure_listing_radius_distribution.py`.
- État : détection propre sur la majorité des lots, **crop final imprécis** sur capsules/coincards.

### M2 — gradient radial polish (livré 2026-05-04)

- Implém : `_radial_gradient_polish` dans `ml/scan/normalize_snap.py`. Branché sur tous les candidats `yolo+hough` et `yolo+bbox` avant le filtre accept/reject. Tag `+polish` ajouté au `method` quand le gain de score ≥ 1.05.
- Coût : ~10-50ms par détection (Sobel local + 30×64 bilinéaires). Sur 4 pièces le total monte à ~2s, acceptable.
- Effet mesuré sur les 8 lots de référence :
  - Lot 117142786358 (Gent Gran) : pièce gauche r=193 → 135 (−30%) — capsule virée.
  - Lot 168215792107 (Pirineus) : passe en `yolo+bbox+polish`, r=180 (au lieu d'un cercle énorme englobant ciel + capsule). À valider visuellement.
  - Cas où Hough avait déjà nailed (lot 114573231478) : polish skip via gain<1.05 — ✓ comportement protecteur.
- Limite identifiée : lot 136929255254 image 0 (pièce inclinée fond sombre) → YOLO 0 bbox, polish n'y peut rien. Ce cas appartient à la dette piste 5 (retrain rim-tight ou recall improvement).

### Backlog

- M3 — Piste 2 (cascade refine) si M2 plafonne sur des cas pas encore vus.
- M3' — Piste 3 (bbox-shrink calibré sur GT) si M2 plafonne.
- M-long — Piste 5 (retrain YOLO rim-tight) — sprint à planifier.
- Problème C (YOLO false-positive sur hologrammes / stickers carrés) : à
  attaquer dans M3 via fill_ratio guard, ou repoussé sur M-long via retrain.
- Investigation des 31/356 raws (~9%) où YOLO ne sort 0 bbox du tout — inclut le cas lot 7 image 0.

## Bench visuel (workflow d'itération)

Outil : `ml/scripts/bench_listing_detection.py`. Une commande, écrase et
régénère `ml/state/listing_bench/` :

```bash
cd ml && .venv/bin/python -m scripts.bench_listing_detection
```

Sortie : 1 jpg par raw du golden set (overlay raw avec bboxes YOLO + cercles
finals + strip 224×224 des crops acceptés) + `summary.md` avec table récap.

**Workflow** :
1. Faire le changement code (`ml/scan/normalize_snap.py` typiquement).
2. Lancer le bench → écrit dans `state/listing_bench/`.
3. Comparer visuellement avec l'itération précédente (les bons sont-ils
   restés bons ? les mauvais se sont-ils améliorés ?).
4. Si validé → append un bloc dans la section "Iterations" ci-dessous.
5. Si dégradation → rollback ou ajustement.

Pas de DB touchée pendant l'itération. Le passage en prod (cleanup SQL +
recrop_ebay_orphans) se fait une fois la qualité figée.

## Iterations

### 2026-05-04 — baseline M2 (YOLO + Hough + clamp + polish)

Code : `normalize_snap.py` à HEAD du chunk M2. Bench tourne sur 11 raws
(8 lots, certains avec img0+img1).

**Constats visuels** :

| lot.img | crop final | notes |
|---|---|---|
| 114573231478.0 | ✓ propre | baseline OK |
| 115143970168.0 | ✓ propre | Meritxell — fix A a éliminé l'expansion sur les arches |
| 114573235985.0 | ✓ ✓ 2/2 | seuil 0.08 a récupéré les 2 pièces |
| 117142786358.0 | ✓ / ✗ / off_edge | gauche OK ; **hologramme = faux positif (C)** ; verso = **cercle déborde (B')** |
| 168045333862.0 / .1 | ✓ ×4 / ×4 | 4 pièces sur cuir, parfait |
| 136929255254.0 | rien | YOLO 0 bbox sur pièce inclinée fond noir (recall) |
| 136929255254.1 | rien | 1 bbox conf~0.05, sub-filtre |
| 146492050953.0 | borderline | composite low-res (269 short), 2 acceptées petites |
| 168215792107.0 | ✓ propre | **Pirineus — gros gain polish, capsule virée** |
| 168215792107.1 | ✓ ×2 | recto+verso, polish a serré le rim |

**Nouveaux problèmes identifiés via le bench** :
- **B'** : sur 117142786358 verso droit, le cercle rouge (rayon overshooting) déborde dans la marge alors que la vraie pièce est entièrement dans le cadre. Le polish n'a pas réussi à shrink. À investiguer : pourquoi le gradient radial n'a pas trouvé le rim plus serré ? Hypothèse : ROI YOLO inclut trop de texte autour, gradient noyé.
- **C** confirmé visuellement : hologramme carré (sticker `SAMMLERPOSTEN`) → bbox YOLO conf=0.61 → cercle inscrit dans bbox carrée → crop = carré gris.

**Statut** : la majorité des cas est propre. Les 2 cas restants (B' et C) sont
candidats pour M3.

### 2026-05-04 — M3a : `_YOLO_BBOX_MARGIN_FRAC` 0.15 → 0.00

**Hypothèse B'** : le polish ne suffit pas à serrer le rim quand Hough refine pique un cercle parasite — Hough peut voter pour la capsule, l'ombre, ou les arches de fond sur les coincards. La cause amont : la ROI Hough = bbox + 15% de marge, ce qui inclut les artefacts autour du rim.

**Changement** : ROI Hough réduit à la bbox stricte (margin 0.00). Hough ne voit plus capsule/ombres/arches → vote uniquement sur le rim.

**Résultats sur les 11 raws du bench** :

| lot.img | Δ r/short | observation |
|---|---|---|
| 114573231478.0 | 0.130 → 0.127 | Cimera, micro-ajustement, OK |
| 115143970168.0 | **0.197 → 0.133** | **Meritxell — rim métallique propre, capsule virée** |
| 114573235985.0 | 0.088 → 0.089 | inchangé |
| 117142786358.0 | 2 acc → **3 acc** | **verso 2€ rejeté off_edge → accepté avec rim correct** |
| 168045333862.0 / .1 | inchangé | 4 pièces, toujours parfait |
| 168215792107.0 | 0.150 → 0.145 | Pirineus img0 — Hough plus tight, polish skip |
| 168215792107.1 | 2 acc → **1 acc** | **faux positif "coin de montagne" disparu** (collateral win) |

**Pas de régression** sur les cas qui marchaient. Aucun crop n'est devenu plus mauvais. Verso Gent Gran bascule de "rejected off_edge" à "accepté avec rim serré" → +1 crop utile.

**Cas restants** :
- Problème C (hologramme `SAMMLERPOSTEN` sur 117142786358) : toujours faux positif, crop = carré gris. Cible M3b.
- Lot 136929255254 img0 : YOLO 0 bbox sur pièce inclinée fond noir. Cible piste 5 (retrain).

### 2026-05-04 — M3b : structure guard intra-disque (low_structure reject)

**Hypothèse C** : YOLO classe parfois des stickers/hologrammes/codes-barres carrés comme pièces (training set inclut probablement des objets métalliques carrés). Le crop sortant est alors un disque quasi-uniforme — ArcFace pollué.

**Discriminateur** : moyenne(|Laplacian|) sur le disque inscrit à 0.95·r mesure la "richesse de structure" (texte, motifs, étoiles, relief). Mesuré sur les 19 crops accepted du golden set : hologramme = 27, vraies pièces 49-179. Gap propre.

**Implémentation** : `_disc_lap_meanabs` calculé une fois par image (Laplacian global ~5-10ms), échantillonné par détection. Reject si < 32 → nouveau reject_reason `"low_structure"`.

**Résultats** :
- 117142786358.0 : 3 acc → **2 acc** + 1 rej `low_structure`. Hologramme out, vraies pièces préservées. ✓
- 18 autres détections accepted du golden set : aucune touchée (toutes ≥ 49 ≫ 32).

**À surveiller en prod** : pièce mate très usée + fond très uniforme pourrait s'approcher de 32. Le métrique dépend du contraste local. Si false reject observé en review, soit baisser threshold, soit changer de métrique (entropie, variance Sobel, structural-similarity).

**Statut** : sur les 11 raws du golden set, plus aucun crop bidon n'est produit. Reste piste 5 (recall miss YOLO sur photos atypiques) en backlog long terme.

### 2026-05-04 — Full recrop prod eBay

- Backup DB : `ml/state/training.db.bak-20260504-2253` (8.7M).
- Cleanup SQL : 3447 image_assets non-manual purgés, 707 source_images reset à `pipeline_state='downloaded'`.
- `recrop_ebay_orphans.py` : 707 raws traités → **513 crops** propres (vs 3447 brouillons), 402 raws sans crop (à investiguer côté piste 5 — soit images banner légitimes, soit recall YOLO).
- **Gap découvert** : le script `recrop_ebay_orphans.py` ne fait QUE `run_detect_crop`, pas `run_resolve` + `run_enqueue`. Les 513 assets sont restés en `pending_match`, review queue vide. Workaround appliqué : invocation manuelle de resolve + enqueue post-recrop. Action future : patcher `recrop_ebay_orphans.py` pour enchaîner les 3 steps comme l'orchestrateur.

| listing_key | particularité |
|---|---|
| `ebay_v1\|114573231478\|0` | coincard texte+motifs, 1 pièce — baseline propre |
| `ebay_v1\|115143970168\|0` | coincard arches concentriques (Meritxell) — piège Hough |
| `ebay_v1\|114573235985\|0` | 2 coincards côte à côte — multi-coin petit r/short |
| `ebay_v1\|117142786358\|0` | coincard recto+verso + hologramme carré — problème C |
| `ebay_v1\|168045333862\|0` | 4 pièces sur cuir — multi-coin propre |
| `ebay_v1\|136929255254\|0` | pièce libre sur support transparent — bbox surdim |
| `ebay_v1\|146492050953\|0` | composite 2 coincards — crop trop large gauche |
| `ebay_v1\|168215792107\|0` | coincard "Pirineus" capsule + ciel — biais capsule |
