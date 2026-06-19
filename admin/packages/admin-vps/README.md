# admin/packages/admin-vps — Eurio panel léger VPS

Front admin léger servi à `https://eurio-admin.musubi.dev` (cf.
`infra/eurio-admin/`). Vue 3 + Vite + Pinia + Vue Router, TypeScript strict.

**Note 2026-06-19** : ce package était initialement `admin/packages/panel/`
et conçu pour remplacer `packages/web/`. Le pivot architectural a redéfini
les rôles — voir
[`docs/work-in-progress/auth-redesign/ARCHITECTURE.md`](../../../docs/work-in-progress/auth-redesign/ARCHITECTURE.md) :
- `studio-local` (ex `packages/web/`) reste le front canonique de travail.
- `admin-vps` (ce package) sert la consultation lightweight + users/tokens,
  mobile-friendly.

## Stack

| Lib | Version | Usage |
|---|---|---|
| Vue 3 | 3.5.x | UI |
| Vite | 6.x | dev server + build |
| Pinia | 3.x | store (auth principal) |
| Vue Router | 4.x | nav + guards de scope |
| TypeScript | 5.6.x | strict mode |

Pas de Tailwind / UI lib pour le skeleton — plain CSS + tokens partagés
(`shared/tokens.css`). Une UI lib sera ajoutée seulement si elle apporte un
gain net (Radix, shadcn-vue, etc.) — décidée plus tard.

## Auth

Le panel **ne décode pas** le JWT de session. Tout passe par cookie HttpOnly
`eurio_session` posé par `eurio-api` après le callback OIDC. Le store
`useAuthStore` appelle `/me` au boot et expose `principal` + `hasScope()`.

Flow login :
1. `/login` → bouton "Se connecter" → redirige vers
   `${VITE_EURIO_API_BASE}/auth/oidc/login?return_to=...`.
2. `eurio-api` redirige vers Authentik (PKCE+state).
3. Authentik → user login → callback `eurio-api` → cookie posé →
   redirige vers le panel (`return_to` ou racine).
4. Le panel recharge `/me` au boot suivant.

## Dev local

```bash
cd admin/packages/panel
pnpm install                # à faire une fois
pnpm dev                    # http://localhost:5173
```

Vite lit `VITE_EURIO_API_BASE` depuis l'env (via direnv, peuplé par
`secrets/dev.env`). Override possible via `.env.local` (gitignored).

### Mode dev bypass (sans Authentik)

Active des deux côtés :

- Backend : `EURIO_DEV_BYPASS=1` côté `eurio-api` + `EURIO_COOKIE_SECURE=0`
  + `EURIO_COOKIE_SAMESITE=lax` (le browser refuse Secure sur http://localhost).
- Frontend : `VITE_EURIO_DEV_BYPASS=1` côté panel.

Un bouton "Dev bypass (local)" apparaît alors sur `/login` et redirige vers
`/auth/oidc/dev/login` qui émet une session pour un user fictif owner/admin/reviewer.

L'`eurio-api` refuse de démarrer avec `EURIO_DEV_BYPASS=1` si
`EURIO_PANEL_ORIGIN` contient `musubi.dev` (garde-fou contre activation
accidentelle en prod — cf. `assert_dev_bypass_safe()`).

## Structure

```
src/
├── api/client.ts          ← wrapper fetch (credentials:'include')
├── stores/auth.ts         ← Pinia : principal, hasScope, login, logout
├── router/index.ts        ← routes + guard global par scope
├── components/AppShell.vue ← layout : sidebar nav + topbar + outlet
├── views/
│   ├── Login.vue          ← boutons login (Authentik + dev)
│   ├── Home.vue           ← dashboard (affiche principal)
│   ├── NotAuthorized.vue  ← page 403 quand scope manquant
│   └── Placeholder.vue    ← écran générique pour les sections à porter
├── styles/main.css        ← @import shared/tokens.css + aliases sémantiques
├── App.vue                ← boot loader + <RouterView/>
└── main.ts                ← createApp / Pinia / Router
```

## Déploiement (C9)

Pas dans le scope de C5. Le panel sera bundlé statique (`pnpm build → dist/`)
et servi par Nginx (`infra/panel/`) sur `eurio-admin.musubi.dev` derrière
Traefik. CSP draftée dans `docs/work-in-progress/auth-redesign/C5-HANDOFF-PANEL-SHELL.md §10`.
