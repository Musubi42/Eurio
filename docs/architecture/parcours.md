# Parcours de la donnée — « je fais ça, où part la donnée ? »

> Troisième axe de lecture de l'architecture, à côté de
> [`README.md`](./README.md) (organisé **par stockage**) et
> [`artifacts.md`](./artifacts.md) (organisé **par artefact**). Ici on part du
> **geste** : un déclencheur, et ce qu'il crée, où ça atterrit, comment ça
> voyage, combien de temps ça vit.
>
> **Règle d'écriture de ce fichier.** Un parcours n'est écrit qu'après avoir été
> tracé dans le code **et** vérifié par une mesure. Toute affirmation chiffrée
> porte sa date de mesure. Les trois erreurs corrigées dans `README.md` le
> 2026-08-16 venaient toutes de documents écrits de bonne foi, sans mesure.

| # | Parcours | État |
|---|---|---|
| 1 | Scrape eBay → raws MinIO + `source_images` | à écrire |
| 2 | Crop → crops MinIO + `image_assets` | à écrire |
| 3 | Review / décision humaine → `review_queue` | à écrire |
| **4** | **Cohorte → itération → bake → entraînement** | **✅ ci-dessous (2026-08-16)** |
| **5** | **Promotion d'un modèle → MinIO → APK** | **🚧 tracé et mesuré (2026-08-16), jamais exécuté — cf. §5 en bas** |
| 6 | Export catalogue → Supabase → `app_core.db` | à écrire (décrit partiellement dans `README.md`) |
| 7 | Fetch référentiel (Numista / Wiki) | à écrire |
| 8 | Scan dans l'app → coffre Room | à écrire |

---

# Parcours 4 — Cohorte → itération → bake → entraînement

> Vérifié dans le code et mesuré le **2026-08-16** sur le Mac, à partir de
> l'itération réelle `4aaac6865ca9` (cohorte `aaf3fcd8f717` « again », 6 pièces)
> et de l'état du canonique à cette date.

## En une phrase

**Tout le calcul est local et n'en sort jamais** ; ce qui voyage, c'est l'état
de l'itération (métadonnée + métriques dénormalisées) poussé au canonique. Le
modèle, le dataset augmenté, les lignes de run : ils restent sur le disque de la
machine qui a calculé, dans aucun transport et dans aucune sauvegarde.

## Le trajet

```
[Front /lab — studio-local, route `meta.heavy` → LOCAL uniquement]
   │
   1. POST /lab/cohorts                    → experiment_cohorts     (canonique via lab_writes)
   │
   2. POST …/iterations                    → experiment_iterations  (canonique, status=pending)
   │      • gèle la cohorte (draft → frozen)
   │      • tire un augmentations_seed aléatoire et le persiste
   │      • préflight par CLASSE (≥4 sources réelles, ≥10 crops eBay), sinon 409
   │
   3. POST …/bake  (202, job détaché)      → ml/datasets/<nid>/augmentations/<iid>/sample_NNN.jpg
   │      lit : obverse Numista (FS) + crops eBay reviewés (MinIO via cache) + réfs BCE/JO
   │      écrit aussi : _manifest.json par pièce
   │      puis : ml/datasets/iterations/<iid>/<class_id>/ = symlinks (layout ImageFolder)
   │
   4. POST …/launch-training (job détaché) → ml/lab/iterations/<iid>/
   │      re-bake idempotent → training (ArcFace) → export TFLite → embeddings
   │      lignes de run : training_runs (SQLite LOCAL inscriptible)
   │
   5. benchmark enchaîné                   → benchmark_runs + verdict
   │      lit ml/datasets/eval_real_norm/ (captures device — jamais du training)
   │
   6. à chaque transition : PUT /iterations/<iid> au canonique
          ne voyage QUE : métadonnée + summary_json (R@1, spread, n photos…)
```

## Étape par étape

### 1. La cohorte

