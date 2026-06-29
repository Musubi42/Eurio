"""Route d'ingestion des run-batches (Modèle B, chunk C3).

Le serveur canonique (writer unique) reçoit les résultats du calcul lourd par run
et les applique via ``client.runbatch.ingest_run`` (1 tx, idempotent). Protégé par
le scope ``ingest:run`` (PAT owner/admin via ``serving.auth_principal.require_scope``).
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from client.runbatch import ingest_run
from serving.auth_principal import require_scope

router = APIRouter(prefix="/ingest", tags=["ingest"])

_store = None


def bind(store) -> None:
    global _store
    _store = store


class RunBatch(BaseModel):
    run_id: str
    tables: dict[str, list[dict]]


@router.post("/run", dependencies=[Depends(require_scope("ingest:run"))])
def ingest_run_route(batch: RunBatch) -> dict:
    """Applique un run-batch au canonique (UPSERT clé naturelle, idempotent)."""
    if _store is None:
        raise HTTPException(status_code=500, detail="ingest non câblé (bind manquant)")
    return ingest_run(_store._connection(), batch.model_dump())  # noqa: SLF001


@router.get("/run/{run_id}", dependencies=[Depends(require_scope("ingest:run"))])
def run_status(run_id: str) -> dict:
    """État d'un run déjà ingéré (depuis ``ingested_runs``)."""
    if _store is None:
        raise HTTPException(status_code=500, detail="ingest non câblé (bind manquant)")
    row = _store._connection().execute(  # noqa: SLF001
        "SELECT run_id, batch_sha, applied_at, counts_json FROM ingested_runs "
        "WHERE run_id=?",
        (run_id,),
    ).fetchone()
    if row is None:
        return {"run_id": run_id, "applied": False}
    return {
        "run_id": row["run_id"],
        "applied": True,
        "batch_sha": row["batch_sha"],
        "applied_at": row["applied_at"],
        "counts_json": row["counts_json"],
    }
