"""FastAPI router pour les données coin lues par l'admin Vue.

P.8a du chantier coin-richness — découpage Supabase → eurio.db. Surface :

  GET    /coins/lookups/trained          → set eurio_ids avec embedding
  GET    /coins/lookups/source-counts    → counts par source (numista, bce, …)
  GET    /coins/{eurio_id}               → Coin payload complet
  GET    /coins/{eurio_id}/i18n          → {names: [], aliases: []}
  GET    /coins/{eurio_id}/prices        → {type_level: [], mint_release_level: []}
  GET    /coins/{eurio_id}/embedding     → {model_version: str | null}
  GET    /coins/{eurio_id}/series        → coin_series row | null
  PATCH  /coins/{eurio_id}                → flip personal_owned / lent_to_me

Coexiste avec ``coin_assets_routes`` (prefix identique ``/coins``) : les
paths ne collisionnent pas. Pas de doublon de modèle, les deux fichiers
sont complémentaires (assets = images, ici = données référentiel + i18n).
"""

from __future__ import annotations

import json
import logging
import sqlite3
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from state import Store

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/coins", tags=["coins"])


_store: Store | None = None


def bind(store: Store) -> None:
    global _store
    _store = store


def _conn() -> sqlite3.Connection:
    if _store is None:
        raise RuntimeError("coins_routes not bound — call bind() first.")
    return _store._connection()  # noqa: SLF001


# ── Models ────────────────────────────────────────────────────────────────


class CoinImage(BaseModel):
    role: str   # 'obverse' | 'reverse'
    source: str
    url: str | None
    local_path: str | None = None


class CoinDetail(BaseModel):
    eurio_id: str
    country: str
    country_name: str | None = None
    year: int
    face_value: float
    currency: str
    is_commemorative: bool
    theme: str | None = None
    numista_id: int | None = None
    design_description: str | None = None
    design_group_id: str | None = None
    series_id: str | None = None
    personal_owned: bool = False
    lent_to_me: bool = False
    needs_review: bool = False
    images: list[CoinImage] = Field(default_factory=list)
    cross_refs: dict[str, str] = Field(default_factory=dict)
    sources_used: list[str] = Field(default_factory=list)
    has_bce: bool = False
    has_ebay: bool = False
    has_lmdlp: bool = False
    has_wikipedia: bool = False


class I18nName(BaseModel):
    lang: str
    title: str
    source: str
    method: str | None = None
    confidence: str | None = None
    model: str | None = None


class I18nAlias(BaseModel):
    lang: str
    alias: str
    source: str
    method: str | None = None
    confidence: str | None = None


class I18nResponse(BaseModel):
    names: list[I18nName]
    aliases: list[I18nAlias]


class TypeLevelPrice(BaseModel):
    source: str
    condition_normalized: str
    condition_raw: str | None = None
    currency: str
    p10: float | None = None
    p50: float | None = None
    p90: float | None = None
    sample_size: int
    period_start: str
    period_end: str


class MintReleasePrice(BaseModel):
    mint_release_id: str
    parent_type_id: str
    mint_id: str | None
    mint_year: int
    issue_type: str
    source: str
    grade_raw: str
    grade_eurio: str | None
    price: float
    currency: str
    fetched_at: str


class PricesResponse(BaseModel):
    type_level: list[TypeLevelPrice]
    mint_release_level: list[MintReleasePrice]


class EmbeddingResponse(BaseModel):
    model_version: str | None


class CoinSeries(BaseModel):
    id: str
    country: str
    designation: str
    designation_i18n: dict[str, str] | None = None
    description: str | None = None
    minting_started_at: str
    minting_ended_at: str | None = None
    minting_end_reason: str | None = None


class CoinPatch(BaseModel):
    personal_owned: bool | None = None
    lent_to_me: bool | None = None


# ── Lookups ───────────────────────────────────────────────────────────────


@router.get("/lookups/trained", response_model=list[str])
def get_trained_eurio_ids() -> list[str]:
    """Liste eurio_ids ayant un embedding (équivalent Supabase
    coin_embeddings.eurio_id distinct)."""
    rows = _conn().execute(
        "SELECT DISTINCT eurio_id FROM coin_embeddings ORDER BY eurio_id"
    ).fetchall()
    return [r[0] for r in rows]


