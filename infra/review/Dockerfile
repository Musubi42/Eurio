# syntax=docker/dockerfile:1.6
#
# Eurio Review Service — image autonome (FastAPI + front statique).
#
# Build context = ce dossier (infra/review). Les sources viennent par
# `additional_contexts` (docker-compose.yml) :
#   - admin → ../../admin   (workspace pnpm, pour builder le front Vue)
#   - ml    → ../../ml      (review_service + shared/storage)
#
# Stage 1 : node-builder → build du front (admin/packages/review/dist)
# Stage 2 : python:3.12-slim → runtime FastAPI + uvicorn + boto3

# ─── Stage 1 : front Vue ──────────────────────────────────────────────────
FROM node:20-alpine AS front-builder

RUN corepack enable && corepack prepare pnpm@9.12.0 --activate

WORKDIR /admin

# Workspace pnpm complet (lockfile + manifests). On installe uniquement le
# filter du front reviewer ; `review-admin` legacy (régie X-Admin-Token) a
# été supprimé en 2026-06-19 (cf. memory project_friends_review_deferred —
# Authentik OIDC remplace la régie legacy).
COPY --from=admin pnpm-workspace.yaml pnpm-lock.yaml package.json ./
COPY --from=admin packages/review packages/review

# Tokens canoniques. Depuis 2026-08-14 (ADR-007) `shared/` est un package du
# workspace pnpm (`@eurio/shared`), déclaré dans admin/pnpm-workspace.yaml par
# l'entrée `../shared`. WORKDIR étant /admin, `../shared` résout vers /shared —
# on reproduit donc le layout du repo à la racine du stage.
#
# ⚠️ Copier le dossier ENTIER, pas seulement tokens.css : sans son package.json
# le workspace ne résout pas et `pnpm install --frozen-lockfile` échoue.
COPY --from=shared . /shared/

RUN pnpm install \
      --filter eurio-review-front... \
      --frozen-lockfile

# L'API est servie par la même origine → chemins relatifs côté front. Si on
# split front/API un jour, passer VITE_REVIEW_API en build-arg.
ARG VITE_REVIEW_API=""
ENV VITE_REVIEW_API=${VITE_REVIEW_API}
RUN pnpm --filter eurio-review-front build


# ─── Stage 2 : runtime Python ─────────────────────────────────────────────
FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    TZ=UTC

# Deps Python : strictement nécessaire, pas la stack ml complète (pas de
# torch / opencv / ultralytics). Pin majeur uniquement.
RUN pip install --no-cache-dir \
        "fastapi>=0.115,<0.120" \
        "uvicorn[standard]>=0.32,<0.40" \
        "boto3>=1.35,<2.0"

# Layout reproduit du repo : /srv/ml/{review_service,shared} + /srv/admin/
# packages/review/dist. Le code (ml/review_service/app.py) calcule
# `_ML_DIR.parent / "admin" / "packages" / "review" / "dist"` → ça tombe
# pile sur /srv/admin/... sans aucun patch.
WORKDIR /srv/ml

COPY --from=ml review_service ./review_service
COPY --from=ml shared/__init__.py ./shared/__init__.py
COPY --from=ml shared/storage ./shared/storage

COPY --from=front-builder /admin/packages/review/dist \
     /srv/admin/packages/review/dist

# Entrypoint : lit les secrets fichiers (/run/secrets/*) → exporte en env,
# puis exec uvicorn.
COPY entrypoint.sh /usr/local/bin/entrypoint.sh
RUN chmod +x /usr/local/bin/entrypoint.sh

# review.db monté en volume → /var/lib/eurio/ (créé par compose).
ENV REVIEW_DB_PATH=/var/lib/eurio/review.db

EXPOSE 8048

ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
CMD ["uvicorn", "review_service.app:app", "--host", "0.0.0.0", "--port", "8048"]