`POST /lab/cohorts` (`lab_routes.py:340`) crée une `ExperimentCohortRow` :
un nom, une zone, une liste d'`eurio_ids`. L'écriture passe par
`serving/lab_writes.py` — **c'est le point d'entrée qui décide où va l'écriture** :
sous le flip Direction A (`EURIO_DB_READONLY=1`, le SQLite local est une réplique)
elle part **d'abord** au canonique VPS, et l'échec du VPS est l'échec de la
requête ; hors flip, écriture locale puis push best-effort (F09).

### 2. L'itération

`POST /lab/cohorts/{id}/iterations` (`lab_routes.py:635`) :

- **Préflight bloquant** (`_require_classes_ready` → `foundation/preflight.py`),
  à la maille **classe**, pas pièce : `block` sous `m_per_class` sources réelles
  (défaut **4**), `warn` sous **10** crops eBay réels — et **les deux refusent**
  la création (409). Le refus tombe **avant** le gel, qui est irréversible.
- **Gel de la cohorte** : `draft → frozen`, `frozen_at` stampé. Les `eurio_ids`
  ne bougent plus — c'est ce qui rend les benchmarks suivants comparables.
  Mesuré : `aaf3fcd8f717.frozen_at = 2026-08-16T01:57:05Z`, une seconde après la
  création de l'itération.
- **Seed persisté** : `augmentations_seed` aléatoire, stocké sur la ligne. C'est
  lui qui rend le bake rejouable — le seed par pièce est
  `sha256(iteration_seed:numista_id)` (`iteration_augmentations.py:90`), donc
  regénérer une pièce ne décale pas les autres.
- **Garde par cohorte** : refus 409 si une itération de la même cohorte est déjà
  en `training`.

L'itération naît `pending`. **Aucun travail de fond ne démarre.**

### 3. Le bake

`POST …/bake` (202) lance un job détaché (rail `jobs/`, bookkeeping dans
`ml/state/eurio.local.db` — jamais le canonique).

Sources réelles d'une pièce, dans cet ordre (`real_training_sources`) :

| Source | D'où elle vient | Note |
|---|---|---|
| `obverse.{jpg,png}` | `ml/datasets/<nid>/` sur le disque | avers Numista |
| crops eBay | MinIO `enrichment-crops` via `local_path()` (cache read-through) | uniquement `training_eligible=1`, `face != 'reverse'` |
| réfs officielles | `coin_canonical_images.local_path` (BCE, EUR-Lex JO) | filet pour les classes pauvres |

**Les captures device ne sont jamais une source de training** — elles sont la
vérité-terrain du bench (Doctrine A). Le revers non plus : le modèle ArcFace ne
voit que l'avers.

Cible par classe = `ceil(100 / n_sources) × n_sources`, plancher `variant_count`.
Mesuré sur `at-2008-2eur-standard-2nd-map` : 16 sources → facteur 7 → **112
samples**, ce que dit son `_manifest.json`.

Bake complet de l'itération, mesuré : **787 samples, 37 Mo**, 7 pièces, ~6 min
sur le Mac — **cache froid**, l'essentiel du temps part en téléchargement des
crops depuis MinIO. Sur cache chaud c'est un autre ordre de grandeur : 390
samples en **~4 s** lors de l'exercice #1 (2026-08-16). Une mesure de durée de
bake ne veut donc rien dire sans préciser l'état du cache.

### 4. L'entraînement

`POST …/launch-training` → job détaché → `training/run_iteration.py` →
`IterationRunner._do_training_phase`.

- **Re-bake idempotent** avant de lancer (`_launch_training`) : rien n'est
  régénéré **si les entrées sont identiques** — comparaison sur `inputs_digest`,
  pas sur le nombre de fichiers (cf. piège ④).
- Le dataset d'entraînement est `ml/lab/iterations/<iid>/dataset/train`, un
  **symlink** vers `ml/datasets/iterations/<iid>/`, lui-même un arbre de symlinks
  vers les samples persistants. Trois niveaux d'indirection, tous locaux.
