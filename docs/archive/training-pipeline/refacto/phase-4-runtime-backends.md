# Phase 4 — Runtime backends visibles (Mac M3 vs PC + 1080 Ti)

> Pré-requis : phases 1-2 livrées (la coquille `IterationDrawerI3.vue`
> existe et a un placeholder pour la "carte runtime"). Avoir lu le
> `get_device("auto")` de `train_embedder.py:363`.
>
> Sortie : un module unique `ml/training/runtime.py`, un endpoint
> `/lab/runner/runtime-info`, un bandeau global sur `/lab`, et la
> carte runtime active dans I3 avant lancement.

## Pourquoi

L'utilisateur tourne sur deux machines :

- **Mac M3** (darwin-arm64) — backend MPS, plus lent mais toujours dispo
- **PC** (linux-x86_64) avec **NVIDIA GeForce GTX 1080 Ti** — backend
  CUDA, sensiblement plus rapide

Aujourd'hui `train_embedder.py:get_device("auto")` choisit correctement
mais log juste `Mode: arcface | Device: mps`. Le front ne sait rien.
Pour ne pas se faire avoir par un fallback CPU silencieux ou un
cuda manquant après un upgrade, il faut **rendre le runtime visible
en permanence**, **avant** de lancer un run.

## Backend

### B1 — Module `ml/training/runtime.py` (nouveau)

**Fichier** : `ml/training/runtime.py`

```py
"""Runtime detection — single source of truth for hardware/backend info.

Used by:
  - train_embedder.py at boot, to log structured info
  - lab_routes.py via /lab/runner/runtime-info, to surface in the UI
  - iteration_runner.py to pick num_workers etc.
"""

from __future__ import annotations
import platform
from dataclasses import dataclass, asdict


@dataclass(frozen=True)
class RuntimeInfo:
    host_os: str            # 'darwin' | 'linux' | 'windows'
    arch: str               # 'arm64' | 'x86_64'
    cpu_brand: str          # best-effort: "Apple M3", "Intel Core i9-..."
    torch_version: str
    backend: str            # 'cuda' | 'mps' | 'cpu'
    device: str             # 'cuda:0' | 'mps:0' | 'cpu'
    num_cuda_devices: int
    gpu_name: str | None    # 'NVIDIA GeForce GTX 1080 Ti' or None
    cuda_version: str | None
    dataloader_workers: int # 4 on cuda, 0 on mps/cpu (matches train_embedder.py)
    hint: str               # human one-liner: "PC + 1080 Ti (CUDA 12.1) — fast"


def detect() -> RuntimeInfo: ...
def to_dict(info: RuntimeInfo) -> dict: ...
```

**Implémentation `detect()`** :
- `host_os = platform.system().lower()`
- `arch = platform.machine().lower()`
- `cpu_brand = _detect_cpu_brand()` — sur darwin, `sysctl -n
  machdep.cpu.brand_string` ; sur linux, `/proc/cpuinfo` ; fallback
  `platform.processor()`
- `torch_version = torch.__version__`
- `backend` :
  - `'cuda'` si `torch.cuda.is_available()`
  - sinon `'mps'` si `torch.backends.mps.is_available()`
  - sinon `'cpu'`
- `device` : `'cuda:0'` / `'mps:0'` / `'cpu'`
- `num_cuda_devices = torch.cuda.device_count() if cuda else 0`
- `gpu_name = torch.cuda.get_device_name(0) if cuda else None`
- `cuda_version = torch.version.cuda if cuda else None`
- `dataloader_workers`: 4 si cuda, 0 sinon (= statu quo
  `train_embedder.py:400`)
- `hint` : composé en clair :
  - `"Apple M3 (mps) — slower, OK for iterating"` sur darwin-arm64+mps
  - `"PC + NVIDIA GeForce GTX 1080 Ti (CUDA 12.1) — fast"` sur linux+cuda
  - `"CPU only — very slow, last resort"` sur cpu

**Cache** : `detect()` est rapide mais on peut mémo (lru_cache(1))
parce que rien ne change pendant la durée du process API.

### B2 — `train_embedder.py` utilise `runtime.py`

**Fichier** : `ml/training/train_embedder.py`

Remplacer `get_device(device_str)` par un appel à `runtime.detect()`,
gardant la possibilité d'override via `--device cpu` (utile pour tests
locaux). Et logger en JSON :

```py
from runtime import detect as detect_runtime

info = detect_runtime()
device = torch.device(args.device) if args.device != "auto" else torch.device(info.device)
print("RUNTIME " + json.dumps(asdict(info)), flush=True)
```

