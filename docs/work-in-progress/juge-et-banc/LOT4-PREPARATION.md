# Lot 4 — préparer les deux runs jumeaux, et mesurer ce qu'ils coûteront

> Fait le **2026-08-25** sur le Mac (`Musubi42s-MacBook-Air-Oim`, Apple M3),
> branche `repo-cleanup`. **Aucun entraînement complet lancé** : deux epochs de
> calibration, isolés, hors pipeline, sans écriture en base. Aucun commit,
> aucun push, rien sur le VPS, rien sur MinIO.
>
> Chaque chiffre porte sa commande. Les estimations sont marquées ⚠️.
>
> 🟢 **Le run A démarrera** — le `SystemExit` qu'on redoutait ne peut pas se
> déclencher en mode lab (§1). Vérifié en jouant la préparation pour de vrai.
>
> 🔴 **Deux obstacles bloquent le protocole tel qu'il est écrit**, et aucun des
> deux ne se voit depuis l'écran :
> 1. la route de création d'itération **ne savait pas transporter
>    `augmentations_seed`** — les deux « jumeaux » auraient reçu des
>    augmentations différentes (§4) ;
> 2. `POST …/launch-training` répond **HTTP 200**, laisse l'itération en
>    `pending`, `error: null` — et le job détaché meurt dans la seconde en
>    `attempt to write a readonly database` (§5).

---

## 0. Ce qui a été créé pendant ce lot

| Objet | Id | État |
|---|---|---|
| Clone de `ab28928bcdc2` | **`70c74956061f`** (`juge-banc-l4-ab`) | `frozen` — 27 eurio_ids, identiques à la source |
| Itération de calibration | `8bbe7ac6c2ac` (`calib-1epoch`) | `pending`, bakée (6594 samples). **Ne sert qu'à mesurer** — à supprimer ou à ignorer |

```bash
curl -s -X POST "http://127.0.0.1:8042/lab/cohorts/ab28928bcdc2/clone" \
  -H "Content-Type: application/json" \
  -d '{"name":"juge-banc-l4-ab","description":"…"}'
# → {"id":"70c74956061f", … "status":"draft"}
```

⚠️ Le nom doit être en **kebab-case minuscule** (`_validate_name`) : un nom avec
majuscules rend `400`, pas une correction silencieuse.

Préflight du clone, avant tout gel :

```bash
curl -s "http://127.0.0.1:8042/lab/cohorts/70c74956061f/training-readiness"
# ready True | n_classes 24 | blocked 0 | warned 0
```

---

## 1. 🟢 Le run A démarrera — et pas pour la raison qu'on croyait

**La crainte** : `_override_val_with_eval_real` lève `SystemExit` si une classe
de la cohorte n'a pas de dossier dans `ml/datasets/eval_real_norm/`.

**Le fait** : ce `SystemExit` est conditionné à `class_kind == "eurio_id"`
(`prepare_dataset.py:411-416`), et le mode lab **passe toujours
`design_group`** :

```bash
grep -n 'config\["class_kind"\]' ml/serving/iteration_runner.py
#   981:        config["class_kind"] = "design_group"
```

En `design_group`, une classe sans dossier device est **silencieusement sautée**
(`continue`) — sa val reste vide, elle n'entre simplement pas dans le split de
validation. Le garde existe, il n'est jamais armé sur le chemin réel. C'est le
motif « un garde posé sur le chemin qu'on avait en tête » du catalogue
`eurio-verify` — ici, à notre avantage.

### L'intersection, à la maille qui décide

⚠️ **Compter les noms de dossiers contre les `eurio_ids` de la cohorte donne un
faux chiffre.** À la maille brute : 17 des 27 eurio_ids ont un dossier, 10 n'en
ont pas. Mais `_override_val_with_eval_real` cherche un dossier pour **n'importe
quel membre du `design_group`** de la classe. Le bon dénominateur est donc les
**24 classes**, pas les 27 pièces.

