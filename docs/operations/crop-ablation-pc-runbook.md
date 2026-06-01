# Runbook PC — sweep ablation format crop (offline, 1080 Ti)

> **À exécuter sur le PC (`desktop`, profil Nix `pc`, GPU 1080 Ti).** Objectif :
> lancer le sweep d'ablation format crop **100 % offline** (aucun Supabase,
> aucun passage par l'app Android / l'admin), et produire une table comparative
> pour désigner le format de crop gagnant.
>
> Contexte stratégique : `docs/cohort-capture-ablation.md` (tracker capture) +
> memory `project_crop_format_ablation`. Décision offline : memory
> `project_crop_ablation_offline_training`. Recherche SOTA : memory
> `reference_crop_format_research`.

---

## Pourquoi offline (lis ça d'abord)

L'ancienne version de ce runbook construisait les **classes d'entraînement
depuis Supabase**. Or `eurio.db` (SQLite local, source de vérité) a beaucoup
**drifté** par rapport à Supabase sur les `eurio_id` : les labels Supabase ne
matchaient plus les captures device → seulement 5/17 pièces alignées → R@1
plafonné ~20 % quel que soit le crop. **On a abandonné Supabase pour ce bench.**

La source de vérité du bench est le **CSV cohort**
`ml/state/cohort_csvs/mix-zone-17.csv` (`eurio_id;numista_id;display_name`). Sa
colonne `eurio_id` EST le label des captures device, donc `train` ↔ `val` ↔
`eval` partagent un seul namespace. On passe ce CSV via `--cohort-csv` ; le
pipeline résout `numista_id → eurio_id` depuis le CSV (fonction
`build_resolver_from_cohort_csv`, `ml/eval/class_resolver.py`) et entraîne
**exactement les 17 coins du CSV** (closed-set 17 classes).

> ⚠️ **Bench relatif** : les captures device servent à la fois de val pendant le
> training (sélection du best_model) et de hold-out final. Le classement
> *relatif* entre combos reste équitable (même val partout), mais le R@1
> *absolu* est optimiste (17-way closed set). C'est ce qu'on veut : choisir le
> meilleur format de crop, pas mesurer la perf prod.

---

## Ce qu'on fait

