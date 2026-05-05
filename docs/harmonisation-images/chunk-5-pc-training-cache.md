# Chunk 5 — PC training cache run-scoped

> Sur le PC fixe, l'entraînement ne doit jamais bloquer sur le réseau.
> En début de run, on télécharge tous les fichiers nécessaires dans un
> cache local scoped par `run_id`. À la fin (ou au début du run suivant),
> on nettoie. Pré-requis : chunk 3 livré.

## Objectif

À la fin du chunk, un run d'entraînement :

1. Démarre, récupère sa liste d'`image_assets` à utiliser (selon la stratégie de training).
2. Sweep les caches orphelins (runs cancelled / failed) **avant** de pré-fetch.
3. Pré-fetch tous les fichiers vers `~/.cache/eurio/runs/<run_id>/` en parallèle.
4. Lance l'entraînement (PyTorch DataLoader pointe vers ce path).
5. À la fin : `try/finally` qui nettoie ce cache run.

Le PC a typiquement plusieurs centaines de GB de SSD, donc 50–100 GB par run cache est OK.

## Pré-requis

- Chunk 3 livré.
- Module `ml/storage/` avec un client S3 (`boto3` ou `minio-py`) configuré.
- Le runner d'entraînement (`ml/api/training_runner.py` ou équivalent) connaît son `run_id`.

## Décisions à acter

1. **Path du cache** : `~/.cache/eurio/runs/<run_id>/<bucket>/<storage_key>` (préserve la hiérarchie pour debug).
2. **Pool de workers download** : 16 (le PC a probablement plus de CPU + meilleur réseau que le Mac).
3. **Augmentation lit depuis le cache** : oui, l'augmentation est parallélisée dans la pipeline existante et lit déjà depuis disque. Aucun changement de code augmentation.
4. **Inclure les images Numista canoniques dans le cache run-scoped** ? Discussion :
   - Pro : 100% local, jamais bloquant.
   - Contre : Numista canonique change rarement → un cache permanent dédié serait plus efficace.
   - **Reco V1** : on les met dans le cache run-scoped aussi, c'est plus simple. Si ça devient un goulot d'étranglement, on fera un cache Numista permanent en V2.

## Implémentation

### 5.1 Sweep des orphelins

Au démarrage du runner :

```python
# ml/storage/training_cache.py
def sweep_orphan_runs(store: Store, cache_root: Path) -> int:
    """Supprime les caches de runs qui ne sont plus 'running' en DB."""
    if not cache_root.exists():
        return 0
    n_deleted = 0
    for run_dir in cache_root.iterdir():
        if not run_dir.is_dir(): continue
        run_id = run_dir.name
        row = store._connection().execute(
            "SELECT status FROM training_runs WHERE id = ?",
            (run_id,)
        ).fetchone()
        if row is None or row["status"] in ("done", "failed", "cancelled"):
            shutil.rmtree(run_dir)
            n_deleted += 1
    return n_deleted
```

Appelé une fois par `runner.start()`, avant le pre-fetch.

### 5.2 Pre-fetch parallèle

```python
def prefetch_for_run(
    run_id: str,
    storage_keys: list[tuple[str, str]],  # [(bucket, key), ...]
    cache_root: Path,
    workers: int = 16,
) -> Path:
    run_dir = cache_root / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    with ThreadPoolExecutor(max_workers=workers) as pool:
        list(tqdm(
            pool.map(
                lambda bk: _download_one(run_dir, *bk),
                storage_keys
            ),
            total=len(storage_keys),
            desc=f"prefetch run {run_id}",
        ))
    return run_dir
```

Idempotent : `_download_one` skip si le fichier existe déjà avec la bonne taille (pas de sha256 ici, on suppose MinIO immuable côté object store).

### 5.3 Wiring dans le runner

```python
# ml/api/training_runner.py (extrait)
def start_run(self, run_id: str, ...):
    cache_root = Path("~/.cache/eurio/runs").expanduser()
    sweep_orphan_runs(self.store, cache_root)

    # Build asset list selon la stratégie de training
    assets = self._select_training_assets(run_id)
    keys = [(bucket_for_asset(a.source), a.storage_key) for a in assets]

    cache_dir = prefetch_for_run(run_id, keys, cache_root)

    try:
        # PyTorch DataLoader pointe vers cache_dir/<bucket>/<storage_key>
        self._train_with_local_dir(cache_dir, ...)
    finally:
        # Best-effort cleanup ; le sweep du run suivant rattrape si exception
        shutil.rmtree(cache_dir, ignore_errors=True)
```

### 5.4 PyTorch DataLoader path resolution

Helper :
```python
def asset_local_path(cache_dir: Path, bucket: str, storage_key: str) -> Path:
    return cache_dir / bucket / storage_key
```

Le Dataset construit ce path en lieu et place de l'ancien `image_assets.storage_path`.

### 5.5 Tâches go-task

```yaml
ml:cache-runs:list:
  desc: List run caches and sizes
  cmds: [du -sh ~/.cache/eurio/runs/* 2>/dev/null || echo none]
ml:cache-runs:sweep:
  desc: Manually sweep orphan run caches
  cmds: [python -m ml.storage.training_cache sweep]
ml:cache-runs:purge-all:
  desc: Nuke all run caches (use after experiments)
  cmds: [rm -rf ~/.cache/eurio/runs]
  prompt: "Sure ?"
```

## Critères d'acceptation

- [ ] Un run d'entraînement complet tourne contre le cache run-scoped, pas de query MinIO pendant la boucle.
- [ ] Au démarrage d'un run, les caches de runs précédents `done|failed|cancelled` sont nettoyés automatiquement.
- [ ] Si on `Ctrl+C` un run, le cache reste ; le prochain run le nettoie.
- [ ] Pre-fetch sur 10k images < 5 min sur la connexion VPS↔PC (Hetzner ou OVH typique).

## Gotchas

- **Disque plein** : si plusieurs runs s'enchaînent, leurs caches peuvent s'accumuler si le sweep ne marche pas. Garde-fou : avant pre-fetch, vérifier `shutil.disk_usage()` et abort si < 20 GB libre. Affiche un warning clair.
- **Fichiers manquants** : si un asset dispare en MinIO entre la query DB et le pre-fetch (rare, mais possible si quelqu'un a purgé un bucket), le download foire. Le runner doit `raise` → le run start est marqué failed → le sweep du suivant nettoie. Ne pas swallow l'erreur.
- **PyTorch num_workers** : si le DataLoader est en multi-process, plusieurs procs pointent vers le même `cache_dir/...` en read. OK, tant que le pre-fetch est terminé avant le DataLoader.start.
- **Augmentation écrit aussi dans le cache** : oui, l'augmentation crée des fichiers à côté des originaux. Tout vit dans `cache_dir/`. À la fin, on nuke tout.

## Anti-objectifs

- ❌ Pas de cache "global persistent" sur le PC partagé entre runs (sauf cache Numista en V2 si avéré nécessaire).
- ❌ Pas de download streaming pendant le training. Pre-fetch d'abord, training ensuite.
- ❌ Pas de retry policy infinie sur le pre-fetch. 3 retries par fichier, sinon échec du run.
- ❌ Pas de deduplication des fichiers entre runs. Si run A et run B utilisent les mêmes images, elles seront téléchargées 2 fois. Simplicité > économie de bande passante (le réseau VPS↔PC est gratuit dans ce cas).