- Tout l'artefact vit sous `ml/lab/iterations/<iid>/` : `checkpoints/best_model.pth`,
  `tflite/`, `embeddings/`, `metrics/`, `reports/`.
- Mesuré sur `4aaac6865ca9` : 10 epochs, **239 s**, `device=mps`, puis export
  TFLite. De la création de l'itération au `.tflite` : **~19 min**.

### 5. Le benchmark et le verdict

Enchaîné par défaut, sous le **même verrou global** (une chaîne à la fois : GPU
partagé). Il évalue le modèle de l'itération contre **ses propres centroïdes**
(`embeddings/embeddings_v1.json`) sur `ml/datasets/eval_real_norm/` — 180 photos
device sur le Mac au 2026-08-16.

Le verdict (`iteration_logic.compute_verdict`) compare le R@1 au parent :
±2 pts = mouvement réel, ≤0,5 pt = `no_change`, −3 pts sur une zone pollue un
`better` en `mixed`.

Le statut de l'itération **n'est pas** touché par l'issue du benchmark : un
benchmark raté laisse l'itération `completed` et se signale ailleurs
(`i4.studio.state='partial'`).

### 6. Ce qui remonte au canonique

À chaque transition, `_sync_canonical` fait `PUT /iterations/<iid>` (après avoir
poussé la cohorte parente — sinon 409 FK). Le canonique
(`iteration_sync_routes.py`) **stocke l'état, jamais le calcul** : il null
délibérément les références qu'il ne peut pas résoudre (recipe, parent, et
surtout `training_run_id` / `benchmark_run_id`).

## La table du parcours

