># Handoff — run d'entraînement COMPLÈTE sur le PC (1080 Ti)

> **Pour une session Claude Code fraîche sur le PC.** Tout le contexte est ici.
> Branche : `sources-jo-wikipedia` (remotes : `origin`=codeberg, `github`=backup).
> Préparé le 2026-06-30 après validation d'un smoke complet sur Mac.
> **Pas-à-pas opérationnel** = [`RUNBOOK-pc-training.md`](./RUNBOOK-pc-training.md) (lis-le aussi).

> ⚠️ **L'historique git a été réécrit le 2026-06-30** (filter-repo : purge des artefacts
> de run ml/lab/iterations + ml/cache). Si le PC a **déjà un clone**, un `git pull` simple
> **échouera** (branches divergentes). Synchronise par :
> ```bash
> cd /chemin/Eurio && git fetch origin --prune && git reset --hard origin/sources-jo-wikipedia
> ```
> (s'il y a du travail local non-poussé sur le PC, le stash AVANT). Sinon, un clone frais marche directement.

## 1. Mission de cette session

Lancer **la vraie run d'entraînement complète** (epochs par défaut = 40, toutes les
images) depuis le lab, sur le GPU du PC (1080 Ti → CUDA). Tout le pipeline a été
**validé en smoke sur Mac** (MPS) — il ne reste qu'à le faire tourner en grand ici.

## 2. État : ce qui a été fait et VALIDÉ (ne pas refaire)

Tout est committé + poussé sur `sources-jo-wikipedia`. Commits clés :

| Commit | Quoi |
|---|---|
| `129feee` | `serving/server.py` lit `EURIO_DB_PATH` + tâche `ml:api-replica` (le lab lit la réplique VPS, pas une DB locale périmée) |
| `2826347` | **Training à la maille design_group** + **fix bench centroïdes** (voir §3) |
| `1cf8815` | 8 tests obsolètes réparés (lab_api + augmentation) → 50 verts |
| `41881cc` | **Observabilité front** : barre de bake live + ligne « Sources réelles » + poll 2 s |
| `b25f4a5` | tâche `ml:api-replica-prod` (sans `--reload`) + runbook PC |

**Validé empiriquement sur Mac** : create → bake (2171 samples, 19 pièces) → train
3 epochs **completed** (recall@1≈0.81) → bench **R@1=0.979 sur 96 photos** (en
standalone). Le front affiche en live : barre bake `X/Y`, sources, époque N/total,
loss, ETA, device, logs, succès/échec.

## 3. Contexte technique à connaître (le « pourquoi »)

