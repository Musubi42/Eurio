# La banque DINO — ce qu'on a mesuré le 2026-08-19

> Chaque chiffre porte sa requête. Base lue : `ml/state/eurio.replica.db`
> (réplique du canonique), sauf mention contraire. Suite du chantier
> `docs/work-in-progress/dino-suggestions/` (juin 2026).
>
> ⚠️ **Deux constats de ce doc sont périmés depuis le soir du 2026-08-19** — les
> §« La couverture de la banque » et §« La traçabilité n'existe pas » portent
> désormais leur correction datée, avec l'état antérieur conservé. Mesures :
> [`../scan-sans-retrain/FINDINGS.md`](../scan-sans-retrain/FINDINGS.md).

## Le point de départ

Sur la cohorte `giga-40-vague1`, la classe `be-2euro-philippe-t1` affiche
**116 crops à trancher**. Une fois la file entièrement scorée, le modèle n'en
rattache que **3** à une pièce courante belge :

| Ce que DINO reconnaît | Crops | Sim moyenne |
|---|---:|---:|
| Commémorative d'un **autre pays** | 84 | 0,60 |
| Commémorative **belge** | 21 | 0,76 |
| Courante d'un autre pays | 5 | 0,73 |
| **Courante belge** | **3** | 0,87 |

```sql
WITH pool AS (
  SELECT a.id AS aid FROM review_queue rq
    JOIN image_assets a ON a.id = rq.image_asset_id
    JOIN source_images s ON s.id = a.source_image_id
   WHERE rq.status='open' AND s.source='ebay' AND s.listing_country='BE'
     AND s.listing_year IS NULL AND rq.kind='single'
     AND (rq.lane='manual' OR rq.lane IS NULL))
SELECT c.is_commemorative, c.country='BE', COUNT(*), ROUND(AVG(p.top1_sim),2)
  FROM pool JOIN image_asset_dino_predictions p
    ON p.asset_id = pool.aid AND p.anchors_kind='2eur_all'
  JOIN coins c ON c.eurio_id = p.top1_eurio_id
 GROUP BY 1,2 ORDER BY 3 DESC;
```

Ce n'est **ni** un problème de scraping (l'offre belge est là : 1 699 annonces,
387 dans l'ère Philippe), **ni** de millésime : 111 des 116 crops sont déjà dans
la bonne ère. C'est que la machine ne regardait pas.

## Les trois banques, et laquelle voit quoi

```
2eur_commemo    508 vecteurs · dinov2-vits14 · dim  384 ·  0 / 56 courantes
2eur_all       1208 vecteurs · dinov2-vitl14 · dim 1024 · 38 / 56 courantes
2eur_standard    38 vecteurs · dinov2-vits14 · dim  384 · 38 / 56 (build de juin)
```
(lecture des `meta` de `ml/state/foundation_anchors_*.npz`)

**Le verdict d'auto-validation lit `2eur_commemo`** (`ml/shared/verdict_scope.py`),
la seule qui ne contienne aucune pièce courante. Conséquence mécanique : aucun
crop de standard ne peut jamais être auto-validé. Les *suggestions* affichées à
l'écran, elles, lisent `2eur_all` — d'où l'impression que DINO marche très bien
quand on regarde, et pas du tout quand on compte.

## Ce que vaut le modèle, mesuré

Sur **1 952 crops déjà tranchés à la main** (vérité terrain
`review_queue.decided_eurio_id`), précision du top-1 selon le spread :

| Palier | Crops | Précision |
|---|---:|---:|
| tous | 1 952 | 78,6 % |
| spread ≥ 0,02 | 1 616 | 89,1 % |
| spread ≥ 0,05 | 1 342 | 94,5 % |
| **spread ≥ 0,10** | **1 014** | **97,1 %** |

```sql
WITH lab AS (
  SELECT rq.decided_eurio_id AS verite, p.top1_eurio_id AS pred,
         COALESCE(p.spread,0) AS spread
    FROM review_queue rq
    JOIN image_asset_dino_predictions p
      ON p.asset_id = rq.image_asset_id AND p.anchors_kind='2eur_all'
   WHERE rq.status='done' AND rq.decided_eurio_id IS NOT NULL)
SELECT COUNT(*), ROUND(100.0*SUM(pred=verite)/COUNT(*),1)
  FROM lab WHERE spread >= 0.10;
```

Sur la file ouverte, **799 crops** dépassent 0,10 — décidables à 97 % de
précision.

## La couverture de la banque : rien ne manque, tout est en retard

