# Eurio ML

Pipeline d'entraînement coin-embedding (MobileNetV3 / ArcFace) + API FastAPI orchestratrice
(`api/server.py`, port 8042) + scrapers/scrapers et bootstrap Supabase.

Toutes les commandes passent par `go-task` (jamais `task` directement, cf. CLAUDE.md).
Liste exhaustive : `go-task --list-all` ou `cat ml/Taskfile.yml`.

## Setup

Identique sur les deux machines :

```bash
nix develop          # ou direnv si .envrc auto-load
go-task ml:setup     # idempotent : crée/répare .venv et installe les deps
```

`ml:setup` :
1. Crée `.venv` avec `--system-site-packages` (le venv hérite des paquets du devShell Nix).
   Si le venv existe déjà sans ce flag, il est recréé.
2. Lance `uv pip install --python .venv/bin/python -e .` qui résout les deps déclarées dans
   `pyproject.toml`. uv applique des sources spécifiques par plateforme pour `torch` /
   `torchvision` (voir section suivante).
3. Affiche la version de torch + état CUDA/MPS pour vérification.

Sortie attendue :

| Machine                              | Ligne finale                                            |
|--------------------------------------|---------------------------------------------------------|
| NixOS x86_64 (PC AMD + 1080ti)       | `torch 2.5.1+cu121  cuda=True  mps=False`               |
| nix-darwin aarch64 (Mac ARM)         | `torch 2.5.1  cuda=False  mps=True`                     |

