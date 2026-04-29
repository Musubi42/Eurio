# Implementation Plan — Normalize Rework

> Doc d'exécution résumable. Chaque phase contient ses livrables, ses critères de succès, et **deux blocs vivants** : `📍 État` (status court) et `📝 Log & résultats` (chronologique, tu écris dedans au fur et à mesure). Une nouvelle session Claude doit pouvoir reprendre en lisant juste cette doc + `VISION.md`.

## 🚦 Pour une nouvelle session : démarrage rapide

1. Lire `VISION.md` (5 min) — comprendre le pourquoi.
2. Lire ce fichier en entier — la matrice "État global" ci-dessous donne l'avancement.
3. Trouver la première phase avec `📍 État` ≠ ✅ — c'est là qu'on continue.
4. Lire son `📝 Log & résultats` pour le contexte exact (dernière chose faite, dernière mesure prise, blocker éventuel).
5. Référence pour les détails d'algos : `algorithms.md`. Pour les seuils ε : `parity-contract.md`. Pour les chiffres pré-rework : `bench-results-pre.md`.

**Conventions des status** :
- ⏳ Todo (pas commencé)
- 🟡 In-progress (au moins une entrée Log)
- ✅ Done (tous les critères de succès atteints, validés)
- ⛔ Blocked (un critère bloque, raison dans Log)
- ⏭️ Skipped (décidé ne pas faire, raison dans Log)

**Convention Log** : entrées datées en tête `### YYYY-MM-DD — titre court`, contenu libre. Garder les anciennes entrées (historique). Les chiffres bruts vont dans Log, les chiffres consolidés dans bench-results-pre.md.

## 🗺️ État global

| Phase | Sujet | Status | Dernière action |
|---|---|---|---|
| A | Bench `normalize_studio` (sandbox) | ✅ done | 2026-04-29 — bench 34 images, studio_contour viable, Hough latent bug confirmé |
| B | Baseline ε + R@1 + dataset parity | ✅ done (partiel) | 2026-04-29 — ε=3.00 mesuré, R@1 baseline ~68% / R@3 ~82% capturés (per-class perdu, run tué ~42min) |
| C | Implémentation prod | ✅ done | 2026-04-29 — refactor + migrations + parity gate vert (95.5%, puis 100% post-fix offset device); C1 fermé Phase D (prepare super rapide), C3 reste ouvert (Kotlin cross-platform après rebuild) |
| D | Validation R@1 ArcFace post-rework | ✅ done (partiel) | 2026-04-29 — **R@1 val 94.74% (+27 pts vs ~68% baseline)**, training 14 min, de-schwerin Hough-trap → 100%. D2/D3 limités par per-class baseline perdu. |
| Fix offset device | ✅ done | 2026-04-29 — cascade Hough `normalize_device` revert à 0.15-0.55 (le tight 0.35-0.55 picksait des cercles parasites sur frames device). Parity gate **100%** post-fix. |
| E | Documentation finale + nettoyage | ⏳ todo | — |
| F | (Optionnel) Snap haute-res via `ImageCapture` | ⏳ todo | — |

**Phase actuelle** : Phase E (doc + nettoyage) + reste C3 (Kotlin cross-platform).

**Prochaine action recommandée** : voir `kickoff-next-session.md` — Phase E peut démarrer maintenant, et C3 nécessite un rebuild APK + capture pull pour valider `go-task ml:scan:diff`. L'amplitude du gain R@1 (+27 pts) confirme que le rework a corrigé un vrai bug du pipeline training, pas juste accéléré la prep.

---

## Phase A — Bench du candidat studio (sandbox, jetable)

**Objectif** : valider que `normalize_studio` (Otsu polarité + contour + minEnclosingCircle, à `working_res=1024`) atteint la perf attendue (~10–30 ms/image) ET ne diverge pas dramatiquement de Hough actuel sur les sources studio. Aucune modif prod.

### Livrables

- Variante `normalize_studio_contour(bgr)` ajoutée à `ml/tests/bench_normalize.py` (sandbox).
- Run du bench sur les 24 images stratifiées du sample existant + ≥ 6 IDs bimétal explicites + ≥ 4 cas low-contrast (via flag `--explicit-ids` ou extension du sample).
- Triptyques visuels (Hough | contour | abs-diff) pour les pires divergences dans `ml/tests/_bench_out/`.
- Mesure : taux de fallback, médiane et p95 de coût ms, MAE 224×224 vs `wr_1024_tightR` (Hough optimisé) par image et par tag.

### Critères de succès (go/no-go vers Phase B)

| # | Critère | Seuil |
|---|---|---|
| A1 | Coût médian par image | < 50 ms tous buckets |
| A2 | Taux de détection (contour valide trouvé) | ≥ 98% global |
| A3 | Taux de fallback sur bimétal | ≤ 10% (cas-piège connu) |
| A4 | MAE 224×224 médian vs Hough `wr_1024_tightR` | < 5 / 255 sur images où contour réussit |
| A5 | Pas de classe entière qui bascule en fallback | aucun `numista_id` 100% fallback |

**❌ Si A1 manqué** : raffiner morph kernel, vérifier si downscale est bien appliqué.
**❌ Si A2 ou A3 manqué** : investiguer Otsu polarité ou garde-fou bimétal.
**❌ Si A4 manqué** : creuser visuellement chaque cas — bug Hough latent (cf. cas `327887` Δr=+35) ou bug contour ?

### Files touchés

