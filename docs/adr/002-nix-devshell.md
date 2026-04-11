# ADR-002 — Nix devShell pour le toolchain

**Date :** 2026-04-09
**Statut :** Acceptée

## Contexte

Le projet nécessite JDK 17, Android SDK (platforms, build-tools, NDK, CMake), Gradle, Python 3.12 + PyTorch, et uv. Installer manuellement via Homebrew ou les installeurs officiels rend l'environnement non reproductible.

## Décision

Gérer tout le toolchain via un **Nix flake** (`flake.nix`) activé automatiquement par **direnv** (`.envrc`).

- Deps système (JDK, SDK, Gradle, Kotlin) : dans le `devShell` Nix
- Deps Python (torch, torchvision, scikit-learn, etc.) : via `python312.withPackages` dans Nix
- Deps pip-only (`ai-edge-torch`) : via `uv` dans un venv local (`ml/.venv/`)

## Conséquences

- `direnv allow` suffit pour avoir l'environnement complet
- Zéro `brew install` ou installation manuelle
- Python 3.12 au lieu de 3.11 (conflit sphinx/torch dans nixpkgs pour 3.11)
- `ai-edge-torch` ne peut pas être dans Nix (pas packagé) → venv séparé via uv
