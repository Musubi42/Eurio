# Data-layer unification — implémentation

> **Mission** : faire d'`eurio-api.musubi.dev` la **seule porte d'entrée**
> data. SQLite `eurio.db` (sur le VPS) devient source de vérité unique.
> MinIO redevient pur object storage (assets). Supabase = mirror Android.
>
> **Décidé le 2026-06-19** suite au pivot architectural et à la
> découverte que **65 tables éditoriales sont déjà présentes** dans le
> `eurio.db` du VPS (identiques au canonical MinIO du 2026-06-17).
>
> **Audience** : Claude Code ou humain qui reprend le chantier. Lire
> dans l'ordre. Chaque phase est commit-able indépendamment.

## 0. État de référence (snapshot 2026-06-19)

### Topologie cible

```
┌──────────────────────────────────────────────────────────────────────┐
│  VPS                                                                 │
│  ────────────────────                                                │
│  eurio-api.musubi.dev   ← FastAPI : seule porte d'entrée data        │
│        │                                                             │
│        ├─► eurio.db (SQLite, /opt/eurio/infra/eurio-api/data/)       │
│        │   = 71 tables (65 éditoriales + 6 auth) = source de vérité  │
│        │                                                             │
│        └─► (futur, optionnel) sync descendant → Supabase             │
│             pour l'app Android                                       │
│                                                                      │
│  MinIO (eurio-s3.musubi.dev)                                         │
│  ──────────────────                                                  │
│  • Buckets `enrichment-crops`, `enrichment-raws`, `numista-canonical`│
│    = assets (images coins, crops, etc.)                              │
│  • Bucket `eurio-db` → KILLED après cutover (phase 5)                │
└──────────────────────────────────────────────────────────────────────┘
                                  ▲
                                  │ HTTP (Bearer PAT ou cookie OIDC)
              ┌───────────────────┼───────────────────┐
              │                   │                   │
       studio-local         admin-vps           ML compute local
       (Mac/PC :5173)       (eurio-admin)       (Mac/PC :8042)
       Bearer PAT           cookie OIDC         = client HTTP de
       lit/écrit            lit (consult        eurio-api (phase 6,
       l'API maison         + auth)             optionnel)
```

### Inventaire factuel

**Tables eurio.db (VPS local, 71)** :

- 65 éditoriales identiques au canonical MinIO du 2026-06-17 (last release).
  - Confirmé par row-count diff côté Mac vs VPS : 0 divergence (cf. session 2026-06-19).
- 6 auth (`users`, `roles`, `user_roles`, `pat_tokens`, `auth_audit`,
  `_schema_migrations`) ajoutées par migrations C2.

