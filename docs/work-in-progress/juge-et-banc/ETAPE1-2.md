# Étapes 1 et 2 — le parc mesuré, et le jeu d'évaluation prélevé

> Session du **2026-08-26**, sur le **Mac**. Pilotage :
> [`SUIVI-MATRICE.md`](./SUIVI-MATRICE.md). Ce fichier porte le détail et les
> commandes ; chaque chiffre est suivi de la requête qui le rend.
>
> ⚠️ **Rien n'a été appliqué au canonique en étape 2, et rien n'a été déployé.**
> L'étape 1 (backfill des mesures), elle, EST écrite au canonique — c'était son
> objet. Ce que le PO doit lancer est au §« Ce qui attend le PO ».

---

## Étape 1 — backfill `quality_score` + tilt sur le parc

### La décision sur le coût d'éviction du cache : `EURIO_CACHE_MAX_GB=0`

**Choix : poser `EURIO_CACHE_MAX_GB=0` le temps de la passe.** Aucun code
touché, aucune régression possible, et — c'est le point — **le résultat est
strictement identique** : l'éviction n'aurait rien évincé.

La démonstration, plutôt que l'intuition :

```bash
du -sh ~/.cache/eurio                       # 15G  (dont enrichment-raws 12G)
echo "$EURIO_CACHE_MAX_GB"                  # 20
```

`_evict_if_needed()` (`ml/shared/storage/local_cache.py:250`) ne supprime que si
`total > max_bytes`. À 15 Go pour un plafond de 20 Go, la boucle `while` ne
s'exécute jamais — le `rglob` complet est du travail pur, jeté. Restait à
vérifier que la passe ne franchirait pas le plafond :

```bash
cd ml && ./.venv/bin/python - <<'PY'
… # raws distincts à examiner, et combien sont déjà en cache
PY
# raws distincts: 11118 en cache: 9539 (85.8%) à télécharger: 1579
```

1 579 raws à télécharger, pour une taille moyenne de 12 Go / 30 385 fichiers
≈ 0,4 Mo → **+0,6 Go**, soit 15,6 Go contre un plafond de 20 Go. Le plafond
n'aurait donc pas été atteint pendant la passe non plus.

Le coût, lui, était bien réel — mesuré ici, et plus bas que le chiffre du SUIVI
(1,87 s ; le cache OS était chaud) :

```bash
cd ml && for i in 1 2 3; do ./.venv/bin/python -c "
import time,sys; sys.path.insert(0,'.')
from shared.storage import local_cache
t=time.perf_counter(); local_cache._evict_if_needed(); print(f'{time.perf_counter()-t:.2f} s')"; done
# 1.36 s / 1.39 s / 1.33 s   (62 583 fichiers)
```

**1 579 téléchargements × 1,35 s ≈ 35 min** de balayage pur, contre ~7,4 min de
CPU d'oracle (17 678 × 0,025 s). L'éviction dominait le coût d'un facteur ~5,
pour un effet nul.

