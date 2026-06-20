# Roadmap — data-layer unification

> Source de vérité de la **progression**. Mise à jour à la fin de chaque
> phase / sous-chunk. Cf. `IMPLEMENTATION-NOTES.md` (à venir) pour les
> détails techniques par phase.

## Statuts

- ✅ done
- 🟡 in-progress
- ⬜ todo
- ❌ abandonné / superseded

## Vue d'ensemble

| Phase | Description | Statut | Effort |
|---|---|---|---|
| **0** | Données canoniques sur VPS (état initial validé) | ✅ 2026-06-19 | — |
| **1** | Orphan tables Supabase (`coin_confusion_map`, `sets_audit`) | ✅ 2026-06-19 | 4h |
| **2a** | Endpoints `/coins/*` + refactor composables coins studio-local | ✅ 2026-06-19 | 3h |
| **2b** | Endpoints `/sources/*` (READ) — **layered pattern, première fois** | ✅ 2026-06-20 | ~5h |
| **2c** | Endpoints `/review-queue/*` (READ) | ✅ 2026-06-20 | ~6h |
| **2d** | Endpoints `/training-runs/*` (READ) | ⬜ | 2-3h |
| **2e** | Endpoints `/mints`, `/referential`, `/cohorts`, `/bench`, `/augmentation` | ⬜ | 3-4h |
| **3** | Refactor composables studio-local restants vers eurio-api | 🟡 immédiats 2026-06-20 | 1-2j |
| **4** | Drop `@supabase/supabase-js` du studio-local | ⬜ | 30min |
| **5** | Kill MinIO `eurio-db` bucket + `ml/store/lease.py` + `ml:db:*` tasks | ⬜ | 2-3h |
| **6** | ML compute local = client HTTP de eurio-api | ⬜ | 3-5j |

## Phase 0 ✅ — État initial vérifié

**2026-06-19** — Vérifié que `/opt/eurio/infra/eurio-api/data/eurio.db` (VPS local)
contient déjà les 65 tables éditoriales identiques au canonical MinIO du
2026-06-17 + 6 tables auth ajoutées par migrations C2. **Pas de migration data
à faire** côté éditorial — la donnée est déjà sur VPS.

Test : Mac ne tient pas le lease (`go-task ml:db:release` → "REFUSÉ"), aucun
travail non poussé. État du VPS = source de vérité.

## Phase 1 ✅ — Orphan tables Supabase

**2026-06-19** — Commits `cc4b7e92` (feat Phase 1).

Livré :
- Migration `0002_orphan_supabase_tables.sql` (idempotent, appliquée
  au startup) — crée `coin_confusion_map` + `sets_audit` en SQLite
- Script `ml/serving/migrate_orphan_supabase.py` (réutilisable)
- Endpoints `/confusion-map/{stats,pairs,coin/{id},zone-map}`
- Endpoint `/audit/sets`
- Refactor `useConfusionMap.ts` + `AuditPage.vue` côté studio-local
- **Finding** : `coin_confusion_map` et `sets_audit` n'existent **pas**
  dans Supabase (schéma "app-facing v2" évolué). Le frontend faisait
  du 404 silencieux. Tables SQLite restent vides en attendant que les
  pipelines ML les peuplent.

## Phase 2a ✅ — Coins

**2026-06-19** — Commit `fca3d167`.

Livré :
- `coins_routes.py` étendu : filtres list_coins (year, series_id,
  variant_kind, min/max_mintage) + 3 endpoints cross-refs
  (`GET/PUT/DELETE /coins/{id}/cross-refs/{ref_type}`)
- `useCoinsApi.ts` : helper `json` → `eurioApi.*` (20+ endpoints
  refactorés en un swap)
- `useArbitrage.ts` : Supabase → eurio-api ; sync cross_refs.numista_id
  via PUT cross-refs (mapping JSONB → table jointure)
- `useStagedCoins.ts`, `useCriteriaPreview.ts`, `CuratedMembersPicker.vue`
  refactorés
- **Studio-local typecheck 100% clean** (6 erreurs TS pré-existantes
  éliminées par effet de bord)

## Phase 2b ✅ — Sources READ

**2026-06-20** — Première application du pattern layered (cf.
`ARCHITECTURE.md`) en grandeur réelle.

