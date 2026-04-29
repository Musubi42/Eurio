# Sprint 4 — Live tests prescriptifs + sync admin

> Durée estimée : 3 jours
> Pré-requis : Sprint 3 complet (l'APK cohortTest existe et tourne).
>
> **Cold start** : lis `vision.md` (acte 1 et 5 — c'est le sprint qui
> mesure pour de vrai), `decisions.md` (D-005, D-008), `glossary.md`
> (live test, conditions), et le sprint 3 progress pour savoir comment
> est structuré le bundle de l'APK.

## Goal

Faire boucler la pipeline : l'utilisateur prend l'APK cohortTest installé
en sprint 3, **fait les 9 tests prescrits**, sync les logs vers admin, voit
la confusion matrix réelle et le delta vs studio benchmark.

C'est le sprint qui transforme la pipeline d'un proxy studio à une mesure
de validation device.

## Scope

### Inclus

- UI on-device de prescription des tests (step-by-step "Test 1/9",
  "Test 2/9", …)
- Logging local JSONL avec `expected_eurio_id`, `condition`, `top_3`,
  `is_correct`, timestamp
- Affichage immédiat du top-3 après snap, commit instantané (pas de
  re-snap pour ce test)
- Endpoint admin `POST /lab/.../live-tests/sync` qui pull le JSONL et
  parse en DB
- Endpoint admin `GET /lab/.../live-tests` qui retourne le récap
- Section §5 dans iteration detail :
  - liste des tests faits (status par test)
  - confusion matrix réelle (ou tableau par pièce × condition)
  - **delta studio R@1 vs live R@1** : la métrique qui dit si le modèle
    tient en condition réelle

### Exclus

- Multi-device (jamais)
- Capture continue avec auto-tagging (sprint 5 si pertinent)
- Re-test d'un test individuel (faut refaire la session entière pour
  l'instant)

## Tasks

### A. UI on-device guidée (~1 jour)

1. **Au démarrage** de l'APK cohortTest, lire
   `assets/cohort_bundle/live_tests_manifest.json` →
   `List<TestPrescription>`.
2. **State Compose** :
   - `tests: List<TestPrescription>`
   - `results: List<TestResult?>` (nullable, par index)
   - `currentIdx: Int`
3. **TopBar** :
   - "Test {currentIdx+1}/{tests.size}"
   - "{expected.eurio_id} · {condition}" (la consigne)
   - chevron back/next pour changer de test (mais pas de re-snap)
4. **ScanScreen** (one-shot mode forcé pendant les live tests) :
   - bouton snap → inference → `TestResult { top_3, predicted_top1,
     similarity_top1, is_correct }` → écrit dans JSONL local + dans la
     state in-memory.
5. **Affichage immédiat** :
   - top-3 (eurio_id, similarité)
   - badge "✓ correct" ou "✗ incorrect" basé sur top-1 vs expected
   - bouton "Test suivant →" (autofocus le prochain test sans résultat)
6. **Indicateur global** : barre de progression "5/9 tests faits".
7. **Fin** : quand tous les tests ont un résultat, écran "Sync :"
   affichant la commande à exécuter sur l'ordi (cf §C).

### B. Format JSONL et écriture (~½ jour)

8. **Path de sortie** :
   `/sdcard/Android/data/com.musubi.eurio.cohorttest/files/Documents/eurio_live_tests/<iteration_id>.jsonl`
9. **Schema d'une ligne** :
   ```json
   {
     "schema_version": 1,
     "test_idx": 1,
     "iteration_id": "8a92f1b3",
     "expected_eurio_id": "fr-2007-2eur-standard",
     "condition": "bright",
     "predicted_top3": [
       {"eurio_id": "fr-2007-2eur-standard", "similarity": 0.94},
       {"eurio_id": "...", "similarity": 0.81},
       {"eurio_id": "...", "similarity": 0.78}
     ],
     "predicted_top1": "fr-2007-2eur-standard",
     "similarity_top1": 0.94,
     "is_correct": true,
     "ts": "2026-04-30T14:23:45.123Z"
   }
   ```
10. **Append mode** : si l'utilisateur kill l'app et reprend, on relit le
    JSONL existant pour pré-populer `results[]` à partir du `test_idx`. La
    session reprend où on en était.

### C. Sync admin (~½ jour)

11. **Task go-task** :
    ```yaml
    cohort-test:pull-tests:
      desc: "Pull live test logs from device"
      vars: {ITERATION: '{{.ITERATION}}'}
      cmds:
        - mkdir -p {{.ROOT_DIR}}/ml/state/live_test_logs
        - adb pull /sdcard/Android/data/{{.APP_ID}}.cohorttest/files/Documents/eurio_live_tests/{{.ITERATION}}.jsonl {{.ROOT_DIR}}/ml/state/live_test_logs/{{.ITERATION}}.jsonl
        - curl -X POST http://127.0.0.1:8042/lab/cohorts/_/iterations/{{.ITERATION}}/live-tests/sync -H "Content-Type: application/json" -d '{}'
    ```
12. **Endpoint** `POST /lab/cohorts/_/iterations/{iid}/live-tests/sync` :
    - lit `ml/state/live_test_logs/<iid>.jsonl`
    - parse, valide (schema_version, iteration_id matche, etc.)
    - upsert dans la table `iteration_live_tests` (cf `filesystem.md`)
    - retourne `{
        inserted: N, skipped_dupe: N,
        summary: {total, correct, recall_at_1: N/total},
      }`
    - le path `_` dans l'URL est un wildcard : on cherche l'iteration par
      `iid` directement, on n'a pas besoin du cohort_id pour le pull
      (info dans le JSONL ou queryable via DB).

### D. Endpoint résultats + section §5 admin (~1 jour)

13. **Endpoint** `GET /lab/cohorts/{cid}/iterations/{iid}/live-tests` :
    - retourne tous les tests sync, regroupés par pièce et par condition
    - inclut `summary: {studio_r_at_1, live_r_at_1, delta}`
    - `studio_r_at_1` vient du benchmark de l'iteration
14. **Composant** `LiveTestsSection.vue` (§5 dans iteration detail) :
    - statut : "0/9 tests sync" → "9/9 tests sync"
    - bouton avec la commande `cohort-test:pull-tests` (copy)
    - quand sync :
      - tableau pièce × condition (3×3 typique)
      - cellule = ✓ ou ✗ + similarité top-1
      - bandeau métriques : `studio R@1 = 0.95 · live R@1 = 0.78 ·
        delta = -17pp`
      - badge couleur sur le delta : vert si |delta| < 5pp, orange < 15pp,
        rouge sinon
15. **Composable** `useLiveTestsQuery(iterationId)` (Vue Query, cache 5min,
    invalidate à chaque sync).

## Files à toucher

### Android (cohortTest flavor)
- `app-android/src/cohortTest/kotlin/.../LiveTestsScreen.kt` — nouveau
- `app-android/src/cohortTest/kotlin/.../LiveTestState.kt`
- `app-android/src/cohortTest/kotlin/.../LiveTestLogger.kt` — JSONL writer
- `app-android/src/cohortTest/kotlin/.../MainActivity.kt` — host des
  écrans
- (optionnel) `app-android/src/cohortTest/kotlin/.../FreescanScreen.kt`
  pour le mode hors-prescription

### Backend
- `ml/state/schema.sql` — table `iteration_live_tests` (déjà décrite dans
  `filesystem.md`)
- `ml/state/store.py` — CRUD
- `ml/api/lab_routes.py` — 2 endpoints

### Tasks
- `app-android/Taskfile.yml` — `cohort-test:pull-tests`

### Front
- `admin/packages/web/src/features/lab/composables/useLabQueries.ts` — 2
  hooks (query + sync mutation)
- `admin/packages/web/src/features/lab/components/LiveTestsSection.vue` —
  nouveau
- intégration dans iteration detail

## Endpoints

```
POST /lab/cohorts/_/iterations/{iid}/live-tests/sync
GET  /lab/cohorts/{cid}/iterations/{iid}/live-tests
```

## Validation

- [ ] L'APK cohortTest démarre sur l'écran "Test 1/9 : … · bright"
- [ ] Snap → inference → top-3 affiché → JSONL écrit (vérifier via adb
      shell `cat`)
- [ ] Kill app + relance → reprend au test où on en était
- [ ] `cohort-test:pull-tests ITERATION=...` → admin a les 9 tests en DB
- [ ] §5 affiche la matrix + delta studio vs live correctement
- [ ] Resync (un même JSONL pulled 2x) ne duplique pas (skipped_dupe>0)

## Open questions

- **OQ-1** : si l'utilisateur snap mais l'inférence rate (modèle pas
  loadé, exception), comment on log ? Reco : on écrit une ligne avec
  `predicted_top3=[]`, `is_correct=false`, et un champ `error: "..."`.
- **OQ-2** : le `condition` du test (bright/dim/tilt) est purement
  déclaratif — l'app n'en vérifie rien. C'est l'utilisateur qui se met
  dans cette condition. OK pour v1, mais à terme peut-être enrichir avec
  capteurs : luminance, gyroscope (pour tilt). Hors-scope ici.
- **OQ-3** : les 3 conditions × ≤3 pièces sample = ≤9 tests par
  iteration. Si la cohort a 17 pièces, on en sample 3 (cf D-008 / OQ-4 du
  sprint 3). **Quel sampling** ? Reco : 1 pièce zone verte + 1 orange + 1
  rouge (besoin du sprint 2 pour la zone). Si pas de zones disponibles,
  3 random.
- **OQ-4** : on permet de **re-snap** un test individuel ? Aujourd'hui
  prescrit "non". Si OQ-1 a un échec d'inférence, faut un fallback. Reco :
  bouton "Refaire le test" disponible **uniquement si dernier résultat
  était une erreur**, jamais si on n'aime pas le résultat.

## Handoff

`progress.md` :
- delta studio vs live observé sur la première vraie iteration trainée
- pièces où le live diverge le plus du studio (à investiguer côté recipe)
- pièges UX rencontrés (mode portrait/paysage, kill app, batterie low…)