| Quoi | Où | Machine | Transport | Vie | Régénérable ? |
|---|---|---|---|---|---|
| Cohorte, itération, verdict, `summary_json` | `experiment_cohorts` / `experiment_iterations` | **canonique VPS** | HTTP `PUT /iterations` | permanent, sauvegardé | non (c'est la décision humaine) |
| Samples augmentés | `ml/datasets/<nid>/augmentations/<iid>/` | machine de calcul | **aucun** | jusqu'au `clear` | oui — seed + sources ⇒ déterministe |
| Staging ImageFolder | `ml/datasets/iterations/<iid>/` | machine de calcul | **aucun** | reconstruit à chaque bake | oui, gratuit (symlinks) |
| Checkpoint, TFLite, embeddings, métriques | `ml/lab/iterations/<iid>/` | machine de calcul | **aucun** (jusqu'à promotion) | jusqu'au nettoyage manuel | oui, en ré-entraînant |
| `training_runs`, `benchmark_runs` | SQLite local inscriptible | machine de calcul | **aucun** depuis le 2026-06-02 | permanent local | non |
| Jobs, PID, logs | `ml/state/eurio.local.db`, `ml/state/job_logs/` | machine de calcul | **aucun**, par conception | local | sans objet |
| Progression live | `ml/state/training_progress/<iid>.json` | machine de calcul | **aucun** | jamais purgé | sans objet |

## Les pièges — tous mesurés le 2026-08-16

### ① Le modèle ne voyage pas. Seul son bulletin de notes voyage.

Le canonique porte **5 itérations** : 4 stampées `created_on='pc'`, 1 `'mac'`.
Sur ces 5, **4 ont `training_run_id` et `benchmark_run_id` à NULL** — nullés par
la tolérance FK de l'upsert, parce que les lignes de run n'ont jamais quitté la
machine de calcul. Les 34 `training_runs` présents au canonique s'arrêtent au
**2026-06-02** : c'est un reliquat de l'époque où la base locale était copiée en
bloc, pas un flux vivant.

Conséquence concrète : depuis le Mac, une itération entraînée sur le PC est
**visible et chiffrée** (`summary_json` porte R@1, spread, nombre de photos) mais
son modèle est **inaccessible**. Il n'y a pas de « télécharger le checkpoint ».
Vérifié : `ml/lab/iterations/` sur le Mac ne contient que 2 dossiers, alors que 5
itérations existent au canonique.

C'est un choix assumé (`iteration_sync_routes.py` le dit), pas un bug. Mais il
faut le savoir avant de promettre à quelqu'un « je te regarde ça depuis mon Mac ».

### ② Le mode compute écrivait dans une base que la promotion ne savait pas lire — **corrigé le 2026-08-16**

Le contournement documenté du flip (skill `eurio-run-local` : `VACUUM INTO
eurio.work.db` puis `EURIO_DB_PATH=…work.db`) met les résultats dans
`ml/state/eurio.work.db`. Or `scripts/promote_iteration.py` codait en dur
`STATE_DB = ml/state/eurio.db` et **ignorait `EURIO_DB_PATH`** — seul entrypoint
du parcours à le faire, tous les autres (`training/run_*.py`, `coin_lookup`,
`train_embedder`) passaient déjà par `resolve_db_path`.

Constaté sur l'itération du jour, entraînée, exportée, artefacts complets sur
disque :

```
$ .venv/bin/python -m scripts.promote_iteration 4aaac6865ca9 --dry-run
Iteration 4aaac6865ca9 not found in …/ml/state/eurio.db
```

Comptes des trois fichiers au même instant : `eurio.db` = 2 itérations,
`eurio.work.db` = 5, `eurio.replica.db` = 5. Le parcours se terminait donc en
**cul-de-sac** sur le Mac : entraîner oui, promouvoir non.

Le script résout maintenant sa base comme le reste du parcours, et son message
d'erreur nomme le `EURIO_DB_PATH` effectif. Vérifié :

```
$ EURIO_DB_PATH=$PWD/state/eurio.work.db \
    .venv/bin/python -m scripts.promote_iteration 4aaac6865ca9 --dry-run
{ "iteration": "4aaac6865ca9", "verdict": "baseline", "diff": { "n_new": 6, … } }
```

⚠️ **La promotion doit tourner sous le même `EURIO_DB_PATH` que l'entraînement.**
Sans lui, elle lit `eurio.db` et ne voit rien — c'est correct, mais ça se dit
maintenant dans le message.

**Et ce correctif en ouvrait un autre, trouvé en déroulant l'exercice #1.** Faire
lire `EURIO_DB_PATH` au script le fait pointer **par défaut sur la réplique**,
puisque c'est le devShell qui pose cette variable. Or la réplique porte
l'itération `completed` avec `training_run_id = NULL` (le canonique null ces
colonnes, cf. piège ①). La promotion **réussissait donc**, en écrivant un
`promoted_from.json` sans lien vers le run : plus rien ne reliait le modèle en
prod à ce qui l'avait produit. Mesuré côte à côte sur `caf98145032c` :

```
réplique        : completed | run=NULL     | bench=NULL
base de calcul  : completed | run=95211d6c | bench=a2b799d71b1c
```

Garde ajoutée : `completed` **sans** `training_run_id` ⇒ refus qui nomme le geste
(« promeus depuis la base de CALCUL »), `--force` pour passer outre. Deux tests
dans `ml/tests/test_promote.py`. La règle générale, elle, tient en une ligne :
**la promotion se fait depuis la base qui porte le run, jamais depuis la
réplique** — la réplique sait *que* ça s'est bien passé, pas *quoi* l'a produit.

### ③ L'entraînement baker des pièces que tu n'as pas choisies

La maille d'entraînement est le `design_group`, pas la pièce. Le bake étend donc
l'ensemble à **l'union des membres des groupes** de la cohorte.

Mesuré : cohorte de **6 pièces** → **7 dossiers d'augmentation**. La pièce en
trop est `at-2008-2eur-standard-2nd-map` (nid 9761), jamais sélectionnée par
l'utilisateur, tirée par le groupe `at-2euro-standard-t1` que partage
`at-2002-2eur-standard-1st-map`. Elle a produit 112 des 787 samples, soit **14 %
du dataset**. C'est voulu (`class_manifest.json` le documente pièce par pièce),
mais ça surprend au premier run et ça fausse toute lecture « j'ai entraîné sur
mes 6 pièces ».

### ④ Le bake était idempotent par comptage, pas par contenu — **corrigé le 2026-08-16**

`generate_for_iteration` comparait `len(existing)` à la cible. Si le compte y
était, il ne régénérait rien — mais il **réécrivait quand même `_manifest.json`**
en re-dérivant `sources[i % len(sources)]` sur la liste de sources **du moment**.

Observé sur `4aaac6865ca9` : les samples ont un mtime de **02:05 UTC**, leurs
manifestes sont stampés **02:11:11 UTC** — l'heure du re-bake au lancement, qui
n'a régénéré aucune image. Une source ajoutée ou retirée entre les deux (review,
réattribution d'un crop) faisait attribuer les samples à des sources qui ne les
avaient pas produits, **sans que rien ne le signale**.

Depuis, l'idempotence porte sur **l'identité des entrées** : le manifeste (v2)
embarque un `inputs_digest` = **configuration** de la recette + seed + cible +
liste ordonnée des sources (chemin et taille), et le snapshot n'est réutilisé que
si ce digest, le nombre de samples et les fichiers listés concordent.

> La première version hachait le `recipe_id` et non la config — creux, puisque
> `PUT /lab/recipes/{id}` modifie une recette **en place**. Éditer une recette
> puis re-baker réutilisait alors l'ancien travail en affirmant la nouvelle
> recette. Trouvé par revue adversariale, pas par le test : mes tests ne
> faisaient varier que les sources. Sinon on régénère — c'est déterministe
(même seed, mêmes sources ⇒ mêmes octets), donc un faux négatif ne coûte que du
CPU alors qu'un faux positif écrivait une provenance fausse. Et le manifeste
n'est plus écrit que par le chemin qui produit réellement les images.

Deux effets de bord réglés au passage : les snapshots **v1** (sans digest) sont
régénérés une fois, et une cible qui **baisse** ne laisse plus de samples
orphelins — le staging symlinke tout `sample_*.jpg`, ces reliquats entraient donc
dans le dataset.

Couvert par 4 tests dans `ml/tests/test_iteration_augmentations.py`, dont celui
du cas historique (sources modifiées à cible constante). Vérifié qu'ils échouent
sur le code d'avant.

### ⑤ Rien de ce parcours n'est sauvegardé

Vérifié par `git check-ignore` : `ml/datasets/iterations/`,
`ml/datasets/*/augmentations/`, `ml/lab/iterations/`, `ml/state/*.db`,
`ml/state/training_progress/` — **tous ignorés**. Et la chaîne de sauvegarde
(`infra/backup/`) tourne **sur le VPS uniquement**.

Ce qu'elle couvre, vérifié dans la copie hors site (4 Go sur pCloud, lot 0) :
`eurio.db` canonique, `review.db`, et les trois buckets MinIO. Autrement dit
**tout ce qui est canonique, et rien de ce qui est calculé**.

Donc : un `git clean -xdf` ou une panne de disque sur la machine de calcul
détruit les checkpoints, les datasets augmentés **et les lignes de run**. Les
samples sont régénérables (seed + sources), les lignes de `training_runs` ne le
sont pas — elles n'existent que dans un `eurio.work*.db` local, gitignoré et hors
sauvegarde. La perte réelle est l'historique, pas les images.

⚠️ Corollaire de procédure, appris de justesse le 2026-08-16 : **ne jamais
recréer une base de calcul en écrasant** (`rm` + `VACUUM INTO`), ce qui était la
recette écrite dans la skill. `VACUUM INTO` un **fichier neuf** et pointer
`EURIO_DB_PATH` dessus. Le motif `.gitignore` a été élargi à `eurio.work*.db`
en conséquence — un fichier de 145 Mo non ignoré n'attend qu'un `git add`
distrait.

### ⑥ Des résidus locaux sans propriétaire

15 fichiers dans `ml/state/training_progress/` (dont un `itstop.json`) pour 5
itérations au canonique, et 209 fichiers dans `ml/state/job_logs/`. Rien ne les
purge. Le rail `jobs/` actuel, lui, ne connaît que 3 lignes dans
`eurio.local.db` — l'écart mesure l'accumulation d'avant sa mise en place.

### ⑦ Un message d'aide qui pointe un module inexistant

`vision/sync_eval_real.py` et plusieurs messages d'erreur
(`prepare_dataset.py:331`, `train_embedder.py:814`) disent de lancer
`python -m scan.sync_eval_real`. **Il n'y a pas de package `ml/scan/`.** La bonne
commande est `go-task ml:eval-real:sync -- <debug_pull_dir>` (qui appelle
`vision.sync_eval_real`).

## Le parcours a été déroulé en entier — exercice #1, 2026-08-16

Écrire le parcours ne suffit pas à prouver qu'il marche. Il a donc été joué de bout
en bout sur le Mac : cohorte `0b4cb60ce342` (3 pièces) → itération `caf98145032c`
→ bake → entraînement 5 epochs → benchmark → verdict `baseline` → `promote
--dry-run`. Déroulé complet, chiffres et incidents :
[`../work-in-progress/HANDOFF-2026-08-16.md`](../work-in-progress/HANDOFF-2026-08-16.md)
§Exercice #1.

Ce que l'exécution a confirmé, et que la lecture du code ne pouvait pas :

- les dimensions **et le gel** arrivent bien au canonique depuis le Mac en mode
  standard (`frozen_at` stampé côté VPS) ;
- après entraînement, le canonique porte statut, verdict et métriques, mais
  `training_run_id`/`benchmark_run_id` **à NULL** — pendant que la base de calcul
  porte les deux. Le piège ① vérifié dans les deux sens, sur une itération neuve ;
- le bake ne réécrit **rien** quand rien ne change, isole la régénération à la seule
  pièce dont une source a bougé, supprime les samples devenus orphelins, et
  reproduit **octet pour octet** le même sample quand la source revient.

Et deux choses qu'elle a **trouvées** : la promotion sans traçabilité (ci-dessus,
piège ②), et le fait que la suite de tests était inexploitable depuis le shell de
dev standard — 246 échecs + 252 erreurs dus au seul flip ambiant, ramenés à 1 échec
préexistant par un fixture `_no_ambient_flip` dans `ml/tests/conftest.py`.

