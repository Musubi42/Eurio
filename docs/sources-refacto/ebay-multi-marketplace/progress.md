# Progress — eBay multi-marketplace

Overview de l'avancement chunk-par-chunk. Mis à jour à chaque livraison.

## État global

| Phase | Chunk | Statut | Commit |
|---|---|---|---|
| B (back) | B1 — schema migrations + i18n table | ✅ done | `5ebc9a0` |
| B | B2 — marketplace map module | ✅ done | `ed421a1` |
| B | B3 — EbayClient marketplace-param | ✅ done | `ed421a1` |
| B | B4 — adapter discover multi-call | ✅ done | `2c290d3` |
| B | B5 — API `/marketplace-map` | ✅ done | (pending) |
| B | B6 — API `/filter-config` | ✅ done | (pending) |
| I (i18n) | I1 — bootstrap Numista i18n (FR+EN) | ✅ done | (pending) |
| I | I2 — theme matcher multilingue | ✅ done | (pending) |
| F (front) | F1 → F4 — pilote / run-detail / règles / coin-detail | ⏳ | — |
| V (validation) | V1 — probe langues + PT routing | ✅ done | (pending) |
| I | I3 — traduction LLM DE/IT/ES/NL (112 coins) | ✅ done | (pending) |
| V | V2 — cutover legacy | ⏳ | — |

**9/14 chunks livrés.** Toute la phase B (backend) est en place — la
chaîne multi-mkt tourne, les 2 APIs front (marketplace-map +
filter-config) sont prêtes à être consommées. **I1 + I2 + V1 livrés** :
~1016 titres FR+EN scraped via TOR + importés en DB, le matcher theme
branché dessus en multilingue, et le probe langues marketplaces a
calibré `MARKETPLACE_ACTIVE_LANGS` + tranché le routing PT. Reste le
front (F1-F4) puis le cutover legacy (V2). Les 4 langues restantes
(de/it/es/nl) viendront via LLM batch (chunk séparé
`i18n-llm-translation.md`) si la mesure de recall le justifie.

## Ce qui fonctionne

- **Migrations idempotentes** sur DB neuve et DB existante. Validé sur
  copie de `training.db` (558 + 32 + 1102 rows préservées, colonnes
  `marketplace*` rajoutées sans casse).
- **Routage explicite** : `route_for(country)` couvre les 21 pays
  eurozone + AD/MC/SM/VA + `'eu'` joint. `UnknownCountry` levé sur
  pays absent du dict — pas de fallback silencieux.
- **`EbayClient` paramétrique** avec `marketplace` keyword-only,
  `Accept-Language` câblé (était manquant avant), `SUPPORTED_MARKETPLACES`
  validé à l'init.
- **`EbayAdapter.discover()` multi-call** :
  - 1 call si GB-only, 2 calls si primary + GB.
  - Query construite dans la langue native du marketplace (FR/EN/DE/IT/ES/NL).
  - Merge en RAM par `item_id` : `marketplace` = first-seen,
    `marketplace_found` = set complet. Pas de `ON CONFLICT DO UPDATE`.
  - `record_search` / `record_discarded` tagués par marketplace → 1 row
    `discovery_searches` par (eurio × mkt), 1 row `discarded_listings`
    par rejet avec le mkt d'origine.
  - Échec d'1 mkt ne casse pas l'autre (log warning + continue).
- **Tests** : 75/75 verts sur scope eBay (adapter, queries, filters,
  client, storage, run-breakdown, bootstrap_coins, API B5/B6).
- **APIs front** : `GET /sources/ebay/marketplace-map` sérialise le
  routage canonique (26 entrées). `GET /sources/ebay/filter-config`
  reflète les constantes de `filters.py` (7 règles : 6 reject + 1 flag)
  avec valeurs `threshold` / `pattern` / `policy` lues runtime, pas
  hardcodées côté API → si quelqu'un modifie `filters.py`, la réponse
  bouge sans toucher au front.

## Décisions actées en cours de route

- **Cache de clients par mkt** intra-adapter (`_client_cache`) pour
  éviter de re-créer les `httpx.Client` à chaque eurio_id d'un batch.
