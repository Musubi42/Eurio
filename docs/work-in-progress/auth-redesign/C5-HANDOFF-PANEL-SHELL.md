# C5 — Panel : skeleton Vue + login OIDC + shell

> **But (1 phrase)** : poser `admin/packages/panel` (nouveau workspace pnpm),
> Vue 3 + Vite + Pinia + Vue Router, avec login OIDC fonctionnel (redirection
> `eurio-api`) et une app shell minimale (nav + header + outlet).
>
> **Ne fait PAS** : porter les écrans review/sources/coins (C6, C7), ni l'UI
> users/tokens (C8). Ici on construit la coquille et on prouve que le login
> marche de bout en bout.

## 0. Pré-requis

- C2 ✅ — `/auth/oidc/login`, `/auth/oidc/callback`, `/me` opérationnels.
- pnpm workspace `admin/` opérationnel.
- Branche : `auth-redesign-c5`.

## 1. Création du workspace

```bash
cd admin/packages
pnpm create vite panel --template vue-ts
cd panel
pnpm add vue-router pinia
pnpm add -D @types/node
```

Ajouter dans `admin/pnpm-workspace.yaml` (s'il n'inclut pas déjà `packages/*`).

## 2. Structure

```
admin/packages/panel/
├── index.html
├── package.json
├── vite.config.ts
├── tsconfig.json
└── src/
    ├── main.ts
    ├── App.vue
    ├── router/
    │   └── index.ts
    ├── stores/
    │   └── auth.ts            ← Pinia store, charge /me, expose principal
    ├── api/
    │   └── client.ts          ← wrapper fetch avec cookie credentials
    ├── views/
    │   ├── Login.vue          ← page de transition (redirige vers /auth/oidc/login)
    │   ├── Home.vue           ← dashboard simple, liens vers les sections
    │   └── NotAuthorized.vue
    ├── components/
    │   └── AppShell.vue       ← layout : nav latérale + header + <RouterView/>
    └── styles/
        └── main.css           ← @import shared/tokens.css (cf. CLAUDE.md R2)
```

## 3. Auth store (`stores/auth.ts`)

```ts
// Pseudocode.
export const useAuthStore = defineStore('auth', () => {
  const principal = ref<Principal | null>(null);
  const loading = ref(true);

  async function load() {
    try {
      principal.value = await api.get('/me');
    } catch {
      principal.value = null;
    } finally {
      loading.value = false;
    }
  }

  function hasScope(s: string): boolean { /* ... */ }
  function hasRole(r: string): boolean { /* ... */ }
  function login() {
    window.location.href = `${import.meta.env.VITE_EURIO_API_BASE}/auth/oidc/login?return_to=${encodeURIComponent(location.href)}`;
  }
  async function logout() {
    await api.post('/auth/oidc/logout');
    principal.value = null;
    router.push('/login');
  }
  return { principal, loading, load, hasScope, hasRole, login, logout };
});
```

## 4. Router avec guard global

```ts
router.beforeEach(async (to) => {
  const auth = useAuthStore();
  if (auth.loading) await auth.load();
  if (to.meta.public) return true;
  if (!auth.principal) return { name: 'login', query: { return_to: to.fullPath } };
  if (to.meta.scope && !auth.hasScope(to.meta.scope as string)) return { name: 'not-authorized' };
  return true;
});
```

Routes initiales :

```ts
const routes = [
  { path: '/login', name: 'login', component: Login, meta: { public: true } },
  { path: '/not-authorized', name: 'not-authorized', component: NotAuthorized, meta: { public: true } },
  {
    path: '/',
    component: AppShell,
    children: [
      { path: '', name: 'home', component: Home },
      // placeholders pour les futurs ports
      { path: 'sources', component: () => import('./views/Placeholder.vue'), meta: { scope: 'sources:read' } },
      { path: 'coins', component: () => import('./views/Placeholder.vue'), meta: { scope: 'coins:read' } },
      { path: 'audit', component: () => import('./views/Placeholder.vue'), meta: { scope: 'audit:read' } },
      { path: 'review', component: () => import('./views/Placeholder.vue'), meta: { scope: 'review:read' } },
      { path: 'training', component: () => import('./views/Placeholder.vue'), meta: { scope: 'training:run' } },
      { path: 'users', component: () => import('./views/Placeholder.vue'), meta: { scope: 'users:read' } },
      { path: 'me/tokens', component: () => import('./views/Placeholder.vue'), meta: { scope: 'tokens:manage_own' } },
    ],
  },
];
```

## 5. `AppShell.vue`

- Nav latérale avec liens vers chaque section, filtrés par `hasScope`.
- Header avec `{ principal.email }` + bouton logout + badge des rôles.
- `<RouterView />`.

Tokens via `shared/tokens.css` (couleurs/spacings/rayons). Pas de hardcoded.

## 6. Env / config

`admin/packages/panel/.env.example` :

```
VITE_EURIO_API_BASE=http://localhost:8042
VITE_EURIO_DEV_BYPASS=0       # 1 en dev local sans Authentik joignable
```

En prod : `VITE_EURIO_API_BASE=https://eurio-api.musubi.dev` (défini au build).

