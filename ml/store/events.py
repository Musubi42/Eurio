"""Machine à états des crops : journalisation des transitions (image_state_*).

Depuis le chantier local-sync (2026-07), chaque event est aussi estampillé
``(op_id, machine, hlc)`` et enfilé dans ``sync_outbox`` — c'est le substrat de
la réplication multi-machine (docs/work-in-progress/local-sync/). Le VPS, hub
de merge, stampe mais n'enfile pas (``EURIO_SYNC_MODE=hub``).
"""

from __future__ import annotations

import json
import logging
import os
import sqlite3
import uuid

from .hlc import hlc_now, machine_id

logger = logging.getLogger(__name__)


def _sync_is_hub() -> bool:
    """Mode hub (VPS) : point de merge, ne pousse vers personne → pas d'outbox.

    Lu à chaque appel (pas au module-load) pour rester testable et suivre un
    changement d'env sans redémarrage d'interpréteur.
    """
    return os.environ.get("EURIO_SYNC_MODE", "").strip().lower() == "hub"


# ─── Modèle d'état explicite des crops (cohort-pipeline rebuild) ──────────────
# Voir schema.sql §"Machine à états" + docs/cohort-pipeline/REBUILD-ANALYSIS.md.
# emit_state_event journalise UNE transition (image_state_events, append-only) ET
# met à jour l'état courant matérialisé (image_state_current) dans la transaction
# du CALLER (pas de BEGIN/COMMIT ici) → atomicité event ⇔ mutation métier.

_CANONICAL_STATES = frozenset((
    "detected", "auto_matched", "queued", "in_review",
    "skipped", "resolved", "rejected", "orphaned", "superseded",
))

# Transitions légales (from_state → {to_state}). None (∅) = première transition.
# Garde-fou « warn-and-write » : une transition hors table est LOGGUÉE puis écrite
# quand même (on observe les anomalies sans casser la prod — rodage). On durcira
# en raise une fois stabilisé.
_LEGAL_TRANSITIONS: dict[str | None, frozenset[str]] = {
    None: frozenset(("detected", "auto_matched", "queued", "orphaned")),
    "detected": frozenset(("queued", "auto_matched", "orphaned", "superseded", "rejected")),
    "auto_matched": frozenset(("queued", "superseded")),
    "queued": frozenset(("in_review", "resolved", "rejected", "skipped", "superseded")),
    "in_review": frozenset(("resolved", "rejected", "queued", "skipped")),
    "skipped": frozenset(("queued", "resolved", "rejected", "superseded")),
    "resolved": frozenset(("queued", "superseded")),
    "rejected": frozenset(("queued", "superseded")),
    "orphaned": frozenset(("queued", "superseded", "rejected")),
    "superseded": frozenset(),
}


