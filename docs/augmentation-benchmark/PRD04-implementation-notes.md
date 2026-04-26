# PRD Bloc 4 — Notes d'implémentation (2026-04-19)

> Résumé de la session qui a livré le Lab. À lire pour reprendre, ajouter des heuristiques d'interprétation, ou étendre les entités.

## Ce qui a été livré

### SQL + Store

| Fichier | Changement |
|---|---|
| `ml/state/schema.sql` | Tables `experiment_cohorts` + `experiment_iterations` + indexes. |
| `ml/state/store.py` | Migration additive `benchmark_runs.per_condition_json`. Dataclasses `ExperimentCohortRow`, `ExperimentIterationRow`. CRUD complet. Extensions de `BenchmarkRunRow` / `create_benchmark_run` / `update_benchmark_run` avec `per_condition` + `training_run_id` (paramètre d'update). |
| `ml/state/__init__.py` | Re-exports. |

### Scripts + helpers

| Fichier | Changement |
|---|---|
| `ml/real_photo_meta.py` | **nouveau** — parsing filename partagé (5 axes : lighting/background/angle/distance/state). `PhotoConditions` dataclass + `parse_filename()`. |
| `ml/check_real_photos.py` | Consomme `real_photo_meta.py` (supprime la duplication). |
| `ml/evaluate_real_photos.py` | `PhotoResult.conditions` rempli via `parse_filename`. `_aggregate` calcule le bloc `per_condition` par axe. Rapport JSON + SQLite enrichis. |

### Logique pure

| Fichier | Rôle |
|---|---|
| `ml/api/iteration_logic.py` | **nouveau** — `compute_verdict`, `compute_delta`, `compute_input_diff` (recipe flatten par layer), `compute_sensitivity` + `SensitivityEntry`. Seuils modifiables en tête de module. |

### Orchestrateur + API

| Fichier | Rôle |
|---|---|
| `ml/api/iteration_runner.py` | **nouveau** — `IterationRunner` avec lock global, `create_and_launch`, `recover_on_boot`, chain `stage → train → bench → finalize`. |
| `ml/api/lab_routes.py` | **nouveau** — router `/lab/*` : cohorts CRUD, iterations CRUD + launch, trajectory, sensitivity, runner status. |
| `ml/api/server.py` | `include_router(lab_routes)` + `bind(store, runner)` + startup hook `recover_on_boot`. |

### UI Admin (Vue)

| Fichier | Rôle |
|---|---|
| `features/lab/types.ts` | Shapes API strictement typées. |
| `features/lab/composables/useLabApi.ts` | Wrappers fetch complets. |
| `features/lab/components/VerdictBadge.vue` | Badge coloré par verdict avec indicateur d'override. |
| `.../InputDiffChip.vue` | Chips `path: before → after` pour le diff inputs. |
| `.../PerConditionTable.vue` | Tableau R@1 par valeur d'axe (réutilisé aussi dans `/benchmark`). |
| `.../TrajectoryChart.vue` | SVG waterfall, clic sur un point navigue vers l'itération. |
| `.../SensitivityPanel.vue` | Table paramètres triés par |ΔR@1 moyen|. |
| `.../CohortCard.vue` | Tile pour `/lab` home. |
| `.../IterationRow.vue` | Ligne dans la table cohort detail avec InputDiffChip inline. |
| `features/lab/pages/LabHomePage.vue` | Grid + stats + filter zone + CTA new cohort. |
| `.../CohortNewPage.vue` | Wizard 3 étapes avec badges photo-ready. |
| `.../CohortDetailPage.vue` | **Vue clé** : header + trajectory + iterations table + sensitivity sidebar. Polling 4s si itération active. |
| `.../IterationNewPage.vue` | Wizard avec prefill du parent + preview diff. |
| `.../IterationDetailPage.vue` | Cartes + per-zone/per-coin delta + per-condition + notes/override. Polling 4s en cours. |

### Router + nav + entry points

| Fichier | Changement |
|---|---|
| `admin/packages/web/src/app/router.ts` | 5 routes Lab lazy-loaded. |
| `admin/packages/web/src/app/nav.ts` | Entrée "Lab" (icône `FlaskConical`) après "Benchmark". |
| `features/coins/pages/CoinsPage.vue` | CTA "Nouveau cohort Lab" dans le footer sticky, avec `cohortDisabled` / `cohortTitle` / `openCohortWizard`. |
| `features/benchmark/pages/BenchmarkRunDetailPage.vue` | Nouvelle section "Par axe de variabilité" consommant `PerConditionTable`. |
| `features/benchmark/types.ts` | `BenchmarkRunDetail.per_condition` typé. |

### Tests

| Fichier | Tests |
|---|---|
| `ml/tests/test_benchmark.py` | +`test_aggregate_per_condition_buckets` — vérifie R@1 par axe. |
| `ml/tests/test_lab.py` | Store CRUD (cohorts + iterations + cascade + FK SET NULL), verdict matrix, delta, input_diff, sensitivity. |
| `ml/tests/test_lab_api.py` | Routes CRUD, validation, 404/409, launch via stub runner, trajectory, sensitivity. |

**75/75 tests passent** (`cd ml && .venv/bin/python -m pytest tests/ -q`).
**vue-tsc clean** sur `features/lab/`, `features/benchmark/`, `app/router`, `app/nav`, `features/coins/pages/CoinsPage.vue`.

## Contrats figés

### Cohort payload

```jsonc
{
  "name": "green-v1",              // kebab-case unique
  "description": "…",
  "zone": "green",                 // optional, ∈ {green, orange, red}
  "eurio_ids": ["fr-…", "de-…"]    // frozen once created
}
```

### Iteration payload

```jsonc
{
  "name": "green-v2 more variants",
  "hypothesis": "…",
  "parent_iteration_id": "abc123", // optional
  "recipe_id": "green-tuned-v2",   // optional, id OR name
  "variant_count": 200,            // 1-2000
  "training_config": {
    "epochs": 40,
    "batch_size": 256,
    "m_per_class": 4
  }
}
```

### Verdict states

`pending` → `baseline` (première itération) | `better` | `worse` | `mixed` | `no_change`

Seuils : `SIGNIFICANT_DELTA=0.02`, `NOISE_BAND=0.005`, `ZONE_REGRESSION_THRESHOLD=0.03` dans `iteration_logic.py`.

### Iteration statuses

`pending` → `training` → `benchmarking` → `completed` | `failed`

## Comment vérifier l'état du Bloc 4

```bash
# 1. Tests
cd ml && .venv/bin/python -m pytest tests/ -q

# 2. Migration appliquée
cd ml && .venv/bin/python -c "
from state import Store; from pathlib import Path
s = Store(Path('state/training.db'))
c = s._connection()
cols = [r['name'] for r in c.execute(\"PRAGMA table_info(benchmark_runs)\").fetchall()]
print('per_condition_json on benchmark_runs:', 'per_condition_json' in cols)
print('experiment_cohorts table:',
  c.execute(\"SELECT count(*) FROM sqlite_master WHERE type='table' AND name='experiment_cohorts'\").fetchone()[0] == 1)
print('experiment_iterations table:',
  c.execute(\"SELECT count(*) FROM sqlite_master WHERE type='table' AND name='experiment_iterations'\").fetchone()[0] == 1)
"

# 3. Endpoints montés
cd ml && .venv/bin/python -c "
import sys; sys.path.insert(0, '.')
from api.server import app
print('\n'.join(sorted([r.path for r in app.routes if '/lab' in getattr(r, 'path', '')])))
"

# 4. Type-check frontend
cd admin/packages/web && pnpm exec vue-tsc --noEmit
```

## Points d'attention & dette identifiée

- **Recipe config dans `_snapshot_inputs`** : si `recipe_id` est supprimée après coup (FK SET NULL), le snapshot perd le recipe config → input_diff devient null côté recipe. Pas bloquant (le delta R@1 reste), mais à surveiller. Alternative v2 : snapshot la config au moment de l'iteration creation.
- **Training `best_model.pth` partagé** : le gate 1-iteration-global évite les collisions, mais si le dev lance un `/training/run` en parallèle via `/coins`, ça va clasher. À moyen terme, il faudrait nommer les checkpoints par run_id.
- **`TrainingConfig` flat** : pour l'instant on passe `{epochs, batch_size, m_per_class}` à plat. Si on veut tracker plus (lr schedule, freeze_epochs), faudra étendre — mais ça se fait sans migration.
- **Sensitivity agrégation simple** : moyenne des deltas. Ne tient pas compte de la variance ni du nombre d'observations dans le ranking. v2 : confidence interval ou z-score.
- **Override verdict n'ajoute pas de justification** : dropdown, mais pas de champ "pourquoi". Workaround actuel : écrire dans `notes`. v2 : champ dédié.
- **Recovery au boot ne gère pas les itérations en `pending`** : si une itération est persistée en `pending` (jamais démarrée — shouldn't happen), elle reste bloquée. Edge case théorique.
- **Per-condition bucket axes** : drops axes vides. Si aucun filename ne matche, axis absent. Pour un dataset de test sans convention, le per_condition tombe à vide → tableau non affiché, UI dégrade propre.
- **`iteration_runner.POLL_INTERVAL_SEC = 5`** : busy-wait sur le store. Pas optimal mais simple. Si l'utilisation monte, passer sur notification par event/condition.

## Comment tester manuellement end-to-end

```bash
# 1. ML API
cd ml && go-task ml:api

# 2. Admin web
cd admin/packages/web && pnpm dev

# 3. Navigate : /coins → sélectionne 3-5 pièces qui ont des photos → clic "Nouveau cohort Lab"
# 4. Wizard → nomme → créé
# 5. Clic "Nouvelle itération" → hypothèse → Lancer
# 6. Observer le cohort : training en cours → benchmark en cours → verdict
# 7. Drill-down iteration : R@k, delta, per-zone, per-coin, per-axis, notes
# 8. Créer une 2e itération (parent = baseline) en changeant variant_count
# 9. Observer delta + sensibilité
# 10. Compare manuel via les 2 lignes de la table
```

## Références croisées

- [`PRD01-implementation-notes.md`](./PRD01-implementation-notes.md) — pipeline + API.
- [`PRD02-implementation-notes.md`](./PRD02-implementation-notes.md) — Studio.
- [`PRD03-implementation-notes.md`](./PRD03-implementation-notes.md) — Benchmark real-photo.
- [`04-experiments-lab.md`](./04-experiments-lab.md) — PRD Bloc 4.
