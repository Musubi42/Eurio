# Sprint 3 — Cohort test app : Gradle flavor + build commands

> Durée estimée : 3-4 jours
> Pré-requis : Sprint 1 (modèle exporté + augmentations stables). Sprint 2
> n'est pas bloquant mais aide à diagnostiquer.
>
> **Cold start** : lis `vision.md` (acte 4 dédié à cette app), `decisions.md`
> (D-007, D-010, D-011), `glossary.md` pour la distinction "App full" vs
> "App cohortTest", et `progress.md` du sprint 1 pour savoir où vit le
> modèle exporté.

## Goal

Permettre à l'utilisateur de **builder une APK dédiée** par cohort+iteration
contenant :
- le modèle entraîné (TFLite)
- le catalog filtré aux coins de la cohort
- la prescription des live tests à faire
- une UI scan minimale (toggle continu/one-shot, top-3 par eurio_id, pas
  d'animation 3D, pas de vault/profile)

Le tout via une commande copy-pasted depuis l'admin :
```
go-task -t app-android/Taskfile.yml cohort-test:install \
  COHORT=<name> ITERATION=<iid>
```

## Scope

### Inclus

- Gradle product flavor `cohortTest`
- Source set `app-android/src/cohortTest/` avec `MainActivity` minimaliste
- Bundle de build (`ml/output/cohort_test_<iid>/`) :
  - `model.tflite` (export du modèle de l'iteration)
  - `catalog_snapshot.json` filtré
  - `cohort_meta.json`
  - `live_tests_manifest.json`
- Tasks go-task : `cohort-test:bundle`, `cohort-test:install`
- Endpoint admin `GET /lab/cohorts/{cid}/iterations/{iid}/test-app/build-info`
  qui retourne la commande exacte
- Section §5 dans iteration detail affichant la commande

### Exclus

- Live test flow on-device (sprint 4)
- Sync logs back to admin (sprint 4)
- iOS variant (jamais)

## Tasks

### A. Gradle product flavor (~1 jour)

1. **`app-android/build.gradle.kts`** : ajouter `flavorDimensions += "scope"`
   et 2 flavors :
   ```kotlin
   productFlavors {
       create("full") {
           dimension = "scope"
           applicationIdSuffix = ""
       }
       create("cohortTest") {
           dimension = "scope"
           applicationIdSuffix = ".cohorttest"
           versionNameSuffix = "-cohorttest"
       }
   }
   ```
2. **Source set** `app-android/src/cohortTest/`:
   - `AndroidManifest.xml` minimal — déclare seulement la `MainActivity`
     du flavor (pointe vers une nouvelle classe), pas de deep link, pas
     de service.
   - `kotlin/com/musubi/eurio/cohorttest/MainActivity.kt` — host pour
     `ScanScreen` uniquement.
   - `assets/` (vide au build, populé par la task bundle).
3. **Vérifier** : `./gradlew :app-android:assembleCohortTestDebug` produit
   un APK installable cohabitant avec `full`.
4. Si possible **partage** des modules de scan (CameraX, OpenCV, scan
   normalize, embedding matcher) entre les deux flavors. La majorité du
   code Kotlin reste dans `src/main/`.

### B. Bundle generation pipeline (~1 jour)

5. **Script Python** `ml/scripts/build_cohort_bundle.py` :
   - Args : `--cohort <name>`, `--iteration <iid>`, `--out <path>`
   - Lit la DB pour vérifier que l'iteration existe et est `completed`
   - Copie le `model.tflite` exporté (depuis `ml/output/...` ou
     `ml/checkpoints/...`)
   - Génère `catalog_snapshot.json` filtré aux `cohort.eurio_ids` à partir
     de `eurio_referential.json`
   - Génère `cohort_meta.json` :
     ```json
     {
       "cohort_id": "...", "cohort_name": "green-v1",
       "iteration_id": "8a92f1b3", "iteration_name": "baseline-1",
       "model_version": "v1-arcface", "trained_at": "2026-..."
     }
     ```
   - Génère `live_tests_manifest.json` :
     ```json
     {
       "version": 1,
       "tests": [
         {"idx": 1, "expected_eurio_id": "fr-2007-2eur-standard", "condition": "bright"},
         {"idx": 2, "expected_eurio_id": "fr-2007-2eur-standard", "condition": "dim"},
         ...
       ]
     }
     ```
     `len(tests) == cohort.eurio_ids × 3 conditions` (bright, dim, tilt).
6. **Endpoint admin** `GET /lab/cohorts/{cid}/iterations/{iid}/test-app/build-info`
   - retourne `{
       cohort_name, iteration_id, model_ready: bool,
       command: "go-task -t app-android/Taskfile.yml cohort-test:install COHORT=... ITERATION=...",
       bundle_path: "ml/output/cohort_test_<iid>/",
       eta_after_train: "iteration must be completed first" (si pas prêt)
     }`

### C. Tasks go-task (~½ jour)

7. **`app-android/Taskfile.yml`** :
   ```yaml
   cohort-test:bundle:
     desc: "Generate the bundle for a cohort+iteration"
     vars: {COHORT: '{{.COHORT}}', ITERATION: '{{.ITERATION}}'}
     preconditions:
       - {sh: 'test -n "{{.COHORT}}" && test -n "{{.ITERATION}}"', msg: "COHORT and ITERATION required"}
     cmds:
       - python -m scripts.build_cohort_bundle --cohort {{.COHORT}} --iteration {{.ITERATION}} --out {{.ROOT_DIR}}/ml/output/cohort_test_{{.ITERATION}}
       - rm -rf {{.ROOT_DIR}}/app-android/src/cohortTest/assets/cohort_bundle
       - mkdir -p {{.ROOT_DIR}}/app-android/src/cohortTest/assets/cohort_bundle
       - cp {{.ROOT_DIR}}/ml/output/cohort_test_{{.ITERATION}}/* {{.ROOT_DIR}}/app-android/src/cohortTest/assets/cohort_bundle/

   cohort-test:install:
     desc: "Bundle + build + install + force-stop the cohortTest APK"
     deps: [cohort-test:bundle]
     cmds:
       - cd {{.ROOT_DIR}} && ./gradlew :app-android:installCohortTestDebug
       - adb shell am force-stop {{.APP_ID}}.cohorttest
       - echo "Installed. Open the cohortTest app on the device."
   ```
8. **Test manuel** : `go-task -t app-android/Taskfile.yml cohort-test:install COHORT=green-v1 ITERATION=8a92f1b3` doit produire un APK installé sur le device.

### D. UI minimale cohortTest (~1 jour)

9. **`MainActivity.kt`** (cohortTest flavor) :
   - charge le bundle depuis assets au boot (ou lazy)
   - state global : `currentMode: ContinuousOrOneShot`, `currentTestIdx: Int`
10. **`ScanScreen` reusable** : on importe depuis `src/main/` mais on
    override le `ScanResultPanel` pour afficher juste le top-3 par
    `eurio_id` (lookup via le catalog filtré).
11. **Pas de** : animation 3D, bottom nav, vault/profile/onboarding.
    `manifest` du flavor n'autorise que `MainActivity`.
12. **Toggle** "Continu / One-shot" en top bar. One-shot = bouton snap
    explicite (réutilise le mode existant). Continu = inférence vidéo
    (réutilise le pipeline scan prod, juste l'UI résultat est différente).
13. **Affichage résultat** :
    - top-3 trié par similarité descendante
    - chaque ligne : `eurio_id` (mono font), similarité %, badge color
      vert/orange/rouge selon similarité

### E. Front admin section §5 (~½ jour)

14. **Composant** `BuildTestAppSection.vue` :
    - fetch `useBuildInfoQuery(iterationId)` (Vue Query)
    - si `model_ready=false` → "Lance d'abord le training"
    - si `model_ready=true` → afficher la commande dans un `<pre>` avec
      bouton "Copier"
    - lien doc vers `docs/training-pipeline/sprint-3-cohort-test-app.md`
15. **Composable** `useBuildInfoQuery` dans `useLabQueries.ts`.

## Files à toucher

### Android
- `app-android/build.gradle.kts` — flavors
- `app-android/src/cohortTest/` — nouveau source set complet
- `app-android/Taskfile.yml` — tasks bundle/install
- `app-android/src/main/java/.../scan/ScanResultPanel.kt` (ou équivalent) —
  refactor pour permettre l'override d'affichage par flavor

### Backend
- `ml/scripts/build_cohort_bundle.py` — nouveau
- `ml/api/lab_routes.py` — endpoint build-info

### Front
- `admin/packages/web/src/features/lab/composables/useLabQueries.ts`
- `admin/packages/web/src/features/lab/components/BuildTestAppSection.vue`
- `admin/packages/web/src/features/lab/pages/IterationDetailPage.vue`

## Validation

- [ ] `./gradlew :app-android:assembleCohortTestDebug` build OK
- [ ] APK cohortTest installable et lance directement sur ScanScreen
- [ ] Toggle continu/one-shot fonctionne, top-3 affiche eurio_id
- [ ] Le bundle dans assets contient les 4 fichiers attendus
- [ ] La commande affichée dans §5 est correcte (verbatim copy → run)
- [ ] App full toujours fonctionnelle (pas de régression sur le flavor full)

## Open questions

- **OQ-1** : où vit l'export TFLite aujourd'hui ? `ml/output/`,
  `ml/checkpoints/`, ou un endpoint `/export/model-sync` ? Vérifier en
  début de sprint, le bundle script doit savoir où le chercher.
- **OQ-2** : versionning APK — on incrémente `versionCode` à chaque
  bundle ? Si oui, comment (timestamp ? hash ?). Reco : `versionCode =
  unix_ts() / 60` dans le flavor cohortTest, suffisant pour adb install
  d'overrider.
- **OQ-3** : signing — on signe avec quelle keystore ? Reco : la même
  debug que `full`, c'est usage interne uniquement.
- **OQ-4** : si la cohort a beaucoup de pièces (≥30), 90 tests prescrits
  c'est trop. Faut-il cap à 9 tests max sample ? Reco : oui, sample 3
  pièces représentatives × 3 conditions = 9 tests. Sampling stratégique
  (vert/orange/rouge zone) à définir si besoin en sprint 4.

## Handoff

`progress.md` à enrichir avec :
- la commande exacte qui marche end-to-end
- pièges Gradle rencontrés (manifestes, R class, KSP scope, …)
- éventuels conflits de classes entre flavors
- état de l'UI cohortTest (capture d'écran décrite si possible)
