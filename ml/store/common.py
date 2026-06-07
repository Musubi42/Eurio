"""Types et helpers partagés entre les modules de store/."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass


@dataclass(frozen=True)
class ClassRef:
    class_id: str
    class_kind: str

    def to_dict(self) -> dict:
        return {"class_id": self.class_id, "class_kind": self.class_kind}

    @classmethod
    def from_dict(cls, d: dict) -> "ClassRef":
        return cls(class_id=d["class_id"], class_kind=d["class_kind"])


def _dump_refs(refs: list[ClassRef]) -> str:
    return json.dumps([r.to_dict() for r in refs])


def _load_refs(raw: str) -> list[ClassRef]:
    return [ClassRef.from_dict(d) for d in json.loads(raw)]


def _optional_column(row: sqlite3.Row, name: str) -> object | None:
    """Return ``row[name]`` if the column exists on the row, else None.

    SQLite rows fetched via older schemas may not expose new columns; we treat
    a missing column the same as NULL.
    """
    try:
        return row[name]
    except (IndexError, KeyError):
        return None
