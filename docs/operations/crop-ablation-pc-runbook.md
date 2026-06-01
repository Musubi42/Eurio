# Runbook PC — sweep ablation format crop (backend, 1080 Ti)

> **À donner tel quel à une session Claude Code fraîche sur le PC (`desktop`, profil
> Nix `pc`, GPU 1080 Ti).** Objectif : lancer le sweep d'ablation format crop
> 100 % backend (aucun passage par l'app Android / l'admin), stocker les sorties
> proprement, et produire une table comparative pour désigner le format gagnant.
>
> Contexte stratégique : `docs/cohort-capture-ablation.md` (tracker capture) +
> memory `project_crop_format_ablation`. Recherche SOTA : memory
> `reference_crop_format_research`.

---

## Ce qu'on fait (stratégie A, actée 2026-06-01)

On évalue **12 formats de crop** (4 margins × 3 edge_modes, résolution 224) en
deux temps pour tenir dans ~45h GPU au lieu de ~60h :

1. **Screening** : entraîner les 12 combos à **8 epochs** (≈ 2.5h/combo ≈ **30h**),
   lire la table triée par R@1, retenir les **2-3 finalistes**.
2. **Finalisation** : ré-entraîner uniquement les finalistes à **20 epochs**
   (≈ 5h/combo ≈ **15h**) pour le chiffre R@1 définitif.

Le hold-out d'éval = **337 captures device** (cohorte `mix-zone-17`, 17 pièces ×
5 conditions d'éclairage). Pour chaque combo, le pipeline re-crope le dataset
Numista d'entraînement avec le format candidat, ré-entraîne un embedder ArcFace,
puis évalue le R@1 sur les **raws device re-cropés au même format**.

> ⚠️ **À ne pas sur-interpréter** : les captures device servent à la fois de
> val pendant le training (sélection du best_model) et de hold-out final. Le
> classement *relatif* entre combos reste équitable (même val partout), mais le
> R@1 *absolu* est optimiste.

---

## Matrice des 12 combos

| margin \ edge | `hard` | `feathered` | `none` |
|---|---|---|---|
| **0.02** | m02-hard | m02-feathered | m02-none |
| **0.05** | m05-hard | m05-feathered | m05-none |
| **0.10** | m10-hard | m10-feathered | m10-none |
| **0.15** | m15-hard | m15-feathered | m15-none |

(`edge_mode` : `hard` = masque noir net hors cercle · `feathered` = transition
douce · `none` = pas de masque. Définition source :
`ml/scripts/recrop_with_config.py:49`.)

---

## Prérequis PC (gate — ne pas avancer si un point échoue)

> **Règle repo** : toujours `go-task` (jamais `task`). Staging git explicite par
> fichier (jamais `git add -A`/`.`). Cf. `CLAUDE.md`.

1. **Repo cloné + devShell `pc`** : `cd <repo>/Eurio && direnv allow`
   (le `.envrc` dispatch sur hostname `desktop` → profil `pc`, qui pose le
   `LD_LIBRARY_PATH` NVIDIA pour CUDA).
2. **Les raws de training sont DÉJÀ là** : `ml/datasets/<numista_id>/{obverse,reverse}.jpg`
   sont versionnés dans le repo (≈ 8900 fichiers). Le clone suffit, rien à
   transférer côté training.
3. **GPU visible** :
   ```bash
   go-task ml:check
   # doit afficher : torch X.Y  cuda=True  mps=False
   ```
   Si `cuda=False` → le devShell `pc` n'est pas chargé (vérifier `direnv`,
   `LD_LIBRARY_PATH`). **Stop tant que cuda≠True.**

---

## Étape 1 — Récupérer le pull device (les 337 captures)

Le hold-out **n'est pas dans le repo** (gitignore `ml/datasets/*`, et le pull vit
sous `debug_pull/`). Deux options :

### Option A (recommandée) — copier le pull déjà vérifié depuis le Mac

Le pull a été fait et réconcilié sur le Mac le 2026-06-01 (337/337 crops, 0
manquant). Il pèse ~24 Mo. Depuis le PC :

```bash
# adapter user@mac-host et le chemin
rsync -av musubi42@<mac-host>:'~/Documents/Musubi42/bizz/Eurio/debug_pull/20260601_154135/' \
    <repo>/Eurio/debug_pull/20260601_154135/
```