On évalue **12 formats de crop** (4 margins × 3 edge_modes, résolution 224), en
**un seul passage à 12 epochs**. À 17 classes c'est rapide : **~1–2 h GPU pour
les 12 combos** (plus besoin du découpage screen-8ep / finalize-20ep de
l'ancienne stratégie, qui supposait un entraînement full-catalogue à ~45 h).

Pour chaque combo, le pipeline re-crope les raws Numista des 17 coins au format
candidat, ré-entraîne un embedder ArcFace, calcule les centroïdes, puis évalue
le R@1 sur les **captures device re-cropées au même format**.

### Matrice des 12 combos

| margin \ edge | `hard` | `feathered` | `none` |
|---|---|---|---|
| **0.02** | m02-hard | m02-feathered | m02-none |
| **0.05** | m05-hard | m05-feathered | m05-none |
| **0.10** | m10-hard | m10-feathered | m10-none |
| **0.15** | m15-hard | m15-feathered | m15-none |

(`edge_mode` : `hard` = masque noir net hors cercle · `feathered` = transition
douce · `none` = pas de masque. Source : `ml/scripts/recrop_with_config.py`.)

---

## Prérequis PC (gate — ne pas avancer si un point échoue)

> **Règle repo** : toujours `go-task` (jamais `task`). Staging git explicite par
> fichier (jamais `git add -A`/`.`). Cf. `CLAUDE.md`.

1. **devShell `pc` chargé** : `cd <repo>/Eurio && direnv allow` (dispatch sur
   hostname `desktop` → profil `pc`, qui pose le `LD_LIBRARY_PATH` NVIDIA).
   *Pas besoin des secrets Supabase pour ce bench* — le training est offline.
2. **GPU visible** :
   ```bash
   cd ml
   .venv/bin/python -c "import torch; print('torch', torch.__version__, 'cuda=', torch.cuda.is_available(), torch.cuda.get_device_name(0) if torch.cuda.is_available() else '')"
   # attendu : torch 2.9.x  cuda= True  NVIDIA GeForce GTX 1080 Ti
   ```
   Si `cuda=False` → devShell `pc` pas chargé (vérifier `direnv`,
   `LD_LIBRARY_PATH`). **Stop tant que cuda≠True.**
   Si le venv est signalé STALE par direnv : `go-task ml:venv-rebuild`.
3. **Raws de training présents** : `ml/datasets/<numista_id>/obverse.jpg` sont
   versionnés (les 17 `numista_id` du CSV sont couverts). Le clone suffit.
4. **CSV cohort présent** : `ml/state/cohort_csvs/mix-zone-17.csv` (17 lignes
   `eurio_id;numista_id;display_name`).

---

## Étape 1 — Récupérer le pull device (captures cohort)

Le hold-out (captures device) **n'est pas dans le repo**. Le téléphone n'a pas
été cleané, donc on peut (re)puller :

```bash
go-task -t app-android/Taskfile.yml capture:pull
# → debug_pull/<TIMESTAMP>/eval_real/{manifest.jsonl, <eurio_id>/<step>_*.jpg}
# Affiche "✓ Pulled 337 crops · 17 coins". Note le <TIMESTAMP>.
```

Fixe la variable de chemin (depuis le repo root) :

```bash
export PULL=debug_pull/20260601_162127     # ← remplace par TON timestamp
ls "$PULL/eval_real/manifest.jsonl"        # doit exister
find "$PULL" -name '*_raw.jpg' | wc -l     # ~337
```

---

## Étape 2 — Synchroniser le val-set `eval_real_norm`

Normalise les captures device (pipeline Hough, comme on-device) en 224×224 dans
`ml/datasets/eval_real_norm/<eurio_id>/`. **Offline** (pas de Supabase). Le
`--clear` (ajouté par la task) vide d'abord l'ancien val-set :

```bash
go-task ml:eval-real:sync -- "../$PULL"
# (la task tourne avec cwd=ml/, d'où le ../)
```

Vérifie en fin de run : `ls ml/datasets/eval_real_norm/` doit lister les **17
`eurio_id`** de la cohorte (ad-2014…, at-2002…, at-2005…, etc.) et rien d'autre.

---

## Étape 3 — Lancer le sweep (12 combos × 12 epochs, offline)

Lance en `tmux` pour survivre à une déconnexion. Le `env -u SUPABASE_*` **force
le mode offline** (sinon, si tes secrets sont chargés par direnv, `train_embedder`
irait interroger Supabase pour les zones d'augmentation — inutile ici, tout
défaut à `orange`). Le sweep est **ré-entrant** (skip ce qui est déjà produit).

```bash
cd ml
tmux new -s ablation        # détacher : Ctrl-b d · réattacher : tmux attach -t ablation

env -u SUPABASE_URL -u SUPABASE_SERVICE_ROLE_KEY -u SUPABASE_ANON_KEY -u SUPABASE_SERVICE_KEY \
.venv/bin/python -m scripts.sweep_ablation \
    --device-pull "../$PULL" \
    --class-kind eurio_id \
    --cohort-csv state/cohort_csvs/mix-zone-17.csv \
    --sweep-default \
    --epochs 12
```

Ce que tu verras défiler, par combo (× 12) :
- `Resolver: 17 known classes from cohort CSV mix-zone-17.csv` ← confirme l'offline
- `prepare_dataset` → re-crop des 17 coins
- `train_embedder` → 12 epochs, `Zone distribution: {'orange': 17}`, R@1 val par epoch
- `compute_embeddings` → `17 classes, 256-dim centroids`
- `eval_cohort_ablation` → `=== R@K summary ===` (R@1/R@5 global + par condition)

Sorties produites par combo (slug = `m<NN>-<edge>-s224[-fw04]`) :

| Quoi | Où |
|---|---|
| Dataset re-cropé | `ml/datasets/eurio-poc-<slug>/` |
| Checkpoint | `ml/checkpoints/best_model_<slug>.pth` |
| Embeddings | `ml/output/embeddings_v1_<slug>.json` |
| Éval par combo | `ml/state/ablation_eval/<slug>.{csv,summary.json}` |
| **Table agrégée** | `ml/state/ablation_eval/_sweep_results.{csv,md}` |

> 💽 **Disque** : les 12 datasets re-cropés cohabitent (le sweep ne nettoie pas,
> pour la ré-entrance). À 17 coins c'est léger. Au besoin, supprimer
> `ml/datasets/eurio-poc-<slug>/` d'un combo **après** que son `.summary.json`
> existe (regénéré si on relance ce combo).

Si interrompu : relancer **la même commande** (reprend où il s'est arrêté). Pour
forcer une étape : `--force-from {recrop,train,embed,eval}`. Pour un seul combo
(debug) : remplacer `--sweep-default` par `--margin-frac 0.10 --edge-mode feathered`.

---

## Étape 4 — Lire les résultats + choisir le gagnant

```bash
cat ml/state/ablation_eval/_sweep_results.md   # trié par R@1 ↓
# fige une copie horodatée si tu veux la garder :
cp ml/state/ablation_eval/_sweep_results.csv ml/state/ablation_eval/_sweep_results_12ep.csv
cp ml/state/ablation_eval/_sweep_results.md  ml/state/ablation_eval/_sweep_results_12ep.md
```

Le **gagnant = meilleur R@1** dans la table (tous les combos sont à 12 epochs,
donc directement comparables). Note son slug : il donne `--margin-frac` (NN/100)
et `--edge-mode`.

> Repère de sanity : un combo correct sort ~75–90 % R@1 sur ce hold-out 17-way.
> Tout combo < 50 % signale un souci (val vide, mismatch de classes) plutôt
> qu'un mauvais format.

---

## Étape 5 — Remonter les résultats / cutover

Seuls les fichiers de résultats (légers) reviennent côté Mac/repo ; les
checkpoints (lourds) restent sur le PC.

```bash
# depuis le Mac :
rsync -av musubi42@desktop:'<repo>/Eurio/ml/state/ablation_eval/_sweep_results*' \
    <repo>/Eurio/ml/state/ablation_eval/
```

Le format gagnant (margin + edge_mode) → **Step 4 cutover** : reporter le
`CropConfig` dans le `SnapNormalizer` Kotlin + re-deploy. Conserver
`best_model_<slug_gagnant>.pth` sur le PC pour l'export TFLite ultérieur.

---

## Checklist

- [ ] devShell `pc` chargé, `cuda=True` (Prérequis #2)
- [ ] CSV cohort présent (`ml/state/cohort_csvs/mix-zone-17.csv`, 17 lignes)
- [ ] pull device présent (`$PULL/eval_real/manifest.jsonl`, ~337 raws)
- [ ] `eval_real_norm/` resync (17 eurio_id de la cohorte, rien d'autre)
- [ ] sweep lancé offline (`env -u SUPABASE_* … --cohort-csv … --sweep-default --epochs 12`) en tmux
- [ ] `_sweep_results.md` lu, gagnant identifié (meilleur R@1)
- [ ] résultats remontés côté Mac/repo

---

## Troubleshooting

| Symptôme | Cause | Fix |
|---|---|---|
| `cuda=False` | devShell `mac`/`default` au lieu de `pc` | `direnv reload`, vérifier hostname `desktop`, `LD_LIBRARY_PATH` NVIDIA |
| `Resolver: … from Supabase` au lieu de `from cohort CSV` | `--cohort-csv` oublié | ré-ajouter `--cohort-csv state/cohort_csvs/mix-zone-17.csv` |
| R@1 ~20 % sur tous les combos | val non aligné / mauvais namespace de classes | tu n'es probablement pas en mode CSV — vérifier le log `Resolver: 17 … from cohort CSV` |
| `No source images found in datasets/` | clone partiel | vérifier `ml/datasets/<numista_id>/obverse.jpg` présents |
| `Missing eval_real_norm/<eurio_id>/` au prepare | sync pas faite / périmée | relancer Étape 2 (`go-task ml:eval-real:sync -- ../$PULL`) |
| `manifest.jsonl absent` | mauvais `$PULL` | pointer le dossier contenant `eval_real/manifest.jsonl` |
| OOM GPU pendant train | batch trop gros pour 11 Go | ajouter `--batch-size 16` à la commande sweep |
| venv STALE (warning direnv) | Nix env changé | `go-task ml:venv-rebuild` |

---

## Liens

- Tracker capture : `docs/cohort-capture-ablation.md`
- Orchestrateur : `ml/scripts/sweep_ablation.py` · Recrop : `ml/scripts/recrop_with_config.py`
- Résolveur offline : `ml/eval/class_resolver.py` (`build_resolver_from_cohort_csv`)
- Sync val : `ml/scan/sync_eval_real.py` (task `go-task ml:eval-real:sync`)
- Éval : `ml/scripts/eval_cohort_ablation.py`
- Memory : `project_crop_ablation_offline_training`, `project_crop_format_ablation`, `reference_crop_format_research`
