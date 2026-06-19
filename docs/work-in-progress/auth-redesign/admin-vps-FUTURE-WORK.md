# admin-vps — chantiers parqués (à reprendre plus tard)

> Décidé le 2026-06-19 : on se focalise sur `studio-local` (heavy local).
> `admin-vps` est livré en MVP fonctionnel (auth OIDC + Mes Tokens + Users)
> et c'est suffisant pour l'usage immédiat. Les chantiers ci-dessous le
> rendront vraiment confortable à terme.

## Statut actuel `admin-vps` (2026-06-19)

✅ Déployé sur `https://eurio-admin.musubi.dev`
✅ Auth OIDC via Authentik (cookie `eurio_session`)
✅ Page **Mes Tokens** : CRUD complet des PAT, modale clair-une-fois, copy-to-clipboard
✅ Page **Users** : liste miroir local + édition rôles (owner/admin/reviewer), anti-lockout
✅ Bundle ~46KB gzip, typecheck clean
⏸️ Layout responsive **partiel** (utilise des breakpoints media-query simples, mais pas de drawer mobile ni de bottom-nav)
⏸️ Dashboard Home = liste des rôles/scopes courants (placeholder)
⏸️ Vues Sources / Coins / Audit / Review / Training = Placeholder

## F8 — Layout responsive mobile-first

**But** : rendre `admin-vps` réellement utilisable au pouce sur tel
(c'était une exigence explicite — cf. `ARCHITECTURE.md` §3).

### Surface

- `src/components/AppShell.vue` : sidebar fixe 240px en desktop. À transformer en :
  - Desktop ≥ 1024px : sidebar fixe (comme aujourd'hui)
  - Tablet 640-1023px : drawer rétractable (icône hamburger top-left)
  - Mobile < 640px : bottom-nav avec icônes uniquement (3-5 items max, le reste dans un overflow menu)
- Tables (`UsersPage`, `MyTokensPage` en partie) : déjà responsive via media-queries CSS. À vérifier sur vrai device tel.
- Topbar : actuellement email + rôles. Mobile = juste avatar/initiale + rôle compact.
- Modales (`MyTokensPage` modale création) : déjà max-height: 90vh + max-width: 560px. Vérifier sur vrai tel.

### Implémentation

1. Refactor `AppShell.vue` :
   - Composable `useSidebarMode()` qui détecte le breakpoint (matchMedia)
   - 3 rendus : `<DesktopSidebar />`, `<MobileDrawer />`, `<MobileBottomNav />`
   - Drawer = overlay avec backdrop + close on outside click + close on route change
   - Bottom-nav : items principaux (Home, Tokens, Users, …) + un "More" qui ouvre le drawer
2. Composant `<ResponsiveTable>` (déjà mentionné dans `admin-vps-SPEC.md` §5) :
   - Wrapper qui rend table en desktop, liste de cards en mobile
   - À appliquer à `UsersPage` et `MyTokensPage` (les pages existantes l'ont fait inline, mais à standardiser)
3. Touch targets ≥ 44px partout (boutons, liens nav, checkboxes).
4. Tester sur un vrai tel (Safari iOS + Chrome Android) avec le PAT déjà créé.

### Estimation : 2-3h

## F9 — Dashboard KPIs

**But** : avoir une Home utile au lieu du placeholder actuel.

### Surface

Réécrire `src/views/Home.vue` :

- En tête : nom + email du user + rôles courants (déjà OK actuellement)
- 4-6 KPI cards en grid responsive :
  - Coins (total, dont needs-review)
  - Sets (total)
  - Sources (configurées, runs des 24h)
  - Review queue (pending, claimed)
  - Tokens actifs (le tien)
  - Users (total, actifs)
- Sparklines optionnels (counts sur 7j) — pas critique
- Refresh manuel + interval auto (30-60s)

### Endpoints requis côté eurio-api

À créer si pas déjà présents :

- `GET /stats/coins` — `{total, needs_review, by_country: {...}}`
- `GET /stats/sets` — `{total, draft, published}`
- `GET /stats/sources` — `{total, runs_24h, last_run_at}`
- `GET /stats/review` — déjà disponible via `/review/flow`
- `GET /stats/users` — `{total, active, by_role: {...}}` (scope `users:read`)
- `GET /stats/tokens` — `{mine_active, mine_total}` (scope `tokens:manage_own`)

Ces endpoints sont simples (un SELECT count par table). Soit on les écrit
dans un nouveau `ml/serving/stats_routes.py`, soit on agrège dans `/me/stats`
côté admin-vps (mais ça change la sémantique de `/me/stats` legacy review).
**Décision** : nouveau `stats_routes.py`, scope par endpoint.

### Implémentation

1. Backend : `stats_routes.py` avec les 6 endpoints
2. Frontend : `src/api/stats.ts` + `src/views/Home.vue` réécrit avec KpiCard
3. Pas de cache ni de polling agressif — fetch on mount + bouton refresh manuel

### Estimation : 2h (1h backend, 1h frontend)

## Autres chantiers parqués `admin-vps`

### Vue Audit log
- `GET /audit/events?limit=…&since=…` (lecture `auth_audit` + `sets_audit`)
- Vue chronologique paginée, filtres par event type et user
- Mobile-friendly card per event

### Vue Coins (consultation only)
- Page lecture des coins canoniques (post D2-D7, quand `coins` est en SQLite VPS)
- Pas d'édition (édition = studio-local)
- Search/filter basique
- Mobile-friendly

### Vue Sets (consultation only)
- Idem, lecture seule, mobile-friendly

### PWA installable
- Manifest + service worker minimal pour pouvoir "Add to Home Screen" sur iOS/Android
- Pas de cache offline complexe — juste l'install prompt

## Ordre suggéré

1. **F8 mobile-first** : c'est ce qui débloque l'usage tel
2. **F9 dashboard** : utile mais bonus
3. Vue Audit log : intéressant pour la sécurité
4. Vues consultation Coins/Sets : utile mais dépend du chantier data (D2-D7)
5. PWA : bonus polish

## Quand reprendre ?

Quand `studio-local` est dans un état satisfaisant (data layer stabilisé,
features qui débloquent l'usage daily), revenir ici et attaquer **F8** en
priorité — c'est le plus impactant pour l'usage réel mobile.
