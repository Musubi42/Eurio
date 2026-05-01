# Phase 5 — Training monitor live (epoch · loss · ETA · log tail)

> Pré-requis : phases 1-4 livrées. La carte runtime existe dans I3, le
> bake produit un manifest, et le subprocess de training log un
> `RUNTIME {...}` au boot. Avoir lu `TrainingRunner._train` et
> `ActiveState`.
>
> Sortie : pendant un training, le tiroir I3 affiche en temps réel
> l'epoch, la loss, l'ETA, le device runtime confirmé, et le tail du
> log subprocess. Plus de spinner aveugle.

## Stratégie

Deux sources d'info qu'on combine côté backend :

1. **Le fichier `ml/state/training_progress/<iid>.json`**, écrit par
   `train_embedder.py` lui-même à chaque epoch. Source structurée,
   rapide à parser.
2. **Le tail in-memory** de `ActiveState.log_lines` (déjà accumulé par
   `TrainingRunner._run_subprocess`). Source brute, pour debug.

Le front consomme un endpoint unique
`GET /lab/runner/training-progress/<iid>` qui agrège les deux.

## Backend

### B1 — `train_embedder.py` écrit le progress sur disque

**Fichier** : `ml/training/train_embedder.py` mode arcface
(ligne 730+).

Ajouter au début du training :

```py
import json
import time
from pathlib import Path

PROGRESS_DIR = Path(__file__).resolve().parent.parent / "state" / "training_progress"

def _write_progress(iteration_id: str | None, payload: dict) -> None:
    if not iteration_id:
        return
    PROGRESS_DIR.mkdir(parents=True, exist_ok=True)
    tmp = PROGRESS_DIR / f"{iteration_id}.json.tmp"
    final = PROGRESS_DIR / f"{iteration_id}.json"
    tmp.write_text(json.dumps(payload), encoding="utf-8")
    tmp.replace(final)  # atomic on POSIX
```

L'`iteration_id` est passé via un nouvel arg `--iteration-id` au
subprocess. **L'iteration_runner doit l'injecter** (cf B3).

À la fin de chaque epoch (ligne 765+ pour arcface), écrire :

```py
elapsed = time.time() - training_started_at
mean_epoch_s = elapsed / epoch
eta = mean_epoch_s * (args.epochs - epoch)
_write_progress(args.iteration_id, {
    "schema_version": 1,
    "iteration_id": args.iteration_id,
    "phase": "training",
    "epoch_current": epoch,
    "epochs_total": args.epochs,
    "loss_current": round(avg_loss, 4),
    "loss_best": round(best_loss, 4),
    "started_at": training_started_iso,
    "elapsed_seconds": int(elapsed),
    "eta_seconds": int(eta),
    "device": str(device),
    "augmentations_runtime": "disabled" if args.prebaked_augmentations else "legacy_compose",
    "updated_at": _iso_now(),
})
```

À la fin du training : écrire un dernier payload avec
`phase="training_done"`. Le runner repassera ensuite à `phase="export"`
et `phase="benchmark"` via le runner orchestration.

### B2 — Le runner met à jour les phases hors training

**Fichier** : `ml/api/iteration_runner.py`

Quand le runner passe à une nouvelle phase (export TFLite, benchmark),
il écrit lui-même dans le même fichier :

```py
def _set_progress_phase(self, iteration_id: str, phase: str) -> None:
    fp = ML_DIR / "state" / "training_progress" / f"{iteration_id}.json"
    payload = {}
    if fp.exists():
        try:
            payload = json.loads(fp.read_text())
        except Exception:
            payload = {}
    payload.update({
        "phase": phase,
        "updated_at": _iso_now(),
    })
    fp.parent.mkdir(parents=True, exist_ok=True)
    tmp = fp.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload))
    tmp.replace(fp)
```

Appelé dans `_chain_steps` aux transitions :
- avant `_launch_training` : `phase="bake"`
- entre training et export : `phase="export"`
- entre export et benchmark : `phase="benchmark"`
- à la fin : `phase="done"` (ou suppression du fichier si
  `iteration.status='completed'`)

### B3 — Pass `--iteration-id` au subprocess

**Fichier** : `ml/api/training_runner.py:_train`

