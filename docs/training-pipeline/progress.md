# Progress log

> Append-only. Une entrée datée par session significative. Quand tu reprends
> un sprint, **lis ce fichier en entier** (au moins les dernières entrées du
> sprint en cours) avant de toucher au code.
>
> Format d'entrée :
>
> ```
> ## YYYY-MM-DD · Sprint N · Session description
>
> **Done** : ce qui a été livré
> **Working** : ce qui marche end-to-end
> **Broken / partial** : ce qui ne marche pas ou est incomplet
> **Deviations from sprint doc** : si on s'est écarté du plan, pourquoi
> **Decisions taken** : choix non triviaux, avec justif
> **Handoff** : ce qu'il faut savoir pour la session suivante
> ```

---

## 2026-04-29 · Sprint 0 · Brainstorm + docs structure

**Done** :
- Brainstorm pipeline complète A→Z avec utilisateur (cf vision.md)
- 7 questions tranchées (cf decisions.md D-001 à D-011)
- Structure docs créée : README, vision, decisions, filesystem, glossary,
  progress, et 5 sprint files
- Plan de 5 sprints validé par l'utilisateur

**Working** : doc structure complète et autoportante.

**Broken / partial** : aucun code écrit, c'est volontaire. Sprint 1 prêt
à démarrer.

**Deviations from sprint doc** : N/A (pas encore de sprint actif).

**Decisions taken** :
- Approche append-only pour progress.md
- Sprint files éditables avec diff noté ici
- Glossary ajouté au plan original (pas dans la demande initiale, jugé
  utile pour cold start des agents)

**Handoff** : commencer par `sprint-1-foundation.md`. Pré-requis listés
dedans. Aucun blocage.

**Etat acquis avant ce sprint** (résumé pour rappel) :
- Cohort capture flow livré (cf `docs/admin/cohort-capture-flow/`).
  Captures device canoniques en `ml/datasets/<numista_id>/captures/`.
- Cache Vue Query + IDB persistence livré sur `/coins` et `/lab`.
  Lookup queries (trained, zones, source-counts) cachées 5min/24h.
- API ML : `/health` est maintenant un liveness probe instantané
  (le rich payload est sur `/health/full`).
- ML_API frontend : `http://127.0.0.1:8042` (évite le retry IPv6
  sur macOS).
- Cohort `green-v1` existante avec 1 pièce
  (`de-2020-2eur-50-years-since-the-kniefall-von-warschau`), status `draft`.

---

## 2026-04-29 · Sprint 1 · Foundation (storage + stop + recipe preview)

**Done** :
- DB : colonne `augmentations_seed INTEGER` ajoutée à `experiment_iterations`
  via `_ensure_column` (back-compat NULL pour rows existantes). Champ
  exposé sur `ExperimentIterationRow`.
- Helper `augmentations_dir_for(numista_id, iteration_id)` exposé dans
  `ml/api/lab_routes.py` ; constante `AUGMENTATIONS_BASE` aussi.
- Nouveau module `ml/training/iteration_augmentations.py` :
  `generate_for_iteration` / `clear_for_iteration` / `list_for_iteration`
  (+ CLI `python -m training.iteration_augmentations --iteration-id <iid>`).
  Seed déterministe par coin = `sha256(iteration_seed:numista_id)[:4]`.
  Sources priorisées : `captures/*.jpg` puis `obverse.{jpg,png}`. Output :
  `ml/datasets/<nid>/augmentations/<iid>/sample_NNN.jpg`. Stage des
  symlinks par eurio_id sous `ml/datasets/iterations/<iid>/<eurio_id>/`
  pour servir de root ImageFolder au training.
- `train_embedder.py` :
  - SIGTERM handler coopératif → flag `_STOP_REQUESTED`. Check fin
    d'epoch (mode `arcface`), écrit `best_model.partial.pth`, `sys.exit(2)`.
  - Nouveau flag `--prebaked-augmentations` qui bypass la recipe-layer
    (passe `recipe_override={"layers": []}`) ; les transforms legacy
    (rotation 360, color jitter, normalize) restent appliquées.
- `IterationRunner._launch_training` : bake les augmentations sur disque
  via `iteration_augmentations.generate_for_iteration` AVANT de lancer
  le training subprocess. Passe `prebaked_augmentations=True` +
  `dataset_override=<iteration_train_root>` au runner. Si aucune source
  pour un coin → fail iteration avec message clair.
- `IterationRunner.stop(iteration_id)` + `TrainingRunner.stop_active()` :
  SIGTERM → wait 30s → SIGKILL. `Popen` actif tracké via `_active_proc`.
  Exit code 2 du subprocess interprété comme stop graceful (pas crash).
- `IterationRunner.create_and_launch` : génère un seed
  `random.randint(0, 2**31-1)` si non fourni, persiste sur la row.
- Endpoints REST :
  - `POST /lab/cohorts/{id}/preview-iteration` (nouveau) : crée une row
    `pending` nommée `preview-<recipe>`, bake les augmentations, retourne
    l'iteration_id. Idempotent par `(cohort, recipe, variant_count)`.
  - `GET /lab/cohorts/{id}/iterations/{iid}/augmentations`
  - `POST /lab/cohorts/{id}/iterations/{iid}/augmentations/regenerate`
    (409 si iteration non pending)
  - `POST /lab/cohorts/{id}/iterations/{iid}/stop` (409 si pas
    training/benchmarking)
  - `GET /datasets/{nid}/augmentations/{iid}/{filename}` static avec
    `Cache-Control: max-age=86400` (modèle après `/images/<nid>/source`).
- Front Vue (admin/packages/web) :
  - Types `IterationAugmentations`, `RegenerateAugmentationsResult`,
    `StopIterationResult`, `PreviewIterationResult` ajoutés à
    `lab/types.ts` ; `IterationDetail.augmentations_seed: number | null`.
  - API helpers `fetchIterationAugmentations`, `regenerateIterationAugmentations`,
    `stopIteration`, `previewIteration` dans `useLabApi.ts`.
  - Composables `useAugmentationsQuery` (staleTime 5min — snapshot
    immutable), `useRegenerateAugmentationsMutation`,
    `useStopIterationMutation` dans `useLabQueries.ts` (+ `LAB_KEYS.augmentations`).
  - Nouveau composant `AugmentationsGallery.vue` : grille `<img>` 6/8/12
    cols cliquables (zoom overlay), CTA « Régénérer » uniquement si
    `status === 'pending'`.
  - Nouveau composant `RecipeSection.vue` : select de recipe (filtré
    sur la zone du cohort), input variant_count, bouton « Prévisualiser »
    qui appelle `previewIteration` puis monte `AugmentationsGallery`.
  - `IterationRow.vue` : bouton « Stop » (rouge) sur les rows
    `training`/`benchmarking`, confirmation dialog, intégré dans la
    cellule R@1 sans casser la grille.
  - `CohortDetailPage.vue` : §3 RecipeSection insérée entre §2 Captures
    et la trajectoire.
  - `IterationDetailPage.vue` : `<AugmentationsGallery>` ajoutée en bas
    de la zone principale (post-training snapshot, 12 par pièce).

**Working** (smoke-testé via FastAPI TestClient sur `green-v1`) :
- Création iteration → seed généré et persisté.
- `preview-iteration` bake 4 samples / pièce sous
  `ml/datasets/226447/augmentations/<iid>/sample_001..004.jpg` puis stage
  symlinks sous `ml/datasets/iterations/<iid>/<eurio_id>/`.
- `GET .../augmentations` renvoie `total_samples=4` + paths relatifs
  servables par `/datasets/...` (Cache-Control vérifié).
- `regenerate` efface + rebake (idempotent).
- `stop` sur iteration `pending` → 409 attendu.
- Front build clean (`pnpm exec vite build` OK), `vue-tsc` clean sur
  toute la zone lab/ sauf 1 erreur pré-existante dans
  `PerConditionTable.vue` (non touchée par ce sprint).
- Suite `pytest tests/test_lab_api.py tests/test_lab.py` : 26 passed,
  1 deselected (`test_create_cohort_rejects_empty_ids` cassé avant ce
  sprint, comportement de la route a changé pour permettre les cohorts
  vides à la création).