### Exercice #2 — le PC entraîne, le Mac observe

Rejoué le même jour sur la frontière inter-machines, avec un run **long
délibérément** (40 epochs, 44 min) : à 80 s, il n'y a aucune fenêtre pour observer
depuis l'autre machine. Cohorte `ab28928bcdc2` (27 pièces), itération
`03f767f998ef`, GPU du PC.

Suivi de bout en bout **depuis le Mac, sans jamais interroger le PC** : `created_on=pc`,
les transitions `pending → training → completed`, puis verdict `baseline` et
métriques (**R@1 0,924 sur 317 photos**, 16 pièces). Et à l'arrivée, la frontière
tient exactement comme décrite : 19 Mo d'artefacts et les lignes de run
(`46a6db10`) **restent sur le PC** ; au canonique, `training_run_id` et
`benchmark_run_id` sont NULL.

Trois choses que seule l'échelle a montrées :

- **L'expansion design_group est massive** : 27 pièces de cohorte → **61 pièces
  bakées**, 5051 samples. 56 % du dataset vient de pièces que personne n'a
  choisies (contre 14 % sur la petite cohorte). C'est ce chiffre qui a révélé que
  `clear_for_iteration` et la galerie, qui ne balayaient que la cohorte, en
  ignoraient la moitié.
