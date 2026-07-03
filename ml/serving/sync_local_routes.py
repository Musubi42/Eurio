"""Routes locales du badge de sync (local-sync) — montées sur server.py SEULEMENT.

Le front (SyncStatusBadge, sidebar studio-local) polle ``GET /sync/status`` et
déclenche ``POST /sync/trigger`` (bouton « Synchroniser », typiquement en fin
de session avant de changer de machine). Pas d'auth : même surface que le
reste de l'API ML locale (:8042, poste de travail).
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException

from .sync_worker import get_worker

router = APIRouter(prefix="/sync", tags=["sync"])


@router.get("/status")
def sync_status() -> dict:
    worker = get_worker()
    if worker is None:
        # Startup pas encore passé (ou serveur lancé sans worker) : le front
        # affiche l'état tel quel plutôt qu'un faux vert.
        return {"state": "disabled", "reason": "worker non démarré"}
    return worker.status()


@router.post("/trigger", status_code=202)
def sync_trigger() -> dict:
    worker = get_worker()
    if worker is None or not worker.is_alive():
        raise HTTPException(
            status_code=503,
            detail="Worker de sync inactif (EURIO_API_URL manquant ?)",
        )
    worker.trigger()
    return {"status": "triggered"}
