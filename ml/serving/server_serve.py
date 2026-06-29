"""App serve-role du canonique sur le VPS (Modèle B, chunk C4).

FastAPI LÉGER : writer unique de ``eurio.db`` (volume ``EURIO_DB_PATH``). Monte un
**cœur garanti** (``/healthz`` + auth + ``/ingest/run``) puis les routers
interactifs légers en **best-effort** — tout router dont une dépendance lourde
(cv2/torch/dino…) manque sur l'image lean est **skippé** et journalisé (no CV/ML
sur le VPS, cf. DESIGN.md). Le log de démarrage liste ``montés`` / ``skippés``.

NE PAS confondre avec ``serving/server.py`` (app FULL workstation). Ici aucun
router de calcul lourd n'est exposé.

RÈGLE DE SYNCHRONISATION FULL ↔ LEAN
--------------------------------------
``serving/server.py`` (FULL, workstation Mac/PC) et ce fichier (LEAN, image VPS)
partagent les mêmes routers légers mais divergent intentionnellement sur les
routers lourds (cv2/torch/dino uniquement disponibles sur la workstation).

Lorsqu'un nouveau router est ajouté dans ``server.py`` :
  • S'il est léger (pas de cv2/torch/dino) → l'ajouter également ici en mount
    inconditionnel (section « Cœur garanti » ou bloc direct comme coin_series).
  • S'il est lourd (cv2/torch/dino) → l'ajouter dans ``_CANDIDATES`` ci-dessous ;
    l'image lean le skippera automatiquement à l'ImportError.

Ne jamais supprimer un router de ``_CANDIDATES`` sans le retirer aussi de ``server.py``.
"""
from __future__ import annotations

import importlib
import logging
import os
from pathlib import Path

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from serving import auth as api_auth
from serving import (
    audit_routes,
    auth_routes,
    confusion_routes,
    db_migrate,
    ingest_routes,
    review_routes,
    stats_routes,
    tokens_routes,
    users_routes,
)
from serving.auth_principal import require_principal
from serving.coin_series import router as coin_series_router
from serving.review_queue import router as review_queue_router
from serving.review_queue.writes import router as review_writes_router
from serving.sources import router as sources_router
from store import Store

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("eurio-api")

_DB_PATH = Path(os.environ.get("EURIO_DB_PATH", "/var/lib/eurio/eurio.db"))

# Migrations idempotentes appliquées AVANT que Store n'ouvre la connexion.
# Couvre les nouvelles tables auth (users/roles/user_roles/api_tokens/auth_audit
# — cf. auth-redesign C2). Les tables existantes (training_*, etc.) sont
# gérées par Store via state/schema.sql.
_applied = db_migrate.run_migrations(_DB_PATH)
if _applied:
    log.info("db_migrate: applied %d migration(s): %s", len(_applied), _applied)

_store = Store(_DB_PATH)
api_auth.bind(_store)

# Boot guard : refuse de démarrer si EURIO_DEV_BYPASS=1 dans un contexte prod.
auth_routes.assert_dev_bypass_safe()

app = FastAPI(title="Eurio API (serve)", version="0.1.0", docs_url="/docs")

_origins = [o for o in os.environ.get("EURIO_API_CORS_ORIGINS", "").split(",") if o]
if _origins:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=_origins,
        # credentials=True nécessaire pour le cookie eurio_session côté panel.
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

