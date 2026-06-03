# Refonte du crop des images scrapées (eBay → training ArcFace)

> **Statut : proposition d'architecture — à valider avant tout code de prod.**
> Phase de recherche+diagnostic produite par le workflow `crop-quality-overhaul-diag`
> (run `wf_a85c6e64-054`, 11 agents). Aucune écriture de code de prod à ce stade.
>
> Artefacts du diagnostic :
> - Script : `ml/scripts/crop_quality_diag.py`
> - Données : `ml/state/crop_diag/results.csv` (par crop : classe, r_ratio, fill_ratio, bucket)
> - Audit visuel : `ml/state/crop_diag/contact_sheet.jpg` (planche-contact des pires crops)

---

## 0. Diagnostic chiffré (corpus réel complet)

**Méthode** : oracle `_probe_true_rim` (Otsu + contour sur le **raw**, identique à `bench_listing_bimetal.py`).
Pour chaque crop : `r_pipe / r_probe < 0.85` → undercrop ; `fill_ratio < 0.50` → wrong ; sinon ok.
**Échantillon = 2274 crops eBay** (totalité du cache local `~/.cache/eurio/enrichment-crops/ebay/`, 0 cache-miss).

| Bucket | n | undercrop % | wrong % | inner-ring flag % | fill_ratio moyen |
|---|---|---|---|---|---|
| bimetal_light | 1056 | 9.3 | 0 | 12.8 | 0.976 |
| bimetal_textured | 932 | 7.9 | 0 | 13.1 | 0.976 |
| mono_light | 173 | 9.2 | 0 | 0 | 0.975 |
| mono_textured | 113 | 2.7 | 0 | 0 | 0.980 |

