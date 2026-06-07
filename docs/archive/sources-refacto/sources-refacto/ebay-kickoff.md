# Kickoff eBay — Étape 3 sources refacto

> Brief auto-suffisant pour ouvrir la session "vraie source eBay
> bout-en-bout" (étape 3 du plan stratégique). À lire en premier
> dans la nouvelle conversation.

## Prompt à coller en début de session

```
J'ouvre une session pour implémenter la source eBay réelle (étape 3
de la refacto sources). Lis ce fichier en entier :
docs/sources-refacto/ebay-kickoff.md

Puis lis dans l'ordre :
  1. docs/sources-refacto/decisions.md (D-19 → D-27 surtout)
  2. docs/sources-refacto/progress.md (dernière entrée — orchestrateur
     + API + CLI livrés)
  3. docs/sources-refacto/orchestration.md (architecture 4 couches)
  4. docs/sources-refacto/schema.md (split source_images / image_assets)
  5. ml/sources/_base/adapter.py (contrat SourceAdapter)
  6. ml/sources/_base/orchestrator.py (run_pipeline)
  7. ml/market/ebay_client.py (legacy à RÉUTILISER tel quel)
  8. ml/market/scrape_ebay.py (legacy à JETER en grande partie ;
     extraire seulement build_search_query + filtres anti-bruit)

On va construire chunk par chunk. Le user m'arrête entre chaque
chunk pour audit visuel. Ordre :
  - 3.A — Schema + SourceQuery extension (target_eurio_ids pluriel)
  - 3.B — eBay adapter core (discover + download_raw)
  - 3.C — Quota + freshness API (pre-flight check)
  - 3.D — CLI eBay (lit freshness, alimente target_eurio_ids)
  - 3.E — Front widget (KPI quota + freshness queue + estimation)
  - 3.F — Quote + lot routing dans resolve.py
  - 3.G — Smoke run réel sur 5 commemos
```

## Le malentendu à dissiper d'entrée

Pendant la session de design on a brièvement glissé vers un modèle
"SourceQuery par cohort country/year/denom". **Faux modèle.** eBay
est une source d'**enrichissement**, pas de découverte. Le pilotage
est :

```
liste de eurio_id (depuis le référentiel canonique)
  └─→ pour chaque eurio_id, on enrichit (images + prix + métadonnées)
```

Pas de cohort dans cette boucle. Les cohorts sont un concept *training-side*
(`cohort_capture_flow`) sans rapport avec l'ingestion source. La page
`/sources` admin a déjà figé la dichotomie "Référentiel canonique"
(numista) vs "Enrichissement" (ebay, mdp, bce, …).

Conséquence sur `SourceQuery` pour eBay : `country`, `year`,
`denomination` sont **inertes**. Seuls `target_eurio_id` (singulier
historique) ou `target_eurio_ids` (pluriel, ajout 3.A) comptent.

## Décisions actées (D-19 → D-27, voir decisions.md)

- **D-19** Source eBay = enrichissement par `eurio_id`. Pas de cohort.
- **D-20** Freshness queue en vue SQL pure (V1).
- **D-21** 1 run = 1 batch de N eurio_ids (default **10**).
- **D-22** Tout télécharger en HD (`item/{id}` systématique).
- **D-23** Pagination `limit=50` no-paginate V1.
- **D-24** Velocity weighting → vue SQL post-hoc.
- **D-25** Quota stop = `partial`, recovery par idempotence.
- **D-26** Lot detection à 2 niveaux (titre heuristique + n_crops par image).
- **D-27** Pre-flight quota check (refus si `estimate × 1.3 > remaining`).

## Ce qui existe déjà (à RÉUTILISER tel quel)

### `ml/market/ebay_client.py` — 134 lignes propres

- `get_app_token()` — OAuth2 client_credentials avec cache TTL
- `EbayClient.search()` — `item_summary/search` avec aspect_filter, fieldgroups
- `EbayClient.get_item()` — `item/{id}` (pour HD images)
- `EbayClient.get_items_by_group()` — expansion multi-année
- `QuotaTracker` câblé en interne (table `api_call_log` SQLite)

→ Aucune modif. On l'importe direct depuis `ml/sources/ebay/adapter.py`.

### `ml/market/scrape_ebay.py` — 647 lignes, dont ~200 à extraire

À **garder** (extraire vers `ml/sources/ebay/queries.py`) :
- `STOP_WORDS`, `_theme_keywords()`, `build_search_query()`
- `title_matches_theme()`
- `NOISE_PATTERNS` regex
- `accept_listing()` (filtre anti-bruit prix/face value)