⚠️ **Le vrai défaut reste ouvert, et il n'est pas de ma main** :
`_evict_if_needed` rglob **avant chaque téléchargement**, sans mémoriser la
taille totale. Toute passe massive future repaiera la même taxe. Le correctif
(mémoriser le total au niveau module, ne rglob qu'au franchissement) est à
inscrire au reste-à-faire — il n'a pas été fait ici : le changer sans mesure
aurait été un correctif non vérifié dans une session qui en interdit.

### La passe

```bash
cd ml && EURIO_CACHE_MAX_GB=0 ./.venv/bin/python -m scripts.backfill_quality_score --apply
```

Sortie finale, **le critère** :

```
  mesurés          : 17678
  score obtenu     : 10483 (59.3 %) — oracle muet : 7195 (40.7 %, NULL = NON MESURÉ)
  tilt mesuré      : 17594 (fiable : 8735)
    ok [0.85,1.0]             8968 (85.5 %)
    penalised [0.60,0.85)     1421 (13.6 %)
    severe (<0.60)              94 (0.9 %)

destination : canonique (POST /ingest/quality-scores)
{"updated": 17658, "skipped": 20, "missing": 0}
```

**`missing = 0`.** Les 20 `skipped` sont les 20 crops d'une passe de fumée
lancée juste avant (`--limit 20 --batch 10`, `{"updated": 20, "skipped": 0,
"missing": 0}`) : l'anti-rétrogradation de `store/quality.py` les a
reconnus, ce qui prouve accessoirement que le garde d'idempotence mord.

Le code de retour a été lu **sans pipe** (`; echo "exit=$?"`) à chaque étape ;
la passe de fumée a servi à vérifier que la route rendait 200 avant d'engager
50 minutes.

### La couverture obtenue — mesurée après `go-task ml:db:pull-replica`

```bash
cd ml && sqlite3 -header -column "file:state/eurio.replica.db?mode=ro" "
select count(*) parc, sum(quality_score is not null) quality,
       round(100.0*sum(quality_score is not null)/count(*),1) pct_q,
       sum(tilt_deg is not null) tilt,
       round(100.0*sum(tilt_deg is not null)/count(*),1) pct_t,
       sum(tilt_trustworthy=1) tilt_fiable,
       sum(quality_pipeline_version is not null) examine
  from image_assets;"
```

| | avant (2026-08-25) | **après** |
|---|---:|---:|
| parc `image_assets` | 18 730 | 18 730 |
| `quality_score` non NULL | 1 052 (**5,6 %**) | **11 535 (61,6 %)** |
| `tilt_deg` non NULL | ~21,5 % du pool | **18 645 (99,5 %)** |
| dont `tilt_trustworthy=1` | — | 9 237 (49,3 %) |
| **examinés** (`quality_pipeline_version`) | 1 052 | **18 730 (100 %)** |

Sur le pool qui compte — crops eBay `training_eligible=1` :

```bash
cd ml && sqlite3 -header -column "file:state/eurio.replica.db?mode=ro" "
select count(*) pool_eligible, sum(quality_score is not null) quality,
       round(100.0*sum(quality_score is not null)/count(*),1) pct_q,
       sum(tilt_deg is not null) tilt,
       round(100.0*sum(tilt_deg is not null)/count(*),1) pct_t
  from image_assets a join source_images si on si.id=a.source_image_id
 where a.training_eligible=1 and si.source='ebay';"
# 2968 | 1942 | 65.4 | 2965 | 99.9
```

`quality_score` : **8,8 % → 65,4 %**. `tilt_deg` : **21,5 % → 99,9 %**.
C'est ce qui rend l'étape 2 possible, et c'est **`tilt_deg`, pas
`quality_score`, qui devient l'instrument** : à 99,9 % de couverture il n'exige
aucune imputation, là où `quality_score` en demanderait pour un tiers du pool.

⚠️ **La limite de méthode est intacte** : 40,7 % des crops gardent un score
`NULL` = *non mesuré*, jamais *mauvais*, et l'oracle reste **aveugle au mauvais
objet** (un crop sur une capsule est scoré « ok »). Poser
`quality_pipeline_version` sur ces 40,7 % est ce qui évite de les
re-télécharger à chaque passage.

---

## Étape 2 — prélever, marquer, exclure

### Le critère de sélection — D5, appliqué

🔴 **Aucun modèle appris n'intervient.** Ni distance DINO à la canonique, ni
score ArcFace, ni embedding. Le raisonnement est celui du SUIVI §D5 et il n'est
pas rouvert ici.

La règle, en toutes lettres (`ml/scripts/select_eval_holdout.py`, docstring de
module) — pour chaque classe, maille `COALESCE(design_group_id, eurio_id)` :

1. **pool candidat** = crops eBay, `training_eligible=1`, `storage_status='present'`,
   non-revers, `eval_corpus IS NULL`, `tilt_deg` **mesuré**, et **qui ne sont pas
   des ancres de la banque servie `2eur_all`** ;
2. ordre par **`(tilt_deg DÉCROISSANT, id CROISSANT)`** — l'`id` est le bris
   d'égalité, il rend l'ordre **total** ;
3. on retient la **moitié la plus inclinée** (`m = ceil(n/2)`) ;
4. on y prend **5 positions régulièrement espacées** :
   `idx_k = floor((2k+1) × m / 10)`, `k = 0…4`.

**Aucun aléatoire n'intervient — il n'y a donc pas de graine à fixer**, et
« rejouable » n'est pas un mot : `test_la_selection_est_rejouable_a_lidentique`
compare deux exécutions.

*Pourquoi les quantiles et pas « les 5 pires »* : un jeu fait des 5 crops les
plus tiltés de chaque classe serait un jeu d'extrêmes, où une valeur aberrante
de l'ellipse (arc partiel, reflet) pèserait autant qu'une vraie photo de biais.
Les quantiles gardent le biais « dégradé » **et** balaient l'étendue visée.

### Les biais introduits — il y en a toujours

À citer avec le résultat, jamais après :

* **le jeu est plus dur que la population**, par construction. Mesuré :

  ```bash
  cd ml && sqlite3 -header -column -readonly \
    "file:$PWD/state/eurio.work.evalholdout.db?immutable=1" "<cf. §Vérification>"
  ```

  | ensemble | n | tilt moyen | tilt min–max | quality moyen |
  |---|---:|---:|---|---:|
  | **jeu d'éval** | 300 | **16,43°** | 5,5 – 39,2 | 0,906 |
  | pool restant (mêmes 60 classes) | 1 905 | 12,75° | 1,7 – 47,6 | 0,921 |

  +29 % d'inclinaison moyenne. **Les taux absolus des deux modèles seront donc
  pessimistes ; seule leur COMPARAISON est lisible.**
* `tilt_deg` **ne mesure pas que l'inclinaison** : un fort tilt apparent peut
  venir d'une pièce partiellement occultée, d'un arc incomplet ou d'un reflet
  qui déforme l'ellipse. Le jeu contient donc aussi des crops *mal détourés*,
  pas seulement des prises de vue obliques ;
* `tilt_trustworthy` **n'est pas exigé** (199/300 le sont) : le restreindre
  couperait le pool et, surtout, les mesures « non fiables » sont précisément
  celles des crops difficiles — les écarter ramènerait le jeu vers le facile, à
  rebours de l'intention. Le drapeau `--require-trustworthy` existe pour
  fabriquer l'autre jeu si on veut mesurer l'écart ;
* **exclure les ancres appauvrit le pool de sa diversité d'apparence** (le FPS
  les a choisies pour ça) : 751 crops écartés à ce titre sur les 60 classes. Le
  jeu est donc un peu plus « typique » que le pool complet. C'est le prix,
  assumé, de ne pas mesurer DINO contre lui-même ;
