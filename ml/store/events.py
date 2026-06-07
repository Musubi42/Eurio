"""Machine à états des crops : journalisation des transitions (image_state_*)."""

from __future__ import annotations

import json
import logging
import sqlite3

logger = logging.getLogger(__name__)


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
) -> int:
    """Journalise la transition d'un crop + rafraîchit son état courant.

    À appeler DANS la transaction du caller (ne fait ni BEGIN ni COMMIT). Si
    ``from_state`` n'est pas fourni, il est lu depuis ``image_state_current``
    (NULL si le crop n'y est pas encore). ``target_eurio_id``/``eurio_id`` non
    fournis sont hérités de la ligne courante. Retourne l'``id`` de l'event.
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

    ev = conn.execute(
        "INSERT INTO image_state_events "
        "(asset_id, from_state, to_state, actor, reason, eurio_id, "
        " target_eurio_id, run_id, detail_json, created_at) "
        "VALUES (?,?,?,?,?,?,?,?,?,datetime('now'))",
        (asset_id, from_state, to_state, actor, reason, eurio_id,
         target_eurio_id, run_id,
         json.dumps(detail) if detail is not None else None),
    )
    event_id = int(ev.lastrowid)

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
