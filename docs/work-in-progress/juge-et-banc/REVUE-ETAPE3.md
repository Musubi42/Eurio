# Revue adversariale — l'étape 3 (entraîner ArcFace sur le PC)

> Revue **en lecture seule** du 2026-08-26, faite sur le Mac
> (`Musubi42s-MacBook-Air-Oim`), branche `repo-cleanup`, `HEAD = c3db5569`.
> Aucun fichier modifié hors celui-ci, aucune écriture en base, aucun
> entraînement, aucun déploiement, aucun commit.
>
> Chaque affirmation de code porte son `fichier:ligne`. Chaque chiffre porte sa
> commande. Les estimations sont marquées ⚠️.
>
> ⏱️ **L'arbre de travail a bougé PENDANT cette revue.** À l'ouverture,
> `git status --porcelain` rendait 3 lignes (`CLAUDE.md`, `secrets/dev.env`,
> `SUIVI-MATRICE.md`). À **00:48:06** il en rend **14** : l'étape 2 (hold-out
> d'éval) est en cours d'écriture en parallèle, non committée, non déployée. Les
> constats §B0 et §B1 ci-dessous portent sur **cet arbre-là**, à cette
> heure-là — ils étaient faux une heure plus tôt et le seront de nouveau dès
> que l'étape 2 sera finie et déployée.

---

## 1. VERDICT

🔴 **Pas prêt.** L'étape 3 peut être *lancée*, mais elle ne peut pas produire le
chiffre qu'elle promet : à cette heure le préflight lui-même **plante sous le
devShell** (§B0, reproduit), le jeu d'évaluation n'est ni tiré ni déployé, et
**aucun outil du dépôt ne sait noter un jeu de crops eBay** — ni pour ArcFace,
ni pour DINO.

---

## 2. LES BLOQUEURS

### B0 🔴 Le préflight et le bake sont cassés **maintenant**, sous le shell par défaut

C'est le bloqueur le plus urgent, et il n'existait pas ce matin.

L'arbre porte deux prédicats neufs, non committés :

- `ml/training/iteration_augmentations.py:260` — `AND a.eval_corpus IS NULL`
- `ml/training/foundation/anchors.py:849` — `AND eval_corpus IS NULL`

La colonne vient de `ml/serving/migrations/0014_eval_corpus_holdout.sql:26`
(fichier **non tracké**). Elle n'est nulle part :

```bash
cd ml && sqlite3 "file:state/eurio.replica.db?mode=ro" \
  "select count(*) from pragma_table_info('image_assets') where name='eval_corpus';"
# 0
for f in state/eurio.work.db state/eurio.work-juge-banc.db; do
  sqlite3 "file:$f?mode=ro" "select count(*) from pragma_table_info('image_assets') where name='eval_corpus';"
done
# 0
# 0
curl -s https://eurio-api.musubi.dev/openapi.json | python3 -c \
  "import json,sys;p=json.load(sys.stdin)['paths'];print([k for k in p if 'eval' in k or 'holdout' in k])"
# []
```

Et le défaut est **reproduit**, pas déduit — `real_training_sources`
(`ml/training/iteration_augmentations.py:332-348`) est partagé par le bake **et**
par le préflight (`ml/training/foundation/preflight.py:179`) :

```bash
cd ml && EURIO_DB_PATH="$PWD/state/eurio.replica.db" EURIO_DB_READONLY=1 \
  ./.venv/bin/python -c "
import sys, pathlib; sys.path.insert(0,'.')
from store import Store, resolve_db_path
from training.iteration_augmentations import real_training_sources
s = Store(resolve_db_path(pathlib.Path('state/eurio.db')))
try: print('OK', real_training_sources('fr-2016-2eur-100th-anniversary-of-the-birth-of-francois-mitterrand', None, s))
except Exception as e: print('ERREUR:', type(e).__name__, e)"
# db = …/ml/state/eurio.replica.db
# ERREUR: OperationalError no such column: a.eval_corpus
```

**Pourquoi la réplique ne se répare pas toute seule** : `StoreBase._bootstrap`
sort en no-op complet quand le store est read-only
(`ml/store/connection.py:138-144`), donc le `_ensure_column("eval_corpus")` posé
en `ml/store/connection.py:594` (impl. `:722-732`) n'est jamais exécuté sur la
réplique. Un `work.db` ouvert **en écriture**, lui, s'auto-répare au premier
open — c'est pourquoi le défaut est invisible en mode compute et mortel sous le
flip.

**Le geste qui le lève** — dans cet ordre, aucun ne se saute :

1. appliquer 0014 au **canonique VPS** (redémarrage `eurio-api`, cf. skill
   `eurio-vps-deploy`) et déployer `POST /ingest/eval-corpus`
   (`ml/serving/ingest_routes.py:274-322`, non déployé) ;
2. `go-task ml:db:pull-replica` — sinon la réplique reste sans la colonne ;
3. **seulement ensuite** `VACUUM INTO` un `work.db` neuf.

⚠️ Un `VACUUM INTO` fait **avant** l'étape 2 emporte une base sans la colonne :
le bake s'auto-réparera (write) mais le marquage d'éval, lui, n'y sera pas.

---

### B1 🔴 Le jeu d'évaluation n'est pas tiré, et il n'est marqué nulle part

`ml/scripts/select_eval_holdout.py` existe (non tracké), sa règle est écrite et
déterministe (`:31-45` — moitié la plus inclinée par `tilt_deg`, 5 positions
régulièrement espacées, aucun aléatoire). **Il n'a pas tourné** : la colonne qu'il
écrit n'existe dans aucune base (§B0), et la route qui la transporte n'est pas
déployée.

