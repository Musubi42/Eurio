"""Rejet canonique du gate vision standard — write-half SQL-pure (Direction A, C4a).

Le gate vision (``scripts/gate_standard_vision.py``) classe les crops eBay avec
Claude (ccproxy, GPU-less côté VPS) et pousse les rejets ``wrong_coin``/``junk``
au canonique via ``POST /ingest/gate/reject`` — seul le VERDICT voyage, pas
l'image. Miroir DB exact de l'ancien ``_reject`` local.

Contrat transactionnel identique à ``store.crops`` : prend ``conn``, ne fait NI
``BEGIN`` NI ``COMMIT`` (le caller possède la transaction). Réversible via
``/review/rejected`` + restore.

Idempotent/sûr : la review_queue est vérifiée EN PREMIER (``AND status='open'``) ;
si elle n'est plus ouverte (rowcount != 1), on retourne ``{"written": False}``
SANS toucher ``image_assets`` — le caller peut committer une tx vide sans risque.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone

from store.events import emit_state_event

ENGINE_VERSION = "vision_standard_gate_v1"


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def apply_gate_reject(
    conn, *, review_id: str, asset_id: str, label: str,
    confidence: float | None, engine_version: str = ENGINE_VERSION,
) -> dict:
    """Rejet canonique réversible (3 écritures). Retourne ``{"written": bool}``.

    Ordre : review_queue d'abord (garde ``status='open'``) → si déjà close,
    aucune autre écriture. Sinon : ``image_assets`` rejected + state event.
    Ni BEGIN ni COMMIT (le caller possède la transaction).
    """
    now = _now_iso()
    reason = f"vision_standard_gate:{label}"
    cur = conn.execute(
        "UPDATE review_queue SET status='done', decision_notes=?, decided_at=?, "
        "decided_by='vision_gate', decision_engine_version=?, decision_metadata_json=? "
        "WHERE id=? AND status='open'",
        (reason, now, engine_version,
         json.dumps({"reason": reason, "confidence": confidence}), review_id),
    )
    if cur.rowcount != 1:
        return {"written": False}
    conn.execute(
        "UPDATE image_assets SET resolution_status='rejected', training_eligible=0, "
        "quality_reason=?, resolved_at=? WHERE id=?",
        ("vision_standard_gate", now, asset_id),
    )
    # actor enum-contraint (image_state_events) → 'ccproxy' (vision Claude) ;
    # la provenance fine du gate vit dans `reason` + review_queue.decided_by.
    emit_state_event(
        conn, asset_id=asset_id, to_state="rejected", actor="ccproxy", reason=reason,
    )
    return {"written": True}
