# PRD Bloc 3 — Notes d'implémentation (2026-04-19)

> Résumé de la session qui a livré le banc d'éval real-photo. À lire pour reprendre une itération sur le banc, ou avant d'attaquer la première campagne de shooting + bench complet.

## Ce qui a été livré

### SQL + Store (extension `training.db`)

| Fichier | Changement |
|---|---|
| `ml/state/schema.sql` | Table `benchmark_runs` + 4 indexes. FK vers `training_runs.id` et `augmentation_recipes.id` (ON DELETE SET NULL). |
| `ml/state/store.py` | `BenchmarkRunRow` dataclass ; `create_benchmark_run`, `update_benchmark_run`, `get_benchmark_run`, `list_benchmark_runs` (filtres model/recipe/zone via LIKE sur JSON), `count_benchmark_runs`, `delete_benchmark_run`. Row-to-dataclass helper `_row_to_benchmark_run`. |
| `ml/state/__init__.py` | Re-export `BenchmarkRunRow`. |

### Scripts Python

| Fichier | Rôle |
|---|---|
| `ml/check_real_photos.py` | Valide `ml/data/real_photos/` (extensions, résolution ≥ 800×800, ≥ 2 sessions distinctes via (lighting, background)), écrit `_manifest.json`. Zones résolues via Supabase `coin_confusion_map` si dispo — silent-fail sinon. CLI `--strict` pour exit 1. |
| `ml/evaluate_real_photos.py` | Benchmark engine. Charge `.pth` (`TorchEmbedder`) ou `.tflite` (`TFLiteEmbedder`), YOLO crop via `ml/output/detection/coin_detector/weights/best.pt` (fallback centre-crop), matche contre les centroïdes de `embeddings_v1.json`. Semantic `Centroid.covers()` — un centroïde `design_group_id` couvre tous ses membres `eurio_id`. Persistance SQLite + rapport JSON `ml/reports/benchmark_<model>_<run_id>.json`. |
| `ml/train_embedder.py` | Gate `_assert_no_real_photos(path, role)` appelé sur `--dataset` + `--val-dataset`. |
| `ml/prepare_dataset.py` | Même gate sur `--raw-dir` + `--output-dir`. |

### FastAPI + routing

| Fichier | Changement |
|---|---|
| `ml/api/benchmark_routes.py` | **nouveau** — router `/benchmark/*`. Endpoints livrés : `GET /library`, `GET /photos/{eurio_id}`, `GET /photos/thumbnail/{path:path}`, `POST /run`, `GET /runs`, `GET /runs/{id}`, `GET /runs/{id}/report`, `DELETE /runs/{id}`. Subprocess runner (thread daemon) + hold-out path validation. Thumbnails hashés TTL 24h. |
| `ml/api/server.py` | `include_router(benchmark_routes.router)` + `bind(store)` + startup hook `cleanup_expired_thumbnails()`. |

### Commandes go-task

| Tâche | Description |
|---|---|
| `ml:benchmark` | Lance `evaluate_real_photos.py {{.CLI_ARGS}}`. |
| `ml:benchmark:photos:check` | Lance `check_real_photos.py {{.CLI_ARGS}}`. |

### Admin Vue

| Fichier | Rôle |
|---|---|
| `admin/packages/web/src/features/benchmark/types.ts` | `BenchmarkRunSummary`, `BenchmarkRunDetail`, `BenchmarkLibrary`, etc. |
| `admin/packages/web/src/features/benchmark/composables/useBenchmarkApi.ts` | Wrappers fetch pour `/benchmark/*` + `thumbnailUrl()`. |
| `admin/packages/web/src/features/benchmark/pages/BenchmarkPage.vue` | Page racine — status ML API, résumé bibliothèque, filtres model/zone, table historique, compare toggle, modal Nouveau run. |
| `.../pages/BenchmarkRunDetailPage.vue` | Drill-down — cartes métriques, R@k par zone, par pièce, heatmap confusion, top-N confusions avec thumbnails. |
| `.../pages/BenchmarkComparePage.vue` | A vs B — métriques globales, par zone, par pièce avec delta coloré (vert/rouge). |
| `admin/packages/web/src/app/router.ts` | Routes lazy `/benchmark`, `/benchmark/runs/:id`, `/benchmark/compare`. |
| `admin/packages/web/src/app/nav.ts` | Entrée "Benchmark" (icône `TrendingUp`) dans la section Outils. |

