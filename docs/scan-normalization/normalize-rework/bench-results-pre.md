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

## Valeurs ε / M_max retenues — à remplir Phase B

**Procédure** : voir [`parity-contract.md`](parity-contract.md) §"Choix de ε et M_max". Mesure cross-algo sur image identique (pas sur paires train↔device).

**Provisoires (estimation pré-mesure)** :

- ε MAE : ~3–5 / 255 (~1.2–2%)
- M_max : ~40–80 / 255 (~16–31%)

**Mesurés Phase B** :

| Métrique | Valeur | Source |
|---|---|---|
| ε retenu | _(à remplir)_ | `measure_parity_baseline.py` |
| M_max retenu | _(à remplir)_ | `measure_parity_baseline.py` |
| MAE p95 (cross-algo Hough vs contour) | _(à remplir)_ | _(idem)_ |
| max_diff p99 (cross-algo) | _(à remplir)_ | _(idem)_ |
| Date mesure | _(à remplir)_ | — |

## R@1 baseline pré-rework — à remplir Phase B

**Procédure** : run training complet sur le pipeline actuel (sans toucher au code), eval R@1 KNN sur `eval_real_norm/`. Stocker ici **avant** de toucher quoi que ce soit en Phase C.

| Mesure | Valeur | Source |
|---|---|---|
| R@1 global (eval_real_norm) | _(à remplir)_ | training run output |
| R@1 par classe — table complète | _(à remplir, table 18 lignes)_ | _(idem)_ |
| Date mesure | _(à remplir)_ | — |
| Commit SHA pipeline mesuré | _(à remplir)_ | git rev-parse HEAD |

## R@1 post-rework — à remplir Phase D

| Mesure | Valeur | Δ vs baseline |
|---|---|---|
| R@1 global | _(à remplir)_ | _(à remplir)_ |
| R@1 par classe | _(à remplir)_ | _(à remplir)_ |
| Date mesure | _(à remplir)_ | — |
| Commit SHA | _(à remplir)_ | — |

## Status (miroir `implementation-plan.md`)

| Phase | Status |
|---|---|
| A — bench `normalize_studio` (sandbox) | ⏳ todo |
| B — baseline ε + R@1 + dataset parity | ⏳ todo |
| C — implem prod | ⏳ todo |
| D — validation R@1 ArcFace post-rework | ⏳ todo |
| E — doc + nettoyage | ⏳ todo |
| F — (opt) snap haute-res `ImageCapture` | ⏳ todo |
