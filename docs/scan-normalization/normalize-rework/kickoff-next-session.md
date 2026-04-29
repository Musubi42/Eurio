# Kickoff — reprise du rework normalize

> Lecture : 2 minutes. Met-toi (et Claude) à jour sur l'état du rework et la prochaine action concrète. Si quelque chose ici diverge de `implementation-plan.md`, le plan a raison — ce document est un raccourci, pas la vérité.

## TL;DR

Le rework `normalize_snap` est **fonctionnellement terminé**. R@1 ArcFace = **94.74%** (+27 pts vs baseline ~68%), `prepare_dataset` quelques secondes (vs >1h), parity gate `studio ↔ device` à **100%** sur Hough-OK subset (25/25 images, ε=3.00) après le **fix offset device du 2026-04-29** (cascade Hough device revert de 0.35-0.55 à 0.15-0.55, le tight pickssait des cercles parasites sur frames device — détails dans le log Phase C de `implementation-plan.md`).

Reste : (1) **valider le port Kotlin** via `go-task ml:scan:diff` après rebuild APK avec le revert ; (2) **clore Phase E** (nettoyage doc + lint).

## État des phases

| Phase | Status |
|---|---|
| A — bench studio_contour | ✅ done |
| B — baseline ε + R@1 baseline | ✅ done partiel (per-class baseline perdu durant le crash 42 min, acceptable) |
| C — implémentation prod | ✅ done (C1, C2, C4, C5, C6 fermés ; **C3 ouvert** = Kotlin cross-platform) |
| D — validation R@1 post-rework | ✅ done partiel (D1 ✅ avec +27 pts ; D2/D3 indéterminés sans per-class baseline) |
| **E — doc + nettoyage** | **⏳ todo (prochaine action)** |
| F — Snap haute-res via `ImageCapture` | ⏳ todo (optionnel, hors-rework) |

## Prochaine action — Phase E (1-2 h)

Liste à dérouler dans l'ordre :

### 1. Fermer C3 (cross-platform Kotlin)

**But** : valider que `SnapNormalizer.kt` (downscale 1024 + cascade large 0.15-0.55 / 0.10-0.55 après le revert du 2026-04-29) produit un 224×224 ε_pf-équivalent à `normalize_device` Python.

**Étapes** :
```bash
go-task android:install        # rebuild APK avec le nouveau SnapNormalizer.kt
# capturer quelques snaps eval_real depuis l'app, puis pull :
adb pull /sdcard/eurio_debug ./debug_pull/<ts>/
go-task ml:scan:diff -- ./debug_pull/<ts>/
```

**Critère** : `ε_pf ≤ 2 / 255` (sub-LSB attendu vu que les deux côtés appellent les mêmes binaires OpenCV). Si > 2 / 255, c'est un drift de port à debug — points sensibles dans le port :
- `Imgproc.resize(..., INTER_AREA)` avec `Math.round(w / scale).toInt()` pour les dimensions cibles
- `(x * scale).toInt()` pour scale-back (truncation, miroir Python `int(x * scale)`)
- Cascade `PASSES` **0.15–0.55 / 0.10–0.55** alignée sur `_DEVICE_HOUGH_PASSES` Python (post-revert du 2026-04-29 — ne PAS resserrer sans tester sur frames device, voir leçon dans `implementation-plan.md` Phase C log)

Voir `app-android/src/main/java/com/musubi/eurio/ml/SnapNormalizer.kt` (commentaires en tête détaillent la mirror exacte).

### 2. Lint / format Python

```bash
# lance le linter du repo (à confirmer dans pyproject.toml)
ml/.venv/bin/ruff check ml/scan/normalize_snap.py ml/training/prepare_dataset.py ml/scan/sync_eval_real.py ml/scan/preview_normalized.py ml/scan/diff_kotlin_python.py ml/tests/bench_normalize.py ml/tests/measure_parity_baseline.py ml/tests/parity_test.py ml/tests/test_normalize_dispatch.py
```

### 3. Mise à jour `.gitignore`

```
ml/tests/_bench_out/
ml/tests/_bench_smoke/
ml/tests/_parity_out/
```

### 4. README parent + CLAUDE.md

- `docs/scan-normalization/README.md` : section "Évolution post-Phase 5" déjà présente, juste vérifier qu'elle reflète `normalize_studio` / `normalize_device` (pas `normalize`).
- `CLAUDE.md` repo-level : si une règle référence "harmonie d'implémentation = même algo des deux côtés", la nuancer en pointant vers VISION.md §"Le nouveau principe" (harmonie = sortie ε-équivalente, pas algo identique).