### Gitignore

`.gitignore` bloque `ml/data/real_photos/` et `ml/reports/` — ne **jamais** committer les photos réelles (cf. R1 strict hold-out).

### Tests

| Fichier | Tests |
|---|---|
| `ml/tests/test_benchmark.py` | Store CRUD, filtres list, gate hold-out, `check_real_photos` (sessions + résolution), `_aggregate` (R@k, top-confusions, per_zone), semantics `Centroid.covers()`, `match_topk`. |
| `ml/tests/test_benchmark_api.py` | `/library`, `/photos/{eurio_id}`, thumbnail JPEG + path-traversal guard via validator, `/run` (missing model, invalid zone, launched background), list filters, detail + delete. `_launch_run` monkeypatché pour éviter les subprocess en test. |

**47/47 tests passent** (`cd ml && .venv/bin/python -m pytest tests/ -q`).

## Contrats figés — ne pas changer sans bump explicite

### Shape `benchmark_runs` (SQLite)

- `id TEXT PK` (uuid hex 12)
- `model_path TEXT`, `model_name TEXT`
- `training_run_id TEXT?` FK → `training_runs.id`
- `recipe_id TEXT?` FK → `augmentation_recipes.id`
- `eurio_ids_json`, `zones_json` (JSON lists)
- `num_photos`, `num_coins`
- `r_at_1`, `r_at_3`, `r_at_5`, `mean_spread`
- `per_zone_json`, `per_coin_json`, `confusion_json`, `top_confusions_json`
- `report_path TEXT`
- `status` ∈ `running|completed|failed`
- `error TEXT?`
- `started_at` (default `datetime('now')`), `finished_at`

### Shape `POST /benchmark/run` body

```jsonc
{
  "model_path": "ml/checkpoints/best_model.pth",  // absolue OU relative au repo
  "eurio_ids": ["fr-2007-2eur-standard"],         // optional
  "zones": ["green", "orange"],                   // optional
  "recipe_id": "green-v2",                         // optional — id ou name
  "run_id": "my-run",                              // optional — sinon uuid
  "top_confusions": 20
}
```

Retour immédiat : `{ run_id, status: "running" }`. Le dev poll `GET /benchmark/runs/{run_id}`.

### Shape du rapport JSON

```jsonc
{
  "run_id", "model_path", "model_name", "recipe_id",
  "started_at", "finished_at", "duration_ms",
  "num_photos", "num_coins", "zones",
  "metrics": { "r_at_1", "r_at_3", "r_at_5", "mean_spread", "median_spread" },
  "per_zone": { "green": { "r_at_1", "r_at_3", "r_at_5", "num_photos" }, ... },
  "per_coin": [ { "eurio_id", "zone", "num_photos", "r_at_1", "r_at_3", "r_at_5" } ],
  "confusion_matrix": { "<eurio_id>": { "<class_id>": int } },
  "top_confusions": [ { "photo_path", "ground_truth", "zone", "spread", "top_3" } ]
}
```

### Convention photos réelles

- Root : `ml/data/real_photos/<eurio_id>/*.{jpg,jpeg,png}`
- Résolution min : 800×800
- Filename best-effort parsé pour tokens `lighting` / `background` / `angle` dans les vocabulaires de `real-photo-criteria.md`. Les tokens inconnus sont ignorés — le script est tolérant.
- Session = clé synthétisée `(lighting, background)` ; flag < 2 sessions via le validator.
- `_manifest.json` à la racine, **pas versionné**.

## Ce qui reste pour démarrer la campagne

Côté code, rien. Côté workflow dev :