```bash
cd ml && ./.venv/bin/python - <<'PY'
import json, sqlite3, sys; from pathlib import Path; sys.path.insert(0,'.')
db='state/eurio.replica.db'; con=sqlite3.connect(f'file:{db}?mode=ro',uri=True)
ids=json.loads(con.execute("select eurio_ids_json from experiment_cohorts "
                           "where id='ab28928bcdc2'").fetchone()[0])
from store.class_resolver import build_resolver
descs,_=build_resolver(force_eurio_id=False, db_path=Path(db)).classes_for_eurio_ids(ids)
dirs={p.name for p in Path('datasets/eval_real_norm').iterdir() if p.is_dir()}
cov=[d for d in descs if any(m in dirs for m in (list(d.eurio_ids) or [d.class_id]))]
print(len(descs), len(cov), sorted(dirs - {m for d in cov for m in d.eurio_ids if m in dirs}))
PY
# 24 17 ['fr-1999-2eur-standard-1st-map', 'mt-2008-2eur-standard-2nd-map']
```

| | |
|---|---:|
| classes de la cohorte | **24** |
| classes avec ≥ 1 membre dans `eval_real_norm/` | **17** |
| classes **sans** aucun snap device | **7** |
| dossiers `eval_real_norm/` inutilisés par cette cohorte | 2 (`fr-1999-…-1st-map`, `mt-2008-…-2nd-map`) |

Les 7 sans snap device : `eu-euro-cash-2012`, `eu-emu-2009`,
`de-2euro-standard-t1`, `es-2euro-felipe-vi-t1`,
`de-2020-2eur-brandenburg-the-bundeslander-series`,
`fi-2016-…-eino-leino`, `fr-2016-2eur-euro-2016-football-championship`.

### La preuve, jouée — pas déduite

La préparation du run A a été exécutée pour de vrai sur le clone bakée :

```bash
cd ml && ./.venv/bin/python -m training.prepare_dataset \
  --only-classes "<les 24 class_id>" --class-kind design_group \
  --val-source device --output-dir "$PWD/lab/iterations/8bbe7ac6c2ac/dataset" \
  --skip-train-split --prebaked-staging-dir "$PWD/datasets/iterations/8bbe7ac6c2ac"
; echo "exit=$?"
# WARNING [--val-source=device] : … ce run N'EST PAS comparable au juge …
#   (17 lignes « 6 device snaps → val/ »)
# Device val total: 102 images
# exit=0
```

**`exit=0`. 17 classes, 102 images.** Pas besoin de la maille `design_group` de
secours proposée dans la mission : elle est **déjà** la maille par défaut, et
c'est elle qui sauve le run.

### 🔴 Ce qui compte davantage : les deux runs auront le MÊME espace de labels

C'était le vrai risque, et il fallait le vérifier avant de dépenser 90 minutes.
`--centroid-source auto` (run A) ne produit **pas** 17 centroïdes :

- les 17 classes avec val device → centroïde `val_mean` — **la fuite** ;
- les 7 sans val → **repli sur `arcface_W`** (`compute_embeddings.py:158-162`,
  la branche `source in ("auto", "arcface_w") … or cls_name not in
  class_embeddings`).

Run A rend donc **24 centroïdes**, run B (`train_mean`) aussi. `replay_corpus`
ne refusera pas de les comparer (`assert_same_label_space`, LOT3 §9.a-3).

Et une coïncidence qui sert l'expérience : **les 17 classes dont le centroïde
est fuité sont exactement les 17 classes que le juge peut noter** (§2). La fuite
porte pile là où la mesure porte — l'écart A−B ne sera pas dilué par des classes
non concernées.

---

## 2. Le recouvrement cohorte ↔ juge — le dénominateur

