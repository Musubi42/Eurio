"""Accès SQL pur du domaine `coin_series` — aucune logique HTTP ici.

Lève des exceptions Python typées ; le mapping HTTP est fait dans `router.py`.
"""
from __future__ import annotations

import json
import sqlite3

from .models import CoinSeries


class SeriesNotFound(Exception):
    """Aucune série pour l'`id` demandé."""


_COLUMNS = (
    "id, country, designation, designation_i18n_json, description, "
    "minting_started_at, minting_ended_at, minting_end_reason, "
    "supersedes_series_id, superseded_by_series_id"
)


def _row_to_model(row: sqlite3.Row) -> CoinSeries:
    i18n_raw = row["designation_i18n_json"]
    return CoinSeries(
        id=row["id"],
        country=row["country"],
        designation=row["designation"],
        designation_i18n=json.loads(i18n_raw) if i18n_raw else None,
        description=row["description"],
        minting_started_at=row["minting_started_at"],
        minting_ended_at=row["minting_ended_at"],
        minting_end_reason=row["minting_end_reason"],
        supersedes_series_id=row["supersedes_series_id"],
        superseded_by_series_id=row["superseded_by_series_id"],
    )


def list_series(conn: sqlite3.Connection) -> list[CoinSeries]:
    """Toutes les séries, triées par (country, minting_started_at).

    Stable : la table est petite (~32 lignes) et figée — le front la cache.
    """
    rows = conn.execute(
        f"SELECT {_COLUMNS} FROM coin_series "
        "ORDER BY country, minting_started_at"
    ).fetchall()
    return [_row_to_model(r) for r in rows]


def get_series(conn: sqlite3.Connection, series_id: str) -> CoinSeries:
    row = conn.execute(
        f"SELECT {_COLUMNS} FROM coin_series WHERE id = ?", (series_id,)
    ).fetchone()
    if row is None:
        raise SeriesNotFound(series_id)
    return _row_to_model(row)