- **Le rail `jobs/` tient sa promesse** : l'API a été tuée en plein bake ; le
  subprocess détaché a survécu et fini ses 5051 samples.
- **Le Mac ne voit pas l'exécution, seulement l'état.** Epochs, loss et ETA vivent
  dans `ml/state/training_progress/<iid>.json` **sur la machine de calcul** ; le
  canonique n'expose aucune route de progression. Pour suivre une run en direct,
  il faut être sur la machine — ou passer par ssh.

⚠️ **Et une panne muette, trouvée là** : une API lancée en mode compte **sans**
`EURIO_API_URL` (hors `sops exec-env`) crée des cohortes et des itérations qui
n'atteignent **jamais** le canonique — HTTP 200, push F09 no-op, invisible
ailleurs. Sous le flip le même cas échoue franchement en 503 ; c'est donc
précisément le mode dans lequel on entraîne qui était aveugle. Un avertissement
au boot de l'API le signale désormais (`serving/server.py`).

## Frontières de ce parcours

- **En amont** : les crops eBay `training_eligible=1` viennent des parcours 2 et
  3. Une cohorte refusée au préflight se répare **là-bas**, pas dans le lab.
- **En aval** : `scripts/promote_iteration.py` (lab → `ml/prod/current/`) puis
  `ml:assets:publish` (→ MinIO `model-artifacts` → APK) sont le **parcours 5**.

  ⚠️ **Cette suite n'a jamais été parcourue.** Mesuré le 2026-08-16 : `ml/prod/`
  n'existe **ni sur le Mac ni sur le PC**, et le manifeste `shared/model-assets.json`
  montre que les artefacts publiés dans MinIO viennent de
  `app-android/src/main/assets/…`, donc des fichiers copiés à la main de l'époque
  — pas d'une promotion. Aucun modèle entraîné dans le lab n'est jamais arrivé
  dans l'APK par ce chemin. (À ne pas confondre avec « la promotion est PC-only » :
  `promote_iteration` crée `ml/prod/` à la demande sur n'importe quelle machine.
  C'est le script *legacy* `promote_prod_assets.py` qui est PC-only.)
