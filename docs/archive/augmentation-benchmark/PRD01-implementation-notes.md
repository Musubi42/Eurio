# PRD Bloc 1 — Notes d'implémentation (2026-04-19)

> Résumé de la session qui a livré le Bloc 1. À lire au démarrage de la session Bloc 2 (Studio) ou Bloc 3 (Benchmark) pour reprendre avec le bon contexte.

## Ce qui a été livré

### Docs (alignement + décisions)

- [01-backend-pipeline.md](./01-backend-pipeline.md) — scope étendu (migrations `training_runs.aug_recipe_id` + `training_staging.aug_recipe_id`, extension `/training/stage`), shape `/preview` figée, 5 questions ouvertes tranchées.
- [02-augmentation-studio.md](./02-augmentation-studio.md) — shape `POST /augmentation/preview` alignée avec PRD01 §5.4.

### Décisions tranchées (§8 PRD01)

| # | Décision |
|---|----------|
| Q1 | TTL previews 24h, cleanup au démarrage FastAPI |
| Q2 | Cap `count` = 64, rejet 400 au-delà |
| Q3 | Bounds → rejet 400 avec `{layer, param}` pour le Studio |
| Q4 | `based_on_recipe_id` auto côté Studio, optionnel côté API |
| Q5 | Pas de layer ordering en v1 |

### Code Python

| Fichier | Changement |
|---|---|
| `ml/augmentations/base.py` | `ParamSchema`/`LayerSchema` TypedDicts, classmethod `Augmentor.get_schema()` par défaut, constante `PROBABILITY_SCHEMA` réutilisable |
| `ml/augmentations/perspective.py` | `get_schema()` avec bounds et descriptions FR |
| `ml/augmentations/relighting.py` | idem — expose `ambient`, `intensity_range`, élévations, `normal_strength`, `smooth_sigma` |
| `ml/augmentations/overlays.py` | idem — expose `categories` (multi), `opacity_range`, `max_layers` |
| `ml/augmentations/pipeline.py` | `list_layer_schemas()` + `validate_recipe()` + `RecipeValidationError(layer, param)` |
| `ml/augmentations/__init__.py` | exports figés : `validate_recipe`, `list_layer_schemas`, `RecipeValidationError`, `OVERLAY_CATEGORIES`, `LayerSchema`, `ParamSchema` |
| `ml/state/schema.sql` | nouvelles tables `augmentation_recipes`, `augmentation_runs`. Migrations additives commentées (appliquées via Python helper) |
| `ml/state/store.py` | `AugmentationRecipeRow`, `AugmentationRunRow` dataclasses ; `RunRow.aug_recipe_id` ; migration `_ensure_column` via `PRAGMA table_info` ; méthodes : `create_recipe/get_recipe/list_recipes/update_recipe/delete_recipe` ; `create_aug_run/update_aug_run/get_aug_run/prune_aug_runs_older_than` ; `stage_classes(items, aug_recipe_ids=…)` ; `list_staging_with_recipe`, `clear_staging_with_recipe` ; `update_run_aug_recipe` |
| `ml/state/__init__.py` | re-exports `AugmentationRecipeRow`, `AugmentationRunRow` |
| `ml/api/augmentation_routes.py` | **nouveau** — `APIRouter("/augmentation")` : `GET /schema`, `GET /overlays`, `POST /preview`, `GET /preview/images/{run_id}/{index}`, CRUD `/recipes`. `cleanup_expired_previews()` idempotent. Bound au Store via `augmentation_routes.bind(store, supabase_fetcher)` |
| `ml/api/server.py` | `app.include_router(augmentation_routes.router)` + hook `on_startup` qui déclenche le cleanup TTL. `StageItem.aug_recipe_id` + `RunPayload.aug_recipe`. `/training/stage` résout le recipe (id ou name) et persiste dans `training_staging`. `/training/run` promeut le recipe (override > homogène) et appelle `update_run_aug_recipe` |
| `ml/api/training_runner.py` | Le step `Entraînement` ajoute `--aug-recipe <id>` à la CLI si présent dans `cfg["aug_recipe"]` ou `row.aug_recipe_id` |
| `ml/train_embedder.py` | `--aug-recipe <id_or_name>` ; résolution via Store ; wrapper PIL→PIL dans `get_train_transforms(recipe)` ; prepend à la Compose torchvision ; non-régression si flag absent |
| `ml/preview_augmentations.py` | `--recipe <id_or_name>` prioritaire sur `--zone` ; charge depuis Store |

