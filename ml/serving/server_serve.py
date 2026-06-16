"""App serve-role du canonique sur le VPS (Modèle B, chunk C4).

FastAPI LÉGER : writer unique de ``eurio.db`` (volume ``EURIO_DB_PATH``). Monte un
**cœur garanti** (``/healthz`` + auth + ``/ingest/run``) puis les routers
interactifs légers en **best-effort** — tout router dont une dépendance lourde
(cv2/torch/dino…) manque sur l'image lean est **skippé** et journalisé (no CV/ML
sur le VPS, cf. DESIGN.md). Le log de démarrage liste ``montés`` / ``skippés``.

NE PAS confondre avec ``serving/server.py`` (app FULL workstation). Ici aucun
router de calcul lourd n'est exposé.
"""
from __future__ import annotations

import importlib
import logging
import os
from pathlib import Path

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from serving import auth as api_auth
from serving import ingest_routes
from store import Store

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("eurio-api")

_DB_PATH = Path(os.environ.get("EURIO_DB_PATH", "/var/lib/eurio/eurio.db"))
_store = Store(_DB_PATH)
api_auth.bind(_store)

app = FastAPI(title="Eurio API (serve)", version="0.1.0", docs_url="/docs")

_origins = [o for o in os.environ.get("EURIO_API_CORS_ORIGINS", "").split(",") if o]
if _origins:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=_origins,
        allow_methods=["*"],
        allow_headers=["*"],
    )


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
        app.include_router(_mod.router, dependencies=[Depends(api_auth.require_token)])
        _mounted.append(_name)
    except Exception as exc:  # noqa: BLE001 — dep lourde ou wiring absent
        _skipped.append(f"{_name} ({type(exc).__name__}: {exc})")
        log.warning("serve: router '%s' NON monté → %s", _name, exc)

log.info("serve-role prêt | DB=%s | auth=%s", _DB_PATH, api_auth.auth_required())
log.info("routers montés : %s", _mounted)
if _skipped:
    log.warning("routers skippés : %s", _skipped)
