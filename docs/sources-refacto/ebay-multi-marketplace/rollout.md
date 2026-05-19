# Rollout — découpage en chunks

> Plan d'exécution chunk-par-chunk avec dépendances et critères de
> validation. Convention `feedback_chunk_audit_flow` : on livre 1 chunk
> (30 min - 3 h), on attend la rétro user, on enchaîne. Pas d'auto-pilot
> multi-chunks.

## Vue d'ensemble — graphe de dépendances

```
  [B1] Schema migrations
        │
        ├──────────────────────────────────────┐
        ▼                                       ▼
  [B2] Marketplace map module           [I1] Bootstrap Numista i18n
        │                                       │
        ▼                                       ▼
  [B3] EbayClient marketplace-param      [I2] Theme matcher multilingue
        │                                       │
        └─────────────────┬─────────────────────┘
                          ▼
                 [B4] Adapter discover multi-call
                          │
                          ├─────────────────────┐
                          ▼                     ▼
              [B5] API /marketplace-map   [B6] API /filter-config
                          │                     │
                          ▼                     │
              [F1] Pilote bandeau strat        │
                          │                     │
                          ▼                     ▼
              [F2] Run-detail badges mkts  [F3] Run-listings règles panel
                          │
                          ▼
              [F4] Coin-detail badges
                          │
                          ▼
                  [V1] Probe langues
                          │
                          ▼
                  [V2] Cutover legacy → multi-mkt
```

## Phase B — Backend pipeline

### Chunk B1 — Schema migrations

**Scope** : ajouter `marketplace` sur `source_images`, `discovery_searches`
**et `discarded_listings`** (utilisé par front-ux §3.C, donc pas
optionnel), créer `coin_names_i18n`, ajouter `_ensure_column` helper.
Inclut `marketplace_found_json` sur `source_images`.

**Fichiers** :
- `ml/state/schema.sql` (DDL idempotente, 3 `ALTER TABLE` + 1 `CREATE TABLE`)
- `ml/state/store.py` ou équivalent — appel `_ensure_column` post-bootstrap

**Tests** :
- Lancer `Store(...)` sur DB neuve → tables présentes.
- Lancer sur DB existante (un dump pre-chantier) → no error, colonnes
  ajoutées, rows existants intacts.
- Insertion `source_images` sans marketplace → OK (nullable).
- Insertion avec marketplace → OK, lisible.

**Critère validation** : `pytest tests/test_storage_migration.py`
(à créer si absent) passe. Pas de side-effect sur runs existants.

**Durée estimée** : 1 h.

---

### Chunk B2 — Marketplace map module

**Scope** : créer `ml/sources/ebay/marketplaces.py` avec `MarketplaceRoute`
dataclass + `route_for(country)`. Pas de modif d'autres fichiers.

**Fichiers** : 1 nouveau fichier, ~80 lignes (dict + helper + 1 test
unit).

**Tests** :
- `test_route_for_native_marketplace` (FR→FR+GB, DE→DE+GB, …)
- `test_route_for_lang_fallback` (LU→FR+GB, AD→ES+GB, …)
- `test_route_for_gb_only` (BG→GB seul, eu→GB seul, …)
- `test_route_for_unknown_country_raises` (XX → ValueError)

**Critère** : 21 pays eurozone + 'eu' tous mappés explicitement. Pas
de fallback "if country not in dict → GB" silencieux. Tous les pays
inconnus lèvent une exception explicite.

**Durée estimée** : 1 h.

---

### Chunk B3 — EbayClient marketplace-paramétrique