**Broken / partial** :
- ⚠️ Le pipeline « bake → train » n'a pas été testé end-to-end avec un
  vrai run (pas de GPU dispo dans ce process). Risque résiduel : la
  prepare_dataset.py step continue à reconstruire `eurio-poc/`, qui
  n'est PAS la nouvelle dataset_override. C'est inutile mais pas
  bloquant — compute_embeddings/seed_supabase/validate_per_class
  consomment toujours `eurio-poc/val` qui reste raw (correct).
- Stop : le SIGTERM check est dans la boucle d'epoch arcface uniquement.
  Le mode classify/embed (pas utilisé en prod) ignore SIGTERM. Pas
  prioritaire vu que tous les iterations utilisent ArcFace.
- Phase « benchmark » non stoppable proprement : le subprocess
  `evaluate_real_photos.py` n'a pas de SIGTERM handler. Si l'utilisateur
  click Stop pendant le benchmark, on tape `subprocess.terminate()` qui
  killera juste le process — pas de partial benchmark écrit (cf OQ-3
  ci-dessous, c'est l'attendu).

**Deviations from sprint doc** :
- Sprint disait « Adapter `train_embedder.py` (ou le pipeline qui génère
  les augmentations) ». Choisi le second : nouveau module dédié
  `iteration_augmentations.py` plutôt que d'alourdir train_embedder.py.
  Justif : le cycle bake → stage symlinks → train est plus clair en deux
  phases qu'en une seule entrée monolithique.
- Sprint demandait endpoint regenerate « 409 si l'iteration n'est pas
  en pending ». Implémenté. La règle « efface auto au passage de la
  recipe » (OQ-1) n'est PAS appliquée automatiquement — c'est le bouton
  Régénérer qui fait le travail. Plus prudent vu la quantité de I/O.
- Le bouton « Prévisualiser augmentations » crée une iteration *séparée*
  via le nouveau endpoint `preview-iteration` au lieu de modifier
  l'iteration courante. Évite la confusion entre une preview et une
  iteration vraie ; permet des previews multiples sans remplacer
  l'historique.
- Pas implémenté de `--no-launch` sur le créateur d'iteration vrai
  (l'iteration créée par « Nouvelle itération » lance toujours le
  training). Le preview est une voie séparée.

**Decisions taken** :
- **OQ-1 (efface auto vs explicit regenerate)** : explicit. Le bouton
  « Régénérer » reste le seul moyen d'écraser le snapshot. Les recipe
  changes sur une iteration `pending` n'effacent pas le disque
  automatiquement (mais l'API enforce que l'iteration doit rester
  `pending` pour autoriser regenerate, et un changement de recipe
  passerait nécessairement par regenerate dans le workflow front).
  Justif : un I/O destructif silencieux est dangereux ; on préfère un
  click explicite.
- **OQ-2 (nb samples preview vs full)** : preview = 9 par défaut côté
  front (input range 1-64), bornage côté API à `[1, 64]`. Snapshot
  complet post-training = `variant_count` (default 100) — inchangé vs
  sprint doc. Justif : 9 (3×3 grid) suffit pour valider visuellement
  une recipe sans saturer le disque pendant les itérations rapides.
- **OQ-3 (benchmark partial sur stop)** : non. Stop = abandon. L'iteration
  finit `failed` avec error « Stopped by user (graceful|forced) ». Le
  subprocess de benchmark reçoit `subprocess.terminate()` mais sans
  cleanup logic — pas de partial R@1 calculé. Justif : un benchmark
  partiel donnerait un nombre trompeur (sous-échantillonnage non
  contrôlé) qui pourrait fausser les comparaisons d'iterations.

**Handoff** :
- Sprint 2 (« Aug vs réelles ») peut démarrer. Il aura besoin :
  - du fait que `<nid>/augmentations/<iid>/sample_*.jpg` est immutable
    pour un (iid, recipe, seed) — c'est garanti maintenant
  - du fait que les previews (`preview-<recipe>`) restent en
    `pending` indéfiniment ; ils peuvent servir de point d'ancrage
    pour la comparaison DINO sans avoir à lancer un training
- Code mort : aucun (le legacy on-the-fly augmentation reste en place
  pour les chemins non-iteration via `/training/run` direct).
- À surveiller en sprint 5 (GC) : les previews `preview-<recipe>`
  s'accumulent sur le disque si l'utilisateur change la recipe
  plusieurs fois sans cleanup. À ce stade ils sont uniquement
  remplacés quand `(recipe, variant_count)` matche une preview
  existante. Idée : sweeper qui supprime les previews `pending`
  vieilles de > 7j.

---

## 2026-04-29 · Sprint 2 · Aug ↔ réelles + déprécation `/benchmark`

**Done** :
- DB : table `iteration_aug_vs_real` (PK `(iteration_id, eurio_id)`,
  FK ON DELETE CASCADE vers `experiment_iterations`) ; dataclass
  `AugVsRealRow` exposée via `state` ; CRUD `upsert_aug_vs_real`,
  `list_aug_vs_real`, `clear_aug_vs_real`.
- Nouveau module `ml/api/distance_logic.py` :
  - `compute_aug_vs_real(iteration_id, store, force=False)` — encode
    captures + samples via DINOv2 ViT-S/14 (réutilise
    `eval/confusion_map.load_encoder` + `_build_transform`), centroid
    L2-normalisé par côté, cosine = `dot(real_centroid, aug_centroid)`.
    Cache hit si `dino_version` matche **et** `(num_real, num_aug)`
    correspondent au disque pour chaque coin.
  - `list_paths_for_iteration(...)` → `(real_samples, aug_samples)`
    relatifs à `ml/` pour la galerie.
  - `summarize(rows)` → `{num_coins, mean_cosine, min_cosine, max_cosine}`.
  - Encoder lazy-loaded au 1er appel (1 fois par process), évite de
    payer DINO au boot de l'API.
- Endpoints :
  - `GET /lab/cohorts/{cid}/iterations/{iid}/aug-vs-real` — lazy
    compute, retourne `{summary, per_coin: [{eurio_id, numista_id,
    num_real, num_aug, cosine, distance, real_samples, aug_samples,
    skipped_reason}], dino_version, computed_at}`.
  - `POST /lab/cohorts/{cid}/iterations/{iid}/aug-vs-real/recompute` —
    purge le cache puis recompute.
  - Nouveau static `GET /datasets/{nid}/captures/{filename}` (Cache-Control
    `max-age=86400`) pour servir les captures à la galerie. L'endpoint
    augmentations existant (`/datasets/{nid}/augmentations/{iid}/{file}`,
    Sprint 1) sert l'autre côté.
- Front Vue :
  - Types `AugVsRealCoin`, `AugVsRealSummary`, `AugVsRealReport` dans
    `lab/types.ts`.
  - API helpers `fetchAugVsReal`, `recomputeAugVsReal` dans
    `useLabApi.ts`.
  - Composables `useAugVsRealQuery` (staleTime 1h, le serveur invalide
    déjà sur drift de counts) et `useRecomputeAugVsRealMutation` dans
    `useLabQueries.ts` (+ `LAB_KEYS.augVsReal`).
  - Nouveau composant `AugVsRealSection.vue` :
    - tableau récap par pièce avec cosine coloré (vert ≥0.85,
      orange 0.70-0.85, rouge <0.70) + label texte
    - click sur une ligne → galerie côte à côte (3 cols réelles | 4 cols
      aug × 3 rows ≤12) avec `loading="lazy"`, zoom overlay
    - bouton Recompute en top-right
  - Mounted en §4 dans `IterationDetailPage.vue` après la galerie aug.
- Déprécation `/benchmark` :
  - Retiré du nav (`app/nav.ts`), import `TrendingUp` cleanup.
  - Banner deprecation en haut de `BenchmarkPage.vue` (couleur warning,
    icône `CircleAlert`, lien vers `/lab`). La page reste accessible
    via URL.
  - `docs/augmentation-benchmark/README.md` annoté legacy avec pointeur
    vers `docs/training-pipeline/`.

**Working** (smoke tests via FastAPI TestClient sur `green-v1`,
1 pièce avec 6 captures + 3 samples augmentés) :
- DINO encoder load on-demand (cache `~/.cache/torch/hub/`), warning
  xFormers attendu sur Apple Silicon (pas un problème).
