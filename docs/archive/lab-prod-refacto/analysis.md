# État actuel : l'enchevêtrement lab ↔ prod

> Snapshot 2026-05-02. À lire avant n'importe quelle phase. Décrit
> précisément ce qui partage de l'état entre lab et prod aujourd'hui,
> les symptômes observables, et les pièges connus.

## Les deux symptômes qui ont déclenché ce refacto

### Symptôme 1 — Carryover d'embeddings (test-2, `e3c4df8678eb`)

Cohort `mix-zone-7-cls`, 7 nouveaux `eurio_id` ajoutés. Métriques
contradictoires :

- Bench studio : R@1 = **85.7%** (R@3 = 88.1%)
- Live tests Android : R@1 strict = **57.1%** (12/21)

Diagnostic complet :
[`docs/training-pipeline/journal/dceb9f44-mix-zone-7-cls/test-2.md`](../training-pipeline/journal/dceb9f44-mix-zone-7-cls/test-2.md).

Cause racine : `iteration_runner._launch_training` appelait
`training_runner.start_run(removed=[])`. Le step `_compute_embeddings`
lit `eurio-poc/val/`, où traînaient les classes des entraînements
précédents (4 `design_group_id` legacy + 13 `eurio_id` historiques).
Résultat : `embeddings_v1.json` à 20 entrées, alors que
`model_meta.json` indique `num_classes=7`. Le matcher voyait 20
candidats dont 6 doublons visuels.

Ce point est **partiellement patché** dans
`iteration_runner.py:871-884` (mode "destructif par itération" : le
runner calcule `removed = current_classes - eurio_ids` et le passe à
`start_run`). Le patch est explicitement temporaire — il sera retiré
quand l'isolation par itération sera en place (phase 2).

### Symptôme 2 — Conflit eurio_id ↔ design_group (test-1 v2 sur cohort mix-zone-7-cls-v2, `8ac508b062da`)

Même cohort, itération clean. Au step `_prepare`, les logs montrent :

```
Restricting to 7 class(es) from --only-classes
TOTAL  4  4  0  0
Device val total: 24 images   (= 4 classes × 6 device snaps)
```

4 classes au lieu de 7. Les 3 manquantes : `at-2002-2eur-standard`,
`be-2007-2eur-standard`, `es-1999-2eur-standard` — celles qui
appartiennent à un `design_group_id` côté Supabase.

Cause racine : conflit entre **deux conceptions du label space** :

- **`iteration_runner.py`** raisonne en `eurio_id` : le folder
  `iterations/<iid>/` contient 7 sous-dossiers nommés par `eurio_id`,
  training prend 7 classes, `--only-classes` lui passe 7 `eurio_id`.
- **`prepare_dataset.py` + `class_resolver.py`** raisonnent en
  `COALESCE(design_group_id, eurio_id)`. Le Resolver tape Supabase,
  voit que `at-2002` a `design_group_id='at-2eur-standard-2002'`, et
  expose donc cette pièce sous `class_id='at-2eur-standard-2002'`.

Conséquence dans `_discover_classes` (prepare_dataset.py:132) :

```python
descriptor = resolver.for_numista(64)  # AT 2002
# descriptor.class_id == 'at-2eur-standard-2002'  (design_group_id)
if descriptor.class_id not in only_classes:  # not in {'at-2002-2eur-standard', ...}
    continue  # SKIPPED silencieusement
```

`prepare_dataset.py` saute les 3 standards. `eurio-poc/val/` n'a que
4 classes. `compute_embeddings.py` produit `embeddings_v1.json` à 4
entrées. Bench / live tests ne peuvent **jamais** prédire AT-2002,
BE-2007, ES-1999 correctement (pas de centroïde dans la lib).

Si on laisse la run se terminer, on récolte des chiffres pour de
mauvaises raisons. **C'est ce qui a déclenché ce refacto.**

## Cartographie des artefacts partagés

### Local — filesystem

