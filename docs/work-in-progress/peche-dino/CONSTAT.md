# La pêche DINO — ce qu'on a bâti le 2026-08-20, et où elle casse

> Chaque chiffre porte sa requête. Base lue : `ml/state/eurio.replica.db`
> (réplique du canonique) sauf mention contraire, ou l'API `eurio-api` quand
> c'est précisé. Suite directe de [`../banque-dino/CONSTAT.md`](../banque-dino/CONSTAT.md).

## Le problème de départ

Une file de review était définie par **ce que le scrape visait**
(`source_images.target_eurio_id`). Pour une classe **courante**, c'est le mauvais
périmètre : le scrape cherche « 2 euro Italia », range ses crops dans le pool
ambigu du pays, et `repository.list_queue` force alors `kind='single'`.

Mesuré sur `it-2euro-standard-t1` (API locale `:8042`) :

```
/review-queue?eurio_id=it-2002-…                        57 items,   2 utiles
                        + order=dino&dino_top1_only     2 items
```

55 crops sur 57 étaient des non-italiennes que la banque savait déjà écarter.
Et les **136 crops de lots** dont le top-1 EST cette classe étaient hors
d'atteinte de cette file, par construction.

## Ce qu'on a bâti

Un périmètre par **prédiction** (`shared/dino_scope.py`), qui **remplace** celui
par cible et traverse les `kind`, les lanes et les pays d'annonce.

| | file par cible | pêche (top-1) |
|---|---:|---:|
| `it-2euro-standard-t1` | 57 items, 2 utiles | **137**, tous de la classe |

Recall par rang, crops ouverts, même classe :

```sql
-- top1
SELECT COUNT(*) FROM review_queue rq
  JOIN image_assets a ON a.id=rq.image_asset_id
  JOIN image_asset_dino_predictions p ON p.asset_id=a.id AND p.anchors_kind='2eur_all'
 WHERE rq.status='open' AND p.top1_eurio_id IN ('it-2002-2eur-standard-1st-map',
       'it-2008-2eur-standard-2nd-map');
-- top3 / top5 : idem via json_each(p.top_k_json) WHERE j.key < 3 (ou 5)
```

```
top1 = 139     top3 = 321     top5 = 485
```

Surfaces livrées : le bandeau de la page cohorte, la page `/review/peche`, la
section de la fiche d'une pièce, et le déroulé des lots **un par un**
(`useLotChain`). Détail des choix : [`DECISIONS.md`](DECISIONS.md).

## Le verdict d'usage, après une vraie session (2026-08-20)

**L'écran tient.** Le mot de l'opérateur : *« la fit de la page avec unité, lot,
top 1 / top 3 / top 5, et 0,05 / 0,10, franchement j'adore. La vue dans Coin
Details pour faire la pêche est vraiment très bien aussi. »*

**Le modèle, non — et pas partout pareil.** Sur `it-2euro-standard-t1` la pêche
a fait passer la classe de 5 à **26 photos au train** en une session. Sur
`es-2euro-juan-carlos-i-t2` et `be-2euro-philippe-t1`, l'opérateur ne recevait
que des pièces françaises et allemandes.

## Pourquoi — le chiffre qui explique tout

Part du pool pêché venant d'une annonce **du pays de la classe** :

```sql
SELECT CASE p.top1_eurio_id
         WHEN 'it-2002-2eur-standard-1st-map' THEN 'IT'
         WHEN 'it-2008-2eur-standard-2nd-map' THEN 'IT'
         WHEN 'es-2010-2eur-standard-juan-carlos-i-2nd-type-2nd-map' THEN 'ES'
         WHEN 'be-2014-2eur-standard-philippe' THEN 'BE' END AS classe,
       si.listing_country, COUNT(*)
  FROM review_queue rq
  JOIN image_assets a ON a.id = rq.image_asset_id
  JOIN source_images si ON si.id = a.source_image_id
  JOIN image_asset_dino_predictions p ON p.asset_id=a.id AND p.anchors_kind='2eur_all'
 WHERE rq.status='open' AND p.top1_eurio_id IN (…)
 GROUP BY 1,2;
```

| Classe | pool pêché | dont annonce du bon pays | |
|---|---:|---:|---:|
| `it-2euro-standard-t1` | 123 | 61 | **50 %** |
| `be-2euro-philippe-t1` | 80 | 44 | **55 %** |
| `es-2euro-juan-carlos-i-t2` | 76 | **14** | **18 %** |

L'Espagne est le cas dégradé : quatre crops sur cinq viennent d'annonces belges,
autrichiennes, allemandes ou italiennes. Le reste du pool ES se répartit
BE 15 · AT 15 · DE 11 · IT 9 · FR 6 · CY 5 · FI 3.

C'est cohérent avec ce que la banque sait faire : **tous les standards à
portrait se ressemblent** (Juan Carlos, Albert II, Philippe, Bertha von
Suttner…), et la comparaison est **globale** — un crop d'une annonce française
est confronté aux 671 étiquettes, pas seulement aux françaises.

