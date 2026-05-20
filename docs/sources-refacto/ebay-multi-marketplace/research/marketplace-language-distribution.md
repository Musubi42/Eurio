# Recherche — distribution des langues de titres par marketplace

> Mesure empirique : dans quelle langue les vendeurs rédigent-ils leurs
> titres sur chaque marketplace eBay ? Alimente
> `MARKETPLACE_ACTIVE_LANGS` (matcher I2).
>
> Livré dans le chunk V1, 2026-05-20.

## Contexte

Le matcher de thème I2 doit comparer le titre seller eBay aux tokens du
titre Numista dans la **bonne langue**. Un marketplace ne sert pas
qu'une langue : un vendeur écrit dans la langue de son choix. Il faut
mesurer, par marketplace, quelles langues dominent réellement.

## Méthode

Script : `ml/scripts/probe_marketplace_languages.py` (jetable).

- 8 commémos 2€ circulées (FR/DE/IT/ES/NL/BE/AD/SM) × 9 marketplaces.
- ~3500 titres tirés (~74 calls eBay).
- Une langue est « active » sur un marketplace si elle ≥ 10 % des
  titres classés.

## Échec de `langdetect`

Premier essai avec `langdetect` : **inexploitable**. Sur les titres
courts en majuscules (`FRANCIA 2022 2 EURO COMMEMORATIVO`),
`langdetect` smear systématiquement IT/ES vers `pt` (portugais) —
jusqu'à 38 % de faux `pt` sur EBAY_IT. Abandonné.

## Classifieur heuristique

Remplacé par un classifieur maison : scoring par mots-marqueurs
numismatiques (`commemorativo`/`moneta` IT, `conmemorativa`/`moneda`
ES, `münze`/`gedenkmünze` DE, …) + noms de pays dans la langue du
vendeur (`Frankrijk`=NL, `Frankreich`=DE — très discriminants) +
function-words.

**Piège écarté** : `UNC`/`BU`/`FDC`/`COINCARD` sont du boilerplate de
grading **international**. Les inclure comme marqueurs EN gonflait le
bucket `en` de titres FR/IT évidents (`2 Euros Commémorative Italie …
UNC` classé `en`). Retirés.

## Résultats (distribution sur titres classés)

| Marketplace | Distribution | Actives ≥10 % |
|---|---|---|
| EBAY_AT | de 89, it 6, fr 4 | de |
| EBAY_BE | fr 80, nl 8, en 8 | fr |
| EBAY_DE | de 97 | de |
| EBAY_ES | es 74, **it 19**, en 4 | es, it |
| EBAY_FR | fr 92, en 6 | fr |
| EBAY_GB | en 96, it 3 | en |
| EBAY_IE | en 77, **it 16** | en, it |
| EBAY_IT | it 88, en 6 | it |
| EBAY_NL | **fr 44**, nl 30, it 14, en 10 | fr, nl, it |

`unknown` (titres non-discriminants type `2 EURO FRANCIA 2022`) : 25-45 %
selon le marketplace. Les % sont calculés sur le sous-ensemble classé.

## Findings

1. **eBay.nl porte surtout du français** (44 %, vendeurs Benelux), pas
   du néerlandais (30 %). Contre-intuitif mais net.
2. **Les vendeurs italiens cross-listent agressivement** sur ES (19 %),
   IE (16 %), NL (14 %).
3. `en` est sous-détecté (titres EN courts → `unknown`) — voir caveat.

## Décision — `MARKETPLACE_ACTIVE_LANGS` recalibré

Corrections appliquées dans `ml/sources/ebay/marketplaces.py` :

- `EBAY_ES` → `+it`
- `EBAY_IE` → `+it`
- `EBAY_NL` → `+fr +it` (fr était manquant alors qu'il domine)

`en` **conservé partout** malgré une mesure souvent < 10 % : il est
sous-détecté (titres EN courts non-discriminants), et le coût d'un faux
lang actif ≈ 1 lookup SQLite vs. une perte de recall si on le retire.
Asymétrie → on garde généreux.

## Caveat de méthode

Le `total` eBay et le classifieur heuristique sont des proxies. Le
classifieur ne classe que ~55-75 % des titres (le reste = `unknown`,
non-discriminant). Suffisant pour un seuil à 10 %, pas pour une mesure
fine. À re-confirmer si on ouvre des marketplaces secondaires.

## Artefacts

- Script : `ml/scripts/probe_marketplace_languages.py` (mode
  `--reclassify` pour ré-itérer le classifieur hors-ligne sur le corpus
  brut sauvegardé)
- JSON : `ml/state/probe_marketplace_languages_*.json` (embarque tous
  les titres bruts)