À **jeter** :
- `target_commemoratives()` (remplacé par freshness queue SQL)
- `compute_market_stats()` / `weighted_quantile()` / `listing_weight()` (déplacé en vue SQL post-hoc)
- `write_observation()` / `write_snapshot()` / `_insert_market_price()` (Supabase legacy)
- `record_run()` JSON (déjà migré SQLite)

Le legacy reste sur disque pendant la transition. Suppression =
chunk séparé après validation 3.G.

## Architecture cible

```
ml/sources/ebay/
├── __init__.py
├── adapter.py          ← EbayAdapter implements SourceAdapter
├── queries.py          ← build_search_query + extracted from legacy
├── filters.py          ← accept_listing + is_lot_suspected (D-26)
├── cli.py              ← reads freshness queue, populates target_eurio_ids
└── README.md           ← ToS, license, quirks, exemples

ml/sources/_base/
├── adapter.py          ← SourceQuery extension (target_eurio_ids pluriel)
├── orchestrator.py     ← loop sur target_eurio_ids si présent
└── steps/resolve.py    ← branche lot vs single (D-26)

ml/api/sources_routes.py  ← +/quota-status, +/freshness, +pre-flight
ml/state/schema.sql       ← +is_lot_suspected, +review_queue.kind, +v_ebay_freshness
```

## Le pipeline 6 étapes — adaptations eBay

| # | Étape | Comportement eBay-spécifique |
|---|---|---|
| 1 | Discover | itère `target_eurio_ids` ; pour chaque, build query depuis `coins.eurio_id` ; search EBAY_FR ; expand groups top-K ; calcule `is_lot_suspected` sur titre |
| 2 | Persist | upsert source_images **1 row par image du listing** (15 photos = 15 rows, partagent `source_ref` + `image_index`) ; stocke `is_lot_suspected` |
| 3 | Download | fetch ebayimg.com (CDN, hors quota Browse) ; HD via `item/{id}.image.imageUrl` + `additionalImages[*].imageUrl` |
| 4 | Detect & crop | inchangé (normalize_snap + pHash) |
| 5 | Resolve | si `is_lot_suspected = false` → insert `pending_quotes` ; si `true` → tag `review_queue.kind = 'lot'`, pas de pending_quote |
| 6 | Enqueue review | inchangé (priority calc) |

## Convention `source_ref` eBay

Le schema (schema.md §"Conventions source_ref") dit `ebay_listing_<itemId>`
**sans index image**. Les multiples images deviennent des `image_assets.crop_index`
distincts attachés au même `source_images`.

→ **Décision en 3.A** : on dévie. eBay donne plusieurs URLs d'image
distinctes par listing (1 obverse + 1 reverse + N détails) — chacune
mérite son propre fichier raw. Solution : `source_ref = ebay_<itemId>_img<N>`,
le `<N>` étant l'index dans `image[] + additionalImages[]`. Cohérent
avec l'idée "1 source_image = 1 fichier". On documente ça dans schema.md
et on adapte le pattern.

Alternative envisagée : 1 source_image avec un payload listant N URLs,
chaque URL téléchargée dans un sous-fichier. Rejetée parce que `bytes`,
`sha256`, `storage_path` perdent leur sens "1 fichier = 1 row".

## Découpage chunk-par-chunk

### 3.A.0 — Bootstrap de la table `coins` SQLite (pré-requis)

**Découverte 2026-05-03** : le référentiel canonique vit en JSON
(`ml/datasets/eurio_referential.json`, 2628 entrées dont 466 commémos
2€ non-EU). Pas de table `coins` en SQLite. La vue SQL `v_ebay_freshness`
exigeait cette table — option B retenue (cf. progress.md).

Modifs :
- `ml/state/schema.sql` — table `coins` (eurio_id PK, country, year,
  face_value, is_commemorative, theme, numista_id, raw_payload_json,
  imported_at) + indexes
- `ml/scripts/bootstrap_coins_from_referential.py` — lit le JSON,
  upsert par `eurio_id` (`INSERT OR REPLACE`). Idempotent.
- `ml/Taskfile.yml` — task `ml:bootstrap-coins` (alias court `bootstrap-coins`)
- `Store._bootstrap()` — vérifie présence de la table `coins` ; si vide,
  warning loggé (pas un raise, le mock adapter doit pouvoir tourner).

Tests :
- `tests/test_bootstrap_coins.py` — script tournable 2 fois sur DB temp
  → 2628 rows constants, idempotence par `eurio_id`.

