"""Bidirectional eurio_id ↔ numista_id mapping.

Source of truth : the canonical local ``ml/state/eurio.db`` ``coins`` table
(SQLite-only doctrine). Each coin has an ``eurio_id`` and (optionally) a
``numista_id``; coins without one cannot be captured (no disk slot in the
``ml/datasets/<numista_id>/`` layout).

Loaded lazily at first lookup, cached in module-level dicts. Call
:func:`reload` to re-read the table (cheap).

Le chemin de la base vient d'abord de :func:`bind` (le ``Store`` que le serveur
ou le test a câblé — même point d'injection que ``lab_routes.bind``), et
seulement à défaut de ``EURIO_DB_PATH`` / ``ml/state/eurio.db``. Sans ``bind``,
la route lisait une autre base que celle que le test lui injectait : cinq tests
de ``test_lab_api.py`` ne passaient que parce qu'un ``eurio.db`` traînait hors
dépôt (run CI 34493861491, 2026-09-10).
"""
from __future__ import annotations

import sqlite3
import threading
from pathlib import Path

from store import resolve_db_path

# Repli quand rien n'est câblé : honore EURIO_DB_PATH (Model B : le compute lit
# la réplique, pas un eurio.db local périmé). Défaut legacy = ml/state/eurio.db.
_DEFAULT_DB = Path(__file__).resolve().parent.parent / "state" / "eurio.db"

_lock = threading.Lock()
_bound_db_path: Path | None = None
_eurio_to_numista: dict[str, int] = {}
_numista_to_eurio: dict[int, str] = {}
_eurio_to_theme: dict[str, str | None] = {}
_loaded = False


def bind(db_path: Path) -> None:
    """Câble la base à lire — celle du ``Store`` injecté, jamais un chemin de
    module. Invalide le cache : un nouveau store est une nouvelle vérité."""
    global _bound_db_path, _loaded
    with _lock:
        _bound_db_path = Path(db_path)
        _loaded = False


def _db_path() -> Path:
    return _bound_db_path if _bound_db_path is not None else resolve_db_path(_DEFAULT_DB)


def _load() -> None:
    global _loaded
    with _lock:
        if _loaded:
            return
        e2n: dict[str, int] = {}
        n2e: dict[int, str] = {}
        themes: dict[str, str | None] = {}
        conn = sqlite3.connect(f"file:{_db_path()}?mode=ro", uri=True)
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