(Cette ligne s'ajoute à celle de phase 3 B2 — on peut combiner les deux
en un seul payload, c'est plus propre.)

### B3 — Endpoint `GET /lab/runner/runtime-info`

**Fichier** : `ml/api/lab_routes.py`

Position : juste à côté de `runner/status` (ligne 1048).

```py
@router.get("/runner/runtime-info")
def runner_runtime_info() -> dict:
    from training.runtime import detect, to_dict
    return to_dict(detect())
```

**Note** : ce calcul est local au process FastAPI — même backend que
celui qui sera utilisé pour les subprocess de training (qui héritent
du venv et donc des mêmes versions torch). Donc l'info est fiable.

### B4 — Lien runtime ↔ training_runner

**Fichier** : `ml/api/training_runner.py`

`TrainingRunner._train` passe `--device {info.device}` au subprocess
(au lieu de `--device auto`) pour explicit-typer dans le log. C'est
optionnel — `auto` fait déjà le bon choix. **Skip si on veut éviter
le risque** : la phase 5 logguera de toute façon le `RUNTIME` JSON
émis par le subprocess.

## Frontend

### F1 — Composant `RuntimeBadge.vue`

**Fichier** : `admin/packages/web/src/features/lab/components/RuntimeBadge.vue`

**Props** : `compact?: boolean` (compact pour le bandeau, full pour la
carte I3).

**Modes d'affichage** :

- **Compact** (bandeau) :
  ```
  [icon] PC + 1080 Ti (cuda:0)
  ```
  Couleur fond : vert si cuda, jaune si mps, rouge si cpu.

- **Full** (carte I3) :
  ```
  ┌─────────────────────────────────────────────────────┐
  │ [icon] Runtime de cette machine                     │
  │                                                     │
  │ Hôte         linux x86_64                           │
  │ CPU          Intel Core i7-7700K                    │
  │ Torch        2.5.1+cu121                            │
  │ Backend      CUDA                                   │
  │ Device       cuda:0                                 │
  │ GPU          NVIDIA GeForce GTX 1080 Ti             │
  │ Workers      4                                      │
  │                                                     │
  │ → PC + 1080 Ti (CUDA 12.1) — fast                  │
  └─────────────────────────────────────────────────────┘
  ```

### F2 — Bandeau global sur `/lab`

**Fichier** : `pages/LabHomePage.vue`

Ajouter `<RuntimeBadge compact />` en haut de la page, **avant** le
DashboardSection. Le bandeau est toujours visible.

```vue
<template>
  <div class="page">
    <header>
      <h1>Lab</h1>
      <RuntimeBadge compact />
    </header>
    <DashboardSection />
    <CohortsList />
  </div>
</template>
```

### F3 — Carte runtime dans I3 (avant lancement)

**Fichier** : `IterationDrawerI3.vue` (créé en phase 2 avec
placeholder).

Quand `iteration.status === 'pending'` et I2 est `ready` :

```vue
<template>
  <DrawerSection :state="state" :title="...">
    <template #body>
      <RuntimeBadge />
      <p class="text-sm muted">
        Le training tournera sur ce matos. Vérifie que c'est ce que tu attends.
      </p>
      <button @click="launch">Lancer training</button>
    </template>
  </DrawerSection>
</template>
```

### F4 — Composables

**Fichier** : `useLabApi.ts`

```ts
export async function fetchRuntimeInfo(): Promise<RuntimeInfo>
```

**Fichier** : `useLabQueries.ts`

```ts
export function useRuntimeInfoQuery() {
  return useQuery({
    queryKey: [...LAB_KEYS.runner, 'runtime-info'],
    queryFn: fetchRuntimeInfo,
    staleTime: 1000 * 60 * 60, // 1h — runtime ne change pas pendant une session
  })
}
```

### F5 — Types

```ts
export interface RuntimeInfo {
  host_os: string
  arch: string
  cpu_brand: string
  torch_version: string
  backend: 'cuda' | 'mps' | 'cpu'
  device: string
  num_cuda_devices: number
  gpu_name: string | null
  cuda_version: string | null
  dataloader_workers: number
  hint: string
}
```

## Critère de succès

1. `curl http://127.0.0.1:8042/lab/runner/runtime-info` :
   - Sur Mac M3 : `{"backend":"mps","device":"mps:0","gpu_name":null,"cuda_version":null,"hint":"Apple M3 (mps) — slower, OK for iterating"}`
   - Sur PC : `{"backend":"cuda","device":"cuda:0","gpu_name":"NVIDIA GeForce GTX 1080 Ti","cuda_version":"12.1","hint":"PC + NVIDIA GeForce GTX 1080 Ti (CUDA 12.1) — fast"}`
2. Bandeau visible en haut de `/lab`, mise à jour après refresh.
3. Carte runtime visible dans I3 avant lancement.
4. Lancer un training : le subprocess `train_embedder.py` log au
   début un `RUNTIME {...}` JSON parsable identique à ce que
   l'endpoint /runtime-info retourne.
5. Sur les deux machines, l'utilisateur voit du premier coup d'œil
   sur quoi il tourne.

## Pièges connus

- **Mac avec eGPU CUDA imaginaire** : ça n'existe pas, mais si
  `torch.cuda.is_available()` retourne true sur darwin par
  configuration foireuse, le code ne crash pas — `gpu_name` sera
  juste bizarre. Acceptable.
- **CUDA détecté mais GPU OOM** : le runtime info ne dit rien sur la
  mémoire libre. Pas dans le scope v1. Si on veut, ajouter
  `torch.cuda.mem_get_info()` plus tard.
- **`platform.processor()` est vide sur darwin** dans certaines
  versions Python. D'où le fallback `sysctl`.
- **Le subprocess tourne dans `ml/.venv/bin/python`** : si le venv
  Mac n'a pas la même version de torch que le venv PC, on aura un
  écart. Ce n'est pas un bug à corriger ici — c'est la responsabilité
  du flake.nix / direnv (cf mémoire `feedback_nix_devshell`). On
  reflète juste ce que le venv dit.
- **`detect()` ne doit jamais raise** : torch présent, c'est garanti
  par le venv. Si un import foire, retourner un `RuntimeInfo` avec
  `backend="cpu"` et `hint="runtime detection failed: ..."`.

## Hors-scope

- Pas de **benchmark synthétique** au boot pour mesurer la vitesse
  réelle. L'utilisateur connaît son matos.
- Pas de **switch runtime** dans l'UI ("force CPU"). Si besoin,
  passer `--device cpu` à la main, statu quo.
- Pas d'**estimation ETA pré-lancement** basée sur l'historique.
  Phase 5 calculera l'ETA pendant le run. Pré-run, on affiche juste
  le matos.
- Pas de **détection d'un runtime distant** (machine différente du
  serveur API). On suppose API + training sur la même machine, ce
  qui est le statu quo.
