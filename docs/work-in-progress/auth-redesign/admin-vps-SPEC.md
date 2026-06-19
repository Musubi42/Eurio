# `admin-vps` — spec du panel léger hosté

> Spec courte du frontend `admin/packages/admin-vps/` servi à
> `https://eurio-admin.musubi.dev`. Décidé le 2026-06-19.

## 1. Identité

- **Nom** : `eurio-admin-vps` (package pnpm).
- **URL** : `https://eurio-admin.musubi.dev`.
- **Stack** : Vue 3 + Vite + Pinia + vue-router.
- **Build** : SPA statique, image nginx derrière Traefik (voir
  `infra/eurio-admin/`).
- **Auth** : OIDC via Authentik, cookie `eurio_session` posé par
  `eurio-api`.

## 2. Promesse

> Un panel **léger**, **mobile-friendly**, **read-mostly**, accessible
> depuis n'importe quel browser sans setup dev. Pour de l'admin
> ponctuelle (gérer des users, consulter des stats, regarder de la
> donnée). Pas de heavy lifting.

## 3. Surface fonctionnelle attendue

| Domaine | In | Out |
|---|---|---|
| **Auth** | login Authentik, /me, logout | gestion compte (passer par Authentik directement) |
| **Users** | CRUD users + rôles (`users:read` + `users:manage`) | provisioning (= dans Authentik) |
| **Mes tokens** | générer / lister / révoquer mes PAT | tokens d'autres users |
| **Dashboards / KPIs** | counts coins, sets, sources, review pending | actions ML |
| **Consultation données** | lecture coins, sets, audit | édition (= studio-local) |
| **Audit log** | lecture sets_audit, activité, sécurité | rien d'autre |
| **Settings perso** | thème, préférences UI | rien backend |

**Out of scope strict** :

- Édition de coins / sets / criteria (= studio-local)
- Lancement training / scrape / crops (= studio-local)
- Review fast-iter (claim/decide/skip — voir
  [`ARCHITECTURE.md §7`](./ARCHITECTURE.md) pour le débat "friends review")
- Tout ce qui appelle ML API local `:8042` (impossible depuis HTTPS)

## 4. UX / contraintes

### 4.1 Mobile first

L'usage typique : tu es au taf sans Mac, ton tel à la main, tu veux :

- Inviter Paolo en `reviewer` (créer/setup son Authentik puis grant role).
- Voir combien d'items review pending.
- Révoquer un PAT que tu sens fuiter.
- Mater une stat sur les coins.

→ Le panel doit être **utilisable au pouce** : touch targets ≥ 44px,
sidebar collapsible en drawer mobile, tables → cards en breakpoint <640px,
formulaires single-column.

### 4.2 Léger

- Bundle JS gzip < 80KB (actuellement 39KB en C5).
- Pas de canvas, pas de webgl, pas de heavy charts (sparkline simple OK).
- Pas de polling agressif (refresh manuel via bouton + intervalle 30s
  max si live).

### 4.3 Lecture-mostly

CRUD limité à :

- Users : changer rôles (`PUT /users/{id}/roles`).
- Tokens perso : `POST /me/tokens`, `DELETE /me/tokens/{id}`.

Le reste = `GET` uniquement. Toute action d'édition complexe (sets,
criteria, etc.) renvoie vers `studio-local` avec un lien "édite ça dans
studio-local sur ton Mac".

## 5. Architecture interne

```
admin/packages/admin-vps/src/
├── api/
│   ├── client.ts           ← fetch + credentials:'include' vers eurio-api
│   ├── users.ts            ← /users, /users/{id}/roles
│   ├── tokens.ts           ← /me/tokens
│   └── stats.ts            ← /stats agrégés (read-only)
├── stores/
│   └── auth.ts             ← Pinia : Principal + hasScope/hasRole
├── views/
│   ├── Home.vue            ← dashboard KPIs
│   ├── Login.vue           ← bouton OIDC
│   ├── NotAuthorized.vue
│   ├── users/
│   │   └── UsersPage.vue   ← table + edit rôle
│   ├── tokens/
│   │   └── MyTokensPage.vue ← lister + créer + révoquer
│   └── settings/
│       └── SettingsPage.vue ← preferences perso
├── components/
│   ├── AppShell.vue        ← drawer responsive (sidebar desktop, bottom-nav mobile ?)
│   ├── KpiCard.vue
│   └── ResponsiveTable.vue ← table → cards en mobile
├── router/
│   └── index.ts            ← guards par scope
└── styles/
    └── main.css            ← tokens.css + responsive utilities
```

## 6. Build + déploiement

Cf. `infra/eurio-admin/` :

- `Dockerfile` multistage (`node:20-alpine` → `nginx:1.27-alpine`)
- `nginx.conf` SPA fallback
- `docker-compose.yml` avec labels Traefik

À chaque change touchant `packages/admin-vps/` ou `shared/tokens.css` :

```bash
cd infra/eurio-admin
docker compose up -d --build
```

Aucun secret SOPS requis (tout l'URL/flag est public).

## 7. Différences par rapport à `studio-local`

| Concept | `admin-vps` | `studio-local` |
|---|---|---|
| Source de design tokens | `shared/tokens.css` (idem) | `shared/tokens.css` (idem) |
| Composants UI | nouveaux, mobile-first | existants (table dense, sidebar desktop) |
| Wrapper API | `credentials:'include'` | `Authorization: Bearer` |
| Pinia stores | `auth` (Principal) + `settings` | `auth` (Principal via PAT) + tous les stores métier existants |
| Vue Router | guards par scope, `meta.public` pour login | idem mais surface plus large |
| Build env | `VITE_EURIO_API_BASE` (durci à `eurio-api.musubi.dev`) | `VITE_EURIO_API_BASE` + `VITE_EURIO_PAT` |

## 8. Périmètre de la session "build admin-vps"

Hors scope cette session :

- Implémenter Users CRUD complet (peut attendre — squelette OK)
- Dashboards riches (KPIs basiques OK)
- Tout layout mobile-first complet

Scope cette session (après le rename + cleanup) :

- Squelette auth fonctionnel (login OIDC + Principal + guards). **Déjà fait en C5**.
- Suppression des vues review accidentellement ajoutées en C6.
- Re-déploiement avec le bon package renamé.

## 9. Évolutions futures

- Vues Users/Tokens complètes (C8 retravaillé pour admin-vps).
- Layout responsive mobile-first (drawer + bottom-nav).
- "Friends review" si on décide α (cf. `ARCHITECTURE.md §7`).
- PWA installable sur tel ?
