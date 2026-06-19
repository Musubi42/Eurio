# ROADMAP — auth-redesign (post-pivot 2026-06-19)

> **Pré-requis transverse** : lire d'abord [`ARCHITECTURE.md`](./ARCHITECTURE.md)
> (source de vérité depuis le pivot) puis [`RESUME-NEXT-SESSION.md`](./RESUME-NEXT-SESSION.md).
>
> Les anciens chunks C6/C7/C8/C9 ont été partiellement invalidés par le
> pivot architectural (dual frontend `studio-local` + `admin-vps`). Cette
> roadmap reflète la **nouvelle** trajectoire.

## Statuts

- ⬜ todo
- 🟡 in-progress
- ✅ done
- ⏸️ blocked (raison)
- ❌ abandonné / superseded

## Backend auth (livré)

| # | Chunk | Statut | Handoff |
|---|---|---|---|
| C1 | Provisioning Authentik (OIDC app + groups) | ✅ 2026-06-19 | [`C1-HANDOFF-AUTHENTIK.md`](./C1-HANDOFF-AUTHENTIK.md) |
| C1.5 | Bootstrap `infra/eurio-api/` VPS | ✅ 2026-06-19 | (inline) |
| C2 | `eurio-api` : middleware JWT + RBAC + `/me` | ✅ 2026-06-19 | [`C2-HANDOFF-API-RBAC.md`](./C2-HANDOFF-API-RBAC.md) |
| C3 | PAT (modèle + endpoints + intersection scopes) | ✅ 2026-06-19 | [`C3-HANDOFF-TOKENS.md`](./C3-HANDOFF-TOKENS.md) |
| C3.5 | Polish pré-front (cookie env-aware, dev login, require_principal global) | ✅ 2026-06-19 | (inline commit 42c6805d) |
| C4 | Absorption `review_service` dans `eurio-api` | ✅ 2026-06-19 | [`C4-HANDOFF-MERGE-REVIEW.md`](./C4-HANDOFF-MERGE-REVIEW.md) |

## Frontend (post-pivot)

| # | Chantier | Statut | Localisation |
|---|---|---|---|
| F1 | Squelette `admin-vps` (Vue 3 + auth OIDC + AppShell + guards) | ✅ 2026-06-19 (ex-C5, renommé) | `admin/packages/admin-vps/` |
| F2 | Déploiement `eurio-admin.musubi.dev` (Dockerfile + nginx + Traefik) | ✅ 2026-06-19 | `infra/eurio-admin/` |
| F3 | Foundations auth PAT côté `studio-local` (client + store + bandeau + .env.example) | ✅ 2026-06-19 | `admin/packages/studio-local/src/{shared/api,stores,shared/ui}` |
| F4 | Studio-local : génération + collage d'un PAT réel (E2E test) | ⬜ | manuel (cf. `PAT-WORKFLOW.md`) |
| F5 | Studio-local : rip auth Supabase OTP (LoginPage + AuthCallbackPage + guard) | ⬜ | `studio-local/src/features/auth/` + `app/router.ts` |
| F6 | Admin-vps : vue Users (table + édition rôles) | ⬜ | `admin-vps/src/views/users/` |
| F7 | Admin-vps : vue Mes Tokens (CRUD PAT, modale clair une fois) | ⬜ | `admin-vps/src/views/tokens/` |
| F8 | Admin-vps : layout responsive mobile-first (drawer + bottom-nav) | ⬜ | `admin-vps/src/components/AppShell.vue` + composants |
| F9 | Admin-vps : dashboard KPIs (counts coins / sets / sources / review) | ⬜ | nouveau `admin-vps/src/views/Home.vue` |

## Data (post-pivot — dégonflé)

| # | Chantier | Statut |
|---|---|---|
| D1 | Audit Supabase tables réellement frontées (2026-06-19) | ✅ 4 tables seulement : `coins`, `coin_confusion_map`, `coin_series`, `sets_audit` |
| D2 | Migration `coin_series` (SELECT only, 200 rows) → SQLite + endpoint `eurio-api` | ⬜ |
| D3 | Migration `coin_confusion_map` (SELECT only, ~1500 rows) → SQLite + endpoint | ⬜ |
| D4 | Migration `sets_audit` (SELECT only, ~100 rows) → SQLite + endpoint | ⬜ |
| D5 | Migration `coins` (SELECT + 1 UPDATE `cross_refs`, ~1500 rows) → SQLite + endpoints CRUD limités | ⬜ |
| D6 | Refactor studio-local : composables passent de Supabase → `eurio-api` Bearer | ⬜ |
| D7 | Suppression du client Supabase frontend (`@supabase/supabase-js`) après D2-D6 | ⬜ |

L'app Android continue à lire Supabase (mirror read-only). Sync descendant
SQLite → Supabase = `ml/export/sync_to_supabase.py` (déjà partiellement
implémenté, à étendre).

## Cleanup & doc

| # | Chantier | Statut |
|---|---|---|
| K1 | Suppression `admin/packages/review-admin/` (legacy auth régie reviewer) | ⬜ |
| K2 | Décision et exécution sur `admin/packages/review/` (mini-app reviewer) | ⬜ (cf. `ARCHITECTURE.md §7`) |
| K3 | Suppression handoffs obsolètes (C6/C7/C8/C9 originaux) ou marquage "superseded" | ⬜ |
| K4 | Spec markdown future "friends review" feature | ⬜ |

## Chunks originaux abandonnés / superseded

| # original | Sort post-pivot |
|---|---|
| C5 | ✅ renommé F1 (`admin-vps` au lieu de `panel`) |
| C6 (port review UI) | ❌ abandonné — studio-local a déjà ses écrans review legacy |
| C6.5 (data migration big-bang) | ❌ superseded par D1-D7 (mécanique, dégonflé) |
| C7a/C7b (port web vers panel) | ❌ inversé — c'est `studio-local` qui reste canonique |
| C8 (UI users/tokens) | ❌ superseded par F6/F7 (côté `admin-vps`) |
| C9 (cutover all-in) | ❌ plus de cutover unique — décommissionnement progressif via D7/K1/K2 |

## Hors scope

Cf. `DESIGN.md §9` + `ARCHITECTURE.md`. En particulier : App Android,
MinIO assets, SSH, pCloud, MCP. La feature "friends review" est différée
(cf. mémoire `project_friends_review_deferred`).
