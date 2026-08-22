# Journal — pipeline propre

> Une entrée par geste : ce qu'on a fait, la commande, le témoin qui prouve
> que ça a tourné, la mesure **avec sa requête**, et la décision ou le lien
> vers [`DECISIONS.md`](DECISIONS.md). Le plus récent en haut. Les chiffres
> sont ceux d'une minute sur `ml/state/eurio.replica.db` : relance la
> requête, ne recopie pas le nombre.

---

## 2026-08-22 — O6 mesuré proprement : l'amorce au médoïde vaut +3,7 pts, et le creux à N=1 disparaît

**Le geste.** Review du PO terminée côté singles (429 acceptés), puis :
seuil `min_exemplars=2` posé au canonique (option A) → rebuild `2eur_all`
amorce **médoïde** → **bras témoin `fps` sur exactement les mêmes données** →
courbes held-out. Le bras témoin est ce qui rend le gain attribuable ; sans
lui on aurait comparé une banque à 1495 ancres (20/08) à une banque à 1831,
c'est-à-dire l'amorce **et** les 429 crops de la review en même temps.

**Protocole du bras témoin, à réutiliser.** Le second build tourne sur une
**copie identique** de la base (`cp` du scratch du premier build), en
`--no-push --db <scratch>` : les références se tracent dans le scratch, la
courbe le lit via `EURIO_DB_PATH`, **le canonique n'est jamais touché**. Seul
le `.npz` servi local est remplacé le temps de la mesure.

```bash
cp $S/eurio_build_scratch.db $S/fps_arm.db
cd ml && EURIO_DB_READONLY= ./.venv/bin/python -m scripts.build_dino_anchors \
  -v --force --kind 2eur_all --seed-order fps --no-push --db $S/fps_arm.db
EURIO_DB_PATH=$S/fps_arm.db ./.venv/bin/python -m scripts.bench_refs_curve \
  --model dinov2_vitl14 --refs 0 1 2 3 5 8 10
```

**Résultat — held-out, population variable, `dinov2_vitl14`, 1831 ancres des
deux côtés, `min_exemplars=2` des deux côtés :**

| N réf./classe | bras `fps` (témoin) | bras **médoïde** (O6) | delta |
|---:|---:|---:|---:|
| 0 *(contrôle)* | 76,2 % | 76,0 % | **−0,2** ✅ |
| 1 | **71,8 %** | **86,8 %** | **+15,0** |
| 2 | 73,5 % | 86,0 % | +12,5 |
| 3 | 75,4 % | 85,7 % | +10,3 |
| 5 | 79,0 % | 86,6 % | +7,6 |
| 8 | 83,3 % | 87,5 % | +4,2 |
| 10 | **84,3 %** | **88,0 %** | **+3,7** |

- **Le contrôle passe** : à N=0 les deux banques sont les 671 canoniques seuls
  et rendent le même score à 0,2 pt près. Les populations held-out diffèrent
  de 6 crops (1191 contre 1185) — la sélection d'exemplaires n'est pas la même,
  donc le complémentaire non plus.
- **Le creux à N=1 est supprimé, pas atténué** : `fps` fait 76,2 → **71,8**
  (−4,4, le premier exemplaire DÉGRADE sa classe) ; médoïde fait 76,0 →
  **86,8** (+10,8). C'est le mécanisme « le rang 1 du FPS est un faux
  attracteur » corrigé à la source, et c'est la preuve la plus solide : elle ne
  dépend pas du niveau absolu.
- **Le gain décroît avec N**, ce qui est cohérent : plus la classe a
  d'exemplaires, moins l'identité du premier compte.

⚠️ **Ce que cette mesure ne dit pas.** Aucun **McNemar entre les deux bras**
n'a été calculé : le JSON de `bench_refs_curve` est agrégé (pas de
prédiction par crop), et les deux populations held-out ne sont pas
identiques — un test apparié demanderait leur intersection. Les p-values des
tables de sortie sont **internes à chaque bras** (chaque palier contre son
propre N=0). L'écart de +3,7 pts à N=10 et sa monotonie sur sept paliers sont
l'argument ; ce n'est pas un test apparié.