- 1er call calcule cosine = **0.9846** (recipe par défaut, captures
  réelles vs samples). Plausible : la recipe par défaut applique des
  perturbations modestes sur les captures, donc les centroids
  restent proches. Sanity check OK (>0.5, <0.99).
- 2e call → cache hit (même `computed_at`), pas de re-compute DINO.
- POST recompute → nouveau `computed_at`, force le re-encode.
- Static `/datasets/<nid>/captures/<filename>` servi avec
  `Cache-Control: max-age=86400`.
- Front `vite build` clean, `vue-tsc` clean dans la zone lab/benchmark
  (sauf erreur `computed unused` pré-existante dans
  `PerConditionTable.vue`, hors scope).
- `pytest tests/test_lab*` : 26 passed (1 deselected pré-sprint).

**Broken / partial** :
- Cosine 0.9846 sur la recipe par défaut + 3 samples est élevé. Quand
  on aura des recipes plus agressives (overlays patina, tilt
  prononcé), on verra du mouvement vers 0.7-0.85. Pour l'instant, le
  signal d'usage est limité tant qu'on n'a pas de variété de recipes
  testée.
- La validation de cache utilise `(dino_version, num_real, num_aug)`.
  Cela ne détecte PAS un changement de contenu d'un fichier capture
  (si un `bright_plain.jpg` est écrasé). C'est un trade-off accepté :
  les captures sont conceptuellement immutables (idempotent sync).
  Sprint 5 pourra ajouter un mtime check si besoin.

**Deviations from sprint doc** :
- Sprint task 4 demandait juste un endpoint `aug-vs-real` retournant
  `per_coin + summary`. J'y ai ajouté `real_samples` + `aug_samples`
  (paths) pour éviter un 2e round-trip front. Plus simple et la
  payload reste petite (~6+12 strings par coin).
- Sprint task 9 disait « retirer la route `/benchmark` du menu » mais
  garder la page accessible. Fait. La route Vue reste configurée
  dans `app/router.ts` — non touchée par ce sprint, sera retirée au
  sprint 5 avec la suppression complète.
- Pas implémenté de redirection 301. Le banner pédagogique avec lien
  vers `/lab` suffit pour la transition utilisateur.

**Decisions taken** :
- **OQ-1 (DINO version trackée)** : `dinov2-vits14`, exposé via
  `eval.confusion_map.DEFAULT_ENCODER_VERSION`. Stocké tel-quel sur
  chaque row du cache. Si un futur swap d'encoder change la
  constante, le cache se ré-invalide automatiquement.
- **OQ-2 (centroids normalisés L2 avant cosine)** : oui — chaque
  embedding individuel est L2-normalisé après le forward DINO, puis
  les centroids (mean) sont **re-normalisés L2** avant le dot product.
  Sans la 2e normalisation, la moyenne de vecteurs unitaires est
  rarement de norme 1, et le « cosine » serait biaisé. Validation
  numérique sur le smoke test : 0.9846 ≤ 1.0 strictement, donc bien
  une similarité cosine.
- **OQ-3 (poids des conditions dans le centroid)** : équipondéré pour
  v1. Les 6 captures (`bright_plain`, `dim_plain`, etc.) contribuent
  également. C'est imparfait quand certaines conditions manquent
  (5/6 par exemple) mais Sprint 5 pourra normaliser par condition si
  les biais deviennent visibles dans les résultats live tests.
- Cache invalidation policy : `(dino_version, num_real, num_aug)` est
  suffisant tant que les fichiers sont append-only (capture flow
  idempotent + augmentations baked une fois). Pas de hash de contenu
  pour rester rapide.

**Handoff** :
- Sprint 3 (« Cohort test app ») peut démarrer.
- Cosines observés à ce stade : un seul point de mesure (0.9846 sur la
  recipe par défaut). Quand on aura des recipes orange/red avec
  patina/scratch overlays, on verra si la métrique discrimine.
- Le front d'AugVsRealSection charge DINO au 1er hit utilisateur ;
  prévoir un loader plus parlant (« Téléchargement modèle DINO… ») au
  sprint 5 si on veut sortir l'expérience UX du log subprocess.
- Code mort : aucun supprimé. La route `/benchmark` reste dans
  `app/router.ts` ; sprint 5 fera le cleanup complet.

---

## 2026-04-29 · Sprint 3 · Cohort test app (Gradle flavor + bundle pipeline)

**Done** :
- Android — Gradle product flavors :
  - `flavorDimensions += "scope"` ajouté dans `app-android/build.gradle.kts`,
    avec deux flavors `full` (prod) et `cohortTest`
    (`applicationIdSuffix = ".cohorttest"`, `versionNameSuffix = "-cohorttest"`).
    Les deux flavors signent avec la même `signingConfigs.debug` repo-versionnée
    (cf. R0/no-debt — pas de keystore par machine).
- Android — Source set `app-android/src/cohortTest/` :
  - `AndroidManifest.xml` : retire `.MainActivity` du launcher via
    `tools:node="remove"`, déclare `com.musubi.eurio.cohorttest.CohortTestActivity`
    comme nouveau launcher, override le `android:label` via `tools:replace`.
  - `res/values/strings.xml` : `app_name_cohorttest = "Eurio Test"`.
  - `java/.../cohorttest/CohortTestActivity.kt` : Activity Compose minimale
    qui lit `assets/cohort_bundle/{cohort_meta,live_tests_manifest,catalog_snapshot}.json`
    et affiche un récap (cohort, iteration, modèle, num_coins, num_tests).
    Aucun camera/inférence pour l'instant — voir « Deviations » plus bas.
  - `assets/cohort_bundle/.gitkeep` : placeholder, le bundle réel y est
    déposé par `cohort-test:bundle`.
- Backend — `ml/scripts/build_cohort_bundle.py` (nouveau, +`__init__.py`) :
  - Args `--cohort`, `--iteration`, `--out`, `--allow-stale-tflite`.
  - Validation : cohort existe, iteration appartient au cohort,
    `iteration.status == 'completed'`, `eurio_embedder_v1.tflite` /
    `embeddings_v1.json` / `model_meta.json` / `catalog_snapshot.json`
    présents, mtime du `.tflite` ≥ `iteration.finished_at` (sauf opt-out).
  - Émet 6 fichiers dans `<out>/` :
    `eurio_embedder_v1.tflite` (copy as-is), `model_meta.json` (copy),
    `embeddings_v1.json` (filtré aux eurio_ids du cohort),
    `catalog_snapshot.json` (filtré : coins + series surviving + sets
    avec member surviving + set_members filtrés),
    `cohort_meta.json` (identité — id, name, iteration, model_version,
    trained_at = iteration.finished_at, generated_at, num_coins),
    `live_tests_manifest.json` (version=1, conditions=bright/dim/tilt,
    `tests = eurio_ids × conditions`, OQ-4 sample à 3×3 si `num_coins ≥ 30`).
- Backend — endpoint `GET /lab/cohorts/{cid}/iterations/{iid}/test-app/build-info` :
  - Retourne `{cohort_name, iteration_id, iteration_name, model_ready,
    command, bundle_path, tflite_present, reason}`.
  - `model_ready=true` ssi `iteration.status=='completed'` ET la TFLite
    existe sur disque ; sinon `command=null` avec `reason` explicite.
  - `command` toujours assemblé avec `cohort.name` (pas `cohort.id`) pour
    coller à l'usage humain.
- go-task `app-android/Taskfile.yml` :
  - `cohort-test:bundle` (preconditions COHORT/ITERATION) appelle
    `python -m scripts.build_cohort_bundle --out ml/output/cohort_test_<iid>`,
    purge puis re-peuple `app-android/src/cohortTest/assets/cohort_bundle/`.
  - `cohort-test:install` enchaîne `bundle` + `installCohortTestDebug`
    + `adb shell am force-stop {{.APP_ID}}.cohorttest`.