```bash
cd ml && ./.venv/bin/python - <<'PY'
import json, sqlite3, sys; from pathlib import Path; sys.path.insert(0,'.')
db='state/eurio.replica.db'; con=sqlite3.connect(f'file:{db}?mode=ro',uri=True)
ids=json.loads(con.execute("select eurio_ids_json from experiment_cohorts "
                           "where id='ab28928bcdc2'").fetchone()[0])
from store.class_resolver import build_resolver
from training.eval.equivalence import build_equivalence_map
descs,_=build_resolver(force_eurio_id=False, db_path=Path(db)).classes_for_eurio_ids(ids)
eq=build_equivalence_map(); mesh={eq.coalesce(d.class_id) for d in descs}
sc=sqlite3.connect('file:state/scan_corpus.db?immutable=1',uri=True)
for lab,w in (("TOUT",""),("20260429"," where bundle_source='device_pull_20260429'"),
              ("20260601"," where bundle_source='device_pull_20260601'")):
    gt=dict(sc.execute(f"select eurio_id, count(*) from scan_corpus{w} group by 1"))
    cov={k:v for k,v in gt.items() if eq.coalesce(k) in mesh}
    print(lab, sum(gt.values()), len(gt), len({eq.coalesce(k) for k in cov}), sum(cov.values()))
PY
# TOUT 451 20 17 419
# 20260429 114 19 17 102
# 20260601 337 17 16 317
```

⚠️ `state/scan_corpus.db` **ne s'ouvre pas avec `sqlite3 -readonly`**
(`unable to open database file` — WAL sans `-shm` accessible). Il faut
`file:…?immutable=1`.

| Filtre | frames | classes vérité | **classes couvertes** | **frames couvertes** |
|---|---:|---:|---:|---:|
| aucun (451) | 451 | 20 | **17 / 24** | **419** (92,9 %) |
| `device_pull_20260429` | 114 | 19 | 17 / 24 | **102** (89,5 %) |
| `device_pull_20260601` | 337 | 17 | 16 / 24 | **317** (94,1 %) |

Classes du corpus **hors** cohorte (fausses par construction, quoi que fassent
les modèles) : `fr-2euro-standard-t1`, `mt-2euro-standard-t1`,
`fr-2018-…-bleuet-de-france`.

🔴 **C'est ce dénominateur qu'il faudra lire.** Comme au lot 3, le `r_at_1_eq`
global sera dilué par ~7 % de frames non couvrables ; la valeur à comparer entre
A et B est **`r_at_1_on_covered`, avec son `n_on_covered`** — et il faut les
citer ensemble, jamais l'un seul.

**Recommandation** : noter les deux runs **sans `--bundle-source`** (451 frames,
419 couvertes). Le corpus complet donne le plus grand `n`, et le filtre par
protocole reste disponible ensuite pour vérifier que l'écart n'est pas porté par
une seule séance photo.

---

## 3. Le coût mesuré — `t_epoch`, et pourquoi il y en a **deux**

### 3.a Le bake — 4 min 01 s par run

```bash
curl -s -X POST ".../iterations/8bbe7ac6c2ac/bake"   # → 202
cd ml && ./.venv/bin/python -c "
import sys;sys.path.insert(0,'.');import jobs
print([dict(r) for r in jobs.connection().execute(
  'select id,status,started_at,finished_at,n_done from jobs order by rowid desc limit 1')])"
# status done | 2026-08-25 14:05:36 → 14:09:37 | n_done 61
# note: "6594 samples, 61 pièces"
```

| | |
|---|---:|
| durée du bake | **241 s** (4 min 01 s) |
| pièces bakées | **61** — dont 34 hors cohorte (maille `design_group`, cf. `eurio-cohort` §1) |
| samples produits | **6594** |

⚠️ **6594, pas 5051.** Le run de référence du 2026-08-16 sur la même cohorte en
produisait 5051 : le pool de crops eBay a grossi de **+30,5 %** depuis. Toute
extrapolation de durée depuis l'historique est donc fausse d'au moins ce
facteur — c'est pourquoi `t_epoch` a été mesuré et pas déduit.

La préparation du dataset (`prepare_dataset`) coûte **1,6 s** — négligeable.

### 3.b 🔴 Il y a deux `t_epoch`, pas un

`train_embedder.py:1109` : `--freeze-epochs` vaut **5** par défaut, et
`pipeline.py` ne le passe jamais. Les **5 premiers epochs gèlent le backbone**,
les suivants rétropropagent dans tout le réseau. Les deux régimes ne coûtent pas
la même chose, et un `t_epoch` unique ferait dérailler le calcul de E.

Les deux mesures, sur la config exacte du run A, **hors pipeline** (aucune
écriture en base), horodatées ligne à ligne :

