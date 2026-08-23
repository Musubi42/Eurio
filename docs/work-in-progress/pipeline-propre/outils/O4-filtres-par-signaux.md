# O4 · Les filtres par signaux dans le périmètre de pêche

> **Statut : LIVRÉ le 2026-08-23.** O4c (désarmement pays) au lot 0, O4a/b
> (ère, dénomination) au lot 6. Station 2 du [flow](../FLOW-ADMIN.md).
> Dépend de [O5](O5-familles-de-signal.md).
>
> Implémentation : `ml/shared/dino_scope.py` (`era_only`, `min_denom`,
> `country_disarmed`, `n_hidden_by_*`). Mesures rejouables :
> `ml/scripts/measure_o4_filters.py`.
>
> ⚠️ **Deux réserves sur ce document.**
> 1. Les EFFECTIFS des quatre régimes ne se reproduisent plus (2 861 crops
>    labellisés le 23/08 contre 2 169 le 20/08 — la base continue d'être
>    tranchée). Les PRÉCISIONS, elles, retombent au dixième près.
> 2. **La porte dénomination (§b) n'a aucun appelant** : le paramètre existe de
>    bout en bout, aucun front ne l'arme. Décision à prendre — la câbler ou la
>    retirer. Cf. [`../REPRENDRE-ICI.md`](../REPRENDRE-ICI.md).
> Prolonge `ml/shared/dino_scope.py` et les 9 décisions de
> [`../../peche-dino/DECISIONS.md`](../../peche-dino/DECISIONS.md).

## Le geste

Faire lire à la pêche les signaux qu'elle ignore, et empêcher son filtre par
défaut de vider la file en silence.

## Ce que la pêche lit aujourd'hui

Un seul signal : `image_asset_dino_predictions.top1_eurio_id` (ou le top-k),
plus `COALESCE(country_spread, spread)` comme palier de marge, plus
`source_images.listing_country`. C'est tout.

Ce qu'elle **ne lit pas**, alors que c'est peuplé :

| signal | couverture sur les crops ouverts |
|---|---|
| `listing_text_signals` (pays, années, lot, marqueurs, `listing_kind`) | **6 617 / 6 617** — année sur 5 808, pays sur 5 276 |
| `image_asset_dino_predictions.denom_2eur_score` | 7 910 / 12 454 |
| `face_margin`, `reverse_sim` | 12 454 / 12 454 |

## Les trois changements, par ordre de valeur mesurée

### a) La contradiction d'ère — gratuite, et elle ne coûte aucun vrai positif

On compare l'**intervalle** des années du titre à l'**ère** de la classe, et on
écarte le crop quand les deux ne se recoupent pas.

L'ère d'une classe courante = `[première année, année du groupe suivant du même
pays − 1]` ; d'une commémorative = son millésime. Calcul :

```sql
SELECT COALESCE(design_group_id, eurio_id) cls, country, MIN(year)
  FROM coins WHERE face_value = 2.0 AND is_commemorative = 0 GROUP BY 1;
-- puis, par pays, la borne haute = (min du groupe suivant) − 1
-- es-2euro-juan-carlos-i-t1 (1999,2009) · t2 (2010,2014) · felipe-vi-t1 (2015,9999)
```

⛔ **La sémantique d'intervalle n'est pas un détail d'implémentation.** Traiter
`years_json = [1999, 2012]` comme une **énumération** produit de fausses
contradictions sur les commémoratives — un titre « 1999–2012 » ne contient pas
littéralement `2004`, et une commémorative de 2004 se fait écarter à tort. Coût
mesuré : le rappel tombe de **85,4 % à 74,2 %** sur les lots. En intervalle
(`Y[0] <= era[1] AND era[0] <= Y[-1]`), il ne coûte **rien** :