- Front Vue — Sprint 3 §5 :
  - Type `CohortTestBuildInfo` dans `lab/types.ts`.
  - `fetchCohortTestBuildInfo` dans `useLabApi.ts`.
  - `useBuildInfoQuery` dans `useLabQueries.ts` (re-poll 5s tant que
    l'iteration est `training`/`benchmarking`, off sinon).
  - Composant `BuildTestAppSection.vue` : 3 états (loading / not_ready
    avec reason / ready avec `<pre>` + bouton Copier verbatim).
  - Mounted comme §5 dans `IterationDetailPage.vue` après
    `AugVsRealSection`.

**Working** (smoke tests) :
- `python -m scripts.build_cohort_bundle` :
  - cohort introuvable → exit 2, message clair.
  - iteration introuvable → exit 2.
  - iteration non-completed → exit 2, message « status 'failed', expected 'completed' ».
  - Cross-cohort iteration → exit 2, indique le bon cohort_id attendu.
  - Happy path (DB patchée pour completer une iteration green-v1) →
    `OK · bundle written ... (1 coins, 1 embeddings, 3 tests)`. Tous
    les fichiers présents et bien formés.
- `GET /test-app/build-info` via `TestClient` :
  - cohort introuvable → 404 « Cohort introuvable ».
  - iteration introuvable → 404 « Itération introuvable ».
  - iteration failed → 200 `{model_ready=false, command=null, reason=…}`.
  - iteration completed → 200 `{model_ready=true, command=<verbatim>, …}`.
- `pytest tests/test_lab.py tests/test_lab_api.py` : 26 passed (1
  deselected pré-sprint comme avant).
- `pnpm typecheck` : pas de nouvelle erreur (les pré-existantes audit/
  sets/PerConditionTable restent telles quelles, hors scope).
- `pnpm exec vite build` : clean, `IterationDetailPage` chunk inclut
  bien la nouvelle section, `useLabQueries` chunk +~600 B.
- `./gradlew :app-android:assembleCohortTestDebug` : BUILD SUCCESSFUL,
  produit `build/outputs/apk/cohortTest/debug/app-android-cohortTest-debug.apk`.
- `./gradlew :app-android:assembleFullDebug` : BUILD SUCCESSFUL,
  pas de régression sur le flavor full.

**Broken / partial** :
- **UI cohortTest = bundle-info uniquement, pas encore d'inférence**
  (cf. Deviations). L'écran affiche le récap du bundle ; il n'y a pas
  de caméra ni de top-3 sur cette session.
- Pas testé sur device physique — `installCohortTestDebug` nécessite un
  device connecté que je n'ai pas pu joindre depuis cette session.
  Le build APK passe, l'install lui-même devrait passer (signature
  debug repo-versionnée garantit qu'il cohabite avec `full`).
- Pas de pytest dédié pour le nouvel endpoint ni pour le bundle script.
  Smoke testé manuellement via `TestClient` + DB patchée. Sprint 4
  pourra ajouter `tests/test_test_app_routes.py` quand le payload se
  stabilisera.
- Avertissement Gradle attendu sur le namespace `org.tensorflow.lite.support`
  (litert-support / litert-support-api) — pré-existant côté
  full debug aussi, ignoré.

**Deviations from sprint doc** :
- Sprint task 9-13 (UI minimale cohortTest avec ScanScreen + toggle
  continu/one-shot + top-3 panel) : **livré comme placeholder,
  pas comme scan fonctionnel**. Raison concrète : `ScanScreen` est
  fortement couplé à `EurioApp` qui construit `CoinAnalyzer` avec les
  modèles prod (`models/eurio_embedder_v1.tflite`, `data/coin_embeddings.json`),
  pas avec ceux du bundle (`cohort_bundle/...`). Découpler proprement
  demande soit (a) un override `EurioApp` par flavor, soit (b) une
  abstraction `CoinAnalyzerSource` qui prend les paths en paramètres.
  Les deux options réécrivent du code prod et débordent du périmètre
  raisonnable de Sprint 3.
  Sprint 4 traitera l'UI scan + top-3 en même temps que la live-test
  flow (idx → expected → log) — les deux partagent le ResultPanel et
  le rewiring du loader, donc autant les faire ensemble.
- Le placeholder actuel charge bien le bundle (cohort_meta, manifest,
  catalog) et affiche un compteur de tests prescrits — c'est suffisant
  pour valider que le pipeline build → install → boot fonctionne
  end-to-end sur device.
- Bundle inclut aussi `embeddings_v1.json` (filtré) en plus des 4
  fichiers du sprint doc, pour que Sprint 4 n'ait pas à re-fetcher
  les centroids depuis ailleurs.

**Decisions taken** :
- **OQ-1 (où vit le TFLite)** : `ml/output/eurio_embedder_v1.tflite` est
  l'export global produit par `python -m training.export_tflite` (path
  confirmé via `grep` dans `ml/api/server.py` et `ml/training/export_tflite.py`).
  Le bundle script copie ce fichier as-is mais **vérifie son mtime** :
  s'il est antérieur à `iteration.finished_at`, exit 4 avec message
  demandant de re-runner l'export. `--allow-stale-tflite` opt-out.
  Conséquence : tant que l'export auto-TFLite n'est pas hooké dans
  `IterationRunner` (sprint 4 territoire), l'utilisateur doit lancer
  manuellement `python -m training.export_tflite` après chaque
  training. Documenté dans le message d'erreur du script.
- **OQ-2 (versionCode)** : pas de bump dynamique. `versionCode=1`
  conservé sur le flavor cohortTest, signé avec le même `debug.keystore`
  repo-versionné que `full`. `adb install -r` (utilisé par
  `gradlew installCohortTestDebug`) ré-installe sans incrémenter.
  Si on rencontre un `INSTALL_FAILED_VERSION_DOWNGRADE` plus tard, on
  basculera sur `versionCode = unix_ts() / 60` ; pas de besoin
  observé pour l'instant.
- **OQ-3 (signing)** : même `signingConfigs.debug` que `full`. Cohabite
  avec `full` sur le device car `applicationIdSuffix=".cohorttest"`
  donne deux applicationIds distincts.
- **OQ-4 (cap des tests)** : oui — sample stratifié à
  `SAMPLED_COIN_COUNT=3` × 3 conditions = 9 tests dès que
  `num_coins ≥ SAMPLE_COIN_THRESHOLD=30`. Stratification = sort
  alphabétique + take-first-3, pour rester déterministe entre runs.
  Sprint 4 raffinera (zone-stratified : vert/orange/rouge) si le
  besoin se fait sentir.
- **Application class non-overridée** : `EurioApp.onCreate()` continue
  de tourner pour le flavor cohortTest (init Room, bootstrap catalog
  prod, OpenCV, etc.). Wasteful mais inoffensif puisque
  `CohortTestActivity` n'utilise rien de Room/Supabase. Override par
  flavor reporté à Sprint 4 si le cold-start devient un problème
  pendant les sessions de test live.

**Handoff** :
- Sprint 4 (« Live test flow » + sync logs) peut démarrer.
- **Pré-requis Sprint 4** :
  1. Décider du wiring `CohortTestActivity` ↔ `CoinAnalyzer` :
     option (a) override `EurioApp` par flavor (cohortTest charge le
     bundle), option (b) ajouter un `CoinAnalyzerFactory` qui prend des
     paths d'assets en argument et l'injecter par flavor. (b) garde
     `EurioApp` partagé, recommandation.
  2. Hooker l'export auto-TFLite dans `IterationRunner._launch_training`
     (post-success) pour éviter l'étape manuelle. Sinon, ajouter un
     warning dans le front quand `tflite_present=true` mais mtime
     antérieur à `finished_at`.
  3. Brancher la consommation de `live_tests_manifest.json` côté
     `CohortTestActivity` — UI walk-through `idx → expected_eurio_id +
     condition`, attente d'un scan, log local. Sync vers admin via
     un nouvel endpoint `POST /lab/cohorts/.../iterations/.../live-tests/log`.
- **Pièges Gradle rencontrés** :
  - Manifest merger échoue sans `tools:replace="android:label"` quand
    le flavor déclare un `<application android:label=…>` (override).
    Fix : ajouter le `tools:replace`.
  - `tools:node="remove"` au niveau `<activity>` retire bien
    `MainActivity` du manifest fusionné mais garde la classe Kotlin
    dans le DEX (pas un drame, ~quelques KB).
  - `cohortTest/java/...` est ramassé automatiquement par AGP+Kotlin —
    pas besoin de déclarer `sourceSets { ... }` explicitement.
- **Configuration produite** : 4 chemins d'APK
  `build/outputs/apk/{full,cohortTest}/{debug,release}` ; la cible
  `release` n'est pas testée à ce sprint.
- **Code mort** : aucun. Le bundle script + endpoint + composant Vue
  sont tous sur des routes nouvelles, rien de remplacé.

