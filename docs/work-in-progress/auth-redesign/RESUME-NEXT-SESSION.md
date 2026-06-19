# RESUME — reprise auth-redesign post-pivot 2026-06-19

> **Pour qui** : une session future (Claude Code ou humain) qui reprend la
> refonte auth après la grosse session du 2026-06-19.
>
> **⚠ Pivot architectural majeur en fin de session 2026-06-19 — lire d'abord
> [`ARCHITECTURE.md`](./ARCHITECTURE.md)**. Les handoffs C6/C7/C8/C9 originels
> sont en partie obsolètes : la cible n'est plus "un seul nouveau panel
> remplaçant web", mais **deux frontends séparés** (`studio-local` heavy +
> `admin-vps` light). Cf. §0bis ci-dessous.
>
> **Statut auth core** : C1 → C5 livrés et déployés. La suite (C6+) bascule
> sur la nouvelle direction.

## 0. Quick map

| Doc | Rôle |
|---|---|
| **[`ARCHITECTURE.md`](./ARCHITECTURE.md)** | **Source de vérité post-pivot 2026-06-19** : dual frontend studio-local + admin-vps, règles de placement features, auth PAT vs OIDC. À lire en premier. |
| [`PAT-WORKFLOW.md`](./PAT-WORKFLOW.md) | Comment générer / coller / révoquer un PAT côté studio-local. |
| [`admin-vps-SPEC.md`](./admin-vps-SPEC.md) | Spec du panel léger VPS (mobile-friendly, read-mostly). |
| [`DESIGN.md`](./DESIGN.md) | Cible auth backend (PAT, OIDC, RBAC). Reste valide. |
| [`HANDOFF.md`](./HANDOFF.md) | Historique d'ouverture (superseded). |
| [`ROADMAP.md`](./ROADMAP.md) | Statut courant des chunks. Mettre à jour en fin de chunk. |
| [`Cx-HANDOFF-*.md`](./) | Handoffs originaux. C6/C7/C8 **en partie obsolètes** depuis pivot. À lire avec recul. |
| **`RESUME-NEXT-SESSION.md`** | **Tu es ici.** Findings + corrections cumulées. |

## 0bis. Pivot du 2026-06-19 — résumé exécutif

Avant le pivot : la cible était "un nouveau panel `packages/panel/` from-scratch
qui remplace progressivement `packages/web/` (C7a/C7b), avec data Supabase
migrée vers SQLite (C6.5)".

Après pivot : **deux frontends parallèles, deux usages distincts** :

- `admin/packages/studio-local/` (ancien `packages/web/`) — heavy local
  Mac/PC sur `pnpm dev :5173`, auth **Bearer PAT** depuis `.env.local`.
  Conserve la majorité du code existant. C'est où raph code activement.