@router.get("/lookups/source-counts", response_model=dict[str, int])
def get_source_counts() -> dict[str, int]:
    """Counts par source (numista, bce, wikipedia, lmdlp, ebay). Dérivé
    de coin_source_refs côté SQLite (vs has_* booléens Supabase). Mapping
    pipeline → ID frontend conservé pour compat (`numista` = numista_api,
    `bce` = bce_official, etc.)."""
    conn = _conn()
    # Sources lues en SQL via les noms registry, exposées sous les clés
    # frontend (court).
    sources = {
        "numista":   "numista_api",
        "bce":       "bce_official",
        "wikipedia": "wikipedia",
        "lmdlp":     "lmdlp",
        "ebay":      "ebay_browse",
    }
    out: dict[str, int] = {}
    for key, registry in sources.items():
        row = conn.execute(
            "SELECT COUNT(DISTINCT target_id) FROM coin_source_refs "
            "WHERE source = ? AND target_kind = 'coin'",
            (registry,),
        ).fetchone()
        out[key] = row[0] if row else 0
    return out


# ── Detail + sub-resources ────────────────────────────────────────────────


def _build_coin_detail(conn: sqlite3.Connection, eurio_id: str) -> CoinDetail:
    row = conn.execute(
        "SELECT * FROM coins WHERE eurio_id = ?", (eurio_id,),
    ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail=f"coin {eurio_id} not found")
    d: dict[str, Any] = dict(row)

    # Images depuis coin_canonical_images
    img_rows = conn.execute(
        "SELECT role, source, url, local_path FROM coin_canonical_images "
        "WHERE eurio_id = ? ORDER BY role, source", (eurio_id,),
    ).fetchall()
    images = [CoinImage(**dict(r)) for r in img_rows]

    # cross_refs depuis coin_cross_refs (key=ref_type, value=ref_value)
    cr_rows = conn.execute(
        "SELECT ref_type, ref_value FROM coin_cross_refs WHERE eurio_id = ?",
        (eurio_id,),
    ).fetchall()
    cross_refs = {r["ref_type"]: r["ref_value"] for r in cr_rows}

    # sources_used = distinct sources qui ont déposé une row sur ce coin
    src_rows = conn.execute(
        "SELECT DISTINCT source FROM coin_source_refs "
        "WHERE target_kind = 'coin' AND target_id = ? ORDER BY source",
        (eurio_id,),
    ).fetchall()
    sources_used = [r[0] for r in src_rows]

    has_flags = {
        "has_bce":       "bce_official" in sources_used,
        "has_ebay":      "ebay_browse"  in sources_used,
        "has_wikipedia": "wikipedia"    in sources_used,
        "has_lmdlp":     "lmdlp"        in sources_used,
    }

    return CoinDetail(
        eurio_id=d["eurio_id"],
        country=d["country"],
        country_name=d.get("country_name"),
        year=d["year"],
        face_value=d["face_value"],
        currency=d.get("currency") or "EUR",
        is_commemorative=bool(d.get("is_commemorative", 0)),
        theme=d.get("theme"),
        numista_id=d.get("numista_id"),
        design_description=d.get("design_description"),
        design_group_id=d.get("design_group_id"),
        series_id=d.get("series_id"),
        personal_owned=bool(d.get("personal_owned", 0)),
        lent_to_me=bool(d.get("lent_to_me", 0)),
        needs_review=bool(d.get("needs_review", 0)),
        images=images,
        cross_refs=cross_refs,
        sources_used=sources_used,
        **has_flags,
    )


@router.get("/{eurio_id}", response_model=CoinDetail)
def get_coin(eurio_id: str) -> CoinDetail:
    return _build_coin_detail(_conn(), eurio_id)


@router.get("/{eurio_id}/i18n", response_model=I18nResponse)
def get_coin_i18n(eurio_id: str) -> I18nResponse:
    conn = _conn()
    names_rows = conn.execute(
        "SELECT lang, title, source, method, confidence, model "
        "FROM coin_names_i18n WHERE eurio_id = ? ORDER BY lang",
        (eurio_id,),
    ).fetchall()
    aliases_rows = conn.execute(
        "SELECT lang, alias, source, method, confidence FROM coin_aliases "
        "WHERE eurio_id = ? ORDER BY lang, alias", (eurio_id,),
    ).fetchall()
    return I18nResponse(
        names=[I18nName(**dict(r)) for r in names_rows],
        aliases=[I18nAlias(**dict(r)) for r in aliases_rows],
    )


