# Setup multi-plateforme : NixOS x86_64 + 1080 Ti / nix-darwin ARM

Notes consolidées des ajustements faits pour que la même stack tourne sur les deux machines de dev. À garder à jour quand un nouveau delta plateforme apparaît.

## Hardware & backends

| | NixOS x86_64 | nix-darwin ARM |
|---|---|---|
| CPU | Ryzen 7 2700X (8c/16t) | Apple Silicon |
| GPU | GTX 1080 Ti (Pascal cc 6.1) | Metal / MPS |
| Backend torch | CUDA 12.6 | MPS |

## Stack Python (`ml/`)

### Venv qui hérite des packages Nix
- `ml/.venv/pyvenv.cfg` : `include-system-site-packages = true` — sans ça `uvicorn`/`fastapi`/`numpy`/`pillow` (servis par le devShell Nix via `python312.withPackages`) ne sont pas vus par le venv.
- `ml/Taskfile.yml` task `setup` recrée le venv avec `python3 -m venv --system-site-packages` si la config est absente.

### torch par plateforme via markers PEP 508
- `ml/pyproject.toml` :
  - `[tool.uv.sources]` : `torch` + `torchvision` pinnés sur l'index `pytorch-cu126` avec marker `sys_platform == 'linux' and platform_machine == 'x86_64'`
  - Sur Mac, le marker ne match pas → fallback PyPI default → wheel MPS
  - **Pourquoi cu126 et pas cu121** : `litert-torch` (export TFLite) + `torchao` requièrent `torch ≥ 2.7` (API `torch.utils._pytree.register_constant`). Les index cu121/cu124 ne publient pas torch ≥ 2.7. cu126 supporte toujours Pascal cc 6.1.
- `typing-extensions>=4.13` épinglé en dep directe pour casser un conflit `xdsl` (transitive de litert-torch) qui pin `<4.13`, alors que le `pydantic-core` du devShell Nix importe `Sentinel` (apparue en 4.13).

### Détection runtime du device (cuda / mps / cpu)
Plus aucun hardcoded `"mps"`. Tous les chemins reçoivent `device="auto"` qui résout au runtime :

| Fichier | Mécanisme |
|---|---|
| `ml/training/train_embedder.py` | `get_device("auto")` → cuda → mps → cpu |
| `ml/training/train_detector.py` | helper local `_resolve_device("auto")` (ultralytics n'accepte pas `auto`) |
| `ml/api/training_runner.py:97` | `self._device = "auto"` forwardé en `--device` au subprocess |
| `ml/api/server.py:160` | Pydantic `TrainConfig.device: str = "auto"` |
| `ml/eval/confusion_map.py:223` | `pick_device()` → cuda → mps → cpu |

## Spécificités Nix

### Libs C linkées par les wheels PyPI (NixOS uniquement)
`flake.nix` shellHook exporte `LD_LIBRARY_PATH` avec :
- `/run/opengl-driver/lib` — driver NVIDIA (libcuda.so.1) pour torch+cu126
- `$NIX_LD_LIBRARY_PATH` — libs C++ standards (libstdc++, zlib…) servies par `programs.nix-ld`

Bloc gardé par `if [ -d /run/opengl-driver/lib ]` → no-op sur Mac.

### `opencv-python-headless` au lieu de `opencv-python`
La variante non-headless link `libGL.so.1` (GUI) qui n'est pas dans le store. Vérifié qu'aucun `cv2.imshow` / `namedWindow` n'est utilisé dans le code.

### Activation auto du venv via direnv
`.envrc` racine, après `use flake` :
```bash
if [ -f ml/.venv/bin/activate ]; then
  source ml/.venv/bin/activate
fi
```
Pas obligatoire pour `go-task` (qui passe par `{{.VENV}}/python` en absolu) mais utile pour les LSPs et le shell interactif.

## Taskfile portable

| Avant | Après | Raison |
|---|---|---|
| `/bin/cp …` (×3 dans `ml/Taskfile.yml` task `deploy`) | `cp …` | NixOS n'a pas de `/bin/cp` (pas de FHS). `cp` via `$PATH` marche partout. |
| `Taskfile.yml` task `filament:install-matc` télécharge toujours `filament-v1.71.0-mac.tgz` | `case "$(uname -s)"` → `linux.tgz` ou `mac.tgz` | Le binaire mac plante en `exec format error` sur Linux. Le tarball Linux tourne sur NixOS via `nix-ld`. |

## Android — signature debug partagée

- Keystore versionné dans `app-android/keys/debug.keystore` (était machine-local par défaut, généré par Gradle dans `~/.android/debug.keystore` à chaque first-build).
- `app-android/build.gradle.kts` :
  ```kotlin
  signingConfigs {
      getByName("debug") {
          storeFile = file("keys/debug.keystore")
          storePassword = "android"
          keyAlias = "androiddebugkey"
          keyPassword = "android"
      }
  }
  ```
  + `buildTypes.debug.signingConfig = signingConfigs.getByName("debug")`. Le variant `qa` hérite via `initWith(getByName("debug"))`.
- Sans ça : `INSTALL_FAILED_UPDATE_INCOMPATIBLE` quand on push depuis une machine alors que le device a déjà une version signée par l'autre.
- Pas un secret prod : password `"android"` est la convention Gradle. Le keystore release/QA prod doit rester hors-repo.

## Comportements à connaître

- Premier `uv pip install -e .` sur une machine : ~2 GB de wheels CUDA tirés du PyPI sur Linux (nvidia-cu12-*, cudnn, triton). Sur Mac : ~500 MB (torch MPS).
- torchao loggue `Skipping import of cpp extensions due to incompatible torch version` quand torch ≠ 2.11 — non bloquant, fallback Python. À surveiller si on passe à des opérations torchao en prod.
- `cv2.cuda` n'est **pas** dans le wheel PyPI `opencv-python-headless`. Utiliser cv2 CUDA = rebuild OpenCV from source (cf. piste d'optim Hough séparée, voir `docs/research/`).
