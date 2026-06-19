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
| **2b** | Endpoints `/sources/*` (READ) — **layered pattern, première fois** | ⬜ | 4-6h |
| **2c** | Endpoints `/review-queue/*` (READ) | ⬜ | 2-3h |
| **2d** | Endpoints `/training-runs/*` (READ) | ⬜ | 2-3h |
| **2e** | Endpoints `/mints`, `/referential`, `/cohorts`, `/bench`, `/augmentation` | ⬜ | 3-4h |
| **3** | Refactor composables studio-local restants vers eurio-api | ⬜ | 1-2j |
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

## Phase 2b ⬜ — Sources READ (next)

**Objectif** : porter les endpoints `/sources/*` lecture seule sur
`eurio-api`, refactor des composables sources studio-local.

**Inaugurera le pattern layered** (`models / repository / service / router`).
C'est la première application en grandeur réelle de l'architecture cible
décrite dans `ARCHITECTURE.md`.

Périmètre :
- ~15 endpoints read-only : status, source detail, runs list, run
  snapshot, funnel, breakdown, listings, searches, discarded, log,
  ebay/{filter-config, freshness-groups, marketplace-map, quota-status}
- 6 composables studio-local : `useSourcesApi`, `useSourceDetail`,
  `useRun{Funnel,Breakdown,Listings,Discarded,Searches}`,
  `useMarketplaceMap`, `useFilterConfig`
- **Hors scope** : endpoints write/trigger (`POST /sources/{id}/runs`,
  retry, crop-pending) — restent sur `localhost:8042` jusqu'à Phase 6

Cf. `HANDOFF-NEXT-SESSION.md` pour le plan d'exécution détaillé.

## Phase 2c ⬜ — Review queue READ

Endpoints `/review-queue/*` (legacy, distinct du `/review/*` C4 — cf.
décision DECISIONS.md). 5773 rows dans `review_queue`. Composables :
`useReviewApi`, `useLotReview`, `useTextSignals`, `useDinoSuggestions`.

Choix à faire : on garde le préfixe legacy `/review-queue/*` ou on
recompose vers `/review/*` C4 ? À discuter en début de session.

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
| `useSourcesApi` | 2b | ⬜ |
| `useSourceDetail` | 2b | ⬜ |
| `useRunFunnel` | 2b | ⬜ |
| `useRunBreakdown` | 2b | ⬜ |
| `useRunListings` | 2b | ⬜ |
| `useRunDiscarded` | 2b | ⬜ |
| `useRunSearches` | 2b | ⬜ |
| `useMarketplaceMap` | 2b | ⬜ |
| `useFilterConfig` | 2b | ⬜ |
| `useReviewApi` (legacy `/review-queue/*`) | 2c | ⬜ |
| `useLotReview` | 2c | ⬜ |
| `useTextSignals` | 2c | ⬜ |
| `useDinoSuggestions` | 2c | ⬜ |
| `useTrainingApi` | 2d | ⬜ |
| `useReferentialApi` | 2e | ⬜ |
| `useBenchApi` | 2e | ⬜ |
| `useCropBenchApi` | 2e | ⬜ |
| `useOperationsApi` | 2e | ⬜ |