```bash
cd ml && ./.venv/bin/python -u training/train_embedder.py --mode arcface \
  --dataset "$PWD/lab/iterations/8bbe7ac6c2ac/dataset/train" \
  --val-dataset "$PWD/lab/iterations/8bbe7ac6c2ac/dataset/val" \
  --epochs 1 --batch-size 256 --m-per-class 4 --device auto \
  --model-version calib-l4b --output /tmp/calib_l4b_ckpt \
  --prebaked-augmentations --iteration-id 8bbe7ac6c2ac 2>&1 | <horodateur>
# [    3.22s]   Epoch  1/1 — starting
# [  216.59s]   Epoch  1 — loss: 8.2501  R@1: 75.49%  R@3: 91.18% [frozen]

# … idem avec --freeze-epochs 0 :
# [    3.31s] --- Unfreezing backbone at epoch 1 ---
# [  359.74s]   Epoch  1 — loss: 3.6326  R@1: 96.08%  R@3: 98.04%
```

| Régime | epochs concernés | **`t_epoch` mesuré** |
|---|---|---:|
| backbone **gelé** | 1 → 5 | **213,4 s** |
| backbone **dégelé** | 6 → E | **356,4 s** (× 1,67) |

Contexte d'exécution, tel que le binaire l'a journalisé :

```
RUNTIME {"device":"mps","torch_version":"2.9.1","dataset_size":6594,
 "num_classes":24,"batch_size":256,
 "runtime":{"cpu_brand":"Apple M3","backend":"mps","num_cuda_devices":0,
            "dataloader_workers":0,"hint":"Apple Silicon (mps) — slower, OK for iterating"}}
```

`epoch_multiplier` vaut 10 (défaut, non passé par le pipeline) → un epoch voit
**65 940 images**, soit **258 pas** à `batch_size=256`, décodées par **un seul
worker** (`num_workers` tombe à 0 hors CUDA, `train_embedder.py:858`).

### 3.c La valeur de **E** que je propose : **8**

Coût d'un run = `5 × 213,4 + (E − 5) × 356,4` secondes.

| E | par run | **deux runs** | tient dans 90 min ? |
|---:|---:|---:|---|
| 8 | 2 136 s (35 min 36 s) | **4 272 s — 71 min 12 s** | ✅ avec de la marge |
| 9 | 2 493 s (41 min 33 s) | 4 985 s — 83 min 05 s | ✅ **plafond strict** (entraînement seul) |
| 10 | 2 849 s (47 min 29 s) | 5 698 s — 94 min 58 s | ❌ |

**Je propose E = 8.** Le plafond arithmétique est 9, mais le budget de 90 min
doit aussi absorber ce que la mission ne compte pas et qui existe : **2 bakes à
4 min 01 s** (8 min 02 s), les deux préparations (3 s), les embeddings et
l'export TFLite. E = 8 laisse ≈ 19 min pour tout ça ; E = 9 en laisse 7 et
transformerait le moindre imprévu en dépassement.

⚠️ **E = 8, c'est 3 epochs dégelés seulement.** Le run de référence en faisait
40. Les deux runs seront **sous-entraînés** — c'est acceptable pour une
**comparaison** (A et B subissent exactement la même privation) mais il faut le
dire : rien ne garantit que l'écart A−B à 8 epochs ait la même amplitude qu'à
40. Il peut être **plus petit** (la fuite a moins eu le temps de payer) comme
plus grand. Ce que le run établira, c'est **le signe et l'existence** de
l'écart, pas sa valeur à convergence.

### 3.d ⚠️ L'alternative qui rend le débat inutile : le PC

Le 1080 Ti a fait 40 epochs en 44 min 36 s le 2026-08-16
(`03f767f998ef`, `created_on='pc'`, `started_at 20:29:53 → finished_at
21:14:29`) — sur **5051** samples. À **6594** samples (+30,5 %), la même chose
coûterait ⚠️ **≈ 58 min**, donc ⚠️ **≈ 116 min pour deux runs à E=40**, ou
⚠️ **≈ 87 min à E=30**.