**Décision.** L'amorce médoïde reste le défaut du builder (`--seed-order
medoid`, commit `244c06b3`). Le plancher `min_exemplars` est **remis à
INACTIF** au canonique (`PUT /lab/dino-thresholds`, value `null` → défaut
code 1) : la mesure du 2026-08-20 dit qu'il coûte ~1 pt et qu'un exemplaire
unique aide sa classe — et sous l'amorce médoïde cet exemplaire unique est
désormais le **médoïde** de la classe, donc l'argument est renforcé.

### La banque de production qui en sort — build `a55e6594da32`

```
note du build : min_exemplars=1 (source=code); amorce=medoide;
                0 classes ramenées au canonique seul
```

| | banque du 20/08 (`365dcab2a253`) | **banque de production (`a55e6594da32`)** |
|---|---:|---:|
| ancres | 1495 | **1909** (671 canoniques + 1238 exemplaires) |
| classes à exemplaires | 124 | **250** |
| classes à la cible (`need = 0`) | 64 | **90** |
| held-out N=10 `vitl14` | 84,8 % | **88,5 %** |
| Σ besoin (671 classes) | 4 663 | **4 066** |

Distribution des exemplaires : 421 classes à 0 · 66 à 1 · 35 à 2 · 25 à 3 ·
15 à 4 · 9 à 5 · 12 à 6 · 5 à 7 · 3 à 8 · 9 à 9 · **71 à 10**.
Goulots : `pleine` 90 · `review` 307 · `scrape` 274.

⚠️ Les +3,7 pts du tableau A/B et les +3,7 pts entre 84,8 % et 88,5 % sont
**deux choses différentes qu'il ne faut pas additionner** : le premier est
l'amorce seule (données identiques), le second cumule l'amorce, les 429 crops
de la review et le retour des 67 exemplaires uniques. Coïncidence de valeur,
pas somme.

### Combien de classes sont prêtes, par voie

```bash
cd ml && ./.venv/bin/python -c "
import sqlite3, sys; sys.path.insert(0,'.')
from shared.class_need import all_needs
c = sqlite3.connect('file:state/eurio.replica.db?mode=ro', uri=True); c.row_factory = sqlite3.Row
n = all_needs(c, anchors_kind='2eur_all', encoder_version='dinov2-vitl14')
print(sum(1 for x in n if x.have >= 8), sum(1 for x in n if x.n_train_eligible >= 10))"
```

| | classes |
|---|---:|
| **voie B** — banque, ≥ 8 exemplaires | **83** |
| **voie A** — cohorte, ≥ 10 crops eBay validés (`MIN_REAL`) | **71** |
| voie A à ≥ 8 · à ≥ 4 | 86 · 132 |

C'est le chiffre à regarder pour composer une cohorte d'entraînement : **71
classes** passent le plancher `MIN_REAL = 10` aujourd'hui.

### Backfill P3 — fait et vérifié

`go-task ml:dino-predictions:backfill -- --kind 2eur_all --force --push`,
**29 min 53** pour 13 390 crops (133,9 ms/asset, `vitl14` sur MPS),
`18:14:50 → 18:44:35 UTC`, 0 erreur, 13 391 lignes poussées au canonique.

La preuve retenue n'est **pas** le code de sortie (défaut M8 : le backfill
sort en 0 même en erreur) :

```bash
cd ml && ./.venv/bin/python -c "
import sqlite3; from store.encoder_bench import calibration_blockers
c = sqlite3.connect('file:state/eurio.replica.db?mode=ro', uri=True)
print(calibration_blockers(c, anchors_kind='2eur_all', encoder_version='dinov2-vitl14'))"
# []
```

Et le contrôle de fraîcheur en `datetime()` — **jamais en chaînes**, c'est le
piège du garde P1/P3 (`'2026-08-22 18:14:50'` contre
`'2026-08-22T18:06:22+00:00'` : l'espace vaut `0x20`, le `T` vaut `0x54`) :

```sql
SELECT SUM(datetime(computed_at) < datetime('2026-08-22T18:06:22+00:00'))
  FROM image_asset_dino_predictions
 WHERE anchors_kind='2eur_all' AND encoder_version='dinov2-vitl14';   -- 0