| Path | Écrit par | Lu par | Rôle | Isolé par iteration ? |
|---|---|---|---|---|
| `ml/datasets/eurio-poc/{train,val,test}/<class>/*.jpg` | `prepare_dataset.py` | `train_embedder.py`, `compute_embeddings.py` | Splits ImageFolder, val pour centroids | ❌ singleton |
| `ml/datasets/eurio-poc/class_manifest.json` | `prepare_dataset.py` | `compute_embeddings.py` | Mapping `class_id` → `class_kind` + members | ❌ singleton |
| `ml/datasets/iterations/<iid>/<eurio_id>/sample_*.jpg` | `iteration_augmentations.py` | `train_embedder.py` (via `dataset_override`) | Bake d'augmentations | ✅ |
| `ml/datasets/<nid>/augmentations/<iid>/sample_*.jpg` | idem | idem | Source canonique des baked samples | ✅ |
| `ml/checkpoints/best_model.pth` | `train_embedder.py` (chaque run) | tout aval | Modèle | ❌ singleton |
| `ml/checkpoints/training_log.json` | `train_embedder.py` | `_finalize_run` | Métriques par epoch | ❌ singleton |
| `ml/output/embeddings_v1.json` | `compute_embeddings.py` | seed Supabase, build APK, bench, live tests | Library de centroids | ❌ singleton |
| `ml/output/coin_embeddings.json` | (legacy) | ? | Reliquat — 26 entries vs 20 dans v1 | ❌ singleton |
| `ml/output/eurio_embedder_v1.tflite` | `export_tflite.py` | build APK | Encoder TFLite | ❌ singleton |
| `ml/output/model_meta.json` | export | bundle Android | Metadata + class list | ❌ singleton |
| `ml/output/per_class_metrics.json` | `validate_per_class.py` | UI lab | Recall@k par classe | ❌ singleton |
| `ml/state/training.db` | tous les runners | tout | DB partagée | ✅ (rows indexées par iid/run_id) |
| `ml/state/training_progress/<iid>.json` | `train_embedder.py` (via `--iteration-id`) | UI training monitor | Progress live | ✅ |
| `ml/state/live_test_logs/<iid>.jsonl` | API ingest | UI lab | Live tests par iteration | ✅ |

### Distant — Supabase

| Table | Écrit par | Quand | Rôle |
|---|---|---|---|
| `model_classes` | `_seed` (training_runner) | À chaque training run lab | Liste des classes connues |
| `coin_embeddings` | `_seed` | À chaque training run lab | Centroids par eurio_id |
| `coins` | seed manuel + admin UI | Catalogue éditorial | Source de vérité pour le resolver |
| `design_groups` | seed manuel + admin UI | Catalogue éditorial | Source du `design_group_id` |

`_seed` est appelé inconditionnellement par
`training_runner._execute` step 4. **Aucun flag** pour distinguer
"run d'expérimentation lab" de "run promu en prod". Supabase reflète
toujours la dernière itération lancée localement.

### Bundle Android — `app-android/src/cohortTest/assets/cohort_bundle/`

`build_cohort_bundle` copie l'état actuel
(`embeddings_v1.json`, `eurio_embedder_v1.tflite`, etc.) au moment où
l'utilisateur déclenche un build pour cohort-test. Le bundle est
cohérent avec l'état local au moment du build, mais il dépend du même
singleton. Pas de moyen de demander "bundle moi l'itération X".

## Ce qui est déjà bien isolé (à préserver)

Le pattern existant n'est pas mauvais — il est **partiel**. Ce qui a
été ajouté en sprint 1+ est correctement isolé par `iteration_id` :

- `ml/datasets/iterations/<iid>/...` (symlinks dataset)
- `ml/datasets/<nid>/augmentations/<iid>/...` (bake)
- `ml/state/training.db` (toutes les tables sont indexées par
  `iteration_id` / `run_id` / `cohort_id`)
