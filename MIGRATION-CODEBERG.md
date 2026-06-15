# Migration Codeberg — Eurio

> Voir la méthode commune : `bizz/MIGRATION-CODEBERG.md`
> **Statut** : 🔴 À faire · **Difficulté** : 🔴🔴 la plus lourde (1.1 GB → < 100 MiB)

## État actuel
- GitHub : `git@github.com:Musubi42/Eurio.git`
- Branche : `sources-jo-wikipedia` _(pas main — vérifier la branche de référence)_
- `.git` : **1.1 GB** · worktree : **12 GB**
- Build : flake.nix (les libs/env sont déjà reproductibles ✅)

## Diagnostic
Le `.git` énorme vient de l'**historique**, pas seulement de HEAD :
- **Backups de DB** `ml/state/eurio.db.bak-*` (~25 MB chacun, **nombreux commits**) → cause n°1.
- **Datasets ML** `ml/datasets/` : **8895 fichiers** (jpg multi-MB) → ~63 MB en HEAD, bien plus en historique.
- **Modèle** `app-android/.../coin_detector.tflite` (14 MB).
- `ml/state/crop_scores/*.png` (22 MB).

→ Une fois `ml/datasets`, `ml/state` et les modèles purgés de TOUT l'historique, il ne reste
que du code (python, kotlin, vue, txt d'annotations) : largement **< 100 MiB** visé.

## À couper
| Chemin | Taille | Destination | Pourquoi |
|---|---|---|---|
| `ml/datasets/**` | 63 MB HEAD (≫ en hist.) | **MinIO** `eurio-datasets` | jeux d'entraînement (images + labels) |
| `ml/state/*.db.bak-*` | ~25 MB × N | **SUPPRIMER** | backups DB éphémères (jamais en git) |
| `ml/state/eurio.db` | — | gitignore | DB d'état runtime, regénérée |
| `ml/state/crop_scores/*.png` | 22 MB+ | **MinIO** ou delete | scores générés |
| `app-android/src/main/assets/models/*.tflite` | 14 MB | **MinIO** `eurio-models` (ou release asset) | modèle entraîné, fetch au build |

> À décider : garder les `*.txt` d'annotations dans git (utile, versionnable) ou les déplacer
> avec les datasets dans MinIO. Recommandation : **garder les labels .txt** (petits, précieux),
> **sortir uniquement les images**.

## Adaptations code (pour que ça tourne après le cut)
- **Pipeline ML** : la lecture des datasets (`ml/datasets/`) doit passer par un **sync MinIO**
  (`mc mirror` au début du training, ou lecture directe via boto3/SDK S3). Ajouter un
  `scripts/fetch-datasets.sh`.
- **App Android** : `coin_detector.tflite` doit être **téléchargé dans `assets/models/` au build**
  (tâche Gradle / hook flake) au lieu d'être commité. Pinner la version du modèle.
- **ml/state** : confirmer que c'est 100 % regénérable ; gitignore (`ml/state/`).
- **.gitignore** : `ml/datasets/**` (images), `ml/state/`, `*.db.bak-*`, `*.tflite`, sorties.

## Procédure git (filter-repo) — historique lourd, faire avec soin
```bash
# 0. SÉCURITÉ : backup miroir COMPLET (l'historique gras au cas où)
git clone --mirror . ../Eurio-FULL-BACKUP.git

# 1. Extraire les assets vers MinIO AVANT purge
mc mb --ignore-existing bizz/eurio-datasets bizz/eurio-models
mc mirror ml/datasets bizz/eurio-datasets/          # images
mc cp app-android/src/main/assets/models/coin_detector.tflite bizz/eurio-models/

# 2. Purger de TOUT l'historique (garde les labels .txt si souhaité : ne pas inclure leur glob)
nix run nixpkgs#git-filter-repo -- \
  --path ml/state \
  --path-glob 'ml/datasets/**/*.jpg' --path-glob 'ml/datasets/**/*.png' \
  --path-glob '*.tflite' --path-glob '*.db.bak-*' \
  --invert-paths

# 3. Vérifier
du -sh .git    # objectif : < 100 MiB

# 4. .gitignore + commit
```

> Si après purge on dépasse encore 100 MiB → envisager la variante **fresh start**
> (nouveau repo, 1 commit code-only). L'historique gras reste dans `Eurio-FULL-BACKUP.git`.

## Migration (Option A)
```bash
git remote rename origin github
git remote add origin git@codeberg.org:<user>/Eurio.git
git push origin --all && git push origin --tags
# Push-mirror Codeberg → GitHub
```

## Checklist
- [ ] Confirmer la branche de référence (sources-jo-wikipedia vs main)
- [ ] Backup miroir COMPLET créé (`Eurio-FULL-BACKUP.git`)
- [ ] Images datasets → MinIO `eurio-datasets`
- [ ] Modèle `.tflite` → MinIO `eurio-models`
- [ ] Décision labels `.txt` : garder dans git (recommandé) ou MinIO
- [ ] Code ML adapté : `fetch-datasets` depuis MinIO
- [ ] Android adapté : download `.tflite` au build
- [ ] `ml/state` confirmé regénérable + gitignore
- [ ] `filter-repo` → `.git` < 100 MiB (sinon fresh start)
- [ ] `nix develop` / build OK ; training OK depuis MinIO
- [ ] Repo Codeberg créé + push + miroir GitHub
- [ ] Statut → 🟢
