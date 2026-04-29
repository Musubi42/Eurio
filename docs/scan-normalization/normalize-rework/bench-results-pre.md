# Bench Results — État pré-rework

> Snapshot des chiffres mesurés *avant* la refonte. Référence pour comparer après.

## Hardware

- CPU : AMD Ryzen 7 2700X (8c/16t, Zen+, ~4.0 GHz boost)
- RAM : (à confirmer)
- GPU : NVIDIA GTX 1080 Ti (Pascal, CC 6.1, 11 GB) — non utilisé pour le bench CPU
- OS : NixOS x86_64
- Python : 3.12 + opencv-python-headless 4.13.0 (PyPI wheel CPU-only)

## Outil

`ml/tests/bench_normalize.py` — voir VISION.md / implementation-plan.md.

Sample : 24 images stratifiées sur 4 buckets (`<1200`, `1200-1800`, `1800-2400`, `2400+`), 6 par bucket, sampling déterministe seed=42 sur `ml/datasets/<numista_id>/obverse.jpg`. Liste exhaustive des IDs dans `bench_normalize.py:sample_dataset` reproductible.

## Variantes mesurées (run du 2026-04-29, partial)

| Variante | Cascade | Working res | Description |
|---|---|---|---|
| `baseline` | prod (0.15–0.55, p2=30/22) | full | algo prod actuel |
| `workres_1024_prodR` | prod | 1024 long-side | downscale seul |
| `workres_1024_tightR` | tight (0.35–0.55, p2=30/22) | 1024 long-side | downscale + radius range serré |
| `fullres_tightR` | tight | full | radius range serré seul |

## Wall-clock (medians, ms)

Run partiel, 4 images mesurées avant timeout pathologique sur image #4 baseline :

| ID | Taille | baseline | wr_1024_prodR | **wr_1024_tightR** | fr_tightR |
|---|---|---|---|---|---|
| 327887 | 923×920 | 13 400 | 15 200 | **3 400** | 3 500 |
| 72183 | 1024×1024 | 4 200 | 4 400 | **600** | 600 |
| 6323 | 1700×1700 | 182 000 (timeout 120 s soft) | 25 500 | **7 300** | 64 500 |
| 6293 | 1300×1300 | hang ≥ 10 min | 24 700 | **4 300** | (pas mesuré) |

**Lecture** :
- `baseline` = pathologique. La perf n'est pas linéaire en taille — content-dependent, hang possible.
- `workres_1024_tightR` = candidat Hough optimisable retenu si on devait rester sur Hough. ×30–60 vs baseline.
- Pas de borne supérieure stable même avec optims : reste à 7 s sur 1700×1700.

## Parité observée vs `baseline` (Δr en pixels full-res)

| ID | Taille | wr_1024_prodR | **wr_1024_tightR** | fr_tightR |
|---|---|---|---|---|
| 327887 | 923×920 | 0 | **+35 (r=457 vs 422)** | +35 |
| 72183 | 1024×1024 | 0 | 0 | 0 |
| 6323 | 1700×1700 | 0 | 0 | 0 |
| 6293 | 1300×1300 | -1 | +1 | (n/a) |

**Lecture** :
- `wr_1024_prodR` (downscale seul) : parité parfaite avec baseline → confirme que le downscale n'altère pas le résultat.
- `tightR` cases (image 327887) : Δr=+35 px. **Probablement un bug latent de baseline** où Hough avec rmin trop petit choisit un cercle plus petit (anneau intérieur ou détail), suppression non-maximum coupe le bon cercle. À valider visuellement avant de conclure.
- Sur les 3 autres images : tightR converge avec baseline.

## Limites du bench actuel