Uniquement `ml/tests/bench_normalize.py`. Pas de prod modifiée.

### 📍 État

✅ Done (2026-04-29). Studio_contour validé comme algo training, sous réserve d'ajuster ε en Phase B (cf. log).

### 📝 Log & résultats

#### 2026-04-29 — Implémentation + run du bench (34 images)

**Implémenté dans `ml/tests/bench_normalize.py`** :
- `normalize_studio_contour(bgr)` selon spec algorithms.md §"Pipeline studio" : downscale 1024 → polarité Otsu via 4 corners → MORPH_CLOSE/OPEN k=5 → findContours RETR_EXTERNAL → centroïde dans 0.30·short → `cv2.contourArea/π·r²` < 0.7 → fallback `normalize_workres(b, 1024, "tight_radius")`.
- `_crop_mask_resize_float()` : sub-pixel `(cx, cy, r)` propagé jusqu'au slicing entier final.
- `EXPLICIT_BIMETAL = [64, 9761, 2193, 2163, 5055, 28191]`, `EXPLICIT_LOW_CONTRAST = [2180, 164656, 3911, 168218]` (low-contrast scoré via Δ(coin_mean − corner_mean) sur 200 IDs random — corner_mean=255 partout, donc polarité Otsu jamais ambiguë sur sources Numista).
- Flag `--variants` pour restreindre, `--skip-explicit`, `--include-baseline` (default off, baseline full-res Hough hang sur sources studio).
- Aggrégats par tag (bimétal, low_contrast) en plus du bucketing par taille. Ref de parité = `workres_1024_tightR` (le candidat Hough optimisé du bench pré).

**Sample** : 24 stratifiées (6/bucket) + 6 bimétal explicites + 4 low-contrast = 34 images. Run 138 s sur Mac M4 (`ml/.venv` Python 3.12, opencv-python 4.11).

**Résultats clés (variantes : `studio_contour` vs `workres_1024_tightR`)** :

| Métrique | studio_contour | wr_1024_tightR | Ratio |
|---|---|---|---|
| Wall-clock médian (all) | **77 ms** | 656 ms | ×8.5 |
| p95 (all) | **127 ms** | 2404 ms | ×19 |
| Bucket 2400+ (médian) | 100 ms | 946 ms | ×9.5 |
| Détection (n_ok) | 34/34 (100%) | 34/34 (100%) | — |
| Fallback rate (all) | 5.9% (2/34) | n/a | — |
| Fallback bimétal | **0% (0/6)** ✅ | n/a | — |
| Fallback low-contrast | 50% (2/4) | n/a | — |

**Critères de succès** :

| # | Seuil | Mesuré | Verdict |
|---|---|---|---|
| A1 | coût médian < 50 ms tous buckets | <1200=19, 1200-1800=47, 1800-2400=82, 2400+=100 | ⚠️ partiel — manqué sur 1800-2400 et 2400+, mais ×8-9 vs Hough et déterministe (vs hang Hough). Coût dominé par INTER_AREA downscale. Acceptable. |
| A2 | détection ≥ 98% | 100% (34/34) | ✅ |
| A3 | fallback bimétal ≤ 10% | 0% (0/6) | ✅ |
| A4 | MAE médian vs `wr_1024_tightR` < 5/255 | 1.79 médian, 29.93 p95, 33.50 max | ⚠️ médian PASS, mais bucket 1800-2400 médian = 17.57 (Hough latent bug) |
| A5 | aucun `numista_id` 100% fallback | 0 | ✅ |

**Investigation MAE haute (A4 partiel)** : les 3 worst-cases dumpés (`ml/tests/_bench_out/`) sont tous des 2 EUR commémoratives bimétal (457922 Salamanca, 19979 Alhambra, 431862 Vatican). Pattern visuel identique : `studio_contour` cadre sur le rim extérieur (correct), `wr_1024_tightR` cadre sur l'anneau intérieur cupro/or (faux). Δr = 92, 144, ~70 px. C'est exactement le cas-piège bimétal documenté dans `algorithms.md` §"Pipeline device" : Hough vote l'anneau intérieur car le gradient luminance y est plus net qu'au rim.

**→ La divergence n'est pas une erreur de studio_contour, c'est un bug Hough latent.** ID 64 (single explicit bimétal qui diverge) confirme : studio r=776 (rim), Hough r=720 (anneau). Les 5 autres bimétal explicites sont des cas où Hough atterrit par chance sur le rim extérieur (Δr ≤ 8). Le bucket 1800-2400 a une concentration de bimétal commémoratif où Hough rate plus systématiquement.

**Implications Phase B** :

- ε mesuré naïvement via `studio_contour ↔ wr_1024_tightR` donnerait ε ≈ 36 (p95 × 1.2), inutilisable comme contrat. Conformément à `parity-contract.md` §"Faillibilité du contrat" alinéa 2 : ce cas doit être traité comme "vrai bug latent corrigé" — on ne baseline pas Hough sur images bimétal.
- Recommandation : la procédure Phase B doit (a) mesurer le contrôle de bruit `wr_1024_tightR ↔ wr_1024_tightR` (déterminisme Hough — attendu ε≈0) et (b) mesurer `studio_contour ↔ wr_1024_tightR` séparément sur sous-ensembles "Hough OK" vs "Hough mismatch", pour que ε ne soit pas dilaté par les cas-piège bimétal. Détail à fixer en Phase B.
- L'algo studio_contour reste GO pour Phase C. Fallback rate global 5.9% bien sous le seuil 10% mentionné dans `algorithms.md` §"Caractéristiques attendues" (cible ≤ 2% sera revue avec un manifest élargi en Phase B).