**Audit attendu** :
```bash
go-task ml:bootstrap-coins
sqlite3 ml/state/training.db "SELECT count(*) FROM coins"
# → 2628
sqlite3 ml/state/training.db "SELECT count(*) FROM coins WHERE face_value=2.0 AND is_commemorative=1 AND country!='eu'"
# → 466
```

### 3.A — Schema source_images / review_queue + SourceQuery extension

**Objectif** : ajouter les colonnes nécessaires et étendre l'API
SourceQuery sans toucher à eBay encore. Tests existants (17/17)
doivent rester verts.

Modifs :
- `ml/state/schema.sql` :
  - `alter table source_images add column is_lot_suspected integer default 0`
    (idempotent via `Store._ensure_column`, pattern existant ligne 425+)
  - `alter table review_queue add column kind text default 'single'`
    (single | lot)
  - `CREATE VIEW IF NOT EXISTS v_ebay_freshness` — schema final ci-dessous
- `ml/sources/_base/adapter.py` :
  - `SourceQuery.target_eurio_ids: tuple[str, ...] | None = None` (pluriel,
    tuple pour rester `frozen=True` hashable)
  - `target_eurio_id` (singulier) gardé rétro-compat ; combinaison interdite
    (raise au boot du SourceQuery via `__post_init__`)
- `ml/sources/_base/orchestrator.py` :
  - Si `query.target_eurio_ids` → l'orchestrateur boucle sur chaque eurio_id,
    appelle `adapter.discover()` avec une `SourceQuery` dérivée (1 eurio_id),
    aggrège tous les items dans un seul run
  - Si `query.target_eurio_id` → comportement actuel inchangé
  - 1 run = 1 batch, `filters_json` archive la liste complète des eurio_ids
- `ml/sources/_base/query_sig.py` :
  - Signature stable quel que soit l'ordre des `target_eurio_ids` (sort interne)

Vue `v_ebay_freshness` (copiée ici pour référence) :

```sql
CREATE VIEW IF NOT EXISTS v_ebay_freshness AS
SELECT
  c.eurio_id,
  c.country,
  c.year,
  MAX(si.fetched_at) AS last_enriched_at,
  COUNT(DISTINCT si.id) AS n_images,
  COUNT(DISTINCT ia.id) AS n_crops
FROM coins c
LEFT JOIN source_images si
  ON si.target_eurio_id = c.eurio_id AND si.source = 'ebay'
LEFT JOIN image_assets ia ON ia.source_image_id = si.id
WHERE c.face_value = 2.0 AND c.is_commemorative = 1 AND c.country != 'eu'
GROUP BY c.eurio_id;
```

