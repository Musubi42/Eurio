# infra/eurio-admin

Front riche `studio-local` servi en **hébergé** (statique nginx derrière Traefik).
Model B / R1 : un seul codebase, build `VITE_DEPLOY_TARGET=hosted` → auth cookie OIDC,
features lourdes ML grisées (admin-vps retiré).

- **Host** : `https://eurio-admin.musubi.dev`
- **API cible** : `https://eurio-api.musubi.dev` (injectée à la compilation via
  `VITE_EURIO_API_BASE` dans `docker-compose.yml`).
- **Source** : `admin/packages/studio-local/` (workspace pnpm `admin/`).
- **Build** : multistage Docker — `node:20-alpine` (pnpm install + `vite build` mode
  hosted) → `nginx:1.27-alpine` (static + SPA fallback).

## Déploiement

```bash
# Les build args Supabase (publics) viennent de l'env SOPS → passer par direnv exec.
cd /opt/eurio/infra/eurio-admin
direnv exec /opt/eurio docker compose up -d --build
```

`VITE_SUPABASE_URL` + `VITE_SUPABASE_ANON_KEY` (publics, RLS-safe) sont requis au build
(`supabase/client.ts` throw au top-level sans eux — legacy data, retrait = chantier D7).
Ils sont sourcés de `secrets/dev.env` (SOPS) via `direnv exec /opt/eurio`.

## Mise à jour

À chaque PR mergée touchant `admin/packages/studio-local/` ou `shared/tokens.css` :

```bash
cd /opt/eurio/infra/eurio-admin
direnv exec /opt/eurio docker compose up -d --build
```

(Aucun cache d'image, pas de tagging — `image: eurio-admin:latest` est
recompilé à chaque `--build`.)

## Pré-requis

- Réseau Docker externe `traefik` (déjà créé par le stack `oim-traefik`).
- DNS `eurio-admin.musubi.dev` → IP du VPS (CNAME ou A).
- Résolveur ACME Let's Encrypt `letsencryptresolver` côté Traefik
  (déjà configuré pour `eurio-api`).
