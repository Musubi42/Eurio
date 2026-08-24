# Architecture frontend Eurio — `studio-local` vs `admin-vps`

> ⚠️ **SUPERSÉDÉ (2026-06-29).** Le split dual-front `studio-local` vs `admin-vps`
> décrit ici est **abandonné** au profit d'une **fusion en UN seul codebase** (front
> riche servi hébergé-léger via cookie Authentik + local-full via PAT ; features
> lourdes grisées + bandeau « lance en local » côté hébergé). État courant + cible :
> [`../model-b/README.md`](../model-b/README.md) §Front. Doc gardé comme historique.

> **Décision actée le 2026-06-19**. Source de vérité pour toute question
> "où va cette feature ?" et "comment auth ?". Tout autre doc qui contredit
> ce fichier est obsolète.

## 0. Topologie

```
                ┌──────────────────────────────────────────────────────┐
                │  VPS (NixOS, Traefik)                                │
                │  ───────────────────────────────────────────         │
                │  eurio-admin.musubi.dev  ← packages/admin-vps        │
                │  eurio-api.musubi.dev    ← FastAPI ml.serving        │
                │  authentik.musubi.dev    ← OIDC IDP                  │
                │  eurio.db (canonical writer = eurio-api)             │
                └──────────────────────────────────────────────────────┘
                              ▲              ▲
                  cookie OIDC │              │ Bearer PAT
                              │              │
        ┌─────────────────────┴───┐   ┌──────┴──────────────────────┐
        │  Mac (dev + reviews)    │   │  PC (training 1080 Ti)      │
        │  ─────────────────────  │   │  ─────────────────────      │
        │  localhost:5173          │   │  localhost:5173             │
        │  = packages/studio-local │   │  = packages/studio-local    │
        │  ML API local :8042      │   │  ML API local :8042         │
        │  eurio.db (lease MinIO)  │   │  eurio.db (lease MinIO)     │
        │  crops, scrape, reviews  │   │  training jobs              │
        └─────────────────────────┘   └─────────────────────────────┘
```

Deux frontends, **un seul backend** (`eurio-api.musubi.dev`).

## 1. Les deux frontends

| | `studio-local` | `admin-vps` |
|---|---|---|
| **Package** | `admin/packages/studio-local/` | `admin/packages/admin-vps/` |
| **Hôte** | `http://localhost:5173` (Mac, PC) | `https://eurio-admin.musubi.dev` |
| **Lancement** | `pnpm dev` (workspace pnpm) | docker compose (Traefik) |
| **Build** | dev-only, jamais déployé | image nginx static derrière Traefik |
| **Auth** | **Bearer PAT** dans `Authorization` header | **Cookie OIDC** `eurio_session` |
| **Source du PAT** | `.env.local` (gitignored, jamais committé) | n/a (Authentik flow) |
| **Heavy compute** | ✅ ML API local `:8042` (crops, scrape, training) | ❌ aucun |
| **Données data** | Supabase + eurio-api selon les pages (transition vers eurio-api) | eurio-api uniquement |
| **Mobile** | non pertinent (dev machine) | **doit** être responsive |
| **Audience** | le dev (toi) et futures machines dev | toi (mobile + desktop) + futurs admins |
| **Features** | tout : crops, scrape, training, review fast-iter, sets, audit, … | consultation lecture + users + tokens |
| **Cookie SameSite** | n/a (pas de cookie) | `lax` (cross-subdomain OK) |

## 2. Pourquoi deux frontends et pas un seul

Le navigateur **interdit** à une page HTTPS (`eurio-admin.musubi.dev`) de
faire des XHR vers `http://localhost:8042` (mixed content). Donc un
frontend hosté sur le VPS ne peut **jamais** parler au ML API local.

Trois solutions étaient envisagées (cf. discussion 2026-06-19) :

- A. VPS-hosted = lightweight only, dev = local via `pnpm dev`. ← **retenu**.
- B. Tailscale serve sur ML API local (HTTPS via Tailscale Funnel). Possible plus tard si besoin.
- C. mkcert + HTTPS sur localhost. Trop de friction par poste.

Pattern A = zéro infra additionnelle, deux URLs pour deux usages
distincts, frontière nette. Si plus tard B devient utile (ex: piloter le
training PC depuis le tel), on flippera la config sans refondre les apps.

## 3. Règles de placement des features

