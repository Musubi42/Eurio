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
| I (i18n) | I1 — bootstrap Numista i18n | ⏳ kickoff écrit | — |
| I | I2 — theme matcher multilingue | ⏳ | — |
| F (front) | F1 → F4 — pilote / run-detail / règles / coin-detail | ⏳ | — |
| V (validation) | V1 — probe langues + PT routing | ⏳ | — |
| V | V2 — cutover legacy | ⏳ | — |

**6/14 chunks livrés.** Toute la phase B (backend) est en place — la
chaîne multi-mkt tourne, les 2 APIs front (marketplace-map +
filter-config) sont prêtes à être consommées. Reste à brancher la i18n
(I1/I2) et le front (F1-F4) puis valider/cutover (V1/V2).

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

## Reste à faire

1. **I1** (bootstrap Numista i18n) — session dédiée. Scope verrouillé
   2026-05-19 : scrape HTML 9 langues, ~578 coins, ~1h27 de run, 0
   quota API. Kickoff complet : `i18n-bootstrap-kickoff.md`.
2. **I2** — refacto theme matcher (cf. `language-probe.md` §"Étape 2bis"
   — stop-words par langue, extraction depuis titre Numista localisé,
   `MARKETPLACE_ACTIVE_LANGS`).
3. **F1 → F4** — front (pilote bandeau strat, run-detail badges,
   règles panel, coin-detail thumbs). Consommer `useMarketplaceMap.ts`
   et `useFilterConfig.ts` (à créer côté admin/web).
4. **V1** — probe langues marketplaces, **inclut décision PT routing**
   (cf. `marketplace-map.md` §"Routage PT provisoire" — TODO en code).
5. **V2** — cutover legacy : retrait `THEME_TOKEN_FR_ALIASES`, smoke
   run sur 10 eurio_ids, mesure recall vs baseline (KPI ≥ ×3).
