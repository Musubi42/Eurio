# Filesystem & DB layout

> Source de vérité pour où vit chaque artefact de la pipeline. À mettre
> à jour quand on ajoute un type de donnée.

## Disque

### `ml/datasets/<numista_id>/` — racine par pièce (statu quo)

```
ml/datasets/<numista_id>/
├── obverse.png, reverse.png      ← Numista raw
├── 001.jpg, 002.jpg, …            ← Numista variants
├── source/                        ← (futur, deferred) raw downloads consolidés
├── captures/                      ← captures device canoniques (acté)
│   ├── bright_plain.jpg
│   ├── dim_plain.jpg
│   ├── daylight_plain.jpg
│   ├── bright_textured.jpg
│   ├── tilt_plain.jpg
│   └── close_plain.jpg
└── augmentations/                 ← snapshot par iteration (sprint 1)
    └── <iteration_id>/
        ├── sample_001.jpg
        ├── sample_002.jpg
        └── …
```

**Note migration `<numista_id>` → `coins/<numista_id>/`** : deferred,
hors-scope. Voir `docs/admin/cohort-capture-flow/design.md` §10. Quand on
fera la migration, tous les paths ci-dessus seront préfixés par `coins/`.
Le code utilise des constantes pour faciliter ce switch.

### `ml/datasets/eval_real_norm/<eurio_id>/` — legacy compat

Encore utilisé par `prepare_dataset.py` pour le val/ split. Alimenté par
`sync_eval_real.py` (déjà en place). Garder tel quel, ne pas toucher.

### `ml/state/`

```
ml/state/
├── training.db                    ← SQLite source de vérité (cohorts, iterations, runs)
├── cohort_csvs/<slug>.csv         ← CSV de capture device (acté)
└── live_test_logs/<iteration_id>.jsonl   ← (sprint 4) résultats device parsés
```

### `ml/output/cohort_test_<iteration_id>/` — bundle pour APK

Sortie du build snapshot pour cohortTest (sprint 3) :

```
ml/output/cohort_test_<iteration_id>/
├── model.tflite                   ← export du modèle de l'iteration
├── catalog_snapshot.json          ← filtré aux coins de la cohort
├── cohort_meta.json               ← eurio_ids, name
└── live_tests_manifest.json       ← liste des 9 tests à faire
```

Copié vers `app-android/src/cohortTest/assets/` par la task
`cohort-test:install`.

### Device — `/sdcard/Android/data/com.musubi.eurio.cohorttest/files/Documents/`

```
/sdcard/.../com.musubi.eurio.cohorttest/files/Documents/
├── eurio_debug/<iteration_id>/    ← snaps debug si activé
└── eurio_live_tests/<iteration_id>.jsonl   ← résultats live (1 ligne par test)
```

Pulled via `cohort-test:pull` task.

## Base de données — `ml/state/training.db` (SQLite)

### Tables existantes (pertinentes)

- `experiment_cohorts` — id, name, eurio_ids_json, status (`draft|frozen`),
  frozen_at, …  *(acté en cohort capture flow)*
- `experiment_iterations` — cohort_id, recipe_id, status, training_run_id,
  benchmark_run_id, training_config_json, …
- `training_runs` — modèle entraîné, recall_at_1, status, …
- `benchmark_runs` — R@1, R@3, R@5, num_photos, per_zone, …
- `augmentation_recipes` — DSL de la recipe

### Tables à ajouter (sprint 4)

```sql
CREATE TABLE iteration_live_tests (
  id              TEXT PRIMARY KEY,
  iteration_id    TEXT NOT NULL REFERENCES experiment_iterations(id) ON DELETE CASCADE,
  test_idx        INTEGER NOT NULL,
  expected_eurio_id TEXT NOT NULL,
  condition       TEXT NOT NULL CHECK (condition IN ('bright','dim','tilt')),
  predicted_top3_json TEXT NOT NULL,    -- [{eurio_id, similarity}, ...]
  predicted_top1  TEXT,                  -- denormalized for fast queries
  similarity_top1 REAL,
  is_correct      INTEGER NOT NULL,      -- 1 if predicted_top1 == expected, else 0
  ts              TEXT NOT NULL          -- ISO8601 from device
);

CREATE INDEX idx_live_tests_iter ON iteration_live_tests(iteration_id);
```

### Champs à ajouter aux tables existantes

`experiment_iterations` :
- `augmentations_seed INTEGER` — fixé à la création de l'iteration, utilisé
  pour reproductibilité (sprint 1).
- `augmentations_path TEXT` — pas strictement nécessaire (calculable depuis
  iteration_id), mais utile pour debugging.

## Endpoints API par sprint

Voir chaque `sprint-N-*.md` pour la liste exhaustive des endpoints à
ajouter/modifier.

## Conventions de nommage

- **iteration_id** : `uuid.uuid4().hex[:12]` (déjà en place)
- **Augmentation samples** : `sample_<3-digit>.jpg`, indexés à partir de 001
- **Live test JSONL** : 1 ligne JSON par test, ordre = ordre de réalisation
  par l'utilisateur

## Tailles attendues (estimations)

| Artefact | Taille typique | × N |
|---|---|---|
| 1 augmentation (224×224 jpg) | ~30 KB | × 100/pièce × 17 pièces × N iterations |
| Snapshot augmentations 1 iter | ~50 MB | × N iterations |
| 1 live_test entry JSONL | ~500 B | × 9 tests × N iterations |
| 1 modèle tflite | ~5-10 MB | × N iterations |
| APK cohortTest | ~30-40 MB | rebuild à chaque iteration |

⇒ une cohort de 17 pièces × 5 iterations ≈ 250 MB augmentations + 50 MB
modèles. Acceptable. GC en sprint 5.
