"""Références Dino multi-exemplaires (improvement-loop B) — accès table.

``dino_class_references`` trace, par classe de la banque de suggestions
``2eur_all``, les crops qui servent d'exemplaires : le canonique + jusqu'à K
vrais crops choisis pour la diversité (FPS), plus les overrides humains
(``manual_pin`` / ``manual_exclude``). Voir state/schema.sql §Références Dino.

Doctrine de réécriture :
- ``replace_auto_references`` : le builder d'ancres remplace en bloc les rows
  ``canonical`` + ``fps`` d'un kind (les auto), en PRÉSERVANT les ``manual_*``.
- ``get_reference_overrides`` : lu AVANT le rebuild pour honorer pin/exclude.
- ``set_reference_override`` / ``clear_reference_override`` : l'UI coin-detail.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass

DEFAULT_KIND = "2eur_all"
_AUTO_METHODS = ("canonical", "fps")
_MANUAL_METHODS = ("manual_pin", "manual_exclude")


@dataclass
class DinoRefRow:
    class_id: str
    eurio_id: str
    asset_id: str | None  # None = canonique
    method: str
    rank: int | None = None
    selected_sim: float | None = None


def replace_auto_references(
    conn: sqlite3.Connection, anchors_kind: str, rows: list[DinoRefRow],
) -> None:
    """Réécrit les rows AUTO (``canonical`` + ``fps``) d'un kind, en gardant
    intactes les rows ``manual_*``. Appelé par le builder après un rebuild."""
    conn.execute(
        "DELETE FROM dino_class_references "
        "WHERE anchors_kind=? AND method IN ('canonical','fps')",
        (anchors_kind,),
    )
    if rows:
        conn.executemany(
            "INSERT OR REPLACE INTO dino_class_references "
            "(anchors_kind, class_id, eurio_id, asset_id, method, rank, selected_sim) "
            "VALUES (?,?,?,?,?,?,?)",
            [
                (anchors_kind, r.class_id, r.eurio_id, r.asset_id, r.method,
                 r.rank, r.selected_sim)
                for r in rows
            ],
        )


def get_reference_overrides(
    conn: sqlite3.Connection, anchors_kind: str = DEFAULT_KIND,
) -> dict[str, list[sqlite3.Row]]:
    """Overrides humains par classe (``manual_pin`` / ``manual_exclude``) — lus
    par le builder pour forcer/bannir des exemplaires."""
    out: dict[str, list[sqlite3.Row]] = {}
    for r in conn.execute(
        "SELECT * FROM dino_class_references "
        "WHERE anchors_kind=? AND method IN ('manual_pin','manual_exclude')",
        (anchors_kind,),
    ).fetchall():
        out.setdefault(r["class_id"], []).append(r)
    return out


def get_class_references(
    conn: sqlite3.Connection, class_id: str, anchors_kind: str = DEFAULT_KIND,
) -> list[sqlite3.Row]:
    """Toutes les rows d'une classe (canonique + fps + manuels), pour l'UI."""
    return conn.execute(
        "SELECT * FROM dino_class_references "
        "WHERE anchors_kind=? AND class_id=? "
        "ORDER BY CASE method WHEN 'canonical' THEN 0 WHEN 'manual_pin' THEN 1 "
        "  WHEN 'fps' THEN 2 ELSE 3 END, rank",
        (anchors_kind, class_id),
    ).fetchall()


def get_references_for_assets(
    conn: sqlite3.Connection, asset_ids: list[str],
    anchors_kind: str = DEFAULT_KIND,
) -> dict[str, sqlite3.Row]:
    """asset_id → row de référence (pour badger les crops en coin-detail)."""
    if not asset_ids:
        return {}
    ph = ",".join("?" for _ in asset_ids)
    return {
        r["asset_id"]: r
        for r in conn.execute(
            f"SELECT * FROM dino_class_references "
            f"WHERE anchors_kind=? AND asset_id IN ({ph})",
            (anchors_kind, *asset_ids),
        ).fetchall()
    }


def set_reference_override(
    conn: sqlite3.Connection, *, class_id: str, eurio_id: str, asset_id: str,
    method: str, anchors_kind: str = DEFAULT_KIND,
) -> None:
    """Épingle (``manual_pin``) ou bannit (``manual_exclude``) un crop comme
    exemplaire. Prend effet au prochain build d'ancres ; la row survit aux
    rebuilds auto. ``asset_id`` requis (on n'override jamais le canonique)."""
    if method not in _MANUAL_METHODS:
        raise ValueError(f"method invalide pour un override : {method}")
    conn.execute(
        "INSERT OR REPLACE INTO dino_class_references "
        "(anchors_kind, class_id, eurio_id, asset_id, method, rank, selected_sim) "
        "VALUES (?,?,?,?,?,NULL,NULL)",
        (anchors_kind, class_id, eurio_id, asset_id, method),
    )


def clear_reference_override(
    conn: sqlite3.Connection, *, asset_id: str, anchors_kind: str = DEFAULT_KIND,
) -> int:
    """Retire un override manuel sur un asset (retour à la sélection auto au
    prochain rebuild). Retourne le nb de rows supprimées."""
    cur = conn.execute(
        "DELETE FROM dino_class_references "
        "WHERE anchors_kind=? AND asset_id=? AND method IN ('manual_pin','manual_exclude')",
        (anchors_kind, asset_id),
    )
    return cur.rowcount
