"""Resolve coin classes for ArcFace training.

A "class" is the label ArcFace learns. Under the design_groups scheme
(docs/design/_shared/design-groups.md §6.1), the label is:

    COALESCE(design_group_id, eurio_id)

So a coin with a design_group_id (shared-design grouping) contributes to a
design_group-level class; a coin without one is its own eurio_id-level class.

This module builds the mapping once from the canonical local eurio.db and
exposes lookups used by prepare_dataset, compute_embeddings, seed_supabase,
and the training runner (SQLite-only doctrine — no Supabase on this path).
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class CoinRef:
    eurio_id: str
    numista_id: int | None
    design_group_id: str | None

    @property
    def class_id(self) -> str:
        return self.design_group_id or self.eurio_id

    @property
    def class_kind(self) -> str:
        return "design_group_id" if self.design_group_id else "eurio_id"


@dataclass(frozen=True)
class ClassDescriptor:
    class_id: str
    class_kind: str  # 'eurio_id' | 'design_group_id'
    numista_ids: tuple[int, ...]
    eurio_ids: tuple[str, ...]

    def to_dict(self) -> dict:
        return {
            "class_id": self.class_id,
            "class_kind": self.class_kind,
            "numista_ids": list(self.numista_ids),
            "eurio_ids": list(self.eurio_ids),
        }

    @classmethod
    def from_dict(cls, d: dict) -> "ClassDescriptor":
        return cls(
            class_id=d["class_id"],
            class_kind=d["class_kind"],
            numista_ids=tuple(d.get("numista_ids", [])),
            eurio_ids=tuple(d.get("eurio_ids", [])),
        )


class Resolver:
    """Caches the coins → class mapping. Construct once per script run."""

    def __init__(self, coins: list[CoinRef]) -> None:
        self._coins = coins
        self._by_class: dict[str, ClassDescriptor] = {}
        self._by_numista: dict[int, ClassDescriptor] = {}
        self._by_eurio: dict[str, ClassDescriptor] = {}
        self._build_index()

    def _build_index(self) -> None:
        grouped: dict[str, list[CoinRef]] = {}
        for coin in self._coins:
            grouped.setdefault(coin.class_id, []).append(coin)

        for class_id, members in grouped.items():
            descriptor = ClassDescriptor(
                class_id=class_id,
                class_kind=members[0].class_kind,
                numista_ids=tuple(
                    sorted({m.numista_id for m in members if m.numista_id is not None})
                ),
                eurio_ids=tuple(sorted({m.eurio_id for m in members})),
            )
            self._by_class[class_id] = descriptor
            for m in members:
                self._by_eurio[m.eurio_id] = descriptor
                if m.numista_id is not None:
                    self._by_numista[m.numista_id] = descriptor

    @property
    def classes(self) -> list[ClassDescriptor]:
        return list(self._by_class.values())

    def for_numista(self, numista_id: int) -> ClassDescriptor | None:
        return self._by_numista.get(numista_id)

    def for_eurio(self, eurio_id: str) -> ClassDescriptor | None:
        return self._by_eurio.get(eurio_id)

    def for_class(self, class_id: str) -> ClassDescriptor | None:
        return self._by_class.get(class_id)

    def numista_for_class(self, class_id: str) -> list[int]:
        d = self._by_class.get(class_id)
        return list(d.numista_ids) if d else []

    def eurio_for_class(self, class_id: str) -> list[str]:
        d = self._by_class.get(class_id)
        return list(d.eurio_ids) if d else []


def load_env(root: Path | None = None) -> dict[str, str]:
    base = root or Path(__file__).resolve().parent.parent.parent
    env: dict[str, str] = {}
    env_path = base / ".env"
    if env_path.exists():
        for raw in env_path.read_text().splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, _, v = line.partition("=")
            env[k.strip()] = v.strip()
    for key in ("SUPABASE_URL", "SUPABASE_ANON_KEY", "SUPABASE_SERVICE_ROLE_KEY"):
        if key in os.environ:
            env[key] = os.environ[key]
    return env


def _default_db_path() -> Path:
    """Canonical local SQLite — ml/state/eurio.db (cf. SQLite-only doctrine).

    Ce module est ``ml/training/eval/class_resolver.py`` → ``parents[2]`` == ``ml/``.
    (Un ``.parent.parent`` pointait à tort vers ``ml/training/state/`` inexistant,
    faisant échouer tout ``build_resolver()`` sans ``db_path`` explicite.)
    """
    return Path(__file__).resolve().parents[2] / "state" / "eurio.db"


def coin_refs_from_sqlite(db_path: Path | None = None) -> list[CoinRef]:
    """Build CoinRefs from the canonical local eurio.db.

    Reads every coin carrying a numista_id from the ``coins`` table. This is
    the SQLite-only source of truth for the admin + training pipeline (the
    legacy Supabase fetch was removed). eurio.db stores ``numista_id`` as a
    direct column (not nested in ``cross_refs`` like the old Supabase projection).
    """
    import sqlite3

    path = Path(db_path) if db_path else _default_db_path()
    if not path.exists():
        raise RuntimeError(f"eurio.db introuvable: {path}")
    coins: list[CoinRef] = []
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        conn.row_factory = sqlite3.Row
        for row in conn.execute(
            "SELECT eurio_id, numista_id, design_group_id FROM coins "
            "WHERE numista_id IS NOT NULL"
        ):
            coins.append(
                CoinRef(
                    eurio_id=row["eurio_id"],
                    numista_id=int(row["numista_id"]),
                    design_group_id=row["design_group_id"],
                )
            )
    finally:
        conn.close()
    return coins


def build_resolver(
    *,
    force_eurio_id: bool = False,
    db_path: Path | None = None,
) -> Resolver:
    """Build the coins → class Resolver from the canonical eurio.db.

    SQLite-only doctrine: eurio.db is the source of truth — Supabase is no
    longer consulted for training/eval. ``force_eurio_id`` drops the
    design_group COALESCE so each coin is its own class (lab iterations).
    """
    coins = coin_refs_from_sqlite(db_path)
    if not coins:
        raise RuntimeError("No coins with numista_id found in eurio.db")
    if force_eurio_id:
        coins = [
            CoinRef(eurio_id=c.eurio_id, numista_id=c.numista_id, design_group_id=None)
            for c in coins
        ]
    return Resolver(coins)


def coin_refs_from_cohort_csv(csv_path: Path) -> list[CoinRef]:
    """Build a CoinRef list from a cohort CSV — offline, no Supabase.

    A cohort CSV is the frozen source of truth for a capture cohort (the
    eurio_id column is the on-device capture label, so train/val/eval share
    one namespace). Format, one coin per line::

        eurio_id;numista_id;display_name

    ``#``-comment lines and the ``eurio_id;…`` header are skipped.
    ``design_group_id`` is always None — cohort benches run class_kind=eurio_id.
    """
    coins: list[CoinRef] = []
    for raw in Path(csv_path).read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or line.startswith("eurio_id"):
            continue
        parts = line.split(";")
        if len(parts) < 2:
            continue
        eurio_id = parts[0].strip()
        nid_raw = parts[1].strip()
        if not eurio_id:
            continue
        coins.append(CoinRef(
            eurio_id=eurio_id,
            numista_id=int(nid_raw) if nid_raw else None,
            design_group_id=None,
        ))
    return coins


def build_resolver_from_cohort_csv(
    csv_path: Path,
    *,
    force_eurio_id: bool = True,
) -> Resolver:
    """Offline Resolver from a cohort CSV (no Supabase).

    ``force_eurio_id`` is accepted for API symmetry with :func:`build_resolver`;
    the CSV carries no design_group anyway, so each coin is its own class.
    """
    coins = coin_refs_from_cohort_csv(csv_path)
    if not coins:
        raise RuntimeError(f"No coin rows parsed from cohort CSV {csv_path}")
    return Resolver(coins)


# ─── Manifest ──────────────────────────────────────────────────────────────
#
# The prepared dataset directory carries a `class_manifest.json` describing
# each class in the split. Downstream scripts (compute_embeddings, seed) read
# this manifest to know the class_kind and eurio_id expansion of each class.

MANIFEST_FILENAME = "class_manifest.json"


def write_manifest(path: Path, classes: list[ClassDescriptor]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "version": 1,
        "classes": [c.to_dict() for c in classes],
    }
    path.write_text(json.dumps(payload, indent=2))


def read_manifest(path: Path) -> list[ClassDescriptor]:
    if not path.exists():
        return []
    data = json.loads(path.read_text())
    return [ClassDescriptor.from_dict(d) for d in data.get("classes", [])]
