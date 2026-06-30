"""Bidirectional eurio_id ↔ numista_id mapping.

Source of truth : the canonical local ``ml/state/eurio.db`` ``coins`` table
(SQLite-only doctrine). Each coin has an ``eurio_id`` and (optionally) a
``numista_id``; coins without one cannot be captured (no disk slot in the
``ml/datasets/<numista_id>/`` layout).

Loaded once at import time, cached in module-level dicts. Call
:func:`reload` to re-read the table (cheap).
"""
from __future__ import annotations

import sqlite3
import threading
from pathlib import Path

from store import resolve_db_path

# Honore EURIO_DB_PATH (Model B : le compute lit la réplique, pas un eurio.db
# local périmé). Défaut legacy = ml/state/eurio.db.
_DB_PATH = resolve_db_path(Path(__file__).resolve().parent.parent / "state" / "eurio.db")

_lock = threading.Lock()
_eurio_to_numista: dict[str, int] = {}
_numista_to_eurio: dict[int, str] = {}
_eurio_to_theme: dict[str, str | None] = {}
_loaded = False


def _load() -> None:
    global _loaded
    with _lock:
        if _loaded:
            return
        e2n: dict[str, int] = {}
        n2e: dict[int, str] = {}
        themes: dict[str, str | None] = {}
        conn = sqlite3.connect(f"file:{_DB_PATH}?mode=ro", uri=True)
        try:
            for eid, nid, theme in conn.execute(
                "SELECT eurio_id, numista_id, theme FROM coins"
            ):
                if not eid:
                    continue
                themes[eid] = theme
                if nid is not None:
                    e2n[eid] = int(nid)
                    n2e[int(nid)] = eid
        finally:
            conn.close()
        _eurio_to_numista.clear()
        _eurio_to_numista.update(e2n)
        _numista_to_eurio.clear()
        _numista_to_eurio.update(n2e)
        _eurio_to_theme.clear()
        _eurio_to_theme.update(themes)
        _loaded = True


def reload() -> None:
    """Force re-read of the referential file."""
    global _loaded
    with _lock:
        _loaded = False
    _load()


def numista_id_for(eurio_id: str) -> int | None:
    _load()
    return _eurio_to_numista.get(eurio_id)


def eurio_id_for(numista_id: int) -> str | None:
    _load()
    return _numista_to_eurio.get(int(numista_id))


def theme_for(eurio_id: str) -> str | None:
    _load()
    return _eurio_to_theme.get(eurio_id)


def display_name_for(eurio_id: str) -> str:
    """Best-effort human label: theme if known, else the eurio_id slug."""
    return theme_for(eurio_id) or eurio_id