**Le PC fait en 90 minutes ce protocole à E ≈ 30 ; le Mac le fait à E = 8.**
Si le PO peut jouer les deux runs sur le PC, il obtient un résultat quatre fois
mieux entraîné pour le même temps d'attente. Le choix mérite d'être posé avant
de lancer quoi que ce soit sur le Mac.

⚠️ Ces trois chiffres PC sont des **extrapolations linéaires** en nombre de
samples, non mesurées. Le seul moyen de les fermer est de rejouer la calibration
du §3.b sur le PC — 6 minutes.

---

## 4. 🔴 Obstacle n°1 — la graine ne se posait pas (corrigé, testé)

`POST /lab/cohorts/{id}/iterations` n'avait **aucun moyen** de recevoir
`augmentations_seed` : `IterationCreatePayload` ne portait pas le champ, et
`create_iteration` ne le transmettait pas au runner — qui en tire alors une au
hasard (`iteration_runner.py:314`).

Mesuré, sur l'itération de calibration créée sans rien demander de spécial :

```bash
curl -s "…/lab/cohorts/70c74956061f/iterations" | python3 -c "…"
# 8bbe7ac6c2ac calib-1epoch pending 1842102175 {…}
#                                   ^^^^^^^^^^ tiré au hasard
```

Sans correctif, les deux runs « jumeaux » auraient reçu **deux jeux
d'augmentations différents**, et l'écart mesuré aurait mélangé la fuite et le
tirage — exactement ce que la mission cherchait à écarter. Rien ne l'aurait
signalé : la scorecard n'affiche pas la graine.

### Le correctif

`ml/serving/lab_routes.py`, deux points (non committé) :

| Ligne | Changement |
|---|---|
| `IterationCreatePayload` | nouveau champ `augmentations_seed: int \| None = None` |
| `create_iteration` | `augmentations_seed=payload.augmentations_seed` passé au runner |

Le comportement par défaut ne bouge pas : sans le champ, `None` → tirage
aléatoire, comme avant.

### Vérifié, y compris par mutation

`ml/tests/test_lab_iteration_seed.py` (neuf, 3 tests) : la route transmet la
graine ; sans elle elle transmet `None` ; et le **vrai** `IterationRunner` (pas
le stub) la persiste dans la row.

```bash
cd ml && ./.venv/bin/python -m pytest tests/test_lab_iteration_seed.py \
  tests/test_lab_api.py -q -p no:randomly ; echo "exit=$?"
# 46 passed — exit=0
```

Mutation (ligne du correctif retirée), code de sortie lu **sans pipe** :

```
MUTATION exit=1   → 2 failed, 1 passed
REVERT   exit=0   → 3 passed
```

⚠️ **L'API qui tourne sur `:8042` a été démarrée avant ce correctif**
(`ml:api-prod`, pas de `--reload`). Elle doit être redémarrée avant de créer les
itérations A et B, sinon le champ sera ignoré en silence et les graines
retomberont au hasard :

```bash
lsof -ti :8042 | xargs kill      # par PID — jamais `pkill -f` (cf. eurio-run-local)
```

Côté entraînement, il n'y a **rien d'autre à figer** : `train_embedder --seed`
vaut 42 par défaut et `pipeline.py` ne le surcharge jamais
(`grep -n '"--seed"' ml/training/pipeline.py` → aucune ligne). La seule
randomité libre était bien celle du bake.

---

## 5. 🔴 Obstacle n°2 — `launch-training` répond 200 et ne lance rien

Sous le flip Direction A (`EURIO_DB_READONLY=1`, posé par le devShell), le
lancement d'un entraînement échoue — `training_runner.create_run_row` écrit
`training_runs` dans le store, donc dans la réplique.

Ce qui est **nouveau et grave**, c'est la façon dont il échoue. Mesuré :

```bash
curl -s -X POST ".../iterations/8bbe7ac6c2ac/launch-training" -w "\nHTTP=%{http_code}\n"
# {… "status":"pending" … "error":null}
# HTTP=200

curl -s ".../iterations/8bbe7ac6c2ac" | python3 -c "…"
# pending | None
```

| Ce que l'API montre | Ce qui s'est passé |
|---|---|
| `HTTP 200` | — |
| `status: pending` | — |
| `error: null` | — |

