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

## Reste à faire

1. **F1 → F4** — front (pilote bandeau strat, run-detail badges,
   règles panel, coin-detail thumbs). Consommer `useMarketplaceMap.ts`
   et `useFilterConfig.ts` (à créer côté admin/web).
2. **V2** — cutover legacy : retrait `THEME_TOKEN_FR_ALIASES` +
   `_legacy_title_matches_theme` + `_theme_keywords`, smoke run sur
   10 eurio_ids, mesure recall vs baseline (KPI ≥ ×3).
4. **Optionnel** — `i18n-llm-translation` (DE/IT/ES/NL) si I2 mesure
   une perte de recall sur les marketplaces DE/IT/ES/BE-NL.