Corollaire déjà observé le premier jour, et confirmé : trier les LOTS par
meilleure marge mettrait **six coffrets autrichiens** en tête de la file belge
(0,126 · 0,107 · 0,071 · 0,069 · 0,067 · 0,054). Sur les standards à portrait,
une marge élevée n'est pas un gage — c'est parfois le signe qu'il se trompe
avec assurance. D'où l'ordre par **nombre** de candidats, pas par marge.

## Le levier mesuré, pour la prochaine session

Parmi les crops standards **déjà validés par un humain**, quelle part vient
d'une annonce du pays de la pièce ?

```sql
WITH valides AS (
  SELECT c.country AS pays_piece, si.listing_country AS pays_annonce
    FROM image_assets a
    JOIN source_images si ON si.id = a.source_image_id
    JOIN coins c ON c.eurio_id = a.eurio_id
   WHERE si.source='ebay' AND a.training_eligible=1
     AND a.storage_status='present'
     AND (a.face IS NULL OR a.face != 'reverse')
     AND c.is_commemorative = 0)
SELECT COUNT(*), SUM(pays_piece = pays_annonce),
       ROUND(100.0*SUM(pays_piece = pays_annonce)/COUNT(*), 1) FROM valides;
```

| population | n | même pays |
|---|---:|---:|
| **standards** validés | 386 | **93,8 %** |
| commémoratives validées | 1733 | 99,2 % |

Donc un filtre « annonce du pays de la classe » coûterait **~6 % des vrais
positifs** et couperait, sur ES, **82 % du bruit** (76 → 14). C'est le geste le
moins cher et le mieux étayé pour la suite. Il reste à trancher (cf.
[`DECISIONS.md`](DECISIONS.md) §Q1) : filtre par défaut avec échappatoire, ou
simple palier proposé à côté de la marge.

Piste à instruire au même moment : les colonnes
`top1_country_eurio_id` / `country_spread` de `image_asset_dino_predictions`
portent déjà une comparaison **scopée au pays**. Le verdict s'en sert
(`top1_country_sim`) ; la pêche, elle, lit le top-1 global. Vérifier si le
top-1 scopé pays ne fait pas le travail sans filtre applicatif.

## Deux pannes trouvées en chemin, et réparées

**1. Le chaînage des lots n'existait pas en production.**
`serving/review_queue/repository.py` renvoyait `prev_listing_key=None,
next_listing_key=None` **en dur** (« coûteux à reproduire ici »). Le front lit
le canonique : les flèches ← / → de la page lot étaient grises depuis toujours.
Vérifié avant correction sur `eurio-api` — les deux clés étaient nulles. Côté
API locale, `_siblings` parcourait **toute** la file lot ouverte (5413 items),
sans scope : « suivant » sortait de la classe au premier clic.

**2. La file servait des données FICTIVES quand le canonique tombait.**
`useReviewApi.ts` substituait un `MOCK_QUEUE` de trente pièces inventées dès
qu'un fetch échouait au niveau réseau. Déclenché en séance par un
`docker compose up -d --build` sur `eurio-api` : l'écran, cadré sur une classe
**espagnole**, s'est mis à servir des pièces **slovènes à 1 EUR** de source
« catawiki », sans un mot. L'opérateur a conclu que la fonctionnalité était
cassée et a « trié » quatre items qui n'existaient pas.

Le tell était à l'écran sans être lisible : *« Pas de prédiction Dino pour ce
crop »*, dans une file qui par construction ne contient que des crops prédits.

Côté écriture c'était pire : `decide`/`skip`/`reject` renvoyaient un succès et
se contentaient d'un `console.info('[mock fallback] …')`.

Les 180 lignes de mock sont **supprimées** du chemin de lecture comme
d'écriture. Une lecture qui échoue lève et l'écran affiche « la file n'a pas pu
être lue » — un état distinct de « tout est résolu ». Une écriture qui échoue
lève et dit que la décision **n'a pas** été écrite.

**3. (mineur, même famille)** `typeof route.query.x === 'string'` rend `null` sur
un paramètre **dupliqué** (vue-router en fait un tableau), et le scope
**retombait sur le suivant, plus large** : une file cadrée sur l'italienne
standard s'est élargie à toute la cohorte et a servi une Saarland allemande, tri
DINO allumé. `queryParam()` prend la dernière valeur — un périmètre qui rate
doit se fermer, jamais s'ouvrir.

> Les trois sont la même faute : **un échec qui élargit ou qui invente, au lieu
> de s'arrêter.** C'est la signature à chercher en priorité dans ce repo.

## État de la cohorte `giga-40-vague1` à la fin de la session

```
it-2euro-standard-t1        26 au train   ·   0 à l'unité · 123 en lots (marge max 0,144)
es-2euro-juan-carlos-i-t2    9 au train   ·   4 à l'unité ·  76 en lots (marge max 0,097)
be-2euro-philippe-t1         5 au train   ·   0 à l'unité ·  80 en lots (marge max 0,126)
```

Plancher 10. Il manque **BE 5** et **ES 1**.