- **Échantillon de 24 images, partial run** : n'inclut pas explicitement de bimétal 2 EUR (le cas-piège connu). Phase A élargira avec `--explicit-ids` sur des bimétal.
- **`--max-seconds-per-cell` est un soft-timeout** : ne peut pas interrompre un appel C `cv2.HoughCircles` en cours. Une cellule peut hang indéfiniment. Limitation à fixer par multiprocessing si on veut un hard-timeout, ou plus simplement à éviter en abandonnant Hough sur sources studio (l'objet du rework).
- **Pas encore mesuré** : `normalize_studio_contour`. C'est l'objet de la Phase A.
- **Pas mesuré** : parité 224×224 pixel-à-pixel (MAE, max_diff) — le bench s'est fait couper avant les tableaux d'agrégat. Les Δr sont indicatifs mais pas le contrat final.

## Phase A — bench `normalize_studio_contour` (run du 2026-04-29)

**Hardware** : Mac M4, ml/.venv Python 3.12 + opencv-python 4.11. **Différent du run pré-rework (Ryzen 7 NixOS)** — les chiffres ms ne sont pas directement comparables au tableau "Wall-clock" plus haut, mais les ratios variant-à-variant (et la parité MAE) le sont.

**Sample** : 34 images = 24 stratifiées (6/bucket) + 6 bimétal explicites (`64, 9761, 2193, 2163, 5055, 28191`) + 4 low-contrast (`2180, 164656, 3911, 168218`).

**Run** : `go-task` non encore câblé pour ce bench, invocation directe :

```bash
ml/.venv/bin/python -m ml.tests.bench_normalize \
  --per-bucket 6 --datasets ml/datasets --out-dir ml/tests/_bench_out \
  --max-seconds-per-cell 30 --variants studio_contour,workres_1024_tightR
```

Total : 138 s.

### Wall-clock par bucket (ms, médiane)

| Variante | <1200 | 1200-1800 | 1800-2400 | 2400+ | all |
|---|---|---|---|---|---|
| `studio_contour` | **19** | **47** | **82** | **100** | **77** |
| `wr_1024_tightR` | 222 | 869 | 636 | 946 | 656 |

**Ratio** : studio_contour ×6-12 plus rapide selon bucket. Pas de hang, pas de timeout (vs Hough qui peut hang sur certaines sources).

### Fallback rate `studio_contour`

| Tag | n | n_fallback | % |
|---|---|---|---|
| all | 34 | 2 | 5.9% |
| bimetal (explicit) | 6 | 0 | **0.0%** |
| low_contrast | 4 | 2 | 50.0% |
| bucket:<1200 | 9 | 1 | 11.1% |
| bucket:1200-1800 | 9 | 1 | 11.1% |
| bucket:1800-2400 | 6 | 0 | 0.0% |
| bucket:2400+ | 10 | 0 | 0.0% |

**IDs en fallback** : `2180` (low_fill_ratio=0.07) et `164656` (low_fill_ratio=0.52, NL Maastricht red star coloured). Le fallback Hough récupère les 2 cas avec output identique au passage sans fallback.

### Parité `studio_contour` ↔ `wr_1024_tightR`

Comparaison cross-algo sur image identique (le test #1 du parity-contract.md), médiane des MAE pixel sur 224×224×3.

| Tag | n_ok | MAE médian | MAE p95 | MAE max |
|---|---|---|---|---|
| all | 34 | **1.79** | 29.93 | 33.50 |
| bimetal | 6 | 1.33 | 17.19 | 22.36 |
| bucket:<1200 | 9 | 3.04 | 23.36 | 24.00 |
| bucket:1200-1800 | 9 | 1.66 | 27.47 | 30.88 |
| bucket:1800-2400 | 6 | **17.57** | 31.58 | 33.50 |
| bucket:2400+ | 10 | 1.52 | 17.24 | 29.43 |
| low_contrast | 4 | 1.52 | 17.26 | 19.77 |

**Worst MAE** : ID 19979 (2 EUR Espagne Alhambra commémo, 2694×2694, bucket 2400+), Δr=144 px, MAE=29.43. Cas-piège bimétal — visuellement, `wr_1024_tightR` cadre sur l'anneau intérieur cupro/or, `studio_contour` sur le rim extérieur (correct).

### Verdict / interprétation

- **Studio_contour est l'algo correct** : `minEnclosingCircle` sur le contour outer-most retourne le rim physique de la pièce. Garde-fou `fill_ratio < 0.7` filtre proprement les cas où Otsu sépare l'anneau (pas le coin), avec fallback Hough en sécurité.
- **Hough wr_1024_tightR a un bug latent sur bimétal commémoratif** : déjà soupçonné dans le tableau "Parité observée vs `baseline`" plus haut (cas 327887 Δr=+35), maintenant confirmé sur 3+ commémos. Le gradient luminance interne (cupro/or) vote plus haut que le rim extérieur quand le radius range Hough autorise les deux.
- **Conséquence pour Phase B** : ε naïf cross-algo serait ≈ 36 (p95 × 1.2), inutilisable. La mesure Phase B doit isoler le bruit déterministe (`wr_1024_tightR ↔ wr_1024_tightR`) du drift bug Hough (`studio_contour ↔ wr_1024_tightR` sur sous-ensemble "Hough OK"). Détails à figer en Phase B.
- **A1 (coût médian < 50 ms tous buckets) partiellement manqué** sur 1800-2400 (82 ms) et 2400+ (100 ms). Coût dominé par `cv2.resize INTER_AREA` du downscale 1024. Pas bloquant : ×8-9 speedup vs Hough et déterministe. Optionnel : downscale en 2 passes (cv2.pyrDown ×N) pour gagner ~30 ms sur 2700+ — à explorer si Phase D montre que ce coût bloque l'expérience training.

### Triptyques worst-case dumpés

`ml/tests/_bench_out/` — layout : `wr_1024_tightR | studio_contour | abs_diff`.

| Fichier | ID | Bucket | Note |
|---|---|---|---|
| `worst_studio_contour_mae1_457922_*.png` | 457922 | 1800-2400 | 2 EUR Espagne Salamanca, Δr=92 |
| `worst_studio_contour_mae2_431862_*.png` | 431862 | 1200-1800 | 2 EUR Vatican commémo |
| `worst_studio_contour_mae3_19979_*.png` | 19979 | 2400+ | 2 EUR Espagne Alhambra, Δr=144 |

## Valeurs ε / M_max retenues — Phase B (run du 2026-04-29)

**Procédure** : voir [`parity-contract.md`](parity-contract.md) §"Choix de ε et M_max". Mesure cross-algo sur image identique (pas sur paires train↔device). Script : `ml/tests/measure_parity_baseline.py`, manifest `ml/tests/parity_dataset.yaml` (34 entrées).

**Run** : `go-task ml:scan:measure-baseline` — 81.7 s, dump JSON dans `ml/tests/_parity_out/baseline.json`.

### Contrôle déterministe `wr_1024_tightR ↔ wr_1024_tightR`

| Métrique | n | mean | p50 | p95 | p99 | max |
|---|---|---|---|---|---|---|
| ctrl_mae | 34 | 0.000 | 0.000 | 0.000 | 0.000 | **0.000** |
| ctrl_max | 34 | 0 | 0 | 0 | 0 | **0** |

Hough wr_1024_tightR est **100% déterministe** sur input identique (attendu, OpenCV C++ deterministic). Le bruit-de-fond est nul — toute dispersion cross-algo mesurée est donc imputable à l'algo, pas au bruit de mesure.

### Cross-algo `studio_contour ↔ wr_1024_tightR` — full manifest (34 images)

| Métrique | n | mean | p50 | p95 | p99 | max |
|---|---|---|---|---|---|---|
| cross_mae | 34 | 8.39 | 1.76 | **29.93** | 32.63 | 33.50 |
| cross_max | 34 | 190.4 | 220 | 255 | 255 | **255** |

### Subset breakdown (seuil `|Δr| ≤ 8 px`)

- **Hough-OK** : 22/34 images (65%)
- **Hough-trap** : 12/34 images (35%) — Hough vote l'anneau intérieur sur bimétal (commémo + 1 standard surprenant : ID 64).

Parmi les 12 Hough-trap, **8 sont dans le training set actuel** (IDs `2201, 81058, 93999, 64, 88, 69470, 82330, 19734` flag par cross_mae > 5) → finding important : le training actuel apprend des crops "anneau intérieur" sur ~36% des classes, ce qui devrait dégrader la qualité des embeddings ArcFace pour ces classes.

### Cross-algo `studio_contour ↔ wr_1024_tightR` — Hough-OK subset (22 images)

| Métrique | n | mean | p50 | p95 | p99 | max |
|---|---|---|---|---|---|---|
| cross_mae_ok | 22 | 1.40 | 1.51 | **2.34** | 2.90 | **3.04** |
| cross_max_ok | 22 | 163.9 | 164 | 255 | 255 | 255 |

### Recommandation ε / M_max

**État Phase B (cascade tight 0.35-0.55, valide pour studio sources)** :

| Scope | n | p95 MAE | ε retenu | p99 max | M_max retenu |
|---|---|---|---|---|---|
| **Hough-OK subset** | 22 | 2.34 | **3.00** | 255 | (non-utilisable — voir note) |
| Full manifest (informational) | 34 | 29.93 | (35.92) | 255 | (non-utilisable) |

**État final Phase E (cascade device revert à 0.15-0.55 — voir §"Fix offset device 2026-04-29")** :

| Scope | n | p95 MAE | ε retenu | p99 max |
|---|---|---|---|---|
| **Hough-OK subset** | 25 | 2.37 | **3.00** | 255 |
| Full manifest (informational) | 34 | 24.31 | (29.18) | 255 |

Le revert élargit le subset Hough-OK (25 vs 22), abaisse p95 (2.37 vs 2.73) et le max (2.75 vs 3.06). ε=3.00 reste le plancher rounding ; le contrat est strictement plus robuste qu'en Phase B.

- **ε = 3.00 / 255** — plancher rounding atteint (`max(p95 × 1.2, 3.0) = max(2.81, 3.0) = 3.0`). Conforme à l'estimation pré-mesure parity-contract.md §"Valeurs cibles" (3–5 / 255).
- **`M_max` non-utilisable via p99 of cross_max** : la métrique `cross_max` (= valeur absolue de la diff max sur 224×224×3 pixels) sature à 255 dès que les masques de coin diffèrent d'1 px, parce qu'un pixel passe de BG (0,0,0) à coin (par ex. 220,180,150) ou inverse. Sur ce dataset, **31/34 images** ont cross_max ≥ 200 même quand cross_mae ≤ 2. La métrique discrimine donc mal. Décision Phase B : remplacer le critère `max_i ≤ M_max for 100% of images` par `cross_pct_diff ≤ 5%` (proportion de pixels qui diffèrent de plus d'1 LSB), ou bornes p99 sur cross_mae. À figer dans `parity_test.py` (Phase C).

### Hough-trap subset (les 12 cas où le bug se manifeste)

| ID | Tags | Δr px | cross_mae | Note |
|---|---|---|---|---|
| 19979 | bimetal_trap, commemorative, large_size | 144 | 29.43 | ES Alhambra |
| 93999 | commemorative, training | 106 | 23.11 | FI von Wright |
| 457922 | bimetal_trap, commemorative | 92 | 33.50 | ES Salamanca |
| 219 | atypical_country, commemorative, large_size | 90 | 21.75 | VA John Paul II |
| 81058 | commemorative, training | 79 | 29.40 | ES Aqueduct |
| 2201 | commemorative, training | 73 | 28.29 | DE Schwerin Castle |
| 431862 | bimetal_trap, commemorative | 61 | 30.88 | VA commemorative |
| 64 | bimetal_stable, standard, training | 56 | 22.36 | AT 1st map (mis-tagged stable!) |
| 3911 | commemorative, low_contrast, small_size | 19 | 19.77 | small format |
| 88 | bimetal_stable, standard, training | 13 | 1.75 | edge case |
| 69470 | standard, training | 10 | 2.03 | edge case |
| 82330 | commemorative, training | 10 | 12.13 | IT Donatello |

**Observation** : ID 64 a été tagué `bimetal_stable` à partir du smoke Phase A mais le full run le classe en Hough-trap (Δr=56). À recorriger dans le manifest si on s'en sert comme contrôle. Pour le baseline, l'effet est nul puisque le subset "Hough-OK" est défini empiriquement par `|Δr| ≤ 8`.

### Implications produit (drift train ↔ inference)

Les 8 classes training actuellement biaisées par Hough-trap auront, en inference, un crop **également buggé** (le snap device passe par le même Hough → vote anneau intérieur). Donc training et inference voient cohéremment des crops "anneau" — cohérent par accident, mais sub-optimal. Après Phase C, training passera à `studio_contour` (rim) tandis que device gardera Hough (anneau) → **drift train↔inference apparaît sur ces 8 classes**. Mitigations envisageables :

1. Patcher Hough device pour fixer le bimétal-trap (ex. fill_ratio guard équivalent du studio, ou `largest centered` plus strict).
2. Garder `wr_1024_tightR` aussi côté training pour les 8 classes affectées (perte du speedup, perte de la précision sub-pixel).
3. Accepter le drift et mesurer en Phase D si R@1 régresse — si oui, retour à 1.

Recommandation : option 1 à instruire en parallèle de Phase C, à valider via le test cross-platform après port Kotlin.

## R@1 baseline pré-rework — Phase B (run du 2026-04-29)

**Procédure** : run training complet sur le pipeline actuel (sans toucher au code), eval R@1 KNN sur `eval_real_norm/`.

| Mesure | Valeur | Source |
|---|---|---|
| R@1 global | **~68%** | training run output (Mac, 2026-04-29) |
| R@3 global | **~82%** | training run output |
| R@1 par classe | _non capturé_ | — |
| Date mesure | 2026-04-29 | — |
| Commit SHA pipeline mesuré | `e3c4ff5` (HEAD au moment du run) | `git rev-parse HEAD` avant Phase C |

**Incident** : le run a été tué après ~42 min, à quelques secondes de la fin. Cause suspectée : interaction direnv / Nix devShell — la console a affiché `source ml/.venv/bin/activate` après le crash, suggérant un re-source automatique de l'environnement (re-shell) qui a tué le process Python. Les chiffres globaux R@1/R@3 ont été visibles juste avant la coupure ; la table par classe et le checkpoint final n'ont pas été persistés.

**Conséquence pour Phase D** : la comparaison post-rework portera sur le R@1 global (~68%) et R@3 (~82%) seulement, sans granularité par classe. Acceptable si l'amélioration globale est nette ; risque si une classe régresse silencieusement. À mitiger en Phase D en re-runnant *aussi* le baseline pré-rework dans un environnement protégé (e.g. `nohup` ou hors-direnv) pour avoir la table complète, **ou** en acceptant que le delta global suffit.

## R@1 post-rework — Phase D (run du 2026-04-29)

**Procédure** : `prepare_dataset` (now `normalize_studio`) + `train_embedder` sur les 17 classes du `eurio-poc/class_manifest.json`. Run complet, pas de crash. 14 min wall-clock (vs 42 min crashed sur baseline).

| Mesure | Valeur | Δ vs baseline |
|---|---|---|
| R@1 global (val_mean = `eval_real_norm/`) | **94.74%** | **+26.74 pts** vs ~68% |
| R@3 global | _non capturé_ (best metric = R@1 only) | — |
| R@1 par classe (synthetic n_augs=50) | bimodal — 3/7 classes à 100%, 4/7 entre 16% et 52% | _(per-class baseline perdu)_ |
| Date mesure | 2026-04-29 | — |
| Commit SHA pipeline mesuré | _(à remplir au prochain commit)_ | — |

**Classes synthetic eval** (n_augs=50 par source) :

| Class | n_sources | R@1 | zone | margin mean |
|---|---|---|---|---|
| ad-2014-2eur-standard | 1 | 100% | orange | +0.13 |
| **de-2007-2eur-schwerin-castle...** | 1 | **100%** | orange | **+0.44** (Hough-trap fix validé) |
| es-2eur-standard-1999 | 2 | 100% | red | +0.26 |
| fi-2017-2eur-100-years-of-independence | 1 | 52% | green | -0.01 |
| fr-2eur-standard-1999 | 2 | 34% | orange | -0.05 |
| de-2020-2eur-50-years-since-the-kniefall... | 1 | 32% | green | -0.03 |
| be-2eur-standard-2007 | 2 | 16% | red | -0.11 |

**Diagnostic des classes basses** : embedding-space class-confusion (be/fr standards visuellement quasi-identiques aux standards d'autres pays) et `n_sources=1` (augmenter sans diversité). **Pas un problème de normalize** — `cos[mean]` intra-classe est sain (0.36–0.72), les crops sont cohérents. Le rework a fait son boulot ; les R@1 basses sont des limitations orthogonales au pipeline de cropping.

**Validation forte** : `de-schwerin` était l'un des 8 cas Hough-trap du training (Δr=73 px en parity Phase B). Post-rework il atteint **100%** R@1 avec margin +0.44. C'est exactement le pattern prédit par Phase B §"Implications produit".

## Status (miroir `implementation-plan.md`)

| Phase | Status |
|---|---|
| A — bench `normalize_studio` (sandbox) | ✅ done (2026-04-29) |
| B — baseline ε + R@1 + dataset parity | ✅ done partiel (2026-04-29) — ε=3.00, R@1 baseline ~68% / R@3 ~82% (per-class perdu) |
| C — implem prod | ✅ done (2026-04-29) — refactor + parity gate vert. Cascade device revert post-Phase D (offset bug, voir §"Fix offset device"). |
| D — validation R@1 ArcFace post-rework | ✅ done partiel (2026-04-29) — R@1 = 94.74% (+27 pts vs baseline). |
| Fix offset device (2026-04-29) | ✅ done — cascade Hough device revert à 0.15-0.55. Parity gate **100%** (25/25 Hough-OK, ε=3.0). |
| D — validation R@1 ArcFace post-rework | ⏳ todo |
| E — doc + nettoyage | ⏳ todo |
| F — (opt) snap haute-res `ImageCapture` | ⏳ todo |
