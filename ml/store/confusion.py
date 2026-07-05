"""Écriture SQL-pure de la cartographie de confusion (``coin_confusion_map``).

Rapatriement F02/C2 : le compute DINOv2 tourne côté Mac/PC (torch, réplique ro)
et pousse ses lignes au canonique via ``POST /ingest/confusion-map`` (Direction A,
writer unique VPS) — jamais d'écriture SQLite distante directe. En dev Model A
(sync désactivée) le compute écrit la DB locale directement via cette même
fonction. La lecture reste servie par ``serving/confusion_routes.py``.

``apply_ingest_confusion_map`` est appelée dans une transaction ouverte par le
caller (l'endpoint d'ingest ou le compute local) — elle ne gère ni BEGIN ni
COMMIT, comme les autres ``apply_ingest_*`` de ``store/``.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from typing import Any, Iterable

_VALID_ZONES = ("green", "orange", "red")


def _coerce_top_k(value: Any) -> str:
    """Normalise ``top_k_neighbors`` en TEXT JSON (le schéma le stocke ainsi)."""
    if value is None:
        return "[]"
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False)


def apply_ingest_confusion_map(
    conn: sqlite3.Connection,
    encoder_version: str,
    rows: Iterable[dict[str, Any]],
) -> dict[str, int]:
    """UPSERT des lignes de cartographie pour ``encoder_version`` (clé naturelle
    ``(eurio_id, encoder_version)``). Merge idempotent : un re-run d'un sous-set
    (``--eurio-ids``) ne touche QUE les pièces recalculées, jamais le reste.

    Chaque ``row`` : ``{eurio_id, nearest_eurio_id, nearest_similarity,
    top_k_neighbors, zone}``. ``computed_at`` est posé ici (UTC ISO) si absent.
    Une zone hors ``green|orange|red`` ou un ``eurio_id`` manquant lève
    ``ValueError`` — pas d'écriture partielle silencieuse (fil rouge F0x).

    Retourne ``{"upserted": n}``.
    """
    now = datetime.now(timezone.utc).isoformat()
    n = 0
    for r in rows:
        eurio_id = r.get("eurio_id")
        if not eurio_id:
            raise ValueError("row sans eurio_id")
        zone = r.get("zone")
        if zone not in _VALID_ZONES:
            raise ValueError(f"zone invalide pour {eurio_id!r}: {zone!r}")
        sim = r.get("nearest_similarity")
        if sim is None:
            raise ValueError(f"nearest_similarity manquant pour {eurio_id!r}")
        conn.execute(
            """
            INSERT INTO coin_confusion_map
              (eurio_id, encoder_version, nearest_eurio_id, nearest_similarity,
               top_k_neighbors, zone, computed_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(eurio_id, encoder_version) DO UPDATE SET
              nearest_eurio_id   = excluded.nearest_eurio_id,
              nearest_similarity = excluded.nearest_similarity,
              top_k_neighbors    = excluded.top_k_neighbors,
              zone               = excluded.zone,
              computed_at        = excluded.computed_at
            """,
            (
                eurio_id,
                encoder_version,
                r.get("nearest_eurio_id"),
                float(sim),
                _coerce_top_k(r.get("top_k_neighbors")),
                zone,
                r.get("computed_at") or now,
            ),
        )
        n += 1
    return {"upserted": n}