```

Banque servie (`.npz`) et références au canonique concordent : 1909 des deux
côtés, `built_at 2026-08-22T18:06:22+00:00`.

**Effet du re-tri sur le besoin** : `review` 307 → **293**, `scrape` 274 →
**288** (les prédictions ont changé, donc `pending` s'est redistribué) ;
Σ besoin inchangé à **4 066** — la banque ne bouge qu'au rebuild suivant.

---

## 2026-08-21 (soir) — La file par run servait des classes pleines : D2 oubliée

**Constat PO** en reviewant `/review/manual?run=10408fc2…,fc6f11c6…` :
`at-2euro-standard-t1` (10/10 fps, 151 validés) et `ad-2euro-standard-t1`
(10/10, 22 validés) revenaient sans cesse.

**Cause** : le reprocess a été cadré par la **cible du scrape** (annonces
visant une classe déficitaire) et l'URL par le **run** ; ni l'un ni l'autre
ne regarde **ce que DINO reconnaît**. Sur les 770 items ouverts avec
prédiction : top-1 = cible **366**, top-1 ≠ cible **404** ; **267** top-1
tombent dans une classe déjà pleine (≥ 8 fps), 503 dans une déficitaire.

```sql
WITH run_items AS (SELECT rq.id, s.target_eurio_id tgt, p.top1_eurio_id top1
  FROM review_queue rq JOIN image_assets a ON a.id=rq.image_asset_id
  JOIN source_images s ON s.id=a.source_image_id
  LEFT JOIN image_asset_dino_predictions p ON p.asset_id=a.id AND p.anchors_kind='2eur_all'
  WHERE rq.status='open' AND a.run_id IN ('10408fc2d40945e491d656cb0b75d2b5','fc6f11c6d754485997b1dc56a3feac2e')),