- `admin/packages/admin-vps/` (ancien `packages/panel/`) — light hosted
  sur `https://eurio-admin.musubi.dev`, auth **cookie OIDC**. Vues
  read-mostly + users/tokens + mobile-friendly. Pas de heavy compute
  (interdit par mixed content HTTPS → http://localhost:8042).

C6 du plan initial (port review UI dans panel) **abandonné** : `studio-local`
a déjà ses propres écrans review backed by `useReviewApi.ts → /review-queue/*`
legacy routes. Les vues review/* écrites brièvement dans panel ont été
supprimées.

C6.5 (data migration) **dégonflée** : audit factuel a montré que seules 4
tables Supabase sont touchées par le frontend (`coins`, `coin_confusion_map`,
`coin_series`, `sets_audit`). Migration mécanique, ~0.5j de travail, non
bloquante pour la suite.

Foundations livrées en fin de session :

- `infra/eurio-admin/` — Dockerfile multistage (node → nginx static) +
  docker-compose Traefik. `https://eurio-admin.musubi.dev` répond 200.
- `admin/packages/admin-vps/` — squelette auth OIDC déployé (Login redirect
  Authentik, Pinia store `/me`, AppShell, guards par scope).
- `admin/packages/studio-local/src/shared/api/eurio-api.ts` — wrapper Bearer
  PAT pour studio-local.
- `admin/packages/studio-local/src/stores/eurio-session.ts` — Pinia store
  `useEurioSession` (load `/me` au boot, status missing/invalid/ok).
- `admin/packages/studio-local/src/shared/ui/EurioSessionBanner.vue` — bandeau
  affiché si PAT manquant/invalide.
- `.env.example` + gitignore `.env.local` côté studio-local.

**Mémoires** : `project_frontend_dual`, `project_friends_review_deferred`.

## 1. État réel au 2026-06-19 (post-session)

### Ce qui marche déjà en prod sur le VPS

| Composant | URL / chemin | État |
|---|---|---|
| Authentik (IDP) | `https://authentik.musubi.dev` | ✅ 2025.10.0, app `eurio-panel`, 3 groupes `eurio-{owner,admin,reviewer}`, scope mapping `eurio_groups`, bindings, RS256 JWKS |
| `eurio-api` | `https://eurio-api.musubi.dev` | ✅ container up, healthz 200, OIDC flow E2E validé, PAT, review absorbé |
| `eurio.db` (SQLite) | `/opt/eurio/infra/eurio-api/data/eurio.db` | ✅ tables auth (`users`, `roles`, `user_roles`, `pat_tokens`, `auth_audit`, `_schema_migrations`) + métier (training, etc.) |
| `review.db` (SQLite) | `/opt/eurio/infra/eurio-api/data/review.db` | ✅ schéma C4 bootstrappé (`review_items`, `decisions`, `meta`) — séparé d'`eurio.db` |
| `admin-vps` (renamed from `panel`) | `admin/packages/admin-vps/` | ✅ déployé sur `https://eurio-admin.musubi.dev` via `infra/eurio-admin/` (nginx + Traefik), build 39KB gzip. Vues review/* supprimées en fin de session 2026-06-19. |
| `studio-local` (renamed from `web`) | `admin/packages/studio-local/` | ✅ code existant intact + foundations PAT auth (eurio-api client + Pinia store + bandeau) ajoutées. Auth Supabase OTP en cohabitation pour l'instant. |

### Ce qui reste à faire (re-priorisé post-pivot)

| Chantier | Localisation | Estimation | Bloquant ? |
|---|---|---|---|
| **Studio-local : générer PAT + tester E2E** | `studio-local` + CLI break-glass | 30 min | non |
| Rip Supabase auth de studio-local | `studio-local/src/features/auth/` | 1h | non (cohabitation OK pour l'instant) |
| Admin-vps : vue Users (CRUD rôles) | `admin-vps/src/views/users/` | 1h | non |
| Admin-vps : vue Mes tokens (PAT mgmt) | `admin-vps/src/views/tokens/` | 1h | non |
| Admin-vps : layout responsive mobile-first | `admin-vps/src/components/AppShell.vue` | 1-2h | bonus UX |
| Migration data Supabase → SQLite (4 tables) | `eurio-api` + studio-local refactor | 0.5-1j | non |
| Cleanup : suppression `packages/review-admin/` | `admin/packages/` | 5min | non |
| Spec friends-review (markdown) | docs | 30min | non |

C6 (original) **annulé**. C7a/b/C9 (originaux) **superseded** par la liste
ci-dessus.

## 2. Endpoints `eurio-api` actuellement live

(Tous testés E2E le 2026-06-19. Disponibles immédiatement pour C6/C8.)

### Auth + identité (C2 + C3.5)

| Méthode | Path | Auth | Notes |
|---|---|---|---|
| GET | `/healthz` | publique | Liveness |
| GET | `/auth/oidc/login?return_to=` | publique | Redirige vers Authentik avec PKCE+state |
| GET | `/auth/oidc/callback?code=&state=` | publique | Set cookie `eurio_session`, redirige vers `EURIO_PANEL_ORIGIN` |
| GET | `/auth/oidc/dev/login?email=&name=` | gated `EURIO_DEV_BYPASS=1` | Cookie de dev (refuse si prod) |
| POST | `/auth/oidc/logout` | cookie | 204 + clear cookie |
| GET | `/me` | cookie ou PAT | Renvoie `{user_id, email, name, roles, scopes, auth_method}` |

### Users (C2)

| Méthode | Path | Scope | Notes |
|---|---|---|---|
| GET | `/users` | `users:read` | Liste users + rôles |
| PUT | `/users/{id}/roles` | `users:manage` | Anti-lockout dernier owner |

### PAT (C3)

| Méthode | Path | Scope | Notes |
|---|---|---|---|
| GET | `/me/tokens` | `tokens:manage_own` | Liste user's tokens (jamais le clair) |
| POST | `/me/tokens` | `tokens:manage_own` | Body `{name, scopes, expires_at?}`, renvoie le clair **une fois** |
| DELETE | `/me/tokens/{id}` | `tokens:manage_own` | Soft-delete |

### Review (C4)

| Méthode | Path | Scope | Notes |
|---|---|---|---|
| GET | `/review/me/items` | `review:read` | Working set du user |
| POST | `/review/claim` | `review:write` | Claim atomique, window 10 |
| POST | `/review/items/{id}/decide` | `review:write` | `{action, eurio_id?, ...}` |
| POST | `/review/items/{id}/skip` | `review:write` | Relâche le claim |
| GET | `/review/me/stats` | `review:read` | `{total, today, user_id}` |
| GET | `/review/flow` | `review:read` | Compteurs + horodatages |
| GET | `/review/decisions?unreconciled=1` | `review:read` | Admin list |
| POST | `/review/publish` | `review:write` | UPSERT idempotent |
| POST | `/review/decisions/ack` | `review:write` | Marque `reconciled_at` |

### Métier legacy (migré sur `require_principal` en C3.5)

| Préfixe | Routes | Notes |
|---|---|---|
| `/coins` | `coins_routes` | OK via cookie OIDC ou PAT depuis C3.5 |
| `/sets` | `sets_routes` | idem |
| `/operations` | `operations_routes` | idem |
| `/peer_arbitration` | `peer_arbitration_routes` (review/) | idem |
| `/ingest` | `ingest_routes` | idem, cœur garanti |

**Skipped au boot** (déps lourdes absentes de l'image lean) :
- `referential` (PIL) — à débloquer plus tard si C7a en a besoin
- `review_queue`, `coin_assets` (cv2) — restent OFF par design

## 3. Décisions/déviations actées dans la session

### 3.1 Format PAT : `eurio_<43 base64url>` (pas base32)

L'arithmétique base32 donne 52 chars pour 256 bits, pas 43. **base64url RFC 4648 sans padding** donne exactement 43 chars pour 32 bytes. Implémenté via `secrets.token_urlsafe(32)`. DESIGN.md §5.1 + C3 §1 corrigés.

### 3.2 Nom de table : `pat_tokens`, pas `api_tokens`

Collision avec la table legacy `api_tokens` du `ml/state/schema.sql` (recréée par Store au boot). Nouvelle table = `pat_tokens` (Personal Access Tokens). DESIGN.md §4 documente la déviation. La table legacy `api_tokens` est **droppée en C9** (cf. C9 §5.1 mis à jour).

### 3.3 Cookie de session : JWT HS256, **pas** sid opaque

Tout est dans le JWT. Claims `{iss, sub, email, roles[], scopes[], sid, iat, exp}`. Pas de session-store côté serveur. Rotation = changer `EURIO_SESSION_SECRET` (invalide toutes les sessions instantanément). Cf. `auth_principal.sign_session_cookie` / `verify_session_cookie`.

### 3.4 Cookie env-aware (C3.5)

`EURIO_COOKIE_SECURE` (default 1) + `EURIO_COOKIE_SAMESITE` (default `lax`). Permet de débrayer en dev local sans HTTPS. En prod : laisser les defaults.

### 3.5 Mode dev bypass (C3.5)

`EURIO_DEV_BYPASS=1` côté `eurio-api` expose `GET /auth/oidc/dev/login`. Refuse au boot si `EURIO_PANEL_ORIGIN` contient `musubi.dev` (`assert_dev_bypass_safe()`).

Coordination panel : `VITE_EURIO_DEV_BYPASS=1` fait apparaître le bouton sur `/login`.

### 3.6 `audit:write` réservé services serveur

Pas dans `ROLE_SCOPES`. Refusé explicitement à la création PAT. Cf. DESIGN.md §3.3 note.

### 3.7 Pattern secrets VPS — SOPS via direnv

Plus de `infra/*/secrets/<name>` en clair. Le `.envrc` racine déchiffre `secrets/dev.env` au `cd /opt/eurio` et exporte les vars dans le shell. `docker compose` les forwarde au container via `${VAR:?missing}`. Fallback scripté : `sops exec-env`. Cf. CLAUDE.md §Secrets.

### 3.8 MinIO ne sert plus la DB (DESIGN.md §9.2)

Le `bootstrap_canonical.py` (seed eurio.db depuis MinIO au cold-start) a été **supprimé en C2**. `eurio.db` vit en filesystem classique (`./data:/var/lib/eurio` bind mount). Backups via `infra/backup/eurio-backup.sh`. MinIO reste utilisé pour les **assets** (images coins, crops, screenshots).

### 3.9 Hostnames finaux

| Service | URL |
|---|---|
| Authentik | `authentik.musubi.dev` (était `auth.musubi.dev` dans la doc initiale) |
| Panel | `eurio-admin.musubi.dev` (était `admin.musubi.dev` dans la doc initiale) |
| API | `eurio-api.musubi.dev` |

Doc entièrement réécrite avec les bons hostnames.

### 3.10 `review:publish` rejeté

Pas de sous-scope dédié pour publish. Tout passe par `review:write` simple. La distinction reviewer/admin se fait par rôle.

### 3.11 Auth Authentik — config de référence

- App OIDC : `eurio-panel` (slug)
- Provider : `eurio-panel-oidc`
- Client ID public : `8nFCZsZV0Pryxcjse0pOq2YQvLbdWXP8gmwYbh82`
- Client Secret : en SOPS sous `EURIO_OIDC_CLIENT_SECRET`
- Redirect URIs (mode **Strict** !) :
  - `https://eurio-api.musubi.dev/auth/oidc/callback`
  - `http://localhost:8042/auth/oidc/callback`
- Backup volumes Postgres Authentik à inclure dans `infra/backup/eurio-backup.sh` :
  - volume Docker `oim-authentik_database` (via `pg_dump`)
  - bind mounts `/opt/stacks/oim-authentik/{media,certs,custom-templates}/`

### 3.12 Sécurité : `require_token` legacy retiré des routes métier (C3.5)

Avant C3.5, les routers `coins`, `sets`, `operations`, `peer_arbitration` étaient sous `Depends(api_auth.require_token)` (bearer legacy via table `api_tokens`). Migrés vers `Depends(require_principal)` (cookie OIDC OU PAT). Conséquences :
- Tout user OIDC connecté au panel peut appeler ces routes via cookie.
- Les workflows Mac/PC doivent utiliser un PAT `eurio_<…>` (pas un bearer legacy).
- L'ancien CLI `python -m serving.auth add-token` est deprecated avec warning mais non supprimé (kill définitif à C9 quand la table `api_tokens` legacy disparaît).

## 4. État des secrets dans `secrets/dev.env`

Ajouts faits dans la session :

| Var | Type | But |
|---|---|---|
| `EURIO_OIDC_CLIENT_SECRET` | secret | Auth provider Authentik (échange code OIDC) |
| `EURIO_SESSION_SECRET` | secret | Clé HS256 du cookie de session (rotation = invalide toutes les sessions) |

Vars publiques (non en SOPS, en clair dans `infra/eurio-api/docker-compose.yml`) :

- `EURIO_OIDC_{ISSUER,JWKS_URL,AUTHORIZATION_ENDPOINT,TOKEN_ENDPOINT,END_SESSION_ENDPOINT,CLIENT_ID,REDIRECT_URI}`
- `EURIO_PANEL_ORIGIN`, `EURIO_COOKIE_NAME`

## 5. C6 — port review UI dans le panel

Lire `C6-HANDOFF-PORT-REVIEW.md` puis :

### Pré-requis (déjà OK)

- C4 ✅ — `/review/*` opérationnels sur `eurio-api`
- C5 ✅ — panel skeleton + auth + router guards + `Placeholder.vue` actuel pour `/review`
- L'API client `api/client.ts` expose `api.get/post/put/delete<T>(path, body?)` — utiliser cette signature, pas l'exemple `get/post` du handoff §3.

### Sortie attendue

```
admin/packages/panel/src/
├── api/review.ts            ← typed wrapper sur /review/*
├── views/review/
│   ├── ReviewQueue.vue      ← liste claim + boutons claim/skip
│   ├── ReviewDecide.vue     ← écran décision (accept/reject, eurio_id, face, ...)
│   ├── ReviewStats.vue      ← stats perso
│   └── admin/
│       ├── ReviewFlow.vue
│       ├── ReviewDecisions.vue
│       └── ReviewPublish.vue
└── router/index.ts          ← remplacer le Placeholder pour /review
```

### Smoke test attendu

1. Login OIDC en `reviewer` (un user mis dans `eurio-reviewer` uniquement côté Authentik) → nav affiche `Review` mais pas `Sources`/`Training`/`Users`.
2. Cliquer `Review` → `ReviewQueue` → bouton "Claim" → 2 items apparaissent (les items seedés en C4 smoke test).
3. Cliquer un item → `ReviewDecide` → choisir "accept" + saisir un `eurio_id` quelconque → submit → l'item disparaît.
4. `ReviewStats` montre `today: 1`.
5. Login en `owner` → voit aussi `ReviewFlow` + `ReviewDecisions` + `ReviewPublish`.

### Référence : code legacy à porter

`admin/packages/review-admin/src/{App.vue,api.ts,styles.css}`. C'est court (1 fichier App, 1 api). Reprendre la structure visuelle.

## 6. C8 — UI users + tokens (peut se faire avant C6 si tu préfères)

Lire `C8-HANDOFF-USERS-UI.md`. Endpoints prêts (`/users`, `/users/{id}/roles`, `/me/tokens`). Le seul point sensible : **affichage du clair du PAT une seule fois** dans une modale. Garanties UX :

- Clair affiché dans une modale dédiée, jamais re-récupérable par re-fetch.
- Bouton "copy-to-clipboard".
- Pas de persistance (`localStorage` interdit). Le clair vit dans une `ref<string|null>` qui est `null` après fermeture de la modale.
- Avertissement explicite "Ce token ne sera plus jamais affiché. Si tu le perds, révoque-le et crée-en un nouveau."

Composables `usersApi`/`tokensApi` à ajouter dans `admin/packages/panel/src/api/`.

## 7. C6.5 — migration data Supabase → SQLite

**Le gros morceau.** À discuter avec l'opérateur avant de coder. Cf. esquisse dans
`ROADMAP.md` (bas du fichier) et la décision DESIGN.md §9.1.

### Pourquoi ce chunk existe

Décision actée le 2026-06-19 : **Supabase disparaît entièrement du stack admin/eurio.** Pas seulement l'auth (magic-link), mais **aussi la donnée éditoriale**. Les ~15 tables Postgres (`coins`, `sets`, `coin_series`, `coin_confusion_map`, `design_groups`, `sets_audit`, `referential_*`, `coin_market_prices`, etc.) sont rapatriées dans `eurio.db` SQLite.

Conséquence : C7a/C7b (port admin UI) ne peuvent pas démarrer avant ce chunk, sinon ils porteraient vers des endpoints qui parlent encore à Supabase.

### Discussion : les 3 grandes options à trancher

#### Option α — Migration big-bang en un chunk

1. Audit Supabase (tables, colonnes, RLS, RPC, rows)
2. Écrire `ml/state/editorial_schema.sql` qui transpose tout en SQLite
3. Script `migrate_supabase_to_sqlite.py` qui pg_dump + transforme + insère
4. Refactor `ml/serving/supabase_client.py` callers vers `sqlite3` direct
5. Supprimer le client Supabase
6. Tests E2E sur chaque endpoint impacté

Effort estimé : **3-5 jours** pleins. Risque : si une table a un schéma complexe (jsonb imbriqué, arrays, custom types Postgres), la transposition peut générer des bugs subtils.

Avantages : un seul cutover propre, après C6.5 le code est cohérent.
Inconvénients : long ; pendant le chunk on n'a rien de testable jusqu'à la fin.

#### Option β — Migration par feature (recommandée)

Découper en sous-chunks par "tribu" de tables, dans l'ordre de criticité pour C7a/C7b :

- **C6.5a — Referential** : `referential_countries`, `referential_issuers`, `referential_series`, `referential_denominations`. Schéma le plus stable, peu de jointures. Démarrer ici.
- **C6.5b — Coins core** : `coins`, `coin_market_prices`, `coin_market_prices_quality`, `coin_i18n_and_aliases`. Plus complexe (i18n, FK vers referential).
- **C6.5c — Sets + criteria** : `sets`, `sets_audit`, criteria preview. Logique DSL.
- **C6.5d — Design groups + confusion** : `design_groups`, `coin_confusion_map`, `coins_review_context`.
- **C6.5e — Le reste** (`coins_lent_to_me`, `coins_personal_owned`, etc.).

Pour chaque sous-chunk :
1. Migration data ponctuelle (CSV ou script)
2. Endpoints `eurio-api` correspondants (CRUD + filtres)
3. Smoke test API

Effort estimé : **~1 jour par sous-chunk**, mais on a un état utilisable à chaque étape.

Avantages : itératif, testable, débloque C7a partiel après C6.5a/b.
Inconvénients : période où Supabase et SQLite coexistent (lecture seule Supabase OK, écritures interdites).

#### Option γ — Conserver Supabase, ne migrer **que** l'auth (revenir à la décision initiale du 2026-06-19 matin)

Le DESIGN §9.1 a basculé en cours de session de "service-role Supabase reste utilisée côté eurio-api" → "tout est rapatrié en SQLite". Si l'effort C6.5 (β ou α) paraît prohibitif, on peut **annuler la décision data** et garder :

- Auth Supabase → killed (déjà décidé)
- Données Supabase → conservées, accédées **uniquement** depuis `eurio-api` avec service-role (jamais depuis le browser)
- C7a/C7b portent les endpoints `eurio-api` qui interrogent Supabase via `supabase_client.py` (déjà en place)

Avantages : on évite le gros chantier C6.5, on garde Postgres pour la donnée éditoriale.
Inconvénients : dépendance Supabase à long terme, pas "all-in" au sens strict.

### Recommandation

**Option β** si l'opérateur est OK pour étaler le chantier. **Option γ** si on veut shipper plus vite et qu'on accepte la dépendance Supabase à long terme. **Option α** seulement si on a un sprint dédié.

À trancher en ouverture de la prochaine session, **avant** de toucher au code de C6.5.

### Quoi qu'on choisisse — pré-requis communs

1. Faire un **inventaire exhaustif** des tables Supabase utilisées par l'admin :
   ```bash
   grep -rEho "from\(['\"]([a-z_]+)['\"]" /opt/eurio/admin/packages/web/src/ | sort -u
   grep -rEho "supabase\.from\(['\"]([a-z_]+)['\"]" /opt/eurio/ml/serving/ | sort -u
   ```
2. Lire `supabase/migrations/*.sql` (15+ fichiers, schéma authoritatif).
3. Backup pg_dump complet de la prod Supabase avant tout chantier (`pg_dump … > backup-pre-c6.5-$(date +%F).sql`).

## 8. C7a / C7b — port admin UI

Lire `C7-HANDOFF-PORT-WEB.md`. Le handoff est déjà splitté en C7a (editorial core : sources/coins/audit/referential) et C7b (sets & analytics).

Dépendance C6.5 : **bloquante** si on prend Option α ou β (on ne porte pas vers des endpoints supabase encore en place). **Non bloquante** si Option γ (on porte directement sur `eurio-api` qui lit Supabase côté serveur).

## 9. C9 — cutover

Lire `C9-HANDOFF-CUTOVER.md`. Quasi-complet. Vérifier que les hostnames + tables (`pat_tokens` vs `api_tokens` legacy) sont à jour (corrigés dans la session).

Pré-requis dur : **backup Authentik vérifié** (cf. §3.11 + C1 §8). Sans ça, on ne déclenche pas C9.

## 10. Conseil de séquencement

```
Session N+1 (cette session-ci a été N) :
  1. Discussion C6.5 avec l'opérateur → trancher α/β/γ
  2. C6 (port review UI)             — 1h, indépendant
  3. C8 (UI users + tokens)          — 45min, indépendant
  → push, fin de session ; tu as un panel utilisable pour review + admin
     local des users/tokens. C7 + C9 sont la suite logique.

Session N+2 :
  4. C6.5 (data migration)           — selon option choisie
  5. C7a (editorial core)            — 2-3h
  6. C7b (sets & analytics)          — 2-3h

Session N+3 :
  7. C9 (cutover)                    — 1-2h
```

## 11. Pièges détectés à éviter

- **NE PAS** réactiver `bootstrap_canonical.py` (MinIO seed de eurio.db). Le code a été retiré de l'entrypoint en C2. Cold-start d'un VPS = restore d'un backup, pas seed MinIO.
- **NE PAS** ajouter `audit:write` à `ROLE_SCOPES` (réservé services serveur).
- **NE PAS** stocker le clair d'un PAT côté front (modale éphémère uniquement).
- **NE PAS** rebrancher `require_token` legacy sur les routes métier — `require_principal` couvre cookie + PAT.
- **NE PAS** changer le nom du cookie `eurio_session` (durci dans `auth_principal.cookie_settings()`, panel `Login.vue`, runbook break-glass).
- **NE PAS** changer le nom des groupes Authentik (`eurio-owner`/`admin`/`reviewer`) — durci dans `auth_oidc._GROUP_TO_ROLE` + binding application.
- **NE PAS** créer un user manuellement dans `eurio.db users` — la table est alimentée uniquement au premier login OIDC. Pour grant un owner avant le premier login : mettre dans le groupe Authentik puis demander à l'user de se logger, puis `grant-owner --email` côté CLI si besoin de plus.
- **Si SOPS exec-env est utilisé en cron/systemd** : la clé age doit être lisible par l'user qui lance le job (cf. CLAUDE.md §Secrets).

## 12. Comment vérifier rapidement l'état au démarrage de session

```bash
cd /opt/eurio
direnv reload                                # charge secrets/dev.env (SOPS)
git log --oneline -15                        # voir où on en est

# eurio-api up ?
docker ps --filter name=eurio-api --format '{{.Status}}'
curl -sS -o /dev/null -w "%{http_code}\n" https://eurio-api.musubi.dev/healthz

# Auth opérationnelle ?
curl -sS https://eurio-api.musubi.dev/auth/oidc/login -o /dev/null -w "%{http_code}\n"

# Tables auth présentes ?
python -c "
import sqlite3
c = sqlite3.connect('/opt/eurio/infra/eurio-api/data/eurio.db')
for r in c.execute(\"SELECT name FROM sqlite_master WHERE type='table' AND name IN ('users','roles','user_roles','pat_tokens','auth_audit','_schema_migrations')\"):
    print(r[0])
"

# Panel build/typecheck OK ?
cd admin/packages/panel
pnpm typecheck && pnpm build && echo "panel OK"
```

Si tout vert → tu peux attaquer C6/C8.

## 13. Pour aller vite — rappel commands utiles

```bash
# Rebuild eurio-api après modif backend
cd /opt/eurio/infra/eurio-api && docker compose up -d --build

# Logs eurio-api
docker logs --tail 30 eurio-api

# Forger un cookie de session pour test (sans passer par OIDC complet)
SESSION=$(docker exec eurio-api python -c "
import sys, os; sys.path.insert(0, '/srv/ml')
os.environ.setdefault('EURIO_DB_PATH', '/var/lib/eurio/eurio.db')
from serving.auth_principal import sign_session_cookie, roles_to_scopes
jwt, _ = sign_session_cookie(
    user_id='<sub_user>', email='<email>',
    roles=['owner','admin','reviewer'],
    scopes=roles_to_scopes(['owner','admin','reviewer'])
)
print(jwt)
")
curl -sS -H "Cookie: eurio_session=$SESSION" https://eurio-api.musubi.dev/me | jq .

# Dev panel
cd /opt/eurio/admin/packages/panel && pnpm dev   # http://127.0.0.1:5173

# Break-glass : grant owner par CLI
docker compose exec eurio-api python -m serving.auth grant-owner --email <…>
```

Bonne reprise ! 🚀