| régime | pays seul (l'existant) | pays + ère non contredite |
|---|---|---|
| lots / courantes · n=68 | 47 servis · 91,5 % | **45 · 95,6 %** |
| lots / commémos · n=418 | 369 · 96,7 % | 369 · 96,7 % *(strictement inchangé)* |
| singles / courantes · n=327 | 299 · 99,7 % | 296 · **100 %** |
| singles / commémos · n=1356 | 1245 · 98,8 % | 1234 · **99,1 %** |

Effet sur les pools réels : **BE 44 → 32, ES 11 → 5, IT 61 → 61**.

Concrètement, sur la file belge, il retire le lot *« Belgische Euro-Münzen –
14 Stück (1999–2012) »* — 9 crops marqués Philippe dans une annonce où **aucune
pièce ne peut être une Philippe** (ère 2014+). Ce lot est aujourd'hui **le
premier de la file**, parce que l'ordre est `n_matching_crops DESC`.

> **Corollaire à traiter dans le même geste** : l'ordre des lots doit compter
> les candidats **survivant aux filtres**, sinon le premier écran reste faux.

### b) La porte dénomination

`denom_2eur_score ≥ 0,4` — mesuré sur 513 crops labellisés par un humain : garde
**95,3 %** des 2 € ; sur les crops que la probe a classés `not_2eur`, en garde
2,3 %.

⚠️ **Le second chiffre est circulaire** (`denom='not_2eur'` a été posé par la
probe elle-même). Le premier ne l'est pas — c'est celui qui compte : le seuil
coûte ~5 % de vrais positifs.

Effet réel : le pool belge passe de 32 à **25**, en retirant surtout les
piécettes des coffrets « 1 cent à 2 euros ». C'est le cas d'usage : dans un KMS,
sept crops sur huit ne sont pas des 2 €.

### c) 🔴 Le filtre pays qui se désarme au lieu de vider

C'est le correctif le plus important de cet outil, et il concerne du code
**déjà livré et actif par défaut**.

```
classes avec un pool de pêche non vide (rang 1)   338
  dont le filtre pays ramène à ZÉRO               137   (41 %)
crops ouverts devenus inatteignables par défaut   412
```

Par pays : PT 13/13, LU 12/12, VA 11/11, LT 10/10, MC 9/9, MT 9/9, LV 8/8,
SK 8/8 — **exactement les pays les plus pauvres en ancres**.

Cause : `listing_country` n'est pas le pays de l'annonce mais le pays que la
recherche **visait** (`sources/ebay/adapter.py:601`, `listing_country=group.country`).
Le filtre est donc une propriété de notre plan de scrape. Là où on n'a jamais
scrapé, il ne reste rien.

Et la mesure qui a fondé D9 ne pouvait pas le voir : sur les 2 169 crops
labellisés, **15 (0,7 %)** appartiennent à ces 15 pays, et **0 sur 15** aurait
survécu au filtre. Le « 5 % de vrais positifs perdus » est un agrégat.

**Le remède, aligné sur un garde-fou déjà écrit.** `dino_scope.class_country`
désactive déjà le filtre quand le pays de la classe ne se résout pas, avec la
bonne justification : *« mordre sur une valeur inconnue renverrait zéro ligne,
ce qui se lit “rien à trancher” : plausible, et faux. »* Il faut étendre ce
raisonnement au cas mesuré : **quand le filtre ramène la file à zéro alors que
le pool non filtré n'est pas vide, il se désarme et le dit.**

```
si pool_filtré == 0 et pool_brut > 0 :
    servir le pool brut
    afficher « filtre pays désarmé — il ne laissait rien (N crops hors ES) »
```

⛔ **Ce n'est pas un repli automatique du genre écarté en D1.** D1 refusait
« pêche si elle donne quelque chose, sinon cible » parce que le périmètre
devenait dépendant de **l'item** — deux crops voisins servis par deux règles.
Ici la bascule dépend de **la classe**, elle est calculée une fois, et elle est
**affichée**. L'écran peut toujours dire ce qu'il montre.

## Le contrat

Tout passe par `build_dino_scope`, qui reste le seul endroit du périmètre :

```python
def build_dino_scope(
    conn, *, dino_class, rank=1, min_spread=None,
    country_only=True,
    era_only=True,          # nouveau — écarte les crops dont le titre contredit l'ère
    min_denom=None,         # nouveau — seuil sur denom_2eur_score
    ...
) -> DinoScope
```

`DinoScope` gagne trois champs de **transparence**, parce qu'un filtre par défaut
qui tait son effet ment par omission (D9) :

```python
country: str | None       # déjà là
country_disarmed: bool    # le filtre pays s'est-il désarmé, et pourquoi
n_hidden_by_era: int
n_hidden_by_denom: int
```

## Réglages par défaut proposés

| filtre | défaut | levable |
|---|---|---|
| pays | actif, **auto-désarmé** si vide | oui (`?pays=tous`) |
| ère | **actif** | oui — il ne coûte aucun vrai positif en mesure |
| dénomination | **inactif** | oui — il coûte ~5 % de vrais positifs, c'est un choix d'opérateur |

## Comment on vérifie qu'il marche

- **La mesure des quatre régimes se rejoue** et rend les mêmes nombres qu'ici.
  Le script est dans le scratchpad de la session du 2026-08-20 ; il doit
  déménager dans `ml/scripts/` pour être rejouable.
- **Le lot belge 1999–2012 disparaît** de la file `be-2euro-philippe-t1`, et
  l'ordre ne le remet pas en tête.
- **Une classe portugaise sert quelque chose** : `pt-*` avec `country_only=True`
  ne rend plus une liste vide mais le pool brut, avec la mention du désarmement.
- **Mutation** : forcer `era_only` en énumération au lieu d'intervalle doit
  faire chuter le rappel commémos-lots de 85,4 à 74,2 % dans le test. Si le test
  reste vert, il ne teste pas ce qu'on croit.

## Ce que cet outil n'est pas

- **Ce n'est pas un auto-accept.** Tout ce qu'il fait est de retirer des
  vignettes qu'un humain aurait écartées à l'œil.
- **Il ne rouvre pas le top-1 scopé pays** (`top1_country_eurio_id`, écarté en
  D9 : 1,2 point de gain, `target_country` NULL sur 2 254 des 6 651 crops
  ouverts). Le re-rang **dans le top-5 du pays** est une autre piste, mesurée
  séparément : elle gagne +5 à +6 points de rappel sur les **singles** et
  **dégrade les lots** (91,5 → 74,1 %). Régime-dépendante, donc hors de cet
  outil tant qu'elle n'a pas été confirmée sur le gold.