Livré :
- `serving/deps.py` — dependency FastAPI `db_connection()` partagée
- `serving/sources/` — domain layered (models / repository / service / router) :
  - `models.py` (24 Pydantic schemas)
  - `repository.py` (SQL pur, sqlite3 stdlib only)
  - `service.py` (registry statique + business logic /sources/status et /sources/{id})
  - `router.py` (15 endpoints, tous sous `require_scope("sources:read")`)
- Câblage `server_serve.py` : `include_router(sources_router)` inconditionnel
  (pas de skip dynamique — le module ne dépend pas de PIL/cv2/torch)
- 15 endpoints READ portés :
  - `/sources` · `/sources/status` · `/sources/{id}` · `/sources/{id}/runs`
  - `/source-runs/{run_id}` · `/funnel` · `/breakdown` · `/listings` ·
    `/searches` · `/discarded` · `/log`
  - `/sources/ebay/quota-status` · `/marketplace-map` · `/filter-config` ·
    `/freshness-groups`
- 9 composables studio-local refactorés vers `eurioApi.get<T>(...)` (PAT) :
  - `useSourcesApi`, `useSourceDetail`, `useRunFunnel`, `useRunBreakdown`,
    `useRunListings`, `useRunDiscarded`, `useRunSearches`,
    `useMarketplaceMap`, `useFilterConfig`
- URL refactor (côté API & front) : `/sources/{id}/runs/{run_id}/X` →
  `/source-runs/{run_id}/X` (run_id globalement unique)
- Déviations documentées dans DECISIONS.md §D-09 (quota live, deltas prix,
  log file FS — non portés en Phase 2b, fallback front existant)

**Studio-local typecheck ✅ clean · build ✅ ok · 15 endpoints smoke ✅ 200**

Hors scope (déférré) :
- Endpoints write/trigger (`POST /sources/{id}/runs`, retry, crop-pending,
  rescue) — restent sur `localhost:8042` (Phase 6)
- File-serving (`/sources/{id}/{raws,assets}/.../file`) — reste sur
  `localhost:8042` (les fichiers vivent côté workstation, pas synchronisés)
- `/sources/{id}/images` · `/quotes` · `/coverage` — Phase 2c ou 2e

## Phase 2c ✅ — Review queue READ (2026-06-20)

**Phase 2c-a (commit `3aa29a44`)** :
- Domaine `serving/review_queue/` (layered, pas de dep ML)
- Endpoints `GET /review-queue/{healthcheck,stats,rejected,
  {review_id}/text-signals, asset/{asset_id}/text-signals}`
- Composables refactorés : `useTextSignals` (full), `useReviewApi`
  (`fetchReviewStats`, `fetchRejectedCrops`, `fetchMarketQuotes`)
- Bonus Phase 2b : `/sources/ebay/market-quotes` (utilisé par
  `useReviewApi.fetchMarketQuotes` — défaut SQL legacy corrigé)

**Phase 2c-b (commit `<2c-b>`)** :
- 5 endpoints lourds : `/review-queue` (list), `/{review_id}` (detail),
  `/triage-stats`, `/lots` (list), `/lots/{listing_key}` (detail)
- Port pure-Python de `compute_auto_validate_verdict` dans `service.py`
  (mirror exact du legacy `training/foundation/auto_validate.py`) +
  `DINO_VERDICT_THRESHOLDS`
- Port pure-Python de `design_group_lot_scope` (helper sources.ebay
  non livré sur lean image)
- Helpers `_row_to_item`, `_build_target_candidate`,
  `_build_dino_top1_candidate`, `_fetch_group_candidates`,
  `_fetch_standard_candidates` portés
- Composables : `useReviewApi.fetchReviewQueue/fetchReviewItem/
  fetchTriageStats` → eurioApi ; `useLotReview.fetchLots/fetchLot` → eurioApi
- `/lots/{key}` : version sans re-détection live (cv2 absent), lit les
  détections persistées dans `source_images.detections_json`. La
  re-détection live et POST decide restent sur ML_API legacy (Phase 6).

## Phase 2d ⬜ — Training READ

Endpoints `/training-runs/*` et sous-ressources (epochs, steps, logs,
classes). Composable `useTrainingApi`. 34 runs + 534 epochs en data.

## Phase 2e ⬜ — Reste éditorial

