# C2 — `eurio-api` : middleware JWT + tables RBAC + `/me`

> **But (1 phrase)** : doter `eurio-api` d'une auth réelle basée sur les JWT
> émis par Authentik (C1), avec un modèle de droits (`users`/`roles`/
> `user_roles`), une dépendance `require_principal` unifiée, et un endpoint
> `/me`.
>
> **Ne fait PAS** : les tokens API personnels (C3), l'absorption des routes
> review (C4), ni le front (C5+). Pas non plus de gestion CRUD d'utilisateurs
> via l'API — ça se passe dans Authentik (V1).

## 0. Pré-requis

- C1 ✅ — Authentik prêt, JWKS accessible, `client_id`/`client_secret` connus.
- **C1.5 ✅ — `infra/eurio-api/` déployé sur le VPS** (compose up, Traefik route `eurio-api.musubi.dev` valide TLS, healthcheck OK). Sans ce déploiement, le flow OIDC ne peut pas être testé E2E parce que le callback `https://eurio-api.musubi.dev/auth/oidc/callback` ne répond pas.
- Branche dédiée : `auth-redesign-c2` à partir de la branche courante.

### 0.1 C1.5 — Bootstrap déploiement `eurio-api` (sous-chunk)

À faire **avant** d'écrire la moindre route OIDC. Le code de l'image `infra/eurio-api/` existe (Dockerfile + compose + entrypoint) mais n'est pas déployé (C4 model-b en pause depuis l'ouverture de cette refonte).

Étapes :

1. `ssh vps && cd /opt/eurio/infra/eurio-api/`
2. Copier les secrets minimaux dans `secrets/` (cf. §1 ci-dessous + Supabase service-role déjà en SOPS).
3. `docker compose up -d`
4. Vérifier Traefik : ajouter les labels `traefik.http.routers.eurio-api.rule=Host(\`eurio-api.musubi.dev\`)` + TLS Let's Encrypt.
5. DNS : `eurio-api.musubi.dev` A → IP VPS.
6. Smoke test : `curl https://eurio-api.musubi.dev/health` → 200.
7. Le service tourne en mode "API existante sans OIDC" — le bearer machine legacy reste utilisable. C2 §3+ rajoute l'OIDC par-dessus.

## 1. Configuration et secrets

**Env vars publiques** (URLs Authentik, **pas** des secrets — à mettre en clair dans `infra/eurio-api/docker-compose.yml` sous `environment:`) :

```
EURIO_OIDC_ISSUER=https://auth.musubi.dev/application/o/eurio-panel/
EURIO_OIDC_JWKS_URL=https://auth.musubi.dev/application/o/eurio-panel/jwks/
EURIO_OIDC_CLIENT_ID=<from C1>            # public, OK en clair
EURIO_PANEL_ORIGIN=https://admin.musubi.dev
EURIO_COOKIE_NAME=eurio_session
EURIO_COOKIE_DOMAIN=admin.musubi.dev      # vide en dev (localhost)
```

**Secrets sensibles** (à mettre dans `secrets/dev.env` via `go-task secrets:edit` + propagés au container via SOPS → fichiers Docker secrets ou env injection) :

```
EURIO_OIDC_CLIENT_SECRET=<from C1>
EURIO_SESSION_SECRET=<32 bytes hex aléatoires — clé HS256 du JWT de session>
```

Justification du split : seul ce qui est vraiment secret va en SOPS. Les URLs publiques d'Authentik et le `client_id` sont déjà visibles dans les requêtes browser (redirect vers `auth.musubi.dev`) — pas de bénéfice à les chiffrer, et ça allège la rotation SOPS.

Côté container, l'`entrypoint.sh` doit propager les secrets sensibles (ajouter le passage `*_FILE` → env si on monte des Docker secrets).

## 2. Dépendances Python

Ajouter dans `infra/eurio-api/Dockerfile` (ou le `pyproject.toml` correspondant si présent) :

- `python-jose[cryptography]` — vérif JWT RS256 (OIDC) **et** signature/vérif JWT HS256 (cookie de session). Un seul lib pour les deux usages.
- `httpx` — fetch JWKS + appels Authentik (devrait déjà être là).
- (~~`itsdangerous`~~ : pas utilisé. Le cookie de session est un JWT HS256, pas une signature `itsdangerous`. Cf. §7.)

## 3. Modules à créer

### 3.1 `ml/serving/auth_oidc.py`

```python
# Pseudocode — l'agent ajuste à l'archi du module.

class JWKSCache:
    """Cache JWKS d'Authentik avec TTL (1h). Refresh sur kid inconnu."""
    def get_key(self, kid: str) -> dict: ...

def verify_oidc_jwt(token: str) -> dict:
    """Vérifie signature RS256 + iss + aud + exp. Renvoie le payload."""

def authentik_groups_to_roles(groups: list[str]) -> list[str]:
    """eurio-owner → owner, eurio-admin → admin, eurio-reviewer → reviewer."""
```

### 3.2 `ml/serving/auth_principal.py`

```python
@dataclass
class Principal:
    user_id: str
    email: str
    roles: list[str]
    scopes: set[str]
    auth_method: Literal["oidc", "api_token"]
    token_id: int | None = None

ROLE_SCOPES: dict[str, set[str]] = {
    "owner": {"sources:*", "coins:*", "audit:read", "review:*",
              "training:run", "ingest:run", "users:*", "tokens:manage_own"},
    "admin": {"sources:*", "coins:*", "audit:read", "review:*",
              "training:run", "ingest:run", "users:read", "tokens:manage_own"},
    "reviewer": {"coins:read", "review:*", "tokens:manage_own"},
}

def roles_to_scopes(roles: list[str]) -> set[str]:
    """Union des scopes des rôles, expansion des wildcards."""

def require_principal(...) -> Principal:
    """Dépendance FastAPI. Lit Authorization Bearer + cookie session."""

def require_scope(scope: str):
    """Factory de dépendance. 403 si scope absent."""

def require_role(role: str):
    """Idem pour les rôles."""
```

