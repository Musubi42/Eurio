# Scan Normalization — Plan d'implémentation

> Stratégie « Monde A » : on contrôle l'input du scan via un pipeline de normalisation strict (mask circulaire + crop + fond neutre + resize), et l'augmentation training reproduit **exactement** l'output de ce pipeline. On accepte n_sources=1 par classe et on compense par un alignement parfait train ↔ inference.

## Contexte

Run F1+F2+F3 (2026-04-27) : R@1 100% en train mais détection device cassée. Cause identifiée : `n_sources=1` par classe rend les métriques per-class tautologiques, et F2 (random backgrounds) introduit du bruit que l'inférence device ne voit jamais. Décision : virer F2, embrasser le contrôle strict de l'input.

## Décisions actées

- **Monde A** : pipeline d'inférence prend les snaps, applique mask circulaire + BG-remove + normalisation. Le modèle est entraîné sur des images visuellement identiques à cet output.
- **F2 supprimé** : plus d'augmentation `background` (plain/gradient/noise). Le fond hors-disque est **fixe et neutre** côté train et inference.
- **n_sources=1 conservé** : on ne tente pas d'élargir les sources obverses. L'alignement strict train↔inference compense.
- **F4 (pré-gen disque) abandonné** pour ce sprint — on y reviendra si pertinent une fois la détection qui marche.

## Phases

| Phase | Objet | Status |
|---|---|---|
| 0 | [Capture vérité-terrain](phase-0-capture.md) — golden set de snaps device par pièce | ✅ done (24/24) |
| 1 | `ml/scan/normalize_snap.py` (Hough → tight crop → black mask → 224) — 24/24 sur eval_real, OK studio | ✅ done |
| 2 | Augmentation training alignée : F2 viré, recipes vidés, prepare_dataset normalize, transforms = rot+affine+perspective+jitter+blur | ✅ done |
| 3 | Eval device-grade : `scan.sync_eval_real` → `datasets/eval_real_norm/` → auto-injecté en val/ par prepare_dataset → R@1 par epoch sur snaps réels | ✅ done (sync + prepare hook + train logs + aug preview) |
| 3b | **Centroid fix** : `compute_embeddings.py` préfère mean(val) sur W, fallback W si val empty. 50 % → 95.83 % sur eval_real_norm (= R@1 KNN training) | ✅ done |
| 4 | Port Kotlin (`SnapNormalizer.kt`) + UX live ring vert/gris + reset/snap dissociés. Validation Python ↔ Kotlin via `go-task ml:scan:diff` | ✅ done (4/4 device-validated, top1 0.91-0.97) |
| 5 | [Backlog Phase 5](phase-5-backlog.md) — auto AF/AE, sharpness gate, exposure gate, burst, auto-snap | 📋 backlog (à activer si signal d'échec mesuré) |

**Ordre strict** : 0 → 1 → 2 → 3 (→ 3b) → 4. Phase 5 attend qu'on ait scaling à 20+ classes pour mesurer les signaux d'échec et décider quelles pistes implémenter.

## Pièces du golden set (Phase 0)

4 classes du run actuel :

- `ad-2014-2eur-standard`
- `de-2007-2eur-schwerin-castle-mecklenburg-vorpommern`
- `de-2020-2eur-50-years-since-the-kniefall-von-warschau`
- `fr-2007-2eur-standard`

## Règles non-négociables

R0 (zéro dette), R1 (proto-first — n.b. la capture-mode est debug-only, hors scope proto), R2 (tokens auto-gen), `go-task` (pas `task`), staging git explicite par fichier.

## État actuel — pipeline normalize (post-rework 2026-04-29)

`scan/normalize_snap.py` expose deux pipelines partageant le même contrat de sortie 224×224 :

- **`normalize_studio(bgr)`** — sources Numista (training). Otsu + `minEnclosingCircle` à `WORKING_RES=1024`, garde-fou bimétal via `fill_ratio < 0.7`. Bascule sur `normalize_device` si la détection de contour échoue.
- **`normalize_device(bgr)`** — frames device (Android live + offline `eval_real_norm`). Cascade Hough `strict → loose` à `WORKING_RES=1024` avec une plage radius wide `0.15–0.55 / 0.10–0.55`. Mirroré bit-pour-bit par `app-android/.../ml/SnapNormalizer.kt`.

Tests :
- `go-task ml:scan:test-dispatch` — unit tests API publique
- `go-task ml:scan:parity-test` — gate cross-algo (ε = 3.0 sur sous-ensemble Hough-OK)
- `go-task ml:scan:diff -- <debug_pull>` — validation port Kotlin sur snaps device
