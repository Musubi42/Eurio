# Normalize Rework — Vision

> Refonte du pipeline `scan/normalize_snap.py` autour d'un nouveau principe de cohérence : **harmonie = contrat de sortie testé, pas implémentation identique**.

## Le déclencheur (2026-04-29)

`prepare_dataset.py` saturait à 1h+ pour 18 classes ; le bench `ml/tests/bench_normalize.py` a montré que `cv2.HoughCircles` sur les sources studio Numista (1500–3000 px) prend **15–200+ secondes par image**, sans borne supérieure stable — la perf est content-dependent (le voting + radius-refinement explose sur certaines images, indépendamment de la taille).

Optimisations explorées et leurs limites :

| Piste | Gain mesuré | Verdict |
|---|---|---|
| Compiler OpenCV+CUDA dans Nix | (non mesuré) | abandonné, complexité Nix > gain attendu |
| Downscale CPU avant Hough (working-res 1024) | ×5–10 | insuffisant : reste à 5–25 s/image sur les gros |
| Tighter radius range (0.35–0.55) | ×3 | utile mais pas seul |
| Combo working-res 1024 + tight radius | ×30–60 | plafond Hough atteint, 3–7 s/image sur 1700 px |

Même le meilleur Hough optimisable laisse le pipeline d'entraînement à plusieurs minutes par classe. Et plus important : `cv2.HoughCircles` est **un mauvais outil pour ce job**. Hough vote dans un espace 3D (cx, cy, r) avec un coût qui dépend du contenu, pas linéairement de la taille — c'est la cause de la variance folle qu'on observe.

## Le constat sous-jacent

Avant ce rework, la règle implicite était : **harmonie = implémentation identique**. `normalize()` Python et `SnapNormalizer.kt` Kotlin devaient être bit-pour-bit le même algo. Cette règle paraît rigoureuse mais elle a deux problèmes :

1. **Elle interdit d'utiliser l'algo optimal pour chaque contexte.** Les sources studio (BG uniforme, coin centré, qualité élevée) appellent un algo différent des frames caméra (BG variable, exposition fluctuante). Forcer le même Hough partout pénalise massivement le côté studio sans bénéfice côté device.

2. **Elle ne garantit pas ce qu'on veut vraiment.** Ce que voit ArcFace, c'est le 224×224 final. Si les inputs diffèrent (ils diffèrent : 720p Android vs 3000 px studio), le même code Python/Kotlin produit *de facto* des comportements différents — Hough avec `param2=30` sur 720p ≠ Hough avec `param2=30` sur 3000 px. L'harmonie d'implémentation est rassurante mais creuse.

## Le nouveau principe

**Deux pipelines sont cohérentes si, soumises à la même image source, elles produisent des sorties 224×224 ε-équivalentes.**

C'est-à-dire :
- L'unité de cohérence est la **sortie sémantique** (le 224×224 que lit ArcFace).
- La cohérence se mesure en **MAE pixel-à-pixel cross-algo sur image identique** (`N_studio(I) ≈ N_device(I)` à ε près, sur le même `I`). Pas sur des paires (capture studio, capture device) du même coin physique — ces paires diffèrent par l'acquisition (lumière, angle, reflets) bien plus que par les normalizers, et noient le signal qu'on veut tester.
- Le **seuil ε** est dérivé empiriquement de la dispersion observée sur le système actuel, ré-évalué périodiquement.
- Les **algos sous-jacents peuvent diverger** pour exploiter les contraintes de chaque contexte.

L'alignement train↔device de bout en bout (le vrai but produit) est mesuré séparément par **R@1 ArcFace sur `eval_real_norm`** — c'est le juge final, et la parité ε n'est qu'une condition nécessaire qu'on peut gate en CI.

## Ce que ça débloque

| Contexte | Algo proposé | Coût attendu |
|---|---|---|
| Training (sources studio Numista, BG uniforme) | Otsu threshold (avec check polarité) → largest contour → `cv2.minEnclosingCircle`, calculé à `working_res=1024` | ~10–30 ms/image, déterministe |
| Device (Android, BG noisy, photo-mode + ring) | Hough cascade à `working_res=1024` (variante `wr_1024_tightR` validée par bench), retour à la résolution native pour le crop | ~30–80 ms/snap |

Speedup training attendu : **×100–500** vs Hough full-res actuel. La pipeline `prepare_dataset.py` passe de 1h+ à quelques secondes pour 18 classes.

Speedup device : pas en cause (Hough sur 720p est déjà rapide). L'enjeu côté device est ailleurs : monter la résolution du snap (cf. ci-dessous).

