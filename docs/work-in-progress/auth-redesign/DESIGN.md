# DESIGN — auth-redesign (cible architecture)

> **Statut** : validé 2026-06-19 par l'opérateur (raphaelthi59@gmail.com).
> **Autoritatif** sur la cible. Tout chunk d'implémentation (`Cx-HANDOFF-*.md`)
> doit s'aligner sur ce document. En cas de conflit, ce doc gagne — ou on met
> à jour ce doc d'abord, puis le chunk.
>
> **Contexte d'ouverture** : voir `HANDOFF.md` (origine + inventaire de la dette).
> Les options §5 du HANDOFF sont **superseded** par ce DESIGN.

## 1. Décisions structurantes (verrouillées)

| # | Décision | Raison |
|---|---|---|
| D1 | **Un seul panel admin self-hosted sur le VPS**. Plus de Vercel. | Stop à la fragmentation 4 surfaces × 4 auths. Souveraineté + unique source de vérité de l'identité. |
| D2 | **Authentik** (déjà déployé par l'opérateur) = IDP unique. OIDC. | Existe déjà, MFA, gestion users/groups UI, providers OAuth disponibles. Pas de réinvention. |
| D3 | **`eurio-api`** (FastAPI, VPS) = backend unique. Absorbe `review_service`. | Une seule API, un seul middleware d'auth, un seul rate-limit, un seul CORS. |
| D4 | **`admin/packages/panel`** (Vue 3 + Vite, nouveau) = front unique. Absorbe `admin/packages/web` + `admin/packages/review-admin`. | Idem côté front. Le proto Vue+Pinia reste séparé (source de vérité du design Android, pas du panel). |
| D5 | **RBAC simple** : 3 rôles applicatifs (`owner`, `admin`, `reviewer`) + scopes fins (`sources:write`, `review:write`, `training:run`, `users:manage`, …). Mapping Authentik group → rôle interne. | Suffit pour 1 opérateur + 2-3 reviewers à terme. Extensible si besoin sans casser. |
| D6 | **Identité = humaine, durable**. Pas de "compte machine" séparé. Mac, PC, futurs runners sont **des sessions/tokens de la même identité**. | Le Mac n'est pas une personne. Les capacités hardware (GPU) ne définissent pas une identité. |
| D7 | **Tokens API personnels** (style GitHub PAT) : créés depuis le panel par l'utilisateur connecté, scopés (capés par ses rôles), révocables, sha-only en base. | Remplace définitivement le pattern `add-token` + copier-coller du C4 model-b. |
| D8 | **`users`, `roles`, `user_roles`, `api_tokens`** vivent dans `eurio.db` (SQLite) au démarrage. Migration Postgres si > 50 users. | Zéro infra add. Compatible Postgres plus tard (schéma simple). |
| D9 | **All-in. Cutover one-shot, pas V1 puis V2, pas de demi-migration.** Plusieurs sessions de dev acceptées pour bâtir et tester les chunks, mais le résultat final est un basculement complet en une fois après ≥7j de coexistence test. On ne livre pas une moitié, on ne traîne pas un dual-mode permanent. | Sinon on traîne 3 auths désynchronisées pendant des mois. Anti-dette. La coexistence test ≠ dual-run permanent. |

## 2. Topologie cible

```
                ┌──────────────────────────────────────────┐
                │           VPS (NixOS, Docker, Traefik)    │
                │                                            │
   ┌────────┐   │   ┌─────────────────┐   ┌──────────────┐  │
   │ Browser│──▶│──▶│  panel (static) │   │  Authentik   │  │
   │ (toi+  │   │   │ eurio-admin.    │◀─▶│ authentik.   │  │
   │  amis) │◀──│───│  musubi (nginx) │   │  musubi (OIDC)│  │
   └────────┘   │            │                   │          │
                │            │ XHR /api          │ JWKS     │
                │            ▼                   │          │
   ┌────────┐   │   ┌─────────────────┐          │          │
   │ ml/    │   │   │  eurio-api      │──────────┘          │
   │ CLI    │──▶│──▶│  (FastAPI)      │   verif JWT          │
   │ (Mac,  │   │   │  eurio-api.musubi│  + bearer machine   │
   │  PC)   │   │   │                 │                     │
   └────────┘   │   │  eurio.db       │                     │
                │   │  users/roles/   │                     │
                │   │  api_tokens     │                     │
                │   └─────────────────┘                     │
                │                                            │
                │   [DECOMMISSIONNÉ après C9]                │
                │   eurio-review (review_service)            │
                └──────────────────────────────────────────┘
```

Domaines :
- `authentik.musubi.dev` → Authentik (existant)
- `eurio-admin.musubi.dev` → panel statique (nouveau, remplace Vercel + `eurio-review.musubi.dev`)
- `eurio-api.musubi.dev` → API unique (existant, étendu)

## 3. Modèle d'identité et de droits

### 3.1 Identité

- **Source de vérité** : Authentik. Un utilisateur = un compte Authentik (email, mot de passe, MFA optionnel).
- **Miroir local** dans `eurio-api.users` : créé/mis à jour au premier login (claim `sub` = id Authentik, `email`, `name`). On ne stocke jamais de mot de passe localement.
- **Mac, PC, autres machines** = sessions ou tokens de la même identité. Pas de table `machines`.

### 3.2 Rôles applicatifs

3 rôles, mappés depuis les groupes Authentik :

| Rôle | Group Authentik | Capacités |
|---|---|---|
| `owner` | `eurio-owner` | Tout. Ne peut être attribué que par un autre `owner`. Au moins 1 owner doit exister. |
| `admin` | `eurio-admin` | Sources, coins, audit, review, training, ingest. Pas la gestion d'utilisateurs ni l'attribution de rôles. |
| `reviewer` | `eurio-reviewer` | Review queue uniquement (claim, decide, skip). |

Un utilisateur peut cumuler plusieurs rôles. Les capacités effectives = union.

### 3.3 Scopes (permissions fines)

Les scopes définissent les endpoints accessibles. Le mapping rôle → scopes est défini côté `eurio-api`, pas dans Authentik.

| Scope | Owner | Admin | Reviewer |
|---|---|---|---|
| `sources:read` | ✅ | ✅ | ❌ |
| `sources:write` | ✅ | ✅ | ❌ |
| `coins:read` | ✅ | ✅ | ✅ |
| `coins:write` | ✅ | ✅ | ❌ |
| `audit:read` | ✅ | ✅ | ❌ |
| `audit:write` | ✅ | ✅ | ❌ |
| `review:read` | ✅ | ✅ | ✅ |
| `review:write` | ✅ | ✅ | ✅ |
| `training:run` | ✅ | ✅ | ❌ |
| `ingest:run` | ✅ | ✅ | ❌ |
| `users:read` | ✅ | ✅ | ❌ |
| `users:manage` | ✅ | ❌ | ❌ |
| `tokens:manage_own` | ✅ | ✅ | ✅ |

> **Note `review:publish`** : rejeté. La publication d'une décision est couverte par `review:write` simple — pas de sous-scope dédié. Si un workflow de validation à 2 niveaux est introduit plus tard, on revisitera.
>
> **Note `audit:write`** : réservé aux services serveur (ingest, training) qui poussent des lignes d'audit. Pas exposé à l'UI ni aux PAT user (filtré côté `roles_to_scopes`).

### 3.4 Tokens API personnels

- Créés depuis `/me/tokens` dans le panel par l'utilisateur connecté.
- Nom libre (ex : `mac-cli`, `pc-training`).
- Scopes : un sous-ensemble des scopes effectifs de l'utilisateur.
- Stockage : `sha256(token)` seulement. Le clair est affiché **une fois** à la création, jamais re-affichable.
- Révocables (`DELETE /me/tokens/:id`) et listables.
- Pas d'expiration par défaut ; champ `expires_at` nullable disponible pour plus tard.

## 4. Schéma DB (tables nouvelles, dans `eurio.db`)

```sql
CREATE TABLE users (
  id            TEXT PRIMARY KEY,        -- claim `sub` d'Authentik
  email         TEXT NOT NULL UNIQUE,
  name          TEXT NOT NULL,
  created_at    INTEGER NOT NULL,        -- epoch ms
  last_login_at INTEGER,
  active        INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE roles (
  name TEXT PRIMARY KEY                  -- 'owner' | 'admin' | 'reviewer'
);

CREATE TABLE user_roles (
  user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  role    TEXT NOT NULL REFERENCES roles(name),
  PRIMARY KEY (user_id, role)
);

CREATE TABLE api_tokens (
  id            INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id       TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  name          TEXT NOT NULL,
  token_sha     TEXT NOT NULL UNIQUE,    -- sha256 hex
  scopes_json   TEXT NOT NULL,           -- JSON array de scopes
  created_at    INTEGER NOT NULL,
  last_used_at  INTEGER,
  revoked_at    INTEGER,
  expires_at    INTEGER                  -- nullable
);
CREATE INDEX api_tokens_user_idx ON api_tokens(user_id);
CREATE INDEX api_tokens_active_idx ON api_tokens(revoked_at) WHERE revoked_at IS NULL;

CREATE TABLE auth_audit (
  id         INTEGER PRIMARY KEY AUTOINCREMENT,
  ts         INTEGER NOT NULL,         -- epoch ms
  actor_id   TEXT,                     -- user.id ou NULL pour les events système (break-glass CLI)
  event      TEXT NOT NULL,            -- 'login.ok' | 'login.fail' | 'token.create' | 'token.revoke' | 'role.grant' | 'role.revoke' | 'grant_owner.cli' | …
  target     TEXT,                     -- user.id / token.id concerné, contextuel
  meta_json  TEXT                      -- payload libre (IP, user-agent, scopes demandés, …)
);
CREATE INDEX auth_audit_ts_idx ON auth_audit(ts);
CREATE INDEX auth_audit_actor_idx ON auth_audit(actor_id);
```

> `auth_audit` est créée dès C2 (migration `0001_auth_redesign.sql`) et écrite par C2 (login), C3 (tokens + break-glass `grant-owner`) et C8 (gestion users/roles).

## 5. Couche d'auth dans `eurio-api`

### 5.1 Vérif unifiée

Une dépendance FastAPI `Principal = require_principal()` qui accepte **deux** schémas d'auth :

1. **Bearer JWT** émis par Authentik (cas browser après login OIDC, transmis en `Authorization: Bearer <jwt>` ou cookie HttpOnly). Vérif via JWKS d'Authentik (cache local 1h).
2. **Bearer token machine** (PAT) émis par `eurio-api` (cas ml/ CLI). Détection : forme `eurio_<43 base32>` (256 bits d'entropie — cf. C3 §1). Lookup sha256 dans `api_tokens`. Mise à jour `last_used_at`.

Les deux résolvent vers un `Principal` interne unique :

```python
class Principal:
    user_id: str
    email: str
    roles: list[str]
    scopes: set[str]
    auth_method: Literal["oidc", "api_token"]
    token_id: int | None   # si auth_method == "api_token"
```

### 5.2 Dependencies par scope

```python
require_scope("sources:write")    # 403 si scope absent
require_role("owner")             # 403 si rôle absent
require_principal()               # auth seulement, sans check
```

### 5.3 Endpoints d'auth/identité

| Route | Méthode | Scope | But |
|---|---|---|---|
| `/auth/oidc/login` | GET | — | Redirige vers Authentik (PKCE) |
| `/auth/oidc/callback` | GET | — | Échange code → tokens, set cookie HttpOnly, redirect panel |
| `/auth/oidc/logout` | POST | principal | Clear cookie + revoke session Authentik |
| `/me` | GET | principal | Renvoie `Principal` (sans token clair) |
| `/me/tokens` | GET | `tokens:manage_own` | Liste les tokens (sans clair) |
| `/me/tokens` | POST | `tokens:manage_own` | Crée un token, renvoie le clair **une fois** |
| `/me/tokens/{id}` | DELETE | `tokens:manage_own` | Révoque |
| `/users` | GET | `users:read` | Liste users + rôles |
| `/users/{id}/roles` | PUT | `users:manage` | Réassigne rôles |

> Note : la création/désactivation d'utilisateurs se fait **dans Authentik** (pas dans `eurio-api`). Le panel embarque un lien profond vers l'UI Authentik pour ça (V1). V2 éventuelle : proxy via Authentik API.

## 6. Front (panel) — cookie de session

- **Stack** : Vue 3 + Vite + Pinia + Vue Router. TypeScript. Material-ish via `shared/tokens.css` (mêmes tokens que le proto).
- **Auth côté browser** : flow OIDC server-side. Le browser ne voit jamais le JWT Authentik ni le `client_secret`. À l'issue du callback OIDC, `eurio-api` émet **son propre JWT de session** signé HS256 et le pose en cookie `eurio_session`. Le panel appelle `/me` au boot pour récupérer le `Principal`.

### 6.1 Cookie `eurio_session`

| Champ | Valeur |
|---|---|
| Nom | `eurio_session` |
| Type | JWT signé HS256 (lib `python-jose`) |
| Clé de signature | `EURIO_SESSION_SECRET` (32 bytes hex, SOPS, rotation = invalidation globale) |
| Attributs | `HttpOnly`, `Secure`, `SameSite=Lax`, `Path=/` |
| Domaine | `eurio-admin.musubi.dev` (prod) / pas de Domain en dev (localhost) |
| Durée | `exp = iat + 8h` |
| Claims | `{sub, email, roles[], scopes[], sid, iat, exp, iss="eurio-api"}` |

- **Pas de session-store côté serveur** : tout est dans le JWT, vérification = `jwt.decode` + clé symétrique. `sid` (uuid v4) sert d'identifiant pour les logs d'audit et la révocation ciblée si besoin (futur — V1 : pas implémenté).
- **Refresh** : à T-15min de l'exp, le front lance silencieusement une re-redirection OIDC `prompt=none` vers Authentik qui renvoie un nouveau cookie sans interaction (si la session Authentik est toujours valide).
- **Révocation en masse** : rotation `EURIO_SESSION_SECRET` → tous les cookies deviennent invalides immédiatement (procédure break-glass, runbook C9 §7).
- **Logout** : `POST /auth/oidc/logout` → clear cookie + best-effort `end_session_endpoint` Authentik.
- **Routes** : `/login` (redirect), `/`, `/sources`, `/coins`, `/audit`, `/review`, `/training`, `/users` (réservée `users:read`), `/me/tokens`.
- **Guards** : `router.beforeEach` redirige vers `/login` si `Principal` absent ; redirige vers `/` si scope manquant pour une route.

## 7. CLI ml/ (Mac, PC)

- `secrets/dev.env` (SOPS) contient `EURIO_API_TOKEN` (token personnel créé depuis le panel).
- Commandes `go-task ml:*` qui parlent à `eurio-api` lisent ce token et l'envoient en `Authorization: Bearer eurio_<...>`.
- Provisioning d'un token = **manipulation dans le panel** (1 clic, copier-coller depuis le navigateur dans SOPS). **Plus aucune commande `add-token` côté VPS.**

## 8. Ce qui est tué (cutover, chunk C9)

- `admin/packages/web` (Vercel) → archivé sous `docs/archive/admin-web/`.
- `admin/packages/review-admin` → archivé sous `docs/archive/admin-review-admin/`.
- `ml/review_service/` → fusionné dans `ml/serving/` (chunks C4) ; ancien code archivé.
- `infra/review/` (container `eurio-review`) → stoppé et supprimé après C9.
- Projet Vercel "eurio-admin" → supprimé du dashboard Vercel.
- DNS `eurio-review.musubi.dev` → CNAME vers `eurio-admin.musubi.dev` ou suppression.
- `REVIEW_ADMIN_TOKEN`, `REVIEW_SESSION_SECRET` dans `secrets/dev.env` → supprimés.

## 9. Hors scope (à NE PAS toucher dans cette refonte)

- **App Android** + Room + offline-first → intangible.
- **MinIO root creds** → secret machine, reste dans SOPS, n'entre pas dans Authentik.
- **SSH** (Codeberg, VPS) → géré par `keychain.nix`, hors scope.
- **pCloud backup** (rclone OAuth) → machine-to-cloud, hors scope.
- **MCP servers Claude** → géré par claude.ai, hors scope.

### 9.1 Dans le scope (clarification post-audit 2026-06-19)

- **Supabase Auth (magic-link `admin/packages/web` `LoginPage.vue`)** : **disparaît complètement** à C9. Toutes les surfaces UI passent par Authentik via le panel. Suppression effective des comptes `auth.users` Supabase (purge documentée dans C9 §5), désactivation du provider magic-link Supabase, suppression de la conf Vercel correspondante.
- **Appels Supabase directs depuis `admin/packages/web`** : **tous migrés** vers des endpoints `eurio-api` équivalents en C7 (split en C7a / C7b). Aucun appel `supabase.from(…)` ne doit subsister côté front après C9.
- **RLS `auth.jwt() ->> 'role' = 'admin'`** (8+ policies dans `supabase/migrations/`) : conservées **en place** (la DB Supabase est intégralement préservée), mais deviennent **inactives** une fois que `eurio-api` est le seul appelant et tape avec la service-role key. Documentées comme dead-but-kept dans le commit C9. **Pas de DROP.**
- **Service-role Supabase** : reste utilisée, mais **uniquement** côté `eurio-api` (VPS, SOPS), jamais côté navigateur.

## 10. Risques et garde-fous

| Risque | Mitigation |
|---|---|
| Authentik tombe → personne ne peut se logger au panel | Maintenir un break-glass : un `owner` peut générer un token personnel à long-lived qui marche même si OIDC est down. Documenté dans le RUNBOOK chunk C9. |
| Bug d'auth qui locke tous les owners | Conserver une commande `python -m serving.auth grant-owner --email <…>` exécutable via `docker exec` (bypass = être sur le VPS). Logged. |
| Fuite d'un token API personnel | Révocation depuis le panel. Rotation manuelle. Audit log léger (qui a créé/révoqué quoi, dans `api_tokens.created_at`/`revoked_at`). |
| Migration des tokens existants `mac`/`pc` (C4 model-b actuel) | Hard cutover : on les invalide à C9. Tu en re-crées 2 propres depuis le panel. |
| Authentik = SPOF | Backup régulier du volume Postgres d'Authentik (`infra/authentik/` ou volume nommé selon l'hébergement actuel). **À concrétiser en C1 §8** : nommer le volume Docker exact et l'inclure dans `infra/backup/eurio-backup.sh`. C9 est **bloqué** tant que ce backup n'est pas vérifié. |

## 11. Open questions (à trancher dans le chunk concerné)

- **OQ1 (C1)** : Authentik tourne dans quel docker-compose ? Faut-il l'ajouter à `infra/` du repo ou il est géré ailleurs sur le VPS ? **Identifier le volume Postgres exact** et l'ajouter à `infra/backup/eurio-backup.sh` (bloque C9).
- **OQ2 (C2)** : JWKS d'Authentik — endpoint exact + politique de cache.
- ~~**OQ3 (C3)** : Format du token personnel.~~ **Tranché** : `eurio_<43 base32>` (256 bits) — cf. §5.1 et C3 §1.
- **OQ4 (C5)** : Panel servi par Nginx static ou monté sur FastAPI (`StaticFiles`) ? **À trancher en C5** (impact CSP, pas en C9). Recommandation provisoire : nginx static + reverse-proxy `/api/*` → eurio-api (séparation claire, CSP simple).
- **OQ5 (C6)** : `review.db` existant a-t-il des données à migrer dans `eurio.db` (decisions historiques) ou on repart vierge ?
- **OQ6 (C9)** : Date du cutover. Pré-requis : panel testé en parallèle pendant ≥ 1 semaine.
- ~~Cookie de session — format.~~ **Tranché** : JWT signé HS256, claims explicites, pas de session-store — cf. §6.1.
- ~~Sort de Supabase Auth.~~ **Tranché** : suppression complète à C9 — cf. §9.1.
