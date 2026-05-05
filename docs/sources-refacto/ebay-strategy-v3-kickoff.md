# Bloc 3 — eBay strategy v3 : pagination + front review lot price

> Plan figé. Implémentation à faire dans une session future. Préreq : bloc 2
> (`ebay-strategy-v2-kickoff.md`) terminé, en particulier l'API
> `decide_lot_with_price` (sous-chantier 2.C).

## Sous-chantier 3.A — Pagination Browse API > 50

### Contexte

Aujourd'hui `DEFAULT_SEARCH_LIMIT = 50` dans `ml/sources/ebay/adapter.py`
(commentaire D-23 : "no pagination V1"). On rate les listings au-delà de
la 50e position quand le marché est riche.

D'après le probe S3, la commémo `fr-2012-2eur-abbe-pierre` a `total=16356`
avec query large — on en récupère 50. Même en supposant que la pertinence
chute après les 20-30 premiers (sort par `bestMatch`), il y a clairement
moyen d'aller chercher 100-200 résultats utiles sur les commémos riches.

### Stratégie : pagination dynamique avec arrêt-précision

Fetcher page par page (offset 0, 50, 100, 150) jusqu'à 4 pages max, **mais
s'arrêter dès que la précision chute** :

```
page = 0
while page < MAX_PAGES:
    items = client.search(q, offset=page*50, limit=50)
    n_passing_postfilter = count(items that match year+theme post-filter)
    if page > 0 and (n_passing_postfilter / len(items)) < 0.20:
        break  # précision chute, on arrête
    page += 1
```

Coût quota : 1-4 calls par eurio_id selon la richesse. Sur les eurios
"pauvres" (AD, marchés petits) → 1 page suffit (`total < 50`). Sur les
riches (FR, DE) → 2-4 pages.

### Paramètres

- `MAX_PAGES = 4` (limit total = 200 résultats max)
- Seuil de précision = 20% (ajustable, à mesurer en run réel)
- Toujours fetcher page 0, même si vide

### Schéma DB

Pas de migration. La pagination est interne au step discover.

### Logging

Étendre `discovery_searches.query_filters_json` avec `pages_fetched` et
`stopped_reason` (`"max_pages"`, `"precision_drop"`, `"empty_page"`,
`"single_page_total"`). Permet de mesurer après-coup combien de calls
sont vraiment utiles.

## Sous-chantier 3.B — Front review lot avec input prix

### Contexte

Bloc 2.C a câblé l'API `decide_lot` pour accepter un prix par crop. Le
front actuel (`LotReviewDetailPage.vue`) ne propose pas ce champ — c'est
ce qu'on ajoute ici.

### UX

Dans le drawer de review d'un lot, pour chaque crop décidé "assigné à
eurio_id X" (pas reject ni skip) :
- Champ numérique optionnel **prix EUR/pièce**
- Auto-suggestion si le lot a un prix global et N crops décidés :
  `prix_global / N` proposé en placeholder. L'utilisateur peut accepter
  (clic) ou écraser.
- Si l'utilisateur laisse le champ vide → on n'envoie pas `price` à l'API
  (pas de coin_market_quote créée — comportement V1).

Pas de validation custom côté front à part `> 0` et `< 10000`.

### Composant

Drawer existant : `LotDetailDrawer.vue` (vu dans le git status). À étendre
avec :
- Input prix par crop (number, step 0.01)
- Bouton "remplir avec prix moyen" (calcul `lot_price / n_decided_to_eurio`)
- Submit qui passe le payload enrichi à l'API `decide_lot`

Style : tokens.css uniquement, pas de hardcoded. Cohérent avec le reste
du drawer.

### Edge cases

- Lot avec un seul crop décidé non-reject → suggestion = lot_price (prix
  total = prix de la pièce).
- Lot avec 0 crop assigné (tous reject/skip) → pas de suggestion, pas
  d'input.
- L'utilisateur peut modifier le prix après envoi ? V1 : non,
  l'attribution est "one-shot". V2 future : édition manuelle des
  coin_market_quotes via une page dédiée (hors scope ici).

## Sous-chantier 3.C — Décision : pièces standards millésimées

### Contexte

Aujourd'hui le pipeline est centré sur les commémos (1 eurio_id = 1
pièce unique). Les pièces standards (la 2€ standard de chaque pays)
sont représentées par **un seul eurio_id** sans année (vérifier dans
`coins`). Conséquence : pas de granularité année pour les standards,
on ne peut pas tracker les prix par millésime ("la 2€ Italie 2007 vaut
plus cher que les autres").

### Question à trancher

**Option A** : 1 eurio_id par millésime pour les standards
(ex: `it-2007-2eur-standard`, `it-2008-2eur-standard`, …). Avantage :
granularité totale, prix par millésime trackés. Inconvénient :
explosion du référentiel (~21 pays × ~25 ans × 8 dénominations =
~4000 nouvelles entries), beaucoup d'overhead pour des pièces souvent
identiques visuellement.

**Option B** : 1 eurio_id global standard + champ `year` sur les
listings ingérés. Le `coin_market_quotes` aurait `(source, eurio_id,
period_start, condition_raw, year)` au lieu de juste `(source, eurio_id,
period_start, condition_raw)`. Avantage : référentiel léger.
Inconvénient : changement de schéma `coin_market_quotes` (UNIQUE étendu),
toute la logique d'attribution doit gérer `year`.

**Option C** : statu quo, on ne capte pas le prix par millésime des
standards en V1. On se concentre sur les commémos (où c'est déjà 1
eurio_id par pièce).

### Recommandation

**Option C pour la V1** car les commémos sont la majorité du marché
intéressant (rares + collectibles + cotés). Les standards sont du
"face value" la plupart du temps. À reconsidérer en V2 si signal
business clair (utilisateurs demandent les prix de standards
millésimées).

### Implication pour le pipeline scrape

Tant qu'on est en option C : le post-filter year peut être souple
(accept-on-missing). On ne perd pas grand-chose à mal tagger un
listing "2€ standard" entre 2007 et 2008 puisqu'on ne distingue pas
les eurio_ids.

## Découpage en chunks (proposé)

- **Chunk 3.A.1** : refactor `_search_and_expand` avec boucle de
  pagination dynamique. Tests.
- **Chunk 3.A.2** : run prod sur 5 eurios riches (FR/DE/IT 2€ commémos
  populaires), mesure pages_fetched / stopped_reason / recall delta.
- **Chunk 3.B.1** : extension `LotDetailDrawer.vue` avec input prix
  par crop + bouton suggestion.
- **Chunk 3.B.2** : tests UX manuels (golden path + edge cases).
- **Chunk 3.C** : décision business sur standards (A/B/C) lors d'un
  point dédié. Pas d'implémentation tant que pas tranché.

Indépendants. Peut commencer par n'importe quel sous-chantier.
