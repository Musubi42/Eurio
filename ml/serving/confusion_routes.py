"""Routes ``/confusion-map/*`` — cartographie de confusion visuelle.

Lecture seule depuis ``eurio.db.coin_confusion_map`` (rapatrié de Supabase
en Phase 1 data-layer-unification). Le compute lourd reste côté ML API
local (Mac/PC :8042) — ces routes-ci ne font que servir la donnée déjà
calculée.

Scopes : ``coins:read`` (toutes les routes).

Cf. ``docs/work-in-progress/data-layer-unification/IMPLEMENTATION.md`` §1.4.
"""
from __future__ import annotations

import json
import os
import sqlite3
from pathlib import Path
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from .auth_principal import Principal, require_scope

router = APIRouter(prefix="/confusion-map", tags=["confusion-map"])

_DEFAULT_ENCODER = "dinov2-vits14"


def _db_path() -> Path:
    return Path(os.environ.get("EURIO_DB_PATH", "/var/lib/eurio/eurio.db"))


def _connect() -> sqlite3.Connection:
    c = sqlite3.connect(str(_db_path()))
    c.row_factory = sqlite3.Row
    return c


_require_read = require_scope("coins:read")

Zone = Literal["green", "orange", "red"]
PersonalFilter = Literal["all", "both", "either"]


# ─── /confusion-map/stats ────────────────────────────────────────────────────


class HistogramBin(BaseModel):
    bin_start: float
    count: int


class ConfusionStats(BaseModel):
    total: int
    by_zone: dict[Zone, int] = Field(
        default_factory=lambda: {"green": 0, "orange": 0, "red": 0}
    )
    last_computed_at: str | None = None
    encoder_version: str
    histogram_bins: list[HistogramBin]


@router.get("/stats", response_model=ConfusionStats)
def get_stats(
    principal: Annotated[Principal, Depends(_require_read)],
    encoder_version: str = Query(default=_DEFAULT_ENCODER),
) -> ConfusionStats:
    """Compte par zone + histogramme des similarités (20 bins 0.05)."""
    conn = _connect()
    try:
        rows = conn.execute(
            "SELECT zone, nearest_similarity, computed_at "
            "FROM coin_confusion_map WHERE encoder_version = ?",
            (encoder_version,),
        ).fetchall()
    finally:
        conn.close()

    by_zone: dict[str, int] = {"green": 0, "orange": 0, "red": 0}
    bins = [HistogramBin(bin_start=round(i * 0.05, 2), count=0) for i in range(20)]
    last: str | None = None
    for r in rows:
        z = r["zone"]
        if z in by_zone:
            by_zone[z] += 1
        sim = float(r["nearest_similarity"])
        idx = min(19, max(0, int(sim * 20)))
        bins[idx].count += 1
        cat = r["computed_at"]
        if cat and (last is None or cat > last):
            last = cat

    return ConfusionStats(
        total=len(rows),
        by_zone=by_zone,  # type: ignore[arg-type]
        last_computed_at=last,
        encoder_version=encoder_version,
        histogram_bins=bins,
    )


# ─── /confusion-map/pairs ────────────────────────────────────────────────────


class PairCoinRef(BaseModel):
    eurio_id: str
    country: str
    year: int | None
    theme: str | None
    face_value: float
    image_url: str | None = None
    issue_type: str | None = None


class ConfusionPair(BaseModel):
    eurio_id_a: str
    eurio_id_b: str
    similarity: float
    zone: Zone
    coin_a: PairCoinRef
    coin_b: PairCoinRef


def _coin_image_url(conn: sqlite3.Connection, eurio_id: str) -> str | None:
    """Première image canonique disponible (obverse en priorité)."""
    row = conn.execute(
        "SELECT url FROM coin_canonical_images "
        "WHERE eurio_id = ? "
        "ORDER BY CASE face WHEN 'obverse' THEN 0 ELSE 1 END, id "
        "LIMIT 1",
        (eurio_id,),
    ).fetchone()
    return row["url"] if row else None


def _coin_refs(conn: sqlite3.Connection, ids: list[str]) -> dict[str, PairCoinRef]:
    """Charge en batch les refs coins + image canonique pour ``ids``."""
    if not ids:
        return {}
    placeholders = ",".join("?" * len(ids))
    rows = conn.execute(
        f"SELECT eurio_id, country, year, theme, face_value, "
        f"       variant_kind AS issue_type "
        f"FROM coins WHERE eurio_id IN ({placeholders})",
        ids,
    ).fetchall()
    out: dict[str, PairCoinRef] = {}
    for r in rows:
        eid = r["eurio_id"]
        out[eid] = PairCoinRef(
            eurio_id=eid,
            country=r["country"],
            year=r["year"],
            theme=r["theme"],
            face_value=float(r["face_value"]),
            image_url=_coin_image_url(conn, eid),
            issue_type=r["issue_type"],
        )
    return out


def _personal_owned_ids(conn: sqlite3.Connection) -> set[str]:
    rows = conn.execute(
        "SELECT eurio_id FROM coins WHERE personal_owned = 1"
    ).fetchall()
    return {r["eurio_id"] for r in rows}