Si `cuda=False` apparaît sur le PC : voir [Pré-requis NixOS](#pré-requis-nixos) ci-dessous.

## Lancer l'API

```bash
go-task ml:api        # uvicorn avec --reload (dev)
go-task ml:api-prod   # sans --reload
```

Sert FastAPI sur `http://127.0.0.1:8042`. Doc OpenAPI : `/docs`.

## Comment c'est géré (multi-plateforme)

Le projet mélange deux gestionnaires de paquets parce qu'aucun ne couvre seul tous les
besoins :

- **Nix devShell** (`flake.nix`) — Python 3.12 + paquets stables résolus par `system`
  (x86_64-linux ou aarch64-darwin) : numpy, pillow, fastapi, uvicorn, httpx, matplotlib,
  scikit-learn, beautifulsoup4… Reproductible bit-pour-bit, mais limité à ce que nixpkgs
  package.
- **uv + venv** (`pyproject.toml`) — pour les paquets non-disponibles ou non-souhaités côté
  Nix : `opencv-python-headless`, `pytorch-metric-learning`, et surtout `torch` /
  `torchvision` qu'on veut **CUDA-enabled sur Linux et MPS-enabled sur Mac**.

Le venv est créé avec `--system-site-packages = true` : les paquets Nix sont visibles
depuis le venv sans réinstallation, et le venv ne contient *que* les extras hors-Nix
(~170 MB au lieu de plusieurs GB).

### torch par plateforme — la mécanique

`pyproject.toml` déclare :

```toml
[tool.uv.sources]
torch       = [{ index = "pytorch-cu121", marker = "sys_platform == 'linux' and platform_machine == 'x86_64'" }]
torchvision = [{ index = "pytorch-cu121", marker = "sys_platform == 'linux' and platform_machine == 'x86_64'" }]

[[tool.uv.index]]
name     = "pytorch-cu121"
url      = "https://download.pytorch.org/whl/cu121"
explicit = true
```

À l'install, uv évalue le marker PEP 508 :

| Plateforme           | Marker vrai ? | Source utilisée                          | Wheel résultant                  |
|----------------------|---------------|------------------------------------------|----------------------------------|
| NixOS x86_64         | oui           | `https://download.pytorch.org/whl/cu121` | `torch-X.Y.Z+cu121-…manylinux…`  |
| Mac aarch64-darwin   | non           | PyPI standard                            | `torch-X.Y.Z-…macosx_arm64…` (MPS) |

`explicit = true` empêche uv de consulter l'index PyTorch pour autre chose que les paquets
qui le citent — pas de pollution.

Les autres deps (`opencv-python-headless`, `pytorch-metric-learning`) ont des wheels
précompilés pour les deux plateformes sur PyPI ; uv choisit le bon automatiquement, aucun
marker à écrire.

### Pourquoi `opencv-python-headless` et pas `opencv-python`

Le wheel `opencv-python` standard linke contre `libGL.so.1` (la partie GUI : `cv2.imshow`,
`namedWindow`…). Sous Nix cette lib n'est pas exposée → import échoue. La variante
`-headless` retire la dépendance GUI et garde toute l'API de traitement d'image.
Le code du repo n'utilise pas la GUI cv2.

### Pourquoi pas torch dans Nix uniquement

`pkgs.python312Packages.torch` côté nixpkgs est CPU-only par défaut sur x86_64-linux —
rendre la 1080ti exploitable demanderait `cudaSupport = true` dans le flake, ce qui force
un rebuild très long et casse l'eval sur Mac (cuda absent de aarch64-darwin). uv avec
markers est plus simple et donne le bon backend sur chaque machine sans toucher au flake.

## Pré-requis NixOS

Les wheels PyPI (notamment torch CUDA) sont liés dynamiquement contre `libstdc++.so.6`,
`libcuda.so.1` et d'autres libs qui ne sont pas dans le store par défaut. Le devShell
gère ça automatiquement : son `shellHook` (cf. `flake.nix`) exporte un `LD_LIBRARY_PATH`
combinant :

- `/run/opengl-driver/lib` — driver NVIDIA exposé par NixOS quand `hardware.nvidia.*` est
  actif. Fournit `libcuda.so.1`, `libnvidia-*.so`. **Pré-requis système** : la 1080ti
  doit être active côté config NixOS.
- `$NIX_LD_LIBRARY_PATH` — set par `programs.nix-ld`. Fournit `libstdc++.so.6`, `libz`,
  etc. **Pré-requis système** : avoir `nix-ld` activé dans la config NixOS, idéalement
  avec quelques libs C++ courantes :
  ```nix
  programs.nix-ld.enable = true;
  programs.nix-ld.libraries = with pkgs; [ stdenv.cc.cc zlib ];
  ```

Note : `nix-ld` seul ne suffit pas pour les modules Python — sa magie cible les binaires
non-Nix qui passent par leur propre interpréteur ELF, alors que `python3` est Nix et
charge ses extensions via `dlopen`, qui lit `LD_LIBRARY_PATH`. C'est pour ça que le
`shellHook` exporte explicitement la variable.

Sortie attendue (dans le devShell) :
```
$ python3 -c 'import torch; print(torch.cuda.is_available(), torch.cuda.get_device_name(0))'
True NVIDIA GeForce GTX 1080 Ti
```

## Pré-requis Mac (nix-darwin)

Rien de particulier côté lib système : les wheels macOS arm64 sont liés contre `libSystem`
qui est toujours présent. `nix-ld` n'existe pas sur darwin, et n'est pas nécessaire.

MPS est disponible dès macOS 12.3 + Apple Silicon, fourni nativement par le wheel torch
PyPI standard. `torch.backends.mps.is_available()` doit renvoyer `True` après `ml:setup`.

## Variables d'environnement

`../.envrc` (chargé par direnv ou exporté manuellement) doit fournir :

- `SUPABASE_URL`, `SUPABASE_ANON_KEY`, `SUPABASE_SERVICE_ROLE_KEY`
- `NUMISTA_API_KEY_MUSUBI00` (et alts pour rotation)
- `EBAY_CLIENT_ID`, `EBAY_CLIENT_SECRET` (pour le scraping prix)

## Tâches courantes

```bash
go-task --list-all                  # toutes les tâches dispo
go-task ml:api                      # FastAPI dev
go-task ml:train-arcface            # entraînement embedder ArcFace
go-task ml:evaluate                 # Recall@1/3 sur le test set
go-task ml:export                   # PyTorch → TFLite
go-task ml:deploy                   # copie TFLite + meta dans app-android/assets
go-task ml:scrape-ebay -- --countries=FR,DE --limit 10
go-task ml:sync-supabase-dry        # preview du push referential → Supabase
```

Pipeline d'entraînement détaillée et structure des datasets : voir
`docs/research/detection-pipeline-unified.md` et `docs/design/_shared/data-contracts.md`.
