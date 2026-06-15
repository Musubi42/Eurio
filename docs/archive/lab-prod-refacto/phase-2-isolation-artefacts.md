# Phase 2 — Artefacts isolés par `iteration_id`

> **Statut** : 🔲 à implémenter. Ne bloque pas l'expérimentation
> immédiate (le mode "destructif par itération" déjà câblé dans
> `iteration_runner.py:871-884` permet de tenir).
>
> **Pré-requis** : phase 1 livrée (label space cohérent). Sans phase 1,
> isoler des artefacts incomplets ne sert à rien.
>
> **Débloque** : comparaison inter-itérations, rollback, et la
> sémantique `prod/current/` de la phase 3.

## Objectif

Tout artefact produit par un training lab vit sous
`ml/lab/iterations/<iteration_id>/`. Aucune itération ne peut polluer
une autre, et le mode "destructif par itération" peut être retiré.

## Structure cible (rappel de [`vision.md`](./vision.md))

```
ml/lab/iterations/<iteration_id>/
├── dataset/
│   ├── train/<eurio_id>/sample_*.jpg   ← symlinks
│   ├── val/<eurio_id>/*.jpg
│   └── class_manifest.json
├── checkpoints/
│   ├── best_model.pth
│   └── training_log.json
├── embeddings/
│   └── embeddings_v1.json
├── tflite/
│   ├── eurio_embedder_v1.tflite
│   └── model_meta.json
├── metrics/
│   └── per_class_metrics.json
└── reports/
    └── benchmark_<bench_id>.json
```

## Ce qui change pour chaque consommateur

### `train_embedder.py`

- Reçoit en plus `--iteration-output-dir <path>` qui devient le racine
  pour `best_model.pth` et `training_log.json` (au lieu de
  `ml/checkpoints/`).
- Le code interne qui écrit "best_model.pth" doit lire ce flag.

### `compute_embeddings.py`

- Reçoit `--val-dir <path>` (au lieu de lire `ml/datasets/eurio-poc/val`)
  et `--output <path>` (au lieu de `ml/output/embeddings_v1.json`).

### `export_tflite.py`

- Reçoit `--model <path>` (déjà câblé) et `--output-dir <path>` (déjà
  câblé partiellement) — vérifier qu'aucun chemin n'est résolu en dur.

### `validate_per_class.py`

- Reçoit `--val-dir`, `--embeddings`, `--output`.

### `iteration_runner.py`

- Calcule `iter_dir = ML_DIR / "lab" / "iterations" / iteration.id` au
  début de `_launch_training`.
- Crée `iter_dir/{dataset,checkpoints,embeddings,tflite,metrics,reports}/`.
- Passe les chemins explicitement au `training_runner`.
- **Retire** le bloc "destructif par itération" (lignes ~871-884
  aujourd'hui) — il devient inutile parce que aucune itération ne
  voit l'état d'une autre.

### `training_runner.py`

- `_prepare()` écrit dans `iter_dir/dataset/` au lieu de `eurio-poc/`.
- `_compute_embeddings()`, `_validate_per_class()` lisent/écrivent
  dans `iter_dir/...`.
- `_seed()` est **commenté** ou conditionné à un flag explicite (la
  vraie suppression vient en phase 3).
- `_delete()` n'a plus besoin de toucher Supabase ni `eurio-poc/` —
  il devient un nettoyage local de `iter_dir/dataset/<class>/` (pour
  un edge case : remove + re-add d'une même classe en cours
  d'itération, rare mais existant).

### Ce qui n'a PAS besoin de bouger

- `iteration_augmentations.py` : déjà bien isolé. `iterations/<iid>/`
  reste le staging dataset, on y ajoute juste les val/.
- `<numista_id>/augmentations/<iid>/` : reste à sa place.
- `state/training.db`, `state/training_progress/`, `state/live_test_logs/` :
  déjà indexés par iid.

## Compat avec les consommateurs en aval

Pendant la phase 2, certains consommateurs lisent encore
`ml/output/embeddings_v1.json` :

- `seed_supabase.py`
- `build_cohort_bundle.py`

Solution transitoire : à la fin du training d'une itération, on
**copie** (ou symlink) `iter_dir/embeddings/embeddings_v1.json` vers
`ml/output/embeddings_v1.json`. Idem pour les autres outputs.
La copie est "la dernière itération qui a tourné = ce qui est dans
output/". Pas idéal mais préserve la rétrocompat le temps que phase 3
et phase 4 finalisent l'isolation.

À la fin de phase 4, plus aucun consommateur ne lit `ml/output/`
directement, on peut retirer la copie.

## Sémantique du mode "destructif" actuel

Le bloc `iteration_runner.py:871-884` qui calcule
`removed = current_classes - eurio_ids` et le passe à `start_run`
était là **uniquement** pour compenser l'absence d'isolation. Une
fois la phase 2 livrée :

```python
# REMOVE in phase 2 — no longer needed once each iteration owns its
# own checkpoint/dataset/embeddings under lab/iterations/<iid>/.
keep = set(eurio_ids)
removed = [c for c in self._training_runner.current_classes()
           if c.class_id not in keep]
```

Devient simplement :

```python
removed = []  # iteration is self-contained
```

Et le step `_delete` ne fait quasi-rien (pas de purge inter-itération
nécessaire).

## Critères d'acceptation

1. ✅ Lancer une nouvelle itération crée
   `ml/lab/iterations/<iid>/{dataset,checkpoints,embeddings,tflite,metrics,reports}/`
   complets après la fin du training.
2. ✅ `ml/datasets/eurio-poc/` n'est **pas** modifié par une itération
   lab (peut être vide ou laissé tel quel ; la phase 4 décide si on
   le supprime).
3. ✅ Lancer deux itérations différentes en parallèle (séries) ne
   partage aucun fichier — chaque `iter_dir/` est intact.
4. ✅ `ml/output/embeddings_v1.json` (et le tflite) est mis à jour à
   la fin du training par copie depuis l'itération qui vient de finir
   (pour préserver les consommateurs aval pas encore migrés).
5. ✅ Le mode "destructif par itération" est **retiré** du code, avec
   une référence dans le commit qui pointe vers ce doc.

## Pièges à éviter

- **Symlinks vs copies.** Pour les samples bakés, les symlinks
  existants (`iterations/<iid>/<eurio_id>/sample_*.jpg` →
  `<nid>/augmentations/<iid>/sample_*.jpg`) restent. Pour les outputs
  de training (best_model, embeddings), on copie — un symlink dans
  `ml/output/` cassé après refactor d'un autre dossier serait une
  source de bugs.
- **Concurrence.** Si deux itérations tournent en parallèle (même si
  c'est verrouillé par le single global lock du
  `iteration_runner._lock`, vérifier), aucun chemin partagé ne doit
  être en write/write. Tout est sous `iter_dir/`, donc OK by design.
- **Recovery on boot.** Le `_rehydrate` du training_runner n'a pas
  besoin de changer (il agit sur la DB). Mais vérifier qu'il ne lit
  pas un chemin singleton qui n'existe plus.

## Sortie

À la fin de phase 2 :

- Chaque itération est un univers complet et fermé.
- Le mode destructif est retiré.
- Les consommateurs aval (Supabase seed, bundle Android) lisent encore
  `ml/output/` mais via une copie post-training. La phase 3 et la
  phase 4 finissent l'isolation.

Update `progress.md`.