- **`item/{id}` HD tiré via le client du first_mkt** : l'`item_id` étant
  stable cross-mkt, le détail est identique — pas la peine de complexifier
  avec un routage dédié.
- **`marketplace_found` figé au first-insert** (COALESCE en UPDATE) :
  V1 ne gère pas le merge cross-run, seulement intra-run. Suffisant pour
  le besoin admin actuel ; cross-run élargi en V2 si nécessaire.
- **Mock de test sticky sur la dernière response** : permet aux tests
  legacy single-mkt de passer sans modif des fixtures (la 2nd mkt voit
  les mêmes items → merge dedup → résultat unchanged).

## Problèmes rencontrés

- **`eurio.db` est vide** (0 byte) ; la vraie DB locale est `training.db`.
  Confusion potentielle pour onboarding future. À adresser hors B-chunks.
- **`scrape_ebay.py` (legacy)** instancie encore `EbayClient` en
  EBAY_FR hardcoded. Listé pour cleanup V2.
- **Test pré-existant cassé** (`test_augmentation::test_list_layer_schemas`)
  hors-scope du chantier — `background` layer ajouté sans update du test.
  Non bloquant pour B4.

## I1 livré (2026-05-20)

Pivot vs kickoff initial (qui visait 9 langues via sous-domaines) :
la probe `i18n-probe.md` a montré que **seuls FR et EN sont vraiment
traduits** par Numista. Les autres sous-domaines servent l'UI traduite
mais conservent le titre EN. Stratégie refondue dans `i18n-strategy.md` :

- **FR + EN scraped** via TOR (ce chunk) → `confidence='canon'`
- **DE/IT/ES/NL via LLM** (chunk séparé `i18n-llm-translation.md`,
  pas livré) → `confidence='llm'`

Architecture livrée (cf. `i18n-scrape-numista.md` à jour) :

- **TOR proxy Docker** : `ml/infrastructure/tor/{torrc,docker-compose.yml}`,
  pattern `IsolateSOCKSAuth` (1 circuit par username SOCKS5, rotation
  par bump du suffixe `_b`)
- **3 scripts, 2 machines** (VPS stateless ML-wise) :
  - `export_i18n_worklist.py` (PC) → `state/i18n_worklist.json`
  - `bootstrap_coin_names_i18n.py` (VPS, modes `--poc` et full)
    → `state/i18n_{results,failures}.jsonl` append-only
  - `import_i18n_results.py` (PC) → `coin_names_i18n` via
    `INSERT OR IGNORE`
- **Schema étendu** : `coin_names_i18n` gagne `confidence` (`'canon'`/
  `'llm'`/`'manual'`) + `model` (TEXT, NULL pour canon). Migration
  additive via `_ensure_column` (pas de recreate-and-copy).
- **Résilience burnt-circuit** : rotation immédiate du username +
  1 retry sur 403/429/5xx/challenge. Skip-set basé uniquement sur
  `results.jsonl` → les failures sont re-tentées au prochain run.

Run réel : ~58 min en background nohup, couverture ~95% en 1 run,
~100% après 1 relance sur les failures (TOR circuits rafraîchis).

## I2 livré (2026-05-20)

Theme matcher multilingue branché sur `coin_names_i18n` (508 FR +
508 EN importés depuis `i18n_results.jsonl`).

Architecture livrée :

- **Module `ml/sources/ebay/theme_tokens.py`** : `STOP_WORDS_BY_LANG`
  (6 langues), `COUNTRY_TOKENS_BY_LANG` (25 pays × 6 langues),
  `normalize` (NFKD drop-accents), `extract_tokens`, `load_i18n_title`.
- **`MARKETPLACE_ACTIVE_LANGS`** dans `marketplaces.py` : langues à
  matcher par marketplace (distinct de `query_lang`).
- **`title_matches_theme(title, eurio_id, *, marketplace, conn)`** :
  nouvelle signature, boucle sur les langues actives, charge le titre
  Numista localisé, matche les tokens discriminants. Permissif quand
  i18n présent mais 0 token (standards). Fallback `_legacy_title_matches_theme`
  (ancien matcher renommé) quand aucun titre i18n trouvé — deprecated,
  retiré en V2.
- **Plomberie `adapter.py`** : `_search_and_expand` reçoit `eurio_id`
  + `marketplace`, le matcher utilise `self.conn`.