Mints (29), coin_credits (1350), coin_topics (1795), coin_observations
(10626), design_groups (46), referential_catalog, augmentation_recipes,
benchmark_runs, cohort_jobs, image_assets. Endpoint par domaine, layered
pattern.

## Phase 3 ⬜ — Refactor composables restants

Tous les composables studio-local qui pointent encore `localhost:8042`
basculent vers `eurioApi`. Pattern :
```ts
- await fetch(`${ML_API}/path`)
+ await eurioApi.get<T>('/path')
```

## Phase 4 ⬜ — Drop `@supabase/supabase-js`

- Retirer `@supabase/supabase-js` de `admin/packages/studio-local/package.json`
- Supprimer `src/shared/supabase/`
- Vite config : retirer `define:` des `VITE_SUPABASE_*`
- `.envrc.example` : retirer les exports

Smoke : `pnpm install && pnpm studio:build` clean.

## Phase 5 ⬜ — Kill MinIO eurio-db

- Supprimer `ml/store/lease.py` + tâches go-task `ml:db:{status,acquire,release,sync,steal}`
- Retirer toute ref au seed MinIO (déjà fait en C2, vérifier)
- Backup quotidien VPS vérifié restorable (test restore depuis pCloud)
- `mc rb --force eurio/eurio-db` (manuel, dernière étape)

## Phase 6 ⬜ — ML compute local → client HTTP eurio-api

Le code Python sur Mac/PC :
- N'écrit plus en local sur `eurio.db`
- Devient un client HTTP de `eurio-api.musubi.dev` (PAT via env var)
- Endpoints à ajouter : `POST /source-runs`, `PATCH /source-runs/{id}/funnel`,
  `POST /coin-observations` (batch), `POST /image-assets`, etc.

Refactor lourd côté `ml/sources/_base/orchestrator.py` + steps + storage.

Effort estimé : 3-5j. À traiter dans son propre handoff.

## Tracking par fichier

À mesure que les composables sont refactorés, mettre à jour cette table
(0 = touche encore `localhost:8042` ou `supabase`, 1 = utilise `eurioApi`).

| Composable | Phase | Statut |
|---|---|---|
| `useConfusionMap` | 1 | ✅ |
| `AuditPage` (sets_audit) | 1 | ✅ |
| `useCoinsApi` (20+ endpoints) | 2a | ✅ |
| `useArbitrage` | 2a | ✅ |
| `useStagedCoins` | 2a | ✅ |
| `useCriteriaPreview` | 2a | ✅ |
| `CuratedMembersPicker` | 2a | ✅ |
| `useCoinsReview` | 2a | ⬜ (à vérifier — pas explicitement traité) |
| `useNumistaReview` | 2a | ⬜ |
| `useCoinAssets` | 2a | ⬜ |
| `useCoinLookups` | 2a | ⬜ (fetchZoneMap = ✅ via confusion-map, reste = ?) |
| `useSourcesApi` | 2b | ✅ |
| `useSourceDetail` | 2b | ✅ (POST + images/quotes/coverage encore legacy) |
| `useRunFunnel` | 2b | ✅ |
| `useRunBreakdown` | 2b | ✅ |
| `useRunListings` | 2b | ✅ (file URLs restent legacy) |
| `useRunDiscarded` | 2b | ✅ |
| `useRunSearches` | 2b | ✅ |
| `useMarketplaceMap` | 2b | ✅ |
| `useFilterConfig` | 2b | ✅ |
| `useReviewApi` (READ) | 2c | ✅ (queue/item/triage/stats/rejected/market-quotes — POST/heavy = legacy) |
| `useLotReview` (READ) | 2c-b | ✅ (fetchLots/fetchLot — POST decide/detect/addCrop = legacy) |
| `useTextSignals` | 2c | ✅ |
| `useDinoSuggestions` | 6 | ⬜ (heavy deps — laisser ML local) |
| `useOperationsApi` | 3 | ✅ |
| `usePeerArbitrationApi` | 3 | ✅ |
| `useTrainingApi` | 2d | ⬜ |
| `useReferentialApi` | 2e | ⬜ |
| `useBenchApi` | 2e | ⬜ |
| `useCropBenchApi` | 2e | ⬜ |
| `useOperationsApi` | 2e | ⬜ |