1. Prendre les photos selon `real-photo-criteria.md` — 5-10 pièces par zone, 5-10 photos par pièce.
2. `go-task ml:benchmark:photos:check` pour valider + générer `_manifest.json`.
3. Entraîner un modèle par zone (via le Studio + handoff training Bloc 2).
4. `go-task ml:benchmark -- --model checkpoints/<ckpt>.pth --zones <zone>` OU via la modal "Nouveau run" dans `/benchmark`.
5. Consulter les métriques dans `/benchmark`, drill-down sur un run, comparer A vs B après chaque tweak.

## Points d'attention & dette identifiée

- **YOLO detector optionnel** : si `ml/output/detection/coin_detector/weights/best.pt` est absent, le bench fallback sur centre-crop. Pour des photos au cadrage serré (`close`), aucun impact. Pour des photos `medium`/`far`, la détection devient critique — vérifier que le détecteur est en place avant la campagne.
- **CPU par défaut** : `TorchEmbedder` force `torch.device("cpu")`. OK pour 150-300 photos (~30s). Si la library grossit à > 1000 photos, passer sur MPS/CUDA comme option CLI.
- **Matrice de confusion tabulée côté Vue** : rendu simple (couleur bg = intensité), pas de tooltip au hover ni synchronisation en mode compare. Suffit pour v1 ; à iterer si des diffs deviennent difficiles à lire.
- **Compare binaire uniquement** : 2 runs côte à côte, sélection via checkbox dans la table. N > 2 = v2.
- **`training_run_id` non rempli en v1** : le script `evaluate_real_photos.py` ne lie pas automatiquement le run de bench au training_run qui a produit le checkpoint. Pour l'instant, remontage manuel via `recipe_id` (qui pointe sur la recette ayant produit le training qui a produit le modèle). TODO : résoudre `training_run_id` depuis le chemin du checkpoint si convention claire.
- **Thumbnails ne reprennent pas quand une photo change** : le cache est busté via `mtime` (regen si source plus récente), mais si on renomme une photo, l'ancien thumbnail reste sur disque jusqu'au cleanup TTL 24h. Non bloquant.
- **Subprocess sans stream live** : les logs de `evaluate_real_photos.py` sont capturés en fin de run, pas streamés. Pour une bibliothèque de 300 photos (~60s), le dev n'a pas de feedback progressif. À voir si on ajoute un status-file comme `confusion_map.py` le fait.
- **Zone filter via LIKE sur JSON** : `list_benchmark_runs(zone=…)` fait `zones_json LIKE '%"green"%'` — faux positif théorique si un eurio_id s'appelle littéralement `green`. Acceptable en pratique ; passer sur JSON1 si la vol devient un problème.

## Comment vérifier l'état du Bloc 3

```bash
# 1. Tests passent
cd ml && .venv/bin/python -m pytest tests/ -q

# 2. Migration appliquée
cd ml && .venv/bin/python -c "
from state import Store; from pathlib import Path
s = Store(Path('state/training.db'))
c = s._connection()
print('benchmark_runs:', c.execute(\"SELECT count(*) FROM sqlite_master WHERE type='table' AND name='benchmark_runs'\").fetchone()[0] == 1)
"

# 3. Endpoints enregistrés
cd ml && .venv/bin/python -c "
import sys; sys.path.insert(0, '.')
from api.server import app
print('\n'.join(sorted([r.path for r in app.routes if '/benchmark' in getattr(r, 'path', '')])))
"

# 4. go-task
go-task --list-all | grep benchmark

# 5. Smoke test bout en bout (sans photos réelles — centre-crop)
cd ml && go-task ml:benchmark:photos:check
```

## Références croisées

- [`PRD01-implementation-notes.md`](./PRD01-implementation-notes.md) — pipeline backend + contrats API.
- [`PRD02-implementation-notes.md`](./PRD02-implementation-notes.md) — Studio admin + handoff training.
- [`03-real-photo-benchmark.md`](./03-real-photo-benchmark.md) — PRD original.
- [`real-photo-criteria.md`](./real-photo-criteria.md) — convention de shooting.
- Mémoire projet : `project_training_pipeline_refacto.md`, `project_arcface_design_group_label.md`.
