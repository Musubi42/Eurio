"""Bidirectional eurio_id ↔ numista_id mapping.

Source of truth : ``ml/datasets/eurio_referential.json`` — each entry has an
``eurio_id`` and (optionally) ``cross_refs.numista_id``. ~557/2628 entries
currently have a numista mapping; coins without one cannot be captured (no
disk slot in the legacy ``ml/datasets/<numista_id>/`` layout).

Loaded once at import time, cached in module-level dicts. Call
:func:`reload` to re-read the file on disk (cheap: ~30ms).
"""
from __future__ import annotations

import json
import threading
from pathlib import Path

_REFERENTIAL_PATH = Path(__file__).resolve().parent.parent / "datasets" / "eurio_referential.json"

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
        with _REFERENTIAL_PATH.open() as f:
            data = json.load(f)
        e2n: dict[str, int] = {}
        n2e: dict[int, str] = {}
        themes: dict[str, str | None] = {}
        for entry in data.get("entries", []):
            eid = entry.get("eurio_id")
            if not eid:
                continue
            themes[eid] = entry.get("identity", {}).get("theme")
            nid = entry.get("cross_refs", {}).get("numista_id")
            if nid is not None:
                e2n[eid] = int(nid)
                n2e[int(nid)] = eid
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