**Chiffres clés :**
- **Undercrop oracle-confirmé : 18.4 %** (191/1037 crops avec oracle valide). Borne basse globale 8.4 %.
  Taux réel estimé **~18 %** (l'oracle ne couvre que 45.6 % du corpus — voir angle mort).
- **~93.7 % des undercrops sont des 2€ bimétalliques** (disque interne or↔argent).
- Undercrops sévères (`r_ratio < 0.60`, typique disque interne) : 1.6 %. **Pire cas mesuré : `r_ratio = 0.504`** (DE-2010 Brême → crop = 50 % du diamètre réel).
- **Overcrop = 0 %**. Le problème n'est PAS « trop de fond ». `fill_ratio` médian = 0.977 partout.
- **Variabilité inter-photos d'une même pièce : `r_ratio` de 0.504 à 1.420.** Cible : réduire la **variance**, pas seulement le biais.
- Fond clair vs texturé : différence non significative (9.3 % vs 7.9 %). L'undercrop est **structurel** (pipeline Hough dans ROI YOLO serrée), indépendant du fond eBay.

### 0.1 Angles morts du diagnostic auto (à connaître)
- **Couverture oracle = 45.6 %** : sur 54.4 % des crops, le fond eBay est trop hétérogène pour qu'Otsu isole le rim. Le 18.4 % est une **borne basse sur les jugés**.
- L'heuristique « 2 cercles concentriques dans le crop » capte 11.3 % des crops mais **precision faible (4.7 %)** : à NE PAS utiliser comme classifieur d'undercrop. Le défaut n'est visible qu'en comparant **crop vs raw** (d'où la page bench).

### 0.2 Correction par audit visuel humain (planche-contact)
Le diagnostic auto conclut « **0 crop wrong** » (selon le seuil `fill_ratio < 0.50`). **C'est trompeur.**
L'inspection visuelle de `contact_sheet.jpg` montre une catégorie distincte que l'oracle ne capte pas :
**objets non-pièce cropés plein cadre** — coincards / blisters « MONNAIE DE PARIS », étiquettes
« F Stuttgart », tubes de pièces vus de bout. Ces crops ont un `fill_ratio` élevé (la carte/l'étiquette
remplit le cadre) donc passent sous le radar `fill_ratio`, mais ce ne sont **pas des pièces**.
→ **5e cause** (sémantique, pas géométrique) que seul un juge « est-ce une pièce ? » (ccproxy vision)
ou une contrainte de circularité forte peut attraper. La page bench doit la rendre visible.

---

## 1. Problème reformulé

Le pipeline eBay (`normalize_listing` → `detect_circles_multi`) produit des crops 224×224 dont **la détection du cercle est correcte en *forme* mais fausse en *échelle* sur les 2€ bimétalliques** : Hough, contraint dans une ROI YOLO serrée, accroche le **disque interne** (frontière or↔argent, gradient net) au lieu du **rim externe** (transition pièce↔fond, gradient faible). Résultat : un crop visuellement « propre » (le disque interne remplit bien le masque, `fill_ratio` médian = 0.977) mais qui ne montre que ~50-72 % du diamètre réel — couronne et étoiles coupées. Le problème **n'est pas le format** (marge 2 %, masque dur, déjà ablationné et confirmé optimal *si la détection est juste*), c'est la **détection du rayon**. Aggravé par l'absence de garde `fill_ratio` dans la branche listing/device (la branche studio l'a, `normalize_snap.py:408-411`) — manque documenté lignes 122-128 comme « separate sprint » : **c'est ce sprint.**

---

## 2. Taxonomie des causes racines (chiffrée)

### 2.1 Ce qui est « FORMAT » (résolu, ne pas rouvrir)
| Paramètre | Valeur | Statut |
|---|---|---|
| `margin_frac` | 0.02 | ✅ Ablationné : m02-hard ≈ m10-hard (83.0 % vs 82.2 % R@1, dans le bruit) |
| `edge_mode` | hard | ✅ hard > feathered > none |
| `output_size` | 224 | ✅ Acté |
| `rmin` large (0.10/0.15) | — | ✅ vs tight 0.35 : large gagne (tight → cercles parasites de fond) |

**Conclusion** : le format est bon **conditionnellement à une détection correcte**. La marge 2 % est cependant *fragile* — 4-5 px de jeu à 224 px : tout sous-rayon ou décentrage clippe le rim. C'est un **amplificateur, pas la cause**.

### 2.2 Ce qui est « DÉTECTION » (la vraie cause)
| Cause | Mécanisme | Chiffre diagnostic |
|---|---|---|
| **A. Disque interne bimétal** | Hough dans ROI YOLO sans garde `fill_ratio` ; gradient or↔argent plus saillant que rim↔fond | **18.4 % undercrop** (191/1037). **~93.7 % des undercrops sont bimétal.** Pire cas `r_ratio=0.504` |
| **B. YOLO bbox sous-estimé → r_max clamp** | `_YOLO_BBOX_MARGIN_FRAC=0.00` : Hough refine bloqué au demi-côté de la bbox. Si YOLO clippe la pièce, le rim est hors d'atteinte | Contributeur à A |
| **C. Sous-cercle parasite** | `rmin_frac=0.10` + tolérance centrage 30 % laisse passer un « 0 » de date / motif capsule sur raws peu downscalés | **0 cas dans le corpus** (`_STRUCTURE_MIN_LAP=32` les a filtrés avant stockage — mais au prix de raws jetés) |
| **D. Décentrage au crop bord** | Re-squaring `min(x1-x0,y1-y0)` ancré en (x0,y0) ne recentre pas → masque off-center | Fréquent multi-pièces bord de cadre (oracle N/A) |
| **E. Objet non-pièce** *(ajout audit visuel)* | Détection cale sur une coincard/blister/tube plein cadre ; circularité non vérifiée sémantiquement | Visible sur `contact_sheet.jpg`, non chiffré (fill_ratio élevé → invisible à l'oracle) |

### 2.3 Découplage critique
Le défaut bimétal **n'est détectable qu'en comparant crop vs raw** (oracle Otsu sur le raw) : le crop montre le bon disque interne *qui remplit le masque*. C'est la raison d'être de la page bench — on ne peut pas auditer la qualité sur le crop isolé.

### 2.4 Angles morts non chiffrés dans le 18.4 %
- **31/356 raws (~9 %) à 0 bbox YOLO** → `crop_status='zero_crops'`, jamais retentés. Trou permanent du training set (piste 5 : retrain YOLO).
- **Fallback studio → device** : les bimétal Numista rejetés par Otsu (`ring_contour`) retombent sur `normalize_device` *sans* garde `fill_ratio` → même bug sur le training Numista.

---

## 3. Ce qu'on a déjà essayé (synthèse honnête)

| Tentative | Résultat | Réévaluation |
|---|---|---|
| Ablation format (12 combos, 17 classes, 337 hold-out) | m02-hard optimal | ✅ Garder. Mais ne touche PAS la détection — fausse impression de « résolu » |
| rmin tight 0.35 | Rejeté (parasites fond) | ✅ Garder large |
| `_YOLO_BBOX_MARGIN_FRAC` 0.15→0.00 | Évite arches capsule | ⚠️ **À rouvrir** : 0.00 cause la cause B |
| structure guard =32 (n=19) | Ferme cas catastrophiques | ⚠️ Calibration fragile, 0 monitoring du faux-rejet |
| garde `fill_ratio` device/listing | **Jamais fait** (« separate sprint ») | 🔴 **C'est le sprint.** Cause racine A |
| ccproxy_judge (Sonnet vision) | Marge sweep DE-2010 jugé | ✅ Réutiliser comme **gold-builder semi-auto** + juge « est-ce une pièce » (cause E) |

**« On ne peut pas faire mieux » passés à réévaluer :**
- *« La marge 2 % est optimale »* → vrai en R@1, faux en robustesse. Optimale SI détection juste.
- *« Hough large rmin est la bonne approche »* → Hough seul **ne sait pas distinguer rim externe de disque interne**. Il faut un **sélecteur de cercle externe explicite**, pas un meilleur Hough.
- *« YOLO bbox = vérité de cadrage »* → faux : YOLO est entraîné sur « pièce visuelle », pas « rim métal ». Le `r_max_clamp` sur la bbox propage l'erreur.

---

## 4. Architecture multi-passe adaptative proposée

Principe : **arrêter de tuner un détecteur unique. Router vers le bon détecteur selon la config, sélectionner le cercle EXTERNE explicitement, puis gater.**

```
                          RAW (cache local, déjà téléchargé)
                                     │
         ┌───────────────────────────┴───────────────────────────┐
         │  PASSE 1 — CLASSIFY (cheap, ~5ms)                       │
         │  • YOLO bbox (existant) → ROI + n_coins                  │
         │  • fond: corner-mean / variance Laplacian → uni|texturé │
         │  • bimétal? : 2 cercles concentriques Hough dans ROI    │
         │  • centré? : |centre_bbox - centre_img| / short         │
         └───────────────────────────┬───────────────────────────┘
                                     │  (profil détecté)
         ┌───────────────────────────┴───────────────────────────┐
         │  PASSE 2 — DETECT (router → détecteur + sélecteur)      │
         │  Détecteur (selon profil) :                             │
         │    fond uni      → contour Otsu + fitEllipse (RANSAC)   │
         │    fond texturé  → EDCircles (multi-cercles, no minDist)│
         │    fallback      → Hough 2-pass (existant)              │
         │  SÉLECTEUR DE CERCLE EXTERNE (clé anti-bimétal) :       │
         │    candidats = tous les cercles centrés                 │
         │    garde fill_ratio ≥ 0.70 (le disque interne échoue)   │
         │    r_final = max(r) parmi candidats valides             │
         │    ROI étendue +12% AVANT Hough refine (corrige cause B)│
         └───────────────────────────┬───────────────────────────┘
                                     │
         ┌───────────────────────────┴───────────────────────────┐
         │  PASSE 3 — QUALITY GATE                                 │
         │  • fill_ratio crop ≥ 0.70 (sinon flag ring_undercrop)  │
         │  • structure guard (existant, =32)                      │
         │  • circularité / « est-ce une pièce » (cause E)         │
         │  • oracle-cheap: r_final / r_probe_otsu ≥ 0.85 si dispo │
         │  • recentrage symétrique au crop bord (corrige cause D) │
         │  Sortie: accepted | flagged(reason) | rejected         │
         │  → écrit quality_score (aujourd'hui jamais écrit)       │
         └───────────────────────────┬───────────────────────────┘
                                     │
                              CROP 224×224 + quality_score + flag
```

### 4.1 Brique par brique
| Brique | Techno | Pourquoi | Coût |
|---|---|---|---|
| **P1 — Classify** | cv2 core (corner-mean, Laplacian var) + Hough 2-cercles existant | Routage cheap, zéro dep, réutilise YOLO déjà appelé | ~60 LOC |
| **P2a — Détecteur fond uni** | `cv2.fitEllipse` sur plus grand contour + wrapper RANSAC | Le contour externe **EST** le rim → attaque directe A/B. Core OpenCV, **portable Android sans contrib** | ~70 LOC |
| **P2b — Détecteur fond texturé** | `cv2.ximgproc.EdgeDrawing.detectCircles()` (EDCircles) | **Pas de minDist** → sort les deux cercles bimétal, le caller pick le plus grand | ~50 LOC + swap pip → `opencv-contrib-python` |
| **P2c — Sélecteur externe** | logique pure : `max(r)` parmi cercles `fill≥0.70` centrés | **LA correction anti-bimétal.** Indépendant du détecteur, portable Kotlin | ~40 LOC |
| **P2d — ROI étendue** | `_YOLO_BBOX_MARGIN_FRAC` 0.00 → ~0.12 *si bimétal* | Corrige cause B sans rouvrir le pb capsule | ~10 LOC |
| **P3 — Quality gate + score** | oracle Otsu cheap (`_probe_true_rim`) → `quality_score` ; recentrage ; circularité | Remplit `quality_score` (NULL aujourd'hui) → `training_eligible` automatisable | ~80 LOC |

### 4.2 Pourquoi pas SAM2 / segment-anything (écarté pour v1)
Poids ~150-360 MB, latence GPU, **non portable on-device raisonnablement** (viole R0 parité). fitEllipse + EDCircles + sélecteur externe couvrent les causes A-D avec **zéro nouveau modèle** et un portage Kotlin tractable. **FastSAM (déjà dispo via ultralytics) reste une option *server-only*** pour la queue des pires images si le bench montre que fitEllipse/EDCircles plafonnent.

### 4.3 Hypothèse à valider par le bench (honnêteté)
On **affirme** que fitEllipse-sur-contour + sélecteur `max(r) | fill≥0.70` corrige l'undercrop bimétal. **On ne l'a pas prouvé.** L'oracle Otsu marche sur 45.6 % des raws (= détecteur P2a sur fond uni). **Risque** : sur les 54.4 % fond texturé, ni Otsu ni fitEllipse ne marchent → EDCircles doit prendre le relais, et **EDCircles n'a jamais tourné sur ce corpus**. Le premier chunk de valeur est donc un **bench A/B des détecteurs**, pas du code de prod.

---

## 5. Contrat de parité web ↔ android

**Invariant** : crop Android (`SnapNormalizer.kt`) et crop Python = **même résultat**, technique libre.
Gate existante (`diff_kotlin_python.py`) : `CENTER_TOL_PX=2`, `RADIUS_TOL_PX=2`, `PSNR_PASS_DB=30.0`. Verdicts : OK / MISMATCH / MISS / FAIL_BOTH / NO_KT.

| Brique | Portable on-device ? | Stratégie parité |
|---|---|---|
| **Sélecteur externe `max(r)\|fill≥0.70`** | ✅ Logique pure | **Porter à l'identique** dans `detectCoinCircle()`. C'est le cœur, trivial à mirrorer |
| **fitEllipse + RANSAC** | ✅ Core OpenCV Android | Porter ; fixer seed RNG identique pour reproductibilité |
| **EDCircles (ximgproc)** | ⚠️ contrib requis dans l'AAR | **Vérifier l'AAR bundlé**. Si absent : EDCircles **training-only Python**, Android = fitEllipse+Hough |
| **Garde fill_ratio** | ✅ | Porter le seuil 0.70 |

**Golden set partagé** (à figer) : N crops device (`device_bimetal_bench/`) + raws → JSONL gelé. Toute modif Python relance `diff_kotlin_python.py` ; CI bloque si verdict ≠ OK/FAIL_BOTH.

**Divergence contrôlée acceptable** : si EDCircles débloque le fond texturé mais absent de l'AAR, EDCircles training-only (Python) et Android = fitEllipse+Hough+sélecteur. Justifié car crops eBay = *training-only* et le hold-out = captures device (fond contrôlé). **À valider (Q4).**

---

## 6. Page bench admin (Vue, `packages/web`)

> Admin exempté du proto-first. Objectif : l'utilisateur balance N crops, compare M algorithmes côte-à-côte, note bon/mauvais → construit un gold.

### 6.1 Source des images (zéro quota)
- Raws déjà en cache : `~/.cache/eurio/enrichment-raws/ebay/` (2274 dispo). **Jamais de re-scrape.**
- Re-crop à la volée via `recrop_with_config.py` / `detect_circles_multi(raw, config=...)`.
- Échantillonnage : réutiliser `crop_exp/sampler_by_score.py` + `sampler_inner.py`, biaisables vers les undercrops (`results.csv` a déjà les `r_ratio`).

### 6.2 Flux de données
```
Vue (packages/web)  ──GET /crop-bench/sample?n=100&bias=undercrop──▶  FastAPI (ml/api/crop_bench_routes.py)
                    ◀── {raws[], algos:[hough,fitellipse,edcircles,...]} ─┘
Vue  ──POST /crop-bench/recrop {raw_id, algo, config}──▶ recrop in-mem
     ◀── {crop_png_b64, cx,cy,r, quality_score, oracle_r_ratio} ────────┘
Vue  ──POST /crop-bench/label {asset_id, algo, verdict:good|bad} ──────▶ gold JSONL
                                                          ml/state/crop_scores/gold/crop_gold.jsonl
```
Nouveau routeur `crop_bench_routes.py` calqué sur `bench_routes.py`. Replay déterministe hors quota.

### 6.3 Rendu (grille comparative)
```
┌──────────────────────────────────────────────────────────────┐
│  RAW (vignette)  │  Hough (actuel) │ fitEllipse │ EDCircles    │
│  [pièce eBay]    │  [crop+r_ratio] │ [crop]     │ [crop]       │
│                  │   r/r̂=0.50 🔴   │ r/r̂=0.97✅ │ r/r̂=0.99✅   │
│                  │  [👍][👎]       │ [👍][👎]   │ [👍][👎]     │
└──────────────────────────────────────────────────────────────┘
Header: filtres (bimétal/mono, fond uni/texturé, undercrop-only), n=10/100,
        agrégats par algo (% good, mean r_ratio, % oracle-couvert)
```
- **Overlay forensique** : cercle détecté dessiné sur le raw.
- **Badge couleur** : 🔴<0.60, 🟡0.60-0.85, ✅≥0.85 (r_ratio oracle quand dispo + fill_ratio + quality_score).

### 6.4 Gold semi-automatique (réutiliser ccproxy_judge)
- Bouton « pré-juger avec ccproxy » (Sonnet vision, ccproxy:3002) sur les paires raw/crop → pré-remplit good/bad **+ détecte les non-pièces (cause E)**, l'utilisateur corrige. Réutilise les sidecars `crop_scores/`.
- Le gold (`crop_gold.jsonl`) = métrique objective pour comparer les détecteurs + set de régression CI.

---

## 7. Plan en chunks (valeur visible tôt, audit entre chaque)

| # | Chunk | Durée | Livrable auditable | Dépend de |
|---|---|---|---|---|
| **0** | **Page bench read-only** : routeur `crop_bench_routes` (sample depuis `results.csv` + raws cache) + page Vue grille raw / crop-actuel + overlay + badge r_ratio. Pas encore d'algos alternatifs | 2-3h | L'utilisateur *voit* enfin les undercrops (raw vs crop) | — |
| **1** | **Détecteur fitEllipse+RANSAC** + sélecteur externe `max(r)\|fill≥0.70`, en 2e colonne | 2-3h | Colonne fitEllipse vs Hough sur 100 crops, % good comparé | 0 |
| **2** | **EDCircles (opencv-contrib)** en 3e colonne + garde bimétal ROI+12% | 1-2h | Colonne EDCircles, surtout fond texturé (les 54 %) | 1 |
| **3** | **Labelling + gold** : boutons 👍👎 + `crop_gold.jsonl` + pré-juge ccproxy. Agrégats precision/recall undercrop par algo | 2h | Premier gold ~100 crops, verdict chiffré « quel algo gagne » | 0 |
| **4** | **DÉCISION détecteur** (sur le gold) + câblage prod : router P1/P2/P3 dans `normalize_listing`, écriture `quality_score`, recentrage | 2-3h | Re-crop des 2274 via `--crop-pending`, nouveau diagnostic comparé | 3 |
| **5** | **Parité Android** : porter sélecteur+fitEllipse dans `SnapNormalizer.kt`, golden figé, `diff_kotlin_python.py` vert | 2-3h | Gate parité OK/FAIL_BOTH | 4 |
| **6** | **Garde fallback studio→device** (fill_ratio) + patch `recrop_ebay_orphans` + monitoring faux-rejet structure guard | 1-2h | Numista bimétal ne tombe plus dans le bug | 4 |

**Ordre justifié** : chunk 0-1 livrent la **preuve visuelle** que le nouveau détecteur corrige l'undercrop *avant* de toucher la prod. La décision (chunk 4) est prise sur le gold (chunk 3), pas sur une intuition. La parité (chunk 5) suit la décision.

---

## 8. Questions ouvertes / décisions à trancher

1. **Périmètre re-crop** : eBay seul (v1) ou eBay + bimétal Numista (fallback bug, impact direct ArcFace) ?
2. **`opencv-contrib-python`** : OK pour swap le package pip côté ML (même version 4.13, drop-in) ?
3. **AAR Android contrib** : je vérifie si l'AAR OpenCV 4.10 inclut ximgproc, ou on tranche d'avance « EDCircles training-only, Android = fitEllipse » ?
4. **Divergence parité acceptée** : un détecteur training-only (EDCircles) absent on-device est-il acceptable tant que le **résultat** reste dans la gate ε=2px sur le golden device ?
5. **`quality_score` automatique** : score oracle-based (45.6 % couverture) + NULL sinon, ou attendre un gold complet avant `training_eligible` ?
6. **Seuil `fill_ratio`** : reprendre 0.70 (studio) ou re-calibrer sur le gold ?
7. **31 raws 0-bbox (piste 5)** : dans ce chantier ou séparé (retrain YOLO) ?
8. **Cible chiffrée** : proposition = **undercrop oracle < 5 %** (vs 18.4 %) ET **variance r_ratio inter-photos ÷ 2**, mesurés sur le gold + re-diagnostic.

---

## 9. Journal d'avancement

### Chunk 0 — Banc admin lecture seule (livré 2026-06-02)
- Backend `ml/api/crop_bench_routes.py` (`/crop-bench/stats|sample|overlay`), réutilise l'oracle du diagnostic → overlay raw avec 🔴 cercle pipeline vs 🟢 vrai rim. Front `admin/.../features/crop-bench/`. Images servies par les endpoints `/sources/.../file` existants (cache local, zéro quota). Vérifié HTTP (stats == diagnostic).
- **Audit visuel** : les pires cas (r̂≈0.50) sont des bimétal single-coin (disque interne cropé) + des photos multi-objets (coincards/certificats « Zertifikat » → cause E confirmée).

### Chunk 1 — Détecteur fitEllipse + sélecteur de cercle externe (livré 2026-06-02)
- Module pluggable `ml/scan/crop_detectors.py` (`DetectorResult`, `detect_fitellipse`, registre `DETECTORS`, `crop_with_detector`). Réutilise les primitifs de prod (`_downscale_to_working_res`, `_crop_mask_resize_float`, `CropConfig` défaut) → **même format de crop**, seule la détection change. `fitellipse` = contour Otsu externe + `cv2.fitEllipse` (semi-grand axe) + sélecteur `max(r) | fill_ratio≥0.70`.
- Endpoints `GET /crop-bench/recrop/{asset_id}?algo=` (crop 224 base64 + r_ratio vs oracle) et `overlay?algos=` (cercle bleu de l'algo). Front : 3e colonne fitEllipse lazy + toggle + comparaison r̂.
- **Résultat empirique (12 pires undercrops, r̂ = r/r_probe oracle)** :
  - **Single-coin fond uni : r̂ 0.51 → ~0.99** (a1ac22f1 0.99, 9e5c1071 0.90, 7eb41f6a 0.99, 59bd06bd 1.00, 1a4e025b/0921f133 0.99, f88ba127 0.99). **Undercrop bimétal corrigé** (le crop montre enfin rim + étoiles + légende). C'est ~93 % du problème.
  - **Multi-objets/lots : r̂ >> 1** (07f6c268 1.62, 17b7802c 2.86, e002c564 3.50) → fitEllipse fusionne les objets et **overcroppe**. À contraindre (bbox YOLO / détection lot).
  - **Fond texturé : `no_ellipse`** (beef7266, 2a02032a) → Otsu n'isole rien. Cible d'**EDCircles** (Chunk 2).
- **Conclusion** : le routage multi-passe est validé empiriquement — fitEllipse résout le gros du volume (uniforme single-coin), reste à router le texturé (EDCircles) et à contraindre les lots (overcrop).

### Chunk 2 — Raffinement contraint `bbox_refine` (livré 2026-06-02)
**Enseignement pivot (mesuré, change l'approche)** : sur un échantillon **aléatoire** (pas les pires), le pipeline **actuel est déjà bon à ~80 %** (good = r̂∈[0.85,1.20]) ; il ne rate que ~18-20 % (undercrop bimétal). Un **remplacement aveugle** par fitEllipse/adaptive plein-cadre est un **RECUL** : ils overcroppent massivement les **sets multi-pièces / blisters / coffrets** (fill circulaire mais cadre tout le coffret), car ils n'ont **pas de localisation**. La localisation YOLO du pipeline actuel est donc **précieuse et à garder**.
- **Décision archi corrigée** : ne pas remplacer le détecteur globalement, mais **raffiner le rim DANS la région de la pièce connue**. `detect_bbox_refine(raw, hint)` : ROI = centre de la bbox stockée ± 2.6·r_hint → contour-fitEllipse circulaire (ou Hough largest sans polish) pour le **rim externe**, avec **plancher r ≥ 0.9·r_hint** (jamais pire que l'actuel) et **plafond r ≤ 2.6·r_hint** (overcrop borné). Pas de YOLO re-run (bbox stockée jugée plus fiable comme prior de centre).
- **Résultat (120 crops aléatoires oracle-jugés)** : `current` **80.0 %** good · `adaptive` plein-cadre 52.5 % (55 overcrop) · **`bbox_refine` 94.2 %** (113 good, 1 undercrop, 6 overcrop, 0 fail). Sur les 16 pires : r̂ 0.50 → ~0.90-1.00 (single-coin, texturé, et la plupart des multi-objets ; 1 multi-objet dur reste au hint = sans régression).
- **Détecteurs au banc** : `bbox_refine` (défaut), `fitellipse`, `adaptive` — sélecteur d'algo + cercle de l'algo sur l'overlay (orange pour refine).
- **Caveat oracle** : `r_probe` reste bruité ; le 94 % est sur l'oracle, indicatif. Le juge final = gold humain (Chunk 3). EDCircles/contrib non nécessaire pour l'instant (le contour-in-ROI suffit sur le texturé une fois localisé).

### Chunk 3 — Lisibilité + gold labeling (livré 2026-06-02)
- **Lisibilité** (retour utilisateur « comparaisons trop serrées ») : carte en **panneaux carrés plus grands** (aspect 1:1), crop 224 **entièrement visible** (`object-fit: contain`), **clic = plein format**, grille élargie (≥620 px → ~2/ligne).
- **Gold labeling** : par carte, juger ✓ bon / ✗ mauvais le crop **actuel** ET le crop **détecteur** courant. Backend : `POST /crop-bench/label` + `GET /crop-bench/labels`, persistance JSONL `ml/state/crop_scores/gold/crop_gold.jsonl` (upsert par (asset_id, target)). **Head-to-head** : `wins` (algo bon & actuel mauvais), `losses`, `both_good/both_bad` ; tally en tête. Sélecteur d'algo → gold par détecteur.
- **But** : trancher sur **vérité humaine** (pas l'oracle bruité) si bbox_refine bat l'actuel, avant de figer en prod (Chunk 4). Le gold = aussi set de régression CI.
- **Gold utilisateur (n=30 head-to-head, 60 labels)** : **bbox_refine 25 gagne · 2 régresse · 0 tous bons · 3 tous mauvais**. Confirme sur vérité humaine que bbox_refine bat largement l'actuel (~83 % wins, 6.7 % régression).

### Note — écrins/capsules « verre » (concentriques à la pièce)
Question : la capsule est elle aussi un cercle (concentrique, plus grand) → risque d'overcrop sur le bord plastique. **Réponse** : géré nativement par le chemin contour de `bbox_refine` — **Otsu accroche le métal de la pièce, pas le plastique transparent** (capsule invisible à la binarisation) ; le **plafond r ≤ 2.6·r_hint** borne le cas d'une capsule opaque/frostée. Vérifié sur fr-2008 capsule (e002c564) : **r̂ 0.94**.
- **Impasse testée & rejetée** : sélecteur « plus grand cercle à bord FORT » (gradient radial du rim, comme le polish de prod). Régresse (94 %→88 %, undercrop 1→11) car **l'anneau interne bimétal a le bord le plus fort** → le filtre favorise parfois l'interne. Capsule (rejeter le grand-faible) et bimétal (rejeter le petit-fort) tirent en sens opposés → ne pas réutiliser le rim-gradient comme sélecteur global. Code reverté.

### Chunk 4 — Câblage prod + re-crop du parc (2026-06-03)
- **Câblage prod** : `detect_circles_multi` (chemin listing/eBay, via `normalize_listing` ← `detect_crop.py`) applique `detect_bbox_refine` en post-step sur le cercle YOLO+Hough+polish (hint), flag `_LISTING_RIM_REFINE=True`, import lazy (anti-cycle). **Listing-only** : `normalize_device` (scan Android) et sa parité Kotlin NON touchés. Vérifié : a1ac22f1 r 104→202, 9e5c1071 151→268, capsule e002c564 convergé ~220. Le post-filtre accept/reject (radius_too_large…) borne les dérives.
- **Mesure parc complet (n=1037 oracle-jugés)** : current **79.9 %** good (191 under, 17 over) → bbox_refine **91.7 %** (31 under, 55 over). Undercrop **−84 %**. Coût = +38 overcrop (borné ≤2.6·hint, moins nocif que l'undercrop pour ArcFace). Méthodes : contour 750, hough 280, hint_kept 7.
- **Re-crop des 2274** : `ml/scripts/recrop_ebay_refine.py` (dry-run par défaut ; `--commit`/`--limit`/`--no-minio`). Repart du hint stocké, écrit le nouveau crop au MÊME storage_path (cache local + MinIO write-through + DB bbox_json/method/dims/phash ; eurio_id préservé). Backup `state/eurio.db.bak-pre-recrop-refine`.
- **Re-crop TERMINÉ** (2026-06-03, ~20 min) : 2274/2274 refinés, **0 échec MinIO**, 1565 agrandis (undercrops corrigés) / 635 resserrés. Tous les `image_assets` eBay portent désormais `detection_method` `…+refine`.
- **Re-diagnostic « après » (parc complet n=2274)** : undercrop **8.4 %→2.6 %** (191→60), **ok 97.4 %**, overcrop/wrong 0 %, r_ratio médian bimétal ~0.93→**~0.98**. (Le flag heuristique `bimetal_inner_ring` MONTE 11→18 % : normal — le crop contient maintenant les DEUX anneaux, signe que le rim externe est capté, pas l'inverse.)
- **Tail résiduel** (planche-contact `state/crop_diag/contact_sheet.jpg`) = surtout des **non-pièces** (coincards « MONNAIE DE PARIS », sets multi-pièces, capsules de bout) marquées OK par l'oracle géométrique → relèvent du **traitement humain** (trash + re-crop manuel), pas de l'algo. → Sessions suivantes : `docs/operations/crop-quality-overhaul/next-sessions.md`.

### Suites (prompts prêts : `next-sessions.md`)
- **Session A** — crop du scan Android (`normalize_device`/`SnapNormalizer.kt`), enjeu = cohérence train↔inference (le device a le même bug bimétal, non corrigé). Test manuel via `/dev/photo`.
- **Session B** — review crop manuelle (`features/review`) : trash le déchet (`training_eligible=0`) + éditeur de cercle pour re-crop manuel des ~2 % récupérables.
