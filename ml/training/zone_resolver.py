"""Resolve `class_id → confusion zone` for the on-the-fly augmentation
pipeline.

Each training class (eurio_id or design_group_id) maps to one of the three
zones — green / orange / red — via ``coin_confusion_map.zone``. A class with
multiple member coins inherits the *worst* zone among its members (red >
orange > green): if any member is hard to disambiguate, the whole class
needs the aggressive recipe.

Classes without a confusion-map entry default to ``orange`` — a conservative
middle ground that exercises perspective + relighting + light overlays.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Iterable

from store import resolve_db_path
from training.eval.class_resolver import Resolver

ZONE_RANK: dict[str, int] = {"green": 0, "orange": 1, "red": 2}
DEFAULT_ZONE = "orange"
VALID_ZONES = ("green", "orange", "red")

# Chemin par défaut de la DB (honore ``EURIO_DB_PATH`` / réplique Direction A ;
# le training tourne là où le compute a lieu — Mac/PC lisent la réplique ro).
_DEFAULT_DB_PATH = Path(__file__).resolve().parent.parent / "state" / "eurio.db"


def _worse(a: str, b: str) -> str:
    return a if ZONE_RANK.get(a, -1) >= ZONE_RANK.get(b, -1) else b


def fetch_eurio_zones() -> dict[str, str]:
    """Read all rows from ``eurio.db.coin_confusion_map`` → ``{eurio_id: zone}``.

    Rapatrié de Supabase (F02/C3) : la cartographie de confusion vit désormais
    dans ``coin_confusion_map`` (eurio.db, réplique ro sur Mac/PC). Lecture seule.

    Returns an empty dict if the table is empty or absent (dev Model A sans la
    migration ``0002_orphan_supabase_tables`` appliquée) — callers fall back to
    ``DEFAULT_ZONE`` for unknown ids. Toute autre erreur SQLite est propagée
    (échec bruyant : pas de fallback silencieux sur une DB corrompue/verrouillée).
    """
    db_path = resolve_db_path(_DEFAULT_DB_PATH)
    if not Path(db_path).exists():
        print(
            f"[zone_resolver] eurio.db introuvable ({db_path}) — "
            "defaulting all classes to orange"
        )
        return {}
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute("SELECT eurio_id, zone FROM coin_confusion_map").fetchall()
    except sqlite3.OperationalError as exc:
        # Table absente = état légitime (Model A dev / catalogue non cartographié).
        # On ne masque PAS les autres OperationalError (lock, corruption) : seule
        # "no such table" retombe sur le défaut orange.
        if "no such table" in str(exc):
            print(
                "[zone_resolver] coin_confusion_map absente — "
                "defaulting all classes to orange"
            )
            return {}
        raise
    finally:
        conn.close()
    out: dict[str, str] = {}
    for r in rows:
        zone = r["zone"]
        eid = r["eurio_id"]
        if zone in VALID_ZONES and eid:
            out[eid] = zone
    return out


def resolve_class_zones(
    class_ids: Iterable[str],
    resolver: Resolver,
    eurio_zones: dict[str, str] | None = None,
) -> dict[str, str]:
    """Map each class_id to its zone (worst zone among its members).

    `eurio_zones` is optional — if omitted, fetched from Supabase. Pass it in
    when you want to call this multiple times without re-querying.
    """
    if eurio_zones is None:
        eurio_zones = fetch_eurio_zones()

    out: dict[str, str] = {}
    for class_id in class_ids:
        descriptor = resolver.for_class(class_id)
        if descriptor is None:
            out[class_id] = DEFAULT_ZONE
            continue
        members = [eurio_zones.get(eid) for eid in descriptor.eurio_ids]
        members = [z for z in members if z in VALID_ZONES]
        if not members:
            out[class_id] = DEFAULT_ZONE
            continue
        worst = members[0]
        for z in members[1:]:
            worst = _worse(worst, z)
        out[class_id] = worst
    return out
