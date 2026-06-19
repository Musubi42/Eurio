# ROADMAP — auth-redesign (chunks d'implémentation)

> Découpage en chunks autonomes, chacun avec son propre `Cx-HANDOFF-*.md`.
> Une session future (Claude Code ou humain) prend un chunk, l'exécute, met à
> jour le statut ici, puis remonte un résumé.
>
> **Pré-requis transverse** : lire `DESIGN.md` **et**
> [`RESUME-NEXT-SESSION.md`](./RESUME-NEXT-SESSION.md) (findings + déviations
> cumulés depuis la session du 2026-06-19) avant de démarrer un chunk.

## Statuts

- ⬜ todo
- 🟡 in-progress
- ✅ done
- ⏸️ blocked (raison)

## Tableau

| # | Chunk | Statut | Dépend de | Handoff |
|---|---|---|---|---|
| C1 | Provisioning Authentik (OIDC app + groups) | ✅ 2026-06-19 (flow E2E validé : login OIDC + cookie posé + user upserté + rôles synchronisés) | — | [`C1-HANDOFF-AUTHENTIK.md`](./C1-HANDOFF-AUTHENTIK.md) |
| C1.5 | Bootstrap déploiement `infra/eurio-api/` sur VPS (compose, secrets, Traefik, healthcheck) | ✅ 2026-06-19 (eurio-api.musubi.dev → 200 /healthz, auth gating actif) | C1 | (dans C2 §0 — sous-section dédiée) |
| C2 | `eurio-api` : middleware JWT + tables RBAC + `/me` | ✅ 2026-06-19 (commit e42a4e4d ; flow OIDC complet validé : login → callback → cookie → user/roles/audit en DB) | C1, C1.5 | [`C2-HANDOFF-API-RBAC.md`](./C2-HANDOFF-API-RBAC.md) |
| C3 | Tokens API personnels (modèle + endpoints + vérif machine) | ✅ 2026-06-19 (PAT format eurio_<43 base64url>, table pat_tokens, /me/tokens GET/POST/DELETE, intersection scopes vérifiée à chaque usage, break-glass grant-owner CLI) | C2 | [`C3-HANDOFF-TOKENS.md`](./C3-HANDOFF-TOKENS.md) |
| C3.5 | Polish pré-front (cookie env-aware, /auth/dev/login, /me name, require_principal global, factories require_scope/role) | ✅ 2026-06-19 (commit 42c6805d ; débloque C5 dev local + C7a/C7b) | C3 | (inline dans le commit) |
| C4 | Absorption `review_service` dans `eurio-api` | ✅ 2026-06-19 (routes /review/* portées avec Principal + scopes ; review.db séparé bootstrappé idempotent ; container eurio-review legacy intact en parallèle) | C2, C3.5 | [`C4-HANDOFF-MERGE-REVIEW.md`](./C4-HANDOFF-MERGE-REVIEW.md) |
| C4 | Absorption `review_service` dans `eurio-api` | ⬜ | C2 | [`C4-HANDOFF-MERGE-REVIEW.md`](./C4-HANDOFF-MERGE-REVIEW.md) |
| C5 | Panel : skeleton Vue + login OIDC + shell | ✅ 2026-06-19 (admin/packages/panel créé, Vue 3 + Vite + Pinia + Router strict TS, AppShell + Login + Home + NotAuthorized + placeholders, router guard par scope, dev bypass aware ; build 38KB gzip, typecheck OK) | C2 | [`C5-HANDOFF-PANEL-SHELL.md`](./C5-HANDOFF-PANEL-SHELL.md) |
| C6 | Panel : portage des écrans review | ⬜ | C4, C5 | [`C6-HANDOFF-PORT-REVIEW.md`](./C6-HANDOFF-PORT-REVIEW.md) |
| C6.5 | Migration data Supabase → `eurio.db` SQLite (schéma + data + switch code `supabase_client` → `sqlite3`) | ⬜ | C2 | (handoff à écrire — esquisse ci-dessous) |
| C7a | Panel : portage editorial core (sources / coins / audit / referential) + endpoints `eurio-api` correspondants | ⬜ | C5, C6.5 | [`C7-HANDOFF-PORT-WEB.md`](./C7-HANDOFF-PORT-WEB.md) §C7a |
| C7b | Panel : portage sets & analytics (sets / criteria-preview / design-groups / confusion / fragment-audit / crop-recovery / denom-gold / parity / lab) + endpoints correspondants | ⬜ | C7a, C6.5 | [`C7-HANDOFF-PORT-WEB.md`](./C7-HANDOFF-PORT-WEB.md) §C7b |
| C8 | Panel : UI users + UI mes tokens | ⬜ | C3, C5 | [`C8-HANDOFF-USERS-UI.md`](./C8-HANDOFF-USERS-UI.md) |
| C9 | Cutover : déploiement VPS, kill Vercel + Supabase Auth + `review_service`, archive | ⬜ | C6, C7a, C7b, C8 | [`C9-HANDOFF-CUTOVER.md`](./C9-HANDOFF-CUTOVER.md) |

## Chemin critique

```
C1 ─▶ C1.5 ─▶ C2 ─┬─▶ C3 ─▶ C8 ─┐
                  ├─▶ C4 ─▶ C6 ─┤
                  └─▶ C5 ─▶ C7a ─▶ C7b ─┴─▶ C9
```

C1 → C1.5 (déploiement `eurio-api`) → C2 sont strictement séquentiels : C2 ne peut être testé E2E (callback OIDC, `/me`) sans un `eurio-api` joignable sur `eurio-api.musubi.dev`. Une fois C2 mergé, C3, C4 et C5 sont parallélisables si plusieurs sessions tournent. C7 est **scindé** en C7a (editorial core) → C7b (sets & analytics) pour garder des chunks lisibles. C9 est le cutover final all-in (cf. DESIGN.md D9), à ne déclencher qu'après C6 + C7a + C7b + C8 validés en coexistence test ≥ 7 jours.

## Conventions de chunk

Chaque `Cx-HANDOFF-*.md` doit contenir :

1. **But en 1 phrase** + ce que le chunk *ne fait pas*.
2. **Pré-requis** (chunks dépendants validés + état repo).
3. **Étapes** numérotées et exécutables.
4. **Critères d'acceptation** vérifiables (curl, requête DB, screenshot).
5. **Garde-fous** (ce qu'il ne faut pas casser, retours arrière).
6. **Résumé à produire** en fin de session (template).

Le chunk **n'invente pas** : si une déviation est nécessaire (lib manquante,
endpoint Authentik différent, schéma DB à ajuster), il la **note dans le
résumé** et met à jour `DESIGN.md` si la déviation est structurelle.

## C6.5 — esquisse (handoff complet à écrire avant exécution)

Décision DESIGN.md §9.1 : Supabase disparaît entièrement, y compris la donnée. Ce chunk porte les ~15 tables éditoriales de Supabase Postgres vers `eurio.db` SQLite, et bascule le code `ml/serving/` vers `sqlite3` direct.

**Étapes** :
1. **Audit Supabase** : inventaire des tables réellement utilisées (`supabase/migrations/*.sql` + `grep -rn "from(['\"]"` côté front + `grep -n "supabase\." ml/serving/`).
2. **Schéma cible SQLite** : transposer chaque table Postgres en SQLite (types `jsonb` → `TEXT`, arrays Postgres → `TEXT` JSON ou table de jointure selon usage, `timestamp with tz` → `TEXT` ISO, etc.). Sortie : `ml/state/editorial_schema.sql` (séparé du training schema pour clarté).
3. **Script de migration data** : `python -m serving.migrate_supabase_to_sqlite` qui :
   - `pg_dump --data-only --inserts <table>` ou requête PostgREST avec pagination ;
   - transforme les lignes (jsonb → str JSON, etc.) ;
   - insert dans SQLite.
   - **Idempotent** (CHECKSUM par table avant/après).
4. **Switch code** :
   - Remplacer chaque `supabase.from('coins').select(…)` par `sqlite3` direct.
   - Refactor `augmentation_routes`, `coins_review_routes` pour ne plus dépendre de `SupabaseClient`.
   - Supprimer `ml/serving/supabase_client.py` à la fin.
   - Supprimer `SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY` de l'env d'eurio-api (gardés en SOPS pour la durée du chunk au cas où on doive rejouer la migration).
5. **Tests** : par table, comparer `count(*)` + sample row entre Supabase et SQLite après migration.
6. **Cutover** : on switch eurio-api code sur SQLite, on relance, on valide. Si OK, on archive le `supabase_client.py` dans `docs/archive/`.

**Pré-requis** : C2 ✅ (les nouvelles tables auth coexistent avec les éditoriales dans `eurio.db`).

**Bloque** : C7a/C7b (qui ne peuvent porter les UIs avant que les endpoints `eurio-api` ne tapent sur SQLite local).

## Hors scope de la roadmap

Cf. `DESIGN.md` §9. En particulier : App Android, MinIO assets (séparé de la DB), SSH, pCloud, MCP.
