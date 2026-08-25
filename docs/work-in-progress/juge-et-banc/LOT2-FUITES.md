# Lot 2 — couper les trois fuites, explicitement

> **Fait le 2026-08-25.** Ce document liste ce qui a changé (`fichier:ligne`),
> colle la sortie des **quatre mutations** qui prouvent que les gardes gardent,
> recopie le nouveau commentaire de `compute_embeddings.py`, et dit ce qui n'a
> **pas** pu être établi.
>
> Le défaut corrigé est celui de [`PROBLEME.md`](./PROBLEME.md) §1 et §1bis : le
> corpus device (`ml/datasets/eval_real_norm/`) servait à la fois de split de
> validation, de source des centroïdes et de juge. Aucune ligne de ce lot ne
> mesure le biais — il rend seulement la fuite **impossible en silence**.
>
> Aucun entraînement lancé, aucune écriture en base, aucun commit.

## 0. État de la suite de tests

| | |
|---|---|
| Baseline avant le lot | `2267 passed, 0 failed` (`cd ml && ./.venv/bin/python -m pytest tests -q -p no:randomly`) |
| Après le lot | `2291 passed, 0 failed` — **+24**, dont 16 écrits ici et 8 par les lots parallèles |
| Tests neufs de ce lot | 2 dans `ml/tests/test_benchmark.py`, 14 dans `ml/tests/test_juge_et_banc_fuites.py` |

## 1. Fuite (a) — les centroïdes fabriqués avec les photos du juge

| Fichier:ligne | Changement |
|---|---|
| `ml/training/pipeline.py:350-363` (`_compute_embeddings`) | `--centroid-source` est passé **toujours**, valeur `row.config.get("centroid_source", "train_mean")`. Le défaut `auto` de `compute_embeddings` ne peut plus être emprunté par le pipeline |
| `ml/serving/iteration_runner.py:991-996` | `config["centroid_source"]` posé explicitement depuis `iteration.training_config`, défaut nommé `train_mean` |
| `ml/training/compute_embeddings.py:83-111` | Commentaire périmé **réécrit** (recopié au §5) |
| `ml/training/compute_embeddings.py:26-45` | Nouvelle fonction `describe_auto_source()` : le défaut `auto` est **conservé** pour les appels manuels, mais journalise un WARNING **nommant la source réellement retenue** et le nombre de fichiers dans `val/` |
| `ml/training/compute_embeddings.py:262-268` | Aide `--centroid-source` réécrite : dit que `train_mean` est la valeur à utiliser et que `val_mean` fuite le juge |

La chaîne est désormais lisible d'un seul `grep` :

```
$ grep -rn "centroid_source" ml/serving/iteration_runner.py ml/training/pipeline.py
ml/training/pipeline.py:357:        centroid_source = row.config.get("centroid_source", "train_mean")
ml/training/pipeline.py:362:            "--centroid-source", str(centroid_source),
ml/serving/iteration_runner.py:994:        config["centroid_source"] = (iteration.training_config or {}).get(
ml/serving/iteration_runner.py:995:            "centroid_source", "train_mean"
```

## 2. Fuite (b) — le corpus device comme split de validation

| Fichier:ligne | Changement |
|---|---|
| `ml/training/prepare_dataset.py:478-488` | Drapeau `--val-source {device,ebay,none}`, `default=None` |
| `ml/training/prepare_dataset.py:547-566` (`main`) | **Obligatoire** avec `--skip-train-split` (mode lab) : `SystemExit` nommant `device|ebay|none`. Hors mode lab, absence → `device` (comportement historique) mais **avec un WARNING qui le nomme** |
| `ml/training/prepare_dataset.py:196-202` | `split_dataset()` prend `val_source` en paramètre **sans défaut** |
| `ml/training/prepare_dataset.py:243-249` et `:314-318` | `_override_val_with_eval_real` n'est appelée **que si** `val_source == "device"` — elle n'est **pas** supprimée (legacy + diagnostic) |
| `ml/training/prepare_dataset.py:320-333` | Nouvelle `_announce_no_device_val()` : `none` → message explicite ; `ebay` → `SystemExit` « n'existe pas encore » (un `val/` vide en silence serait le défaut qu'on corrige) |
| `ml/training/prepare_dataset.py:387-394` | À l'entrée de `_override_val_with_eval_real`, un WARNING dit que **ce run n'est pas comparable au juge** |
| `ml/serving/iteration_runner.py:982-990` | `config["val_source"]` posé explicitement depuis `iteration.training_config` (défaut nommé `device`) |
| `ml/training/pipeline.py:262-277` (`_prepare`) | Passe `--val-source` ; en mode itération (`iter_dir`), **refuse** (`RuntimeError`) si `val_source` est absent de la config |

