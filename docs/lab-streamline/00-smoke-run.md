# Chunk 00 — Smoke-run (validation du flow)

> **But** : prouver que les données *flow au bon endroit au bon moment*, avant le
> gros run PC sur les 17. Petit run : **2 classes, 3 epochs**, sur le Mac.
> Ce n'est PAS une mesure de qualité — juste un test de plomberie end-to-end.

## Périmètre

Sous **doctrine A** (captures device = hold-out). On valide la chaîne :

```
cohort (2 coins) → captures device synced (HOLD-OUT)
                 → bake augmentations Numista (TRAIN)
                 → train ArcFace 3 epochs
                 → export TFLite
                 → benchmark R@1 sur captures device
                 → artefacts au bon endroit
```

> eBay + review NE sont PAS dans ce smoke-run (chunks 03–04). On valide d'abord le
> cœur training/bench avec les sources déjà présentes (Numista + captures device).

## Les 2 classes choisies

Prises parmi les 5 dont le slug matche entre CSV et device pull (pas de
réconciliation nécessaire) :

| eurio_id | numista_id | Pourquoi |
|---|---|---|
| `fr-2008-2eur-french-presidency-of-the-council-of-the-european-union` | 3561 | slug match exact, design distinct |
| `fr-2018-2eur-simone-veil` | 141382 | slug match exact, design distinct |

## Pré-vols (vérifiés 2026-06-02)

- [x] `ml/datasets/3561/obverse.jpg` et `ml/datasets/141382/obverse.jpg` présents (source training). ✅
- [x] Captures device présentes pour les 2 coins dans `debug_pull/20260429_214408/eurio_debug/eval_real/`. ✅ (6 steps `*_crop.jpg` + `*_raw.jpg` chacun)
- [x] Mode capture du pull existant = **LEGACY** (6 steps × 1 photo), PAS ablation — alors que le CSV est passé `# mode=ablation` depuis. ⚠️ Sans impact pour le smoke ; mais le **hold-out final des 17 devra être re-pullé** (slugs corrigés + mode ablation cohérent).
- [ ] ML API up + runner idle (à checker au moment du lancement).

## Étapes

> Le but est de passer **par le lab** autant que possible (c'est ce qu'on
> streamline). Les commandes CLI ne sont là qu'en secours / pour comprendre ce que
> le lab déclenche sous le capot.

1. **Reset lab** — supprimer les cohorts/itérations de test existantes
   (`DELETE /lab/cohorts/{id}` pour chaque). Garde datasets/images/captures.
2. **Créer la cohort smoke** `smoke-2` avec les 2 eurio_ids
   (via `CohortNewPage`, textarea — l'import CSV est le chunk 01, pas requis ici).
3. **Sync captures device** (hold-out) — `POST /lab/cohorts/{id}/captures/sync`
   avec `pull_dir=debug_pull/20260429_214408`.
   → vérifier l'écriture dans `ml/datasets/{3561,141382}/captures/` et
   `ml/datasets/eval_real_norm/{eurio_id}/`.
4. **Créer une itération** sur `smoke-2` : `variant_count` petit (ex. 20 pour aller
   vite), `training_config = { epochs: 3, batch_size: 32, m_per_class: 4 }`.
5. **Bake** — `POST .../iterations/{iid}/bake`.
   → vérifier `ml/datasets/{nid}/augmentations/{iid}/*.jpg` (~20/classe).
6. **Launch training** — `POST .../iterations/{iid}/launch-training`.
   → suivre le monitor live (loss/epoch), 3 epochs.
7. **Vérifier les artefacts** (checklist ci-dessous).

## Checklist « le bon fichier au bon endroit »

| Quand | Fichier attendu | Sens |
|---|---|---|
| après sync | `ml/datasets/3561/captures/*.jpg`, `ml/datasets/141382/captures/*.jpg` | hold-out normalisé |
| après sync | `ml/datasets/eval_real_norm/<eurio_id>/*.jpg` | split val/bench |
| après bake | `ml/datasets/<nid>/augmentations/<iid>/*.jpg` | sources training augmentées |
| après prepare | `ml/datasets/eurio-poc/{train,val,test}/<class>/*.jpg` | dataset splitté |
| après train | `ml/checkpoints/best_model.pth` | checkpoint |
| après train | `ml/state/training_progress/<iid>.json` | télémétrie live |
| après export | `ml/output/eurio_embedder_v1.tflite` | modèle quantifié |
| après embed | `ml/output/embeddings_v1.json` | centroïdes (2 classes) |

## Critères de succès (plomberie, pas qualité) — ✅ TOUS VERTS

- [x] L'itération atteint `status=completed` (cohort `smoke-2`, itération `smoke-plumbing-4` = `53caddf5ab54`).
- [x] Captures device JAMAIS dans `train/` — `train/<class>/` = 10 augmentations bakées (depuis obverse) ; `val/<class>/` = 6 device snaps. Mur train/bench tenu.
- [x] Artefacts présents : `checkpoints/best_model.pth`, `tflite/eurio_embedder_v1.tflite`, `embeddings/{coin_embeddings,embeddings_v1}.json`, `metrics/per_class_metrics.json`, `dataset/class_manifest.json` — tous sous `ml/lab/iterations/53caddf5ab54/`.
- [x] Benchmark sur captures device : per-class **R@1=1.0** (2 classes triviales) ; training_log 3 epochs, loss → 0.
- [x] Aucune écriture Supabase (`_seed` skip en mode iter_dir ; resolver lit eurio.db).

## Bugs de câblage révélés par le smoke (et corrigés)

1. **`--only-classes` = tout le catalogue** au lieu des coins de la cohort.
   `training_runner._prepare` utilisait `classes_after` (registre global model_classes)
   pour une itération lab. → fix : itérations (iter_dir) utilisent `classes_added`.
2. **Resolver tapait Supabase (404)** — viol doctrine SQLite-only.
   `class_resolver.build_resolver` → `fetch_coin_refs(Supabase)`. → fix : nouveau
   `coin_refs_from_sqlite()` lit `eurio.db` (689 coins, numista_id colonne directe) ;
   `build_resolver` rebranché dessus. `fetch_coin_refs` (Supabase) laissé pour le
   tool legacy `eval/equivalence.py` (hors scope).
3. **`ModuleNotFoundError: No module named 'eval'`** dans le subprocess training.
   `_run_subprocess` ne fixait pas `PYTHONPATH` → ne marchait que si le serveur était
   lancé avec `PYTHONPATH=ml` (fragile, cassé après reload uvicorn). → fix : Popen
   force `PYTHONPATH=ML_DIR:…`.

Bonus : log « from Supabase » → « from eurio.db » dans `prepare_dataset.py`.

## Fichiers touchés

- `admin/.../features/lab/csv.ts` (nouveau) + `CohortNewPage.vue` — import CSV (chunk 01).
- `ml/api/training_runner.py` — `_prepare` (classes_added) + `_run_subprocess` (PYTHONPATH).
- `ml/eval/class_resolver.py` — `coin_refs_from_sqlite` + `build_resolver` sur eurio.db.
- `ml/training/prepare_dataset.py` — message de log.

## Journal

- 2026-06-02 — doc créée, plan posé.
- 2026-06-02 — reset lab (5 cohorts test purgées), chunk 01 import CSV livré, smoke
  run exécuté : 3 bugs câblage trouvés+corrigés, itération `53caddf5ab54` **completed**.
  Flow validé end-to-end. Prêt pour le câblage eBay/review puis le run PC des 17.