# Routes auth OIDC + identité (sans `require_token` legacy — elles ont leur
# propre dep `require_principal` ou sont publiques pour le flow).
app.include_router(auth_routes.router)
app.include_router(users_routes.router)
app.include_router(tokens_routes.router)
app.include_router(review_routes.router)
app.include_router(confusion_routes.router)
app.include_router(audit_routes.router)
# D2 data-layer-unification : domaine `coin_series` (READ) layered, scope
# coins:read — remplace le dernier supabase.from('coin_series') de studio-local.
app.include_router(coin_series_router)
# F9 dashboard KPIs : compteurs read-only agrégés, filtrés par scope (lean).
app.include_router(stats_routes.router)
# Phase 2b data-layer-unification : domaine `sources` (READ) layered, sans
# dépendances ML lourdes — mount inconditionnel sur l'image lean.
app.include_router(sources_router)
# Phase 2c data-layer-unification : domaine `review_queue` (READ) layered.
# Endpoints heavy (manual-crop, dino-suggestions, auto-crop) restent dans le
# legacy `review.review_queue_routes` (skipped sur lean image via cv2).
app.include_router(review_queue_router)
# TC2 (Model B) : écritures review (decide/skip/reject/restore) SQL-pures, cv2-free
# → servies sur l'image lean (scope review:write). Le full app `server.py` garde le
# legacy `review.review_queue_routes` (mêmes paths + crops cv2) → ne PAS monter ici-bas
# dans server.py (routes dupliquées).
app.include_router(review_writes_router)


@app.on_event("startup")
async def _start_canonical_sync() -> None:
    """C8 (Model B) : pousse périodiquement le canonique VPS → MinIO pour que
    pull_replica (qui lit MinIO) reflète l'état frais du writer unique. Best-effort
    (jamais bloquant pour le boot)."""
    try:
        from serving.canonical_sync import start_background_sync
        start_background_sync()
        log.info("canonical_sync: tâche de fond planifiée")
    except Exception as exc:  # noqa: BLE001
        log.warning("canonical_sync: démarrage impossible : %s", exc)


@app.get("/healthz")
def healthz() -> dict:
    """Liveness — ouvert (pas d'auth), pour Traefik/monitoring."""
    return {"ok": True, "role": "serve", "db": str(_DB_PATH)}


# ─── Cœur garanti : ingest run-batch (auth au niveau route) ──────────────────
ingest_routes.bind(_store)
app.include_router(ingest_routes.router)

# ─── Routers interactifs légers, best-effort (skip si dep lourde absente) ────
# (nom, module, a un bind(store) ?). Les heavy (review_queue/coin_assets : cv2/
# crop_edit) sont listés mais échoueront à l'import sur l'image lean → skippés.
_CANDIDATES = [
    ("coins", "serving.coins_routes", True),
    ("sets", "serving.sets_routes", True),
    ("operations", "serving.operations_routes", False),
    ("referential", "serving.referential_routes", False),
    ("peer_arbitration", "review.peer_arbitration_routes", False),
    ("review_queue", "review.review_queue_routes", False),
    ("coin_assets", "serving.coin_assets_routes", True),
]
_mounted: list[str] = []
_skipped: list[str] = []
for _name, _modpath, _has_bind in _CANDIDATES:
    try:
        _mod = importlib.import_module(_modpath)
        if _has_bind and hasattr(_mod, "bind"):
            _mod.bind(_store)
        # Auth-redesign C3.5 : migration require_token (legacy bearer machine
        # via table api_tokens) → require_principal (cookie OIDC + PAT). Le
        # legacy bearer n'est plus accepté sur ces routes ; les workflows
        # Mac/PC doivent utiliser un PAT (eurio_<43 base64url>).
        app.include_router(_mod.router, dependencies=[Depends(require_principal)])
        _mounted.append(_name)
    except (ImportError, ModuleNotFoundError) as exc:
        # Skip uniquement si une dépendance lourde (cv2/torch/dino…) est absente
        # de l'image lean — ces routers lèvent ImportError/ModuleNotFoundError à
        # l'import. Toute autre exception (typo, init bug, AttributeError…) doit
        # remonter en clair pour ne pas masquer un vrai problème de câblage.
        _skipped.append(f"{_name} ({type(exc).__name__}: {exc})")
        log.warning("serve: router '%s' NON monté (dep absente) → %s", _name, exc)

log.info("serve-role prêt | DB=%s | auth=%s", _DB_PATH, api_auth.auth_required())
log.info("routers montés : %s", _mounted)
if _skipped:
    log.warning("routers skippés : %s", _skipped)