État des mesures dont il dépend, sur la réplique du jour :

```bash
cd ml && sqlite3 "file:state/eurio.replica.db?mode=ro" \
  "select count(*), sum(tilt_deg is not null), sum(quality_score is not null)
     from image_assets where training_eligible=1;"
# 2969|2216|530
```

`tilt_deg` couvre **2 216 / 2 969** crops éligibles (74,6 %) — l'étape 1 a
largement tourné ; `quality_score` en couvre **530** (17,9 %), le critère de D5
n'en a pas besoin.

**Geste** : jouer l'étape 2 après B0, et **coller le compte de lignes marquées**
(`select count(*) from image_assets where eval_corpus is not null` → attendu
**300**) avant de créer la moindre itération.

---

### B2 🔴 Aucun outil du dépôt ne sait noter un jeu de crops eBay

**C'est le trou le plus important du dossier, et il n'est pas nommé dans
`SUIVI-MATRICE.md`.** L'étape 3 promet « ~300 crops eBay sur 60 classes ». Rien
ne peut les noter aujourd'hui.

`replay_corpus` ne lit **qu'une seule table** :

- `ml/scripts/replay_corpus.py:87` importe `ScanCorpusStore` ;
- `:662` `store = ScanCorpusStore(db_path=args.db)` ; `:675-676` les deux
  `list_captures` ;
- SQL réel : `ml/store/scan_corpus.py:466-511` — `SELECT * FROM scan_corpus …`,
  jamais de jointure canonique ;
- chargement d'image, les deux seuls chemins : `:272` (`--path full` →
  `normalize_device_path`) et `:277` (`--path fast` → le crop stocké).

Ce qu'il faudrait changer, point par point, pour lui donner un jeu eBay :

| # | Point | Fichier:ligne |
|---|---|---|
| 1 | source du jeu (`ScanCorpusStore` → `review.bench_gold.load_gold` + `resolve_local_paths`) | `replay_corpus.py:662-679` ; `ml/review/bench_gold.py:123-139`, `:396-421` |
| 2 | signature de `replay_candidate` : `frames_root + cap.crop_path` est relatif au store, un crop eBay a un chemin MinIO résolu en absolu | `replay_corpus.py:244-250`, `:277` |
| 3 | résolution du label attendu — `GoldCrop` porte **deux** identités, `truth_eurio_id` et `class_id` (la clé sous laquelle la banque indexe). Choisir laquelle fait foi est une décision, pas un renommage | `bench_gold.py:147-148`, `:199-214` ; `replay_corpus.py:269`, `:287` |
| 4 | `by_condition` dégénère : un crop eBay n'a pas de condition de prise de vue | `replay_corpus.py:302`, `:412` |
| 5 | `--path full` appelle `normalize_device_path` ; le pendant eBay est `normalize_listing_path` — **pas le même détecteur** | `ml/vision/normalize_snap.py:352-355` vs `:1132` |
| 6 | `corpus_version` (hash des `capture_id`) vs `gold_version` du gold figé : il faut en choisir un | `ml/store/scan_corpus.py:113-116` ; `bench_gold.py:8-16` |
| 7 | le bloc `excluded` repose sur `eval_decision`, colonne propre à `scan_corpus` | `replay_corpus.py:369-389`, `:700` ; `scan_corpus.py:56-60` |

**Geste** : c'est un lot, pas un réglage. Tant qu'il n'est pas joué, l'étape 3
produit un modèle **qu'on ne saura pas noter sur le jeu qu'on vient de lui
cacher**. La seule note disponible resterait le corpus device
(`replay_corpus --iteration <iid> --path full`) — utile, mais ce n'est pas ce
que D1 décrit.

---

### B3 🔴 60 vs 671 : il n'existe aucun chemin DINO dans le juge

Le garde d'espace de labels est réel et il **refusera** — c'est voulu :

- `assert_same_label_space`, `ml/scripts/replay_corpus.py:534-575` ;
- il ne compare **que** deux `embeddings_v1.json`, sur la maille
  `COALESCE(design_group, eurio_id)` (`:550-554`) ;
- condition de refus : `if cand_mesh == base_mesh: return` (`:557-558`) → **toute**
  différence lève, y compris un sur-ensemble strict. Aucune tolérance ;
- `raise SystemExit(<str>)` → message sur stderr, **exit 1**, avant
  `out_dir.mkdir()` (`:744`) et avant toute inférence (`:748`) ;
- aucune dérogation n'existe (pas de `--allow-label-space-mismatch`, cf.
  `LOT3-JUGE.md` §9.e).

Ce qu'il faudrait pour que la comparaison soit **acceptée sans le désarmer** :

1. **la sous-banque DINO de D3, exportée au format `embeddings_v1.json`
   restreint aux 60 `class_id` d'ArcFace.** Le seul précédent de restriction
   dans le dépôt est `_filter_embeddings`
   (`ml/scripts/build_cohort_bundle.py:163-176`) ;
2. **un encodeur DINO chargeable par le juge — et ça, ça n'existe pas.**
   `load_embedder` n'accepte que `.pth/.pt/.tflite`
   (`ml/training/eval/evaluate_real_photos.py:177-183`), or la banque servie est
   un `.npz` :