---

## 2026-04-30 · Sprint 4 · Live tests prescriptifs + sync admin

**Done** :
- DB : table `iteration_live_tests` ajoutée à `schema.sql`
  (PK `(iteration_id, test_idx)`, FK ON DELETE CASCADE vers
  `experiment_iterations`, contrainte CHECK sur `condition`). Dataclass
  `IterationLiveTestRow` exposée via `state` ; CRUD `upsert_live_test`
  (retourne `bool` pour distinguer insert vs dupe), `list_live_tests`,
  `clear_live_tests`.
- Backend `ml/api/lab_routes.py` :
  - `POST /lab/cohorts/_/iterations/{iid}/live-tests/sync` : lit
    `ml/state/live_test_logs/<iid>.jsonl`, valide ligne par ligne
    (`schema_version=1`, `iteration_id` matche, `condition` ∈
    {bright,dim,tilt}, `test_idx ≥ 1`, etc.), upsert + retourne
    `{inserted, skipped_dupe, parse_errors[], summary}`. Le wildcard `_`
    sur le cohort_id est intentionnel — l'iteration porte son cohort.
  - `GET /lab/cohorts/{cid}/iterations/{iid}/live-tests` : retourne
    `tests[]` + `matrix[eurio_id][condition]` + `summary` avec
    `studio_r_at_1` (depuis le benchmark de l'iteration), `recall_at_1`
    (live), `delta` (live − studio).
  - Helper `_safe_repo_relative` pour les paths user-facing (les tests
    patchent `LIVE_TEST_LOGS_DIR` à un tmpdir hors-repo).
  - `LIVE_TEST_SCHEMA_VERSION = 1`, `LIVE_TEST_CONDITIONS = {bright,
    dim, tilt}` exposés au top du module.
- Backend `ml/api/iteration_runner.py` : nouveau pas
  `_export_tflite(iteration_id)` invoqué dans `_chain_steps` entre la
  fin du training et le démarrage du benchmark. Lance
  `python -m training.export_tflite` via le venv Python du module ML.
  Échec d'export = warning loggué, l'iteration **continue** (le
  training est valide ; l'utilisateur peut re-exporter manuellement
  avant de bundle).
- Tests `ml/tests/test_lab_api.py` : 6 nouveaux tests
  `test_live_tests_*` (sync 404, sync parse + dedup, get matrix, get
  404 cross-cohort, sync rejection sur iteration_id mismatch). Fixture
  `live_test_client` redirige `LIVE_TEST_LOGS_DIR` vers tmpdir.
- Front Vue (admin/packages/web) :
  - Types `LiveTestEntry`, `LiveTestsReport`, `LiveTestsSyncResult`,
    `LiveTestCondition`, `LiveTestsSummary`, `LiveTestTopMatch` dans
    `lab/types.ts`.
  - API helpers `fetchLiveTests`, `syncLiveTests` dans `useLabApi.ts`.
  - Hooks `useLiveTestsQuery` (staleTime 5min, sync invalide) et
    `useSyncLiveTestsMutation` dans `useLabQueries.ts` (+
    `LAB_KEYS.liveTests`).
  - Composant `LiveTestsSection.vue` : bouton « Sync depuis device »,
    bandeau commande copy-paste `cohort-test:pull-tests
    ITERATION=<iid>`, bandeau métriques (Studio R@1 · Live R@1 · Delta
    coloré : vert <5pp / orange <15pp / rouge sinon), tableau matrix
    coin × condition avec cellules ✓/✗ + similarité top-1 + tooltip
    détaillé.
  - Mounted en §5 (suite) dans `IterationDetailPage.vue` après
    `BuildTestAppSection`.
- Taskfile `app-android/Taskfile.yml` : nouvelle tâche
  `cohort-test:pull-tests` (`adb pull` du JSONL puis `curl POST` sur
  `/lab/cohorts/_/iterations/<iid>/live-tests/sync`). Précondition
  `ITERATION` requis. Path device :
  `/sdcard/Android/data/com.musubi.eurio.cohorttest/files/Documents/eurio_live_tests/<iid>.jsonl`.
- Android — Sprint 4 partie host (cohortTest flavor) :
  - `app-android/src/main/.../ml/CoinAnalyzerFactory.kt` (nouveau,
    main source set) : factory qui construit un `CoinAnalyzer` à
    partir d'`AssetPaths(modelPath, metaPath, embeddingsPath)`. Deux
    presets : `PROD` (paths d'`EurioApp`) et `COHORT_BUNDLE` (paths
    sous `cohort_bundle/`). Detector YOLO/Hough volontairement non
    branché — cohortTest tourne en photo-mode only (D-005). C'est
    l'option (b) du handoff Sprint 3 — `EurioApp` reste intact.
  - `app-android/src/cohortTest/.../LiveTestState.kt` (nouveau) :
    dataclasses `TestPrescription`, `TestResult`, `TopMatch`.
  - `app-android/src/cohortTest/.../LiveTestLogger.kt` (nouveau) :
    JSONL writer/reader. Écrit
    `<getExternalFilesDir(Documents)>/eurio_live_tests/<iid>.jsonl`
    (= path device pulled par `cohort-test:pull-tests`). `readAll()`
    pré-popule la state in-memory au relaunch ; `append(result)`
    n'écrit qu'une seule fois par `(iid, test_idx)`.
  - `app-android/src/cohortTest/.../LiveTestsScreen.kt` (nouveau) :
    Compose UI complet — top bar « Test N/M : eurio_id · condition »,
    progress bar, CameraX preview avec guide circulaire, bouton Snap,
    panel Top-3 (✓ correct / ✗ incorrect / Erreur), bouton « Test
    suivant → » qui auto-jump au prochain test sans résultat, chevrons
    ‹ › pour naviguer. End-of-run card affiche la commande pull.
  - `app-android/src/cohortTest/.../CohortTestActivity.kt` (refactoré)
    : remplace le placeholder Sprint 3. Charge le bundle, init
    OpenCV (idempotent), build l'analyzer via la factory avec un
    `LiveTestRelay` (ScanCallbackRelay-like), monte `LiveTestsScreen`.
    `EurioApp.onCreate()` continue de tourner pour cohortTest mais
    l'activity n'utilise rien de Room/Supabase.

**Working** (smoke tests via FastAPI TestClient + Gradle assemble) :
- `pytest tests/test_lab.py tests/test_lab_api.py
  --deselect ::test_create_cohort_rejects_empty_ids` :
  **32 passed, 1 deselected** (6 nouveaux tests Sprint 4 inclus).
  ```
  collected 33 items / 1 deselected / 32 selected
  tests/test_lab.py .........                                              [ 28%]
  tests/test_lab_api.py .......................                            [100%]
  ======================= 32 passed, 1 deselected in 0.65s =======================
  ```
- Smoke endpoint via `TestClient` :
  - 404 sur log absent : message contient `JSONL absent` + commande pull.
  - 404 sur iteration inconnue.
  - Parse 6 lignes, 3 valides + 1 vide + 1 JSON invalide + 1 wrong
    schema → `inserted=3 skipped_dupe=0 errors=2`,
    `parse_errors=['line 5: invalid JSON ...', 'line 6: schema_version=99 != 1']`.
  - `GET .../live-tests` retourne `summary={total=3, correct=1,
    studio_r_at_1=0.92, recall_at_1=0.333, delta=-0.587}`,
    `matrix={'fr-2007': {'bright': ..., 'dim': ...}, 'de-2005': {...}}`.
  - 2e POST sync = `inserted=0 skipped_dupe=3` (idempotence).
  - 404 sur cross-cohort : `GET /lab/cohorts/wrong/iterations/iter1/...`.
  - Mismatch `iteration_id` dans la JSONL → ligne rejetée avec
    `parse_errors` mais le reste passe.
- `pnpm typecheck` — pas de nouvelle erreur dans `features/lab/`. Les
  pré-existantes (`audit/AuditPage`, `sets/SetEditDrawer`,
  `sets/SetsListPage`, `lab/PerConditionTable.vue`) restent telles
  quelles (hors scope).
- `pnpm exec vite build` : clean (2.78s). Le chunk
  `IterationDetailPage` passe de 26.x kB à 31.28 kB (gzip 8.18 kB) à
  cause du nouveau composant ; `useLabQueries` 13.6 → 16.05 kB.
- `./gradlew :app-android:assembleCohortTestDebug` : **BUILD
  SUCCESSFUL** (7s). APK produit
  `build/outputs/apk/cohortTest/debug/app-android-cohortTest-debug.apk`.
- `./gradlew :app-android:assembleFullDebug` : **BUILD SUCCESSFUL**
  (2s). Pas de régression sur la prod.

**Broken / partial** :
- **Pas de test sur device physique** — pas de hardware connecté
  pendant cette session. La factory + le wiring CameraX ont été
  validés au build mais le snap → ArcFace → JSONL n'a pas été testé
  end-to-end. Le user devra valider sur device en :
  1. Bundle + install : `go-task -t app-android/Taskfile.yml
     cohort-test:install COHORT=green-v1 ITERATION=<iid>`
  2. Lancer "Eurio Test", autoriser caméra, faire les 9 snaps
  3. Pull + sync : `go-task -t app-android/Taskfile.yml
     cohort-test:pull-tests ITERATION=<iid>`
  4. Vérifier §5 dans /lab.
- L'auto-export TFLite est silencieux côté front. Si l'export échoue
  (par ex. environnement litert_torch cassé), le bundle script se
  plaindra ensuite avec exit 4 (logique mtime de Sprint 3) ; la
  réparation = lancer `python -m training.export_tflite` à la main.
  Pas de UI signal pour l'instant — Sprint 5 territoire si on veut
  surfacer l'erreur dans `BuildTestAppSection`.
- L'app cohortTest n'a pas de "session reset" UI. Si l'utilisateur
  veut reprendre une session fraîche pour la même iteration, il doit
  manuellement supprimer `<sdcard>/.../eurio_live_tests/<iid>.jsonl`
  avant relance (ou simplement écraser via une nouvelle iteration).
  Documenté dans le code mais pas exposé dans l'UI.
- Pas de validation côté front que `parse_errors[]` est vide après un
  sync — actuellement on alert() si > 0, ce qui est acceptable mais
  pas joli. À polir Sprint 5.

**Deviations from sprint doc** :
- Sprint task A.4 demandait l'écriture JSONL « pendant le snap ». J'ai
  séparé en deux phases : le snap émet un `TestResult` via le relay,
  le composable LiveTestsScreen le persiste via `LiveTestLogger.append`
  *si* c'est la première écriture pour ce test_idx (ou si l'écriture
  précédente était un erreur et celle-ci est OK — voir OQ-4). Empêche
  les doubles writes silencieuses.