- **À côté** : le détecteur YOLO (dataset de détection + `best.pt`) a sa **propre**
  chaîne, `ml:training-assets:*`, décrite dans [`README.md` §3](./README.md). Il ne
  passe pas par le lab.

---

# Parcours 5 — Promotion d'un modèle → MinIO → APK

> Tracé dans le code et mesuré le **2026-08-16**. ⚠️ **Jamais exécuté** : à la
> différence du parcours 4, rien ici n'est prouvé par une exécution. Ce qui suit
> dit ce que le code fait et ce que l'état actuel permet de mesurer — pas ce
> qu'on a vu marcher.

## Le trajet, et ses quatre outils

```
ml/lab/iterations/<iid>/          (sortie du parcours 4)
   │  scripts/promote_iteration.py <iid>
   │     • copie ATOMIQUE des 3 dossiers → prod/current   (archive l'ancien)
   │     • écrit promoted_from.json (sha256 de chaque fichier)
   │     • POUSSE SUPABASE — pas optionnel, cf. ci-dessous
   ▼
ml/prod/current/{checkpoints,embeddings,tflite}
   │  scripts/promote_prod_assets.py     (docs : « PC uniquement »)
   ▼
app-android/src/main/assets/{models,data}
   │  go-task ml:assets:publish  → MinIO `model-artifacts` + réécrit
   │                                shared/model-assets.json (committé)
   ▼
MinIO  ──  go-task ml:assets:fetch  (preBuild Gradle)  ──▶  APK
```

Quatre étapes, trois outils distincts, dont **un documenté comme obsolète**
(`ml:deploy` → `ml/output/`, supprimé) et **un troisième chemin** qui fait la même
chose en silence (`POST /export/deploy`, qui renvoie `200 {count: 0}` si la source
manque). Cf. `README.md` §« Trois mécanismes de déploiement d'assets ».

## Ce que l'état actuel dit — mesures