* `quality_score` **n'entre pas dans le classement** — muet sur 1/3 du parc ;
  une règle qui imputerait une valeur aux muets choisirait en fait
  *l'imputation*. Il est reporté à titre descriptif ;
* le rang 0 (le crop **le plus** incliné de chaque classe) n'est jamais pris :
  les quantiles sont des milieux d'intervalle. C'est délibéré — c'est là que
  vivent les aberrations d'ellipse.

### Le résultat — 60 classes, 300 crops

```bash
cd ml && ./.venv/bin/python -m scripts.select_eval_holdout --plan /tmp/plan.json
```

```
corpus             : matrice-encodeurs-2026-08 (règle v1)
classes retenues   : 60
crops prélevés     : 300
écartées (plancher) : 190
tilt des prélevés  : min 5.5° · médiane 15.7° · max 39.2°
tilt fiable        : 199/300
{"updated": 0, "skipped": 0, "conflict": 0, "missing": 0, "dry_run": true, "a_marquer": 300}
```

**60 × 5 = 300**, exactement la cible de D1/D2 — et le chiffre est retrouvé
**indépendamment** du SUIVI, par une requête qui compte les classes :

```bash
cd ml && sqlite3 -header -column "file:state/eurio.replica.db?mode=ro" "
with p as (select coalesce(co.design_group_id, co.eurio_id) cid, count(*) n
   from image_assets a join source_images si on si.id=a.source_image_id
   join coins co on co.eurio_id=a.eurio_id
  where si.source='ebay' and a.training_eligible=1 and a.storage_status='present'
    and (a.face is null or a.face!='reverse') group by 1)
select sum(n>=10) 'classes>=10', sum(n>=15) 'classes>=15', count(*) classes_avec_crops from p;"
# 68 | 60 | 250
```

68 classes à ≥ 10 crops, **60 à ≥ 15** (= `quota 5 + MIN_REAL 10`). Les 8
perdues sont bien celles de D2.

### Le marquage — migration `0014`, colonne `image_assets.eval_corpus`

