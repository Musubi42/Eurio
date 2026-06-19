# syntax=docker/dockerfile:1.6
#
# Eurio Admin Panel (SPA Vue/Vite) — servi en statique par nginx derrière
# Traefik. Build context = ce dossier ; les sources viennent par
# `additional_contexts` (docker-compose.yml) : admin → ../../admin,
# shared → ../../shared (tokens.css canonique).

# ── Stage 1 : build SPA ────────────────────────────────────────────────────
FROM node:20-alpine AS builder

ENV PNPM_HOME=/pnpm \
    PATH=/pnpm:$PATH

RUN corepack enable && corepack prepare pnpm@9.12.0 --activate

# L'alias Vite `@shared` est `path.resolve(__dirname, '../../../shared')`
# où __dirname = packages/panel/. Depuis /build/admin/packages/panel/ ça
# résout vers /build/shared. On reproduit donc la même structure que le repo.
WORKDIR /build

# Workspace pnpm complet (admin/ root + packages/panel/).
COPY --from=admin pnpm-workspace.yaml admin/pnpm-workspace.yaml
COPY --from=admin package.json admin/package.json
COPY --from=admin pnpm-lock.yaml admin/pnpm-lock.yaml
COPY --from=admin packages/admin-vps admin/packages/admin-vps

# shared/ (tokens.css canonique).
COPY --from=shared . shared/

WORKDIR /build/admin

# Installer uniquement les deps du panel (frozen-lockfile pour repro).
RUN pnpm install --frozen-lockfile --filter "eurio-admin-vps..."

# Build avec env de prod (URL eurio-api injectée à la compilation).
ARG VITE_EURIO_API_BASE=https://eurio-api.musubi.dev
ENV VITE_EURIO_API_BASE=$VITE_EURIO_API_BASE

RUN pnpm -C packages/admin-vps build

# ── Stage 2 : nginx static ──────────────────────────────────────────────────
FROM nginx:1.27-alpine AS runtime

COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=builder /build/admin/packages/admin-vps/dist /usr/share/nginx/html

EXPOSE 80

# Healthcheck simple : la page index est servie.
HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
  CMD wget -qO- http://127.0.0.1/ >/dev/null 2>&1 || exit 1
