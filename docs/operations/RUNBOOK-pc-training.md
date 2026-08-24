# Runbook — lancer une run d'entraînement complète sur le PC

> Doc courte à suivre demain sur le PC (1080 Ti). Valide d'abord chaque démarrage,
> puis lance, puis regarde le front se rafraîchir. Smoke validé sur Mac le 2026-06-30.

## 0. Préconditions — à démarrer DANS L'ORDRE

```bash
# 1) Donnée canonique fraîche du VPS (réplique locale read-only)
go-task ml:db:pull-replica
#    → attendu : "réplique read-only → …/state/eurio.replica.db (N coins)"

# 2) API ML sur la réplique, SANS --reload (crucial : --reload tue le subprocess
#    train/bench à chaque sauvegarde de fichier)
go-task ml:api-prod
#    (`ml:api-replica-prod` a été SUPPRIMÉE avec le chantier local-sync en
#     juillet 2026 — cf. le commentaire dans `ml/tasks.yml`. La tâche restante
#     est `ml:api-prod` ; elle honore `EURIO_DB_PATH` si tu veux pointer la
#     réplique explicitement.)
#    → laisse ce terminal ouvert. Vérifie dans un autre :
curl -s -o /dev/null -w "%{http_code}\n" http://127.0.0.1:8042/health   # attendu 200

# 3) Front local (PAT depuis .env.local)
pnpm -C admin/packages/studio-local dev
#    → ouvre http://localhost:5173/lab
```

**À vérifier avant de lancer :**
- [ ] `:8042/health` → 200, et c'est bien la **réplique** (pas le terminal `--reload`).
- [ ] Le front charge, nav lab non grisée (mode local, `hasLocalMlApi` vrai).
- [ ] GPU vu : au lancement, le monitor affichera `device: cuda` (sinon CUDA pas câblé).

## 1. Lancer la run depuis le front

1. Va sur la cohorte (`/lab/cohorts/<id>`, ex. mix-zone-17 `b0299ca0252b`).
2. **Crée une itération** (tiroir I1) — sélectionne une recipe. ⚠️ créer une itération
   **gèle** la cohorte (eurio_ids verrouillés). `training_config` vide = epochs 40 par
   défaut, `m_per_class=4`.
3. **Tiroir I2 — Bake** : clique « Générer ». Regarde la **barre de bake monter** (X/Y)
   et la ligne **« Sources réelles : N avers Numista · M crops eBay · K réfs BCE »**.
4. **Tiroir I3 — Entraînement** : clique « Lancer ». Le **TrainingMonitor** apparaît.

## 2. Ce que tu dois VOIR se rafraîchir (poll 2 s)

| Étape | Ce qui s'affiche |
|---|---|
| Bake | barre `X/Y` pièces + ligne provenance des sources |
| Training | **époque N/total**, loss courante + best, temps écoulé + ETA, `device: cuda` |
| Logs | les 500 dernières lignes (bloc dépliable) |
| Fin | `done` → recap (version, R@1) ; ou `failed`/`benchmark_failed` + raison |
| Benchmark | tourne sur les **96 photos device** de la cohorte (eval_real_norm) |

Si l'écran reste « En attente… » au tout début, c'est normal : c'est la phase bake
avant que le training n'écrive son premier JSON de progression.

## 3. À savoir / pièges

- **be-2007 & co.** : l'entraînement tourne à la maille **design_group** (canonique).
  Les standards pluri-millésimes (be-2007 ⊕ be-1999, etc.) sont **une seule classe** et
  pool leurs sources → plus de blocage préflight « 1 source < m_per_class=4 ». La run
  tire donc des pièces **hors-cohorte** (membres des mêmes groupes) — attendu.
- **Ne touche aucun fichier `serving/*.py` pendant la run** si jamais tu repasses en
  `ml:api` (`--reload`) : ça redémarre uvicorn et tue le subprocess. D'où `api-prod`.
- **Bench à 0 photo** : corrigé (le bench pointe les centroïdes de l'itération, pas
  `prod/current`). Si ça réapparaît, vérifier `lab/iterations/<iid>/embeddings/embeddings_v1.json`.
- **Supprimer une itération bloquée en `running`** : si un subprocess est mort en
  laissant un run `running`, le DELETE refuse → passer le `benchmark_runs`/`training_runs`
  concerné à `failed` avant.

## 4. Vérifs post-run (artefacts écrits)

```bash
IID=<iteration_id>
ls ml/lab/iterations/$IID/{checkpoints/best_model.pth,tflite/*.tflite,embeddings/embeddings_v1.json,dataset/class_manifest.json,metrics/per_class_metrics.json}
```

## 5. Tests (sanity local, optionnel)

```bash
cd ml && .venv/bin/python -m pytest tests/test_lab_api.py tests/test_augmentation.py tests/test_augmentation_api.py -q   # 50 verts
```
_(NB : la suite complète a ~17 échecs pré-existants hors-scope — benchmark bare-import,
normalize_listing, référentiel — non liés au lab training.)_