- **Tests** : 82 verts sur scope eBay (75 baseline + 7 intégration
  matcher). Anciens tests sur la signature legacy renommés `_legacy_*`.

Validation empirique :

- **Stop-words** (`scripts/probe_i18n_tokens.py`) : médiane tokens
  utiles = 2.0 sur FR et EN, dans la cible [2,6]. Pas de tuning requis.
- **Smoke recall** (`scripts/probe_i18n_recall.py`) : rejoué sur les
  921 listings `theme_mismatch` rejetés par le matcher legacy →
  **105 recover** (11%), tous vrais positifs à l'audit visuel (titres
  FR sellers que le slug EN ne traduisait pas : "Nouvelle Réforme",
  "Pays des Pyrénées", "Gypaète", "Jeux des Petits États", etc.).
  Baseline legacy sur cet échantillon = 0 par construction.

### Limite connue — thèmes courts (< 4 chars)

2 coins sur 508 ont un thème FR qui tient en un mot < 4 lettres :
`ad-2023-…UN` ("ONU") et `ad-2024-…skiing` ("Ski"). `extract_tokens`
les drop via `min_len=4` → 0 token FR. Le token EN (`admission`,
`skiing`) ne matche pas les titres FR sellers → faux négatifs
résiduels. Choix V1 : **ne pas baisser `min_len`** (risque de faux
positifs type "war"⊂"warm" sur 506 autres coins). Documenté, à
reconsidérer en V2 si la perte de recall est jugée significative
(min_len adaptatif possible).

## V1 livré (2026-05-20)

Probe empirique des langues de titres par marketplace + décision PT.

Script `scripts/probe_marketplace_languages.py` (jetable) : 8 commémos
circulées × 9 marketplaces, ~3500 titres tirés, ~74 calls eBay.

- **Détection de langue** : `langdetect` essayé puis **abandonné** — il
  smear systématiquement IT/ES vers `pt` sur les titres courts en
  majuscules (FRANCIA, EURO, FDC, COINCARD). Remplacé par un classifieur
  heuristique maison (mots-marqueurs numismatiques + noms de pays
  distinctifs + function-words). Le JSON embarque tous les titres bruts
  → mode `--reclassify` pour itérer le classifieur sans re-taper l'API.
- **Piège écarté** : `UNC`/`BU`/`FDC`/`COINCARD` sont du boilerplate
  international — les inclure comme marqueurs EN gonflait le bucket `en`
  de titres FR/IT évidents. Retirés.
- **Résultat** `MARKETPLACE_ACTIVE_LANGS` recalibré :
  - `EBAY_ES` → `+it` (vendeurs IT cross-listent, ~19 % des titres)
  - `EBAY_IE` → `+it` (~16 %)
  - `EBAY_NL` → `+fr` (DOMINANT ~44 %, eBay.nl est Benelux) `+it` (~14 %)
  - `en` conservé partout (sous-détecté par le classifieur, coût ≈ 0).
- **Routing PT** : recall `total` eBay = ES 608 / GB 362 = **1.68×**
  (stable sur 5 runs), sous le seuil ×2 → `route_for("PT")` repasse en
  `primary=None` (GB-only). Cf. `marketplace-map.md` §"Routage PT".

Caveat : `unknown` reste 25-45 % (titres bruts non-discriminants type
"2 EURO FRANCIA 2022"). Les pourcentages d'actives sont calculés sur le
sous-ensemble classé — suffisant pour le seuil 10 %.

Findings consolidés → `research/marketplace-language-distribution.md`.

## F1-F2 livrés (2026-05-20)

Surfaces front-ux.md :
- **F1** — bandeau "Stratégie d'extraction" dans le pilote eBay
  (`EbayPilotPanel`) : composable `useMarketplaceMap` (B5), coût quota
  moyen calculé live, modal table de routage, badges marketplace.
- **F2** — colonne `Mkts` dans le run breakdown : `MarketplaceBadge.vue`
  (drapeau SVG en fond + scrim + code), backend `RunBreakdownEntry.marketplaces`.

Reste **F3** (run listings — discovery searches enrichies + panel
règles) et **F4** (coin-detail — badge marketplace par thumb).