```bash
cd ml && ./.venv/bin/python -c "
import numpy as np; d=np.load('state/foundation_anchors_2eur_all.npz',allow_pickle=True)
print('ancres', d['matrix'].shape, '| classes uniques', len(set(d['eurio_ids'].tolist())))
print(d['meta'][0])"
# ancres (2062, 1024) | classes uniques 671
# {"encoder_version": "dinov2-vitl14", "anchors_kind": "2eur_all", "built_at": "2026-08-24T20:41:15+00:00",
#  "count": 2062, "dim": 1024, "bank_id": "92cc70a481924a96bd6f2588cef8663d"}
```

**Il n'y a aujourd'hui aucun chemin DINO dans `replay_corpus`.** Restreindre la
banque à 60 classes est nécessaire mais **pas suffisant**.

⚠️ Et un piège de lecture : le garde ne se déclenche **que si `--baseline` est
passé** (`replay_corpus.py:739-741`). Deux runs notés séparément produisent deux
scorecards sans le moindre refus — rien n'empêche de les comparer à la main. Le
garde protège la comparaison automatique, pas le lecteur.

---

### B4 🟠 La cohorte à geler n'existe pas encore

D2 dit **60 classes**. La cohorte disponible en porte **68**, et elle est
`draft` avec 0 itération :

```bash
cd ml && sqlite3 "file:state/eurio.replica.db?mode=ro" \
  "select id,name,status,created_at from experiment_cohorts where name like 'rich%';"
# 773ce86bdad2|rich10-68c|draft|2026-08-24 23:29:55
sqlite3 "file:state/eurio.replica.db?mode=ro" \
  "select count(*) from experiment_iterations where cohort_id='773ce86bdad2';"
# 0
```

Créer une itération **gèle la cohorte de façon irréversible** (skill
`eurio-cohort`). Geler `rich10-68c` telle quelle donne un espace de labels à 68,
que le garde du §B3 refusera de comparer à une sous-banque à 60.

**Geste** : cloner (`POST /lab/cohorts/773ce86bdad2/clone`, nom en kebab-case
minuscule — un nom avec majuscules rend `400`, cf. `LOT4-PREPARATION.md` §0),
retirer les 8 classes sous plancher, préflighter, **puis** geler.

⚠️ Le préflight ne bloquera **pas** ces 8 classes : `_verdict`
(`ml/training/foundation/preflight.py:213-230`) ne rend `block` que si
`seed == 0` ou `seed < m_per_class=4`. `n_ebay < MIN_REAL=10` rend seulement
`warn`. Une classe qui tombe de 15 à 10 crops passe donc en `ok`, et une qui
tombe à 9 passe en `warn` — **jamais en `block`**. Le plancher `MIN_REAL` ne
protège rien ici ; c'est le PO qui doit composer les 60, pas le préflight qui
les imposera. Mesuré :

```bash
cd ml && sqlite3 "file:state/eurio.replica.db?mode=ro" "
with ids as (select je.value eid from experiment_cohorts ec, json_each(ec.eurio_ids_json) je where ec.id='773ce86bdad2'),
cls as (select distinct coalesce(c.design_group_id,c.eurio_id) cid from coins c join ids on ids.eid=c.eurio_id),
pc as (select coalesce(co.design_group_id,co.eurio_id) cid,
       sum(case when ia.training_eligible=1 and s.source='ebay' then 1 else 0 end) n
       from coins co left join image_assets ia on ia.eurio_id=co.eurio_id
       left join source_images s on s.id=ia.source_image_id
       where coalesce(co.design_group_id,co.eurio_id) in (select cid from cls) group by 1)
select (select count(*) from pc where n>=15), (select count(*) from pc where n>=10 and n<15), (select sum(n) from pc);"
# 60|8|2297
```

**60 classes ≥ 15 crops · 8 classes entre 10 et 14 · 2 297 crops eBay** dans la
cohorte. Le compte de D2 est confirmé.

---

### B5 🟠 `launch-training` répond toujours HTTP 200 en laissant mourir le job

Non corrigé, vérifié au code aujourd'hui :

- `ml/serving/lab_routes.py:729-749` — la route rend
  `_iteration_with_run_metrics(row)` sans rien attendre ;
- `ml/serving/iteration_runner.py:379-398` puis `_launch_chain` `:421-432` →
  `jobs.launch(...)`, **subprocess détaché** ;
- la première écriture canonique du job détaché est
  `update_iteration(status="training")` (`iteration_runner.py:662-667`) → sous le
  flip : `attempt to write a readonly database`, job mort en moins d'une seconde ;
- le handler global qui traduirait ça en 503 `canonical_readonly`
  (`ml/serving/server.py:110-131`) est un exception handler FastAPI : il ne
  couvre **jamais** un subprocess détaché. D'où le silence total.

**Le seul endroit qui dit la vérité est la table `jobs`.** Le geste est le mode
compute (§4), et son piège d'ordre est en §4 étape 2.

---

## 3. LES PIÈGES — ce qui laissera lancer et rendra un chiffre faux

> C'est la section qui compte. Aucun de ces défauts ne se voit depuis l'écran,
> et aucun ne fait rougir un test.

### P1 🔴 Le bake n'est pas le même sur le PC que sur le Mac, et **rien ne le dit**

`real_training_sources` (`ml/training/iteration_augmentations.py:332-348`)
additionne trois pools, et **ils ne voyagent pas de la même façon** :

