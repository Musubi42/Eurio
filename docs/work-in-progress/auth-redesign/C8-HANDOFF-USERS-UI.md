# C8 — Panel : UI users + UI mes tokens

> **But (1 phrase)** : ajouter dans le panel deux pages — `/users` (vue
> globale des utilisateurs miroir + rôles, scope `users:read`/`users:manage`)
> et `/me/tokens` (gestion de ses propres tokens API, scope
> `tokens:manage_own`).
>
> **Ne fait PAS** : la création d'utilisateurs (ça se passe dans Authentik en
> V1, avec un lien profond depuis le panel). Pas non plus l'UI rôles
> Authentik elle-même.

## 0. Pré-requis

- C2 ✅ — `/users`, `/users/{id}/roles` (anti-lockout dernier owner inclus).
- C3 ✅ — `/me/tokens` GET/POST/DELETE (format `eurio_<43 base64url>`, refus `audit:write`).
- C5 ✅ — panel shell (`admin/packages/panel/`).
- Lire d'abord : [`RESUME-NEXT-SESSION.md`](./RESUME-NEXT-SESSION.md).
- Branche : `auth-redesign-c8`.

## 1. Page `/users` (Users.vue)

- Table : `email`, `name`, `roles` (badges), `last_login_at`, `active`.
- Pour un `owner` (scope `users:manage`) : éditeur de rôles inline (cocher
  `owner`/`admin`/`reviewer`) → `PUT /users/{id}/roles`.
- **Disclaimer visible** : "La création/suppression d'utilisateurs se fait
  dans Authentik" + bouton lien profond vers `https://authentik.musubi.dev/...`.
- Pour un `admin` (scope `users:read` seul) : table en lecture seule, pas
  d'édition.

Détails UX :
- Empty state : "Aucun utilisateur synchronisé. Les users apparaissent ici
  après leur premier login."
- Confirmation modale avant retrait du dernier rôle d'un user.
- Erreur API si on tente d'attribuer un rôle non couvert par les groupes
  Authentik réels → afficher le message renvoyé par `eurio-api`.

## 2. Page `/me/tokens` (MyTokens.vue)

- Table : `name`, `scopes`, `created_at`, `last_used_at`, `revoked_at`,
  bouton "Révoquer".
- Bouton "Créer un token" → modale :
  - input `name`
  - checkboxes `scopes` (filtrées par les scopes effectifs du user)
  - input optionnel `expires_at` (date picker)
  - submit → `POST /me/tokens`
- À la réponse, **afficher le clair dans un panneau dédié** avec :
  - copy-to-clipboard
  - avertissement "Ce token ne sera plus jamais affiché"
  - bouton "Compris, fermer" (qui purge le clair du DOM/state).

## 3. Composables / API

Créer `admin/packages/panel/src/api/users.ts` + `tokens.ts`. **`api/client.ts` expose `api.get/post/put/delete<T>(path, body?)`**.

```ts
import { api } from './client'

export interface UserRow {
  id: string
  email: string
  name: string
  created_at: number
  last_login_at: number | null
  active: boolean
  roles: string[]
}

export const usersApi = {
  list: () => api.get<UserRow[]>('/users'),
  setRoles: (id: string, roles: string[]) =>
    api.put<{ user_id: string; roles: string[] }>(`/users/${id}/roles`, { roles }),
}

export interface TokenRow {
  id: number
  name: string
  scopes: string[]
  created_at: number
  last_used_at: number | null
  revoked_at: number | null
  expires_at: number | null
  active: boolean
}

export interface CreateTokenResponse {
  id: number
  name: string
  scopes: string[]
  expires_at: number | null
  token: string  // CLAIR — à afficher une fois, jamais persister
  warning: string
}

export const tokensApi = {
  list: () => api.get<TokenRow[]>('/me/tokens'),
  create: (body: { name: string; scopes: string[]; expires_at?: number | null }) =>
    api.post<CreateTokenResponse>('/me/tokens', body),
  revoke: (id: number) => api.delete<{ id: number; revoked_at: number }>(`/me/tokens/${id}`),
}
```

## 4. Critères d'acceptation

- Owner : voit la table, peut éditer les rôles, sauvegarde OK.
- Admin : voit la table, pas de boutons d'édition.
- Reviewer : `/users` redirige vers `not-authorized`.
- N'importe quel user authentifié : peut créer + révoquer ses tokens, ne voit
  pas ceux des autres.
- Le clair d'un token créé n'apparaît **jamais** dans la console du browser
  ni dans `localStorage`.

## 5. Garde-fous

- **Ne jamais persister** le clair (ni state durable, ni localStorage). Vie
  du clair = vie de la modale.
- Confirmer toute action destructive (révocation, retrait de rôle).
- Lien profond Authentik : utiliser une env var `VITE_AUTHENTIK_URL` (pas
  hardcoded), et target `_blank rel="noopener"`.

## 6. Résumé

```
## C8 — résumé UI users + tokens

- Page /users : OK (owner edit / admin read / reviewer 403)
- Page /me/tokens : OK (create / list / revoke)
- Clair affiché une seule fois : OK
- Lien Authentik : <URL>
- Déviations : <…>
```