## Benchmark routing marketplace — concluant (2026-05-20/21)

Probe empirique : quel marketplace maximise le recall par pays
d'origine ? Itération 3 (theme-match réactivé, débloquée par I3) →
**concluant**. Findings + matrice 24×9 →
`research/marketplace-routing-benchmark.md` §Itération 3.

**Décision actée (2026-05-21)** : routage **uniforme** `{EBAY_DE,
EBAY_ES}` pour toutes les origines (DE primary query `de`, ES second
query `es`). Plus de table per-origine, `EBAY_GB` retiré (0 listing
EUR exploitable). Le marketplace est un canal de découverte (dédup par
`item_id`), pas un segment — `{DE,ES}` est le top-2 mesuré sur ~22/24
origines.

→ Implémenté (chunk **C0**) : `marketplaces.py` simplifié
(`DISCOVERY_MARKETPLACES` + `discovery_marketplaces()`, suppression de
`_ROUTES`/`route_for`/`MarketplaceRoute`/`UnknownCountry`), `adapter.py`
+ B5 API + front pilote (`useMarketplaceMap`, modal, bandeau) alignés.
81 tests eBay/marketplace verts.

## I3 livré (2026-05-20)

Traduction LLM DE/IT/ES/NL des 112 coins du benchmark, faite par
Claude Code lui-même en un go (4 agents parallèles + rattrapage +
review). Cf. `i18n-llm-translation.md` §Done.

- **448 lignes** dans `ml/state/i18n_llm_results.jsonl`,
  `import_llm_translations` → `coin_names_i18n` (112 rows `llm_v1`
  par lang de/it/es/nl).
- **0 % uncertain** ; audit qualité par agent de review → verdict OK,
  aucune hallucination, 1 ajustement stylistique nl appliqué.
- 2 anomalies remontées côté worklist (typo `title_en` `ee-2022`,
  `title_fr` non traduit `hr-2025-pula`) — hors périmètre, n'affectent
  pas l'import.

## V2 — cutover legacy livré (2026-05-21)

Retrait du matcher theme legacy maintenant que le matcher multilingue I2
(`coin_names_i18n`, couverture ~100 % après I1+I3) est validé :

- `queries.py` : suppression de `THEME_TOKEN_FR_ALIASES`,
  `_legacy_title_matches_theme`, `_theme_keywords`, `STOP_WORDS`,
  `COUNTRY_SLUG_TOKENS`, et du champ `EbayQuery.theme_tokens`.
- `title_matches_theme` : le fallback legacy (slug EN + aliases FR)
  est remplacé par un **retour permissif `True`** quand aucun titre
  i18n n'est disponible — sans titre localisé, on ne peut pas
  theme-matcher, on ne filtre donc pas le listing.
- `adapter.py` : `theme_tokens` retiré des métadonnées `filters_meta`
  et `raw_payload` des `discovery_searches`/`discarded_listings`.
