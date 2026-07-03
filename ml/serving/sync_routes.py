"""Endpoints de sync event-log (local-sync) — côté canonique ET workstation.

Le VPS (hub de merge) reçoit les events des machines (``POST /db/events/push``,
idempotent par op_id, matérialise via ``apply_remote``) et les redistribue
(``GET /db/events/pull`` — exclut la machine demandeuse, donc les writes review
du VPS lui-même, stampés ``machine='vps'``, redescendent naturellement).

SQL pur (Store + sync_replay) → monté inconditionnellement sur ``server_serve``
(lean) et ``server`` (full, règle de parité FULL↔LEAN). Scope ``ingest:write``
(déjà attribué owner/admin — pas de scope neuf).

Doctrine : docs/work-in-progress/local-sync/.
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from serving.auth_principal import require_scope
from store import apply_remote, event_to_wire, tombstone_to_wire
from store.hlc import hlc_now, machine_id

logger = logging.getLogger("eurio-api.sync")

router = APIRouter(prefix="/db/events", tags=["sync"])

_store = None

_PULL_LIMIT_MAX = 2000


def bind(store) -> None:
    global _store
    _store = store


def _conn():
    if _store is None:
        raise HTTPException(status_code=500, detail="sync non câblé (bind manquant)")
    return _store._connection()  # noqa: SLF001


class PushPayload(BaseModel):
    machine: str = Field(min_length=1)
    events: list[dict] = Field(default_factory=list)
    tombstones: list[dict] = Field(default_factory=list)


@router.post("/push", dependencies=[Depends(require_scope("ingest:write"))])
def push_events(payload: PushPayload) -> dict:
    """Applique un lot d'events/tombstones au canonique (idempotent, 1 tx).

    Le client marque ``pushed`` uniquement les op_id de ``accepted`` +
    ``duplicates`` ; les ``orphaned`` (asset inconnu ici — run pas encore
    ingéré) restent pending côté client et reviendront au prochain cycle.
    """
    conn = _conn()
    for ev in payload.events:
        missing = [k for k in ("op_id", "asset_id", "to_state", "actor",
                               "created_at", "machine", "hlc") if not ev.get(k)]
        if missing:
            raise HTTPException(
                status_code=422,
                detail=f"event incomplet (op_id={ev.get('op_id')}) : {missing}",
            )
    for ts in payload.tombstones:
        missing = [k for k in ("op_id", "asset_id", "machine", "hlc")
                   if not ts.get(k)]
        if missing:
            raise HTTPException(
                status_code=422,
                detail=f"tombstone incomplet (op_id={ts.get('op_id')}) : {missing}",
            )

    conn.execute("BEGIN IMMEDIATE")
    try:
        stats = apply_remote(
            conn, events=payload.events, tombstones=payload.tombstones,
        )
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise

    known = {ev["op_id"] for ev in payload.events} | {
        ts["op_id"] for ts in payload.tombstones
    }
    orphaned = {
        r[0] for r in conn.execute(
            "SELECT op_id FROM sync_orphan_events"
        ).fetchall()
    } & known
    accepted = sorted(known - orphaned)
    server_machine = machine_id(conn)
    logger.info(
        "[sync] push from=%s events=%d tombstones=%d inserted=%d dup=%d orphaned=%d",
        payload.machine, len(payload.events), len(payload.tombstones),
        stats.inserted, stats.duplicates, len(orphaned),
    )
    return {
        "accepted": accepted,
        "orphaned": sorted(orphaned),
        "server_hlc": hlc_now(conn, server_machine),
        "stats": {
            "inserted": stats.inserted,
            "duplicates": stats.duplicates,
            "tombstones_applied": stats.tombstones_applied,
            "assets_materialized": stats.assets_materialized,
            "errors": stats.errors,
        },
    }


@router.get("/pull", dependencies=[Depends(require_scope("ingest:write"))])
def pull_events(
    machine: str = Query(min_length=1),
    since_hlc: str = Query(default=""),
    limit: int = Query(default=500, ge=1, le=_PULL_LIMIT_MAX),
) -> dict:
    """Events/tombstones stampés APRÈS ``since_hlc``, hors ceux de la machine
    demandeuse. Pagination : curseur = ``max_hlc`` retourné, ``has_more``."""
    conn = _conn()
    if machine == machine_id(conn):
        raise HTTPException(
            status_code=422,
            detail="machine == machine du serveur — un nœud ne se pull pas lui-même",
        )
    ev_rows = conn.execute(
        "SELECT * FROM image_state_events "
        "WHERE hlc IS NOT NULL AND hlc > ? AND machine != ? "
        "ORDER BY hlc LIMIT ?",
        (since_hlc, machine, limit + 1),
    ).fetchall()
    has_more = len(ev_rows) > limit
    ev_rows = ev_rows[:limit]
    # Curseur = hlc du DERNIER event de la page quand il en reste (pas le max
    # global — sinon un event entre deux pages serait sauté). Les tombstones
    # sont bornés à la même fenêtre pour rester alignés sur le curseur ; un
    # doublon inter-pages est absorbé par l'idempotence op_id.
    if has_more and ev_rows:
        window_end = ev_rows[-1]["hlc"]
        ts_rows = conn.execute(
            "SELECT * FROM sync_tombstones "
            "WHERE hlc > ? AND hlc <= ? AND machine != ? ORDER BY hlc",
            (since_hlc, window_end, machine),
        ).fetchall()
        max_hlc = window_end
    else:
        ts_rows = conn.execute(
            "SELECT * FROM sync_tombstones "
            "WHERE hlc > ? AND machine != ? ORDER BY hlc",
            (since_hlc, machine),
        ).fetchall()
        hlcs = [r["hlc"] for r in ev_rows] + [r["hlc"] for r in ts_rows]
        max_hlc = max(hlcs) if hlcs else since_hlc
    return {
        "events": [event_to_wire(r) for r in ev_rows],
        "tombstones": [tombstone_to_wire(r) for r in ts_rows],
        "max_hlc": max_hlc,
        "has_more": has_more,
    }
