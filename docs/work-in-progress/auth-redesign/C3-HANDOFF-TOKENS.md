# C3 — Tokens API personnels

> **But (1 phrase)** : remplacer le pattern `add-token` + copier-coller par des
> tokens API personnels créés depuis l'API (puis depuis le panel en C8),
> stockés sha-only, scopés, révocables, vérifiés par le même middleware que les
> JWT OIDC.
>
> **Ne fait PAS** : l'UI dans le panel (C8). Ici on construit les endpoints +
> la vérif côté backend, testés via `curl`.

## 0. Pré-requis

- C2 ✅ — `Principal`, `require_scope`, table `api_tokens` créée.
- Branche : `auth-redesign-c3`.

## 1. Modèle de token

- Format : `eurio_<43 base64url caractères (RFC 4648 sans padding)>` (256 bits d'entropie). **Tranché — cf. DESIGN.md §5.1.** Génération : `secrets.token_bytes(32)` → `secrets.token_urlsafe(32).decode().rstrip("=").lower()` → préfixer `eurio_`. Pas de checksum (pas nécessaire pour V1, lookup direct par sha).
- Préfixe `eurio_` détectable pour distinguer du JWT (qui commence par `eyJ`).
- Stockage : `sha256(token)` hex en `api_tokens.token_sha`. Le clair n'est
  **jamais** stocké côté serveur, **affiché une seule fois** à la création.
- Scopes : sous-ensemble strict des scopes effectifs de l'utilisateur au moment
  de la création. Si l'utilisateur perd un rôle plus tard, les scopes du token
  ne sont pas étendus — ils restent tels que créés (mais l'intersection
  scopes∩scopes_effectifs_actuels est vérifiée à chaque requête).

## 2. Endpoints

| Route | Méthode | Scope | Comportement |
|---|---|---|---|
| `GET /me/tokens` | GET | `tokens:manage_own` | Liste des tokens de l'user (id, name, scopes, created_at, last_used_at). Pas de clair. |
| `POST /me/tokens` | POST | `tokens:manage_own` | Body `{name, scopes, expires_at?}`. Crée, renvoie `{id, token: "eurio_..."}` **une fois**. Vérifie que `scopes` ⊆ scopes effectifs. |
| `DELETE /me/tokens/{id}` | DELETE | `tokens:manage_own` | Set `revoked_at=now()`. Soft delete pour conserver l'audit. |

## 3. Vérif machine dans `require_principal`

Étendre la dépendance `require_principal` (C2) :

```python
def require_principal(authorization: str = Header(...)) -> Principal:
    if not authorization.startswith("Bearer "):
        raise 401
    token = authorization[7:]
    if token.startswith("eurio_"):
        return _principal_from_api_token(token)
    return _principal_from_oidc_jwt(token)
```

`_principal_from_api_token` :

1. `sha = sha256(token)`
2. Lookup `api_tokens WHERE token_sha = sha AND revoked_at IS NULL AND (expires_at IS NULL OR expires_at > now)`.
3. 401 si introuvable.
4. Charger `users` + `user_roles`. Calculer scopes effectifs (rôles actuels).
5. **Intersecter** avec `scopes_json` du token.
6. Update `last_used_at = now()` (async/fire-and-forget pour ne pas bloquer la requête).
7. Renvoyer `Principal(auth_method="api_token", token_id=<id>, scopes=intersection)`.

## 4. Migration des tokens existants (model-b C4)

Les tokens `mac`/`pc` créés via `add-token` legacy :

- **Option A** : on les migre en bulk → script qui parcourt l'ancienne table et insère dans `api_tokens` avec un `user_id` "système" (à éviter — ça réintroduit un compte machine).
- **Option B** (recommandée) : on les **invalide en C9** et l'opérateur re-crée 2 tokens propres (`mac-cli`, `pc-cli`) depuis le panel à ce moment. ~1 minute de friction one-shot.

Choix retenu : **B**. La commande `python -m serving.auth list/add-token` est **supprimée** dans ce chunk (ou marquée deprecated avec warning). Une seule porte d'entrée : l'API.

## 5. Break-glass

Garder une commande **non documentée** dans le panel mais utilisable via
`docker exec`. Implémentée dans `ml/serving/auth.py` (sous-commande à ajouter
à la CLI existante, à côté de `add-token` / `list` qui sont supprimées) :

```bash
docker compose exec eurio-api python -m serving.auth grant-owner --email <…>
```

Elle :
1. Trouve ou crée le `users` correspondant (par email).
2. Ajoute le rôle `owner` dans `user_roles` (idempotent).
3. Logge dans stdout + écrit une ligne dans `auth_audit` (`event='grant_owner.cli'`, `actor_id=NULL`, `target=<user.id>`, `meta_json={"invoked_by":"docker exec","email":"…"}`).

La table `auth_audit` est **créée en C2** (migration `0001_auth_redesign.sql`, cf. DESIGN.md §4) et écrite dès C2 (login.ok / login.fail). C3 ajoute les events `token.create`, `token.revoke`, `grant_owner.cli`. Pas besoin de "créer si pas déjà" — la migration C2 la garantit.

Cas d'usage : Authentik tombe ou bug d'auth verrouille tous les owners. Tu te
connectes au VPS en SSH, tu te re-grant. Documenté dans le RUNBOOK de C9.

## 6. Critères d'acceptation

```bash
# Avec un cookie de session OIDC valide (cf. C2)
COOKIE="session=…"

# Créer un token
curl -s -X POST -H "Content-Type: application/json" --cookie "$COOKIE" \
  -d '{"name":"test-mac","scopes":["coins:read","review:write"]}' \
  https://eurio-api.musubi.dev/me/tokens
# → {"id": 1, "token": "eurio_XXXXXXXX..."}

TOKEN=eurio_XXXXXXXX...

# L'utiliser
curl -s -H "Authorization: Bearer $TOKEN" https://eurio-api.musubi.dev/me
# → Principal avec auth_method=api_token, scopes={coins:read, review:write, tokens:manage_own}

# Tenter un scope hors-scopes du token → 403
curl -si -H "Authorization: Bearer $TOKEN" https://eurio-api.musubi.dev/ingest/run/foo
# → 403

# Lister
curl -s --cookie "$COOKIE" https://eurio-api.musubi.dev/me/tokens | jq .

# Révoquer
curl -s -X DELETE --cookie "$COOKIE" https://eurio-api.musubi.dev/me/tokens/1

# Le token révoqué ne marche plus
curl -si -H "Authorization: Bearer $TOKEN" https://eurio-api.musubi.dev/me
# → 401
```

## 7. Garde-fous

- **Ne JAMAIS logger** le token clair (filtrer dans le logging middleware si nécessaire).
- **`POST /me/tokens`** : rate-limit (5/min/user) pour éviter l'exfiltration en cas de XSS du cookie.
- **Pas de re-affichage** : si l'user perd le clair, il révoque et re-crée.
- **Scope `tokens:manage_own`** uniquement — un user ne peut pas créer/lister/révoquer les tokens d'un autre user (pas même un owner, sauf via break-glass `grant-owner`).

## 8. Résumé à produire

```
## C3 — résumé tokens API personnels

- Branche / commits : <…>
- Endpoints /me/tokens GET/POST/DELETE : OK / KO
- Vérif machine via require_principal : OK / KO
- Tests curl complets : <résumé>
- Ancien `add-token` CLI : supprimé / marqué deprecated / conservé (préciser)
- Break-glass `grant-owner` : implémenté et testé OUI/NON
- Audit log écrit (creation/revoke) : OUI/NON, table : <…>
- Déviations vs DESIGN.md : <…>
```