```bash
cd ml && ./.venv/bin/python -c "
import sys;sys.path.insert(0,'.');import jobs
print([dict(r) for r in jobs.connection().execute(
  'select id,kind,status,error,started_at,finished_at from jobs order by rowid desc limit 1')])"
# {'kind':'iteration','status':'failed',
#  'error':'attempt to write a readonly database',
#  'started_at':'2026-08-25 14:25:03','finished_at':'2026-08-25 14:25:03'}
```

**Le job est mort en moins d'une seconde. Rien à l'écran ne le dit** : ni code
HTTP, ni statut d'itération, ni champ `error`. Un opérateur attendrait
indéfiniment un entraînement qui n'a jamais commencé. C'est le motif exact du
catalogue `eurio-verify` — *une valeur par défaut plausible là où il fallait une
erreur* — et il n'y figure pas encore ; il mériterait d'y entrer.

### Conséquence : les deux runs se jouent en **mode compute**, pas sous le flip

Et il y a un piège d'ordre. Le clone `70c74956061f` et ses itérations vivent
dans le **canonique** ; une `work.db` fabriquée avant leur création ne les
contient pas. La séquence doit donc être :

1. créer A et B **sous le flip** (l'API redémarrée avec le correctif §4) → les
   rows partent au canonique ;
2. `go-task ml:db:pull-replica` → la réplique les voit ;
3. `VACUUM INTO` un fichier **NEUF** ;
4. redémarrer l'API en mode compute sur ce fichier ;
5. baker, puis lancer les deux entraînements.

☠️ **Ne jamais `rm` `ml/state/eurio.work.db`.** Elle porte les
`training_runs`/`benchmark_runs` de tous les calculs faits sur cette machine,
rien ne les sauvegarde et rien ne les régénère (`eurio-run-local`). `VACUUM
INTO` refuse d'écraser — c'est une protection, pas un obstacle à contourner.

---

## 6. Les deux `training_config`, côte à côte

**Vérification en un coup d'œil : seules deux lignes diffèrent.**

| Clé | **Run A — AVEC la fuite** | **Run B — SANS** |
|---|---|---|
| `epochs` | `8` | `8` |
| `batch_size` | `256` | `256` |
| `m_per_class` | `4` | `4` |
| **`val_source`** | 🔴 **`"device"`** | 🟢 **`"none"`** |
| **`centroid_source`** | 🔴 **`"auto"`** | 🟢 **`"train_mean"`** |
| `recipe_id` (hors config) | `3e022c8bb17a` | `3e022c8bb17a` |
| `variant_count` (hors config) | `100` | `100` |
| **`augmentations_seed`** (hors config) | **`20260825`** | **`20260825`** |
| cohorte | `70c74956061f` | `70c74956061f` |

Les trois clés `m_per_class` / `min_real` / `training_target` sont **ajoutées
d'office** par la route (gel des seuils, `lab_routes.py::create_iteration`) et
seront identiques des deux côtés. Tout le reste — `class_kind`,
`prebaked_augmentations`, `mode`, `--seed 42`, `--freeze-epochs 5`,
`--epoch-multiplier 10` — est posé par `iteration_runner`/`pipeline` et ne
dépend d'aucune des deux clés qui changent.

### Ce que chaque réglage produit concrètement

| | Run A | Run B |
|---|---|---|
| `val/` | **102 images device**, 17 classes | **vide** |
| choix du checkpoint | meilleur `R@1` **sur le juge** 🔴 | **dernier epoch** (`train_embedder.py:1016-1019`) |
| centroïdes | 17 × `val_mean` 🔴 + 7 × `arcface_W` | 24 × `train_mean` |
| espace de labels | **24** | **24** |

⚠️ **L'asymétrie de sélection de checkpoint est voulue, ce n'est pas un défaut
du protocole.** A peut retenir un epoch antérieur à 8, B retient toujours le
8ᵉ. C'est précisément la fuite n°1 de [`PROBLEME.md`](./PROBLEME.md) §1 (« la
sélection de modèle se fait sur le jeu de test ») : elle fait partie de ce qu'on
mesure. Il ne faut pas la « corriger » pour rendre les runs plus jumeaux — on
supprimerait la moitié de l'expérience.

