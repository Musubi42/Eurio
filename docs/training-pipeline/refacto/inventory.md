# Inventory — état actuel de la codebase concernée

> Snapshot au 2026-05-01. À lire avant n'importe quelle phase. Liste les
> fichiers à toucher, les fonctions à respecter, et ce qui existe déjà
> côté backend/front pour ne pas réinventer.

## Backend Python (`ml/`)

### Iteration & runner

| Fichier | Rôle | Fonctions clés |
|---|---|---|
| `ml/api/iteration_runner.py` (608 L) | Orchestre une iteration : bake → train → export TFLite → benchmark → verdict | `IterationRunner.create_iteration`, `launch_training`, `_chain_steps`, `_launch_training`, `_export_tflite`, `_launch_benchmark`, `_finalize`, `stop`, `recover_on_boot` |
| `ml/api/training_runner.py` (669 L) | Sous-runner qui exécute la pipeline 6-steps (Suppression → Préparation → Entraînement → Embeddings → Sync → Validation per-class) | `TrainingRunner.start_run`, `_train`, `_run_step`, `active_snapshot`, `load_logs`, `stop_active`, `ActiveState{run_id,epoch,epochs_total,log_lines}` |
| `ml/api/lab_routes.py` (1602 L) | Toutes les routes `/lab/*` (cohorts, iterations, runner status, captures, augmentations, aug-vs-real, test-app, live-tests, dashboard) | Voir grep `@router\.` plus bas |
| `ml/api/iteration_logic.py` | Calcul verdict, delta, input_diff, sensitivity (pur, pas d'IO) | `compute_verdict`, `compute_delta`, `compute_input_diff` |
| `ml/api/distance_logic.py` | DINO aug↔réelles | `compute_aug_vs_real`, `summarize` |

### Training scripts

| Fichier | Rôle | Points sensibles |
|---|---|---|
| `ml/training/iteration_augmentations.py` (289 L) | **Bake obverse-only** sur disque | Déjà strict obverse (lignes 76-87). `OBVERSE_NAMES = ("obverse.jpg", "obverse.png")`. **Source de vérité de la règle**, ne rien casser ici. |
| `ml/training/train_embedder.py` (892 L) | Subprocess de training, mode `arcface` par défaut | `get_device("auto")` ligne 363, log `Mode: arcface | Device: {device}` ligne 647. **`get_train_transforms()` ligne 168 applique encore** Resize+RandomRotation(360)+RandomAffine+RandomPerspective+ColorJitter+GaussianBlur+ToTensor+Normalize+RandomErasing **même quand `--prebaked-augmentations` est passé** (cf `build_train_dataset` ligne 193 qui set `recipe_override={"layers": []}` mais garde le legacy transforms). C'est **le** point à purger en phase 3. |
| `ml/training/coin_dataset.py` (180 L) | Dataset PyTorch zone-aware | OK statu quo |
| `ml/training/export_tflite.py` | Export TFLite après training | OK statu quo, hooké post-training depuis sprint 4 |

### State & store

| Fichier | Rôle |
|---|---|
| `ml/state/store.py` | SQLite ORM-lite : cohorts, iterations, recipes, runs, epochs, steps, benchmark_runs, live_tests, aug_vs_real |
| `ml/state/schema.sql` | Schéma DB — toutes les tables existent déjà, **ne pas modifier** sauf phase 5 si besoin |
| `ml/state/training.db` | DB SQLite live |

### Endpoints `/lab/*` (lab_routes.py)

```
GET    /lab/cohorts                            list cohorts
POST   /lab/cohorts                            create cohort
GET    /lab/cohorts/{id_or_name}               get cohort
PUT    /lab/cohorts/{cohort_id}                update cohort
DELETE /lab/cohorts/{cohort_id}                delete cohort
POST   /lab/cohorts/{cohort_id}/coins          attach coin
DELETE /lab/cohorts/{cohort_id}/coins/{eurio_id}  detach coin
POST   /lab/cohorts/{cohort_id}/clone          clone cohort

GET    /lab/cohorts/{cohort_id}/iterations
POST   /lab/cohorts/{cohort_id}/iterations
POST   /lab/cohorts/{cohort_id}/iterations/{iid}/launch-training
GET    /lab/cohorts/{cohort_id}/iterations/{iid}
PUT    /lab/cohorts/{cohort_id}/iterations/{iid}
DELETE /lab/cohorts/{cohort_id}/iterations/{iid}
POST   /lab/cohorts/{cohort_id}/iterations/{iid}/stop
GET    /lab/cohorts/{cohort_id}/trajectory
GET    /lab/cohorts/{cohort_id}/sensitivity

GET    /lab/cohorts/{cohort_id}/captures/status
POST   /lab/cohorts/{cohort_id}/captures/csv
POST   /lab/cohorts/{cohort_id}/captures/sync

POST   /lab/cohorts/{cohort_id}/preview-iteration
GET    /lab/cohorts/{cohort_id}/iterations/{iid}/augmentations
POST   /lab/cohorts/{cohort_id}/iterations/{iid}/augmentations/regenerate
DELETE /lab/cohorts/{cohort_id}/iterations/{iid}/augmentations
GET    /lab/cohorts/{cohort_id}/iterations/{iid}/aug-vs-real
POST   /lab/cohorts/{cohort_id}/iterations/{iid}/aug-vs-real/recompute

GET    /lab/runner/status                      {busy: bool}  ← très pauvre
GET    /lab/cohorts/{cohort_id}/iterations/{iid}/test-app/build-info
DELETE /lab/cohorts/{cohort_id}/iterations/{iid}/test-bundle

POST   /lab/cohorts/_/iterations/{iid}/live-tests/sync
GET    /lab/cohorts/{cohort_id}/iterations/{iid}/live-tests

GET    /lab/dashboard
```

### À ajouter dans ce refacto

| Phase | Endpoint | Forme |
|---|---|---|
| 1 | `GET /lab/cohorts/{cohort_id}/progress` | `{c1:{state, missing_obverses[]}, c2:{state, missing_captures[], expected_per_coin}}` |
| 2 | `GET /lab/cohorts/{cohort_id}/iterations/{iid}/progress` | `{i1, i2, i3:{phase, epoch, loss, ...}, i4:{a, b, c, d}}` |
| 4 | `GET /lab/runner/runtime-info` | `{host, arch, torch_version, backend, device, num_cuda_devices, gpu_name?, dataloader_workers, hint}` |
| 5 | `GET /lab/runner/training-progress/{iid}` | `{phase, epoch, epochs_total, loss_current, loss_best, started_at, elapsed_seconds, eta_seconds, log_tail[]}` |

## Frontend Vue (`admin/packages/web/src/features/lab/`)

### Pages

| Fichier | Statut |
|---|---|
| `pages/CohortDetailPage.vue` (392 L) | Refacto en phase 1 (2 tiroirs C1/C2) |
| `pages/IterationDetailPage.vue` (814 L) | Refacto en phase 2 (4 tiroirs I1/I2/I3/I4). Le plus gros chantier. |
| `pages/CohortNewPage.vue` | Inchangé |
| `pages/IterationNewPage.vue` | Inchangé |
| `pages/LabHomePage.vue` | Phase 4 ajoute le bandeau runtime en haut |

### Composants existants à réutiliser

| Composant | Rôle | Réutilisé en |
|---|---|---|
| `components/CaptureSection.vue` | Section captures device (CSV + sync) | tiroir C2 (réembarqué dans un wrapper) |
| `components/AugmentationsGallery.vue` | Galerie samples bakés + purge | tiroir I2 |
| `components/AugVsRealSection.vue` | Galerie + cosine DINO | sous-tiroir I4b |
| `components/BuildTestAppSection.vue` | Commande build APK + état | sous-tiroir I4c |
| `components/LiveTestsSection.vue` | Sync JSONL + matrix | sous-tiroir I4d |
| `components/PerConditionTable.vue` | Per-condition R@1 | sous-tiroir I4a (regroupé avec métriques studio) |
| `components/IterationRow.vue` | Liste iterations dans cohort | inchangé |
| `components/VerdictBadge.vue` | Badge verdict | inchangé |
| `components/InputDiffChip.vue` | Diff vs parent | inchangé |
| `components/CohortAttachModal.vue` | Modal attach coins | inchangé (reste utilisé depuis `/coins`) |
| `features/augmentation/components/RecipeConfigurator.vue` | Configurateur inline (sliders + preview) | tiroir I1 |

### Composants à créer

| Composant | Phase | Rôle |
|---|---|---|
| `components/DrawerSection.vue` | 1 | Wrapper visuel commun (header lisible + body collapse + état empty/partial/ready/done) |
| `components/CohortDrawerC1.vue` | 1 | Tiroir C1 sélection |
| `components/CohortDrawerC2.vue` | 1 | Tiroir C2 captures (wrappe `CaptureSection` existant + state) |
| `components/IterationDrawerI1.vue` | 2 | Tiroir I1 recipe (wrappe `RecipeConfigurator`) |
| `components/IterationDrawerI2.vue` | 2 | Tiroir I2 bake (wrappe `AugmentationsGallery` + bouton générer + progression) |
| `components/IterationDrawerI3.vue` | 2 + 5 | Tiroir I3 training (intègre runtime card + monitor live) |
| `components/IterationDrawerI4.vue` | 2 | Tiroir I4 méta (4 sous-tiroirs) |
| `components/RuntimeBadge.vue` | 4 | Bandeau global sur `/lab` |
| `components/RuntimeCard.vue` | 4 | Carte runtime dans I3 (avant lancement) |
| `components/TrainingMonitor.vue` | 5 | Epoch progress + loss + ETA + log tail |

### Composables

| Fichier | Statut |
|---|---|
| `composables/useLabApi.ts` | Ajouter `fetchCohortProgress`, `fetchIterationProgress`, `fetchRuntimeInfo`, `fetchTrainingProgress`, `bakeAugmentationsForIteration` (renommage potentiel — voir phase 2) |
| `composables/useLabQueries.ts` | Ajouter `useCohortProgressQuery`, `useIterationProgressQuery`, `useRuntimeInfoQuery`, `useTrainingProgressQuery` (refetchInterval 2s tant que training/benchmarking) |
| `features/augmentation/composables/useRecipeEditor.ts` | Inchangé |

### Types

| Fichier | À ajouter |
|---|---|
| `features/lab/types.ts` | `CohortProgress`, `IterationProgress`, `RuntimeInfo`, `TrainingProgress`, `DrawerState = 'empty' \| 'partial' \| 'ready' \| 'done' \| 'running'` |

## Points d'attention transverses

### 1. Le contrat obverse-only doit rester intact

`iteration_augmentations.py` ligne 76-87 et le commentaire ligne 14-20
sont la source de vérité produit (cf mémoire
`feedback_training_source_obverse_only`). **Aucune phase ne touche à ce
fichier sauf pour ajouter du logging** (phase 3).

### 2. Le bake écrit déjà sous `<nid>/augmentations/<iid>/`

Pas de réorg disque. Phase 3 ajoute juste une **garantie runtime** :
`train_embedder.py` ne doit appliquer **aucun transform random** quand
`--prebaked-augmentations` est set (uniquement Resize 224 + Normalize
ImageNet).

### 3. Le runner enforce déjà "1 iteration à la fois"

`IterationRunner._global_lock` (threading.Lock). Pas besoin de tordre
ça en phase 4/5, le runtime info est mono-host par définition.

### 4. Le SIGTERM stop fonctionne (partiellement)

Sprint 1 D-009 : check de stop dans la boucle ArcFace uniquement. La
phase 5 expose le bouton Stop dans I3 ; n'élargit pas le périmètre du
stop (les autres modes — classify, embed — ne sont pas utilisés en
prod, statu quo).

### 5. Logs subprocess

`TrainingRunner._train` accumule les lignes stdout dans
`ActiveState.log_lines` (cf ligne 88) mais n'expose **rien**
publiquement à part `load_logs(run_id)` qui sert l'archive post-run.
Phase 5 ajoute un endpoint qui lit le tail in-memory + parse epoch/loss
depuis ces lignes (regex sur le format émis par `train_embedder.py`
ligne 481-483 : `"  Epoch {epoch:>2} — loss: {avg_loss:.4f} ..."`).

### 6. Convention go-task

Toutes les commandes copy-paste affichées dans le front utilisent
`go-task --taskfile <file>` (jamais `task` — cf mémoire
`feedback_gotask_binary`).

## Vérification rapide après un agent

Quand un agent dit avoir fini une phase, on peut vérifier :

| Phase | Vérif |
|---|---|
| 1 | `curl localhost:8042/lab/cohorts/<id>/progress` retourne `{c1, c2}`. CohortDetailPage montre 2 tiroirs avec headers. |
| 2 | `curl .../iterations/<iid>/progress` retourne `{i1, i2, i3, i4}`. IterationDetailPage montre 4 tiroirs. |
| 3 | Lancer un training : le subprocess log `runtime augmentations: disabled`. Inspecter visuellement un sample bakké et un batch sortant du DataLoader → différence = Resize+Normalize uniquement. |
| 4 | `curl /lab/runner/runtime-info` retourne le bon backend. Bandeau visible dans `/lab`. |
| 5 | Pendant un training, `curl .../training-progress/<iid>` retourne `epoch>0` et un `log_tail` non vide. Le composant Vue stream sans rafraîchir la page. |