def emit_state_event(
    conn: sqlite3.Connection,
    *,
    asset_id: str,
    to_state: str,
    actor: str,
    reason: str | None = None,
    eurio_id: str | None = None,
    target_eurio_id: str | None = None,
    run_id: str | None = None,
    detail: dict | None = None,
    from_state: str | None = None,
    detail_fields: dict | None = None,
) -> int:
    """Journalise la transition d'un crop + rafraîchit son état courant.

    À appeler DANS la transaction du caller (ne fait ni BEGIN ni COMMIT). Si
    ``from_state`` n'est pas fourni, il est lu depuis ``image_state_current``
    (NULL si le crop n'y est pas encore). ``target_eurio_id``/``eurio_id`` non
    fournis sont hérités de la ligne courante. Retourne l'``id`` de l'event.

    ``detail_fields`` (sync) : affectations complètes ``{"table.colonne": valeur}``
    matérialisables par le replay distant (convention ``detail_json = {"v": 1,
    "fields": {...}}``). Sans lui, l'event est journalisé/synchronisé mais ne
    matérialise rien à distance (transition d'état pure).
    """
    if to_state not in _CANONICAL_STATES:
        raise ValueError(f"emit_state_event: état inconnu {to_state!r}")

    cur_row = conn.execute(
        "SELECT current_state, eurio_id, target_eurio_id "
        "FROM image_state_current WHERE asset_id=?",
        (asset_id,),
    ).fetchone()
    if cur_row is not None:
        prev_state = cur_row["current_state"] if isinstance(cur_row, sqlite3.Row) else cur_row[0]
        if from_state is None:
            from_state = prev_state
        if target_eurio_id is None:
            target_eurio_id = cur_row["target_eurio_id"]
        if eurio_id is None:
            eurio_id = cur_row["eurio_id"]

    legal = _LEGAL_TRANSITIONS.get(from_state, frozenset())
    if to_state not in legal and to_state != from_state:
        logger.warning(
            "emit_state_event: transition inattendue %s → %s (asset=%s actor=%s reason=%s)",
            from_state, to_state, asset_id, actor, reason,
        )

    body: dict = dict(detail or {})
    if detail_fields is not None:
        body["v"] = 1
        body["fields"] = detail_fields

    op_id = uuid.uuid4().hex
    machine = machine_id(conn)
    hlc = hlc_now(conn, machine)

    ev = conn.execute(
        "INSERT INTO image_state_events "
        "(asset_id, from_state, to_state, actor, reason, eurio_id, "
        " target_eurio_id, run_id, detail_json, created_at, op_id, machine, hlc) "
        "VALUES (?,?,?,?,?,?,?,?,?,datetime('now'),?,?,?)",
        (asset_id, from_state, to_state, actor, reason, eurio_id,
         target_eurio_id, run_id,
         json.dumps(body) if body else None,
         op_id, machine, hlc),
    )
    event_id = int(ev.lastrowid)

    if not _sync_is_hub():
        conn.execute(
            "INSERT INTO sync_outbox (op_id, kind, event_id, asset_id) "
            "VALUES (?, 'event', ?, ?)",
            (op_id, event_id, asset_id),
        )

    conn.execute(
        "INSERT INTO image_state_current "
        "(asset_id, current_state, eurio_id, target_eurio_id, "
        " last_event_id, actor, state_since) "
        "VALUES (?,?,?,?,?,?,datetime('now')) "
        "ON CONFLICT(asset_id) DO UPDATE SET "
        "  current_state=excluded.current_state, "
        "  eurio_id=COALESCE(excluded.eurio_id, image_state_current.eurio_id), "
        "  target_eurio_id=COALESCE(excluded.target_eurio_id, image_state_current.target_eurio_id), "
        "  last_event_id=excluded.last_event_id, "
        "  actor=excluded.actor, "
        "  state_since=excluded.state_since",
        (asset_id, to_state, eurio_id, target_eurio_id, event_id, actor),
    )
    return event_id


def record_tombstone(
    conn: sqlite3.Connection,
    *,
    asset_id: str,
    storage_path: str | None = None,
    reason: str | None = None,
) -> str:
    """Journalise la suppression d'un asset AVANT son DELETE (même transaction).

    Le DELETE CASCADE efface les events de l'asset — la suppression voyage donc
    dans ``sync_tombstones`` (jamais cascadée) + une entrée outbox dédiée.
    Sémantique : terminal, delete gagne sur toute édition concurrente (v1).
    Retourne l'``op_id`` du tombstone. Idempotent par asset (re-delete = upsert).
    """
    op_id = uuid.uuid4().hex
    machine = machine_id(conn)
    hlc = hlc_now(conn, machine)
    conn.execute(
        "INSERT INTO sync_tombstones (asset_id, op_id, machine, hlc, storage_path, reason) "
        "VALUES (?,?,?,?,?,?) "
        "ON CONFLICT(asset_id) DO UPDATE SET "
        "  op_id=excluded.op_id, machine=excluded.machine, hlc=excluded.hlc, "
        "  storage_path=COALESCE(excluded.storage_path, sync_tombstones.storage_path), "
        "  reason=COALESCE(excluded.reason, sync_tombstones.reason)",
        (asset_id, op_id, machine, hlc, storage_path, reason),
    )
    if not _sync_is_hub():
        conn.execute(
            "INSERT INTO sync_outbox (op_id, kind, event_id, asset_id) "
            "VALUES (?, 'tombstone', NULL, ?)",
            (op_id, asset_id),
        )
    return op_id