Le point d'entrée réel refuse bien, **code de sortie lu sans pipe** :

```
$ cd ml && ./.venv/bin/python -m training.prepare_dataset --skip-train-split \
    --class-kind design_group --raw-dir datasets --output-dir /tmp/pd ; echo "exit=$?"
--val-source est OBLIGATOIRE avec --skip-train-split (mode lab). Choisis device|ebay|none.
Il n'y a pas de défaut : l'ambiguïté est exactement ce qui a laissé le corpus device servir
de split de validation ET de juge du benchmark
(cf. docs/work-in-progress/juge-et-banc/PROBLEME.md §1).
exit=1
```

⚠️ La commande de la mission (`python training/prepare_dataset.py …`) échoue
avant d'arriver au garde : `ModuleNotFoundError: No module named 'training'`,
`exit=1`. Le script ne s'invoque que par `-m training.prepare_dataset` (c'est
d'ailleurs ce que fait `scripts/recrop_with_config.py:91`). Sans
`--class-kind`, argparse sort en `exit=2` avant le garde — le garde est bien
**après** le parsing.

## 3. Fuite (c) — le garde qui gardait un dossier mort

| Fichier:ligne | Changement |
|---|---|
| `ml/training/train_embedder.py:55-73` | `REAL_PHOTOS_DIR` → **`REAL_PHOTO_ROOTS`**, un tuple : `ml/data/real_photos` (legacy, absent du disque), `ml/datasets/eval_real_norm` (le juge device actuel), `ml/state/scan_corpus` (frames de scan rejouables) |
| `ml/training/train_embedder.py:76-98` | `_assert_no_real_photos` boucle sur les racines et **nomme celle qui a déclenché** dans le message |
| `ml/training/prepare_dataset.py:336-361` | **Second garde, de CONTENU** : `_assert_val_holdout_free(output_dir, val_source)` — en mode lab, si `val_source != "device"` alors `val/` doit être **vide**, `SystemExit` sinon. C'est la seule formulation posée sur le chemin réellement emprunté : la fuite passe par une **copie de fichiers**, pas par un chemin de dataset |
| `ml/tests/test_benchmark.py:115-171` | Les 2 tests existants **conservés** (monkeypatch adapté au nouveau nom, et un commentaire qui dit qu'ils n'exercent qu'une racine fabriquée) + 2 tests neufs sur les racines **réelles**, sans monkeypatch |

`ml/state/scan_corpus` n'existe pas encore sur le Mac : le garde est **lexical**
(`Path.resolve()` non strict), il n'a pas besoin que le répertoire existe.
Aucun appelant existant n'est cassé — `prepare_dataset` passe `--raw-dir
ml/datasets`, qui est un **parent** de `eval_real_norm`, pas un descendant.

## 4. Les quatre mutations — sortie collée

Discipline `eurio-verify` : *un garde dont aucune mutation ne fait rougir un
test n'est pas un garde.* Sauvegardes dans le scratchpad, restauration par
`cat backup > fichier`, retour au vert vérifié après **chacune**.

### Mutation 1 — retirer `ml/datasets/eval_real_norm` de `REAL_PHOTO_ROOTS`

```
        target = te.ML_DIR / "datasets" / "eval_real_norm" / "fr-2euro-standard-t1"
>       with pytest.raises(SystemExit) as exc:
E       Failed: DID NOT RAISE <class 'SystemExit'>

tests/test_benchmark.py:144: Failed
FAILED tests/test_benchmark.py::test_hold_out_gate_covers_eval_real_norm
1 failed, 12 passed in 1.55s
--- revert vérifié ---
13 passed in 1.54s
```

### Mutation 2 — retirer `ml/state/scan_corpus` de `REAL_PHOTO_ROOTS`

```
        target = te.ML_DIR / "state" / "scan_corpus" / "frames" / "abc123.jpg"
>       with pytest.raises(SystemExit) as exc:
E       Failed: DID NOT RAISE <class 'SystemExit'>

tests/test_benchmark.py:161: Failed
FAILED tests/test_benchmark.py::test_hold_out_gate_covers_scan_corpus
1 failed, 12 passed in 1.60s
--- revert vérifié ---
13 passed in 1.60s
```

### Mutation 3 — neutraliser le garde de contenu sur `val/`

(`return` posé en tête de `_assert_val_holdout_free`)

```
        val_cls = out / "val" / "fr-2euro-standard-t1"
        (val_cls / "fr-2007-2eur__step3.jpg").write_bytes(b"x")
>       with pytest.raises(SystemExit) as exc:
E       Failed: DID NOT RAISE <class 'SystemExit'>

tests/test_juge_et_banc_fuites.py:139: Failed
FAILED tests/test_juge_et_banc_fuites.py::test_val_holdout_guard_rejects_non_empty_val
1 failed, 13 passed in 1.55s
--- revert vérifié ---
14 passed in 1.60s
```

### Mutation 4 — retirer `--centroid-source` de `pipeline.py`

```
        cmd = captured[0]
>       assert cmd[cmd.index("--centroid-source") + 1] == "arcface_w"
E       ValueError: '--centroid-source' is not in list

tests/test_juge_et_banc_fuites.py:65: ValueError
FAILED tests/test_juge_et_banc_fuites.py::test_compute_embeddings_always_passes_centroid_source
FAILED tests/test_juge_et_banc_fuites.py::test_compute_embeddings_centroid_source_comes_from_config
2 failed, 12 passed in 1.59s
--- revert vérifié ---
14 passed in 1.60s
```

## 5. Le nouveau commentaire de `compute_embeddings.py`, recopié

`ml/training/compute_embeddings.py:83-111` :

```python
    # Stratégie de centroïde par classe — trois sources possibles :
    #
    #   (a) train_mean — moyenne des embeddings du split train. **C'est la
    #       source à préférer**, et c'est celle que `training/pipeline.py`
    #       passe explicitement.
    #   (b) arcface_w — prototype ArcFace W.
    #   (c) val_mean — moyenne des embeddings du split val.
    #
    # ⚠️ Le commentaire qui vivait ici jusqu'au 2026-08-25 argumentait
    # l'inverse : il recommandait (c) en s'appuyant sur un diagnostic
    # « R@1 = 95,83 % par KNN sur val contre 50 % déployé via W ». Ce chiffre
    # porte sur **24 images / 4 classes, avril 2026, zéro crop eBay en base** —
    # il n'a jamais été reproduit à l'échelle, et il a été **réfuté deux fois** :
    #
    #   • docs/model-efficiency/C1-reliable-centroids.md — 2026-06-11, n = 317
    #     photos : train_mean 82,97 % > arcface_w 82,65 % > val_mean 77,60 %,
    #     val_mean est le PIRE des trois ; il ne couvrait que 27 classes / 546.
    #   • docs/work-in-progress/scan-quality/exp-02-centroids-arcfacew.md —
    #     2026-07-06, n = 73 frames appariées, test de McNemar :
    #     train_mean 0,7671 (+8,2 pts) > arcface_w 0,7397 > val_mean 0,6849 ;
    #     p = 0,180 — un défaut de PUISSANCE (n = 73), pas un défaut de
    #     train_mean.
    #
    # 🔴 Et surtout : `prepare_dataset` remplit `val/` avec le corpus device
    # `ml/datasets/eval_real_norm/`, qui est **le juge du benchmark**. Prendre
    # val_mean, c'est fabriquer le prototype d'une classe à partir des photos
    # qui la testent — une fuite d'étiquette directe, pas un biais de quelques
    # points. Cf. docs/work-in-progress/juge-et-banc/PROBLEME.md §1bis.
```

## 6. Ce que je n'ai pas pu établir

| # | Ce qui reste ouvert |
|---|---|
| 1 | **Combien vaut le biais** (Q6 du PROBLEME). Il faudrait rejouer le run du 2026-08-16 contre un juge propre — un entraînement, donc hors périmètre de ce lot. Le `r@1 = 92,4 %` reste **non interprétable** ; ce lot empêche seulement de le refabriquer |
| 2 | **`--val-source=ebay` n'est pas implémenté** et sort en `SystemExit` explicite. Le prélèvement eBay est le §3 du PROBLEME et n'a pas été tranché (Q2/Q3) — le construire silencieusement vide aurait été le même défaut, autrement habillé |
| 3 | **La valeur par défaut `device` est conservée en amont** (`iteration_runner`, et mode legacy de `prepare_dataset`). Le comportement historique est donc préservé, mais il **le dit** désormais. Basculer ce défaut sur `none` est une décision produit (Q4 : sans val, la sélection de checkpoint devient « dernier epoch »), pas une décision de ce lot |
| 4 | **`ml/state/scan_corpus` n'existe pas sur le Mac.** Le garde y est vérifié lexicalement, jamais contre un vrai fichier. Si le lot corpus déplace ce répertoire, la racine doit suivre |
| 5 | **Aucun run réel n'a exercé la chaîne complète.** Les tests couvrent la construction des lignes de commande et les deux gardes ; ils ne prouvent pas qu'un `iteration_runner` de bout en bout aboutit — cela demanderait un entraînement, interdit ici |
| 6 | **Les appelants hors dépôt** (VPS, notebooks, invocations manuelles historiques) qui feraient `--skip-train-split` sans `--val-source` échoueront désormais bruyamment. C'est voulu, mais je n'ai pas pu inventorier ces appelants |