**Une colonne TEXTE, pas un booléen** : elle nomme le corpus
(`matrice-encodeurs-2026-08`), ce qui permet d'en avoir plusieurs, de savoir
lequel a servi à quelle mesure, et de relire le hold-out des mois plus tard.
`NULL` = pas d'éval, et c'est le défaut de tout le parc.

**Pourquoi pas `training_eligible = 0`** : il porte le verdict de la **review**
(« ce crop est-il bon ? »), pas un **rôle** (« à quoi sert-il ? »). Les
confondre ferait disparaître les 300 crops des compteurs de review et rendrait
un retour au train indistinguable d'une réhabilitation.

Le **contrat de miroir à trois branches** est tenu, et chaque branche a son
test :

| branche | où | garde |
|---|---|---|
| `ALTER … ADD COLUMN` | `ml/serving/migrations/0014_eval_corpus_holdout.sql` | ajoutée à la liste **`exclues`** de `tests/test_schema_mirror.py` (jamais `MIROIR_ATTENDU` : la migration n'est pas rejouable sur une base vide) |
| miroir | `ml/state/schema.sql` — colonne **et** index partiel | `test_la_migration_0014_est_bien_un_alter_et_un_index`, `test_une_base_neuve_nait_avec_eval_corpus` |
| `_ensure_column` | `ml/store/connection.py`, **en PRE-bootstrap** | `test_une_base_anterieure_rattrape_eval_corpus` |

⚠️ **Le piège de la troisième branche a été rencontré pour de vrai.** Posé
d'abord dans le bloc `_ensure_column` **post**-`executescript`, il était trop
tard : `schema.sql` crée l'index PARTIEL
`idx_image_assets_eval_corpus ON image_assets(eval_corpus) WHERE …`, qui
échoue en `no such column: eval_corpus` **avant** que le rattrapage ne tourne.
C'est le test qui l'a dit — il a été écrit avant le correctif, et il a rougi.
Le `_ensure_column` vit désormais juste avant `conn.executescript(schema)`,
même patron que `run_id` / `stale_since`.

### L'exclusion de l'entraînement — les DEUX voies

Il n'y a **pas de point unique en amont** (SUIVI §Étape 2). Le prédicat est
écrit deux fois, et **chaque voie a son test et sa mutation** :

| voie | fichier | prédicat |
|---|---|---|
| ArcFace (et le seed du préflight) | `ml/training/iteration_augmentations.py` — `_ebay_training_sources` | `AND a.eval_corpus IS NULL` |
| ancres DINO | `ml/training/foundation/anchors.py` — `_candidate_crops_for_class` | `AND eval_corpus IS NULL` |

### La propagation « côté MinIO et côté API »

**Côté MinIO : ça n'a pas de sens technique, et je ne l'invente pas.** La clé S3
d'un crop est **immuable** et sert de jointure partout —
`image_assets.storage_path`, le cache local `local_path("enrichment-crops", …)`,
chaque URL signée déjà émise. Déplacer les 300 objets sous un préfixe `eval/`
imposerait de réécrire 300 `storage_path`, invaliderait le cache local
correspondant, et **n'apporterait rien** : aucune collecte d'entraînement ne
décide par préfixe S3 — les deux requêtes partent d'`image_assets`. **Les octets
ne bougent pas ; c'est la LIGNE qui porte le rôle.**

Si le PO veut malgré tout le voir depuis la console MinIO, la forme honnête est
un **tag d'objet** (`mc tag set`, métadonnée, ni octet ni clé touchés) — mais il
faut dire ce qu'il vaut : **rien du pipeline ne le lit**, il serait décoratif.
À ne poser que si l'usage est l'œil humain, et à ne jamais traiter comme la
source de vérité.

**Côté API, en revanche, ça a un sens précis, et c'est fait** — trois gestes :

1. **écrire** : `POST /ingest/eval-corpus`
   (`ml/serving/ingest_routes.py`, write-half `ml/store/eval_corpus.py`,
   client `ml/client/ingest.py::push_eval_corpus`). Même doctrine que
   `/ingest/quality-scores` : la sélection tourne où sont les mesures, seules
   les lignes voyagent. Deux gardes — un crop **ne change jamais de corpus en
   silence** (`conflict`), et le retrait exige de **nommer** le corpus qu'on
   croit retirer (`expect`), rien ne s'efface par omission ;
2. **lire** : `eval_corpus` est exposé dans
   `GET /lab/cohorts/{id}/training-crops` (`store/funnel.py`, modèles
   `serving/lab_read_models.py` et `serving/lab_routes.py`) — le crop reste
   visible et reviewable, avec son rôle affichable ;
3. **compter juste** : `n_eligible` (« part au train », comparé à `min_real`
   pour le verdict `underfed`) **exclut désormais les crops d'éval**. Sans ça le
   panneau annoncerait un effectif que le bake ne prendra jamais — et
   `underfed` mentirait dans le sens rassurant.

Le **plan JSON** (`--plan`) est le quatrième support, et le plus durable : il
liste `asset_id`, `class_id`, `rang`, `tilt_deg`, `quality_score` de chaque
prélèvement. C'est lui qu'il faut garder à côté de la mesure.

---

## Vérification

### Le préflight reste `ready=True` après prélèvement — et il voit la coupe

Joué sur une **copie** (`state/eurio.work.evalholdout.db`, faite par
`VACUUM INTO` — jamais `cp` sur du WAL), avec les 300 marqués, en appelant le
**vrai** `preflight_classes` sur les 60 classes :

| | n_classes | block | warn | **ready** | n_ebay total |
|---|---:|---:|---:|:---:|---:|
| avant prélèvement | 60 | 0 | 0 | **True** | 2 208 |
| **après prélèvement** | 60 | 0 | 0 | **True** | **1 908** |

**Aucune classe ne tombe.** L'écart est exactement **−300** : le préflight voit
la coupe, et le quota se raisonne bien sur le reste. La classe la plus juste
retombe à **12** crops (`ad-2015-2eur-30th-anniversary-of-the-age-of-majority-at-18-years`),
soit 2 au-dessus de `MIN_REAL = 10`.

Le `n_ebay` du préflight (2 208) coïncide **au crop près** avec le
`n_train_avant` calculé par la sélection — deux chemins indépendants, même
nombre.

### Les mutations — chaque garde a été cassé, et le bon test a rougi

**Mutation A — prédicat ArcFace retiré** (`iteration_augmentations.py`) :

```
=== MUTATION A — prédicat ArcFace retiré ===
tests/test_eval_holdout.py:137: AssertionError
FAILED tests/test_eval_holdout.py::test_arcface_ne_collecte_pas_un_crop_deval
1 failed, 14 passed in 1.97s
--- et le PRÉFLIGHT réel, même mutation :
étiquette=APRES-MUTATION-A  n_classes=60  block=0  warn=0  ready=True
   n_ebay total sur les 60 classes : 2208
=== revert vérifié ===
15 passed in 2.00s
```

La seconde moitié est la preuve qui compte : **au vrai point d'entrée**, sans le
prédicat, `n_ebay` remonte de 1 908 à **2 208** — les 300 crops d'éval
rentrent au training. Le test unitaire garde le prédicat ; c'est l'exécution qui
garde le câblage.

**Mutation B — prédicat des ancres DINO retiré** (`anchors.py`) :

```
tests/test_eval_holdout.py:154: AssertionError
FAILED tests/test_eval_holdout.py::test_les_ancres_dino_ne_prennent_pas_un_crop_deval
1 failed, 14 passed in 2.10s
=== revert vérifié ===
15 passed in 2.53s
```

**Mutation C — `_ensure_column` pre-bootstrap neutralisé** (`connection.py`) :

```
store/connection.py:335: OperationalError
FAILED tests/test_eval_holdout.py::test_une_base_anterieure_rattrape_eval_corpus
1 failed, 14 passed in 2.71s
=== revert vérifié ===
15 passed in 2.76s
```

### Un défaut trouvé et corrigé par ces tests : une boucle infinie

`quantiles_moitie_haute` bouclait `while idx in rangs or idx >= n: idx += 1` —
sur un pool plus court que le quota, `idx >= n` reste vrai pour toujours. Le
symptôme était **un pytest qui ne rendait jamais la main** : exactement la
famille de pannes de ce dépôt — *un script qui ne répond plus ressemble à un
calcul long, pas à une panne*. Corrigé (`while idx < n and idx in rangs`), et
`test_les_rangs_quantiles_sont_dans_la_moitie_haute_et_distincts` balaie
`n = 10…59` plus les cas courts.

---

## ⚠️ Ce que je n'ai PAS pu établir

* **Le marquage n'est pas au canonique**, donc les 300 crops ne sont pour
  l'instant exclus de l'entraînement **nulle part en production**. Tout ce qui
  est démontré ci-dessus l'est sur une **copie** ou en test. Tant que le PO n'a
  pas joué le §suivant, le hold-out n'existe pas.
* **Le prédicat casse la réplique tant que la colonne n'y est pas.** Et la
  réplique **ne peut pas s'auto-réparer** : `StoreBase._bootstrap` est un no-op
  en lecture seule. Pire, **le processus `:8042` la ré-écrase toutes les 120 s**
  (`client/replica.py::start_autopull`, `EURIO_REPLICA_AUTOPULL_INTERVAL=120`) —
  un `ALTER` posé à la main sur la réplique **disparaît en moins de deux
  minutes, sans un mot**. C'est vécu dans cette session : la requête de contrôle
  a rendu `2968`, puis `no such column` cinq minutes plus tard. **L'ordre de
  déploiement n'est donc pas négociable : la colonne au canonique D'ABORD.**
* Le mode `--require-trustworthy` n'a pas été **mesuré** : je n'ai pas produit
  le jeu alternatif ni comparé les deux. Le drapeau existe, son effet est décrit,
  pas chiffré.
* Aucun **entraînement**, aucune **banque**, aucune **matrice** : étapes 3 à 5.
* Le correctif de `_evict_if_needed` n'est **pas** fait (cf. §Étape 1).

---

## Ce qui attend le PO

**Dans cet ordre. L'ordre est le point.**

1. **Appliquer `0014` au canonique** (VPS) — la colonne d'abord, tout le reste
   ensuite. Sans elle, `_ebay_training_sources` et `_candidate_crops_for_class`
   lèvent `no such column: eval_corpus`, et sous un job détaché ça donne
   **HTTP 200 + silence** :

   ```bash
   # sur le VPS, cf. skill eurio-vps-deploy
   docker compose -f /opt/eurio/infra/eurio-api/docker-compose.yml \
     exec eurio-api sqlite3 /var/lib/eurio/eurio.db \
     < /opt/eurio/ml/serving/migrations/0014_eval_corpus_holdout.sql
   # (ou laisser server_serve.py l'appliquer au boot via _schema_migrations)
   ```

   Contrôle, **sans pipe** :

   ```bash
   sqlite3 -readonly /var/lib/eurio/eurio.db \
     "select count(*) from pragma_table_info('image_assets') where name='eval_corpus';" ; echo "exit=$?"
   # → 1
   ```

2. **Rafraîchir la réplique du Mac** — ou ne rien faire : l'autopull de `:8042`
   la reprend en ≤ 120 s. Pour forcer : `go-task ml:db:pull-replica`.

3. **Déployer la route** `POST /ingest/eval-corpus` (même image que
   `/ingest/quality-scores`), puis vérifier par **l'OpenAPI**, jamais par un
   code HTTP :

   ```bash
   curl -s https://eurio-api.musubi.dev/openapi.json \
     | python3 -c "import json,sys; [print(k) for k in sorted(json.load(sys.stdin)['paths'])]" \
     | grep eval-corpus
   ```

4. **Prélever pour de vrai**, depuis le Mac :

   ```bash
   cd ml
   ./.venv/bin/python -m scripts.select_eval_holdout \
        --plan ../docs/work-in-progress/juge-et-banc/eval-holdout-plan.json     # dry-run, à relire
   ./.venv/bin/python -m scripts.select_eval_holdout \
        --plan ../docs/work-in-progress/juge-et-banc/eval-holdout-plan.json --apply
   # attendu : {"updated": 300, "skipped": 0, "conflict": 0, "missing": 0}
   ```

   ⚠️ **Le plan doit être régénéré après le déploiement, pas repris d'ici** : le
   pool a bougé depuis (review en cours), et c'est le plan **appliqué** qui doit
   être committé à côté de la mesure.

5. **Vérifier que le préflight tient toujours**, sur la vraie cohorte des 60
   classes, avant l'étape 3 :

   ```bash
   curl -s "http://127.0.0.1:8042/lab/cohorts/<cohort_id>/training-readiness" | python3 -m json.tool
   # → ready: true attendu
   ```

6. Alors seulement, **étape 3** : l'entraînement ArcFace sur le PC.
