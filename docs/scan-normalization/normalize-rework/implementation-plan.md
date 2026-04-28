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
| A | Bench `normalize_studio` (sandbox) | ⏳ todo | — |
| B | Baseline ε + R@1 + dataset parity | ⏳ todo | — |
| C | Implémentation prod | ⏳ todo | — |
| D | Validation R@1 ArcFace post-rework | ⏳ todo | — |
| E | Documentation finale + nettoyage | ⏳ todo | — |
| F | (Optionnel) Snap haute-res via `ImageCapture` | ⏳ todo | — |

**Phase actuelle** : aucune (rework pas encore démarré, doc en place).

**Prochaine action recommandée** : Phase A. Voir le bloc Phase A ci-dessous.

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

⏳ Todo

### 📝 Log & résultats

_(à remplir au fur et à mesure)_

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

⏳ Todo

### 📝 Log & résultats

_(à remplir)_

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

⏳ Todo

### 📝 Log & résultats

_(à remplir)_

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

⏳ Todo

### 📝 Log & résultats

_(à remplir)_

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