### Tests

- `ml/tests/test_augmentation.py` (17 tests) — introspection, validation (recipes OK, bounds, unknown layers, unknown params, list length/options), déterminisme pipeline seed-based, Store CRUD, staging avec recipe ids, non-régression staging legacy, `create_run(aug_recipe_id)`, prune TTL.
- `ml/tests/test_augmentation_api.py` (9 tests) — `/schema`, `/overlays`, CRUD recipes (create/duplicate/get by id+name/list/update/delete), rejets 400 (bounds, unknown layer, bad name, count cap, source manquante, recipe invalide).

Tous les tests passent : **26/26** en ~0.5s (`.venv/bin/python -m pytest ml/tests/ -q`).

## Contrats figés — ne pas changer sans bump explicite

### Shape recipe (JSON)

```jsonc
{
  "count": 50,                                // optionnel, défaut côté pipeline
  "layers": [
    { "type": "perspective", "probability": 0.7, "max_tilt_degrees": 20 },
    { "type": "relighting", "probability": 0.6, "ambient": 0.35, "intensity_range": [0.7, 1.1], /* ... */ },
    { "type": "overlays", "probability": 0.7, "categories": ["patina","dust"], "opacity_range": [0.10, 0.30], "max_layers": 2 }
  ]
}
```

- `intensity_range`, `opacity_range` → **listes** (JSON-friendly), jamais de tuple côté wire.
- Noms de layer types gravés : `perspective`, `relighting`, `overlays`.
- Ajouts possibles (nouveaux layers) sans bump. Renames ou suppressions = bump.

### Shape `POST /augmentation/preview` réponse

```jsonc
{
  "run_id": "ab12cd34ef56",
  "images": [
    { "index": 0, "url": "/augmentation/preview/images/ab12cd34ef56/0" },
    // ...
  ],
  "duration_ms": 2340,
  "seed": 42
}
```

Le Studio itère sur `images[].url` pour `<img :src>`.

### Shape `POST /training/stage` étendue

```jsonc
{
  "items": [
    { "class_id": "fr-2e-2007", "class_kind": "eurio_id", "aug_recipe_id": "red-tuned-v2" },
    { "class_id": "de-2e-2005", "class_kind": "eurio_id" }  // aug_recipe_id optionnel
  ]
}
```

`aug_recipe_id` accepte `id` ou `name` ; le serveur résout et persiste toujours l'`id`.

### Promotion `training_runs.aug_recipe_id`

Au moment du `POST /training/run` :

1. Si `RunPayload.aug_recipe` fourni → wins (override global).
2. Sinon, si tous les items staged partagent la **même** `aug_recipe_id` non-null → promue sur le run.
3. Sinon (hétérogène ou tout null) → `aug_recipe_id = null` sur le run (comportement legacy).

`v1` = un seul recipe par training run. Multi-recipes = v2.

## Ce qui reste pour Bloc 2 (Studio admin)

Voir `02-augmentation-studio.md`. Dépendances Bloc 1 = ✅ toutes livrées :

- `GET /augmentation/schema` — pour générer les sliders dynamiquement.
- `GET /augmentation/overlays` — pour lister les textures (read-only v1).
- `POST /augmentation/preview` + `GET /augmentation/preview/images/…` — grille 4×4.
- CRUD `/augmentation/recipes` — save/load/list.
- `/training/stage` accepte `aug_recipe_id` → handoff depuis le Studio fonctionne.

Points d'attention pour l'implém Bloc 2 :

- Le Studio doit résoudre `eurio_ids` query param → `Coin[]` via Supabase côté Vue (pattern `CoinsPage.vue`).
- Healthcheck + dégradation offline : calquer sur `ConfusionMapPage` / `TrainingPage`.
- `/augmentation/overlays` renvoie des chemins relatifs à `ml/data/overlays/` — le Studio ne sert pas les vignettes en v1, il affiche juste les noms.