### 5. Décision finale `bench_normalize.py`

Le bench reste utile comme outil exploratoire (mesurer le coût de futures tweaks à `normalize_studio` ou `normalize_device`). À conserver tel quel. Pas un livrable de prod, pas dans CI.

### 6. Commit final

Tout en un seul commit propre : "scan-normalization: rework normalize_studio / normalize_device".

## Ce qu'il faut savoir avant de toucher quoi que ce soit

- **Ne pas lancer training dans un shell direnv-watched** : le run baseline (Phase B.5) a été tué à 42 min juste avant la fin par un re-source automatique de `.envrc` (la console a affiché `source ml/.venv/bin/activate` après le kill). Pour un long run : `nohup` + tmux, ou un shell où direnv n'est pas accroché.
- **`go-task` toujours, jamais `task` ni invocation directe** (mémoire repo).
- **Pas d'édition manuelle des tokens** Color.kt / Shape.kt / Spacing.kt — passer par `tokens.css` + `go-task tokens:generate` (mémoire repo).
- **Constants ArcFace figées** : `OUTPUT_SIZE=224`, `COIN_MARGIN=0.02`, `BG_COLOR=(0,0,0)`. Toucher ces valeurs = re-train + re-export TFLite. Hors scope sans validation explicite.
- **`WORKING_RES=1024`** est partagé Python ↔ Kotlin. Si tu le changes, il faut re-bench Phase A et re-mesurer ε Phase B.

## Découvertes notables (à garder en tête)

1. **Bug latent Hough sur bimétal commémo confirmé**. Sur ~36% du training set actuel, Hough vote l'anneau intérieur cupro/or au lieu du rim extérieur. Le studio_contour donne le rim correct via `minEnclosingCircle` post-Otsu, ce qui explique le bond R@1 +27 pts.

2. **Drift train↔inference latent** : `normalize_studio` (training) = rim, `normalize_device` (inference) = anneau intérieur sur les classes bimétal-trap. Cohérent par accident dans le training actuel mais sub-optimal. Mitigation possible : ajouter un fill_ratio guard équivalent au studio dans le device (hors scope rework actuel, à instruire séparément).

3. **`cross_max` est une mauvaise métrique de garde-fou** : sature à 255 dès qu'1 px de masque diverge. Le contrat utilise `cross_pct_diff ≤ 5%` ou MAE ≤ ε à la place (cf. `parity-contract.md` §"Test #1").

4. **Per-class R@1 à 16-52% sur certaines classes** (be-standard, fr-standard, de-kniefall, fi-2017) sont des problèmes orthogonaux : confusion embedding-space entre standards visuellement similaires, ou n_sources=1. Pas normalize-bound. À instruire séparément (ajouter sources, augmenter agressivement, ou matching multi-vue).

5. **Cascade Hough device : ne pas resserrer**. Le tight 0.35-0.55 / 0.30-0.55 a été tenté Phase C, validé Phase A sur sources studio (24 images Numista), et a cassé en prod sur frames device avec BG variable (cercles parasites du grain table/ombre/vignette outvotent le rim de la pièce — voir `implementation-plan.md` Phase C log §"Fix offset device"). La cascade prod actuelle est large `(0.15-0.55, 0.10-0.55)` à `WORKING_RES = 1024`. Si tu veux re-tighten un jour, il faut **étendre `parity_dataset.yaml` avec des frames device** (BG noisy) avant.

6. **Le ring guide vert ne dit pas "ta pièce a été détectée"** — il dit seulement "un cercle quelconque a été détecté". UX hint fixe au centre, par design (`CoinAnalyzer.kt:152-159`). Si jamais un futur bug ressemble à "ring vert mais snap décalé", c'est probablement un Hough qui pick un parasite — vérifier le `method` retourné et les params de cascade.

## Phase F (optionnelle, parallèle)

Snap haute-res via `ImageCapture` (CameraX). Indépendante du rework, sortie produit. Voir `implementation-plan.md` Phase F. Critère de ship : R@1 sur golden set ≥ baseline + 5 pts absolus (sinon abandon).

## Liens

- [`implementation-plan.md`](implementation-plan.md) — vérité, table des phases + log par phase
- [`bench-results-pre.md`](bench-results-pre.md) — chiffres pré et post-rework
- [`parity-contract.md`](parity-contract.md) — méthode de test, seuils, dataset
- [`algorithms.md`](algorithms.md) — spec des deux normalizers
- [`VISION.md`](VISION.md) — pourquoi le rework
