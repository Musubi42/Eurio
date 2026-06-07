# Sources / scraping — overview multi-sessions

> Index vivant des chantiers menés sur la pipeline sources & scraping.
> Lis ce fichier d'abord pour ré-attraper le fil après un trou. Il pointe
> vers les kickoffs détaillés sans tout reproduire.

## Ce qui est fait

### S1 — Page debug per-listing dans `sources/:id/runs/:run_id`
**Statut** : livré (2026-05-04). Doc : `listing-debug-view-kickoff.md`.

- 9 colonnes ajoutées sur `source_images` : `download_endpoint`, `download_status`,
  `download_error`, `download_http_status`, `crop_status`, `crop_error`,
  `n_crops_detected`, `route_decision`, `route_reason`.
- Steps 3 (download), 4 (detect_crop), 6 (enqueue) instrumentés pour écrire
  ces colonnes.
- Endpoint `GET /sources/:id/runs/:run_id/listings?eurio_id=…`.
- Page Vue.js `SourceRunListingsPage.vue` avec cards verticales,
  thumb du raw, badges de décision, mini-thumbs des crops, trace dépliable.
- Clic sur une ligne du breakdown agrégé → vue listings filtrée par eurio_id.

### S2 — Logging des appels `discover()` (Discovery Searches)
**Statut** : livré (2026-05-04). Doc : `listing-debug-view-kickoff.md` (ajouts).

- Nouvelle table `discovery_searches` : 1 row par appel logique
  `adapter.discover()` pour un (run, target_eurio_id). Colonnes :
  `endpoint`, `query_q`, `query_filters_json`, `status`, `http_status`,
  `n_raw_results`, `n_kept_results`, `duration_ms`, `error`.
- Contrat `SourceAdapter.discover()` étendu : accepte un callback
  `record_search` optionnel.
- eBay adapter instrumenté : mesure durée, capture `httpx.HTTPStatusError`,
  log success/empty/failed avec compteurs.
- Endpoint `GET /sources/:id/runs/:run_id/searches?eurio_id=…`.
- Section collapsible "Discovery searches" sur la page listings.
- Permet désormais de distinguer "vraiment 0 résultat" vs "scrape pas
  exécuté / failed / post-filter trop strict".

### S3 — A/B probe des stratégies de query eBay
**Statut** : livré (2026-05-04). Script : `ml/scripts/probe_ebay_query_strategies.py`.

- 5 eurio_ids × 6 variantes (FR vs EN country name, year aspect on/off,
  theme tokens dans `q`, marketplace EBAY_FR/GB/DE).
- Dump JSON dans `ml/state/probe_ebay_query_strategies_<ts>.json`.
- Tableau récap stdout.
- Conclusions tirées :
  - **Garder le nom de pays FR** dans `q` sur EBAY_FR (les chiffres infirment
    "anglais partout" — Belgique > Belgium ×12, Allemagne > Germany ×60).
  - **Drop l'aspect `Année:{...}`** dans `aspect_filter` (gain ×16-50 sur
    AD/FR sans coût ailleurs).
  - **V4 theme-tokens-in-q est mort** (=0 partout, eBay search trop strict).
  - **EBAY_GB est un meta-marketplace** intéressant (+90× SK, +400× DE)
    mais bruité ; à utiliser comme marketplace **par défaut + spécialisé pays**.
  - **Le filtre `priceCurrency:EUR` à lui seul tue 49→0** sur
    bearded-vulture. Trop strict pour beaucoup de listings sur EBAY_FR.

### S4 — Bloc 1 : assouplissement des filtres + post-filter year
**Statut** : livré (2026-05-05). Doc : `ebay-postfilter-year-kickoff.md`
(ce qu'on fait dans la session courante).

- Drop l'aspect Année du `aspect_filter` eBay.
- Drop le `filter_expr=priceCurrency:EUR`.
- Ajouter post-filter applicatif year-in-title (regex `\b(19|20)\d{2}\b`)
  policy *accept-on-missing*.
- Nouvelle table `discarded_listings` (audit trail des rejets, récupérable
  plus tard).

## Ce qu'il reste à faire (futur, non commencé)

### Bloc 2 — Multi-marketplace + i18n + prix manuel review lot
Doc : `ebay-strategy-v2-kickoff.md`.

Résumé :
- Bootstrap noms multilingues depuis Numista (FR/EN/DE/IT/ES) → table
  `coin_names_i18n` ou colonne `coins.names_i18n_json`.
- Switch marketplace par défaut sur EBAY_GB (+ EBAY_<country_origin> en
  enrichissement). Config par-pays plutôt que constante hardcodée.
- API `decide_lot_with_price` (back) : permettre de saisir un prix par crop
  lors du review d'un lot. Préparer le terrain pour le futur front.

### Bloc 3 — Pagination + front review lot price
Doc : `ebay-strategy-v3-kickoff.md`.

Résumé :
- Pagination Browse API > 50 (offset jusqu'à 200, heuristique
  d'arrêt-précision).
- Front lot review : input prix par crop dans le drawer.
- Décision sur les pièces standards millésimées (un eurio_id par
  millésime ou un seul partagé ?). Pas tranché.

## Pivots / changements de cap

- **Anglais partout dans la query** : envisagé en S3 puis abandonné — les
  données prouvent que sur EBAY_FR le nom FR matche mieux. La piste
  multilingue passe par i18n des **theme tokens** (post-filter), pas par
  réécriture de la query.
- **Backfill des nouvelles colonnes** sur les anciens runs : volontairement
  abandonné depuis S1. On instrumente l'avenir, pas le passé.
- **Theme tokens dans `q`** (V4 du probe) : éliminé, recall=0.
