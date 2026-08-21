# La chaîne propre — de la requête eBay à la banque DINO

> **Document de vision, pas de plan d'exécution.** Il pose ce que la chaîne fait
> aujourd'hui, où elle fuit, et à quoi ressemblerait une version dont on n'aurait
> pas honte. Rien ici n'est implémenté par ce document.
>
> Écrit le **2026-08-20**. Base lue : `ml/state/eurio.replica.db` (réplique du
> canonique, lecture seule), pull du 03:22 UTC, `-wal` à 19:19 UTC.
> **Chaque chiffre porte sa requête** — recopie la requête, jamais le nombre :
> la review avance pendant qu'on lit, et le même fait compté sur deux mailles
> donne deux nombres également honnêtes.
>
> Documents dont celui-ci est la suite, à lire avant :
> [`../scan-sans-retrain/ALLOCATEUR-SCRAPE.md`](../scan-sans-retrain/ALLOCATEUR-SCRAPE.md)
> (le maillon 1 est déjà conçu là-bas),
> [`../scan-sans-retrain/COURBE-REFERENCES.md`](../scan-sans-retrain/COURBE-REFERENCES.md)
> (d'où vient « 8 »), [`../peche-dino/DECISIONS.md`](../peche-dino/DECISIONS.md)
> (les 9 décisions du filtrage), et les skills `eurio-banque`, `eurio-review`,
> `eurio-enrichment`.

---

## 1. Ce qu'on cherche

Une phrase : **671 classes, 8 crops propres chacune, obtenus avec le moins de
quota eBay et le moins de temps humain possible.**

Le reste du document découle de là. « Propre » veut dire quatre choses
simultanées, et c'est le cumul qui est difficile :

1. le crop montre **la bonne pièce** (bonne classe, pas une voisine) ;
2. il montre son **avers** (le revers commun 2 € n'apprend rien) ;
3. il est **exploitable** (cadré, net, pas trop incliné) ;
4. il est **diversifiant** par rapport aux sept autres — sinon le huitième ne
   vaut rien.

⚠️ **« 8 » est un arbitrage coût/bénéfice, pas un plateau.** La courbe
références/classe ne montre aucun plateau : 8→9 est du bruit (`z=0,50`) mais
9→10 est significatif (+1,36 pt, `z=2,54`). Le rendement passe de ~2,5 pt/réf
avant 8 à ~0,8 après. Au-delà de **10**, un crop validé n'entre plus du tout
dans la banque (`DEFAULT_EXEMPLARS_PER_CLASS = 10`, `anchors.py:445`) : il sert
l'entraînement ArcFace, pas les suggestions. Donc **8 est la cible, 10 le
plafond dur, et tout ce qui dépasse 10 est du temps humain perdu pour la
banque.** Source : `COURBE-REFERENCES.md` §3.5 et §4.3.

### Où on en est de cet objectif

```sql
-- exemplaires par classe, grain BANQUE
SELECT class_id, SUM(method='fps') n FROM dino_class_references
 WHERE anchors_kind='2eur_all' GROUP BY 1;
```

| exemplaires | 0 | 2 | 3 | 4 | 5 | 6 | 7 | ≥ 8 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| classes | **547** | 28 | 9 | 12 | 5 | 5 | 1 | **64** |

- **671 classes, 607 déficitaires, déficit total 4663 exemplaires.**
- **66 classes** seulement peuvent être comblées **aujourd'hui** avec ce qui
  attend en file ouverte (36 si on exige une marge ≥ 0,05).
- **347 classes déficitaires n'ont AUCUN crop en file ouverte** : pour elles le
  goulot n'est pas la review, c'est qu'on n'a jamais interrogé eBay.

*(La colonne « 1 » est vide parce que la banque servie a été bâtie avec le
plancher `min_exemplars=2`, **retiré du code depuis**. Au prochain rebuild elle
se remplira. Cf. `eurio-banque` §3.)*

---

## 2. L'entonnoir, mesuré

```sql
SELECT COUNT(*) FROM source_images WHERE source='ebay';            -- 16241
SELECT COUNT(*) FROM image_assets;                                 -- 12454
SELECT COUNT(*) FROM review_queue;                                 -- 11912
SELECT COUNT(*) FROM image_assets WHERE training_eligible=1;       -- 2157
SELECT COUNT(*) FROM dino_class_references
 WHERE anchors_kind='2eur_all' AND method='fps';                   --   824
```

| étape | volume | ce qui se perd ici |
|---|---:|---|
| images sources eBay | 16 241 | |
| — téléchargement échoué | 1 290 | |
| — 🔴 **téléchargées, zéro crop détecté** | **7 531** | **46 % du total** — cf. ci-dessous |
| — images ayant produit un crop | 6 989 | |
| crops détectés | 12 449 | 1,78 crop par image cropée |
| rejetés automatiquement | 3 074 | dont `denom='not_2eur'` 1 381, `face='reverse'` 1 138 |
| items de review créés | 11 912 | |
| — tranchés | 5 241 | |
| — **encore ouverts** | **6 617** | ← le stock |
| `training_eligible = 1` | 2 157 | ~41 % des items tranchés |
| **exemplaires retenus en banque** | **824** | le plafond de 10/classe en jette |

```sql
SELECT COUNT(*) FROM source_images WHERE source='ebay' AND download_status='failed'; -- 1290
SELECT COUNT(*) FROM source_images WHERE source='ebay' AND crop_status='zero_crops'; -- 7531
SELECT COUNT(*) FROM source_images WHERE source='ebay' AND crop_status='success';    -- 6989
```

### 🔴 Correction du 2026-08-21 — la plus grosse fuite n'était pas dans ce tableau

La première version de ce document résumait la perte entre « images sources » et
« crops détectés » par *« annonces sans pièce détectable »*. C'était vrai et
sans intérêt. La mesure exacte l'est beaucoup plus : **7 531 images ont été
téléchargées avec succès puis jetées** parce que la détection n'a rien rendu
(`crop_status='zero_crops'`, `crop_error='normalize_listing returned 0 crops'`
sur 7 403 d'entre elles).

C'est **la plus grosse perte de toute la chaîne** — plus grosse que les portes
automatiques et le rejet humain réunis — et elle arrive **après** qu'on a payé
l'appel eBay.

### ✅ Revue du 2026-08-21 (après-midi) — on les a ouvertes, et on sait ce que c'est

Le paragraphe précédent disait *« personne n'a jamais ouvert ces images »* et
*« ce n'est pas le chantier crop-recovery »*. **Les deux sont faux**, et la
correction agrandit le gisement au lieu de le réduire :

- **L'unité de coût est l'annonce, pas l'image** (un `item/{id}` par annonce,
  les images sont des téléchargements gratuits). À ce grain : **7 662 annonces,
  2 950 (38 %) n'ont produit aucun crop**, dont 2 338 avec une cible — **808
  visent 143 classes déficitaires**, 1 399 des classes pleines.
- **60 images `_img0` tirées au hasard (seed 42) : 42 (70 %) sont UNE pièce de
  2 €, propre, plein cadre.** Le reste : 6 boîtiers/coincards, 3 rouleaux,
  2 pièces de 2 cents, 2 revers, 5 photos à deux pièces.
- **Cause racine mesurée** : le détecteur est YOLO-first et **YOLO ne voit pas
  une pièce qui remplit le cadre** (0 bbox ≥ 60 % du petit côté sur les 60) ; il
  ne trouve que des cercles intérieurs (`r/short` 0,02–0,09 →
  `radius_too_small` / `gated_fragment`). C'est **exactement** le diagnostic
  du chantier [`crop-recovery`](../crop-recovery/VISION.md) (« la détection se
  rabat sur le motif central », jeu D2 = 341 `zero_crops`).
- **Le remède existe et ne tourne pas** : `vision/score_recover.py`
  (stratégie A, 86 % au banc) est **OFF par défaut** (`EURIO_CENSUS_RECOVER`),
  et le run du 2026-08-16 porte **0 crop `score_recover`** sur 601 acceptés.
  Rejoué sur les 42 pièces seules : recover ON en rattrape **32 (76 %)** ; un
  Hough plein cadre (ROI = image, `r ≥ 0,30·short`, centré) en trouve **40**.
- **Rien n'a jamais été reprocessé** : `detect_crop.run(retry_zero_crops=True)`
  existe et n'est exposé ni en CLI, ni dans l'orchestrateur, ni dans `tasks.yml`.
  Les 7 531 raws sont tous `storage_status='present'` en MinIO.

Ordre de grandeur : **~2 000 crops propres sans un appel eBay**, pour 2 157
`training_eligible` depuis le début du projet. ✅ **Fait le soir même** sur les
811 annonces déficitaires : 669 récupérées (82 %), 936 crops, 777 en file
ouverte — cf. [`JOURNAL.md`](JOURNAL.md). → [`outils/O7`](outils/O7-reprocess-zero-crops.md),
qui passe d'« instrumenter » à « reprocesser ».

**Rendement mesuré d'un run de scrape** (2026-08-16, `ALLOCATEUR-SCRAPE.md`) :
740 appels → 801 raws → 661 crops → 62 validés → **50 ancres**. Soit **~15
appels eBay par exemplaire gagné**, et **~13 crops examinés par exemplaire
gagné**.

À ce rendement, les 4663 exemplaires manquants coûtent ~70 000 appels
(~14 jours de quota) et ~60 000 crops à examiner. **C'est ce chiffre-là qu'il
faut faire tomber, et il ne tombera pas en accélérant la review.**

---

## 3. Les quatre vérités qui contraignent tout le design

Elles ne sont pas des opinions : chacune est mesurée, et chacune invalide une
idée qui paraît évidente.

### V1 · La file ouverte est à 55 % du travail perdu d'avance

Répartition des 6617 crops ouverts selon le **besoin de la classe** que leur
top-1 désigne :

| | crops | |
|---|---:|---|
| utiles à la cible 8 | **839** | 13 % |
| classes **déjà pleines** (10 exemplaires, besoin 0) | **3 612** | 55 % |
| top-1 hors du grain de la banque | 2 166 | 33 % |

Les **12 classes les plus représentées totalisent 1615 crops (24 % de la
file)** — et **toutes ont déjà 10 exemplaires**. En tête :
`ad-2014-…council-of-europe` 305 crops, `fr-2010-…degaulle` 197,
`fr-2008-…french-presidency` 187.

> **Conséquence de design.** Une file de review qui n'est pas cadrée par le
> **besoin** dépense la moitié de son temps pour rien. Ce n'est pas un défaut de
> l'écran : c'est ce qu'on lui donne à servir.

### V2 · Il existe 87 classes où l'image ne PEUT PAS trancher

Cinq émissions communes — un dessin identique frappé par 13 à 19 pays :

```sql
SELECT design_group_id, COUNT(DISTINCT country) FROM coins
 WHERE design_group_id IS NOT NULL GROUP BY 1 HAVING COUNT(DISTINCT country)>1;
-- eu-erasmus-2022 19 · eu-eu-flag-2015 19 · eu-euro-cash-2012 18
-- eu-emu-2009 16 · eu-rome-2007 13        → 87 pièces
```

La banque en fait **87 classes distinctes** (le builder indexe une commémorative
sous son propre `eurio_id`, jamais sous son `design_group_id` — cf. V4).
Précision du top-1 sur les 219 crops labellisés de ces pièces :

| ce qu'on demande | précision |
|---|---:|
| le bon **dessin** (pays indifférent) | **97,7 %** |
| le bon **pays** | **64,4 %** |

Le seul écart visible entre un Erasmus autrichien et un Erasmus chypriote est
une inscription de quelques millimètres, illisible à 224 px. **Un tiers des
verdicts est un tirage au sort, et aucune quantité de crops supplémentaires ne
le corrigera.**

Ces classes coûtent **1029 des 6617 crops ouverts (16 %)**.

> **Conséquence de design.** La chaîne doit savoir, **par classe**, quel signal
> est décisif. Pour une commémorative nationale c'est l'image ; pour une
> émission commune c'est le texte ou le pays de la recherche, et l'image ne sert
> qu'à confirmer le dessin. Servir les deux avec la même règle, c'est garantir
> 35 % d'erreur sur une famille entière.

### V3 · `listing_country` n'est pas le pays de l'annonce

`sources/ebay/adapter.py:601` : `listing_country=group.country`, où `group` est
le **groupe de découverte** de la requête. C'est le pays que la recherche
**visait**, pas l'emplacement du vendeur ni celui de l'objet — lequel n'est
capturé nulle part (`raw_payload_json` ne porte que l'image, le vendeur et sa
note).

Preuve croisée : `AD` porte 2726 annonces, dont 1673 sur `EBAY_DE`. Andorre
n'est pas une place de marché eBay.

```sql
SELECT listing_country, marketplace, COUNT(*) FROM source_images
 GROUP BY 1,2 ORDER BY 3 DESC LIMIT 5;
-- AD|EBAY_DE|1673   FR|EBAY_ES|1433   AT|EBAY_ES|1260   BE|EBAY_DE|1214
```

Le filtre pays de la pêche (D9) est donc, littéralement : *« ne garder que les
crops découverts par une recherche visant ce pays »*. C'est un filtre
**efficace** — mais c'est une propriété de **notre plan de scrape**, pas de
l'objet. Et il se retourne :

| | |
|---|---:|
| classes avec un pool de pêche non vide (rang 1) | 338 |
| **dont le filtre pays ramène à ZÉRO** | **137 (41 %)** |
| crops ouverts devenus inatteignables par défaut | 412 |

Par pays : PT 13/13, LU 12/12, VA 11/11, LT 10/10, MC 9/9, MT 9/9, LV 8/8,
SK 8/8, SM 12/13. Ce sont **exactement** les pays les plus pauvres en ancres
(`banque-dino/CONSTAT.md` : LU 33/41 sans ancre, MT 27/34, LT 18/21).

Et voici pourquoi la mesure qui a fondé D9 ne pouvait pas le voir :

```
population qui a fondé D9 : 2169 crops labellisés
  dont 15 (0,7 %) appartiennent aux 15 pays que le filtre vide entièrement
  sur ces 15 crops, 0 auraient survécu au filtre   (0,0 %)
```

> **Conséquence de design, et c'est la leçon de méthode du chantier.** C'est
> **la même faute que le plancher `min_exemplars`** de la veille : un agrégat
> extrapolé en règle par classe. « On perd 5 % de vrais positifs » est vrai en
> moyenne et vaut **100 %** pour un cinquième du catalogue. Tout filtre par
> défaut doit désormais être mesuré **par strate**, et pas seulement en agrégat.

### V4 · Trois conventions portent le nom `class_id`

C'est le défaut **Q13** de `eurio-banque` §4, resté « non diagnostiqué ». Il est
diagnostiqué ici.

| endroit | règle |
|---|---|
| `coins` | `COALESCE(design_group_id, eurio_id)` — un Erasmus est `eu-erasmus-2022` |
| `dino_class_references.class_id` | **`eurio_id` du représentant** : la commémo elle-même ; pour une courante, le premier membre du groupe (`_class_specs_2eur_all`, `anchors.py:757`) |
| `encoder_bench_gold.class_id` | le `eurio_id` représentant du groupe (`ORDER BY year, eurio_id`) |

Vérifié :

```sql
SELECT class_id, eurio_id, method, COUNT(*) FROM dino_class_references
 WHERE anchors_kind='2eur_all' AND eurio_id LIKE 'it-200%standard%' GROUP BY 1,2,3;
-- it-2002-2eur-standard-1st-map | it-2002-… | canonical | 1
-- it-2002-2eur-standard-1st-map | it-2002-… | fps       | 6
-- it-2002-2eur-standard-1st-map | it-2008-… | fps       | 2
--   ↑ class_id, PAS 'it-2euro-standard-t1'
```

Une requête écrite avec la convention `coins` rend **2166 crops « hors banque »**
qui sont pourtant en banque. Elle ne lève rien.

> **Conséquence de design.** Une seule fonction doit traduire, et `shared/`
> en porte déjà l'amorce (`bank_classes.bank_class_ids_for_class`). Toute
> requête qui joint la banque à `coins` sans passer par elle est fausse — y
> compris celles écrites dans les docs et dans cette skill.

---

## 4. Les sept maillons — l'existant et la cible

### M1 · Décider quoi chercher

**Existant.** `ml/scripts/allocate_ebay_scrape.py` + `go-task ml:ebay:allocate`,
conçu dans [`ALLOCATEUR-SCRAPE.md`](../scan-sans-retrain/ALLOCATEUR-SCRAPE.md).
Alloue le quota par déficit : `need(c) = max(0, 8 − have(c) − pending(c))`,
score par groupe de découverte = `Σ poids / coût`, remplissage glouton,
dry-run par défaut, ne repasse pas sur un groupe frais (30 j).

**Ce qui manque.** Rien de structurel — c'est le maillon le plus abouti. Deux
réserves à porter : le préflight quota de `sources/cli.py` est **faux d'un
facteur ~130** (défaut S3, non corrigé, vit dans `serving/sources_routes.py`),
et le vide est enregistré **au mauvais endroit pour l'allocateur** :
`discovery_searches.status='empty'` porte **9** recherches vides (toutes
Andorre 2019/2024/2025), mais `allocate_ebay_scrape._empty_upstream_members`
lit `coin_source_status`, qui n'a **aucune** ligne eBay en `empty_upstream`.
*(Corrigé le 2026-08-21 : une première version disait « aucune recherche vide
n'a jamais été enregistrée » — c'est la table qu'on regardait.)*

**Cible.** Que l'allocateur **lise** `discovery_searches` (ou que la recherche
vide pose aussi `coin_source_status`), pour que le tour suivant n'y retourne pas.

### M2 · Formuler la requête

**Existant.** `sources/ebay/queries.py` construit une requête par langue de
marketplace (`EBAY_DE` + `EBAY_ES`), à la maille **groupe de découverte** :
commémorative `(2 €, pays, année)`, courante `(2 €, pays, toutes ères)`. Le
standard ratisse `limit=200` au lieu de 75.

**Ce qui manque.** La requête ne dit jamais « avers » ni « pas de lot », et
elle ne peut pas : eBay n'indexe pas ça. Le tri se fait donc **après**, sur
16 241 images pour 2157 crops utiles.

**Cible.** Utiliser les marqueurs de rejet déjà extraits
(`rejected_markers_json`, `is_lot`, `listing_kind`) pour **ne pas télécharger**
ce qu'on sait devoir jeter — le tri le moins cher est celui qu'on fait sur le
titre, avant l'appel `item/{id}`. Aucune mesure n'existe encore sur ce que ça
économiserait : **à mesurer avant de coder.**

### M3 · Récupérer et cropper

**Existant.** `sources/_base/steps/detect_crop.py` → `vision.normalize_snap`
(multi-Hough), crops 224×224, pHash 64 bits par crop, dédup couche 4 par pHash
(`auto_phash` : 310 crops ont hérité leur label d'un jumeau).
`0 crop` n'est pas une erreur — c'est logué et le raw reste reprocessable.

**Ce qui manque.** La **qualité** du crop n'est mesurée que sur ~46 % d'entre
eux (`quality_score`, rétro-rempli depuis `state/crop_diag/results.csv`) ;
ailleurs elle est NULL et l'expert `crop_quality` s'abstient.

**Cible.** Une qualité mesurée sur 100 % des crops, parce que c'est la
condition 3 de « propre » — et qu'un crop incliné entré en banque pollue les
sept autres.

### M4 · Les portes automatiques

**Existant, et elles marchent.**

| porte | ce qu'elle enlève | mesure |
|---|---:|---|
| `denom` (probe 2 € vs junk) | 1 381 crops | seuil 0,4 garde **95,3 %** des 2 € et **2,3 %** des non-2 € |
| `face` (revers commun) | 1 138 crops | `FACE_REVERSE_TAU = 0,065` sur `reverse_sim − top1_sim` |

⚠️ La mesure du seuil `denom` est **partiellement circulaire** : `denom='not_2eur'`
a été posé par la probe elle-même. Le chiffre non circulaire est l'autre : sur
513 crops labellisés par un humain, un seuil à 0,4 en garde 95,3 %.

**Ce qui manque.** `denom_2eur_score` n'est **pas lu par la pêche** : 7910
crops sur 12454 le portent, et le périmètre de review l'ignore. Mesuré sur le
pool belge filtré pays : 32 crops → **25** avec un seuil à 0,4, en retirant
surtout les piécettes des coffrets « 1 cent à 2 euros ».

### M5 · Les signaux et le consensus

**Existant, et c'est le maillon le plus prometteur — il est déjà écrit.**
`review/validation/experts.py` normalise trois experts (`text`, `dino`,
`crop_quality`) en `Signal(expert, score, label, reason, raw)` ;
`review/validation/consensus.py` les agrège en table de décision lisible
`{accept, needs_review, reject}` + lane + confiance + règle nommée.

**Deux limites, toutes deux mesurées.**

1. **Il est en SHADOW.** `consensus_verdict` est calculée et diffée contre le
   verdict courant sur le gold ; elle n'est **pas câblée au pipeline live**.
2. **Il est aveugle sur les pièces courantes.** `collect_signals` appelle
   `fetch_and_resolve_signals`, dont le défaut est
   `anchors_kind = VERDICT_ANCHORS_KIND = '2eur_commemo'` — une banque qui ne
   contient **aucune** étiquette de pièce courante (0 sur 508). Tout crop de
   standard tombe donc en `unknown` par la règle 1, sans qu'une seule erreur
   soit levée. Cf. `eurio-review` §« la review est AVEUGLE sur les standards ».

**Le gisement de signaux non lus.** `listing_text_signals` couvre **100 %** des
crops ouverts (6617/6617), avec l'année sur 5808 et le pays sur 5276. Il porte
`countries` / `years` / `denominations` / `theme_tokens` / `rejected_markers` /
`is_lot` / `listing_kind` / `condition` / `vs_target_verdict`. **La pêche n'en
lit rien.**

Un signal y a été mesuré et il est gratuit — **la contradiction d'ère**. On
compare l'intervalle `[min, max]` des années du titre à l'ère de la classe, et
on écarte quand ils ne se recoupent pas.

⚠️ **La sémantique d'intervalle n'est pas un détail** : traiter `[1999, 2012]`
comme une énumération produit de fausses contradictions sur les commémoratives
(rappel 85,4 % → 74,2 % sur les lots). En intervalle, le filtre ne coûte **aucun
vrai positif dans les quatre régimes** :

| régime | pays seul | pays + ère non contredite |
|---|---|---|
| lots / courantes (n=68) | 47 servis, 91,5 % | **45, 95,6 %** |
| lots / commémos (n=418) | 369, 96,7 % | 369, 96,7 % *(inchangé)* |
| singles / courantes (n=327) | 299, 99,7 % | 296, **100 %** |
| singles / commémos (n=1356) | 1245, 98,8 % | 1234, **99,1 %** |

Effet sur les vrais pools : **BE 44 → 32, ES 11 → 5, IT 61 → 61**.

**Cible.** Un moteur de signaux **unique**, scopé sur la bonne banque, dont la
pêche et le verdict soient deux lectures — pas deux implémentations. Et une
table qui dit, **par famille de classe**, quel signal est décisif (V2).

### M6 · La review — le maillon qui manque vraiment

**Existant.** Six écrans (`/review`, `manual`, `auto-accept`, `lot`, `recover`,
`peer-arbitration`) plus la pêche (`/review/peche`) livrée le 2026-08-20.
L'opérateur en est satisfait : *« la fit de la page avec unité, lot, top 1 / top
3 / top 5, et 0,05 / 0,10, franchement j'adore. »*

**Ce qui manque, et c'est le cœur de ce document : il n'existe aucune vue qui
parte du BESOIN.** Toutes les files partent d'un périmètre (une cible, une
cohorte, une classe qu'on a tapée à la main). Aucune ne répond à la question
*« quelle classe dois-je nourrir maintenant, et combien lui manque-t-il ? »*.

C'est ce qui produit V1 : 55 % de la file ouverte sert des classes qui n'ont
besoin de rien, et personne ne le voit à l'écran.

**Cible — la vue « classe → 8 ».** Une liste de classes ordonnée par *ce que la
review peut débloquer aujourd'hui*, où chaque ligne porte :

```
be-2euro-philippe-t1     5/8   ██████░░   +32 candidats   marge max 0,053   [pêcher]
lu-2euro-henri-i-t1      0/8   ░░░░░░░░    0 candidat     → scrape (M1)
ad-2014-…-council        10/8  ████████   PLEINE — ne plus servir
```

et trois propriétés non négociables :

- **elle dit quand le goulot n'est pas elle.** 347 classes déficitaires n'ont
  aucun crop en file : les envoyer vers la review est une perte de temps, la
  vue doit les router vers l'allocateur ;
- **elle s'arrête à 10.** Au-delà, un crop validé n'entre plus en banque —
  continuer est mesurablement du travail perdu (médiane de **25 crops décidés**
  sur les classes pleines, pour un plafond de 10) ;
- **elle ne se ment pas sur zéro.** Une classe dont le pool filtré tombe à zéro
  doit dire *pourquoi* — filtre pays trop mordant (V3), ère contredite, ou
  vraiment rien.

### M7 · La banque et sa mesure

**Existant.** `build_anchors_2eur_all` : un canonique Numista par classe +
jusqu'à 10 exemplaires choisis par *farthest-point sampling*, `floor_sim=0,45`.
Rebuild 237 s, puis backfill des prédictions ~28 à 41 min (obligatoire, sinon la
review trie sur les vecteurs de l'ancienne banque). Traçabilité en base depuis
la migration 0007 (`dino_class_references` + `dino_anchor_builds`).

**Le levier mesuré et non implémenté.** Le rang 1 du FPS est le crop le **plus
atypique** de sa classe, donc un faux attracteur. À **nombre d'ancres
strictement identique**, garder le rang le *moins* diversifiant rend **77,8 %**
contre 73,8 % en `vitl14` :

```bash
cd ml && EURIO_DB_PATH=$PWD/state/eurio.replica.db ./.venv/bin/python \
  -m scripts.bench_refs_curve --model dinov2_vitl14 --refs 0 1 2 3 --rank-order last
```

**Amorcer le FPS au médoïde** plutôt qu'au point le plus lointain vaut donc 4 à
6 points, **sans une seule donnée nouvelle**. `--rank-order last` est une sonde,
pas un builder : le geste reste à écrire (½ journée + 237 s + ~41 min).

⚠️ **Décalage à traiter avant tout rebuild** : la banque servie porte encore
`min_exemplars=2`, le code ne l'applique plus. Le prochain rebuild changera la
forme de la banque (68 classes retrouveront leur exemplaire) et **le garde P1 ne
le signalera pas** — il compte les classes à ≥ 2 exemplaires, un compte que ce
retour laisse invariant.

**Ce que l'encodeur ne donnera pas.** DINOv3 est **réfuté** sur notre tâche
(`vit_small_p16.dinov3` 78,7 % contre `dinov2_vits14` 85,9 % à taille égale,
McNemar `p ≤ 3,6e-15`). Il n'y a pas de meilleur backbone gelé disponible :
`dinov2_vitl14` reste l'encodeur de la review.

---

## 5. À quoi ressemble la chaîne propre

```
   ┌─ M1 ALLOUER ────────────────────────────────────────────────┐
   │  besoin(classe) = 8 − ancres − candidats_en_file            │
   │  → groupes de découverte, ordonnés par besoin/coût          │
   │  → enregistre « vide » quand eBay ne rend rien              │
   └──────────────────────────┬──────────────────────────────────┘
                              ↓
   ┌─ M2 CHERCHER ───────────────────────────────────────────────┐
   │  requête par groupe × marketplace                            │
   │  → tri sur le TITRE avant tout téléchargement                │
   └──────────────────────────┬──────────────────────────────────┘
                              ↓
   ┌─ M3 CROPPER ─────────────┴─ M4 PORTES ──────────────────────┐
   │  Hough → 224² → pHash    │  denom · face · qualité (100 %)   │
   └──────────────────────────┬──────────────────────────────────┘
                              ↓
   ┌─ M5 SIGNAUX ────────────────────────────────────────────────┐
   │  texte (pays, ère, lot, marqueurs) + DINO (classe, marge)    │
   │  + qualité de crop  →  UN moteur de consensus, scopé sur la  │
   │  BONNE banque, avec une règle PAR FAMILLE de classe (V2)     │
   └──────────────────────────┬──────────────────────────────────┘
                              ↓
   ┌─ M6 REVIEW cadrée par le BESOIN ────────────────────────────┐
   │  vue « classe → 8 » ; s'arrête à 10 ; route vers M1 quand    │
   │  le goulot est le scrape ; explique tout zéro                │
   └──────────────────────────┬──────────────────────────────────┘
                              ↓
   ┌─ M7 BANQUE ─────────────────────────────────────────────────┐
   │  FPS amorcé au médoïde · rebuild · backfill · courbe         │
   └──────────────────────────┬──────────────────────────────────┘
                              └──→ retour en M1 : le besoin a changé
```

Le point important est la **boucle** : aujourd'hui la chaîne est un tuyau qu'on
pousse par un bout ; propre, elle se referme, et c'est le besoin recalculé qui
commande le tour suivant.

---

## 6. L'ordre des gestes, et ce que chacun coûte

Aucun de ces gestes n'est engagé par ce document.

| # | Geste | Pourquoi maintenant | Coût |
|---|---|---|---|
| **1** | **Amorcer le FPS au médoïde** (M7) | 4 à 6 points sur tout, sans données nouvelles, mesuré. Améliore le filtrage **et** la review **et** le scan. C'est la racine | ½ j + 237 s + ~41 min |
| **2** | **La vue « classe → 8 »** (M6) | Sans elle, 55 % du temps de review est perdu et personne ne le voit. C'est ce qui rend les autres gestes mesurables | 1 à 2 j |
| **3** | **L'ère et le denom dans le périmètre** (M5) | Gratuits, mesurés, zéro vrai positif perdu. BE −27 %, ES −55 % de bruit | ½ j |
| **4** | **Le filtre pays qui se désarme au lieu de vider** (V3) | 137 classes servent zéro par défaut, dont tous les pays pauvres | ½ j |
| **5** | **Le consensus sorti du shadow, scopé sur `2eur_all`** (M5) | Le moteur existe ; il juge sur une banque aveugle aux courantes | 1 j + re-calibrage |
| **6** | **Une règle par famille** pour les 87 émissions communes (V2) | 16 % de la file ouverte, 35 % d'erreur structurelle | à concevoir |
| **7** | **Le scrape** (M1) | 347 classes n'ont aucun crop. Argent réel | ~10 j de quota |

**Ce qui devrait passer en premier si on ne devait en faire qu'un : le 1.**
C'est le seul qui améliore tous les maillons à la fois, et il est déjà mesuré.

> ✅ **Révisé le 2026-08-21** : un geste **0** passe devant — le reprocess des
> annonces `zero_crops` (O7), ~2 000 crops sans quota, code existant. L'ordre
> arbitré avec le PO est dans [`DECISIONS.md`](DECISIONS.md).

---

## 7. Ce que ce document ne prétend pas

- **Il ne dit pas ce que vaudra la banque sur une frame de caméra.** Tout ce
  qui précède est la tâche **review** (photos de vendeurs eBay, cadrées par
  quelqu'un qui veut montrer la pièce). La tâche **scan** n'a **0 capture
  versionnée** — cf. [`../scan-quality/DURABILITE-CORPUS.md`](../scan-quality/DURABILITE-CORPUS.md).
- **Il ne remplace pas la décision humaine.** `training_eligible = 1` n'est
  régénérable par aucun calcul. Tout ce qui précède sert à ce qu'un humain
  regarde moins de vignettes, jamais à ce qu'il en regarde zéro.
- **Il ne rouvre pas le top-1 scopé pays** (D9) sans nouvelle mesure.
- **Il ne tranche pas** entre les gestes du §6 : c'est au PO.

## 8. Questions ouvertes

> ✅ Les questions 1 et 2 sont **tranchées le 2026-08-21** — voir
> [`DECISIONS.md`](DECISIONS.md) (D2, D3, D4). Restent 3 et 4.

1. **La cible est-elle 8 pour toutes les classes ?** Une émission commune ne
   sera jamais mieux que 64 % sur le pays quel que soit le nombre de crops.
   Faut-il leur donner 8 quand même, ou les traiter à part ?
2. **Que faire des 3612 crops de classes pleines ?** Les fermer en masse
   libérerait la file — mais c'est une écriture sur 55 % du stock, et un crop
   « de classe pleine » l'est selon un top-1 qui peut se tromper.
3. **Le tri sur titre avant téléchargement (M2) économise combien ?** Non
   mesuré. À chiffrer avant de coder.
4. **La qualité de crop sur les 54 % restants** : rétro-remplissage ou
   recalcul ?

---

## 9. Suite — le flow admin et les outils

Ce document pose le **quoi**. Le **comment on le pilote** est dans
[`FLOW-ADMIN.md`](FLOW-ADMIN.md) : les huit plaques de l'entonnoir, les quatre
stations de l'admin, et le piège de nommage entre les deux « N par classe » du
projet.

Les outils qui en découlent ont chacun leur spec :

| | outil | station |
|---|---|---|
| [O1](outils/O1-besoin-par-classe.md) | Le besoin par classe, calculé en un seul endroit | 0 |
| [O2](outils/O2-vue-classe-vers-8.md) | La vue « classe → 8 » | 0 |
| [O3](outils/O3-entonnoir-huit-plaques.md) | L'entonnoir étendu, par run et par classe | 3 |
| [O4](outils/O4-filtres-par-signaux.md) | Les filtres par signaux dans la pêche | 2 |
| [O5](outils/O5-familles-de-signal.md) | La table « quel signal décide » | 0 · 2 |
| [O6](outils/O6-amorce-fps-medoide.md) | L'amorce du FPS au médoïde — la racine | — |
| [O7](outils/O7-reprocess-zero-crops.md) | Reprocesser les 2 950 annonces sans crop — **en premier** | 3 |
