# Journal — pipeline propre

> Une entrée par geste : ce qu'on a fait, la commande, le témoin qui prouve
> que ça a tourné, la mesure **avec sa requête**, et la décision ou le lien
> vers [`DECISIONS.md`](DECISIONS.md). Le plus récent en haut. Les chiffres
> sont ceux d'une minute sur `ml/state/eurio.replica.db` : relance la
> requête, ne recopie pas le nombre.

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