**Le modèle en production tient en 23 classes.** Récupéré depuis MinIO par
`ml:assets:fetch` : `coin_embeddings.json`, 23 entrées, clés = `numista_id`.

**Sa liste de classes est périmée.** `model_meta.json` nomme les classes par des
slugs qui n'existent plus au référentiel : `at-2eur-standard-2002` (aujourd'hui
`at-2002-2eur-standard-1st-map`), `es-2016-2eur-old-city-of-segovia…`
(`…-old-town-…`), `de-2007-2eur-schwerin-castle…`
(`…-state-of-mecklenburg-vorpommern`). Sans conséquence fonctionnelle immédiate —
l'app matche sur la clé `numista_id`, stable — mais toute lecture humaine de ce
fichier est trompeuse.

**Les deux espaces de clés coexistent, et c'est voulu.** Le lab produit
`coin_embeddings.json` (plat, clés `numista_id` → ce que lit `EmbeddingMatcher`)
**et** `embeddings_v1.json` (riche, clés `class_id` → ce que pousse Supabase et ce
que compare le diff de promotion). Vérifié sur une itération réelle. Promouvoir ne
casserait donc pas le scan.

## Le piège principal : la promotion REMPLACE, elle n'accumule pas

`_atomic_copy` remplace `prod/current` en bloc. Le fichier d'embeddings embarqué
dans l'APK est donc **substitué**, pas fusionné. Or le nom du drapeau
`--replace-all` et le vocabulaire du diff (`added` / `kept` / `absent_in_promotion`)
suggèrent le contraire : `--replace-all` ne pilote QUE la suppression des **lignes
Supabase** devenues orphelines. Les classes listées dans `absent_in_promotion` sont
exactement celles qui **disparaîtront de l'APK**, sans que rien ne les retienne.

Mesuré sur l'itération du PC (`03f767f998ef`) contre la production actuelle :

| | classes |
|---|---|
| en production aujourd'hui | 23 |
| itération du PC | **61** (l'expansion design_group, cf. parcours 4 ③) |
| communes | 20 |
| **perdues** si on promeut | **3** — `fr-1999-2eur-standard-1st-map`, `fr-2007-2eur-standard-2nd-map`, `es-2010-2eur-standard-juan-carlos-i-2nd-type-2nd-map` |
| gagnées | 41 |

Le bilan net est très favorable (23 → 61), mais trois pièces reconnues aujourd'hui
cesseraient de l'être. Ce n'est pas un bug : c'est le contrat du script. C'est un
**arbitrage produit**, et il doit être fait en le sachant.

## Le second piège : promouvoir écrit en production, sans option

`promote()` appelle `_push_supabase()` **inconditionnellement** (hors `--dry-run`,
qui ne fait rien du tout). Il n'existe aucun `--no-supabase`. Conséquence : on ne
peut pas exercer la chaîne locale — copier vers `prod/current`, vérifier les sha,
rafraîchir les assets — **sans écrire dans la base que consomme l'app en prod**.
C'est le même couplage que celui qui faisait échouer `build-app-core` quand
Supabase était injoignable (cf. `README.md`), et il rend le parcours 5 impossible à
répéter à blanc.

## Ce qu'il faudrait pour l'exercer proprement

1. Un `--no-supabase` (ou `--local-only`) sur `promote_iteration`, pour séparer le
   geste local du geste de production.
2. Trancher le sort des 3 classes perdues : les accepter, ou entraîner une
   itération dont la cohorte les couvre.
3. Alors seulement : promotion réelle → `promote_prod_assets` → `ml:assets:publish`
   → rebuild de l'APK → vérifier que le scan reconnaît une pièce nouvellement
   couverte.

⚠️ Et un détail qui mordra à l'étape 3 : `AppCoreBootstrapper.kt` gate le
rechargement du catalogue sur `APP_CORE_VERSION`, **constante codée en dur jamais
incrémentée** (cf. `README.md`). Ça concerne `app_core.db`, pas les embeddings,
mais c'est le même genre de piège dans la même étape.
