# Audit de la cohorte giga-40-vague1 — ce qu'on entraînerait aujourd'hui

> Mesuré le 2026-08-18 sur `888cbc5d3a9e`. Compteurs lus au **canonique**
> (`/lab/cohorts/888cbc5d3a9e/training-crops`), stock de review lu au funnel local.
> Rien ici n'est estimé : chaque nombre vient d'une de ces deux réponses.

## En une ligne

**40 classes · 129 pièces · 1171 photos** partiraient à l'entraînement.
**7 classes** sont sous le plancher de 10. **44 photos** manquent pour les y amener.

## Le point qui décide de tout : une classe ≠ une pièce

Le modèle n'apprend pas « une pièce », il apprend **un dessin**. Plusieurs pièces
qui partagent leur face nationale forment **une seule classe**, et **leurs photos
s'additionnent**. C'est pour ça que 129 pièces font 40 classes.

Les cas où ça compte le plus :

| Classe | Pièces regroupées | Photos mises en commun |
|---|---:|---:|
| `eu-eu-flag-2015` | 21 | 16 |
| `eu-erasmus-2022` | 19 | 16 |
| `eu-euro-cash-2012` | 18 | 68 |
| `eu-emu-2009` | 16 | 63 |
| `eu-rome-2007` | 13 | 34 |
| `it-2euro-standard-t1` | 2 | 2 |

Conséquence pratique : **trier une photo de n'importe quelle pièce du groupe**
fait monter la classe entière. Sur le drapeau européen 2015, une photo maltaise et
une photo slovaque nourrissent la même classe.

## Vérification : aucune pièce n'est perdue

Les 129 pièces déclarées sont **toutes** rattachées à une classe — vérifié un à un,
0 orpheline. Sept d'entre elles n'apparaissent pas dans la vue sourcing parce que
celle-ci regroupe les millésimes d'une même ère sur une seule ligne :

| Pièce invisible au sourcing | Portée par | Classe |
|---|---|---|
| `at-2008-2eur-standard-2nd-map` | `at-2002-2eur-standard-1st-map` | `at-2euro-standard-t1` |
| `be-2007-2eur-standard-albert-ii-2nd-map-1st-type-1st-portrait` | `be-1999-2eur-standard-albert-ii-1st-map-1st-type-1st-portrait` | `be-2euro-albert-ii-t1` |
| `be-2009-2eur-standard-albert-ii-2nd-map-2nd-type-1st-portrait` | `be-2008-2eur-standard-albert-ii-2nd-map-2nd-type-2nd-portrait` | `be-2euro-albert-ii-t2` |
| `de-2008-2eur-standard-2nd-map` | `de-2002-2eur-standard-1st-map` | `de-2euro-standard-t1` |
| `es-2007-2eur-standard-juan-carlos-i-1st-type-2nd-map` | `es-1999-2eur-standard-juan-carlos-i-1st-type-1st-map` | `es-2euro-juan-carlos-i-t1` |
| `fr-2007-2eur-standard-2nd-map` | `fr-1999-2eur-standard-1st-map` | `fr-2euro-standard-t1` |
| `it-2008-2eur-standard-2nd-map` | `it-2002-2eur-standard-1st-map` | `it-2euro-standard-t1` |

Elles seront donc bien entraînées. C'est un défaut d'affichage, pas de données.

## Les 40 classes, de la plus pauvre à la plus riche

`photos` = ce qui part à l'entraînement · `à trancher` = crops en attente de verdict ·
`jamais découpés` = images téléchargées dont aucun crop n'a été tiré.

