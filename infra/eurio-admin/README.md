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
cd /opt/eurio/infra/eurio-admin
docker compose up -d --build
```

Le build n'a plus besoin d'aucun secret : depuis D7, le front ne dépend plus de
Supabase. Seuls `VITE_DEPLOY_TARGET=hosted` + `VITE_EURIO_API_BASE` (constantes
publiques) sont injectés, en dur dans `docker-compose.yml`.

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