| Pool | Fonction | Origine | Se télécharge ? |
|---|---|---|---|
| avers Numista | `_source_images` `:211-222` | `ml/datasets/<numista_id>/obverse.jpg` | ❌ `.exists()` sec |
| crops eBay | `_ebay_training_sources` `:224-267` | `local_path("enrichment-crops", …)` `:262` | ✅ MinIO, à la volée |
| réfs BCE / EUR-Lex | `_canonical_ref_images` `:269-330` | `ML_DIR.parent / local_path` | ❌ `.exists()` sec |

Les deux pools qui ne se téléchargent pas vivent dans des répertoires
**gitignorés** — `.gitignore:54` (`ml/datasets/*`) et `.gitignore:143`
(`ml/canonical_images/`) — et le Mac en porte beaucoup :

```bash
cd ml && ls datasets | grep -c '^[0-9]*$'   # 695
ls canonical_images | wc -l                 # 1079
```

**Si le PC ne les a pas** (ou en a moins), alors : le préflight rend d'autres
`n_numista`/`n_ref`, le bake produit un jeu d'entraînement **sans l'avers
canonique**, et **aucune erreur n'est levée** — `_canonical_ref_images` dit
explicitement « les chemins absents du disque sont ignorés (pas d'erreur
bloquante) » (`:284-285`).

**Le seul contrôle possible** : comparer, classe par classe, les `n_numista` /
`n_ebay` / `n_ref` du préflight joué **sur le PC** à ceux joués sur le Mac. Un
écart = deux bakes différents.

⚠️ Nuance à ne pas confondre : en mode itération prebaked,
`prepare_dataset` lit le staging et **pas** `datasets/<nid>/`
(`ml/training/pipeline.py:279-296`, commentaire `:281-285`). C'est le **bake
lui-même** qui est machine-dépendant, pas la préparation.

### P2 🔴 `val_source` par défaut vaut `device` — la fuite se ré-arme toute seule

`ml/serving/iteration_runner.py:988-990` : `config["val_source"] =
(iteration.training_config or {}).get("val_source", "device")`.

Une `training_config` qui oublie la clé remet le corpus device en split de
validation. Ce n'est pas théorique — le run de référence du PC portait
exactement ça :

```bash
cd ml && sqlite3 -header "file:state/eurio.replica.db?mode=ro" \
  "select id,name,created_on,started_at,finished_at,training_config_json
     from experiment_iterations where id='03f767f998ef';"
# 03f767f998ef|exercice-2-pc-long|pc|2026-08-16T20:29:53Z|2026-08-16T21:14:29Z|{"epochs": 40}
```

**Et sur le PC c'est pire, parce que ça échoue à moitié.**
`ml/datasets/eval_real_norm/` est gitignoré (`.gitignore:54`) donc probablement
absent du PC. Dans ce cas `_override_val_with_eval_real` **imprime une note et
retourne** (`ml/training/prepare_dataset.py:380-384`) : `val/` reste vide.
Le garde de contenu ne rougit pas — il sort d'emblée quand `val_source ==
"device"` (`:344-345`). On obtient donc un run qui **dit** `device`, se comporte
comme `none`, et ne laisse aucune trace de l'écart. Deux machines, deux
comportements, un seul nom.

**Geste** : poser `val_source` et `centroid_source` **explicitement** dans
`training_config`, et vérifier la valeur relue sur la row avant de baker.

### P3 🟠 `--val-source ebay` n'existe pas — le val du run est un choix binaire

`ml/training/prepare_dataset.py:319-326` lève un `SystemExit` nommé :
« le prélèvement eBay de validation n'existe pas encore … Utilise
`--val-source=none` en attendant ». Les 300 crops d'éval **ne peuvent donc pas**
servir de split de validation, même une fois marqués. Q4 de `PROBLEME.md` reste
entière : soit `device` (fuite + couverture partielle), soit `none` (dernier
epoch).

✅ **Correction à la prémisse de la mission** : `LOT2-FUITES.md` §6 disait
`none` « non exécuté ». Ce n'est plus vrai — le run B `11b7a626c57a` l'a joué de
bout en bout le 2026-08-25, jusqu'à l'export TFLite :

```bash
cd ml && ls lab/iterations/11b7a626c57a/
# checkpoints  dataset  embeddings  metrics  reports  tflite
find lab/iterations/11b7a626c57a/dataset/val -type f | wc -l   # 0
find lab/iterations/027254937193/dataset/val -type f | wc -l   # 102
```

Le chemin `none` est donc **prouvé**, avec une réserve dure ci-dessous.

### P4 🔴 Avec `val` vide, `best_model.pth` n'est écrit **qu'à la dernière epoch**

`ml/training/train_embedder.py:1016-1018` :

```python
save_now = (val_loader is not None and val_metrics["recall@1"] >= best_recall) \
           or (val_loader is None and epoch == args.epochs)