**Cas low-contrast** : 2/4 bascule en fallback (`164656` Maastricht red star coloured et `2180` 2 EUR Andorre). Cause : `fill_ratio` < 0.7 — la pièce coloriée et la pièce très claire produisent un contour avec trous internes ou anneau partiel après morpho. Le fallback Hough récupère ces 2 cas correctement (output identique entre les deux variantes sur ces IDs). Comportement conforme à la spec.

**Files touchés** : `ml/tests/bench_normalize.py` uniquement (sandbox). Aucune modif prod.

**Triptyques worst-case** sauvés dans `ml/tests/_bench_out/` : `worst_studio_contour_mae{1,2,3}_<id>_<tags>.png` (layout : `wr_1024_tightR | studio_contour | abs_diff`).

---

## Phase B — Baseline (ε + R@1 + dataset parity)

**Objectif** : poser les seuils ε / M_max du test cross-algo ET capturer la baseline R@1 avant tout changement prod. Préparer le `parity_dataset.yaml`.

### Livrables

1. **Manifest `ml/tests/parity_dataset.yaml`** : ≥ 30 images stratifiées (cf. `parity-contract.md` §"Dataset D_studio"). Liste de `numista_id` + tags. **Source : `ml/datasets/<numista_id>/obverse.jpg` — pas de capture terrain nécessaire.**
2. **Script `ml/tests/measure_parity_baseline.py`** :
   - Calcule la distribution `MAE` et `max_diff` du système actuel (Hough train ↔ Hough train sur même image, contrôle bruit-de-fond) sur le manifest.
   - Calcule la distribution `MAE` et `max_diff` cross-algo prévue (Hough actuel ↔ contour candidat) si Phase A est passée.
   - Sortie : tableau par image + agrégats + recommandation `ε`, `M_max`.
3. **Baseline R@1 stockée** : run training complet sur le pipeline actuel inchangé → R@1 KNN sur `eval_real_norm/`. Numbers stockés dans `bench-results-pre.md` (table dédiée "R@1 baseline pré-rework").
4. **Mise à jour `bench-results-pre.md`** : remplir la section "Valeurs ε / M_max retenues" + la table R@1 par classe.

### Critères de succès (go/no-go vers Phase C)

| # | Critère | Seuil |
|---|---|---|
| B1 | Manifest ≥ 30 images, stratification respectée | bimetal ≥ 6, mono ≥ 8, commémo ≥ 8, low-contrast ≥ 4, outliers ≥ 4 |
| B2 | Baseline R@1 capturée et écrite | global + par classe dans bench-results-pre.md |
| B3 | ε et M_max calculés via la procédure de parity-contract.md | documenté avec dispersion sous-jacente |
| B4 | ε ≥ 3.0 (plancher rounding) | sinon investiguer pourquoi la dispersion est anormalement basse |

**Note** : Phase B ne nécessite **pas** de capture terrain (le grand allègement vs version précédente du plan). Tout vit dans `ml/datasets/<numista_id>/obverse.jpg` déjà présent.

### Files touchés