---

## 7. Les commandes exactes

**Prérequis, dans cet ordre.** Redémarrer l'API (correctif §4) :

```bash
lsof -ti :8042 | xargs kill
go-task ml:api-prod       # PAS ml:api (--reload tue les subprocess d'entraînement)
curl -s http://127.0.0.1:8042/health   # attendre {"status":"ok"}
```

### Étape 1 — créer les deux itérations (sous le flip, écriture canonique)

```bash
# Run A — AVEC la fuite
curl -s -X POST "http://127.0.0.1:8042/lab/cohorts/70c74956061f/iterations" \
  -H "Content-Type: application/json" -d '{
    "name": "l4-run-a-avec-fuite",
    "hypothesis": "val_source=device + centroid_source=auto : le juge sert de val ET de source de centroides (PROBLEME.md 1 et 1bis).",
    "recipe_id": "3e022c8bb17a",
    "variant_count": 100,
    "augmentations_seed": 20260825,
    "training_config": {"epochs": 8, "batch_size": 256, "m_per_class": 4,
                        "val_source": "device", "centroid_source": "auto"}
  }' -w "\nHTTP=%{http_code}\n"

# Run B — SANS
curl -s -X POST "http://127.0.0.1:8042/lab/cohorts/70c74956061f/iterations" \
  -H "Content-Type: application/json" -d '{
    "name": "l4-run-b-sans-fuite",
    "hypothesis": "Jumeau de A. Seuls val_source et centroid_source changent.",
    "recipe_id": "3e022c8bb17a",
    "variant_count": 100,
    "augmentations_seed": 20260825,
    "training_config": {"epochs": 8, "batch_size": 256, "m_per_class": 4,
                        "val_source": "none", "centroid_source": "train_mean"}
  }' -w "\nHTTP=%{http_code}\n"
```

🔴 **Contrôle obligatoire avant d'aller plus loin** — si la graine ne s'est pas
posée, tout ce qui suit est perdu :

```bash
curl -s "http://127.0.0.1:8042/lab/cohorts/70c74956061f/iterations" \
 | python3 -c "
import json,sys
for it in json.load(sys.stdin):
    print(it['id'], it['name'], it['augmentations_seed'], it['training_config'])"
# les DEUX doivent afficher 20260825
```

### Étape 2 — basculer en mode compute

```bash
go-task ml:db:pull-replica
nix develop .#mac --command sqlite3 ml/state/eurio.replica.db \
  "VACUUM INTO 'ml/state/eurio.work-juge-banc.db'"     # fichier NEUF, jamais un rm
lsof -ti :8042 | xargs kill
EURIO_DB_READONLY= EURIO_DB_PATH="$PWD/ml/state/eurio.work-juge-banc.db" go-task ml:api-prod
```

### Étape 3 — baker puis entraîner, un run à la fois

`<A>` et `<B>` = les deux ids rendus par l'étape 1. **Séquentiellement** : le
runner est en single-flight global, et deux entraînements concurrents sur un Mac
sans CUDA fausseraient les deux durées.

```bash
for IID in <A> <B>; do
  curl -s -X POST ".../lab/cohorts/70c74956061f/iterations/$IID/bake"          # 202
  until [ "$(curl -s ".../iterations/$IID/augmentations/job" \
            | python3 -c 'import json,sys;print(json.load(sys.stdin)["status"])')" != running ]
  do sleep 15; done
  curl -s -X POST ".../lab/cohorts/70c74956061f/iterations/$IID/launch-training"
done
```

🔴 **`HTTP 200` ne veut pas dire « ça tourne » (§5).** Après chaque lancement :

```bash
cd ml && ./.venv/bin/python -c "
import sys;sys.path.insert(0,'.');import jobs
for r in jobs.connection().execute(
  'select kind,status,error,log_path from jobs order by rowid desc limit 3'): print(dict(r))"
```

### Étape 4 — noter les deux contre le juge

```bash
cd ml
./.venv/bin/python -m scripts.replay_corpus --iteration <A> --path full \
  --out /tmp/l4_run_a ; echo "exit=$?"
./.venv/bin/python -m scripts.replay_corpus --iteration <B> --path full \
  --out /tmp/l4_run_b ; echo "exit=$?"
```

