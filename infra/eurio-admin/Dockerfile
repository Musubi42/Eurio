# syntax=docker/dockerfile:1.6
#
# Eurio Admin Panel — front riche `studio-local` servi en HÉBERGÉ (Model B / R1).
# UN seul codebase : en hébergé, build `VITE_DEPLOY_TARGET=hosted` → auth cookie OIDC,
# features lourdes ML grisées. Servi en statique par nginx derrière Traefik. Build
# context = ce dossier ; les sources viennent par `additional_contexts`
# (docker-compose.yml) : admin → ../../admin, shared → ../../shared (tokens.css canonique).

# ── Stage 1 : build SPA ────────────────────────────────────────────────────
FROM node:20-alpine AS builder

ENV PNPM_HOME=/pnpm \
    PATH=/pnpm:$PATH

RUN corepack enable && corepack prepare pnpm@9.12.0 --activate

# On reproduit la structure du repo : studio-local importe `shared/tokens.css` en
# relatif (résout vers la racine = /build), comme en local (shared sibling d'admin).
WORKDIR /build

# Workspace pnpm (admin/ root + packages/studio-local/).
COPY --from=admin pnpm-workspace.yaml admin/pnpm-workspace.yaml
COPY --from=admin package.json admin/package.json
COPY --from=admin pnpm-lock.yaml admin/pnpm-lock.yaml
COPY --from=admin packages/studio-local admin/packages/studio-local

# shared/ (tokens.css canonique).
COPY --from=shared . shared/

WORKDIR /build/admin

# Installer uniquement les deps de studio-local (frozen-lockfile pour repro).
RUN pnpm install --frozen-lockfile --filter "eurio-studio-local..."

# Env de build hébergé, injectée à la compilation (cf. vite.config define) :
#  - DEPLOY_TARGET=hosted → auth cookie OIDC + features lourdes grisées
#  - EURIO_API_BASE → backend canonique
# (Supabase retiré du front en D7 — plus aucun VITE_SUPABASE_* requis au build.)
ARG VITE_DEPLOY_TARGET=hosted
ARG VITE_EURIO_API_BASE=https://eurio-api.musubi.dev
ENV VITE_DEPLOY_TARGET=$VITE_DEPLOY_TARGET \
    VITE_EURIO_API_BASE=$VITE_EURIO_API_BASE

RUN pnpm -C packages/studio-local build

# ── Stage 2 : nginx static ──────────────────────────────────────────────────
FROM nginx:1.27-alpine AS runtime

COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=builder /build/admin/packages/studio-local/dist /usr/share/nginx/html

EXPOSE 80

# Healthcheck simple : la page index est servie.
HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
  CMD wget -qO- http://127.0.0.1/ >/dev/null 2>&1 || exit 1