**Model B** : le canonique = SQLite **sur le VPS** derrière `eurio-api`. Le compute
(PC/Mac) travaille sur une **réplique locale** tirée du VPS (`go-task ml:db:pull-replica`
→ `ml/state/eurio.replica.db`). Images dans **MinIO** (crops eBay tirés en cache au bake).
Le lab lit la DB pointée par `EURIO_DB_PATH` (d'où `ml:api-replica-prod`).

**Maille design_group (crucial)** : l'entraînement tourne à la maille **canonique du
label ArcFace = `COALESCE(design_group_id, eurio_id)`**. Les standards pluri-millésimes
d'un même avers (ex. `be-2007` ⊕ `be-1999` → groupe `be-2euro-albert-ii-t1`) sont **une
seule classe** et **poolent leurs sources réelles**. Avant ce fix, le lab forçait
`eurio_id` → `be-2007` (1 source) bloquait le préflight `m_per_class=4`. Maintenant il
hérite des crops de be-1999. **Conséquence attendue** : la run **tire des pièces
hors-cohorte** (les autres membres des groupes de la cohorte) — c'est voulu (décision PO).
Sites du fix : `serving/iteration_runner.py::_launch_training`,
`training/iteration_augmentations.py::generate_for_iteration`,
`training/prepare_dataset.py::_override_val_with_eval_real`.

**Bench** : benche désormais contre les centroïdes **de l'itération**
(`lab/iterations/<iid>/embeddings/embeddings_v1.json`), plus contre `prod/current/`
(absent → "Centroids file not found"). Eval déjà design_group-aware (`Centroid.covers`).

## 4. ⚠️ Piège n°1 absolu : `--reload`

`go-task ml:api` lance uvicorn **avec `--reload`**. Pendant un run, le training écrit des
fichiers (`state/training_progress/<iid>.json`, `lab/iterations/<iid>/…`) → `--reload`
**redémarre uvicorn et TUE le subprocess bench** (constaté 2× : le bench meurt en
laissant sa row `running`, l'itération reste `benchmarking`). Le training survit
(détaché double-fork), mais pas le bench.

→ **Pour la vraie run, lance `go-task ml:api-replica-prod` (SANS `--reload`).** Et ne
touche **aucun fichier `serving/*.py`** pendant un run si jamais tu es en `ml:api`.

## 5. Comment lancer (résumé — détail dans le runbook)

```bash
go-task ml:db:pull-replica          # réplique VPS fraîche
go-task ml:api-replica-prod         # lab sur la réplique, SANS reload (terminal dédié)
pnpm -C admin/packages/studio-local dev   # front → http://localhost:5173/lab
```
Puis dans le front : cohorte → créer itération (epochs 40 par défaut) → I2 « Générer »
(bake) → I3 « Lancer ». Regarde I2 (barre + sources) puis I3 (TrainingMonitor).
URL page itération : `/lab/cohorts/<cohortId>/iterations/<iterationId>`.

**Driver par curl** (alternative au clic) : `POST /lab/cohorts/{c}/iterations` (recipe_id
requis) → `POST .../{iid}/bake` (poll `.../augmentations/job`) → `POST .../{iid}/launch-training`
(poll `GET .../{iid}` status + `GET /lab/runner/training-progress/{iid}`).

## 6. Vérifs de succès

- `device: cuda` dans le monitor (sinon CUDA pas câblé sur le PC → vérifier le devShell `pc` + `LD_LIBRARY_PATH` NVIDIA, cf. `flake.nix`).
- Préflight passe (be-2007 & co ne bloquent plus grâce au design_group).
- Fin : itération `completed`, et le **bench finit avec des vrais chiffres** (num_photos>0)
  — c'est le signe que `--reload` ne l'a pas tué.
- Artefacts : `ml/lab/iterations/<iid>/{checkpoints/best_model.pth, tflite/*.tflite,
  embeddings/embeddings_v1.json, dataset/class_manifest.json, metrics/per_class_metrics.json}`.

## 7. Pièges secondaires

- **Créer une itération gèle la cohorte** (`draft→frozen`, eurio_ids verrouillés). Normal.
- **Supprimer une itération bloquée `running`/`benchmarking`** échoue → passer d'abord la
  row `benchmark_runs`/`training_runs` concernée à `failed` (UPDATE SQL sur le `EURIO_DB_PATH`).
- **17 tests pré-existants rouges** dans la suite complète (test_benchmark bare-import,
  test_normalize_listing, référentiel/orchestrator) — **hors scope, pas une régression**
  (vérifié). Les tests du lab training (lab_api/augmentation) sont verts.
- Résidu Mac : une itération de validation `74ba5d2e140e` peut encore exister côté Mac
  (DB + `ml/lab/iterations/`), sans impact PC (DB séparée).

## 8. Sources de vérité / pour aller plus loin

- Model B (archi, réplique, mode opératoire serveur) : `docs/work-in-progress/model-b/README.md`.
- Mémoire projet : `project_lab_design_group_training`, `project_model_b_server_canonical`.
- R3/R4 Model B restants (training `--push` au canonique, débit review) : `model-b/README.md` §Briefs.
  **Non requis pour cette run** (le push des métadonnées au VPS est différé ; la run locale suffit).