Ajouter dans le `cmd` :

```py
cmd.extend(["--iteration-id", iteration_id_or_empty_string])
```

Récupérer `iteration_id` depuis `cfg["iteration_id"]` que le
`IterationRunner._launch_training` doit setter dans le config dict.

**Fichier** : `ml/api/iteration_runner.py:_launch_training` ligne 380.

```py
config["iteration_id"] = iteration.id
```

**Fichier** : `ml/training/train_embedder.py` argparser :

```py
parser.add_argument("--iteration-id", type=str, default=None)
```

Quand `None`, le `_write_progress` no-op (path legacy `/training/run`
direct, pas d'iteration).

### B4 — Endpoint `GET /lab/runner/training-progress/<iid>`

**Fichier** : `ml/api/lab_routes.py`

```py
@router.get("/runner/training-progress/{iid}")
def runner_training_progress(iid: str) -> dict:
    fp = _ML_DIR / "state" / "training_progress" / f"{iid}.json"
    payload: dict = {}
    if fp.exists():
        try:
            payload = json.loads(fp.read_text())
        except Exception:
            payload = {"error": "progress file unreadable"}
    # Tail des logs du subprocess actif
    runner = _get_training_runner()  # via app.state ou DI
    log_tail: list[str] = []
    snap = runner.active_snapshot()
    if snap and snap.get("run_id"):
        # ActiveState.log_lines est private — exposer via une méthode publique tail()
        log_tail = runner.tail_logs(n=30)
    payload["log_tail"] = log_tail
    return payload
```

**Côté `TrainingRunner`** : ajouter une méthode `tail_logs(n: int) -> list[str]` qui retourne les N dernières lignes de `_active.log_lines` thread-safe.

### B5 — Cleanup du fichier progress

À la fin du chain (succès ou échec), `iteration_runner` peut
supprimer le fichier `training_progress/<iid>.json` ou le laisser
en place (utile pour debug). **Recommandation v1** : laisser en
place mais avec `phase="done"` ou `phase="failed"`. La purge se fait
via le sprint 5 GC déjà existant (purge iteration → cascades).

## Frontend

### F1 — Composant `TrainingMonitor.vue`

**Fichier** : `admin/packages/web/src/features/lab/components/TrainingMonitor.vue`

**Props** : `iterationId`, `iteration` (pour les fallbacks).

**Body** :

```
┌───────────────────────────────────────────────────────────────┐
│ Phase: training                          [🔴 Stopper]         │
│                                                               │
│ Device confirmé: mps:0 (Apple M3)                             │
│ Augmentations runtime: disabled (bake-only)                   │
│                                                               │
│ Epoch 12 / 40  ████████████░░░░░░░░░░░░░░  30%               │
│ Loss : 0.8421  Best : 0.8102                                  │
│ Temps : 4 min 23 s  · ETA : ~10 min                           │
│                                                               │
│ ▼ Logs (30 dernières lignes)                                  │
│ ─────────────────────────────────                             │
│ [hh:mm:ss]   Epoch 11/40 — loss: 0.8512 ...                  │
│ [hh:mm:ss]   Epoch 12/40 — starting                           │
│ [hh:mm:ss] TENSOR_CHECK model.device=mps:0                    │
│ ...                                                           │
└───────────────────────────────────────────────────────────────┘
```

**Phases possibles dans le payload** : `bake`, `training`,
`training_done`, `export`, `benchmark`, `done`, `failed`. Affichage
adapté :

- `bake` : "Bake en cours…" (devrait être éphémère)
- `training` : full monitor comme ci-dessus
- `training_done` / `export` : "Export TFLite en cours…" + spinner
- `benchmark` : "Benchmark en cours…" + spinner
- `done` : recap (caché dès que I3 passe à state ready, on bascule sur
  le summary post-training)
- `failed` : message d'erreur extrait du payload + bouton Retry

### F2 — Polling

```ts
export function useTrainingProgressQuery(iterationId: Ref<string>, status: Ref<string>) {
  return useQuery({
    queryKey: [...LAB_KEYS.runner, 'training-progress', iterationId.value],
    queryFn: () => fetchTrainingProgress(iterationId.value),
    refetchInterval: () => {
      const s = status.value
      if (['training','benchmarking'].includes(s)) return 2000
      return false  // off
    },
    enabled: computed(() => ['training','benchmarking'].includes(status.value)),
  })
}
```

### F3 — Intégration dans `IterationDrawerI3.vue`

Quand `iteration.status === 'training'` ou `'benchmarking'`, afficher
`<TrainingMonitor :iterationId="iid" :iteration="iteration" />`. Sinon,
afficher la carte runtime + bouton (statu quo phase 4).

### F4 — Types

```ts
export interface TrainingProgress {
  schema_version: number
  iteration_id: string
  phase: 'bake' | 'training' | 'training_done' | 'export' | 'benchmark' | 'done' | 'failed'
  epoch_current?: number
  epochs_total?: number
  loss_current?: number
  loss_best?: number
  started_at?: string
  elapsed_seconds?: number
  eta_seconds?: number
  device?: string
  augmentations_runtime?: 'disabled' | 'legacy_compose'
  updated_at?: string
  log_tail: string[]
  error?: string
}
```

## Critère de succès

1. Lancer un training réel sur une iteration ; pendant le run :
   - `cat ml/state/training_progress/<iid>.json` montre un payload
     qui s'incrémente epoch par epoch.
   - `curl /lab/runner/training-progress/<iid>` retourne le payload
     + un `log_tail` non vide.
   - Le composant `TrainingMonitor` affiche epoch courant, loss, ETA
     qui se mettent à jour toutes les 2s sans refresh manuel.
   - Le `device` affiché correspond à ce que la carte runtime annonçait
     avant le lancement (cohérence phase 4 ↔ phase 5).
   - `augmentations_runtime: "disabled"` (cohérence phase 3).
2. Pendant le benchmark : monitor affiche "phase: benchmark", pas
   d'epoch (le benchmark n'a pas d'epoch).
3. Stop pendant le training : monitor affiche `phase: failed` avec
   message "Stopped by user (graceful)". Iteration passe en `failed`,
   tiroir I3 redevient lockable (state `partial`).
4. Après succès complet : monitor disparaît au profit du recap
   `iteration.training_summary` (durée, epochs, best loss).
5. Pas de fuite mémoire : le fichier progress est <1KB par iteration,
   le log_tail in-memory plafonne à N lignes (TrainingRunner gère
   déjà ça via list de strings — vérifier le cap).

## Pièges connus

- **Race condition sur le rename** : sur Windows le `tmp.replace(final)`
  peut foirer si le fichier est ouvert ailleurs. On ne supporte pas
  Windows nativement (le user est sur Mac+Linux), donc ignoré.
- **Multi-line stdout** : `train_embedder.py` print en plusieurs
  lignes par epoch. Le regex côté `TrainingRunner._run_subprocess`
  est déjà OK pour parser les `Epoch [N/total] loss: ...`. Mais pour
  v1 on n'a pas besoin de regex côté runner — c'est `train_embedder.py`
  lui-même qui écrit le JSON, le runner se contente d'accumuler les
  lignes.
- **Le fichier progress survit aux crashes** : si le subprocess
  crash entre deux epochs, le payload reste figé sur la dernière
  epoch écrite. Le `iteration.status` passera à `failed` et le front
  affichera "phase: failed" en se basant sur le status iteration,
  pas sur le payload. OK.
- **Le polling 2s génère ~30 req/min par iteration** ouverte. Single
  user, négligeable. Si on en a marre des req, passer à SSE plus
  tard.
- **`refetchInterval` qui change** : TanStack Query doit recevoir une
  fonction (pas une valeur), c'est ce que la signature ci-dessus
  fait. Vérifier que le Vue Query (TanStack) supporte la function
  form (oui depuis v5).

## Hors-scope

- Pas de **graphe loss curve** dans la v1. Just la valeur courante
  + best. Si on veut, le store a déjà la table `epochs` qu'on peut
  consulter post-run.
- Pas de **persistence du log tail** (in-memory uniquement, perdu au
  restart API). Statu quo `TrainingRunner.load_logs` qui lit l'archive
  post-run pour le passé.
- Pas d'**alerts auto** (loss qui diverge, etc.). v1 = juste afficher.
- Pas de **WebSocket / SSE**. Polling HTTP suffit.