**Tables vides confirmées intentionnellement** (par l'opérateur 2026-06-19) :
`sets`, `set_members`, `coin_series`, `referential_catalog`,
`cohort_members`, et autres tables non encore utilisées. Schémas en place,
data viendra avec l'usage. **Ne pas chercher à les peupler depuis Supabase.**

**Tables Supabase orphelines** (présentes UNIQUEMENT côté Supabase, pas en
SQLite) :
- `coin_confusion_map` (~1500 rows, read-only frontend, alimenté par
  scripts ML backend)
- `sets_audit` (~100 rows, append-only audit log, écrit côté Supabase
  par triggers historiques)

**Front studio-local — surface à refactorer** :

- **24 fichiers** lisent Supabase directement
- **32 fichiers** tapent `ML_API` (`http://127.0.0.1:8042`) — endpoints
  FastAPI locaux
- Overlap probable : ~40-50 fichiers distincts à refactorer

**Composables ML_API identifiés** (à mapper vers eurio-api) :

| Composable | Domaine | Endpoint(s) ML_API actuel(s) |
|---|---|---|
| `useTrainingApi` | training | `/training/*` |
| `useCoinsApi` | coins | `/coins/*` |
| `useSetsApi` | sets | `/sets/*` |
| `useCropBenchApi` | crop-bench | `/crop-bench/*` |
| `useCoinsReview` | coins/needs-review | `/coins-review/*` |
| `useNumistaReview` | coins/numista-review | `/numista-review/*` |
| `useCoinAssets` | coins | `/coin-assets/*` |
| `useRunSearches` | sources | `/sources/runs/.../searches` |
| `useMarketplaceMap` | sources/ebay | `/marketplace-map/*` |
| `useReferentialApi` | referential | `/referential/*` |
| `useBenchApi` | bench | `/bench/*` |
| `useOperationsApi` | operations | `/operations/*` |
| `useReviewApi` | review (legacy) | `/review-queue/*` |
| `useLotReview` | review | `/review-queue/lot/...` |
| `useTextSignals` | review | `/text-signals/*` |
| `useDinoSuggestions` | review | `/dino/*` |
| `useCoinLookups` | coins | `/coins/lookups` (+ supabase) |
| `useSourceDetail` | sources | `/sources/{id}` |
| `useRunBreakdown` / `useRunDiscarded` / `useRunFunnel` / `useRunListings` | sources/runs | `/sources/runs/...` |

**Composables Supabase identifiés** (à mapper vers eurio-api OU à
décommissionner) :

| Composable / fichier | Tables | Op |
|---|---|---|
| `useArbitrage.ts` | `coins` | SELECT + UPDATE `cross_refs` |
| `useConfusionMap.ts` / `useConfusionZone.ts` | `coin_confusion_map` | SELECT (Phase 1 — table orpheline à migrer d'abord) |
| `useCoinSeries.ts` | `coin_series` | SELECT (déjà en eurio.db, vide pour l'instant) |
| `AuditPage.vue` | `sets_audit` | SELECT (Phase 1 — table orpheline) |
| `useStagedCoins.ts`, `CuratedMembersPicker.vue` | `coins` | SELECT |
| `useCriteriaPreview.ts`, `CriteriaBuilder/LivePreview/...` | `coins` | SELECT |
| `useCoinLookups.ts` | misc lookups | mix supabase/ML_API |
| `EnrichmentGallery.vue`, `CoinDetailPage.vue`, `CoinsPage.vue` | `coins` | SELECT |

### Hors scope (volontairement)

- App Android — continue à lire Supabase (mirror, voir Phase 5bis future)
- Réécriture du proto (`packages/proto/`)
- Refactor heavy de `ml/` (scripts d'enrichment, etc.) hors Phase 6
- Migration des tables non-utilisées par le frontend (audit séparé si besoin)

## 1. Phase 1 — Migrer les 2 tables Supabase orphelines vers SQLite

**But** : transposer `coin_confusion_map` et `sets_audit` en SQLite,
ajouter les endpoints de lecture, refactor les 2-3 composables qui
les lisent. Petit chunk indépendant, démarre la mécanique.

### 1.1 Audit du schéma Supabase

Pour chaque table, récupérer la définition (colonnes + types + indexes) :

```bash
# Depuis le VPS, via le service-role key (cf. secrets/dev.env)
curl -s "$SUPABASE_URL/rest/v1/coin_confusion_map?limit=1" \
  -H "apikey: $SUPABASE_SERVICE_ROLE_KEY" \
  -H "Authorization: Bearer $SUPABASE_SERVICE_ROLE_KEY"
# → inspecter le sample
```

Ou via la doc Supabase migrations dans `supabase/migrations/*.sql` :

```bash
grep -rn "create table.*coin_confusion_map\|create table.*sets_audit" \
  supabase/migrations/
```

### 1.2 Transposition SQLite

Convertir Postgres → SQLite :
- `text` → `TEXT`
- `uuid` → `TEXT`
- `timestamptz` → `TEXT` ISO-8601 (cf. `coin_observations` pour le pattern)
- `jsonb` → `TEXT` (JSON-stringifié)
- `array` → `TEXT` (JSON-stringifié ou table de jointure si requête lourde)
- enums → `TEXT` + `CHECK (col IN (...))`

Créer un nouveau fichier `ml/serving/migrations/0002_orphan_supabase_tables.sql`
qui ajoute les deux tables. Idempotent (`CREATE TABLE IF NOT EXISTS`).

### 1.3 Migration data one-shot

Script `ml/serving/migrate_orphan_supabase.py` :
- Lit Supabase via PostgREST (pagination `?limit=1000&offset=N`)
- Insert dans SQLite (transformation jsonb→str)
- Idempotent (`INSERT OR REPLACE` ou check `count(*)` avant/après)
- Logs : nombre de rows migrées + count diff Supabase vs SQLite

```bash
docker exec eurio-api python -m serving.migrate_orphan_supabase \
    --table coin_confusion_map
docker exec eurio-api python -m serving.migrate_orphan_supabase \
    --table sets_audit
```

### 1.4 Endpoints eurio-api

Nouveau fichier `ml/serving/confusion_routes.py` :
- `GET /confusion-map` — `scopes: coins:read` — pagination `?limit=&offset=`
- `GET /confusion-map/zone-stats?zone=...` — agrégats pour la vue

Nouveau fichier `ml/serving/audit_routes.py` (ou intégré dans
`users_routes.py` ?) :
- `GET /audit/sets?limit=&since=...` — `scopes: audit:read`

Câbler dans `ml/serving/server.py` (suit le pattern des routers
existants).

### 1.5 Refactor studio-local

- `src/features/confusion/composables/{useConfusionMap,useConfusionZone}.ts`
  - Remplacer `supabase.from('coin_confusion_map')` par
    `eurioApi.get('/confusion-map?...')`
- `src/features/audit/pages/AuditPage.vue`
  - Remplacer `supabase.from('sets_audit')` par `eurioApi.get('/audit/sets')`

### 1.6 Critères d'acceptation phase 1

- [ ] Migration script idempotent, exécuté 2× = même état
- [ ] `select count(*) from coin_confusion_map` en SQLite == count Supabase
- [ ] `GET /confusion-map` retourne les 1500 lignes via API
- [ ] Page Confusion + Audit du studio-local affichent exactement la
      même chose qu'avant (smoke visuel)
- [ ] Aucun appel `supabase.from('coin_confusion_map')` ni
      `supabase.from('sets_audit')` ne reste dans studio-local

### 1.7 Effort

~4-6h, indépendant, pas de blocage.

## 2. Phase 2 — Écrire les endpoints eurio-api pour les tables éditoriales

**But** : exposer toutes les tables que studio-local utilise via API.
C'est le **gros morceau** du chantier.

### 2.1 Liste des endpoints prioritaires

Triés par fréquence d'usage côté front :

| Tables | Endpoints à créer | Auth | Effort |
|---|---|---|---|
| `coins` (+ relations) | `GET /coins`, `GET /coins/{id}`, `GET /coins/{id}/observations`, `PATCH /coins/{id}` (cross_refs only — Arbitrage), `GET /coins/{id}/enrichment` | `coins:read/write` | 1j |
| `sources_registry`, `source_runs`, `source_images` | `GET /sources`, `GET /sources/{id}`, `GET /sources/{id}/runs`, `GET /sources/{id}/runs/{run_id}` (+ funnel/breakdown/listings/discarded/searches sous-routes) | `sources:read` | 1j |
| `review_queue`, `consensus_verdicts` | `GET /review-queue`, `POST /review-queue/{id}/decide`, etc. (port legacy `/review-queue/*` de localhost:8042) | `review:read/write` | 0.5j |
| `training_runs` + relations | `GET /training/runs`, `GET /training/runs/{id}`, `POST /training/runs` (lance), `GET /training/runs/{id}/epochs/steps/logs` | `training:run` | 0.5j |
| `mints`, `mint_release_*`, `pending_quotes` | `GET /mints`, `GET /mints/releases`, `GET /quotes/pending` | `coins:read` | 0.5j |
| `discovery_searches`, `discovery_log`, `discarded_listings`, `listing_text_signals` | `GET /discovery/...` | `sources:read` | 0.5j |
| `image_assets` + state events | `GET /image-assets`, `POST /image-assets/{id}/state` | `coins:write` | 0.5j |
| `wikipedia_nl_coins` | `GET /wikipedia/nl-coins` | `sources:read` | 0.2j |
| `cohort_jobs`, `experiment_*`, `iteration_*` | `GET /cohorts/...`, `/experiments/...` | `training:run` | 0.5j |
| `design_groups`, `coin_credits`, `coin_topics` | `GET /design-groups`, etc. | `coins:read` | 0.3j |
| Référentiel : `referential_catalog`, `referential_discovery_queue` | `GET /referential/...` | `coins:read` | 0.3j |
| Bench : `benchmark_runs`, `cohort_*` | `GET /bench/...` | `training:run` | 0.3j |
| Augmentation : `augmentation_runs`, `recipes`, `training_staging` | `GET /augmentation/...`, `POST /...` | `training:run` | 0.5j |

**Total estimé : 6-8j** si on couvre 100% de la surface. Mais on peut
**livrer incrémentalement** (refactor composable par composable, donc on
n'a besoin que de l'endpoint correspondant à chaque étape).

### 2.2 Conventions endpoints

- Préfixes courts, kebab-case : `/coins`, `/source-runs`, `/training-runs`
- Pagination : `?limit=&offset=` (max limit 500), retour `{items: [], total: n, limit: n, offset: n}`
- Filtres : query params explicites (`?country=FR&denomination=2eur&year=2002`)
- Erreurs : HTTPException avec `detail` lisible
- Auth : `Annotated[Principal, Depends(require_scope("..."))]` partout
- Réponses : pydantic models pour le typage, pas de `dict` brut
- Mutations : POST/PATCH/DELETE explicites, idempotence quand possible
- Audit : `write_auth_audit(...)` pour les mutations sensibles

### 2.3 Structure de fichiers

Chaque domaine = un fichier de routes :

```
ml/serving/
├── coins_routes.py            (existe ? à étendre)
├── sources_routes.py
├── review_queue_routes.py     (port legacy → /review-queue)
├── training_routes.py
├── mints_routes.py
├── discovery_routes.py
├── image_assets_routes.py
├── cohorts_routes.py
├── referential_routes.py
├── bench_routes.py
└── augmentation_routes.py
```

Câblage dans `server.py` : `app.include_router(...)` pour chaque.

### 2.4 Pattern test par endpoint

Pour chaque endpoint créé :
1. `curl -H "Authorization: Bearer $PAT" https://eurio-api.musubi.dev/endpoint` → 200
2. Smoke test sur 1 row sample (compare shape avec ce que le composable
   front attend)
3. Vérifier scopes (un PAT sans le scope requis → 403)

### 2.5 Critères d'acceptation phase 2

- [ ] Tous les endpoints listés en 2.1 existent et répondent 200 avec
      un Bearer PAT valide
- [ ] Aucun composable studio-local ne lit en direct la DB locale —
      tout passe par HTTP
- [ ] Documentation OpenAPI auto-générée par FastAPI accessible à
      `/docs` (mais protégée si possible)

## 3. Phase 3 — Refactor des composables studio-local

**But** : remplacer dans chaque composable `fetch(ML_API + path)` par
`eurioApi.get/post/put/delete(path)`. Idem `supabase.from(...)` →
`eurioApi.*`.

### 3.1 Liste de refactor

Par ordre de criticité (= ce qui te bloque le plus dans ton workflow daily) :

1. `useCoinsApi`, `useCoinsReview`, `useNumistaReview` (les pages coins)
2. `useReviewApi`, `useLotReview` (la review queue legacy — où tu
   passes du temps)
3. `useSourceDetail` + `useRun*` (sources runs analysis)
4. `useTrainingApi` (lancer training)
5. `useArbitrage` (le PATCH cross_refs)
6. `useSetsApi` + composables sets (`useCriteriaPreview`, `useCoinSeries`)
7. `useCoinAssets`, `EnrichmentGallery`
8. Le reste (bench, crop-bench, augmentation, referential, marketplace-map,
   text-signals, dino-suggestions, operations)

### 3.2 Pattern de migration par composable

```diff
- const ML_API = 'http://127.0.0.1:8042'
- const res = await fetch(`${ML_API}/coins/${id}`)
- const data = await res.json()
+ import { eurioApi } from '@/shared/api/eurio-api'
+ const data = await eurioApi.get<Coin>(`/coins/${id}`)
```

Pour les Supabase `from()` :

```diff
- const { data, error } = await supabase.from('coins').select('*').eq('eurio_id', id)
- if (error) throw error
+ const data = await eurioApi.get<Coin[]>(`/coins?eurio_id=${id}`)
```

### 3.3 Effort

Ce sera mécanique une fois l'endpoint correspondant existe. ~10-15min
par composable simple, ~30min pour les complexes (Arbitrage avec PATCH,
useCriteriaPreview avec filtres dynamiques).

**Total : 1-2j parallèle à Phase 2** (au fur et à mesure que les
endpoints arrivent).

### 3.4 Critères d'acceptation phase 3

- [ ] `grep -rn "ML_API\|fetch.*127.0.0.1:8042" src/features/` → 0 résultats
- [ ] `grep -rn "supabase\.from\|supabase\.rpc" src/features/` → 0 résultats
- [ ] Tous les écrans studio-local fonctionnent en pointant uniquement
      sur `eurio-api.musubi.dev` (test E2E manuel page par page)

## 4. Phase 4 — Drop `@supabase/supabase-js`

**But** : retirer toute trace de Supabase du studio-local.

### 4.1 Surface

- `package.json` : retirer `@supabase/supabase-js`
- `src/shared/supabase/` : supprimer le dossier entier (`client.ts`,
  `types.ts`, `database.generated.ts`)
- `vite.config.ts` : retirer les `define:` pour
  `VITE_SUPABASE_URL/ANON_KEY/SERVICE_KEY`
- `.envrc` (template) : retirer les exports `VITE_SUPABASE_*`
- `secrets/dev.env` : retirer `SUPABASE_*` côté env web (garder côté ML
  si scripts backend les utilisent encore)
- AppLayout : retirer le bandeau `DEV_BYPASS` (Supabase service_role)

### 4.2 Critères d'acceptation phase 4

- [ ] `pnpm install` ne pull plus `@supabase/supabase-js` dans
      `node_modules/`
- [ ] `pnpm studio:typecheck` passe (aucune référence orpheline aux
      types Supabase)
- [ ] `pnpm studio:build` produit un bundle sans Supabase
- [ ] Studio-local boot ne se plaint plus de variables Supabase manquantes

### 4.3 Effort

~30min après Phase 3 terminée. Si Phase 3 est incomplète, ne pas dropper.

## 5. Phase 5 — Décommissionner MinIO `eurio-db`

**But** : retirer le lease workflow + le bucket MinIO eurio-db, simplifier
les opérations.

### 5.1 Pré-requis

- Phase 0 (= confirmer pas de boulot Mac non poussé) — déjà fait par
  l'opérateur 2026-06-19. `ml:db:release` côté Mac a confirmé que la
  machine ne tient pas le lease.
- Phase 3 complète (sinon le frontend lit encore Supabase / ML_API
  localhost, donc il dépend de la DB locale Mac/PC).

### 5.2 Surface code à supprimer

- `ml/store/lease.py` — module entier
- `ml/Taskfile.yml` — sections `db:status / db:acquire / db:release /
  db:sync / db:steal` (lignes ~538-561)
- Toute mention de `bootstrap_canonical` dans `ml/` (déjà retirée en C2,
  vérifier à nouveau)
- Toute mention de seed MinIO → eurio.db dans `infra/eurio-api/` (déjà
  retirée en C2, vérifier)
- Variables d'env / SOPS : `MINIO_*` côté eurio-api uniquement pour
  assets (`enrichment-crops` etc.) — garder, juste vérifier que rien ne
  pointe vers `eurio-db` bucket

### 5.3 Suppression côté MinIO

**Manuel, après cutover validé** :

```bash
# Lister les objets restants
mc ls --recursive eurio/eurio-db
# Sauvegarder une dernière copie locale (par sécurité, hors MinIO)
mc cp eurio/eurio-db/eurio.db /tmp/eurio-db-final-snapshot-$(date +%F).db
# Supprimer le bucket
mc rb --force eurio/eurio-db
```

⚠ Ne PAS faire `mc rb` avant d'être sûr à 100% que le VPS local fonctionne
comme source de vérité, **et** d'avoir testé le restore depuis backup
encrypté (`infra/backup/eurio-backup.sh`) au moins une fois.

### 5.4 Backups

S'assurer que `infra/backup/eurio-backup.sh` capture bien :
- `/opt/eurio/infra/eurio-api/data/eurio.db` (canonical, fait déjà)
- `/opt/eurio/infra/eurio-api/data/review.db` (séparé)
- volumes Authentik (cf. RESUME §3.11)

### 5.5 Critères d'acceptation phase 5

- [ ] `ml:db:*` go-tasks n'existent plus
- [ ] `ml/store/lease.py` supprimé
- [ ] `grep -rn "eurio-db" ml/ infra/` → uniquement dans docs/archive ou commentaires explicatifs
- [ ] Backup quotidien testé restorable (script `infra/backup/README-RESTORE.md`)
- [ ] (Manuel) bucket MinIO `eurio-db` supprimé

### 5.6 Effort

~2-3h. Bloqué par Phase 3.

## 6. Phase 6 — (Optionnel) ML compute local en client HTTP de eurio-api

**But** : faire que le code Python qui tourne sur Mac/PC (crops, scraping,
training) push ses résultats via HTTP vers eurio-api au lieu d'écrire
en direct dans une DB SQLite locale.

### 6.1 Pourquoi optionnel

- C'est un refactor lourd côté `ml/` (10-15 modules)
- Latence réseau : un crop = 1-N appels HTTP au lieu d'un INSERT local.
  À mesurer avant de décider si on l'accepte.
- Alternative : garder le ML local qui écrit dans `eurio.db` local en
  WAL mode, sync périodique (push) vers VPS via API batch.

### 6.2 Options à l'étude

- **6a — Tout en HTTP** : chaque write → POST vers eurio-api. Simple,
  latence à valider sur un workflow réel (crop d'une lot de 50 listings).
- **6b — Write-through cache** : ML local maintient une copie SQLite
  read-cache, écrit en HTTP + cache invalidate.
- **6c — Outbox pattern** : ML écrit en local + outbox table, un worker
  pousse en batch vers eurio-api. Robustesse offline + perf.

À discuter en ouvrant le sujet, **pas avant Phase 5 complète**.

## 7. Risques et open questions

### 7.1 Concurrent writes côté eurio-api

SQLite WAL mode supporte multiple readers + 1 writer. Si plusieurs Mac/PC
push en parallèle via eurio-api, les transactions sérialisées par SQLite
fonctionneront, mais latence possible. À monitorer sous charge.

→ Mitigation : la plupart des writes éditoriales sont peu concurrentes
(un dev à la fois). Si problème → réfléchir à un queue/worker.

### 7.2 Schéma drift

Aujourd'hui, les schémas SQLite éditoriaux sont définis dans `ml/state/schema.sql`
(legacy) + `ml/serving/migrations/*.sql` (auth-redesign). Migrations
futures pour les endpoints CRUD : étendre `ml/serving/migrations/`
avec une convention claire (`NNNN_description.sql` numéroté).

### 7.3 Sync Supabase → Android

Hors scope immédiat. Quand on sera prêt :
- Étendre `ml/export/sync_to_supabase.py` aux tables manquantes
  (aujourd'hui : `coins`, `source_observations`, `coin_market_prices`)
- Cron ou trigger après mutations VPS

### 7.4 Friends-review feature

Reste défférée (cf. memory `project_friends_review_deferred`). Une fois
phase 5 OK, le container `eurio-review` legacy peut être stoppé sans
risque (sa data est déjà absorbée par `eurio-api` C4).

### 7.5 `useReviewApi.ts` legacy `/review-queue/*`

Le composable `useReviewApi` tape `/review-queue/*` legacy, **pas**
`/review/*` C4. Quand on porte vers eurio-api, soit :
- (a) Recréer `/review-queue/*` dans eurio-api en gardant la même shape
  (port direct)
- (b) Refactor le frontend pour utiliser `/review/*` C4 (changement
  d'API surface)

(a) est plus rapide, (b) est plus propre long-terme. À trancher au
moment du refactor.

## 8. Ordre d'opérations recommandé

```
Phase 1 (orphan tables) ──┐
                          ├─► Phase 2 (endpoints, par batch) ──┐
                          │                                    │
                          │   ┌── Phase 3 (refactor composables, en parallèle de 2) ──┐
                          │   │                                                       │
                          └───┴── Phase 4 (drop @supabase/supabase-js) ───────────────┤
                                                                                      ▼
                                                                              Phase 5 (kill MinIO eurio-db)
                                                                                      │
                                                                                      ▼
                                                                              Phase 6 (optionnel, ML HTTP client)
```

**Commit-flow conseillé** :
- 1 commit par phase 1 complète
- Pour phase 2/3 : commits incrémentaux par domaine (`feat(coins-api)`,
  `feat(sources-api)`, etc.), avec refactor composable correspondant
  dans le même commit ou un commit lié
- Phase 4 : 1 commit dédié `chore(studio-local): drop Supabase`
- Phase 5 : 1 commit dédié `chore: kill MinIO eurio-db + lease workflow`

## 9. Outils utiles pendant le chantier

### Inspecter eurio.db

```bash
docker exec eurio-api python -c "
import sqlite3
c = sqlite3.connect('/var/lib/eurio/eurio.db')
c.row_factory = sqlite3.Row
# Schema d'une table
for r in c.execute(\"SELECT sql FROM sqlite_master WHERE name='coins'\"):
    print(r[0])
# Sample row
for r in c.execute('SELECT * FROM coins LIMIT 1'):
    print(dict(r))
"
```

### Smoke test API

```bash
PAT='eurio_xxx'  # depuis .env.local
curl -sS -H "Authorization: Bearer $PAT" \
    https://eurio-api.musubi.dev/coins?limit=3 | jq .
```

### Comparer studio-local avant/après refactor

```bash
# Snapshot pre-refactor du JSON renvoyé
curl -sS -H "Authorization: Bearer $PAT" \
    https://eurio-api.musubi.dev/coins/euro_1c_fr_2002 > /tmp/coin-new.json
# Idem côté Supabase (référence)
curl -sS "$SUPABASE_URL/rest/v1/coins?eurio_id=eq.euro_1c_fr_2002" \
    -H "apikey: $SUPABASE_ANON_KEY" > /tmp/coin-supa.json
diff <(jq -S . /tmp/coin-new.json) <(jq -S . /tmp/coin-supa.json)
```

### Backup avant chaque phase

```bash
sudo cp -av /opt/eurio/infra/eurio-api/data/eurio.db \
       /opt/eurio/infra/eurio-api/data/eurio.db.bak-pre-phase-N-$(date +%Y%m%d-%H%M%S)
```

## 10. Aller au-delà de cette session

Quand la phase actuelle est terminée :
1. Mettre à jour la table de suivi en §8 (statut par phase)
2. Mettre à jour la mémoire (`~/.claude/projects/-opt-eurio/memory/project_data_unification.md`)
3. Commit un `docs(data-unification): marquer phase N ✅` après chaque jalon
4. Lire la phase suivante avant de coder

---

**Sources consultées 2026-06-19** :
- Lease state vérifié OK (Mac n'a pas le lease, dernier release 2026-06-17)
- `mc cp eurio/eurio-db/eurio.db` → 99MB, SHA256 cohérent
- `sqlite3` inspect : 65 tables canonical = 65 tables VPS (row counts identiques sur les tables non-vides)
- 24 fichiers studio-local touchent Supabase, 32 touchent `ML_API` localhost