- Tests : suppression des tests legacy, `test_discover_ambiguous_*`
  re-seedé avec un titre `coin_names_i18n` (le theme-match s'appuie
  désormais sur l'i18n, plus sur les tokens de slug). 98 tests
  eBay/marketplace/pricing verts, 0 régression.

**Reste empirique** : un smoke run réel (10 eurio_ids, recall vs
baseline) reste à faire pour confirmer que la couverture i18n est
assez haute pour que le retrait du fallback ne coûte pas de recall —
c'est un run eBay (quota), à faire avec un run discovery réel.

## Découverte groupée — chunks 1-6 livrés (2026-05-22)

Bascule de la maille de découverte : `(dénom, pays, année)` au lieu de
`eurio_id`. Une recherche eBay ramène toutes les commémos-sœurs d'un
groupe ; chaque listing est attribué à sa pièce par le theme-match
multilingue. L'`eurio_id` reste la maille de stockage / review / prix.
Motivation : `build_query` ne tenait pas compte du thème → deux sœurs
de la même année déclenchaient deux requêtes byte-identiques et le
post-filtre `theme_mismatch` jetait les listings de la sœur non ciblée
(149 faux rejets sur un run mesuré).

- **Chunks 1-3** — cœur backend (`DiscoveryGroup`, `match_listing_to_group`
  routeur 4 verdicts, `build_group_query`), vue `v_ebay_freshness_groups`
  + endpoints `freshness-groups` / `run-preview`, quota group-aware,
  front `EbayPilotPanel` groupé.
- **Chunk 4** (`cc25c01`) — run-detail : retry des téléchargements
  échoués (`resume_failed_downloads`), `zero_crops` n'est plus une
  erreur, breakdown relu pour runs groupés, panneau « Règles de
  filtrage ».
- **Chunk 5** (`d3a149e`) — review : relabel « Cible eBay » → « Pièce
  proposée », candidats du groupe sélectionnables pour les listings sans
  proposition (verdict ambigu).
- **Commit différé** (`2c515db`) — décisions review POSTées après une
  fenêtre undo de 10 s (fix re-décision 409).
- **Chunk 6** — `v_ebay_freshness` devient la projection per-eurio_id de
  `v_ebay_freshness_groups` (cohérence des deux vues) ; docstrings
  « cible eBay » alignées sur la sémantique theme-match. Détail dans
  `discovery-groupee-handoff.md`.

## Reste à faire

1. **F3 → F4** — front (run listings, coin-detail thumbs).
2. **Smoke run V2** — discovery réel sur 10 eurio_ids, recall vs baseline.
3. **Pipeline prix & état** (plan C0-C4) :
   - **C0** routing `{DE,ES}` — ✅ livré.
   - **C1** migration + taxonomie — ✅ livré : colonnes `listing_origin_date`
     + `sold_qty` (source_images, vélocité), `listing_kind`
     (single/lot/coffret/graded_slab) + `condition_normalized`
     (UNC/TTB/TB) + confidences (listing_text_signals). Migrations
     additives idempotentes, CHECK sur `listing_kind`. `is_lot_suspected`
     conservé tant que `listing_kind` n'est pas peuplé (C2) — retrait
     une fois les consommateurs (lot review) migrés.
   - **C2** extraction signaux — ✅ livré : l'extracteur `text_signals`
     produit `listing_kind` (graded_slab > lot > coffret > single) +
     `condition` (UNC/TTB/TB, défaut UNC faible confiance) + confiances.
     Dictionnaires multilingues fr/en/de/es/it. `EXTRACTOR_VERSION` v1→v2
     (force la ré-extraction). 28 tests extracteur + step `discarded`
     fixture resync (drift B1 corrigé).
   - **C3** agrégation prix — ✅ livré : module pur `sources/pricing`
     (pondération vélocité = récence × bonus ventes, percentiles
     p10/p50/p90 pondérés, nettoyage outliers ±×4) + step
     `price_aggregate` (filtre `listing_kind='single'`, dédup par
     listing, écrit `coin_market_quotes` une ligne par coin×tier×période).
     Câblé en step 9 de l'orchestrateur → un snapshot prix par run,
     l'historique s'accumule. 17 tests.
     - **Fixes audit run 85bd…** (2026-05-21) : `MIN_SAMPLES_FOR_OUTLIER`
       4→3 (la médiane à n=3 résiste à un outlier unique) ; garde-fou
       inter-tier `MAX_TIER_RATIO_VS_UNC=3.0` (un TTB/TB au p50 > 3× le
       p50 UNC = échantillon contaminé → quote supprimée — tuait le cas
       `be-2008 TB p50=222€`) ; le step écrit `n_quotes_added` sur
       `source_runs` (colonne QUOTES du run-detail).
   - **C4** upgrade review — ✅ livré.
     - **C4a** backend : payload `ReviewItem` enrichi (kind/condition/âge),
       `GET /sources/ebay/market-quotes` (prix réf par tier), `POST
       /review-queue/{id}/correct-listing` (propage à tout le listing,
       marque `extractor_version='manual'`). Garde-fou : le step C2
       skippe les rows `'manual'` même en `force`. 11 tests.
     - **C4b** front : composant `ListingContextCard.vue` (carte
       « Listing & marché » — badges type/état + confiance, ambre si
       faible confiance, ligne marché + anomalie prix). Touches `K`/`C`
       (cycle, opt-in) dans `useReviewKeybinds`, prefetch des quotes
       marché des candidats. `⏎` d'attribution inchangé.