CORS : `eurio-api` doit autoriser `http://localhost:5173` (dev) et
`https://admin.musubi.dev` (prod). Vérifier `EURIO_API_CORS_ORIGINS` dans
`infra/eurio-api/docker-compose.yml`. **Important** : `credentials: 'include'`
nécessite `Access-Control-Allow-Credentials: true` et une origine exacte (pas `*`).

### 6.1 Mode dev (remplaçant du `DEV_BYPASS` legacy)

Le legacy `admin/packages/web/src/app/router.ts:191` injectait un user fictif via la service-role Supabase quand `import.meta.env.DEV` était true et qu'on cliquait "DEV bypass". On remplace par un équivalent **côté `eurio-api`**, pas côté front :

- Si `EURIO_DEV_BYPASS=1` côté `eurio-api` (uniquement en compose dev, **jamais** en prod — vérifié au boot), un endpoint `GET /auth/dev/login?email=raphael@example.dev` est exposé. Il :
  1. Refuse en prod (assertion sur `EURIO_PANEL_ORIGIN` ne contient pas `musubi.dev`).
  2. Upsert un user de test (`active=1`, rôle `owner`).
  3. Émet le cookie `eurio_session` JWT HS256 normal (cf. C2 §7).
- Côté panel, si `VITE_EURIO_DEV_BYPASS=1`, la page `/login` affiche un bouton "Dev bypass" qui redirige vers `/auth/dev/login`.
- Aucun secret nouveau à propager : on réutilise `EURIO_SESSION_SECRET`. Pas de fake JWT, pas de divergence de code path.

Garde-fou hard : si `EURIO_DEV_BYPASS=1` ET (`EURIO_PANEL_ORIGIN` contient `musubi.dev` OU le binding écoute autre chose que `127.0.0.1`), `eurio-api` refuse de démarrer.

## 7. Critères d'acceptation

- `pnpm --filter panel dev` démarre Vite sur `http://localhost:5173`.
- Ouvrir `/` → redirection `/login` → bouton "Se connecter" → redirection
  Authentik → après login → retour sur `/` avec email visible dans le header.
- Logout → cookie nettoyé → `/` redirige vers `/login`.
- Un user `reviewer` voit Review/Home dans la nav, **pas** Sources/Training/Users.
- Refresh F5 maintient la session (cookie persistant).

## 8. Garde-fous

- Le panel **ne décode pas** le JWT. Il consomme uniquement `/me` et fait
  confiance au cookie.
- **Pas** de stockage de tokens en `localStorage`/`sessionStorage`. Tout en
  cookie HttpOnly côté serveur.
- CSP stricte : pas d'inline scripts, pas de eval. Définie dans le `nginx.conf`
  servant le bundle (cf. §10 ci-dessous).

## 9. ~~OQ4~~ — Tranché : servage du panel

(Cette OQ revenait sur la table en C9 dans la version précédente. Tranchée ici par cohérence avec D9 all-in et pour figer la CSP dès le panel shell.)

**Choix retenu : Nginx static** (Option A, anciennement renvoyée à C9).

- Le bundle Vue compilé (`pnpm --filter panel build` → `dist/`) est servi par un container Nginx dédié (`infra/panel/`), avec :
  - SPA fallback (`try_files $uri /index.html`)
  - Headers CSP / HSTS / X-Frame-Options
  - Reverse-proxy `/api/*` → `eurio-api:8042/*` (même origine côté browser → cookie SameSite=Lax sans tracas, pas besoin de CORS pré-flight pour les appels normaux ; CORS reste pour l'origine OIDC callback distincte si on garde `eurio-api.musubi.dev` séparé)
  - Volume monté sur `dist/` (push CI ou rsync depuis local pour V1).
- Pourquoi pas FastAPI `StaticFiles` (Option B) : couple le déploiement front au déploiement API, rend la CSP plus complexe à gérer (mélange de headers FastAPI et statiques), et empêche un cache CDN/Traefik granulaire. Le seul avantage (un container de moins) ne justifie pas le couplage.
- L'implémentation effective du container nginx est faite en C9. Ici, C5 fige juste le choix et écrit l'`index.html` + `vite.config.ts` pour qu'ils soient compatibles avec un servage statique racine (`base: "/"`).

## 10. CSP recommandée (à figer dans `infra/panel/nginx.conf` en C9)

```
default-src 'self';
script-src 'self';
style-src 'self' 'unsafe-inline';     # Vue inline styles ; à tightener si possible
img-src 'self' data: https:;
connect-src 'self' https://eurio-api.musubi.dev https://auth.musubi.dev;
frame-ancestors 'none';
form-action 'self' https://auth.musubi.dev;
```

## 11. Résumé à produire

```
## C5 — résumé panel shell

- Branche / commits : <…>
- Vue + Vite + Pinia + Router : OK
- Login OIDC bout-en-bout testé : OUI/NON
- Logout OK : OUI/NON
- Guards par scope : testés OUI/NON
- CORS dev : OK
- Mode dev (EURIO_DEV_BYPASS) testé : OUI/NON
- Choix servage figé (nginx static) : OK
- CSP draft écrite : OUI/NON
- Déviations vs DESIGN.md : <…>
- Open questions pour C7 / C9 : <…>
```