## Ce qui reste pour Bloc 3 (Benchmark)

Voir `03-real-photo-benchmark.md`. Dépendances Bloc 1 = ✅ toutes livrées :

- Table `augmentation_recipes` existe → FK `benchmark_runs.recipe_id` valide.
- Table `training_runs` avec `aug_recipe_id` → FK `benchmark_runs.training_run_id` + chaîne de traçabilité complète.

Bloc 3 devra créer :

- Table `benchmark_runs` (`ml/state/schema.sql`).
- `ml/evaluate_real_photos.py` + `ml/check_real_photos.py`.
- Routes `/benchmark/*` dans `ml/api/` (mimer le pattern de `augmentation_routes.py` pour rester cohérent).
- Commandes `go-task ml:benchmark` + `go-task ml:benchmark:photos:check`.

## Comment vérifier l'état du Bloc 1

```bash
# 1. Migrations appliquées
cd ml && .venv/bin/python -c "
from state import Store
from pathlib import Path
s = Store(Path('state/training.db'))
conn = s._connection()
cols_runs = [r['name'] for r in conn.execute('PRAGMA table_info(training_runs)').fetchall()]
cols_stg  = [r['name'] for r in conn.execute('PRAGMA table_info(training_staging)').fetchall()]
print('aug_recipe_id on training_runs:', 'aug_recipe_id' in cols_runs)
print('aug_recipe_id on training_staging:', 'aug_recipe_id' in cols_stg)
print('augmentation_recipes table:', conn.execute(\"SELECT count(*) FROM sqlite_master WHERE type='table' AND name='augmentation_recipes'\").fetchone()[0] == 1)
print('augmentation_runs table:',    conn.execute(\"SELECT count(*) FROM sqlite_master WHERE type='table' AND name='augmentation_runs'\").fetchone()[0] == 1)
"

# 2. Endpoints enregistrés
cd ml && .venv/bin/python -c "
import sys; sys.path.insert(0, '.')
from api.server import app
print('\n'.join(sorted([r.path for r in app.routes if '/augmentation' in getattr(r, 'path', '')])))
"

# 3. Tous les tests passent
cd ml && .venv/bin/python -m pytest tests/ -q

# 4. Training legacy non régressé
cd ml && .venv/bin/python train_embedder.py --help   # doit afficher --aug-recipe
```

## Points d'attention & dette identifiée

- **Validation côté `/training/stage`** : pour l'instant on résout chaque `aug_recipe_id` via `store.get_recipe()`. Si un item en réfère 10 avec le même nom, on fait 10 lookups. Pas un problème au volume actuel (≤ 20 items) mais à optimiser si la liste explose.
- **RNG partagé entre workers DataLoader** : `AugmentationPipeline` maintient un RNG instance-level ; avec `num_workers > 0` torchvision peut forker, dupliquant l'état. Actuellement `mps` tourne `num_workers=0` donc pas d'impact ; à revoir si on passe sur CUDA avec workers > 0 (option : re-seed par worker).
- **Wrapper `transforms.Lambda`** autour du pipeline : simple mais pas introspectable. Si on veut plus tard afficher le pipeline dans le log training, prévoir un wrapper custom avec `__repr__` explicite.
- **Promotion `aug_recipe_id` homogène** : la règle "un seul recipe par run" est une simplification v1. Quand on voudra mélanger des zones dans un même training, il faudra persister la recette par classe (colonne sur `training_run_classes` ou table pivot).
- **Overlays read-only côté API** : pas d'upload de textures depuis le Studio. La banque vit dans `ml/data/overlays/` (generée par `generate_overlay_textures.py`). Le Studio montre ce qui existe, pas plus.

## Références croisées

- Pipeline d'augmentation d'origine : `docs/research/ml-scalability-phases/phase-2-augmentation.md`.
- Spec initiale du banc d'éval : `docs/research/ml-scalability-phases/phase-4-subcenter-evalbench.md`.
- Mémoire projet : `project_training_pipeline_refacto.md` (SQLite source de vérité, 1 run = N classes).
