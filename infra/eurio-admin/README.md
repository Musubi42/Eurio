# infra/eurio-admin

Panel admin Vue/Vite servi en statique par nginx derrière Traefik.

- **Host** : `https://eurio-admin.musubi.dev`
- **API cible** : `https://eurio-api.musubi.dev` (injectée à la compilation via
  `VITE_EURIO_API_BASE` dans `docker-compose.yml`).
- **Source** : `admin/packages/admin-vps/` (workspace pnpm `admin/`).
- **Build** : multistage Docker — `node:20-alpine` (pnpm install + `vite build`)
  → `nginx:1.27-alpine` (static + SPA fallback).

## Déploiement

```bash
cd infra/eurio-admin
docker compose up -d --build
```

Aucun secret SOPS requis pour ce service — tout est public (URL API,
flag dev-bypass). Le compose se contente des labels Traefik.

## Mise à jour

À chaque PR mergée touchant `admin/packages/admin-vps/` ou `shared/tokens.css` :

```bash
cd infra/eurio-admin
docker compose up -d --build
```

(Aucun cache d'image, pas de tagging — `image: eurio-admin:latest` est
recompilé à chaque `--build`.)

## Pré-requis

- Réseau Docker externe `traefik` (déjà créé par le stack `oim-traefik`).
- DNS `eurio-admin.musubi.dev` → IP du VPS (CNAME ou A).
- Résolveur ACME Let's Encrypt `letsencryptresolver` côté Traefik
  (déjà configuré pour `eurio-api`).