| Feature | Où ? | Pourquoi |
|---|---|---|
| Auth login OIDC | `admin-vps` (Authentik flow) | Cookie utile uniquement pour `admin-vps` |
| Auth PAT setup | `studio-local` (.env.local) | Seul cas où Bearer est utilisé |
| Users CRUD | `admin-vps` | Léger, mobile-friendly, admin tâche ponctuelle |
| Mes PAT (perso) | **les deux** | Génération possible depuis admin-vps (UI mobile-friendly), saisie côté studio-local |
| Crops review (fast iter) | `studio-local` | Heavy compute ML local |
| Scrape sources (eBay, Numista…) | `studio-local` | ML API local |
| Training launch + monitoring | `studio-local` | GPU local |
| Sets / criteria / audit | `studio-local` (édition), `admin-vps` (consultation read-only) | Édition = beaucoup d'iter, mieux en local |
| Consulter dashboards / KPIs | `admin-vps` | Lecture pure, mobile friendly |
| Confusion analyzer | `studio-local` | Édition + heavy compute |

> **Règle simple** : si la feature appelle le ML API local OU itère
> rapidement sur des données qui devraient être local-first, c'est dans
> `studio-local`. Si la feature est de la lecture / admin légère
> consultable depuis un mobile, c'est dans `admin-vps`.

## 4. Comment les deux apps se parlent à `eurio-api`

### `admin-vps` (cookie OIDC)

1. User clique "Se connecter via Authentik" sur `eurio-admin.musubi.dev/login`.
2. Redirect vers `eurio-api.musubi.dev/auth/oidc/login?return_to=…`.
3. Authentik flow PKCE → callback `eurio-api/auth/oidc/callback`.
4. eurio-api set cookie `eurio_session` (HS256 JWT) sur `eurio-api.musubi.dev`,
   SameSite=Lax (cross-subdomain OK avec `eurio-admin`).
5. Redirect final vers `eurio-admin.musubi.dev`.
6. Tous les XHR `admin-vps → eurio-api` ont `credentials: 'include'` →
   cookie envoyé automatiquement.

### `studio-local` (Bearer PAT)

1. User génère un PAT (via `admin-vps` ou CLI break-glass) avec scopes
   adaptés. Cf. [`PAT-WORKFLOW.md`](./PAT-WORKFLOW.md).
2. User le colle dans `admin/packages/studio-local/.env.local` :
   ```
   VITE_EURIO_API_BASE=https://eurio-api.musubi.dev
   VITE_EURIO_PAT=eurio_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
   ```
3. `pnpm dev` → Vite injecte ces vars à la compilation.
4. Tous les XHR `studio-local → eurio-api` ajoutent
   `Authorization: Bearer <VITE_EURIO_PAT>`.
5. Côté eurio-api : `require_principal` reconnaît le PAT et résout en
   `Principal` (user + scopes effectifs).

## 5. Pourquoi pas de PAT côté `admin-vps`, pas de cookie côté `studio-local`

- **`admin-vps` cookie only** : pas de PAT en localStorage / .env. Le cookie
  est HttpOnly, le JS ne le voit pas. Rotation via OIDC logout.
- **`studio-local` PAT only** : le cookie cross-origin (`localhost` →
  `eurio-api.musubi.dev`) nécessiterait `SameSite=None; Secure` côté
  eurio-api, perte de protection CSRF basique. PAT en Bearer = pas de
  cookie, pas de SameSite à gérer, pas de CSRF (pas de cookie = pas de
  CSRF par construction).

## 6. Évolution du dépôt — packages obsolètes

| Avant 2026-06-19 | Après | Statut |
|---|---|---|
| `admin/packages/web/` | `admin/packages/studio-local/` | renommé |
| `admin/packages/panel/` | `admin/packages/admin-vps/` | renommé |
| `admin/packages/review-admin/` | — | **deprecated**, kill en cleanup |
| `admin/packages/review/` | — | **deprecated** (legacy reviewer UI standalone) — voir section 7 |

## 7. Spec "friends review" (à statuer plus tard)

`admin/packages/review/` est le mini-app reviewer (claim/decide/skip) qui
servait à inviter des potes par lien. Pas porté dans `studio-local`
aujourd'hui — pas la priorité. À statuer ultérieurement :

- Option α : porter ces écrans dans `admin-vps` (mobile-first, accessible
  par un user `reviewer` Authentik). Cohérent avec la philosophie
  admin-vps = features légères + mobile.
- Option β : porter dans `studio-local` (mais alors les potes auraient
  besoin de cloner le repo, pas réaliste).
- Option γ : garder `packages/review/` standalone et le redéployer en
  conteneur séparé (`reviewers.musubi.dev` ?).

Note dans MEMORY : `project_friends_review_deferred`.

## 8. À lire ensuite

- [`PAT-WORKFLOW.md`](./PAT-WORKFLOW.md) — générer, coller, multi-machine, scopes
- [`admin-vps-SPEC.md`](./admin-vps-SPEC.md) — spec du panel léger (mobile-friendly)
- [`RESUME-NEXT-SESSION.md`](./RESUME-NEXT-SESSION.md) — reprise + état chunks
