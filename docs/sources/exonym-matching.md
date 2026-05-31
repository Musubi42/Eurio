# Exonymes & divergences de vocabulaire : nl.wikipedia ↔ eurio.db

## Le problème

La couche « attendu » de la matrice de couverture (`/referential/coverage`)
provient de **nl.wikipedia** (« Lijst van herdenkingsmunten van € 2 »), une
ligne par pièce avec un **thème en néerlandais**. On matche ce thème à un
`eurio_id` via le `SlugGroupMatcher`, en réutilisant les **titres NL qu'on a
déjà stockés** par pièce (`coin_names_i18n` / `coin_descriptions_i18n` lang='nl')
comme slugs auxiliaires. Même langue des deux côtés → ~98 % matchent tout seuls.

Restent des cas où **aucun slug ne peut matcher**, non pas par faute de seuil,
mais parce que Wikipédia emploie un **autre mot** que notre titre :

- **exonyme néerlandais** d'un toponyme : *Koerland* ≠ Kurzeme, *Letgallen* ≠
  Latgale, *Midden-Lijfland* (Moyenne-Livonie) ≠ Vidzeme, *Selonië* ≠ Selija ;
- **aspect / sujet différent** de la même pièce : *société ornithologique* vs
  *la cigogne noire* ; *Hildesheim / Michaeliskirche* vs *Basse-Saxe* ;
- **granularité différente** : *église Santa María del Naranco* vs la série
  *« églises du royaume des Asturies »* ;
- **descripteur différent** : *Koningsdubbelportret* (double portrait royal) vs
  *accession au trône*.

Nos traductions NL ne peuvent rien y faire (Koerland et Kurzeme n'ont aucune
lettre commune). Baisser le seuil fuzzy créerait des faux positifs ailleurs.
**On a déjà la réponse** (la pièce est en base) → on l'inscrit explicitement,
plutôt que d'inventer un algorithme pour des cas niche.

## La résolution

Table `MANUAL_OVERRIDES` dans `ml/referential/scrape_wikipedia_coins.py` :
`(country, year, theme_slug_wiki) → eurio_id`. Le matcher la consulte avant le
fuzzy (mécanisme partagé `SlugGroupMatcher.overrides`, comme JO/BCE). **Durable :
un re-scrape (`go-task ml:scrape-wikipedia-coins`) ré-applique les liens.**

Une ligne par cas (état au 2026-05-31) :

| Pays | Année | Thème nl.wikipedia | eurio_id | Pourquoi |
|---|---|---|---|---|
| DE | 2014 | Michaeliskirche in Hildesheim, Nedersaksen | `de-2014-2eur-state-of-lower-saxony` | monument vs Land |
| NL | 2014 | Koningsdubbelportret | `nl-2014-2eur-accession-of-king` | double portrait vs accession (→ canonique, pas la variante *coloured*) |
| LV | 2015 | 30 jaar Letse ornithologische vereniging | `lv-2015-2eur-the-black-stork` | société ornitho. vs la cigogne noire |
| LV | 2016 | Midden-Lijfland | `lv-2016-2eur-vidzeme` | exonyme (Moyenne-Livonie = Vidzeme) |
| ES | 2017 | kerk van Santa María del Naranco | `es-2017-2eur-churches-of-the-kingdom-of-asturias` | église précise vs série |
| LV | 2017 | Koerland | `lv-2017-2eur-kurzeme` | exonyme (Courlande = Kurzeme) |
| LV | 2017 | Letgallen | `lv-2017-2eur-latgale` | exonyme (Latgale) |
| LT | 2018 | 100 jaar onafhankelijke staat | `lt-2018-2eur-centenary-of-independent-baltic-states` | indép. lituanienne = série commune États baltes |
| LV | 2025 | Selonië | `lv-2025-2eur-selija` | exonyme (Sélonie = Selija) |

## Cas connexe : doublon de ligne (pas un exonyme)

**SM 2012 « 10 jaar euro »** : San Marino apparaît à la fois sous l'émission
commune « Europese Unie » (dépliée par pays → marqueur jointe) **et** dans une
ligne nationale au même `theme_slug`. Collision de PK. Corrigé non par override
mais par la **règle de dédup** (`scrape_wikipedia_coins.harvest`) : à PK égale,
on garde la ligne **matchée** plutôt que de la laisser écraser par le doublon
non matché.

## Ce qui reste légitimement « manquant »

Après overrides, les seules cellules rouges sont **vraiment absentes d'eurio.db**
(la pièce existe mais on ne l'a pas encore référencée) → c'est le terrain de
l'**auto-discover** (`POST /referential/discover-coin`, file de review). Au
2026-05-31 : EE 2020 (traité de Tartu), MT 2026 (chien des pharaons, Valletta).

## Maintenance

Quand une nouvelle pièce reste rouge alors qu'on l'a en base :
1. `go-task ml:scrape-wikipedia-coins -- --unmatched` pour voir le thème + pays/année.
2. Vérifier qu'on a bien la pièce (`coins`) et son `eurio_id`.
3. Ajouter une ligne dans `MANUAL_OVERRIDES` + une ligne dans le tableau ci-dessus.
4. Re-scraper. Ne **pas** toucher la DB à la main (les overrides sont la SOT).