> 🔴 **CORRIGÉ le 2026-08-19 (soir).** Le chiffre « 130 pièces sans ancre »
> ci-dessous est **périmé** : il décrivait un build antérieur. Au build du
> 2026-08-19T00:28, **664 classes portent leur canonique** et **7 seulement**
> n'en avaient pas (`n_no_canonical = 7`). Les 7 ont été rapatriées le soir même
> par `cd ml && .venv/bin/python -m referential.fetch_review_images --ids
> 375327,576180,194605,581307,581165,578765,576181` → « Done: 7 downloaded, 0
> failed », et `_class_specs_2eur_all` rend désormais `sans canonique: 0`.
>
> **Le trou réel s'est déplacé** : il n'est plus dans les canoniques mais dans
> les **exemplaires**. 125 classes en portent, **182** pourraient en porter — et
> la cause est trouvée : `build_dino_anchors.py` codait son `--db` par défaut en
> dur sur `ml/state/eurio.db` (6205 `image_assets`) au lieu d'honorer
> `EURIO_DB_PATH` → la réplique (12454). Correctif écrit, rebuild non lancé.
> Cf. [`../scan-sans-retrain/PREREQUIS.md`](../scan-sans-retrain/PREREQUIS.md) §P1.
>
> Le mécanisme décrit ci-dessous reste **exact** — c'est lui qu'il faut retenir.

**130 pièces sur 658 n'ont aucune ancre. Les 130 ont pourtant une image
canonique en base.** *(état antérieur, conservé pour la trace)* Le trou n'est
pas « les nouveautés » : ce sont des pays entiers.

| Pays | Sans ancre / total |
|---|---:|
| LU | 33 / 41 |
| MT | 27 / 34 |
| LT | 18 / 21 |
| IT | 17 / 42 |
| LV | 15 / 19 |

Cause : `_resolve_obverse_path` (`ml/training/foundation/anchors.py:280`) exige
`ml/datasets/<numista_id>/obverse.jpg` **sur le disque**. 115 pièces ont un
dossier vide (téléchargement Numista échoué, jamais journalisé) et 7 pièces de
2026 sont absentes de `coin_catalog.json`. Et une classe sans canonique est
éliminée **entièrement**, même avec quarante crops validés (`anchors.py:514`).

**Testé le 2026-08-19 : 5 URL sur 5 répondent 200 aujourd'hui.** Le rapatriement
ne coûte ni quota ni appel API (`retry_missing_images` n'écrit que sur le
filesystem).

## La traçabilité n'existe pas

> 🔴 **CORRIGÉ le 2026-08-19 (soir).** `dino_class_references` **n'est plus
> vide** : le build de la nuit a poussé sa trace au canonique par `--push`.
>
> ```bash
> sqlite3 "file:ml/state/eurio.replica.db?mode=ro" \
>   "select count(*) from dino_class_references;
>    select count(*) from dino_anchor_builds;
>    select method, count(*) from dino_class_references group by 1;"
> # 1250 | 1 | canonical|664  fps|586
> ```
>
> Le bug est corrigé à la source : `ml/scripts/build_dino_anchors.py:65-130`
> porte désormais `preflight_db_traceability()`, qui **sonde réellement
> l'écriture** (CREATE + DROP dans `store._writing()`) **avant** les quatre
> minutes d'encodage, et lève `ReadOnlyTraceabilityError` en nommant ses trois
> sorties. Le chemin nominal sous Direction A est `--push` →
> `client.ingest.push_dino_references` → `POST /ingest/dino-references` (route
> présente dans l'OpenAPI de production).
>
> **On peut donc désormais dire ce que contient la banque servie sans ouvrir le
> `.npz`** — mais seulement pour `2eur_all` : c'est le seul kind qui écrit
> (`WRITING_KINDS`). Le diagnostic d'origine, ci-dessous, reste la référence sur
> *pourquoi* la panne était muette.

`dino_class_references` était **vide dans les 8 bases locales et au canonique**.
La cause est écrite dans le code (`ml/scripts/build_dino_anchors.py:64-82`) :
`BEGIN IMMEDIATE` réussit sur une connexion en lecture seule, et l'échec
n'arrive qu'à la première vraie écriture — après quatre minutes d'encodage, à
la dernière ligne du build. Sous le flip Direction A, tous les builds ont donc
écrit leur `.npz` et perdu leur trace.

Il n'existait alors aucun moyen de dire ce que contient la banque servie sans
ouvrir le `.npz`.

## Le pool ambigu n'était jamais scoré

`_select_assets_for_backfill` faisait `LEFT JOIN coins` puis
`WHERE c.face_value = 2.0` — ce qui se comporte en INNER JOIN. Tout crop dont le
listing n'a pas de `target_eurio_id` sortait du périmètre : **2 193 crops
ouverts sur 6 897**, exactement ceux dont personne ne sait à quelle pièce ils
appartiennent.

## Les seuils sont en dur, et calibrés pour un autre encodeur

`ml/training/foundation/thresholds.py` : `top1_country_sim_min = 0.55` et
`country_spread_min = 0.05`, calibrés sur **vits14**, appliqués par un verdict
qui lira `2eur_all`/**vitl14** après bascule. Les deux échelles de similarité ne
sont pas comparables. Le docstring dit encore « valeurs provisoires, à calibrer
après 200 reviews annotées » — il y en a 1 955.
