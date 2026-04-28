# `/sources` — page admin de contrôle des sources externes

Panneau de contrôle unique pour les sources d'ingestion : Numista, eBay, LMDLP,
Monnaie de Paris, BCE, Wikipedia. Quota, dernier fetch, couverture, delta.

## Plan

| Doc | Sujet |
|---|---|
| **[implementation-plan.md](./implementation-plan.md)** | **🚧 Plan d'action consolidé pour livrer le backend + brancher les vraies données. À lire en premier si tu prends la suite du chantier.** |
| [vision.md](./vision.md) | Pourquoi cette page, principes, scope, non-goals |
| [frontend.md](./frontend.md) | UI/UX, composants, layout (livré, mocké) |
| [backend.md](./backend.md) | Endpoint `/sources/status`, agrégation, contrats |
| [quotas.md](./quotas.md) | Refacto `numista_key_usage` → `api_call_log` générique |
| [temporal.md](./temporal.md) | Détection nouvelles pièces, deltas, historique prix |
| [v2-triggering.md](./v2-triggering.md) | Notes pour V2 — pourquoi non-trivial, archi |

## TL;DR

V1 = lecture seule. Une grille 2-col, une carte par source, polling 10s sur
`GET /sources/status`. Fetch via UI = V2 (job runner non-trivial).

## État

- ✅ Frontend Vue livré (mocké) — `admin/packages/web/src/features/sources/`
- ✅ Nav + route câblés
- ❌ Backend, helpers CLI, instrumentation quotas, snapshots prix → cf. [`implementation-plan.md`](./implementation-plan.md)