```

Conséquence : tout arrêt avant la dernière epoch — OOM CUDA, SIGTERM, coupure,
`ml:api` au lieu de `ml:api-prod` — laisse **zéro** modèle exploitable. Un arrêt
coopératif n'écrit qu'un `best_model.partial.pth` (`:1043-1057`), et les trois
étapes suivantes pointent toutes `best_model.pth` (`pipeline.py:367`, `:397`,
`iteration_runner.py:1097`). Sur un run PC de ⚠️ ~2 h 20 (§P9), ce n'est pas un
risque théorique.

Corollaire de lecture : avec `val` vide, `val_metrics` vaut `{"recall@1": 0.0,
"recall@3": 0.0}` à chaque epoch (`train_embedder.py:970-973`), remonté tel quel
en base (`pipeline.py:454-465`). **La scorecard affichera 0 %** — ce n'est pas
une régression, c'est l'absence de val. Le run B en porte déjà la trace
(`recall@1` 0,0 côté B contre 0,8627 côté A, `LOT4-RESULTATS.md` §6).

### P5 🔴 La couche de textures — **je ne peux pas la vérifier sur le PC**

Sur le Mac, elle est inerte et mesurée comme telle
(`ml/training/data/overlays/` absent, jamais versionné). Le contrôle
`go-task ml:augment-textures-check` a été **réparé au L7** (commit `c3db5569`) :
il rend maintenant un verdict au lieu d'un `ModuleNotFoundError`.

**Ce que je ne peux pas établir depuis le Mac** : si le PC dispose de ses
textures. Les deux cas ont des conséquences opposées :

- **le PC les a** → son bake applique 3 couches là où le Mac en applique 2. Le
  run de l'étape 3 ne sera comparable **ni à A, ni à B, ni au `92,4 %` du
  2026-08-16**, et rien ne le dira : le message part 36 fois dans un log de job
  détaché ;
- **le PC ne les a pas** → même privation que A et B, comparabilité interne
  conservée.

**Le contrôle coûte une commande, et il doit être joué SUR LE PC avant le bake,
sa sortie collée** :

```bash
go-task ml:augment-textures-check ; echo "exit=$?"
```

### P6 🟠 `EURIO_CACHE_MAX_GB=20` s'applique aussi au PC — contre sa propre doctrine

`flake.nix:129` pose `EURIO_CACHE_MAX_GB = "20"` dans `commonEnv`, hérité par
`pcShell` (`flake.nix:250`). Or la docstring du cache dit l'inverse :
« **PC training** : the runner overrides `EURIO_CACHE_ROOT` per `run_id` and
leaves `MAX_GB=0` » (`ml/shared/storage/local_cache.py:11-13`).

Conséquence : `_evict_if_needed()` est appelé **avant chaque téléchargement
manqué** (`local_cache.py:94-96`) et fait un `root.rglob("*")` complet
(`:264`). Sur le Mac ce parcours coûte **1,87 s** pour 62 183 fichiers
(chiffre de `SUIVI-MATRICE.md` §Étape 1) ; mesuré aujourd'hui :

```bash
du -sh ~/.cache/eurio && find ~/.cache/eurio -type f | wc -l
# 15G
# 62805
```

Sur un PC à cache froid il faut tirer ⚠️ ~2 300 crops : le coût du balayage
croît avec le cache, et il est **entièrement invisible** (aucun log, aucune
métrique).

⚠️ Et un mode d'échec dur : `local_path` lève `FileNotFoundError` si MinIO est
injoignable (`local_cache.py:121-124`), et `_ebay_training_sources` **ne le
rattrape pas** (`iteration_augmentations.py:262`). Un hoquet MinIO tue le bake
dans un job détaché → HTTP 200, silence.

### P7 🟠 `--path fast` est le défaut du juge, alors que `full` est une condition de validité

`ml/scripts/replay_corpus.py:637` : `--path` a pour défaut `"fast"`. Quatre
normaliseurs cohabitent dans les crops stockés (`hough_tight` 113,
`hough_relaxed` 1, `hough_strict` 280, `hough_loose` 57 — mesuré, cité
`ml/serving/scan_corpus_routes.py:172-176`), et `hough_tight`/`hough_relaxed`
**n'existent plus dans le code** : ce sont des noms figés dans d'anciens crops.
Noter en `fast` mélange une différence de code avec une différence de prise de
vue. **Aucun garde ne refuse `fast`** — c'est une discipline d'appelant.

### P8 🟠 `inputs_digest` ne quitte pas le disque, et le pool grossit

Le pool a pris **+30,5 %** en neuf jours pour la même cohorte : 5 051 samples le
2026-08-16, 6 594 le 2026-08-25 (`SUIVI-MATRICE.md`, §Reste-à-faire). Le digest
qui dirait avec quoi un modèle a été entraîné existe, mais il vit dans le
`_manifest.json` du bake et n'est jamais persisté sur l'itération. Deux runs à
quinze jours d'écart ne bakent pas la même chose, **et rien ne le dit**.

### P9 ⚠️ Le coût, estimé — et il est bien plus lourd que 44 minutes

La cohorte déclare 68 `eurio_id`, mais l'entraînement travaille à la maille
`design_group` et tire des pièces **hors cohorte** :

```bash
cd ml && sqlite3 "file:state/eurio.replica.db?mode=ro" "
with ids as (select je.value eid from experiment_cohorts ec, json_each(ec.eurio_ids_json) je where ec.id='773ce86bdad2'),
cls as (select distinct coalesce(c.design_group_id,c.eurio_id) cid from coins c join ids on ids.eid=c.eurio_id)
select (select count(*) from ids), (select count(*) from cls),
       (select count(*) from coins c2 where coalesce(c2.design_group_id,c2.eurio_id) in (select cid from cls));"