| # | Classe | Type | Pièces | Photos | À trancher | Jamais découpés |
|---:|---|---|---:|---:|---:|---:|
| 1 | `it-2euro-standard-t1` ⚠ | ère | 2 | **2** | 193 | 80 |
| 2 | `be-2012-2eur-75th-anniversary-of-queen-elisabeth-music-competition` ⚠ | pièce | 1 | **3** | 74 | 19 |
| 3 | `de-2006-2eur-state-of-schleswig-holstein` ⚠ | pièce | 1 | **3** | 35 | 7 |
| 4 | `be-2euro-philippe-t1` ⚠ | ère | 1 | **4** | 280 | 104 |
| 5 | `cy-2euro-standard-t1` ⚠ | ère | 1 | **4** | 293 | 56 |
| 6 | `es-2euro-juan-carlos-i-t2` ⚠ | ère | 1 | **4** | 241 | 66 |
| 7 | `fr-2018-2eur-100th-anniversary-of-the-end-of-the-first-world-war-bleuet-de-france` ⚠ | pièce | 1 | **6** | 86 | 18 |
| 8 | `be-2euro-albert-ii-t1` | ère | 2 | **10** | 121 | 104 |
| 9 | `de-2009-2eur-federal-state-of-saarland` | pièce | 1 | **11** | 115 | 25 |
| 10 | `fr-2euro-standard-t1` | ère | 2 | **11** | 139 | 50 |
| 11 | `de-2euro-standard-t1` | ère | 2 | **13** | 299 | 108 |
| 12 | `es-2euro-juan-carlos-i-t1` | ère | 2 | **13** | 272 | 120 |
| 13 | `eu-eu-flag-2015` | ère | 21 | **16** | 70 | 140 |
| 14 | `eu-erasmus-2022` | ère | 19 | **16** | 46 | 80 |
| 15 | `be-2euro-albert-ii-t2` | ère | 2 | **16** | 125 | 87 |
| 16 | `fi-2016-2eur-90th-anniversary-of-the-death-of-the-writer-eino-leino` | pièce | 1 | **16** | 38 | 54 |
| 17 | `de-2020-2eur-german-polish-reconciliation` | pièce | 1 | **17** | 50 | 89 |
| 18 | `fr-2018-2eur-simone-veil` | pièce | 1 | **18** | 9 | 56 |
| 19 | `ad-2euro-standard-t1` | ère | 1 | **22** | 62 | 191 |
| 20 | `es-2euro-felipe-vi-t1` | ère | 1 | **24** | 254 | 108 |
| 21 | `fr-2016-2eur-euro-2016-football-championship` | pièce | 1 | **25** | 35 | 60 |
| 22 | `fi-2016-2eur-100th-anniversary-of-the-birth-of-georg-henrik-von-wright` | pièce | 1 | **26** | 87 | 96 |
| 23 | `at-2018-2eur-100-years-republic-of-austria` | pièce | 1 | **27** | 78 | 214 |
| 24 | `fi-2017-2eur-100-years-of-independence` | pièce | 1 | **27** | 28 | 95 |
| 25 | `fr-2010-2eur-degaulles-radio-speech-on-june-18th-1940-70th-anniversary-of-the-appeal-of-june-18` | pièce | 1 | **29** | 192 | 49 |
| 26 | `it-2016-2eur-550th-anniversary-of-the-death-of-donatello` | pièce | 1 | **29** | 26 | 62 |
| 27 | `de-2020-2eur-brandenburg-the-bundeslander-series` | pièce | 1 | **33** | 95 | 133 |
| 28 | `fr-2016-2eur-100th-anniversary-of-the-birth-of-francois-mitterrand` | pièce | 1 | **33** | 27 | 112 |
| 29 | `eu-rome-2007` | ère | 13 | **34** | 75 | 168 |
| 30 | `de-2007-2eur-state-of-mecklenburg-vorpommern` | pièce | 1 | **34** | 60 | 126 |
| 31 | `es-2016-2eur-old-town-of-segovia-and-its-aqueduct` | pièce | 1 | **35** | 77 | 264 |
| 32 | `at-2016-2eur-200th-anniversary-of-the-national-bank` | pièce | 1 | **39** | 59 | 176 |
| 33 | `be-2011-2eur-100th-international-womens-day` | pièce | 1 | **40** | 76 | 231 |
| 34 | `fi-2012-2eur-150th-birthday-of-helene-schjerfbeck` | pièce | 1 | **45** | 23 | 18 |
| 35 | `it-2016-2eur-2200th-anniversary-of-the-death-of-plautus` | pièce | 1 | **47** | 93 | 82 |
| 36 | `fr-2008-2eur-french-presidency-of-the-council-of-the-european-union` | pièce | 1 | **49** | 76 | 199 |
| 37 | `eu-emu-2009` | ère | 16 | **63** | 205 | 215 |
| 38 | `eu-euro-cash-2012` | ère | 18 | **68** | 153 | 256 |
| 39 | `at-2005-2eur-50th-anniversary-of-the-austrian-state-treaty` | pièce | 1 | **110** | 175 | 171 |
| 40 | `at-2euro-standard-t1` | ère | 2 | **149** | 271 | 197 |

## Ce qui bloque

**7 classes sous 10 photos.** Le contrôle avant entraînement refuse de créer l'itération.

| Classe | Photos | Manque | Stock à trancher | Suffit ? |
|---|---:|---:|---:|---|
| `it-2euro-standard-t1` | 2 | 8 | 193 | oui, largement |
| `be-2012-2eur-75th-anniversary-of-queen-elisabeth-music-competition` | 3 | 7 | 74 | oui, largement |
| `de-2006-2eur-state-of-schleswig-holstein` | 3 | 7 | 35 | oui, largement |
| `be-2euro-philippe-t1` | 4 | 6 | 280 | oui, largement |
| `cy-2euro-standard-t1` | 4 | 6 | 293 | oui, largement |
| `es-2euro-juan-carlos-i-t2` | 4 | 6 | 241 | oui, largement |
| `fr-2018-2eur-100th-anniversary-of-the-end-of-the-first-world-war-bleuet-de-france` | 6 | 4 | 86 | oui, largement |

## Les réserves non exploitées

- **4713 crops attendent un verdict** (1017 à l'unité, 3696 en lots).
- **4486 images téléchargées n'ont jamais donné de crop.** C'est le gisement
  que la passe de secours bimétal a rouvert hier ; il n'a été exploité que sur 11 pièces.
- **33 crops sont bloqués hors file** : ni tranchés, ni visibles en review.

## Les fuites à connaître

- **56 crops sont partis sur 37 pièces sœurs hors cohorte.**
  Exemple : 4 crops du Bleuet de France ont atterri sur sa version *colorée*, qui
  n'est pas dans la cohorte. Ces photos existent mais n'entraîneront rien.
- **1 crop marqué revers** et **0 face non tranchée** : validés mais exclus
  du bake. Le piège existe, il ne coûte presque rien aujourd'hui.

## Ce qu'il reste à décider

1. **Le plancher de 10 est un choix, pas une loi.** Il est réglable. La vraie question :
   accepte-t-on d'entraîner avec des classes à 10 photos quand d'autres en ont 149 ?
2. **Les 7 classes faibles sont toutes rattrapables par le tri seul** — aucune ne
   demande de scraper. Le stock est là.
3. **Le gisement des jamais-découpés** peut réduire le tri avant même de commencer.