have AS (SELECT class_id, SUM(method='fps') n FROM dino_class_references WHERE anchors_kind='2eur_all' GROUP BY 1)
SELECT COUNT(*) FROM run_items r JOIN have h ON h.class_id=r.top1 WHERE h.n>=8;   -- 267
```

Le chiffre était déjà dans l'entrée précédente (« top-1 vers une classe
pleine : 269 ») ; il n'avait pas été traduit en filtre. **Leçon** : un
périmètre de review doit appliquer D2 (filtre par la prédiction) quel que
soit son mode d'entrée — run, cohorte, cible. Le run n'est qu'un sous-ensemble.

**Correctif** : `?need=1` sur la file (`need_only` côté API), calculé par
`shared.class_need` (top-1 dans une classe à `have < target`) ; les autres
sont **parqués** (D3) et comptés dans le bandeau.

---

## 2026-08-21 — O7 : les 808 annonces déficitaires rejouées

Run `10408fc2d40945e491d656cb0b75d2b5` (`go-task ml:src:ebay:reprocess-zero -- --push`),
13:07:44 → 13:58:53 (**51 min**, Mac MPS), témoin `recover=ON tau=0.55
scope=deficit listings=771 images=1215` (les 40 du palier étaient déjà sortis
du périmètre : elles ont des assets). Push 9 589 lignes, vérifié après
`ml:db:pull-replica`. Bilan cumulé des deux runs (`fc6f11c6…` + `10408fc2…`) :

| plaque (grain annonce) | | requête |
|---|---:|---|
| annonces rejouées | **811** | `n_listings` des deux bilans |
| images rejouées | 1 276 | |
| images avec ≥ 1 crop | 935 (73 %) | |
| **annonces récupérées** (≥ 1 crop) | **669 (82 %)** | `annonces sans crop 2 950 → 2 281` (requête de l'entrée précédente) |
| crops ajoutés | 936, dont **923 `score_recover`** | `SELECT COUNT(*), SUM(detection_method='score_recover') FROM image_assets WHERE run_id IN (…)` |
| portes | 138 `reverse`, 5 `not_2eur` → 134 `done` (rejet terminal) | `review_queue` joint sur `image_assets.run_id` |
| **en file ouverte** | **777** (669 single, 108 lot) | idem, `status='open'` |
| dont marge ≥ 0,10 / ≥ 0,05 | 443 / 564 | `COALESCE(country_spread, spread)` sur `2eur_all` |
| top-1 vers une classe déficitaire / pleine | 508 / 269 | jointure `dino_class_references` grain banque |

Dénominateur : 6 596 + 7 924 + 1 290 + 431 = 16 241. `calibration_blockers('2eur_all','dinov2-vitl14')` → `[]`
(prédictions écrites par `auto_validate`, aucun backfill requis).

**Effet sur le besoin** (`shared.class_need.all_needs`, avant → après) :
scrape 276 → **260**, review 328 → **344**, pleine 67, Σ need 4 426 inchangé —
la banque ne bouge qu'à la review puis au rebuild.

**Ce que recover rate encore** : 341 images toujours `zero_crops` parmi les
rejouées, dont **106 sans aucun cercle** (recover n'a pas d'indice) et 151
carrées ; `reject_reason` restants : `radius_too_small` 1 226,
`gated_fragment` 754. C'est la population du **repli plein cadre** (O7 §étape 5)
— à bencher sur D1/D3 de crop-recovery avant d'ouvrir le jalon.

**Non rejoué** (D3) : 1 467 annonces de classes pleines + 63 à 8–9 + 612 sans
cible. Elles attendent le mécanisme « parqué ».

---

## 2026-08-21 — O7 livré, palier 40 au canonique

**Code** : `ml/scripts/reprocess_zero_crops.py` + tâche `ml:src:ebay:reprocess-zero`
(commit `1572bcbb`), 11 tests, suite à 1942 verts.

**Dry-run** (`-- --dry-run`) : 808 annonces / 1 273 images / 143 classes ;
`--scope all` : 2 950 / 4 927 (deficit 808, 8-9 63, pleines 1 467, cible
NULL 612 — les « 92 non représentantes » d'O7 sont résolues par
`bank_classes` et rejoignent pleines/8-9 ; les 612 sans cible n'étaient pas
comptées dans la ventilation d'O7).

**Palier 40** (`-- --limit 40 --seed 42 --push`), run `fc6f11c6d754485997b1dc56a3feac2e`,
13:04:44 → 13:06:53 (**2 min 09**), témoin `recover=ON tau=0.55 scope=deficit
listings=40 images=61` :

| | |
|---|---:|
| images rejouées | 61 |
| images avec ≥ 1 crop | **48 (79 %)** |
| crops ajoutés | 48, dont **47 `score_recover`** |
| restées `zero_crops` | 13 |
| portes | 4 `reverse`, 1 `not_2eur` → 5 rejetés |
| enfilés | 42 (37 single, 5 lot) |
| push `/ingest/run` | 508 lignes |

Vérifié après `go-task ml:db:pull-replica` :
`SELECT COUNT(*), SUM(detection_method='score_recover') FROM image_assets
WHERE run_id='fc6f11c6…'` → 48 | 47 ; prédictions `2eur_all` présentes sur les
48 (écrites par `auto_validate`, pas besoin de backfill) ; dénominateur
7 483 + 7 037 + 1 290 + 431 = 16 241.

Critère du palier (≥ 50 % d'annonces avec crop) passé → reste des 808 lancé
dans la foulée (entrée suivante).

---

## 2026-08-21 — Revue de la vision, ouverture des `zero_crops`, décisions D1–D6

**Contexte.** Revue des docs écrits la veille (`VISION.md`, `FLOW-ADMIN.md`,
`outils/O1..O7`) contre la réplique (pull du 20/08 21:07, WAL du 21/08
12:56) et le code. Aucun appel eBay.

**Corrigé dans les docs et la skill.**
- `eurio-banque` §2 et §4 : `dino_class_references.class_id` est l'`eurio_id`
  du représentant, pas `COALESCE(design_group_id, eurio_id)` —
  `SELECT COUNT(*) FROM (SELECT DISTINCT class_id FROM dino_class_references
  WHERE anchors_kind='2eur_all') WHERE class_id IN (SELECT design_group_id
  FROM coins WHERE design_group_id IS NOT NULL)` → **0**.
- `VISION.md` §M1 : les recherches vides existent dans
  `discovery_searches.status='empty'` (9, toutes Andorre) ; l'allocateur lit
  `coin_source_status`, qui n'en a aucune.
- Migrations : la réplique est à `0011` (`SELECT * FROM _schema_migrations
  ORDER BY 1 DESC LIMIT 1`) — PREREQUIS et la skill disaient « 0008 ».
  `dino_thresholds` est vide (tout `source='code'`).

**Les `zero_crops`, au grain annonce** (l'unité de coût eBay est l'`item/{id}`) :

```sql
WITH l AS (SELECT substr(source_ref,1,instr(source_ref,'_img')-1) listing,
                  SUM(crop_status='success') s
             FROM source_images WHERE source='ebay' GROUP BY 1)
