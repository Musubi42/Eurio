# Chunk 5 — Pre-fetch run-scoped training

> Sur le PC fixe, l'entraînement ne doit jamais bloquer sur le réseau.
> En début de run, on pré-fetch tous les crops nécessaires dans un cache
> scoped par `run_id`. Sweep des runs morts au démarrage.
> Pré-requis : chunk 4 livré.

## Objectif

À la fin du chunk, un run d'entraînement :

1. Démarre, récupère sa liste de crops à utiliser (training = obverse uniquement, cf. `feedback_training_source_obverse_only`).
2. Sweep les caches orphelins (runs `done|failed|cancelled`) **avant** de pré-fetch.
3. Pré-fetch tous les crops vers `~/.cache/eurio/runs/<run_id>/` en parallèle (réutilise `local_cache.local_path` mais avec `EURIO_CACHE_ROOT` overridé sur le run).
4. Lance l'entraînement (PyTorch DataLoader pointe vers ce path).
5. À la fin (`try/finally`) : `shutil.rmtree(cache_dir, ignore_errors=True)`.

Les augmentations vivent dans `ml/cache/augmentation_sources/<run_id>/` (déjà existant), elles ne sont **jamais** uploadées en S3 (vision §P5).

## Volumétrie réelle

Training actuel = **obverses uniquement**. ~5k coins × ~200 KB ≈ **1 GB par run**, pas 50 GB. Le pré-fetch est rapide même sur connexion VPS↔PC modeste.

Si jamais on entraîne aussi sur les crops scrapés (futur), recalibrer.

## Pré-requis

- Chunk 4 livré (lib `ml/storage/local_cache.py`).
- Le runner d'entraînement connaît son `run_id` et sa liste d'assets.

## Décisions actées

1. **Cache root override par run** : `EURIO_CACHE_ROOT=~/.cache/eurio/runs/<run_id>` au moment du pré-fetch, pour réutiliser exactement la même lib que le Mac (zéro duplication de code).
2. **Workers** : 16 (PC a plus de CPU + meilleur réseau).
3. **Sweep** : compare les dossiers `~/.cache/eurio/runs/*` aux runs `running` en DB, supprime tout le reste.
4. **Cleanup post-run** : `try/finally` rmtree. Si crash, le sweep du run suivant rattrape.

## Implémentation

### 5.1 Sweep des orphelins

```python
# ml/storage/training_cache.py
import shutil
from pathlib import Path
from ml.state.store import Store

def sweep_orphan_runs(store: Store, runs_root: Path) -> int:
    """Supprime les caches de runs qui ne sont plus 'running' en DB."""
    if not runs_root.exists():
        return 0
    n = 0
    for run_dir in runs_root.iterdir():
        if not run_dir.is_dir():
            continue
        run_id = run_dir.name
        row = store._connection().execute(
            "SELECT status FROM training_runs WHERE id = ?", (run_id,),
        ).fetchone()
        if row is None or row["status"] in ("done", "failed", "cancelled"):
            shutil.rmtree(run_dir, ignore_errors=True)
            n += 1
    return n
```

### 5.2 Pre-fetch parallèle

```python
import os
from concurrent.futures import ThreadPoolExecutor
from tqdm import tqdm
from ml.storage.local_cache import local_path

def prefetch_for_run(
    run_id: str,
    items: list[tuple[str, str]],   # [(bucket, storage_key), ...]
    runs_root: Path,
    workers: int = 16,
) -> Path:
    run_dir = runs_root / run_id
    # Override le cache root pour ce run uniquement
    os.environ["EURIO_CACHE_ROOT"] = str(run_dir)
    os.environ["EURIO_CACHE_MAX_GB"] = "0"   # unbounded inside the run
    # Reset le client S3 module-level si déjà instancié dans un autre contexte
    # (en pratique le runner tourne dans son propre process).

    with ThreadPoolExecutor(max_workers=workers) as pool:
        list(tqdm(
            pool.map(lambda bk: local_path(bk[0], bk[1]), items),
            total=len(items),
            desc=f"prefetch run {run_id}",
        ))
    return run_dir
```

### 5.3 Wiring dans le runner

```python
# ml/api/training_runner.py
from pathlib import Path
import shutil

def start_run(self, run_id: str, ...):
    runs_root = Path("~/.cache/eurio/runs").expanduser()
    sweep_orphan_runs(self.store, runs_root)

    assets = self._select_training_assets(run_id)   # obverses only
    items = [(bucket_for_asset(a.source), a.storage_path) for a in assets]

    cache_dir = prefetch_for_run(run_id, items, runs_root)

    try:
        # PyTorch DataLoader résout via local_path() qui hit le cache run-scoped
        self._train_with_local(cache_dir, ...)
    finally:
        shutil.rmtree(cache_dir, ignore_errors=True)
```

### 5.4 Disque garde-fou

Avant pre-fetch :

```python
import shutil as sh
free_gb = sh.disk_usage(runs_root).free / 1024**3
if free_gb < 5:
    raise RuntimeError(f"Disk free {free_gb:.1f}GB < 5GB safety threshold")
```

### 5.5 Tâches go-task

```yaml
ml:cache-runs:list:
  desc: List run caches and sizes
  cmds: [du -sh ~/.cache/eurio/runs/* 2>/dev/null || echo none]
ml:cache-runs:sweep:
  desc: Manually sweep orphan run caches
  cmds: [python -m ml.storage.training_cache sweep]
ml:cache-runs:purge-all:
  desc: Nuke all run caches
  cmds: [rm -rf ~/.cache/eurio/runs]
  prompt: "Sure ?"
```

## Critères d'acceptation

- [ ] Run training complet tourne contre le cache run-scoped, 0 query MinIO pendant la boucle
- [ ] Au démarrage d'un run, les caches `done|failed|cancelled` sont purgés
- [ ] Si on `Ctrl+C` un run, le cache reste ; le prochain run le nettoie
- [ ] Pre-fetch sur ~5k crops < 1 min sur réseau VPS↔PC standard
- [ ] Disque garde-fou abort si < 5 GB libre

## Gotchas

- **Augmentations** : produites dans `ml/cache/augmentation_sources/<run_id>/`, lues depuis ce path par le DataLoader. Pas dans le run-cache S3, pas dans le sweep. Cycle de vie séparé (et déjà géré par le code training existant).
- **DataLoader multi-process** : si `num_workers > 0`, plusieurs procs lisent `cache_dir/...` en read. OK tant que le pre-fetch est fini avant `DataLoader.start()`.
- **Asset dispare en MinIO entre query DB et pre-fetch** : `local_path` raise → run failed → sweep rattrape. Ne pas swallow.
- **Reset du client boto3 dans le runner** : le module-level `_s3` peut hériter d'un autre cache root si réutilisé. En pratique le runner tourne dans son propre process — pas de souci. Si jamais tests in-process : appeler `ml.storage.local_cache._s3 = None` après reset env.

## Anti-objectifs

- ❌ Pas de cache "global persistent" inter-runs sur le PC. Chaque run a son cache, jeté à la fin.
- ❌ Pas de download streaming pendant le training. Pre-fetch d'abord, training ensuite.
- ❌ Pas de retry policy infinie sur le pre-fetch. boto3 retry par défaut (3), au-delà → fail run.
- ❌ Pas de dedup inter-runs. Si run A et B téléchargent le même asset, c'est OK — coût négligeable, complexité évitée.