- Sprint task B.10 demandait que le relaunch « pré-populate
  results[] à partir du test_idx ». Implémenté via
  `LiveTestLogger.readAll()` au mount de `RunFlow`. Si la dernière
  ligne pour un `test_idx` est invalide, on traite comme « pas
  encore snapped » (l'utilisateur peut refaire).
- Sprint task C.11 (Taskfile bloc YAML) avait `vars: {ITERATION:
  '{{.ITERATION}}'}` puis `{{.APP_ID}}.cohorttest` en path device.
  J'ai utilisé la même variable `APP_ID` que les autres tâches du
  fichier (`com.musubi.eurio`) avec suffix `.cohorttest` direct. Pas
  de divergence sémantique, juste la convention Taskfile existante.
- Sprint task A.7 « Sync : commande à exécuter sur l'ordi ». Le
  composant Vue affiche la commande exacte ; l'app Android affiche un
  end-of-run card avec la même commande pour rappel. C'est redondant
  (un côté suffirait) mais utile : l'utilisateur termine la session
  sur device et voit immédiatement quoi taper sans devoir rouvrir
  l'admin.
- Sprint doc Files à toucher liste `FreescanScreen.kt (optionnel)`
  pour le mode hors-prescription. Non implémenté — la spec dit
  optionnel, et il n'apporte rien à la boucle de validation pour la
  v1. Sprint 5 territoire.

**Decisions taken** :
- **OQ-1 (snap → inférence rate, comment on log)** : on écrit
  `predicted_top3=[]`, `predicted_top1=null`, `similarity_top1=null`,
  `is_correct=false`, et un champ `error: "<reason>"` non-null. Le
  champ `error` est déclaré nullable dans le schema SQL et le type
  `IterationLiveTestRow`. Côté Vue, la cellule matrix affiche
  `✗ err` en rouge. Coté backend, `is_correct` reste comptabilisé
  dans `correct/total` comme un échec (donc baisse le `recall_at_1`
  live) — c'est volontaire : si l'inférence rate sur device, c'est un
  vrai miss du point de vue produit.
- **OQ-2 (condition vérifiée par l'app)** : non, conformément à la
  reco. C'est purement déclaratif et c'est l'utilisateur qui se met
  dans `bright`/`dim`/`tilt`. Pas de capteur (luminance,
  gyroscope) — hors-scope explicite. Si on veut auto-tagger plus
  tard, le format JSONL accepte des champs additionnels (forward-
  compat via `schema_version`).
- **OQ-3 (sampling 3/9 quand cohort ≥ 30 pièces)** : pas changé vs
  Sprint 3. Le bundle script garde `SAMPLED_COIN_COUNT=3` avec un
  sort alphabétique (déterministe). Pas de stratification par zone
  pour cette session — les zones (`green/orange/red` du sprint 2) ne
  sont pas attachées par-pièce dans la DB, juste par-cohort. Sprint 5
  territoire si on veut zone-stratifier.
- **OQ-4 (re-snap d'un test individuel)** : oui mais *uniquement*
  quand le résultat précédent était une erreur d'inférence (champ
  `error` non-null). Le bouton « Refaire » apparaît dans ce cas et
  pas autrement. Évite le biais de confirmation (« j'aime pas le
  résultat, je refais ») tout en donnant une porte de sortie pour
  les vrais bugs (caméra qui rate, normalize qui foire). Côté
  backend, l'upsert basé sur `(iteration_id, test_idx)` PK absorbe
  les retries (le 1er insert gagne ; les suivants sont
  `skipped_dupe`). Côté Android, on appelle bien `logger.append` à
  chaque nouveau résultat, donc le JSONL contient potentiellement 2
  lignes pour le même `test_idx` — c'est OK, le parser server-side
  garde la 1ère via la PK.
- **Auto-export TFLite hooké post-training** : oui, dans
  `IterationRunner._chain_steps` entre `_wait_training` (succès) et
  `_launch_benchmark`. Échec d'export = log warning, iteration
  continue (le training est valide). Justif : le user voit toujours
  son verdict + R@1 même si l'export rate ; et le bundle script de
  Sprint 3 a déjà la logique mtime + message d'erreur clair pour le
  rattrapage manuel. Plus prudent que de fail l'iteration entière.
- **Wiring Sprint 3 handoff (a) vs (b)** : option (b) retenue
  (CoinAnalyzerFactory), conformément à la reco du handoff. EurioApp
  reste un singleton qui sert le flavor full ; le flavor cohortTest
  ne touche pas EurioApp et utilise la factory directement dans
  l'Activity. Coût : init Room/catalog/etc. inutile au boot
  cohortTest. Pas mesuré, pas observé comme problème ; à mesurer si
  cold-start devient gênant pendant les sessions test.

**Handoff** :
- Sprint 5 (Polish) peut démarrer.
- **Pré-requis Sprint 5 / device validation** :
  1. Lancer une iteration trainée jusqu'au bout sur la cohort
     `green-v1` (ou n'importe laquelle).
  2. `go-task -t app-android/Taskfile.yml cohort-test:install
     COHORT=green-v1 ITERATION=<iid>`. Vérifier qu'« Eurio Test »
     démarre sur l'écran « Test 1/N : ... · bright ».
  3. Faire 9 snaps. Vérifier que :
     - le top-3 s'affiche immédiatement après chaque snap
     - le badge ✓/✗ correspond à top-1 vs expected
     - « Test suivant → » saute au prochain test sans résultat
     - kill app + relance : reprend au test où on en était
  4. `adb shell cat /sdcard/Android/data/com.musubi.eurio.cohorttest/files/Documents/eurio_live_tests/<iid>.jsonl`
     → vérifier que les lignes sont bien formées.
  5. `go-task -t app-android/Taskfile.yml cohort-test:pull-tests
     ITERATION=<iid>` → vérifier la réponse curl `inserted=N
     skipped_dupe=0`.
  6. Ouvrir `/lab/cohorts/<cohort>/iterations/<iid>` → §5 doit
     afficher la matrix + delta.
- **Métriques live attendues sur green-v1** : pas mesurées ici
  (offline). Quand le user fera la première vraie passe, copier la
  ligne « delta studio vs live observé sur la première vraie
  iteration trainée » dans cette section pour démarrer la base de
  données empirique demandée par le sprint doc § Handoff.
- **Pièges potentiels device** :
  - SnapNormalizer requires `OpenCVLoader.initLocal()`. EurioApp.onCreate
    l'appelle, et CohortTestActivity le re-call defensively
    (idempotent). Si OpenCV rate, le snap échouera silencieusement
    avec « NORMALIZE FAILED » dans le top-3 → l'app loggue ça en
    `error: "NORMALIZE FAILED: ..."`.
  - Permission caméra : Android 14+ peut afficher la dialog au
    premier launch. Le composable la demande explicitement via
    `rememberLauncherForActivityResult` ; si refusée, on affiche un
    écran « Autorisation caméra requise » avec un bouton retry.
  - Le composant Vue n'est pas auto-polled. Le user doit cliquer
    « Sync » manuellement après avoir lancé `pull-tests`. Sprint 5
    pourrait poller toutes les 5s ou bien ajouter un long-polling
    sur le mtime du fichier `live_test_logs/<iid>.jsonl`. Pas
    prioritaire.
  - L'auto-export TFLite tourne dans le subprocess Python du venv
    `ml/.venv/bin/python`. Si ce venv est cassé (par ex. après un
    `pip install` qui a sauté `litert_torch`), le runner loggue
    warning mais le user verra `tflite_present=false` dans
    `BuildTestAppSection` au moment de bundle.
- **Code mort** : aucun supprimé. Le placeholder Sprint 3 dans
  `CohortTestActivity` a été remplacé par la version full Sprint 4 ;
  rien d'autre touché.
- **Fichiers ajoutés** :
  - `app-android/src/main/java/com/musubi/eurio/ml/CoinAnalyzerFactory.kt`
  - `app-android/src/cohortTest/java/com/musubi/eurio/cohorttest/LiveTestState.kt`
  - `app-android/src/cohortTest/java/com/musubi/eurio/cohorttest/LiveTestLogger.kt`
  - `app-android/src/cohortTest/java/com/musubi/eurio/cohorttest/LiveTestsScreen.kt`
  - `admin/packages/web/src/features/lab/components/LiveTestsSection.vue`
- **Fichiers modifiés** :
  - `ml/state/schema.sql`, `ml/state/store.py`, `ml/state/__init__.py`
  - `ml/api/lab_routes.py`, `ml/api/iteration_runner.py`
  - `ml/tests/test_lab_api.py` (+6 tests)
  - `app-android/Taskfile.yml` (+ `cohort-test:pull-tests`)
  - `app-android/src/cohortTest/java/com/musubi/eurio/cohorttest/CohortTestActivity.kt`
    (placeholder → full live tests host)
  - `admin/packages/web/src/features/lab/types.ts`
  - `admin/packages/web/src/features/lab/composables/useLabApi.ts`
  - `admin/packages/web/src/features/lab/composables/useLabQueries.ts`
  - `admin/packages/web/src/features/lab/pages/IterationDetailPage.vue`

---

## 2026-04-30 · Sprint 5 · Polish — pipeline complète

**Done** :
- Backend (`ml/api/lab_routes.py`) :
  - `GET /lab/dashboard` : aggrège cross-cohort en 3 vues —
    `top_recipes` (recipe_id × moyenne live R@1, fallback studio),
    `difficult_coins` (live R@1 < 0.5 sur ≥3 iterations distinctes),
    `distance_distribution` (histogramme cosines aug↔réel sur 5 bins
    `[0,0.5][0.5,0.7][0.7,0.85][0.85,0.95][0.95,1]`). Reuse les helpers
    `list_iterations`/`list_live_tests`/`list_aug_vs_real` du store —
    pas de table dédiée, recompute on demand (cheap pour quelques
    cohorts).
  - `DELETE /lab/cohorts/{cid}/iterations/{iid}/augmentations` :
    `shutil.rmtree` `<numista_id>/augmentations/<iid>/` pour chaque
    coin du cohort + le staging root `datasets/iterations/<iid>/`.
    409 sur status `training`/`benchmarking`. Skipped list pour les
    coins sans numista_id.
  - `DELETE /lab/cohorts/{cid}/iterations/{iid}/test-bundle` :
    `shutil.rmtree` `ml/output/cohort_test_<iid>/`. Idempotent
    (`removed=false` si déjà absent).
- Front Vue :
  - Types `DashboardReport`, `DashboardTopRecipe`, `DashboardDifficultCoin`,
    `DashboardDistanceBin`, `PurgeAugmentationsResult`,
    `PurgeTestBundleResult` ajoutés à `lab/types.ts`.
  - `BenchmarkRunDetail` (+ deps `BenchmarkPerCoin`, `BenchmarkTopConfusion`)
    migré depuis `features/benchmark/types.ts` vers `lab/types.ts`.
  - `fetchDashboard`, `fetchBenchmarkRunDetail`, `purgeIterationAugmentations`,
    `purgeIterationTestBundle` dans `useLabApi.ts`.
  - `useDashboardQuery` (staleTime 30s), `usePurgeAugmentationsMutation`,
    `usePurgeTestBundleMutation` dans `useLabQueries.ts` ; clé
    `LAB_KEYS.dashboard`.
  - Nouveau composant `DashboardSection.vue` : 3 cards (top recipes,
    difficult coins, histogram cosines barres horizontales) — états
    loading/error/empty/data. Mounted en haut de `LabHomePage.vue`
    avant la liste cohorts.
  - `AugmentationsGallery.vue` : bouton « Purger » (Trash2 icon)
    visible quand l'iteration n'est ni training ni benchmarking et
    que `total_samples > 0`. Confirmation dialog. Invalide la query
    augmentations + dashboard.
  - `BuildTestAppSection.vue` : bouton « Purger bundle » visible
    quand `model_ready=true`. Confirmation + message inline.
  - `CohortDetailPage.vue` : banner warning au-dessus de §3 quand
    `iterations.length ≥ 5 && failed.count ≥ 2`, avec pointer vers
    le bouton purge sur l'iteration concernée.
- Suppression `/benchmark` (Sprint 5 task C) :
  - `IterationDetailPage.vue` : import déplacé vers
    `fetchBenchmarkRunDetail` + `BenchmarkRunDetail` depuis
    `@/features/lab/...`.
  - 3 routes retirées de `app/router.ts` (`benchmark`,
    `benchmark/runs/:id`, `benchmark/compare`).
  - `admin/packages/web/src/features/benchmark/` **supprimé entièrement**
    (3 pages + types.ts + composables/useBenchmarkApi.ts). Pas de
    backwards-compat — la route `/benchmark` du nav avait déjà été
    retirée au sprint 2 et la page laissait juste un banner.
  - `docs/augmentation-benchmark/README.md` : reste annoté legacy,
    pointer vers `docs/training-pipeline/`.
- Doc utilisateur : `docs/training-pipeline/USER_GUIDE.md` (nouveau,
  ~280 lignes) — tutorial step-by-step en 10 étapes (créer cohort →
  capturer photos → recipe → iteration → inspection studio → APK
  cohortTest → live tests → sync → itérer → GC), table de
  troubleshooting, check-list "iteration validée" (R@1 studio ≥ 0.85
  / R@1 live ≥ 0.70 / cosine ∈ [0.70, 0.95]).

**Working** (smoke tests) :
- `pytest tests/test_lab.py tests/test_lab_api.py` : 32 passed
  (1 deselected pré-Sprint 1, comme attendu).
- TestClient sur les 3 nouveaux endpoints :
  - `GET /lab/dashboard` (état actuel : 0 iteration completed) → 200
    `{top_recipes:[], difficult_coins:[], distance_distribution:{total:0,
    bins:[…]}, totals:{n_cohorts:2, n_iterations:2, n_completed:0}}`.
    L'aggrégat est cohérent (rien à agréger encore).
  - `DELETE .../augmentations` sur iteration failed → 200
    `{removed_dirs:[], staging_root_removed:false, skipped:[]}`
    (pas d'augmentations sur disque pour cette iteration, no-op clean).
  - `DELETE .../test-bundle` → 200 `{bundle_path:..., removed:false}`.
  - `DELETE .../augmentations` cohort introuvable → 404 attendu.
- `pnpm typecheck` : aucune nouvelle erreur dans `lab/`. Pré-existantes
  dans `audit/`, `sets/`, `PerConditionTable.vue` inchangées (hors scope).
- `pnpm exec vite build` : clean en 3.28s, le chunk `LabHomePage` a
  pris ~1.5 KB (DashboardSection inline), le chunk `useLabQueries`
  ~600 B de plus. Bundle benchmark/* gone.
- `./gradlew :app-android:assembleCohortTestDebug :app-android:assembleFullDebug`
  : BUILD SUCCESSFUL (UP-TO-DATE car aucun changement Android au sprint).

**Broken / partial** :
- **Pas de mesure réelle de R@1 live encore** — la pipeline est complète
  end-to-end mais aucune iteration n'a été menée jusqu'à la sync live
  tests sur cette session. Les chiffres demandés par le sprint doc §
  Handoff (« chiffres mesurés sur la première cohort réelle ») resteront
  à remplir lors de la première vraie passe device.
- Le dashboard ne fait pas de cache server-side. Pour quelques cohorts
  c'est négligeable (<50ms observé). Si on dépasse 20+ iterations
  completed avec live tests, recompute deviendra perceptible — à ce
  moment-là, ajouter un cache TTL 60s côté backend ou une vue matérialisée.
- L'auto-cleanup hard (purge silencieuse après N jours) n'est PAS
  implémenté (cf. OQ-1 décision : non). Banner suffit pour l'instant.
- La métrique de **stagnation** (cohort qui ne progresse plus sur 5
  iterations consécutives, suggestion "essaie une nouvelle cohort")
  est volontairement laissée pour plus tard (cf. OQ-3 : pas trivial à
  coder, valeur incertaine tant qu'on n'a pas vu plusieurs cohorts en
  production).

**Deviations from sprint doc** :
- Sprint task 2-3 demandait une page dédiée `/lab/dashboard`. Choix :
  intégrer `DashboardSection` directement en haut de `/lab` (LabHome).
  Raison : le dashboard cross-cohort sert exactement le même persona
  que la home — on ne navigue pas vers une page séparée pour ces
  agrégats, on les voit en arrivant. Pas de route ajoutée, pas de
  duplication d'header. Si l'agrégat grossit (Sprint 6+), on pourra
  le sortir en page dédiée.
- Sprint task 7 (auto-cleanup soft : "5 iterations + ≥2 failed →
  banner "Purger les failed ?"") implémenté côté front uniquement, pas
  d'endpoint dédié batch. Banner suggère d'aller cliquer "Purger" sur
  chaque iteration manuellement. Raison : un endpoint
  `purge_failed_in_cohort` introduirait une opération non-atomique
  (loop sur les iterations) avec une sémantique floue si l'une est en
  cours, et on revient au problème de fraîcheur Sprint 5 a cherché à
  éviter. Manuel = explicite.
- Sprint task 4 spec disait "409 si l'iteration est `running`". Sémantique
  ajustée : 409 si status ∈ {`training`, `benchmarking`}, qui est la
  vraie condition runtime. `pending` est purgeable (preview iterations
  qui s'accumulent au sprint 1 — OK les wiper).

**Decisions taken** :
- **OQ-1 (auto-cleanup hard)** : non, comme suggéré par le spec.
  L'utilisateur garde la main. Le banner suffit pour l'observabilité.
  Future evolution possible : marquer les iterations `failed` plus
  vieilles que 30j en `archived` avec un job nightly — mais c'est de
  l'over-engineering tant qu'on est mono-utilisateur.
- **OQ-2 (metric "difficult coin")** : `live R@1 < 0.5` sur `≥3
  iterations distinctes` — exactement ce que le spec proposait. Les
  deux constantes sont en haut de `lab_routes.py`
  (`_DIFFICULT_R1_THRESHOLD = 0.5`, `_DIFFICULT_MIN_ITERATIONS = 3`)
  pour tweak rapide. Exposées dans la payload du dashboard
  (`distance_distribution.threshold_difficult_r_at_1` /
  `min_iterations_for_difficult`) pour que le front puisse les afficher.
- **OQ-3 (stagnation)** : reporté. Trop incertain de la définition
  utile (5 iterations sans amélioration > 2pp mesurée comment ? Le R@1
  live qui est bruité ? Le studio ? Le delta par axe ?). On y reviendra
  quand on aura observé empiriquement plusieurs cohorts.
- **Migration `BenchmarkRunDetail` plutôt que suppression** : le
  composable lab consomme encore le payload détaillé du benchmark
  (per_condition table). Plutôt que rewriter ce que `IterationDetailPage`
  affiche, on a déplacé `fetchBenchmarkRunDetail` + types dans
  `features/lab/` (les seuls consommateurs restants après le ménage).
  Le backend `/benchmark/*` lui reste actif — il est consommé par cette
  fonction. Si Sprint 6+ veut un cleanup complet, ce sera le moment de
  fusionner les payloads benchmark dans la table `experiment_iterations`.
- **Dashboard inline plutôt qu'en route séparée** : cf. Deviations.

**Handoff — pipeline complète** :
- Le repo est à un point stable. Bon moment pour un tag git
  (`git tag training-pipeline-v1`).
- **Ce qui marche end-to-end** (validé par smoke tests cette session) :
  cohort → recipe preview → iteration training+benchmark → auto export
  TFLite → bundle → install cohortTest APK → live tests JSONL → sync
  admin → dashboard cross-cohort. Tous les endpoints ont été appelés
  avec succès, tous les builds passent.
- **Ce qui reste à valider sur device** (depuis Sprint 4 handoff,
  toujours valable) : les 6 étapes du device walkthrough — installer,
  lancer 9 snaps, kill+relance, inspecter JSONL, pull-tests, vérifier
  §6 admin. Voir `progress.md` Sprint 4 § Handoff pour la check-list
  détaillée.
- **Métriques empiriques à recueillir au premier vrai run** (compléter
  cette section quand l'utilisateur aura tourné une iteration réelle) :
  - R@1 studio observé : à mesurer
  - R@1 live observé : à mesurer
  - Delta studio↔live : à mesurer
  - Cosine aug↔réel moyen : à mesurer
  - Recipes qui marchent / cassent : à observer
- **Prochaine étape produit** : déploiement modèle prod (export
  TFLite vers `app-android/src/main/assets/models/`, après validation
  de la check-list `USER_GUIDE.md` § "iteration validée"). Ou ouverture
  d'un nouveau cohort orange / rouge pour scaler l'évaluation.
- **Code mort retiré** : `admin/packages/web/src/features/benchmark/`
  intégralement (3 pages + 2 fichiers ts). 3 routes retirées de
  `app/router.ts`. Le backend FastAPI conserve `/benchmark/*` car
  encore consommé par lab via `fetchBenchmarkRunDetail`. Si Sprint 6+
  fusionne les benchmarks dans `experiment_iterations`, ce sera le
  moment de retirer la moitié backend aussi.
- **Fichiers ajoutés** :
  - `admin/packages/web/src/features/lab/components/DashboardSection.vue`
  - `docs/training-pipeline/USER_GUIDE.md`
- **Fichiers modifiés** :
  - `ml/api/lab_routes.py` (+3 endpoints)
  - `admin/packages/web/src/features/lab/types.ts`
  - `admin/packages/web/src/features/lab/composables/useLabApi.ts`
  - `admin/packages/web/src/features/lab/composables/useLabQueries.ts`
  - `admin/packages/web/src/features/lab/components/AugmentationsGallery.vue`
  - `admin/packages/web/src/features/lab/components/BuildTestAppSection.vue`
  - `admin/packages/web/src/features/lab/pages/CohortDetailPage.vue`
  - `admin/packages/web/src/features/lab/pages/IterationDetailPage.vue`
  - `admin/packages/web/src/features/lab/pages/LabHomePage.vue`
  - `admin/packages/web/src/app/router.ts`
- **Fichiers supprimés** :
  - `admin/packages/web/src/features/benchmark/` (entier — 5 fichiers)

---
