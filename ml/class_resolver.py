"""Resolve coin classes for ArcFace training.

A "class" is the label ArcFace learns. Under the design_groups scheme
(docs/design/_shared/design-groups.md §6.1), the label is:

    COALESCE(design_group_id, eurio_id)

So a coin with a design_group_id (shared-design grouping) contributes to a
design_group-level class; a coin without one is its own eurio_id-level class.

This module builds the mapping once from Supabase and exposes lookups used by
prepare_dataset, compute_embeddings, seed_supabase, and the training runner.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import httpx


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
    base = root or Path(__file__).resolve().parent.parent
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


def fetch_coin_refs(
    *,
    supabase_url: str,
    supabase_key: str,
    numista_ids: Iterable[int] | None = None,
) -> list[CoinRef]:
    """Fetch coin identifiers from Supabase.

    If `numista_ids` is given, only coins with one of those ids are returned.
    Otherwise, all coins with a numista_id are returned (the universe known to
    the ML pipeline).
    """
    headers = {
        "apikey": supabase_key,
        "Authorization": f"Bearer {supabase_key}",
    }
    params: dict[str, str] = {
        "select": "eurio_id,design_group_id,cross_refs",
        "cross_refs->numista_id": "not.is.null",
    }
    rest_base = supabase_url.rstrip("/") + "/rest/v1"

    coins: list[CoinRef] = []
    with httpx.Client(headers=headers, timeout=60) as client:
        resp = client.get(
            f"{rest_base}/coins",
            params=params,
            headers={"Range": "0-9999"},
        )
        resp.raise_for_status()
        filter_ids = {int(n) for n in numista_ids} if numista_ids else None
        for row in resp.json():
            cross = row.get("cross_refs") or {}
            nid_raw = cross.get("numista_id")
            nid = int(nid_raw) if nid_raw is not None else None
            if filter_ids is not None and (nid is None or nid not in filter_ids):
                continue
            coins.append(
                CoinRef(
                    eurio_id=row["eurio_id"],
                    numista_id=nid,
                    design_group_id=row.get("design_group_id"),
                )
            )
    return coins


def build_resolver(env: dict[str, str] | None = None) -> Resolver:
    env = env or load_env()
    url = env.get("SUPABASE_URL", "")
    key = env.get("SUPABASE_SERVICE_ROLE_KEY", "")
    if not url or not key:
        raise RuntimeError(
            "SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY required to build class resolver"
        )
    coins = fetch_coin_refs(supabase_url=url, supabase_key=key)
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
