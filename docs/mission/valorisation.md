# Mission — Valorisation & complétion

> Index : [`README.md`](./README.md) · Stratégie : [`product-strategy.md`](./product-strategy.md)

## Objectif

Donner de la **valeur émotionnelle** à la donnée qu'on a déjà :
- « **ta collection vaut €X** » (somme des cotes du coffre) ;
- **cote par qualité** d'une pièce (UNC / TTB / TB), comme une fiche marchande ;
- « **il te manque Y → acheter ici** » (la carte/sets disent le manque, on route vers l'achat) ;
- **alertes nouvelles sorties** (on les connaît au bleeding-edge via JO/couverture).

C'est le **hook gratuit** qui accroche les collectionneurs, et la **base du palier P1**
(affiliation) — plus l'amorce de la liquidité marketplace (wishlists + « à vendre »).

## Acquis (la donnée est prête)

- **Prix par qualité** : LMDLP (cote boutique par grade) + eBay (vélocité). Mapping UNC/TTB/TB.
- **Manque** : matrice de couverture + sets → on sait précisément ce qui manque à un coffre.
- **Bleeding-edge** : JO/couverture → on détecte les nouvelles commémo tôt (matériau d'alertes).
- Routing marketplaces (eBay/LMDLP/monnaies) déjà étudié.

## Reste à faire

- Surfacer la **cote** dans la fiche pièce + un **total coffre** (« collection : €X »).
- « **Manquante → où acheter** » : liens sortants (deviennent affiliés en P1, cf. Croissance).
- **Alertes** nouvelles sorties / variations de prix (base premium P2).
- (Option) exposer la cote côté **catalogue web** (cf. Croissance).

## Dépendances souples

- Données **prêtes** ✅. Besoin d'un **minimum d'app** (fiche pièce + coffre) pour l'afficher.
- Pas bloquant pour le scan ni l'app : c'est une **couche par-dessus** la boucle.

## Done quand

L'utilisateur voit **ce que vaut sa collection** et **où compléter** ce qui lui manque,
directement dans l'app.

## Détail / exécution

Memories : `project_lmdlp_rebuild`, `project_ebay_api_strategy`, `reference_numista_prices`,
`project_coin_richness`, `project_eurlex_source`. Données : `docs/sources/`.
