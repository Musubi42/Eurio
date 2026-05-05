# Bloc 1 — eBay : drop filtres trop stricts + post-filter year applicatif

> Implémenté dans la session du 2026-05-05. Préreq : sessions S1-S3
> terminées (`sessions-overview.md`).

## Objectif

Assouplir les filtres eBay qui crashent le recall sans perdre les pièces
millésimées. Mesuré dans le probe S3 :
- `priceCurrency:EUR` à lui seul : 49 → 0 sur bearded-vulture
- `aspect_filter Année:{...}` : recall ×16-50 sur AD/FR sans coût ailleurs

## Ce qu'on change

### 1. `ml/sources/ebay/queries.py`
Drop le segment `Année:{...}` du `aspect_filter`. Garder seulement
`categoryId:32650`. L'année reste dans `q` (le post-filter eBay sur le
texte de la query continue de prioriser les listings 2025 quand la query
contient "2025").

### 2. `ml/sources/ebay/adapter.py`
Drop `filter_expr="price:[1..500],priceCurrency:EUR"` du call
`client.search`. On ne demande plus à eBay de pré-filtrer par prix ni
devise — on fait ça applicativement dans `accept_listing`.

### 3. `ml/sources/ebay/filters.py` — extension `accept_listing`
Ajouter le post-filter year-in-title pour les commémos millésimées :

- Extraire l'année du titre via regex `\b(19|20)\d{2}\b`.
- Si trouvée et différente de `coin.year` → reject (raison
  `"year_mismatch"`).
- Si **non** trouvée → **accept** (policy "accept-on-missing", évite
  d'écraser le recall sur les listings sans année dans le titre).

Filtre prix-en-EUR : conservé via `accept_listing` qui regarde
`row["price_value"]` et `row["price_currency"]`. Reject les non-EUR.
Reject prix < 1 ou > 500.

### 4. Nouvelle table `discarded_listings`
Trace les listings rejetés par `accept_listing` (avant qu'ils ne soient
ingérés). But : pouvoir auditer si un assouplissement futur
récupérerait des listings utiles.

```sql
CREATE TABLE IF NOT EXISTS discarded_listings (
  id            TEXT PRIMARY KEY,
  run_id        TEXT REFERENCES source_runs(id) ON DELETE CASCADE,
  source        TEXT NOT NULL,
  source_ref    TEXT NOT NULL,            -- item_id
  target_eurio  TEXT,
  reason        TEXT NOT NULL,             -- 'year_mismatch'|'non_eur'|'noise_title'|...
  title         TEXT,
  raw_payload   TEXT,                       -- json snapshot
  created_at    TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX idx_discarded_listings_run ON discarded_listings(run_id);
CREATE INDEX idx_discarded_listings_reason ON discarded_listings(reason);
```

## Ce qu'on ne change PAS

- `ISO2_TO_NAME_FR` : reste en place. Le probe S3 a montré que le nom
  FR matche mieux sur EBAY_FR. Multilangue → bloc 2.
- Marketplace EBAY_FR : reste hardcodé. Multi-marketplace → bloc 2.
- Limit=50 : pas de pagination ici. Pagination → bloc 3.

## Audit

```bash
# Lancer un nouveau run sur les mêmes 5 eurio_ids du probe S3
# Vérifier dans discovery_searches que n_raw_results > 0 sur bearded-vulture
sqlite3 ml/state/training.db "
  SELECT target_eurio_id, n_raw_results, n_kept_results
    FROM discovery_searches
   WHERE run_id = '<new-run-id>'
   ORDER BY created_at;"

# Inspecter discarded_listings pour valider les rejets
sqlite3 ml/state/training.db "
  SELECT reason, count(*) FROM discarded_listings
   WHERE run_id='<new-run-id>'
   GROUP BY reason;"
```

## Critères de succès

1. `bearded-vulture` retourne au moins quelques `n_raw_results > 0`
   (probablement 50, plafonné par limit).
2. `n_kept_results` reste raisonnable (post-filter year ne dégrade pas
   trop la précision sur les commémos millésimées).
3. `discarded_listings` se peuple avec des raisons cohérentes (la majorité
   `year_mismatch` ou `wrong_currency`, pas une avalanche de rejets
   massifs sur les eurio_ids historiquement bons).
