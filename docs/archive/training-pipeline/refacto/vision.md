# Vision — Cohort / Iteration / Run en tiroirs

> Le récit du flow cible, de la sélection de pièces à l'affichage du
> verdict, en passant par les logs streamés du training. Lis ce fichier
> avant les phases si tu veux le "pourquoi" avant le "quoi".

## Principe directeur : le tiroir

Un **tiroir** est une étape avec :

- un **état dérivé** (`empty` / `partial` / `ready` / `done`) calculé
  côté backend à partir du disque + DB, jamais déclaratif côté front
- un **gate** : tant que le tiroir N n'est pas `ready`, le tiroir N+1
  est verrouillé (visible mais non actionnable)
- un **header lisible d'un coup d'œil** ("§I2 · 800 aug bakées · 16/16
  pièces") pour qu'un coup d'œil suffise à savoir où on en est
- un **corps expand/collapse** : éditable quand le tiroir est l'étape
  active, lecture seule sinon

Le tiroir feed le suivant **par contrat de données**, pas par convention :
le backend dit "C2 est `done` quand toutes les pièces de la cohort ont
6 captures sur disque", point. Le front se contente d'afficher.

## Cohort — 2 tiroirs

### Tiroir C1 — Sélection des pièces

État de la cohort : `draft` (statu quo).

**Entrée** : aucune.

**Action de l'utilisateur** : depuis `/coins`, ouvrir la modal "Cohort
lab" et attacher des coins. Depuis le tiroir C1, retirer un coin.

**Validation** :
- au moins 1 coin attaché
- chaque coin doit avoir un `obverse.jpg` ou `obverse.png` présent sur
  disque (`ml/datasets/<nid>/`). Si une pièce n'en a pas, le tiroir
  reste `partial` et liste les pièces manquantes.

**Sortie** : N coins sélectionnés, tous obverse-ready.

**Quand C1 est `done`** : C2 devient actionnable.

### Tiroir C2 — Captures device (pour bench, jamais pour training)

**Entrée** : C1 `done`.

**Action de l'utilisateur** :
1. Click "Générer le CSV" → backend écrit `ml/state/cohort_csvs/<name>.csv`
2. Le tiroir affiche **3 commandes copy-paste** dans l'ordre :
   - `adb push <csv_path> /sdcard/Download/cohort.csv`
   - lancer le mode capture dans l'APK cohortTest
   - `go-task --taskfile app-android/Taskfile.yml pull-debug`
3. Click "Sync" → backend lit `debug_pull/<latest>/` et copie dans
   `ml/datasets/<nid>/captures/`.

**Validation** :
- chaque coin de la cohort a 6/6 captures attendues (`bright_plain`,
  `dim_plain`, `bright_perturbed`, `dim_perturbed`, `tilt_plain`,
  `tilt_perturbed` — cf `CAPTURE_STEPS`).
- tant qu'une pièce a < 6, le tiroir reste `partial` et la liste des
  manquants est visible.

**Sortie** : toutes les pièces ont 6 captures sur disque.

**Quand C2 est `done`** : on peut créer une iteration. Le bouton
"Nouvelle itération" devient actionnable.

**À noter** : ces captures servent uniquement au benchmark studio (I4a),
à la mesure DINO (I4b), et aux live tests (I4d). **Elles ne sont jamais
lues par `iteration_augmentations.py`** — voir phase 3.

## Iteration — 4 tiroirs

L'iteration porte un essai reproductible : recipe figée, bake snapshot
sur disque, training run, évaluations.

### Tiroir I1 — Recipe d'augmentation

**Entrée** : iteration créée (statu quo : `status='pending'`,
`recipe_id=null` autorisé).

**Action de l'utilisateur** :
- choix d'une recipe existante via dropdown, OU édition d'une recipe
  via le configurateur inline (déjà livré post-sprint 5)
- preview live sur **un** obverse choisi parmi les eurio_ids de la
  cohort (3×3 grid)

**Validation** :
- `iteration.recipe_id` non null
- `iteration.variant_count` ≥ 1

**Sortie** : recipe figée sur l'iteration. Si l'utilisateur change la
recipe sur une iteration `pending`, le tiroir I2 (s'il était `done`)
repasse en `empty` parce que le snapshot disque devient stale (le
backend invalide déjà via `update_iteration` quand la recipe change —
cf `lab_routes.py:481`).

### Tiroir I2 — Bake des augmentations

**Entrée** : I1 `done`.

**Action de l'utilisateur** :
- click "Générer les augmentations" → bake **synchrone visible** :
  - barre de progression par pièce
  - logs lisibles ("piece 3/16: bg-2024 → 50/50 samples")
  - écrit dans `ml/datasets/<nid>/augmentations/<iid>/sample_*.jpg`
  - et stage des symlinks dans `ml/datasets/iterations/<iid>/<eurio_id>/`
    (statu quo)

**Validation** :
- chaque coin de la cohort a `≥ variant_count` samples sur disque
- aucun coin avec `skipped_reason` (pas de numista_id, pas d'obverse, etc.)

**Sortie** : N coins × variant_count samples bakés.

**Statut visuel** : "800 / 800 (16 × 50)" en vert, ou "650 / 800 — 3
coins manquants" en orange + liste.

### Tiroir I3 — Training

**Entrée** : I2 `done`.

**Avant le lancement, le tiroir affiche une carte "Runtime"** :
- machine détectée : `Apple M3 (arm64)` ou `Linux x86_64 + NVIDIA
  GeForce GTX 1080 Ti (CUDA 12.x)`
- backend torch : `torch 2.x · mps` ou `torch 2.x cu121`
- workers DataLoader prévus (4 sur CUDA, 0 sur MPS/CPU — déjà
  encodé dans `train_embedder.py:400`)
- estimation grossière du temps par epoch (extraite des runs précédents
  sur ce host — phase 4 décide si on l'implem v1)

**Action de l'utilisateur** : click "Lancer training".

**Pendant le training** :
- I1 et I2 deviennent `done` collapsed (recipe + nb aug visibles, non
  éditables)
- I3 expand affiche :
  - phase (`bake` / `training` / `export` / `benchmark` — déjà partagé
    par le runner via le subprocess de chain)
  - epoch courant / total + barre de progression
  - loss courante + best
  - temps écoulé / ETA (calculé à partir de la moyenne des epochs
    déjà finies)
  - **log tail brut** : 30 dernières lignes stdout du subprocess
    `train_embedder.py`, scrollable, monospace
  - device runtime confirmé (vérif `next(model.parameters()).device`
    écrite par `train_embedder.py` à epoch 0)
  - bouton Stop visible ici aussi (statu quo SIGTERM, déjà OK)

**Polling** : 2s tant que `iteration.status === 'training'`,
2s tant que `'benchmarking'`, off sinon.

**Validation** :
- training_run terminé (`status='completed'`)
- export TFLite réussi (mtime du `.tflite` ≥ training finished_at)
- benchmark run terminé

**Sortie** : `iteration.status='completed'` + `r_at_1` calculé.

### Tiroir I4 — Évaluation

**Entrée** : I3 `done`.

Méta-tiroir avec 4 sous-tiroirs (chacun avec son propre état) :

#### I4a — Benchmark studio
R@1 / R@3 / R@5 / spread sur les captures device de la cohort.
Statu quo, juste regroupé visuellement.

#### I4b — Aug ↔ réelles (DINO)
Galerie côte à côte + cosine par pièce. Statu quo
(`AugVsRealSection.vue`).

#### I4c — Build cohortTest APK
Commande copy-paste + état du bundle. Statu quo
(`BuildTestAppSection.vue`).

#### I4d — Live tests device
Sync JSONL, matrix coin × condition. Statu quo
(`LiveTestsSection.vue`).

Ces 4 sont déjà livrés — la phase 2 les regroupe sous un même header
"§I4 Évaluation" et ne change pas leur logique.

## Training pipeline : deux backends

Voir phase 4. Résumé du contrat :

- Un module unique `ml/training/runtime.py` détecte et expose le
  backend.
- `train_embedder.py` log au boot, en JSON sur stdout :
  ```
  {"event":"runtime","host":"darwin-arm64","torch":"2.x","backend":"mps","device":"mps:0"}
  ```
  + une vraie vérif post-`.to(device)` :
  ```
  {"event":"tensor_check","model_device":"mps:0"}
  ```
- Un endpoint `GET /lab/runner/runtime-info` expose ces infos statiques
  au front (avant même qu'on lance un run).
- Un bandeau global `/lab` affiche en permanence "Tu tournes sur Mac
  M3 (mps)" ou "PC + 1080 Ti (cuda:0)".

## Pourquoi ce design casse les mensonges

| Affirmation | Vérification utilisateur |
|---|---|
| "Entraîné sur obverse uniquement" | `iteration_augmentations.py` log `source_path` au bake (phase 3 le rend explicite). Le tiroir I2 affiche "source: obverse.jpg" par pièce. |
| "Plus d'augmentation à la volée" | `train_embedder.py` log au boot `dataset_size = N (prebaked, runtime augmentations: disabled)`. Le tail visible dans I3 le confirme. |
| "Ça tourne sur ton GPU" | I3 affiche le device **avant** le lancement (carte runtime) et **pendant** (log `tensor_check`). |
| "Le training avance" | Loss et epoch streamés en temps réel, pas calculés a posteriori. |
| "Stop fonctionne" | SIGTERM coopératif déjà en place (Sprint 1), exposé visuellement avec un bouton dans I3. |

## Hors-scope dans ce refacto

- Pas de **changement** des métriques ou de la définition des
  benchmarks. Les biais identifiés en review (cohortTest filtré,
  studio circulaire) restent. C'est un autre chantier.
- Pas de **A/B comparaison side-by-side** entre iterations. Ça reste
  via `/lab/cohorts/<id>` (trajectoire). Le refacto ne traite que la
  page iteration unique.
- Pas de **multi-cohort training** : statu quo, une iteration =
  une cohort.
- Pas de **changement de schéma DB** sauf si phase 5 décide qu'un
  fichier JSON ne suffit pas pour le progress.