## Réalité device : photo-mode + ring, pas live continu

L'expérience produit la plus fiable aujourd'hui n'est pas la détection live continue — elle a un taux d'échec significatif sous éclairage variable et bouge en main. Le path qui marche, déjà implémenté en mode debug (cf. `CoinAnalyzer.kt:130-222`, `SnapNormalizer.detectCircleOnly`) :

1. L'utilisateur cadre la pièce dans un cercle guide à l'écran.
2. À 5 fps, un Hough léger colore le ring (vert si cercle centré détecté, gris sinon).
3. Quand le ring est vert, l'utilisateur tape SNAP : la frame en cours est passée au normalizer complet → ArcFace.

C'est le path à honorer comme cible production. Le rework normalize doit garantir que ce snap (frame `ImageAnalysis` ~720p aujourd'hui) traverse `normalize_device` proprement.

**Levier indépendant** : aujourd'hui le snap utilise la frame `ImageAnalysis` (~720p). Le bumper à un `ImageCapture.takePicture()` au moment du tap (full-res capteur, ~4000×3000) augmente l'info utile fournie au normalizer sans toucher au modèle. C'est une optimisation Android adjacente au rework, traitée en Phase F optionnelle de l'`implementation-plan.md`.

## Garde-fous

Le risque du contract-based parity, c'est de *cacher* une régression sous une métrique mal définie. Trois tests, chacun gate un type de régression différent :

| Test | Mesure | Catch |
|---|---|---|
| **cross-algo** (nouveau) | `MAE(N_studio(I), N_device(I))` sur la même image studio | Drift entre les deux algos sur input identique |
| **cross-platform** (existant) | `MAE(N_device_py(I), Kotlin_hough(I))` via `ml:scan:diff` | Drift Python ↔ Kotlin du port `SnapNormalizer.kt` |
| **R@1 end-to-end** | R@1 KNN ArcFace sur `eval_real_norm` | Régression réelle de reconnaissance, le seul juge final |

Règles :

1. **Seuil ε dérivé empiriquement.** On mesure la dispersion sur le système actuel (Hough train ↔ Hough train sur même image, cas trivial où ε≈0 attendu hors bug Hough), on choisit ε avec marge.
2. **Cross-algo et cross-platform gate la CI.** `go-task ml:scan:parity-test` doit passer avant tout merge qui touche un normalizer.
3. **R@1 reste le KPI ultime.** Si la parité passe mais R@1 régresse, on revient en arrière. La parité ε est nécessaire mais pas suffisante.
4. **Fallback documenté.** Si l'algo studio rate (image atypique, polarité Otsu ratée), retomber sur l'algo device. La fallback chain est elle-même testée, et son taux ≤ 2% sur le bench.

## Ce qui ne change PAS

- `OUTPUT_SIZE = 224`, `COIN_MARGIN = 0.02`, `BG_COLOR = (0, 0, 0)` — les constantes du contrat ArcFace restent figées.
- **Le 224 est non-négociable dans ce rework.** L'input du backbone MobileNetV3-Small pré-entraîné ImageNet (`train_embedder.py:64`) est 224. Bouger l'input size = changer de backbone = retrain from scratch sans transfer ImageNet + re-export TFLite + re-bench latency device + nouvelle baseline R@1. Hors scope. Aucun stockage 1024 intermédiaire non plus : on ne crée pas de format dont rien ne se sert aujourd'hui.
- Inférence à une résolution > 224 est techniquement et sémantiquement impossible : la shape `[1,224,224,3]` est figée à l'export TFLite, et les features convolutives sont scale-tuned au 224 d'entraînement (les passer à 1024 produit des embeddings bruités).
- L'augmentation training reste alignée sur la sortie du normalizer (cf. principe Monde A, README parent).
- Le port Kotlin reste un port — mais il porte désormais l'algo *device-optimal*, pas l'algo studio.
- La règle "n_sources=1, BG fixe" du Monde A est intacte.

## Liens

- [`algorithms.md`](algorithms.md) — détail des deux algos (studio + device) et leurs paramètres
- [`parity-contract.md`](parity-contract.md) — méthode de test, seuils, dataset
- [`implementation-plan.md`](implementation-plan.md) — phases d'implémentation, files touchés, critères de succès
- [`bench-results-pre.md`](bench-results-pre.md) — chiffres de référence pré-rework (Hough full-res), pour comparer après
- [`../README.md`](../README.md) — pipeline phases 0–5 (contexte initial, n_sources=1, Monde A)