SELECT COUNT(*), SUM(s>0), SUM(s=0) FROM l;   -- 7662 | 3937 | 2950
```

Par état de la classe visée (`target_eurio_id` joint à `dino_class_references`
grain banque) : **808 annonces → 143 classes déficitaires**, 1 399 → 55
classes pleines, 39 → classes à 8–9, 92 → cible non représentante.

**Échantillon** : 60 images `_img0` (`ORDER BY random() LIMIT 400`, puis
`random.seed(42)`, filtre « présente en cache », `[:60]`) → **42 pièces
seules propres plein cadre (70 %)**, 6 boîtiers, 3 rouleaux, 2 × 2 cents,
2 revers, 5 doubles.

**Cause racine** (rejoué en local, `normalize_listing_with_detections`) :
YOLO ne rend aucune bbox ≥ 60 % du petit côté sur les 60 ; seuls des cercles
intérieurs (`r/short` 0,02–0,09) → `radius_too_small` / `gated_fragment`.
`detections_json` du run `473c2225…` (433 images) : `radius_too_small` 1 584,
`gated_fragment` 1 149, 43 images sans aucun cercle.

**Remède** : `EURIO_CENSUS_RECOVER=1` rattrape **32/42** ; un Hough plein
cadre (ROI = image, `r ≥ 0,30·short`, centré) **40/42**. Le run du
2026-08-16 porte 0 crop `score_recover` sur 601 acceptés : la passe n'a
jamais tourné en prod.

**Courbe émissions communes** (`bench_refs_curve --bank-classes/--gold-classes`
sur les 87 `eurio_id` des `design_group_id` multi-pays, `vitl14`, 102 crops /
15 classes held-out) : pays@1 **90,2 % (N=0) → 97,1 % (N=5)**, plat ensuite ;
global@1 17,6 → 29,4 %. → D4, cible 5 pour cette famille.

**Décisions** : D1–D6 dans [`DECISIONS.md`](DECISIONS.md). Ordre :
O7 → O6 → O1/O5 → design O2/O4 → O3 → scrape.

**Plan du sprint 1** : `~/.claude/plans/ok-mon-ami-c-est-binary-jellyfish.md`
(Lot 0 journal · Lot 1 `scripts/reprocess_zero_crops.py` + tâche + tests ·
Lot 2 run réel par paliers, 808 annonces déficitaires · Lot 3 mesures).