@router.get("/{eurio_id}/prices", response_model=PricesResponse)
def get_coin_prices(eurio_id: str) -> PricesResponse:
    """Option B (cf. P.8 audit) — structure riche :
    * type_level   : agrégation UNC/TTB/TB depuis coin_market_quotes
    * mint_release_level : prix granulaires par atelier × grade depuis
      mint_release_prices (joint avec coin_mint_releases pour les méta)
    """
    conn = _conn()
    tl_rows = conn.execute(
        "SELECT source, condition_raw, condition_normalized, currency, "
        "p10, p50, p90, sample_size, period_start, period_end "
        "FROM coin_market_quotes WHERE eurio_id = ? "
        "ORDER BY period_start DESC, condition_normalized",
        (eurio_id,),
    ).fetchall()

    mr_rows = conn.execute(
        """
        SELECT p.mint_release_id, r.parent_type_id, r.mint_id, r.mint_year,
               r.issue_type, p.source, p.grade_raw, p.grade_eurio,
               p.price, p.currency, p.fetched_at
        FROM mint_release_prices p
        JOIN coin_mint_releases r ON r.id = p.mint_release_id
        WHERE r.parent_type_id = ?
        ORDER BY r.mint_year, r.mint_id, r.issue_type, p.grade_raw
        """,
        (eurio_id,),
    ).fetchall()

    return PricesResponse(
        type_level=[TypeLevelPrice(**dict(r)) for r in tl_rows],
        mint_release_level=[MintReleasePrice(**dict(r)) for r in mr_rows],
    )


@router.get("/{eurio_id}/embedding", response_model=EmbeddingResponse)
def get_coin_embedding(eurio_id: str) -> EmbeddingResponse:
    """Renvoie le model_version le plus récent (par created_at) si présent."""
    row = _conn().execute(
        "SELECT model_version FROM coin_embeddings WHERE eurio_id = ? "
        "ORDER BY created_at DESC LIMIT 1", (eurio_id,),
    ).fetchone()
    return EmbeddingResponse(model_version=row[0] if row else None)


@router.get("/{eurio_id}/series", response_model=CoinSeries | None)
def get_coin_series(eurio_id: str) -> CoinSeries | None:
    conn = _conn()
    coin = conn.execute(
        "SELECT series_id FROM coins WHERE eurio_id = ?", (eurio_id,),
    ).fetchone()
    if coin is None or coin[0] is None:
        return None
    row = conn.execute(
        "SELECT id, country, designation, designation_i18n_json, description, "
        "minting_started_at, minting_ended_at, minting_end_reason "
        "FROM coin_series WHERE id = ?", (coin[0],),
    ).fetchone()
    if row is None:
        return None
    d = dict(row)
    designation_i18n = (
        json.loads(d["designation_i18n_json"]) if d.get("designation_i18n_json") else None
    )
    return CoinSeries(
        id=d["id"], country=d["country"], designation=d["designation"],
        designation_i18n=designation_i18n,
        description=d.get("description"),
        minting_started_at=d["minting_started_at"],
        minting_ended_at=d.get("minting_ended_at"),
        minting_end_reason=d.get("minting_end_reason"),
    )


@router.patch("/{eurio_id}", response_model=CoinDetail)
def patch_coin(eurio_id: str, payload: CoinPatch) -> CoinDetail:
    """Flip personal_owned / lent_to_me. Pas-d'-op si payload vide."""
    conn = _conn()
    updates: list[str] = []
    params: list[Any] = []
    if payload.personal_owned is not None:
        updates.append("personal_owned = ?")
        params.append(1 if payload.personal_owned else 0)
    if payload.lent_to_me is not None:
        updates.append("lent_to_me = ?")
        params.append(1 if payload.lent_to_me else 0)
    if updates:
        updates.append("updated_at = datetime('now')")
        params.append(eurio_id)
        sql = f"UPDATE coins SET {', '.join(updates)} WHERE eurio_id = ?"
        result = conn.execute(sql, params)
        if result.rowcount == 0:
            raise HTTPException(status_code=404, detail=f"coin {eurio_id} not found")
    return _build_coin_detail(conn, eurio_id)