# 68|68|157
```

**68 classes → 157 pièces bakées.** Pour le sous-ensemble des 60 classes : **148
pièces** (requête du §B4).

| Grandeur | Valeur | Provenance |
|---|---:|---|
| samples / pièce, bake du 2026-08-25 | **108,1** | 6 594 / 61 (`LOT4-PREPARATION.md` §3.a) |
| ⚠️ samples attendus, 60 classes | **≈ 16 000** | 148 × 108,1 |
| référence PC | **44 min 36 s** pour 40 epochs / 5 051 samples | `03f767f998ef`, `20:29:53Z → 21:14:29Z` (requête §P2) |
| ⚠️ facteur d'échelle | **× 3,17** | 16 000 / 5 051 |
| ⚠️ **40 epochs sur le PC** | **≈ 141 min** (2 h 21) | 44,6 × 3,17 |
| ⚠️ 20 epochs | ≈ 71 min | |
| ⚠️ 8 epochs | ≈ 28 min | |
| ⚠️ bake seul | **≈ 10 min** + téléchargements MinIO à froid | 241 s pour 6 594 sur M3, × 2,4 |

⚠️ **Ce sont des extrapolations linéaires en nombre de samples, non mesurées.**
Elles ignorent l'élargissement de la couche ArcFace (24 → 60 classes, effet
marginal), l'état du cache MinIO du PC, et le coût de `compute_embeddings` +
export TFLite — **absent du budget, pas estimé**. Le seul moyen de les fermer
coûte 6 minutes : rejouer la calibration 1 epoch du `LOT4-PREPARATION.md` §3.b
**sur le PC**.

⚠️ Et une réserve de méthode : `epoch_multiplier` vaut 10 par défaut et
`pipeline.py` ne le passe jamais — un epoch voit dix fois le dataset. Le coût
est donc bien linéaire en samples, mais ce facteur 10 n'est écrit nulle part
dans la config d'une itération.

### P10 🟠 Les pièges déjà payés — état vérifié au code, un par un

| Piège | État | Preuve |
|---|---|---|
| `augmentations_seed` transporté | ✅ **fermé** | `lab_routes.py:192` (champ), `:707` (passe-plat), `iteration_runner.py:275`, `:314`, `:326` ; lu au bake `iteration_augmentations.py:388-391`, dérivé par pièce `:469` |
| `--centroid-source` toujours passé | ✅ **fermé** | `pipeline.py:357` puis `:362`, sans condition |
| `--val-source` obligatoire en mode lab | ✅ **fermé** | `prepare_dataset.py:548-556` (`SystemExit`) ; `pipeline.py:269-276` (`RuntimeError` en mode itération) |
| `--val-source none` de bout en bout | ✅ **joué** le 2026-08-25 | run `11b7a626c57a`, `val/` vide, artefacts complets (§P3) — **mais** §P4 |
| Garde de contenu sur `val/` | ✅ en place | `prepare_dataset.py:336-361` — inactif quand `val_source == "device"` (`:344-345`), cf. §P2 |
| `launch-training` → 200 + job mort | ❌ **NON corrigé** | §B5 |
| Textures inertes | ⚠️ **invérifiable à distance** | §P5 |
| ⚠️ La graine torch/numpy | fixe à **42**, jamais surchargée, **jamais tracée** dans `training_config` | `train_embedder.py:1116` ; aucun `--seed` dans `pipeline.py` |

⚠️ Un message reste faux, signalé au L4 et à recroiser : `describe_auto_source`
journalise « `--centroid-source` absent → défaut `auto` » **alors que
`pipeline.py` le passe explicitement**. Il accuse une cause fausse.

### P11 🟠 Divers, à savoir avant de lire un chiffre

- **`r_at_1_eq` dilue.** Il compte au dénominateur les frames dont la classe
  n'existe pas dans le candidat. La valeur qui décide est
  `primary.r_at_1_on_covered`, **citée avec `n_on_covered`**, jamais l'un sans
  l'autre (`replay_corpus.py:455-458` ; obligation écrite dans
  `corpus-spec.md` §8ter).
- **Le mtime du `.db` ment** en WAL — `.db` à 01:31, `-wal` à 17:21, seize
  heures d'écart mesurées le 2026-08-25. Ne jamais juger la fraîcheur d'une
  réplique dessus.
- **`sqlite3 -readonly` échoue** sur `scan_corpus.db` (WAL sans `-shm`) ; il
  faut `file:…?immutable=1` — qui rend en échange un instantané **périmé** dès
  qu'un écrivain tourne, `exit=0`, sans message.
- **`go-task ml:db:pull-replica`** suppose `sqlite3_rsync` (devShell) et la clé
  `~/.ssh/eurio_replica`. Sans eux : repli HTTP, snapshot complet ~156 Mo.
  **Je ne sais pas si le PC a cette clé.**
- **`ml/.venv` peut être stale** : `flake.nix:164-176` ne détecte que la désync
  de store-path, **pas** l'absence de CUDA. Le seul contrôle est
  `go-task ml:setup`, qui imprime `cuda=…`. Si `cuda=False`, l'entraînement
  tombe sur CPU **sans erreur**, et `num_workers` passe à 0
  (`train_embedder.py:857-858`).
- **Le `gitRemotesHook` du flake force encore `codeberg`** (`flake.nix:201`)
  alors que CLAUDE.md dit le remote abandonné et que le VPS suit `github`. Sur
  le PC, tirer explicitement : `git fetch github repo-cleanup && git merge
  --ff-only github/repo-cleanup`. (`github/repo-cleanup` et `HEAD` sont à
  égalité ce soir : `git rev-list --left-right --count github/repo-cleanup...HEAD`
  → `0  0`.)

---

## 4. LA SÉQUENCE EXACTE À JOUER

> Les étapes 0 à 2 sont sur le **Mac / VPS**. L'étape 3 seulement est sur le PC.
> Chaque code de sortie se lit **sans pipe** (`; echo "exit=$?"`).

### Étape 0 — lever B0 (VPS, puis Mac)

```bash
# a. Committer l'étape 2, déployer le canonique (skill eurio-vps-deploy)
#    → migration 0014 appliquée + POST /ingest/eval-corpus servi
curl -s https://eurio-api.musubi.dev/openapi.json \
  | python3 -c "import json,sys;print([k for k in json.load(sys.stdin)['paths'] if 'eval-corpus' in k])"