(L'ORDER BY est appliqué au SELECT qui consomme la vue, pas dans la vue.)

Tests :
- `tests/test_orchestrator.py` :
  - Nouveau test `test_target_eurio_ids_loop()` avec mock adapter qui
    enregistre les eurio_ids reçus en paramètre
  - Test `test_query_signature_stable_with_eurio_ids()` (ordre indifférent)

**Audit attendu** : `pytest tests/test_sources_base.py tests/test_orchestrator.py -q` →
17/17 + nouveaux verts. `sqlite3 ml/state/training.db "SELECT count(*) FROM v_ebay_freshness"`
retourne 466 (toutes nulles `last_enriched_at` au démarrage).

### 3.B — eBay adapter core

**Objectif** : `EbayAdapter.discover()` et `download_raw()` qui passent
le contrat SourceAdapter, testés avec httpx mocked.

Fichiers :
- `ml/sources/ebay/queries.py` — `build_search_query(eurio_id)` qui
  charge `coins` depuis SQLite, extrait `(country, year, theme_slug)`,
  délègue à un `_build_query_from_identity()` portable depuis legacy
- `ml/sources/ebay/filters.py` :
  - `accept_listing(row, face_value)` (extrait du legacy)
  - `is_lot_suspected(title) -> bool` (regex `lot|coffret|série|rouleau|set\b|collection complète`)
- `ml/sources/ebay/adapter.py` :
  - `EbayAdapter(source_id='ebay', client: EbayClient, store: Store)`
  - `discover(query)` :
    - charge `query.target_eurio_ids` (ou `[query.target_eurio_id]`)
    - pour chaque eurio_id : build query, search (`limit=50`, no paginate D-23),
      expand groups top-K=2, optionnellement fetch `item/{id}` pour HD
      images (D-22), filter via `accept_listing`, marque `is_lot_suspected`
    - yield 1 `DiscoveredItem` par image du listing (15 photos = 15 yields,
      `source_ref = ebay_<itemId>_img<N>`)
    - log `n_calls` au tracker quota après chaque API call
  - `download_raw(item, dest)` : `httpx.get(item.raw_payload['image_url'], timeout=30)`,
    écrit atomiquement, retourne size + sha256 + dims
- `ml/sources/ebay/__init__.py` — re-export EbayAdapter
- `ml/sources/_base/sources_registry.py` — entrée `ebay` (déjà présente,
  vérifier `is_future=False`)

Tests :
- `tests/test_ebay_adapter.py` :
  - mock `EbayClient.search()` retourne 1 listing avec 3 photos
  - asserts : 3 `DiscoveredItem` yieldés, `source_ref` distincts,
    `is_lot_suspected=False` sur titre normal
  - test du flag lot : titre `"Lot 5 pièces 2 euros"` → `is_lot_suspected=True`
  - mock `httpx.get()` pour `download_raw` retourne fake bytes,
    asserts size + sha256 cohérents

**Audit attendu** : `pytest tests/test_ebay_adapter.py -v` vert.

### 3.C — Quota + freshness API

**Objectif** : exposer ce que le front affiche.

Endpoints (dans `ml/api/sources_routes.py`) :

```
GET  /sources/ebay/quota-status
       → { "calls_today": 1240, "limit": 5000,
           "remaining": 3760, "exhausted": false }

GET  /sources/ebay/freshness?limit=50
       → { "items": [
            { "eurio_id": "fr-2eur-2015-...", "last_enriched_at": null,
              "n_images": 0, "n_crops": 0, "status": "never" },
            …
          ],
          "buckets": { "never": 183, "stale_90d": 67, "fresh": 270 } }

POST /sources/ebay/runs?dry_run=&force=
     body: { "target_eurio_ids": ["fr-2eur-2015-...", "..."] }
       → 202 { run_id, status: "started", estimate_calls: 70 }
       → 409 { error: "quota_insufficient",
               estimate: 70, remaining: 35,
               max_safe_batch: 4 }
```

Helpers :
- `ebay_calls_today(store) -> int` (lecture `api_call_log WHERE source='ebay' AND date(at) = today`)
- `estimate_calls(store, n) -> int` :
  - si moins de 3 runs eBay terminés en `success`/`partial` → fallback hardcodé `7 × n`
  - sinon : `avg(n_calls / max(len(filters_json.target_eurio_ids), 1))` × n × 1.0
- Pre-flight dans `POST /runs` : si `estimate * 1.3 > remaining` → 409

Tests d'intégration FastAPI :
- store temp + injection dans `srv._store`
- mock 3 runs historiques avec n_calls connus → vérifier estimate
- POST runs avec batch trop gros → 409 avec `max_safe_batch` cohérent

**Audit attendu** : `curl http://localhost:8042/sources/ebay/quota-status`
retourne du JSON sain.

### 3.D — CLI eBay

**Objectif** : pouvoir lancer un batch depuis le terminal sans front.

`ml/sources/ebay/cli.py` (ou sous-commande de `ml/sources/cli.py`) :

```
go-task ml:src:ebay:run -- --batch 10
go-task ml:src:ebay:dry -- --batch 10
go-task ml:src:ebay:limit -- --batch 3 --eurio-ids fr-2eur-2015-...
go-task ml:src:ebay:status   # affiche quota + dernier run
```

- `--batch N` : prend les N premiers eurio_ids de la freshness queue
- `--eurio-ids a,b,c` : override la sélection manuellement
- `--dry-run` : exécute Discover seulement, n'écrit rien
- Pre-flight check identique au POST endpoint (refuse si quota insuffisant)

Tasks dans `ml/Taskfile.yml` (4 tasks).

**Audit attendu** : `go-task ml:src:ebay:dry -- --batch 3` affiche
les 3 prochains eurio_ids + l'estimate calls + remaining quota,
sans rien écrire en DB.

### 3.E — Front widget freshness + estimation

**Objectif** : la page `/sources/ebay` devient *l'interface de pilotage*
de l'enrichissement.

Composants :
- `EbayQuotaKPI.vue` — bandeau "Quota Browse API : 1240 / 5000 (76% restant)"
  avec ring de progression
- `EbayFreshnessWidget.vue` — pie chart 3 buckets (never / stale / fresh)
  + liste paginée des prochains eurio_ids à enrichir avec preview
  obverse Numista
- `EbayRunDialog.vue` — modal pré-run : slider batch size 5-30,
  "Estimation : N calls — Quota restant : M — ✅ OK / ⚠️ insuffisant",
  bouton Run / Dry désactivé si insuffisant
- live counter `+N calls` ajouté au bandeau live existant

Branchement :
- `useEbayFreshness.ts` : `fetchQuotaStatus`, `fetchFreshness`, fallback
  graceful (mock si network down)
- bouton Run existant déclenche `EbayRunDialog` au lieu d'un POST direct
- toast post-run : "Batch terminé : 487 calls / 312 images / 24 prix /
  3 lots à reviewer"

Audit visuel : 5 chunks séparés, 1 commit par chunk visuel, validation
utilisateur entre chaque (pattern de la session 2026-05-02).

### 3.F — Quote + lot routing dans resolve.py

**Objectif** : finaliser l'étape 5 du pipeline pour eBay.

Modif `ml/sources/_base/steps/resolve.py` :
- charge `source_images.is_lot_suspected` du source_image parent
- pour chaque image_asset :
  - status reste `needs_review` (D-18)
  - si `is_lot_suspected = false` ET listing a un prix :
    - insert dans `pending_quotes` (1 row par source_image, pas par crop —
      le prix est de l'annonce, pas du crop)
    - dédup par `(source_image_id)` UNIQUE (à ajouter au schema)
  - si `is_lot_suspected = true` :
    - `review_queue.kind = 'lot'`
    - pas de pending_quote
- enqueue review : kind hérité

Tests :
- `test_resolve_quote_eligible()` : single listing avec price → 1 pending_quote
- `test_resolve_lot_no_quote()` : lot listing → review_queue.kind = 'lot', 0 pending_quote
- `test_resolve_idempotent()` : re-run = 0 nouvelle pending_quote

### 3.G — Smoke run réel + audit visuel

**Objectif** : valider sur de la vraie donnée que le pipeline
bout-en-bout fonctionne.

Procédure :
1. `go-task ml:src:ebay:dry -- --batch 5 --eurio-ids "<5 commemos populaires>"` :
   doit afficher 5 eurio_ids, ~35 calls estimés, ~5000 quota restant.
2. `go-task ml:src:ebay:run -- --batch 5` :
   - run en partial ou success
   - audit visuel : `open ml/datasets/sources/ebay/<eurio>/raw_*.jpg` —
     les images doivent être de vraies pièces eBay
   - check DB : `select count(*) from source_images where source='ebay'` ≥ 30
   - check DB : `select count(*) from pending_quotes` ≥ 5
   - check DB : `select count(*) from review_queue where kind='lot'` ≥ 0
3. Re-run identique :
   - 0 nouveau row, 0 fichier téléchargé (idempotence)
4. Documenter dans `progress.md` :
   - moyenne calls/eurio_id observée (pour calibrer estimate)
   - taux de lots détectés
   - taux d'images skippées par filtre anti-bruit
   - bugs éventuels rencontrés

## Parking lot (V1.5+, à NE PAS construire en V1)

Documenté ici pour ne rien perdre des réflexions de cette session.

### Lot review page (V1.5)

UI dédiée à `/review/lots` avec :
- À gauche : N crops détectés par `normalize_snap` sur les images d'un
  listing lot (ex: coffret BE de 5 pièces)
- À droite : grille des `eurio_id` candidats (filtre par pays/année du listing)
- Drag-drop (ou top-K + "Skip") pour assigner chaque crop à un eurio_id
- Pas d'attribution prix (le prix d'un coffret n'est pas décomposable)
- Action "Toutes ces pièces sont la même" pour cas dégénéré

**Pré-requis** : on doit avoir 200+ rows `review_queue.kind='lot'` accumulés
pour calibrer l'UX. Tant qu'on n'a pas ce volume, on accumule en V1
(les lots restent visibles dans `/review` mais avec un badge "lot — pas
encore actionnable").

### Auto-name avec calibration sur vraies données (V1.5)

D-18 a différé l'auto-name. Une fois 500+ runs eBay accumulés en V1,
recalculer la précision d'un name-match sur le titre + filtres.
Si on peut tenir un seuil ≥ 0.92 sans trop de faux positifs, ré-introduire
`auto_name` en step 5 avec ce seuil.

### Velocity weighting view (V1.5)

`v_coin_market_quotes_weighted` :
- INPUT : `coin_market_quotes` brut (1 row par listing eBay observé)
- COMPUTE : `weight = log(1 + sold_count / years_listed) × max(seller_fb_pct, 10)/100`
- OUTPUT : P25 / P50 / P75 pondérés par `eurio_id × condition_normalized × period`
- Avantage : recalculable à la lecture, schéma de pondération évolutif sans re-scrape

### Pagination > 50 (V2)

Si on observe que les commemos populaires ont >100 listings actifs et
qu'on perd de la donnée, paginer. Coût quota multiplié par `ceil(total/50)`.
Pas avant validation V1.

### `item/{id}` HD systématique vs paresseux (V2)

D-22 dit systématique. Si on observe en V1 que beaucoup de `item_summary`
ont déjà `additionalImages` HD, on pourrait basculer en paresseux
(call `item/{id}` seulement si `additionalImages` vide ou taille basse).
Économie potentielle : 30-50% du quota. À mesurer en 3.G.

### Scheduled re-fetch (V2)

Cron qui lance automatiquement un batch sur les eurio_ids dont
`last_enriched_at > 90j`. La freshness queue le fait déjà manuellement,
le cron c'est juste l'automatisation. Triviale une fois le `/schedule`
agent câblé.

### Multi-source freshness (V2)

Aujourd'hui `v_ebay_freshness` est eBay-only. Quand on aura catawiki,
numiscorner, cgb, on voudra une vue `v_enrichment_freshness(source, eurio_id)`
pivotée pour piloter "quelles sources manquent pour cette pièce ?".

## Endpoints eBay disponibles (pour mémoire)

| API | Endpoint | Usage |
|---|---|---|
| Browse `item_summary/search` | `GET /buy/browse/v1/item_summary/search` | recherche listings actifs (1 call/query) |
| Browse `item/{id}` | `GET /buy/browse/v1/item/{item_id}?fieldgroups=PRODUCT` | détail HD multi-image (1 call/listing) |
| Browse `item/get_items_by_item_group` | `GET /buy/browse/v1/item/get_items_by_item_group` | variations multi-année (1 call/group) |
| Marketplace Insights (sold) | ❌ partner-gated | hors scope |
| Buy Feed | ❌ application growth limit | hors scope |
| Analytics `getRateLimits` | ✅ public | pas câblé V1 |

Marketplace : `EBAY_FR` (header `X-EBAY-C-MARKETPLACE-ID`).
Scope OAuth : `https://api.ebay.com/oauth/api_scope`.
Quota : 5000 calls/jour Browse API (limit "App Growth" par défaut).

## Vérifications avant de coder

```bash
# Tests existants verts
cd ml && .venv/bin/python -m pytest tests/test_sources_base.py tests/test_orchestrator.py -q
# → doit afficher 17 passed

# Token eBay valide
.venv/bin/python -c "import os; from market.ebay_client import get_app_token; print(get_app_token(os.environ['EBAY_CLIENT_ID'], os.environ['EBAY_CLIENT_SECRET'])[:20])"

# Référentiel canonique présent
sqlite3 ml/state/training.db "select count(*) from coins where face_value = 2.0 and is_commemorative = 1 and country != 'eu'"
# → doit afficher ~500
```

## Ce qu'on NE fait PAS dans la session 3

- **Lot review page** (V1.5)
- **Auto-name calibré** (V1.5)
- **Velocity weighting view** (V1.5)
- **Pagination > 50** (V2)
- **Scheduled re-fetch** (V2)
- **Suppression du legacy `ml/market/scrape_ebay.py`** (chunk séparé après 3.G validé)

## Sortie attendue

À la fin de la session 3 :
- 5 commemos eBay réelles enrichies (~30 images téléchargées, ~5 prix
  capturés, 0-2 lots en review queue)
- Page `/sources/ebay` opérationnelle, KPI quota visible, freshness
  queue lisible, modal pré-run avec estimation
- CLI `go-task ml:src:ebay:run -- --batch 10` fonctionnel
- Re-run identique = 0 nouveau (idempotence des 5 couches)
- `progress.md` documenté avec stats observées

## Contraintes héritées

- **R0 pas de dette technique** (CLAUDE.md) — pas de shortcut.
- **D-13** — pipeline 6 étapes, jamais monolithique.
- **D-17** — pas de fallback silencieux dans detect_crop.
- **D-18** — pas d'auto-name V1, tout en `needs_review`.
- **Audit visuel chunk-par-chunk** — l'utilisateur valide chaque chunk
  avant le suivant. Pas d'enchaînement sans "go".
- Pas d'emojis dans le code.