- `ml/state/training_progress/<iid>.json`
- `ml/state/live_test_logs/<iid>.jsonl`

**Ce qui pré-existe (eurio-poc/, output/, checkpoints/) reste
singleton.** La phase 2 du refacto étend simplement le pattern existant
à ces artefacts.

## Le double label space

Le conflit eurio_id ↔ design_group n'est pas un bug isolé — c'est une
ambiguïté de design.

`docs/design/_shared/design-groups.md` décrit le `design_group_id`
comme un mécanisme de regroupement éditorial : "ces eurio_id partagent
la même matrice visuelle, on les compte comme une seule classe pour
ArcFace". Ça a du sens à l'usage (pour ne pas multiplier les classes
quasi-identiques), mais ça mélange deux préoccupations :

1. **Décision ML** — quelle granularité de classes pour ArcFace.
2. **Décision produit** — quelles pièces afficher comme "interchangeables"
   dans l'UI.

Aujourd'hui les deux sont conflées dans le même champ Supabase
(`coins.design_group_id`). Le Resolver applique un COALESCE qui force
les scripts ML à voir le monde en `design_group_id` quand il existe.
L'iteration_runner, plus récent, a été construit en `eurio_id` pur
parce que c'est ce qu'on veut **isolé par expérimentation**.

La **vision** (cf. [`vision.md`](./vision.md)) résout ça en posant :

- **Lab** = `eurio_id` partout, point. Une expérimentation traite
  chaque coin individuellement.
- **Prod** = mapping `design_group_id` appliqué au moment de la
  promotion (les centroïdes des `eurio_id` membres d'un même group
  sont fusionnés à ce moment-là, ou le matcher applique la règle
  d'équivalence à l'inférence — décision à trancher en phase 3).

## Symptômes annexes que l'isolation résoudrait

1. Le mode "destructif par itération" (qui est dans
   `iteration_runner.py:871-884` aujourd'hui) cesserait d'être
   nécessaire — une itération ne touche pas l'état partagé.
2. `recall_at_1=0.38` pendant le training vs `R@1=85.7%` au bench :
   ces deux métriques mesurent des surfaces différentes (val pollué
   pendant le training, embeddings library pour le bench). Avec
   isolation, le contrat de chaque mesure est explicite.
3. `coin_embeddings.json` à 26 entries vs `embeddings_v1.json` à 20 :
   reliquat typique d'un singleton accumulé sans purge. Disparaît avec
   un store par itération.
4. Impossibilité de revenir en arrière. Si test-1 v2 est moins bon que
   test-2, on n'a pas de "snapshot test-2" à restaurer.
5. `_seed` qui pousse en Supabase à chaque run lab — effet de bord
   invisible et imprévisible.
6. Le bundle Android ne sait référencer que "le modèle actuel". Pas de
   moyen d'A/B-tester deux itérations sur le même device.

## Les fichiers sensibles

| Fichier | Pourquoi sensible |
|---|---|
| `ml/api/iteration_runner.py` | Orchestrateur lab. Contient le patch temporaire "destructif par itération" (ligne ~880). À retirer en phase 2. |
| `ml/api/training_runner.py` | Pipeline 6-steps partagée legacy + lab. Le step 0 `_delete` et le step 4 `_seed` sont les leviers de l'isolation. |
| `ml/eval/class_resolver.py` | Source du COALESCE design_group/eurio. Phase 1 ajoute un mode eurio-only. |
| `ml/training/prepare_dataset.py` | Le COALESCE remonte ici via `_discover_classes`. Phase 1 ajoute le flag `--class-kind`. |
| `ml/training/compute_embeddings.py` | Lit `eurio-poc/val/`. Phase 2 le rend iteration-aware. |
| `ml/bootstrap/seed_supabase.py` | Push Supabase. Phase 3 le rend opt-in promote-only. |
| `ml/scripts/build_cohort_bundle.py` | Bundle Android. Phase 4 le rend iteration-aware. |