# attendu : ['/ingest/eval-corpus']   (aujourd'hui : [])

# b. Rapatrier le schéma
go-task ml:db:pull-replica
cd ml && sqlite3 "file:state/eurio.replica.db?mode=ro" \
  "select count(*) from pragma_table_info('image_assets') where name='eval_corpus';"
# attendu : 1        (aujourd'hui : 0)
```

### Étape 1 — tirer et marquer les 300 crops (Mac)

```bash
cd ml && ./.venv/bin/python -m scripts.select_eval_holdout <ses arguments> ; echo "exit=$?"
sqlite3 "file:state/eurio.replica.db?mode=ro" \
  "select eval_corpus, count(*), count(distinct eurio_id) from image_assets
    where eval_corpus is not null group by 1;"
# attendu : matrice-encodeurs-2026-08 | 300 | …
```

🔴 **Contrôle obligatoire — le prélèvement doit se voir dans le bake.** Rejouer
le préflight de la cohorte **avant et après** le marquage et comparer `n_ebay`
classe par classe : la somme doit baisser de **300 exactement**. Si elle ne
baisse pas, le prédicat n'est pas honoré et l'expérience est morte avant de
commencer.

### Étape 2 — composer et geler la cohorte des 60 (Mac, sous le flip)

```bash
curl -s -X POST "http://127.0.0.1:8042/lab/cohorts/773ce86bdad2/clone" \
  -H "Content-Type: application/json" -d '{"name":"matrice-60c","description":"…"}'
# → {"id":"<C60>", …, "status":"draft"}     (nom en kebab-case minuscule, sinon 400)

# retirer les 8 classes < 15 crops, puis :
curl -s "http://127.0.0.1:8042/lab/cohorts/<C60>/training-readiness"
# attendu : ready True | n_classes 60 | blocked 0
# ⚠️ 'warned' peut être > 0 sans que ce soit un blocage — cf. B4
```

Puis créer l'itération, **avec les deux clés posées explicitement** :

```bash
curl -s -X POST "http://127.0.0.1:8042/lab/cohorts/<C60>/iterations" \
  -H "Content-Type: application/json" -d '{
    "name": "matrice-arcface-60c",
    "hypothesis": "ArcFace 60 classes, jeu d eval eBay exclu du train (D1/D2).",
    "recipe_id": "3e022c8bb17a",
    "variant_count": 100,
    "augmentations_seed": 20260826,
    "training_config": {"epochs": 40, "batch_size": 256, "m_per_class": 4,
                        "val_source": "none", "centroid_source": "train_mean"}
  }' -w "\nHTTP=%{http_code}\n"

# 🔴 Contrôle : la graine ET les deux clés doivent être relues sur la row
curl -s "http://127.0.0.1:8042/lab/cohorts/<C60>/iterations" | python3 -c "
import json,sys
for it in json.load(sys.stdin): print(it['id'], it['augmentations_seed'], it['training_config'])"
# les deux clés val_source/centroid_source DOIVENT apparaître
```

### Étape 3 — sur le PC

**3.a Préconditions, dans cet ordre.**

```bash
cd /chemin/vers/Eurio
git fetch github repo-cleanup && git merge --ff-only github/repo-cleanup
direnv reload                       # profil pc → nvidiaHook + flipHook

go-task ml:setup                    # attendu : torch …  cuda=True
go-task ml:augment-textures-check ; echo "exit=$?"
#   → COLLER la sortie. Elle décide si le run est comparable à A/B ou non (P5)

go-task ml:db:pull-replica ; echo "exit=$?"
cd ml && sqlite3 "file:state/eurio.replica.db?mode=ro" \
  "select count(*) from pragma_table_info('image_assets') where name='eval_corpus';"   # 1
sqlite3 "file:state/eurio.replica.db?mode=ro" \
  "select count(*) from image_assets where eval_corpus is not null;"                   # 300
ls datasets | grep -c '^[0-9]*$'    # à comparer aux 695 du Mac (P1)
ls canonical_images | wc -l         # à comparer aux 1079 du Mac (P1)
```

**3.b Mode compute — le piège d'ordre.**

Le `VACUUM INTO` doit venir **après** le pull, et **après** que l'itération
existe au canonique : un `work.db` fabriqué avant ne la contient pas.

```bash
[ -e ml/state/eurio.work-matrice.db ] || nix develop .#pc --command \
  sqlite3 ml/state/eurio.replica.db "VACUUM INTO 'ml/state/eurio.work-matrice.db'"
# ☠️ jamais `cp` (WAL), jamais `rm` sur une work.db existante

lsof -ti :8042 | xargs kill          # par PID — jamais `pkill -f`
EURIO_DB_READONLY= EURIO_DB_PATH="$PWD/ml/state/eurio.work-matrice.db" go-task ml:api-prod
#                                    ml:api-prod, PAS ml:api (--reload tue les subprocess)

ps eww -o command= -p $(lsof -ti :8042) | tr ' ' '\n' | grep -E '^EURIO_DB'
# EURIO_DB_PATH=…/eurio.work-matrice.db
# EURIO_DB_READONLY=
```

**3.c Baker, puis entraîner.**

```bash
curl -s -X POST ".../lab/cohorts/<C60>/iterations/<IID>/bake"        # attendu 202
until [ "$(curl -s ".../iterations/<IID>/augmentations/job" \
   | python3 -c 'import json,sys;print(json.load(sys.stdin)["status"])')" != running ]
