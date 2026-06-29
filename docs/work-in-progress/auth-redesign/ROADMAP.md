> 📜 **HISTORIQUE / quasi-terminé.** Backend auth (C1-C4) + front (F1-F9) livrés.
> Le volet **front** (dual `studio-local`/`admin-vps`) est **supersédé par la fusion**
> — cf. [`../model-b/README.md`](../model-b/README.md) §Front + §R1. Reste data D2/D7
> (dernier `supabase.from`) + cleanup K1-K4.

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
| F5 | Studio-local : rip auth Supabase OTP (LoginPage + AuthCallbackPage + guard) | ✅ 2026-06-19 (`0939b84`) | pages/guard supprimés ; reliquat = client *data* Supabase (cf. D2/D6/D7) |
| F6 | Admin-vps : vue Users (table + édition rôles) | ✅ 2026-06-19 (`4eb980c`) | `admin-vps/src/views/users/UsersPage.vue` |
| F7 | Admin-vps : vue Mes Tokens (CRUD PAT, modale clair une fois) | ✅ 2026-06-19 (`5a2669a`) | `admin-vps/src/views/tokens/MyTokensPage.vue` |
| F8 | Admin-vps : layout responsive mobile-first (drawer + bottom-nav) | ✅ 2026-06-29 (à valider sur vrai tel) | `AppShell.vue` + `composables/useSidebarMode.ts` + `components/navIcons.ts` |
| F9 | Admin-vps : dashboard KPIs (counts coins / sets / sources / review) | ✅ 2026-06-29 | `views/Home.vue` + `api/stats.ts` + `ml/serving/stats_routes.py` |

## Data (post-pivot — dégonflé)

| # | Chantier | Statut |
|---|---|---|
| D1 | Audit Supabase tables réellement frontées (2026-06-19) | ✅ 4 tables seulement : `coins`, `coin_confusion_map`, `coin_series`, `sets_audit` |
| D2 | Migration `coin_series` → SQLite (seed canonique) + endpoint `eurio-api` | 🟡 en cours (2026-06-29) — seed n'existait qu'en Supabase ; refactor `enrich_coins_metadata.py` PostgREST → Store |
| D3 | Migration `coin_confusion_map` → SQLite + endpoint | ✅ data-layer-unification Phase 1 (`confusion_routes.py`) |
| D4 | Migration `sets_audit` → SQLite + endpoint | ✅ data-layer-unification Phase 1 (`audit_routes.py`) |
| D5 | Migration `coins` → SQLite + endpoints CRUD limités | ✅ data-layer-unification Phase 2a (`fca3d167`, `coins_routes.py`) |
| D6 | Refactor studio-local : composables Supabase → `eurio-api` Bearer | 🟡 en cours — la plupart ✅ ; reliquat = `useCoinSeries` (D2) + composables heavy (Phase 6) |
| D7 | Suppression du client Supabase frontend (`@supabase/supabase-js`) après D2-D6 | ⬜ bloqué par le dernier `supabase.from('coin_series')` de `useCoinSeries.ts` |

> **Source de vérité data** : ces chunks D2–D7 sont **supersédés en pratique** par
> `docs/work-in-progress/data-layer-unification/` (effort plus mature, pattern layered).
> Voir sa `ROADMAP.md` (tracking par composable) et son `ARCHITECTURE.md` (conventions endpoints).

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