### Option B — re-puller (téléphone branché au PC)

Le device **n'a pas été cleané**, les captures y sont toujours :

```bash
go-task -t app-android/Taskfile.yml capture:pull
# note le nouveau timestamp affiché → debug_pull/<NEW_TS>/eval_real/
```

### Fixer la variable de chemin

Pour la suite, depuis le repo root :

```bash
export PULL=debug_pull/20260601_154135        # ou <NEW_TS> si option B
ls "$PULL/eval_real/manifest.jsonl"           # doit exister
find "$PULL" -name '*_raw.jpg' | wc -l        # doit afficher 337
```

---

## Étape 2 — (Re)synchroniser le val-set `eval_real_norm`

`prepare_dataset` **remplace le val-set** par une version normalisée des captures
device. Il faut la régénérer depuis CE pull (l'ancienne est périmée — le `--clear`
de la task la vide d'abord) :

```bash
go-task ml:eval-real:sync -- "../$PULL"
# (la task tourne avec cwd=ml/, d'où le ../ ; elle ajoute --clear automatiquement)
```

Vérifier en fin de run : `ls ml/datasets/eval_real_norm/` doit lister les 17
`eurio_id` de la cohorte (ad-2014…, at-2002…, at-2005…, etc.) et **rien d'autre**.

---

## Étape 3 — Screening : 12 combos à 8 epochs

Lance le sweep en arrière-plan (≈ 30h) — préfère `tmux`/`nohup` pour survivre à
une déconnexion SSH. Le sweep est **ré-entrant** (skip ce qui est déjà produit).

```bash
cd ml
tmux new -s ablation        # ou: nohup ... &
.venv/bin/python -m scripts.sweep_ablation \
    --device-pull "../$PULL" \
    --sweep-default \
    --class-kind eurio_id \
    --epochs 8
# détacher tmux : Ctrl-b d   ·   réattacher : tmux attach -t ablation
```

Sorties produites par combo (slug = `m<NN>-<edge>-s224`) :

| Quoi | Où |
|---|---|
| Dataset re-cropé | `ml/datasets/eurio-poc-<slug>/` |
| Checkpoint | `ml/checkpoints/best_model_<slug>.pth` |
| Embeddings | `ml/output/embeddings_v1_<slug>.json` |
| Éval par combo | `ml/state/ablation_eval/<slug>.{csv,summary.json}` |
| **Table agrégée** | `ml/state/ablation_eval/_sweep_results.{csv,md}` |

> 💽 **Disque** : 12 datasets re-cropés cohabitent (le sweep ne nettoie pas, pour
> la ré-entrance). Surveiller l'espace ; au besoin supprimer
> `ml/datasets/eurio-poc-<slug>/` d'un combo **après** que son `.summary.json`
> existe (il sera regénéré si on relance ce combo).

Si interrompu : relancer **la même commande** (reprend où il s'est arrêté). Pour
forcer une étape : `--force-from {recrop,train,embed,eval}`.

---

## Étape 4 — Archiver la table de screening + choisir les finalistes

**Avant** de full-trainer (qui écrase les entrées par slug), fige la table 8ep :

```bash
cd ml
cp state/ablation_eval/_sweep_results.csv state/ablation_eval/_sweep_results_screen8ep.csv
cp state/ablation_eval/_sweep_results.md  state/ablation_eval/_sweep_results_screen8ep.md
cat state/ablation_eval/_sweep_results_screen8ep.md   # triée par R@1 ↓
```

Retiens les **2-3 meilleurs slugs** (ex. `m02-feathered`, `m05-hard`). Note-les :
le slug exact donne `--margin-frac` (NN/100) et `--edge-mode`.

> Hypothèse de la stratégie A : le *classement* à 8 epochs ≈ celui à 20. Les
> finalistes obtiennent ensuite leur vrai chiffre 20ep ci-dessous.

---

## Étape 5 — Finaliser : full-train des 2-3 finalistes à 20 epochs

Pour **chaque** finaliste, ré-entraîne à 20 epochs en forçant depuis `train`
(réutilise le dataset re-cropé existant, ré-entraîne + ré-embed + ré-éval) :

```bash
cd ml
# exemple finaliste m05-hard :
.venv/bin/python -m scripts.sweep_ablation \
    --device-pull "../$PULL" \
    --class-kind eurio_id \
    --margin-frac 0.05 --edge-mode hard \
    --epochs 20 --force-from train
# répéter pour chaque finaliste (adapter --margin-frac / --edge-mode)
```

Puis ré-agrège toutes les `summary.json` (mélange : finalistes en 20ep, le reste
en 8ep) et fige la table finale :

```bash
.venv/bin/python -m scripts.sweep_ablation --aggregate-only \
    --device-pull "../$PULL" --class-kind eurio_id
cp state/ablation_eval/_sweep_results.csv state/ablation_eval/_sweep_results_final.csv
cp state/ablation_eval/_sweep_results.md  state/ablation_eval/_sweep_results_final.md
cat state/ablation_eval/_sweep_results_final.md
```

> Dans `_sweep_results_final.md`, les finalistes sont à 20 epochs, les autres à 8.
> Le **gagnant = meilleur R@1 parmi les finalistes 20ep** (ne pas comparer un 20ep
> à un 8ep). La table 8ep complète reste dans `_sweep_results_screen8ep.md`.

---

## Étape 6 — Remonter les résultats pour comparaison

Seuls les fichiers de résultats (légers) doivent revenir côté Mac/repo ; les
checkpoints (lourds) restent sur le PC. Depuis le Mac (ou commit côté PC) :

```bash
rsync -av musubi42@desktop:'<repo>/Eurio/ml/state/ablation_eval/_sweep_results_*' \
    <repo>/Eurio/ml/state/ablation_eval/
```

Artefacts de comparaison finaux :
- `ml/state/ablation_eval/_sweep_results_screen8ep.{csv,md}` — grille complète 8ep
- `ml/state/ablation_eval/_sweep_results_final.{csv,md}` — finalistes 20ep

Le format gagnant (margin + edge_mode) → **Step 4 cutover** : reporter le
`CropConfig` dans le `SnapNormalizer` Kotlin + re-deploy. Conserver
`best_model_<slug_gagnant>.pth` sur le PC pour l'export TFLite ultérieur.

---

## Checklist

- [ ] devShell `pc` chargé, `go-task ml:check` → `cuda=True`
- [ ] pull device présent (`$PULL/eval_real/manifest.jsonl`, 337 raws)
- [ ] `eval_real_norm/` resync (17 eurio_id de la cohorte, rien d'autre)
- [ ] screening lancé (`--sweep-default --epochs 8`) en tmux
- [ ] `_sweep_results_screen8ep.md` figé, 2-3 finalistes choisis
- [ ] finalistes full-trainés (`--epochs 20 --force-from train`)
- [ ] `_sweep_results_final.md` figé, gagnant identifié
- [ ] résultats remontés côté Mac/repo

---

## Troubleshooting

| Symptôme | Cause | Fix |
|---|---|---|
| `cuda=False` | devShell `mac`/`default` chargé au lieu de `pc` | `direnv reload`, vérifier hostname `desktop` dans `.envrc`, `LD_LIBRARY_PATH` NVIDIA |
| `No source images found in datasets/` | clone partiel / LFS manquant | vérifier `ml/datasets/<numista_id>/obverse.jpg` présents |
| `Missing eval_real_norm/<eurio_id>/` au prepare | sync pas faite / périmée | re-lancer Étape 2 (`go-task ml:eval-real:sync -- ../$PULL`) |
| `manifest.jsonl absent` | mauvais `$PULL` | pointer le dossier contenant `eval_real/manifest.jsonl` |
| OOM GPU pendant train | batch trop gros pour 11 Go | ajouter `--batch-size 16` à la commande sweep |
| Un combo a planté en cours | étape échouée | relancer la même commande (ré-entrant) ; sinon `--force-from train` sur ce combo |

---

## Liens

- Tracker capture : `docs/cohort-capture-ablation.md`
- Orchestrateur : `ml/scripts/sweep_ablation.py`
- Recrop : `ml/scripts/recrop_with_config.py` · Éval : `ml/scripts/eval_cohort_ablation.py`
- Sync val : `ml/scan/sync_eval_real.py` (task `go-task ml:eval-real:sync`)
- Memory : `project_crop_format_ablation`, `reference_crop_format_research`, `project_training_bench_split`