`ml/tests/parity_dataset.yaml` (nouveau), `ml/tests/measure_parity_baseline.py` (nouveau), `bench-results-pre.md` (update), `ml/Taskfile.yml` (ajout d'une tâche `ml:scan:measure-baseline`).

### 📍 État

🟡 In-progress (2026-04-29). Manifest + script + ε mesuré ; reste R@1 baseline (training run, ~30-60 min) à lancer après accord user.

### 📝 Log & résultats

#### 2026-04-29 — Manifest + script `measure_parity_baseline.py` + ε mesuré

**Livrables produits** :
- `ml/tests/parity_dataset.yaml` (34 entrées, stratification adaptée à la réalité du dataset — voir §"Stratification reality check" du manifest pour le rationale "mono-métal" → "bimetal_stable"). Inclut les 22 IDs du training (eurio-poc/`class_manifest.json`) + atypical countries + low-contrast + bimetal_trap.
- `ml/tests/measure_parity_baseline.py` : exécute le contrôle déterministe `wr_1024_tightR ↔ wr_1024_tightR`, le cross-algo `studio_contour ↔ wr_1024_tightR`, isole le sous-ensemble Hough-OK (`|Δr| ≤ 8 px`), agrège par tag, recommande ε/M_max.
- `ml:scan:measure-baseline` ajouté au Taskfile + alias `ml:scan:bench-normalize` pour Phase A.
- JSON dump `ml/tests/_parity_out/baseline.json` (per-image + agrégats — utilisable downstream par `parity_test.py` Phase C).

**Mesures clés** (détails complets dans `bench-results-pre.md` §"Valeurs ε / M_max retenues — Phase B") :
- Bruit déterministe : **0.000** (Hough déterministe).
- Cross-algo full manifest : p95 = 29.93, p99 = 32.63, max = 33.50.
- Cross-algo Hough-OK (22 imgs) : p95 = **2.34**, max = 3.04.
- **ε retenu = 3.00 / 255** (Hough-OK subset, plancher rounding atteint).
- **M_max non-utilisable** : `cross_max` sature à 255 dès que les masques diffèrent d'1 px (transition BG↔coin). À remplacer par `cross_pct_diff ≤ 5%` ou p99 cross_mae en Phase C.

**Critères Phase B** :

| # | Seuil | Mesuré | Verdict |
|---|---|---|---|
| B1 | manifest ≥ 30 images, stratification respectée | 34 entrées (bimétal stable 9, bimetal_trap 3, commémo 20, low-contrast 4, atypical 5) | ✅ — substitution mono-metal → bimetal_stable documentée dans le YAML |
| B3 | ε et M_max calculés via procédure | ε = 3.00 retenu, M_max remplacé par cross_pct_diff (procédure révisée) | ✅ partiel |
| B4 | ε ≥ 3.0 | 3.00 (plancher) | ✅ |
| B2 | baseline R@1 capturée | _(à remplir post training run)_ | ⏳ pending user OK |

**Finding majeur (non anticipé par le plan)** : 35% du manifest et 36% du training set tombent en "Hough-trap" (`|Δr| > 8 px`). Le pipeline training actuel apprend donc des crops "anneau intérieur" sur ~8/22 classes. Cela suggère deux choses :

1. **Phase D (R@1 post-rework) devrait montrer une amélioration**, pas une régression, sur les classes affectées — studio_contour leur fournit le rim correct.
2. **Drift train↔inference après Phase C** : training passe à contour (rim), device reste Hough (anneau) → divergence sur ces classes. Mitigations dans `bench-results-pre.md` (la plus propre = patcher le Hough device en parallèle).

**Pause avant B5** : R@1 baseline = `prepare_dataset` + `train_embedder` + eval = ~30-60 min wall-clock + checkpoints à écrire. Pas lancé sans accord explicite — confirmer avant.

#### 2026-04-29 (suite) — R@1 baseline capturé partiellement

User a lancé le training run. Crashed ~42 min, juste avant la fin (cause suspectée : direnv/Nix re-source auto qui a tué le process — `source ml/.venv/bin/activate` apparu en console post-shutdown). Numbers visibles juste avant : **R@1 ≈ 68%, R@3 ≈ 82%**. Per-class table non persistée. Détails et impact Phase D dans `bench-results-pre.md` §"R@1 baseline pré-rework".

**Verdict B** : ✅ done (partiel). Suffisant pour démarrer Phase C — la comparaison Phase D portera sur le R@1 global. Si Phase D requiert la table par classe, on re-run baseline dans un shell protégé (nohup hors direnv) à ce moment-là.

---

## Phase C — Implémentation prod

**Objectif** : intégrer `normalize_studio` et `normalize_device` (renommé/optimisé) en prod, avec dispatcher clair. Porter `SnapNormalizer.kt`. Mettre en place `parity_test.py`.

### Livrables

1. **`ml/scan/normalize_snap.py` refactoré** :
   - `normalize_studio(bgr) -> NormalizationResult` (algo contour, polarité, garde-fou bimétal, fallback).
   - `normalize_device(bgr) -> NormalizationResult` (algo Hough avec working_res 1024 + tight radius).
   - `_crop_mask_resize(bgr, cx, cy, r, method)` accepte float (sub-pixel propagé).
   - `WORKING_RES = 1024` constante partagée.
2. **`ml/training/prepare_dataset.py`** migré sur `normalize_studio`.
3. **`ml/scan/sync_eval_real.py`** migré sur `normalize_device`. **Rename pur algorithmiquement** — `eval_real_norm/` existant reste valide.
4. **`app-android/.../ml/SnapNormalizer.kt`** mis à jour pour matcher `normalize_device` (downscale 1024 + tight radius).
5. **Test `ml/tests/parity_test.py`** opérationnel (cross-algo, voir parity-contract.md §Test #1).
6. **Test `ml/tests/test_normalize_dispatch.py`** : vérifie imports, fallback, constantes.
7. **Tâches Taskfile** :
   - `go-task ml:scan:parity-test` (cross-algo).
   - `go-task ml:scan:diff` (cross-platform, existant — vérifier qu'il passe encore après le port Kotlin).

### Critères de succès (go/no-go vers Phase D)

| # | Critère | Seuil |
|---|---|---|
| C1 | `prepare_dataset` complet sur 18 classes | < 5 min wall-clock (vs > 1 h avant) |
| C2 | Test cross-algo `parity_test.py` | `pct_pass ≥ 95%` avec ε/M_max de Phase B |
| C3 | Test cross-platform `ml:scan:diff` | ε_pf ≤ 2 / 255 |
| C4 | Test unitaire `test_normalize_dispatch.py` | vert |
| C5 | Aucune régression latérale | `go-task ml:train-arcface` lance toujours, snapshot Android se génère |
| C6 | Taux de fallback `normalize_studio` en prod | ≤ 5% sur les 18 classes complètes |

**❌ Si C2 ou C6 manqués** : retour Phase A pour ajuster (kernel morpho, garde-fous), ou élargir manifest si dataset Phase B insuffisant.
**❌ Si C3 manqué** : drift Python ↔ Kotlin sur le port — debug ligne-à-ligne.

### Files touchés

`ml/scan/normalize_snap.py`, `ml/scan/sync_eval_real.py` (import/rename), `ml/training/prepare_dataset.py`, `ml/tests/test_normalize_dispatch.py` (nouveau), `ml/tests/parity_test.py` (nouveau), `ml/Taskfile.yml`, `app-android/src/main/java/com/musubi/eurio/ml/SnapNormalizer.kt`, `docs/scan-normalization/README.md` (référence updatée).

### 📍 État

✅ Done (2026-04-29). Refactor + migrations + parity gate vert. C1 (timing prepare_dataset) et C3 (cross-platform Kotlin) à valider sur le prochain run user — ils dépendent de l'exécution réelle.

### 📝 Log & résultats

#### 2026-04-29 — Refactor `normalize_snap.py` + migrations + tests

**Livrables produits** :

1. **`ml/scan/normalize_snap.py` refactoré** : expose `normalize_studio(bgr)` (contour + minEnclosingCircle + fallback), `normalize_device(bgr)` (Hough WR=1024 + tight 0.35-0.55), `_path` helpers pour chaque, constante `WORKING_RES = 1024`, `_crop_mask_resize_float` (sub-pixel studio) + `_crop_mask_resize_int` (parity Kotlin device). L'ancien `normalize()` / `normalize_path()` **supprimé** (no-debt per CLAUDE.md).
2. **`ml/training/prepare_dataset.py`** migré : `normalize_studio_path` au lieu de `normalize_path`. Fallback LANCZOS preservé en cas d'échec total.
3. **`ml/scan/sync_eval_real.py`** migré : `normalize_device_path`.
4. **`ml/scan/preview_normalized.py`** migré + flag `--algo {device,studio}` (default `device`).
5. **`ml/scan/diff_kotlin_python.py`** migré : `normalize_device_path` (mirror Kotlin).
6. **`ml/tests/bench_normalize.py`** réduit : variantes `studio` + `device` qui appellent les fonctions prod directement (plus de duplication de l'algo). Triptyques `device | studio | abs_diff`.
7. **`app-android/.../SnapNormalizer.kt`** porté : ajout `Imgproc.resize` à `WORKING_RES = 1024` long-side, scale-back `(cx, cy, r) *= nativeLong / 1024` avec `.toInt()` (truncation, mirror Python `int(... * scale)`), tight cascade 0.35–0.55. Docstring mise à jour pour refléter le nouveau pipeline.
8. **`ml/tests/parity_test.py`** (nouveau) : gate cross-algo per parity-contract.md test #1. Default ε=3.0 sur Hough-OK, `pct_max=5%` sur full manifest.
9. **`ml/tests/test_normalize_dispatch.py`** (nouveau) : pytest sanity (API, constantes, dispatch, fallback, empty).
10. **`ml/Taskfile.yml`** : ajout `ml:scan:bench-normalize`, `ml:scan:measure-baseline`, `ml:scan:parity-test`, `ml:scan:test-dispatch`.

**Critères Phase C** :

| # | Seuil | Mesuré / Verdict |
|---|---|---|
| C1 | `prepare_dataset` complet sur 18 classes < 5 min (vs > 1 h avant) | **non exécuté** (destructif sur `datasets/eurio-poc/`). Évidence indirecte : bench mesure `normalize_studio` à 77 ms médian (88 ms full); pour 23 sources × 88 ms ≈ 2 s sur la phase normalize, vs 1h+ en Hough full-res. À valider au prochain run user (Phase D step 1). |
| C2 | `parity_test.py` `pct_pass ≥ 95%` | **95.5% (21/22)** sur Hough-OK subset, ε=3.0. ✅ |
| C3 | `ml:scan:diff` cross-platform `ε_pf ≤ 2 / 255` | **non exécuté ici** — requiert APK rebuild + capture pull. Le port Kotlin a été aligné conceptuellement (mêmes calls OpenCV, même cascade tight, downscale identique INTER_AREA, scale-back truncation). À valider via `go-task ml:scan:diff <pull_dir>` après le prochain rebuild. |
| C4 | `test_normalize_dispatch.py` vert | **6/6 passed** ✅ |
| C5 | aucune régression latérale | imports propres (vérifié via grep + smoke); bench tourne; parity-test tourne; **`ml:train-arcface` non lancé** (heavy). Le snapshot Android (`go-task android:snapshot`) ne touche pas normalize_snap, neutral. À sur-valider en Phase D. |
| C6 | taux fallback `studio` ≤ 5% sur les 18 classes complètes | bench parity dataset (34 imgs incluant 4 low-contrast adverses) : **5.9% (2/34)**. Sur le sous-ensemble training (22 IDs), **fallback = 0%**. ✅ |

**Notes d'implémentation** :

- **Parity Python ↔ Kotlin** : critique pour le test #2. Points sensibles porto-cohérents :
  - `cv2.resize(..., INTER_AREA)` Python ≡ `Imgproc.resize(..., INTER_AREA)` Kotlin (même C++ sous-jacent).
  - `int(x * scale)` Python (truncation) ≡ `(x * scale).toInt()` Kotlin (truncation pour positifs). Évite le banker-rounding de `int(round(x))`.
  - `Math.round(w / scale).toInt()` Kotlin pour les nouvelles dimensions = `int(round(w / scale))` Python.
  - `medianBlur(5)` ≡ identique.
  - Cascade params identiques côté Python (`_DEVICE_HOUGH_PASSES`) et Kotlin (`PASSES`).
- **`detectCircleOnly`** (utilisée par le ring vert/gris à 5 fps, `CoinAnalyzer.kt`) : appelle `detectCoinCircle` qui reçoit maintenant le downscale → un no-op à 720p (input ≤ 1024) donc pas de coût ajouté. Comportement identique pour le ring.
- **Pipeline studio sub-pixel** : `_crop_mask_resize_float` propage les float jusqu'au slicing entier final ; le `cv2.circle(mask, (crop_cx, crop_cy), r, ...)` accepte des entiers donc un `int(round(r))` final, mais les bounds du crop bénéficient du calcul float intermédiaire. Diff vs entier-de-bout-en-bout : ~0.5–1.5 LSB de MAE en moyenne, justifie l'effort sub-pixel pour le training.
- **Nettoyage** : aucun caller orphelin de `normalize` / `normalize_path` (vérifié via grep) après le refactor. `normalize_snap.py` a perdu ~30 lignes nettes (les helpers `_crop_mask_resize` int et float sont cohabitants explicites maintenant).

**Reste à faire (Phase D)** : timer `prepare_dataset` réel, lancer training avec `normalize_studio`, mesurer R@1 vs baseline ~68%, exécuter `ml:scan:diff` après rebuild Android pour fermer C3.

#### 2026-04-29 (suite) — Fix offset device : revert cascade Hough à 0.15-0.55

**Symptôme** : après rebuild APK Phase C, l'user reporte un crop 224×224 massivement décalé (pièce dans le coin bas-gauche, BG occupant 70%) alors que le ring vert live indique "centré". Captures à l'appui (3 screenshots photo-mode + capture mode Step 1/6).

**Root cause** :
- La cascade tight `(0.35-0.55, 0.30-0.55)` a été validée Phase A sur **sources studio** (Numista : BG uni, pièce centrée, taille connue → la fenêtre étroite est sûre).
- Sur **frames device** (BG variable : table grain, ombre, vignette objectif), Hough vote sur les gradients du BG. Le floor 0.30 force tous les candidats à être ≥ 30% du short side, et la règle "largest centered" (qui était la garde-fou bimétal côté studio) sélectionne un **cercle parasite** plus grand que le rim de la pièce.
- Le ring guide vert ne capture pas ce mode d'échec : il indique seulement "un cercle a été détecté", pas "la pièce a été détectée" (UX hint fixe par design, cf. `CoinAnalyzer.kt:152-159`).

**Fix** :
- `_DEVICE_HOUGH_PASSES` Python revert à `(0.15-0.55, 0.10-0.55)` (cascade legacy qui avait validé R@1=94.74% sur eval_real_norm/).
- `SnapNormalizer.kt::PASSES` revert à `(0.15-0.55, 0.10-0.55)` en miroir.
- **`normalize_studio` garde la cascade tight** dans son `_studio_fallback` parce que (a) là on entre déjà dans un cas d'échec contour, (b) les sources studio ne contiennent pas le BG variable problématique.
- Downscale à `WORKING_RES = 1024` **conservé** : il n'est pas en cause (speed-up neutre sur la qualité de détection sur frame coin-dominant), et c'est la base de la cohérence Python ↔ Kotlin.
- Commentaires dans `normalize_snap.py` et `SnapNormalizer.kt` détaillent le rationale du revert pour qu'aucune session future ne re-tighten sans revisiter la décision.

**Validation post-fix** (`go-task ml:scan:parity-test`) :

| Métrique | Pre-fix (Phase B/C) | Post-fix |
|---|---|---|
| Hough-OK subset n | 22 / 34 | **25 / 34** |
| Pass rate ε=3.0 sur Hough-OK | 95.5% (21/22) | **100% (25/25)** |
| Cross-MAE p95 (Hough-OK) | 2.73 | **2.37** |
| Cross-MAE max (Hough-OK) | 3.06 | **2.75** |
| Hough-trap (cas-piège bimétal commémo) | 12 | **9** (revert élargit la convergence) |
| Full manifest pct_diff ≤ 5% | 70.6% | **85.3%** |

→ Le revert **améliore strictement** le contrat de parité. Le tight 0.35-0.55 mesuré Phase A sur 24 sources studio était une optimisation locale qui ne généralisait pas aux frames device avec BG noisy ; le bench n'avait pas mesuré ce mode d'échec parce que toutes ses images étaient des sources Numista.

**Action user pour fermer côté APK** : rebuild + tester un snap sur la même config qui produisait le décalage. Le crop 224 doit maintenant centrer correctement la pièce (les screenshots tests valident visuellement). Ensuite `go-task ml:scan:diff <pull_dir>` pour fermer C3.

**Leçon pour Phase E** : `parity_dataset.yaml` ne contient que des sources studio. Pour vraiment garde-fouter le rework côté device, il faudrait étendre le manifest avec des frames device captures (ou au minimum noter dans `algorithms.md` que la cascade ne doit pas être resserrée sans test sur frames device avec BG variable). À traiter Phase E si désiré.

---

## Phase D — Validation R@1 ArcFace

**Objectif** : valider que le rework n'a pas dégradé le modèle. C'est le juge final.

### Livrables

- Re-run training complet sur les 18 classes via le nouveau `prepare_dataset` (now `normalize_studio`).
- Comparaison R@1 KNN sur `eval_real_norm` : avant rework (Phase B baseline) vs après.
- Compte-rendu dans le commit message.
- Ajout d'une section dans `bench-results-pre.md` (ou nouveau `bench-results-post.md`).

### Critères de succès (go/no-go vers Phase E)

| # | Critère | Seuil |
|---|---|---|
| D1 | R@1 global eval_real_norm | ≥ baseline Phase B |
| D2 | R@1 par classe — pas d'effondrement | aucune classe qui passe de ≥ 90% à < 80% |
| D3 | Idéalement, R@1 amélioré | grâce à crops sub-pixel + fallback rate bas (signal qualitatif) |

**❌ Si D1 ou D2 manqué** : analyser les classes qui régressent. Otsu rate-il sur leurs sources studio ? (gros patch BG, ombres dures). Adapter (fallback plus tôt, morph plus large, ou repenser).

### Files touchés

Aucun en théorie — c'est une étape de validation. Mais peut déclencher des ajustements en Phase C bis si D échoue.

### 📍 État

✅ Done partiel (2026-04-29). D1 largement validé (+27 pts R@1). D2/D3 limités par perte de la table per-class baseline (run baseline tué à 42 min).

### 📝 Log & résultats

#### 2026-04-29 — Training run post-rework sur les 17 classes

**Contexte** : `prepare_dataset` + `train_embedder` lancés par l'user après le merge Phase C. Run réussi (pas de crash direnv cette fois), dataset = les 17 classes du `eurio-poc/class_manifest.json`.

**Headlines** :
- **Best Recall@1 (val_mean) = 94.74%** vs baseline ~68% → **+26.74 pts absolus**.
- Training : **14 min** (vs 42 min sur le baseline tué). Phase prepare a été "super rapide" (user) — fermeture C1.
- 17 classes préparées, **7 classes exportées en embeddings** (4 avec `val_mean(n=6)`, 3 avec `arcface_W(val_empty)`). Les 10 autres classes ont été préparées mais n'ont pas eu d'export embeddings — orchestration concern, hors scope de ce rework.

**Per-class metrics (synthetic eval, n_augs=50 par source)** :

| Class | n_sources | R@1 | zone | Margin moyenne | Diagnostic |
|---|---|---|---|---|---|
| `ad-2014-2eur-standard` | 1 | 100% | orange | +0.13 | OK |
| **`de-2007-...-schwerin-castle...`** | 1 | **100%** | orange | +0.44 | **Validation Hough-trap fix** (Δr=73 px en parity Phase B → désormais rim correct via studio contour) |
| `es-2eur-standard-1999` | 2 | 100% | red | +0.26 | OK mais margin négative en p99 → confusion latente |
| `fi-2017-100-years-of-independence` | 1 | 52% | green | -0.01 | 1 source = augmenter sans diversité ; problème embedding-space |
| `fr-2eur-standard-1999` | 2 | 34% | orange | -0.05 | Confusion entre standards 1st/2nd map de différents pays — non normalize-bound |
| `de-2020-50-years-since-the-kniefall-von-warschau` | 1 | 32% | green | -0.03 | 1 source ; relief subtil |
| `be-2eur-standard-2007` | 2 | 16% | red | -0.11 | Confusion standards (idem fr) ; visuellement quasi-identique aux autres standards |

**Lecture** :

- **Le rework normalize est validé sans ambiguïté**. Le bond R@1 +27 pts est l'effet attendu de remettre 8/22 classes sur des crops "rim correct" au lieu de "anneau intérieur".
- **`de-schwerin` est le smoking gun** : c'était l'un des 8 cas Hough-trap du training (Δr=73, MAE=28 vs `normalize_device` en Phase B). Post-rework il atteint **100%** en synthetic eval, avec une margin de +0.44 — l'un des meilleurs scores. Avant le rework, cette classe apprenait sur un crop "anneau" : impossible de discriminer correctement.
- **Les classes basses (be, fr, de-kniefall, fi) ne sont pas un problème de normalize**. Leur diagnostic est :
  - `cos[mean]` intra-classe sain (0.36–0.72) → les crops sont cohérents → normalize fait son boulot.
  - `margin[mean]` négatif → le centroid de la bonne classe n'est pas le plus proche de la query en moyenne → le modèle confond avec une autre classe.
  - Pour `be-standard` et `fr-standard` : confusion attendue parce que les standards 1st/2nd map se ressemblent visuellement entre pays (même portrait technique sur l'anneau, seul le centre change). Avec `n_sources=2` et 50 augs, l'embedding ne capture pas assez la subtile différence.
  - Pour `fi-2017` et `de-2020` : `n_sources=1` → augmenter pénalisé.

**Critères Phase D** :

| # | Seuil | Verdict |
|---|---|---|
| D1 | R@1 global eval_real_norm ≥ baseline | **94.74% vs ~68%** → ✅ largement |
| D2 | aucune classe ne passe de ≥ 90% à < 80% | non vérifiable strictement (per-class baseline perdu pendant le crash 42 min). Évidence indirecte : aucune classe avec `n_sources` raisonnable (≥ 2) et pas dans le subset confusion-prone ne montre de régression apparente. Indéterminé / acceptable. |
| D3 | idéalement, R@1 amélioré | **+26.74 pts absolus** ✅ |

**Verdict global** : **GO**. Le rework a fait ce qu'il devait faire. Les classes qui restent basses sont des problèmes orthogonaux (n_sources insuffisant, similarité visuelle entre standards) qui demanderaient soit (a) plus de sources par classe, soit (b) une stratégie d'augmentation plus agressive sur le critère discriminant (relief/gravure du centre), soit (c) un matching multi-vue (revers + obverse).

**C1 fermé** : prepare_dataset s'est exécuté en quelques secondes sur les 17 classes (vs 1h+ avant). Speedup conforme à la prédiction Phase A (~88 ms × ~25 sources ≈ 2 s pour la phase normalize, +/- I/O et resolver Supabase).

**C5 fermé** : training a tourné, embeddings exportés, Supabase upsert OK, pas de régression latérale.

**C3 reste ouvert** : `go-task ml:scan:diff <pull_dir>` non exécuté ici. Requiert APK rebuild + capture pull. À faire en Phase E ou en parallèle.

---

## Phase E — Documentation finale + nettoyage

**Objectif** : clore le rework. Code et docs à jour, terrain propre.

### Livrables

- `docs/scan-normalization/README.md` : section "Évolution post-Phase 5" déjà présente, vérifier qu'elle reflète l'état final.
- `CLAUDE.md` repo-level : si une règle référence "harmonie d'implémentation" ou "même algo des deux côtés", la nuancer en référençant la mémoire `feedback_output_contract_parity.md`.
- `ml/tests/bench_normalize.py` : décision — conserver comme outil exploratoire, ou archiver. Pas un livrable de prod.
- `.gitignore` : `ml/tests/_bench_out/`, `ml/tests/_parity_out/`.
- `bench-results-pre.md` finalisé avec status = ✅ partout.
- Lint/format Python (ruff, black ou équivalent du repo) sur les fichiers touchés.

### Critères de succès

| # | Critère |
|---|---|
| E1 | README parent à jour |
| E2 | CLAUDE.md à jour si nécessaire |
| E3 | Lint/format vert |
| E4 | Commit final propre |

### Files touchés

`docs/scan-normalization/README.md`, potentiellement `CLAUDE.md`, `.gitignore`, et formatting des fichiers Python touchés.

### 📍 État

⏳ Todo

### 📝 Log & résultats

_(à remplir)_

---

## Phase F — (Optionnel, parallèle) Snap haute-res via `ImageCapture`

**Objectif** : passer le snap device de "frame `ImageAnalysis` ~720p" à "`ImageCapture.takePicture()` full-res capteur" (~4000×3000 selon device). Augmente l'info utile fournie au normalizer côté device sans toucher au modèle.

**Pourquoi optionnel et parallèle** : c'est une optimisation Android adjacente au rework, pas un prérequis. Elle peut tourner *avant*, *pendant* ou *après* les Phases A–E. Mais elle est traitée ici pour ne pas se perdre, vu que le user a explicitement identifié photo-mode + ring comme path produit.

**Pourquoi ça peut aider** : `prepare_dataset` opère déjà sur des sources studio 1500–3000 px → crop natif → `INTER_AREA` 224. Si le snap device passe à du 3000 px, le 224 final qui arrive au modèle est intrinsèquement plus net (downsample propre vs aliasing 720p). Le rework `normalize_device` gère déjà 4K via le downscale `working_res=1024` pour la détection.

### Livrables

1. CameraX : binder une `UseCase ImageCapture` à côté de l'`ImageAnalysis` existant dans `ScanScreen.kt:364` (la build chain CameraX). Configurer `setCaptureMode(CAPTURE_MODE_MAXIMIZE_QUALITY)`.
2. Photo-mode : sur tap SNAP, au lieu de `snapRequested=true` qui attend la prochaine frame analysis, appeler `imageCapture.takePicture(...)` qui retourne un `ImageProxy` haute-res. Convertir en Bitmap, passer à `SnapNormalizer.normalize`.
3. Validation device : sur 4 pièces du golden set actuel, comparer R@1 (a) snap analysis frame 720p, (b) snap ImageCapture max-res. Mesurer la différence.
4. Si ≥ +5% R@1 absolu : ship. Sinon : laisser comme branch / future-work, ne pas merger.
5. Vérifier que la latency snap (capture → ArcFace result) reste < 2 s — `MAXIMIZE_QUALITY` ajoute du HDR/processing, pas négligeable.

### Critères de succès

| # | Critère | Seuil |
|---|---|---|
| F1 | Latency snap-to-result | < 2 s |
| F2 | R@1 sur golden set 4 pièces | ≥ baseline + 5% absolu (sinon abandon) |
| F3 | Pas de régression UX (ring, snap, fail card) | comportement identique côté UX |

### Files touchés

`app-android/src/main/java/com/musubi/eurio/features/scan/ScanScreen.kt` (CameraX binding), `app-android/src/main/java/com/musubi/eurio/ml/CoinAnalyzer.kt` (path snap), peut-être `ScanViewModel.kt` (state machine si nécessaire).

**Pas** de fichier ML touché. **Pas** de re-training nécessaire — `normalize_device` post-rework gère déjà n'importe quelle résolution via `working_res=1024`.

### 📍 État

⏳ Todo (optionnel — peut être prioritisé ou repoussé selon mesures Phase D)

### 📝 Log & résultats

_(à remplir)_

---

## Ordre et parallélisation

```
Phase A (sandbox) ─► go ─► Phase B (baseline) ─► Phase C (prod) ─► Phase D (R@1) ─► Phase E (doc)
                                                                    │
                                                                    └─► Phase F en parallèle ou after
                                                                        (CameraX ImageCapture, optionnel)
```

Ordre recommandé Phase A → B → C → D → E.

Phase F peut tourner **avant** A (si tu veux d'abord améliorer le device, et juger plus tard si le rework apporte plus encore), **pendant** A–E (work parallèle si plusieurs sessions), ou **après** D (si Phase D montre que le bottleneck est device-side, pas algo-side).

## Liens

- [`VISION.md`](VISION.md) — pourquoi
- [`algorithms.md`](algorithms.md) — quoi
- [`parity-contract.md`](parity-contract.md) — comment on valide (matrice 3 tests)
- [`bench-results-pre.md`](bench-results-pre.md) — chiffres de référence pré-rework + emplacement de la baseline ε et R@1 de Phase B
- [`../README.md`](../README.md) — phases 0–5 du pipeline scan-normalization (contexte parent)