**Scope** : retirer `MARKETPLACE = "EBAY_FR"` hardcoded. Passer le
marketplace + accept-language au constructeur. Ajouter `Accept-Language`
header (manquant aujourd'hui).

**Fichiers** :
- `ml/market/ebay_client.py` — refacto `__init__`
- Tests `tests/test_ebay_api.py`, `tests/test_ebay.py`, etc. — adapter
  les mocks pour le nouveau constructeur

**Callers à mettre à jour** (signature breakage assumé) :
- `ml/api/sources_routes.py:64`
- `ml/sources/cli.py:48`
- `ml/market/scrape_ebay.py:567` (legacy — soit on patche, soit on
  marque comme à supprimer dans le cleanup V2 ; à trancher au moment
  du chunk, mais **listé ici** pour ne pas l'oublier).

`EbayClient(token)` sans paramètre marketplace = error explicite (pas
de défaut FR silencieux — la dette c'est exactement ça).

**Critère** : tests passent, `EbayClient(token, marketplace='EBAY_DE')`
envoie le bon header `X-EBAY-C-MARKETPLACE-ID: EBAY_DE` + `Accept-Language: de-DE`.

**Durée estimée** : 1.5 h.

---

### Chunk B4 — Adapter discover multi-call

**Scope** : `EbayAdapter.discover()` fait 2 calls (primary + GB —
séquentiel V1, parallélisation deferred), **merge en mémoire** des
résultats par item_id avant yield, persiste 2 rows `discovery_searches`,
yield les `DiscoveredItem` avec `marketplace` (premier mkt qui a vu
l'item) + `marketplace_found` (liste complète). Le step persist remplit
ensuite `source_images.marketplace` + `marketplace_found_json` en **1
seule INSERT par item_id**.

**Stratégie de merge** (rappel `schema.md` §"Stratégie d'écriture") :

```python
# Pseudo
seen: dict[str, MergedItem] = {}  # item_id → (first_mkt, set[mkts], row)
for mkt in [route.primary, route.global_]:  # ordre primary→GB
    if mkt is None: continue
    for row in self._search_and_expand(mkt):
        if row.item_id not in seen:
            seen[row.item_id] = MergedItem(first=mkt, found={mkt}, row=row)
        else:
            seen[row.item_id].found.add(mkt)
# Yield 1 DiscoveredItem par item_id, avec marketplace_found = sorted(found)
```

Pas d'`ON CONFLICT DO UPDATE` côté SQLite — la dédup vit en RAM.

**Fichiers** :
- `ml/sources/ebay/adapter.py` — refacto `_search_and_expand` en double
  call, dedup, fusion
- `ml/sources/ebay/queries.py` — `build_query(coin, marketplace)` accepte
  marketplace pour choisir la map ISO2_TO_NAME_{FR,EN,DE,IT,ES,NL}
- `ml/sources/_base/steps/discover.py` — propager le marketplace dans
  les rows persistées
- `ml/sources/ebay/__init__.py` — fix imports si refacto

**Tests** :
- `test_discover_two_marketplaces` (FR coin → 2 rows searches + dedup
  vérifié sur item_id partagé).
- `test_discover_gb_only` (BG coin → 1 row search EBAY_GB).
- `test_discover_dedup_overlap` (mock 2 réponses avec 3 items partagés →
  source_images = 3 rows uniques, marketplace_found_json contient
  les 2 mkts pour les 3 items).
- `test_discover_query_lang_per_marketplace` (DE coin sur EBAY_DE →
  query "2 euro Deutschland 2024" ; sur EBAY_GB → "2 euro Germany 2024").

**Critère** : 1 run dry sur un eurio_id de test produit exactement 2
rows `discovery_searches` (ou 1 si GB-only), avec funnel cohérent.

**Durée estimée** : 3 h. Le plus gros chunk back.

---

### Chunk B5 — API `/sources/ebay/marketplace-map`

**Scope** : nouvelle route FastAPI qui expose le contenu de
`ml/sources/ebay/marketplaces.py` (le dict serialisé en JSON) pour le
front.

**Fichiers** :
- `ml/api/sources_routes.py` — ajouter la route
- composable côté front : nouveau fichier `useMarketplaceMap.ts`

**Critère** : `curl localhost:8042/sources/ebay/marketplace-map` renvoie
le JSON complet de la map, avec `coin_country → {primary, global,
query_lang}` pour les 22 entries.

**Durée estimée** : 30 min.

---

### Chunk B6 — API `/sources/ebay/filter-config`

**Scope** : route qui réflexionne le contenu de
`ml/sources/ebay/filters.py` pour exposer NOISE_PATTERNS, LOT_PATTERNS
(string), seuils `FACE_VALUE_FACTOR_{LOW,HIGH}`, `YEAR_IN_TITLE_RE`,
policy year. Sert au panel "Règles actives".

**Fichiers** :
- `ml/api/sources_routes.py` — route + sérialisation regex en string
- composable côté front : `useFilterConfig.ts`

**Critère** : payload JSON consommable par le front (regex en string
human-readable, seuils numériques, descriptions courtes par règle).

**Durée estimée** : 1 h.

---

## Phase I — i18n

### Chunk I1 — Bootstrap Numista i18n

**Scope** : script `ml/scripts/bootstrap_coin_names_i18n.py` qui scrape
les 6 sub-domains Numista pour les ~3000 coins ciblés. Lancement unique,
~3-4 h.

**Fichiers** :
- `ml/scripts/bootstrap_coin_names_i18n.py` (nouveau)
- `Taskfile.yml` — ajouter `ml:bootstrap-coin-names-i18n` task

**Tests** :
- Unit test sur le parsing HTML (mock 1 page Numista, vérifier extraction `<h1>`).
- Test idempotence : 2 runs successifs ne dupliquent pas les rows.

**Critère** :
- Run terminé sans erreur sur 3000 coins.
- Coverage ≥ 80 % par langue (cf. `language-probe.md` §"Critère de succès").

**Durée estimée** : 2 h (code) + 4 h (run sans intervention).

---

### Chunk I2 — Theme matcher multilingue

**Scope** : refacto `title_matches_theme()` pour consommer
`coin_names_i18n` selon les langues actives du marketplace courant.
Déprécation de `THEME_TOKEN_FR_ALIASES`.

**Fichiers** :
- `ml/sources/ebay/queries.py` — refacto matcher, dict statique
  `MARKETPLACE_ACTIVE_LANGS` (provisoirement câblé avec les langues
  prédites en `language-probe.md` §"Critère d'arbitrage")
- Tests `tests/test_ebay_*.py` adaptés

**Tests** :
- `test_matches_fr_token_on_ebay_fr` (titre FR contient le token FR → match)
- `test_matches_de_token_on_ebay_de` (idem DE)
- `test_matches_en_token_on_ebay_gb_with_de_seller` (titre DE sur GB,
  GB a "de" dans active_langs → match)
- `test_no_match_when_no_token` (titre random sans aucun token → no match)
- `test_legacy_compat` (un coin sans i18n bootstrappé → fallback FR
  hardcoded, no crash)

**Critère** : matcher convertit l'eurio_id `bearded-vulture` sur EBAY_DE
en match sur "Bartgeier" / sur EBAY_ES sur "Quebrantahuesos".

**Durée estimée** : 2 h.

---

## Phase F — Front

Toutes les surfaces front sont décrites dans `front-ux.md`. Le découpage
suit cette spec : 1 chunk = 1 surface.

### Chunk F1 — Pilote bandeau stratégie

**Scope** : ajouter le bandeau "Stratégie d'extraction" + modal table
complète + tag `[FR][GB]` dans preview batch.

**Fichiers** :
- `admin/.../components/EbayPilotPanel.vue`
- nouveau `MarketplaceStrategyModal.vue`
- consomme `useMarketplaceMap.ts` (B5)

**Critère** : visible sur `/sources/ebay`, tooltip OK, modal s'ouvre,
table affichée.

**Durée estimée** : 2 h.

---

### Chunk F2 — Run-detail colonne marketplace badges

**Scope** : ajouter colonne `Mkts` dans `SourceRunDetailPage.vue` table
avec badges par eurio_id.

**Fichiers** :
- `admin/.../pages/SourceRunDetailPage.vue`
- composable `useRunBreakdown.ts` — étendre type pour `marketplaces`
- API : agrég côté `ml/api/sources_aggregator.py` (déjà builder du
  breakdown — ajouter sub-query sur `source_images.marketplace`)

**Critère** : badges visibles, palette cohérente, tooltip "N depuis EBAY_X".

**Durée estimée** : 2 h.

---

### Chunk F3 — Run-listings : règles panel + searches enrichies

**Scope** :
- Section "Discovery searches" : afficher 1 row par (eurio × mkt),
  payload étendu (marketplace, accept_language, browse_url).
- Bouton "Règles actives" → drawer/modal listant NOISE_PATTERNS, seuils,
  policy year, stats run par règle.

**Fichiers** :
- `admin/.../pages/SourceRunListingsPage.vue` — section searches
  enrichie + bouton rules + drawer
- nouveau `FilterRulesPanel.vue`
- consomme `useFilterConfig.ts` (B6)

**Critère** : Discovery searches montrent 2 rows par eurio quand 2 mkts
appelés ; règles panel listable, valeurs cohérentes avec `filters.py`.

**Durée estimée** : 3 h.

---

### Chunk F4 — Coin-detail thumbs marketplace badges

**Scope** : ajouter mini-badge marketplace en coin top-right des thumbs
`EnrichmentGallery.vue`. Étendre `useCoinAssets` pour récupérer le
champ.

**Fichiers** :
- `admin/.../components/EnrichmentGallery.vue`
- `admin/.../composables/useCoinAssets.ts`
- `ml/api/coin_assets_routes.py` — ajouter `marketplace` au payload

**Critère** : sur `/coins/<eurio_id>`, chaque thumb enrichment montre
le badge marketplace en top-right.

**Durée estimée** : 1.5 h.

---

## Phase V — Validation

### Chunk V1 — Probe langues marketplaces + PT routing

**Scope** : implémentation `ml/scripts/probe_marketplace_languages.py`
(cf. `language-probe.md` §"Étape 2"). Run unique, ~72 calls, génère le
dump JSON qui confirme/ajuste `MARKETPLACE_ACTIVE_LANGS`. **Inclut une
mini-section dédiée au routing PT** : 2-3 commémos PT testées sur
EBAY_ES vs EBAY_GB pour confirmer ou retirer la route PT→ES.

**Fichiers** : 1 nouveau script + `Taskfile.yml`.

**Critère** :
- Dump JSON produit, table `by_lang` cohérente avec les prédictions.
- Décision PT actée : soit `EBAY_ES` reste (recall ≥ ×2 GB-only sur PT),
  soit le code de `route_for("PT")` bascule sur `primary=None`
  (GB-only). Commit dédié à la décision, lien vers le probe data.

**Durée estimée** : 1.5 h (code) + 5 min (run) + 30 min (analyse PT).

---

### Chunk V2 — Cutover legacy → multi-mkt

**Scope** :
- Vérifier que tous les chunks B/I/F sont mergés et stables.
- Run smoke sur 10 eurio_ids variés (mix avec/sans marketplace natif).
- Vérifier funnel par marketplace, dédup OK, KPI recall ≥ ×3 vs baseline.
- Retirer le code legacy hardcoded :
  - `MARKETPLACE = "EBAY_FR"` (déjà retiré au chunk B3)
  - `THEME_TOKEN_FR_ALIASES` dans `queries.py` (déjà obsolète depuis I2)
  - Tout commentaire référant à `EBAY_FR` comme unique mkt.

**Critère** : Smoke run vert. Le front affiche les marketplaces. Les
KPI recall mesurés sont ≥ ×3 sur la médiane vs baseline. Aucun
`EBAY_FR` hardcoded ne reste dans le code de prod.

**Durée estimée** : 2 h (smoke + cleanup).

---

## Récap budget total

| Phase | Chunks | Durée estimée cumulée |
|---|---|---:|
| B (back) | B1 → B6 | ~8 h |
| I (i18n) | I1 → I2 | ~4 h code + ~4 h run |
| F (front) | F1 → F4 | ~8.5 h |
| V (valid) | V1 → V2 | ~3.5 h + 5 min run |
| **Total** | **14 chunks** | **~28 h** |

Ordre recommandé pour le démarrage :

1. **B1** (schema) — débloque tout le reste.
2. **B2** + **B3** en parallèle si motivation.
3. **I1** (bootstrap i18n) en background pendant qu'on code B4.
4. **B4** (adapter multi-call) — gros chunk, prendre du recul après.
5. **I2** (matcher multilingue) — finalise la chaîne back.
6. **B5/B6** (APIs front) — préparent le terrain front.
7. **F1 → F4** (front) dans l'ordre, audit visuel chunk-par-chunk.
8. **V1** (probe langues) — peut être fait avant F3 si on veut confirmer
   les active_langs avant de coder le matcher final.
9. **V2** (cutover + smoke) — fin du chantier.

Premier chunk à toucher : **B1**. Démarre par les migrations DB pour ne
rien casser pendant les chunks suivants.