@router.get("/pairs", response_model=list[ConfusionPair])
def get_pairs(
    principal: Annotated[Principal, Depends(_require_read)],
    encoder_version: str = Query(default=_DEFAULT_ENCODER),
    limit: int = Query(default=100, ge=1, le=2000),
    zone: Literal["all", "green", "orange", "red"] = Query(default="all"),
    personal: PersonalFilter = Query(default="all"),
) -> list[ConfusionPair]:
    """Paires (A↔B) ordonnées par similarité décroissante, dédupliquées."""
    conn = _connect()
    try:
        params: list = [encoder_version]
        sql = (
            "SELECT eurio_id, nearest_eurio_id, nearest_similarity, zone "
            "FROM coin_confusion_map "
            "WHERE encoder_version = ? AND nearest_eurio_id IS NOT NULL"
        )
        if zone != "all":
            sql += " AND zone = ?"
            params.append(zone)

        owned: set[str] | None = None
        if personal != "all":
            owned = _personal_owned_ids(conn)
            if not owned:
                return []
            in_clause = ",".join("?" * len(owned))
            if personal == "both":
                sql += f" AND eurio_id IN ({in_clause}) AND nearest_eurio_id IN ({in_clause})"
                params.extend(list(owned))
                params.extend(list(owned))
            else:  # 'either'
                sql += (
                    f" AND (eurio_id IN ({in_clause}) "
                    f"      OR nearest_eurio_id IN ({in_clause}))"
                )
                params.extend(list(owned))
                params.extend(list(owned))

        sql += " ORDER BY nearest_similarity DESC LIMIT ?"
        params.append(limit * 4)  # over-fetch pour dédup symétrique

        raw = conn.execute(sql, params).fetchall()

        seen: set[tuple[str, str]] = set()
        deduped: list[sqlite3.Row] = []
        for r in raw:
            a, b = r["eurio_id"], r["nearest_eurio_id"]
            key = (a, b) if a < b else (b, a)
            if key in seen:
                continue
            seen.add(key)
            deduped.append(r)
            if len(deduped) >= limit:
                break

        # Enrichissement coins refs en batch
        ids = list({i for r in deduped for i in (r["eurio_id"], r["nearest_eurio_id"])})
        refs = _coin_refs(conn, ids)

        def _ref(eid: str) -> PairCoinRef:
            return refs.get(eid) or PairCoinRef(
                eurio_id=eid, country="—", year=None, theme=None,
                face_value=0.0, image_url=None,
            )

        return [
            ConfusionPair(
                eurio_id_a=r["eurio_id"],
                eurio_id_b=r["nearest_eurio_id"],
                similarity=float(r["nearest_similarity"]),
                zone=r["zone"],  # type: ignore[arg-type]
                coin_a=_ref(r["eurio_id"]),
                coin_b=_ref(r["nearest_eurio_id"]),
            )
            for r in deduped
        ]
    finally:
        conn.close()


# ─── /confusion-map/coin/{eurio_id} ──────────────────────────────────────────


class ConfusionNeighbor(BaseModel):
    eurio_id: str
    similarity: float
    coin: PairCoinRef | None = None


class CoinConfusionDetail(BaseModel):
    zone: Zone
    nearest_similarity: float
    nearest_eurio_id: str | None
    top_k_neighbors: list[ConfusionNeighbor]


@router.get("/coin/{eurio_id}", response_model=CoinConfusionDetail | None)
def get_coin_detail(
    eurio_id: str,
    principal: Annotated[Principal, Depends(_require_read)],
    encoder_version: str = Query(default=_DEFAULT_ENCODER),
) -> CoinConfusionDetail | None:
    conn = _connect()
    try:
        row = conn.execute(
            "SELECT zone, nearest_similarity, nearest_eurio_id, top_k_neighbors "
            "FROM coin_confusion_map "
            "WHERE encoder_version = ? AND eurio_id = ?",
            (encoder_version, eurio_id),
        ).fetchone()
        if not row:
            return None

        neighbors_raw = json.loads(row["top_k_neighbors"] or "[]")
        ids = [n["eurio_id"] for n in neighbors_raw if "eurio_id" in n]
        refs = _coin_refs(conn, ids)

        neighbors = [
            ConfusionNeighbor(
                eurio_id=n["eurio_id"],
                similarity=float(n.get("similarity", 0.0)),
                coin=refs.get(n["eurio_id"]),
            )
            for n in neighbors_raw
            if "eurio_id" in n
        ]
        return CoinConfusionDetail(
            zone=row["zone"],  # type: ignore[arg-type]
            nearest_similarity=float(row["nearest_similarity"]),
            nearest_eurio_id=row["nearest_eurio_id"],
            top_k_neighbors=neighbors,
        )
    finally:
        conn.close()


# ─── /confusion-map/zone-map ────────────────────────────────────────────────


class ZoneEntry(BaseModel):
    zone: Zone
    nearest_similarity: float


@router.get("/zone-map", response_model=dict[str, ZoneEntry])
def get_zone_map(
    principal: Annotated[Principal, Depends(_require_read)],
    encoder_version: str = Query(default=_DEFAULT_ENCODER),
) -> dict[str, ZoneEntry]:
    """Dictionnaire `eurio_id → {zone, similarity}` pour badges côté front."""
    conn = _connect()
    try:
        rows = conn.execute(
            "SELECT eurio_id, zone, nearest_similarity "
            "FROM coin_confusion_map WHERE encoder_version = ?",
            (encoder_version,),
        ).fetchall()
    finally:
        conn.close()
    out: dict[str, ZoneEntry] = {}
    for r in rows:
        if r["zone"] not in ("green", "orange", "red"):
            continue
        out[r["eurio_id"]] = ZoneEntry(
            zone=r["zone"],  # type: ignore[arg-type]
            nearest_similarity=float(r["nearest_similarity"]),
        )
    return out