do sleep 30; done

curl -s -X POST ".../lab/cohorts/<C60>/iterations/<IID>/launch-training"
```

🔴 **`HTTP 200` ne veut pas dire « ça tourne ».** Après chaque lancement, et
c'est le seul contrôle qui vaille :

```bash
cd ml && ./.venv/bin/python -c "
import sys;sys.path.insert(0,'.');import jobs
for r in jobs.connection().execute(
  'select kind,status,error,log_path from jobs order by rowid desc limit 3'): print(dict(r))"
# attendu : status 'running', error None
# si status='failed' + 'no such column: a.eval_corpus'  → l'étape 0 n'a pas été jouée
# si status='failed' + 'readonly database'              → le mode compute n'est pas actif
```

**3.d Ce qu'il faudra relever, et rapatrier.**

Le calcul reste sur le PC : `ml/lab/iterations/<IID>/` est gitignoré
(`.gitignore:70`), et les modèles **ne remontent jamais** au canonique — seul
l'**état** de l'itération y monte, automatiquement et en best-effort
(`iteration_runner.py:337-370`, backfill manuel `go-task ml:lab:push-dimensions`).
Deux options, à trancher :

- noter **sur le PC** (mais `ml/state/scan_corpus.db` y est probablement absent —
  gitignoré, `.gitignore:158`) ;
- ou publier les artefacts (`go-task ml:training-assets:publish`) et les tirer
  sur le Mac (`ml:assets:fetch`) pour y jouer le juge.

Dans les deux cas, à relever et à consigner : `samples` du bake, la sortie de
`ml:augment-textures-check`, `n_numista`/`n_ebay`/`n_ref` du préflight PC, la
durée réelle, et le `t_epoch` gelé/dégelé.

---

## 5. CE QUE JE N'AI PAS PU ÉTABLIR

| # | Question ouverte | Pourquoi |
|---|---|---|
| 1 | **Si le PC a ses textures d'overlay.** | `ml/training/data/overlays/` est local et jamais versionné. Non atteignable depuis le Mac. C'est le §P5, et il décide de la comparabilité du run avec A, B et le `92,4 %`. **Une commande sur le PC ferme la question.** |
| 2 | **Si le PC a `ml/datasets/<numista_id>/` et `ml/canonical_images/`.** | Gitignorés (`.gitignore:54`, `:143`). S'ils manquent, le bake est silencieusement différent (§P1). |
| 3 | **Si le PC a `ml/state/scan_corpus.db`, `ml/datasets/eval_real_norm/`, la clé `~/.ssh/eurio_replica`, un `ml/.venv` avec CUDA.** | Tous locaux et non versionnés. |
| 4 | **Le coût réel sur le PC.** | Les chiffres du §P9 sont des extrapolations linéaires en samples, jamais mesurées. Se ferment en 6 minutes (calibration 1 epoch). Le coût de `compute_embeddings` + export TFLite est **absent du budget**, pas estimé. |
| 5 | **Le nombre exact de samples que le bake produira.** | 108,1 samples/pièce est une moyenne d'un bake à 61 pièces ; rien ne garantit qu'elle tienne à 148 pièces avec une distribution de crops différente. |
| 6 | **Ce que l'étape 2 fera exactement.** | Elle s'écrivait pendant cette revue. J'ai lu son intention (`select_eval_holdout.py:1-45`, migration 0014) et vérifié ses deux prédicats, **pas** son exécution — elle n'a pas tourné, la colonne n'existe nulle part. |
| 7 | **Si les 60 classes tiennent après prélèvement.** | Mesurable seulement une fois le marquage posé : le préflight avant/après est le seul juge (§4 étape 1). Le calcul sur papier dit oui, mais `real_training_sources` dépend du **disque de la machine** (§P1) — la réponse peut différer entre Mac et PC. |
| 8 | **Le contenu du `warned` du préflight à 60 classes.** | Le préflight n'a pas été joué : le lancer aujourd'hui plante (§B0). |
| 9 | **Ce que le `92,4 %` du 2026-08-16 vaut.** | Q6 de `PROBLEME.md`. Le run de référence porte `{"epochs": 40}` seul, donc `val_source` implicite : il est fuité, et il a tourné sur un autre bake. Il ne se compare à rien de ce qui sera produit ici. |

---

## Voisinage

- [`SUIVI-MATRICE.md`](./SUIVI-MATRICE.md) — le pilotage, D1..D6, les quotas
- [`PROBLEME.md`](./PROBLEME.md) — le défaut d'origine, Q1..Q6
- [`LOT3-JUGE.md`](./LOT3-JUGE.md) §9 — le garde d'espace de labels et ses mutations
- [`LOT4-PREPARATION.md`](./LOT4-PREPARATION.md) — la calibration, le mode compute, le piège d'ordre
- [`LOT4-RESULTATS.md`](./LOT4-RESULTATS.md) — ce que la fuite vaut, et pourquoi le global ment
- [`MATRICE.md`](./MATRICE.md) §7 — l'ordre de travail : **le lot 7 (cet
  entraînement) dépend du lot 1 (la séparation)**. C'est exactement l'arbitrage
  que cette revue trouve encore ouvert.
- Skills : `eurio-cohort`, `eurio-run-local`, `eurio-data-writes`, `eurio-verify`,
  `eurio-vps-deploy`