**`--path full` est une condition de validité**, pas une option de performance :
quatre normaliseurs cohabitent dans les crops stockés et `fast` mélangerait une
différence de prise de vue avec une différence de code (README §« Ce que la
session a fermé »). Ordre de grandeur : ~20 s pour 337 frames, donc ⚠️ ~27 s
pour 451.

Ce qu'il faudra lire, et **seulement** ça :

```
primary.r_at_1_on_covered   (avec n_on_covered, attendu 419)
label_space.n_covered_classes  (attendu 17 des deux côtés)
errors.n                    (doit être 0 ; sinon la mesure ne vaut rien)
```

⚠️ **Ne pas utiliser `--baseline lab/iterations/<B>` pour comparer.**
`load_candidate` fait `sorted(dir.rglob("*.tflite")) or sorted(dir.rglob("*.pth"))`
(`replay_corpus.py:101`) : si l'export TFLite a tourné, la **baseline serait
notée en int8 pendant que le candidat l'est en fp32**, et l'écart mesuré
mélangerait la fuite et la quantisation. Deux runs `--iteration` séparés, deux
scorecards, lecture manuelle.

---

## 8. Ce que je n'ai pas pu établir

| Question | Pourquoi elle reste ouverte |
|---|---|
| **Le coût réel d'un run complet** (embeddings, export TFLite, benchmark) | Le pipeline ne peut pas tourner sous le flip (§5) et je n'ai pas redémarré l'API du PO en mode compute. Seuls le bake (241 s), la préparation (1,6 s) et les deux `t_epoch` sont mesurés. Le reste est **absent du budget**, pas estimé |
| **Les trois chiffres du PC** (§3.d) | Extrapolations linéaires en nombre de samples depuis le run du 2026-08-16. Se ferment en 6 minutes : rejouer le §3.b sur le PC |
| **L'amplitude attendue de l'écart A−B** | Aucune mesure préalable. Q6 de [`PROBLEME.md`](./PROBLEME.md) est justement ce que ce lot prépare — impossible de dire à l'avance si E=8 suffit à le rendre visible |
| **Le comportement de `--val-source=none` bout en bout** | Le §1 n'a joué la préparation que pour le run A. Le garde de contenu `_assert_val_holdout_free` (L2 §3) devrait rendre `val/` vide sans erreur pour B, mais je ne l'ai **pas** exécuté sur ce dataset |
| **Le seuil `thresholds.json`** | Aucune des deux itérations n'en produira *a priori* (celle du lot 3 n'en avait pas) — donc `abstention.coverage` vaudra 1,0 des deux côtés et le matcher répondra toujours. À confirmer sur la première scorecard |
| **Ce que devient l'itération de calibration `8bbe7ac6c2ac`** | Laissée `pending` avec son bake sur disque (6594 symlinks). Elle ne gêne pas (le garde C7 ne bloque que sur `training`), mais elle traîne. À supprimer par `DELETE …/iterations/8bbe7ac6c2ac` si le PO préfère un lab propre |

---

## 9. État de la suite de tests

```bash
cd ml && ./.venv/bin/python -m pytest tests/test_lab_iteration_seed.py \
  tests/test_lab_api.py -q -p no:randomly ; echo "exit=$?"
# 46 passed — exit=0
```

Baseline du chantier : **2316 passed, 0 failed**. Ce lot ajoute **3 tests**
(`tests/test_lab_iteration_seed.py`) → attendu **2319**. Non relancée en entier
ici : la suite complète n'était pas dans le périmètre du lot, et son coût aurait
mangé le budget de calibration.

Fichiers touchés, non committés :

- `ml/serving/lab_routes.py` — 7 lignes (§4)
- `ml/tests/test_lab_iteration_seed.py` — neuf
- `ml/lab/iterations/8bbe7ac6c2ac/`, `ml/datasets/iterations/8bbe7ac6c2ac/` — artefacts de calibration (gitignorés)

Aucun fichier de `ml/training/*` ni `ml/scripts/replay_corpus.py` n'a été
modifié.