### 3.3 `ml/serving/auth_routes.py`

Endpoints OIDC (cf. DESIGN.md §5.3) :

- `GET  /auth/oidc/login` → redirect Authentik (PKCE, state en cookie).
- `GET  /auth/oidc/callback` → échange code → tokens, upsert user en DB, set cookie session signé.
- `POST /auth/oidc/logout` → clear cookie, optionnellement appel revoke Authentik.

### 3.4 `ml/serving/users_routes.py`

- `GET /me` → renvoie le `Principal` (sans secrets).
- `GET /users` (scope `users:read`) → liste users miroir local + rôles.
- `PUT /users/{id}/roles` (scope `users:manage`) → réassigne les rôles **côté miroir uniquement** ; cap'd par les groupes Authentik réels (un user qui n'est pas dans `eurio-admin` chez Authentik ne peut pas avoir `admin` côté miroir).

## 4. Migration DB

Créer `ml/serving/migrations/0001_auth_redesign.sql` (ou utiliser le mécanisme
de migration existant — voir `ml/canonical/schema.py` ou équivalent) :

```sql
-- Schéma complet : cf. DESIGN.md §4
CREATE TABLE IF NOT EXISTS users (...);
CREATE TABLE IF NOT EXISTS roles (...);
CREATE TABLE IF NOT EXISTS user_roles (...);
CREATE TABLE IF NOT EXISTS api_tokens (...);   -- ajouté ici, alimenté en C3
INSERT OR IGNORE INTO roles(name) VALUES ('owner'), ('admin'), ('reviewer');
```

Appliquée au boot de `eurio-api` (entrypoint ou hook FastAPI startup).

## 5. Câblage dans `server_serve.py`

- Monter `auth_routes` (login/callback/logout) **avant** que `require_principal`
  ne soit posé sur les autres routers.
- Monter `users_routes`.
- Garder `EURIO_API_AUTH_REQUIRED=1` (déjà en place) — la nouvelle dep remplace
  l'ancien `require_token`.
- L'ancien bearer machine (`api_tokens.token_sha` actuel) reste **fonctionnel
  en parallèle** dans ce chunk pour ne pas casser les workflows ml/ existants.
  Sa migration vers le nouveau modèle est faite en C3.

## 6. Critères d'acceptation

```bash
# a) Discovery JWKS atteignable depuis le container
docker compose exec eurio-api curl -s $EURIO_OIDC_JWKS_URL | jq '.keys[0].kty'
# → "RSA"

# b) /auth/oidc/login renvoie 302 vers Authentik
curl -si https://eurio-api.musubi.dev/auth/oidc/login | head -5
# → 302 Location: https://auth.musubi.dev/...

# c) Flow complet manuel : ouvrir /auth/oidc/login dans le browser,
#    se logger sur Authentik, retomber sur /auth/oidc/callback → set cookie.
#    Puis :
curl -s --cookie "session=…" https://eurio-api.musubi.dev/me | jq .
# → {"user_id":"…","email":"raphaelthi59@gmail.com","roles":["owner"], …}

# d) Sans auth → 401
curl -si https://eurio-api.musubi.dev/me
# → 401

# e) Scope manquant → 403
#    (créer un user de test sans owner, tenter /users/.../roles → 403)
```

## 7. Garde-fous

- **Ne pas casser** le bearer machine actuel — il reste branché. C3 le retirera proprement.
- **Ne pas exposer** `EURIO_OIDC_CLIENT_SECRET` ni `EURIO_SESSION_SECRET` dans les logs (filtrer dans le logging middleware).
- **Cookie de session `eurio_session`** (cf. DESIGN.md §6.1) :
  - **JWT HS256** signé avec `EURIO_SESSION_SECRET`. Claims : `{sub, email, roles[], scopes[], sid (uuid4), iat, exp=iat+8h, iss="eurio-api"}`.
  - Attributs : `HttpOnly`, `Secure`, `SameSite=Lax`, `Path=/`, `Domain=admin.musubi.dev` en prod (vide en dev).
  - **Pas de session-store côté serveur** : tout est dans le JWT, validation = `jwt.decode` + clé symétrique. `sid` sert uniquement à l'audit log.
  - **Pas le JWT Authentik brut** dans le cookie : on émet notre propre JWT court, contenant seulement ce que `eurio-api` a besoin de re-vérifier sur chaque requête.
  - **Rotation = invalidation globale** : changer `EURIO_SESSION_SECRET` invalide tous les cookies (procédure break-glass).
- **JWKS** : refresh sur `kid` inconnu, mais **rate-limit** (1 refresh / 60 sec max) pour éviter un DoS via Authorization headers forgés.

## 8. Résumé à produire

```
## C2 — résumé eurio-api auth

- Branche : <…>
- Commits : <sha .. sha>
- Migrations DB appliquées : <…>
- Dependencies ajoutées : python-jose[cryptography], httpx, …
- Routes /auth/oidc/login + callback + logout : OK / KO
- /me : OK / KO
- /users + /users/{id}/roles : OK / KO
- Flow login browser complet testé : OUI/NON
- Ancien bearer machine encore fonctionnel : OUI/NON  (doit être OUI)
- Déviations vs DESIGN.md : <…>
- Open questions pour C3/C4/C5 : <…>
```
