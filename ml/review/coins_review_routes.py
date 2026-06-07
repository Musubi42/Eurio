"""FastAPI router pour `/coins-review` — review queue UI backing.

Sert la queue des coins avec `needs_review = true` enrichis par
`apply_3e_enrich_context.py` (review_action_hint + review_payload).
Consommé par l'admin Vue (`admin/packages/web/src/features/coins/.../*`).

3 actions de résolution :
  - rebind          : bind un numista_id à ce coin (search locale + API fallback)
  - no-coverage     : acter qu'il n'existe pas d'équivalent Numista
  - delete-redirect : supprimer le coin et migrer ses dépendants vers une cible

Refs :
  docs/research/referential-v2-progress.md §3e
  supabase/migrations/20260516_coins_review_context.sql
  ml/referential/apply_3e_enrich_context.py  (contrat du payload)
"""

from __future__ import annotations

import json
import logging
import re
import unicodedata
from datetime import date
from pathlib import Path
from typing import Any, Callable

import httpx
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from serving.supabase_client import SupabaseClient

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/coins-review", tags=["coins-review"])

# ─── Bound state ──────────────────────────────────────────────────────────────

_get_supabase: Callable[[], SupabaseClient] | None = None


def bind(get_supabase: Callable[[], SupabaseClient]) -> None:
    """Wire le router à un getter Supabase lazy (cf. server.py)."""
    global _get_supabase
    _get_supabase = get_supabase


def _sb() -> SupabaseClient:
    if _get_supabase is None:
        raise HTTPException(503, "coins_review_routes not bound")
    return _get_supabase()


# ─── Local Numista catalog (loaded lazily) ────────────────────────────────────

_ML_DIR = Path(__file__).parent.parent
_CATALOG_PATH = _ML_DIR / "datasets" / "coin_catalog.json"

# Names → iso2 map (cf. ml/referential/eurio_referential.py)
_COUNTRY_NAME_TO_ISO2: dict[str, str] = {
    "Austria": "at", "Belgium": "be", "Bulgaria": "bg", "Croatia": "hr",
    "Cyprus": "cy", "Estonia": "ee", "Finland": "fi", "France": "fr",
    "Germany": "de", "Greece": "gr", "Ireland": "ie", "Italy": "it",
    "Latvia": "lv", "Lithuania": "lt", "Luxembourg": "lu", "Malta": "mt",
    "Netherlands": "nl", "Portugal": "pt", "Slovakia": "sk", "Slovenia": "si",
    "Spain": "es", "Andorra": "ad", "Monaco": "mc", "San Marino": "sm",
    "Vatican City": "va", "Vatican": "va", "European Union": "eu",
    "Germany, Federal Republic of": "de",
}

_catalog_cache: list[dict] | None = None


def _load_catalog() -> list[dict]:
    """Return the local Numista catalog, normalized with `country_iso2` field."""
    global _catalog_cache
    if _catalog_cache is not None:
        return _catalog_cache
    if not _CATALOG_PATH.exists():
        _catalog_cache = []
        return _catalog_cache
    raw = json.loads(_CATALOG_PATH.read_text())
    coins = raw.get("coins", {})
    rows: list[dict] = []
    for nid_key, c in coins.items():
        country = c.get("country")
        iso2 = _COUNTRY_NAME_TO_ISO2.get(country or "")
        rows.append({
            "numista_id": str(c.get("numista_id", nid_key)),
            "name": c.get("name") or "",
            "country": country,
            "country_iso2": iso2,
            "year": c.get("year"),
            "face_value": c.get("face_value"),
            "type": c.get("type"),
        })
    _catalog_cache = rows
    return _catalog_cache


_WORD_RE = re.compile(r"[a-z0-9]+")


def _ascii_fold(s: str) -> str:
    """Strip diacritics so 'Guimarães' matches 'guimaraes'."""
    nfkd = unicodedata.normalize("NFKD", s or "")
    return "".join(ch for ch in nfkd if not unicodedata.combining(ch))


def _tokenize(s: str) -> set[str]:
    return set(_WORD_RE.findall(_ascii_fold(s).lower()))


# ─── Response models ─────────────────────────────────────────────────────────


class ReviewQueueItem(BaseModel):
    eurio_id: str
    country: str
    year: int
    theme: str | None
    design_description: str | None
    is_commemorative: bool
    cross_refs: dict[str, Any] = Field(default_factory=dict)
    images: Any = None  # JSON in DB — list or dict, keep loose
    design_group_id: str | None
    review_reason: str | None
    review_action_hint: str | None
    review_payload: dict[str, Any] = Field(default_factory=dict)
    variants: list[dict] = Field(default_factory=list)


class CatalogHit(BaseModel):
    numista_id: str
    name: str
    country: str | None
    country_iso2: str | None
    year: int | None
    face_value: float | None
    type: str | None
    score: float
    source: str  # 'local' | 'numista_live'


class RebindPayload(BaseModel):
    numista_id: str
    native_url: str | None = None


class NoCoveragePayload(BaseModel):
    note: str | None = None


class DeleteRedirectPayload(BaseModel):
    target_eurio_id: str
    confirm: bool = False


# ─── GET /coins-review/queue ─────────────────────────────────────────────────


@router.get("/queue", response_model=list[ReviewQueueItem])
def queue() -> list[ReviewQueueItem]:
    """Retourne les coins.needs_review=true enrichis avec leurs variants liés."""
    sb = _sb()
    coins = sb.query(
        "coins",
        select=(
            "eurio_id,country,year,theme,design_description,is_commemorative,"
            "cross_refs,images,design_group_id,review_reason,review_action_hint,"
            "review_payload"
        ),
        params={"needs_review": "eq.true", "order": "review_action_hint.asc,country.asc,year.asc"},
    )
    if not coins:
        return []

    # Pre-fetch variants for any verify_parent cases
    parent_eids = [
        c["eurio_id"] for c in coins
        if c.get("review_action_hint") == "verify_parent"
    ]
    variants_by_parent: dict[str, list[dict]] = {}
    if parent_eids:
        in_list = ",".join(parent_eids)
        rows = sb.query(
            "coin_variants",
            select="id,parent_type_id,finish,obverse_url,reverse_url,notes",
            params={"parent_type_id": f"in.({in_list})"},
        )
        for r in rows:
            variants_by_parent.setdefault(r["parent_type_id"], []).append(r)

    out: list[ReviewQueueItem] = []
    for c in coins:
        out.append(ReviewQueueItem(
            eurio_id=c["eurio_id"],
            country=c["country"],
            year=c["year"],
            theme=c.get("theme"),
            design_description=c.get("design_description"),
            is_commemorative=c.get("is_commemorative", False),
            cross_refs=c.get("cross_refs") or {},
            images=c.get("images"),
            design_group_id=c.get("design_group_id"),
            review_reason=c.get("review_reason"),
            review_action_hint=c.get("review_action_hint"),
            review_payload=c.get("review_payload") or {},
            variants=variants_by_parent.get(c["eurio_id"], []),
        ))
    return out


# ─── GET /coins-review/search-numista ────────────────────────────────────────


@router.get("/search-numista", response_model=list[CatalogHit])
def search_numista(
    q: str = Query("", description="Free-text search on Numista catalog name"),
    country: str | None = Query(None, description="ISO2 (lowercase), e.g. 'fr'"),
    year: int | None = Query(None),
    face_value: float = Query(2.0, description="Default 2.0 (review queue is 2€-only)"),
    limit: int = Query(20, ge=1, le=100),
    include_live: bool = Query(False, description="Fall back to Numista API if local has < 3 hits"),
) -> list[CatalogHit]:
    """Search the local Numista catalog snapshot. Optional live API fallback.

    Local search = `coin_catalog.json` packagé (688 coins, ~441 2€). Fast,
    zero quota. Si include_live=true et le local renvoie < 3 hits, on
    appelle l'API Numista en complément (consomme du quota — réservé à
    l'usage manuel par l'admin).
    """
    catalog = _load_catalog()
    q_tokens = _tokenize(q)
    cn = country.lower() if country else None

    # Score local candidates
    scored: list[tuple[float, dict]] = []
    for row in catalog:
        if cn and row.get("country_iso2") != cn:
            continue
        if year is not None and row.get("year") != year:
            continue
        if face_value is not None and row.get("face_value") not in (None, face_value):
            continue
        name_tokens = _tokenize(row["name"])
        if q_tokens:
            inter = len(q_tokens & name_tokens)
            if inter == 0:
                continue
            score = inter / max(len(q_tokens), 1)
        else:
            score = 1.0  # no q → keep all that match country/year
        scored.append((score, row))
    scored.sort(key=lambda x: (-x[0], x[1].get("numista_id")))
    local_hits = [
        CatalogHit(
            numista_id=str(r["numista_id"]),
            name=r["name"],
            country=r.get("country"),
            country_iso2=r.get("country_iso2"),
            year=r.get("year"),
            face_value=r.get("face_value"),
            type=r.get("type"),
            score=s,
            source="local",
        )
        for s, r in scored[:limit]
    ]

    if include_live and len(local_hits) < 3 and q:
        try:
            live = _search_numista_live(q, country=cn, year=year, face_value=face_value)
            seen = {h.numista_id for h in local_hits}
            for h in live:
                if h.numista_id not in seen:
                    local_hits.append(h)
                if len(local_hits) >= limit:
                    break
        except Exception as exc:  # noqa: BLE001
            logger.warning("numista live search failed: %s", exc)

    return local_hits


def _search_numista_live(
    q: str,
    *,
    country: str | None,
    year: int | None,
    face_value: float | None,
) -> list[CatalogHit]:
    """Live search via Numista API v3. Requires NUMISTA_API_KEY env."""
    import os
    api_key = os.environ.get("NUMISTA_API_KEY", "")
    if not api_key:
        from serving.supabase_client import load_env
        env = load_env()
        api_key = env.get("NUMISTA_API_KEY", "")
    if not api_key:
        return []
    params: dict[str, Any] = {"q": q, "category": "coin", "count": 20, "lang": "en"}
    if country:
        params["issuer"] = country.lower()
    if face_value is not None:
        params["face_value"] = face_value
    if year is not None:
        params["year"] = year
    headers = {"Numista-API-Key": api_key}
    with httpx.Client(timeout=10) as cli:
        resp = cli.get("https://api.numista.com/v3/types", params=params, headers=headers)
        resp.raise_for_status()
        data = resp.json()
    out: list[CatalogHit] = []
    for t in data.get("types", []):
        out.append(CatalogHit(
            numista_id=str(t.get("id")),
            name=t.get("title") or "",
            country=(t.get("issuer") or {}).get("name"),
            country_iso2=(t.get("issuer") or {}).get("code", "").lower() or None,
            year=t.get("min_year"),
            face_value=(t.get("value") or {}).get("numeric_value"),
            type=None,
            score=0.5,  # live hits don't have a meaningful local score
            source="numista_live",
        ))
    return out


# ─── POST /coins-review/{eurio_id}/rebind ────────────────────────────────────


@router.post("/{eurio_id}/rebind")
def rebind(eurio_id: str, payload: RebindPayload) -> dict[str, Any]:
    """Bind un numista_id à ce coin. PATCH coins + UPSERT coin_source_refs."""
    sb = _sb()
    rows = sb.query(
        "coins",
        select="eurio_id,cross_refs",
        params={"eurio_id": f"eq.{eurio_id}"},
    )
    if not rows:
        raise HTTPException(404, f"coin {eurio_id} not found")
    coin = rows[0]

    nid_int: int
    try:
        nid_int = int(payload.numista_id)
    except ValueError:
        raise HTTPException(400, f"numista_id must be int-like, got {payload.numista_id!r}")

    cross_refs = dict(coin.get("cross_refs") or {})
    cross_refs["numista_id"] = nid_int
    today = date.today().isoformat()

    sb.patch(
        "coins",
        filters={"eurio_id": f"eq.{eurio_id}"},
        payload={
            "cross_refs": cross_refs,
            "needs_review": False,
            "review_reason": None,
            "review_action_hint": None,
            "review_payload": None,
            "last_updated": today,
        },
    )
    sb.upsert(
        "coin_source_refs",
        [{
            "coin_type_id": eurio_id,
            "source": "numista",
            "native_id": str(nid_int),
            "native_url": payload.native_url,
        }],
        on_conflict="coin_type_id,source,native_id",
    )
    return {"eurio_id": eurio_id, "numista_id": nid_int, "status": "rebound"}


# ─── POST /coins-review/{eurio_id}/no-coverage ──────────────────────────────


@router.post("/{eurio_id}/no-coverage")
def no_coverage(eurio_id: str, payload: NoCoveragePayload) -> dict[str, Any]:
    """Clear needs_review, garde le coin tel quel (Numista n'a pas d'entrée)."""
    sb = _sb()
    rows = sb.query(
        "coins",
        select="eurio_id,sources_used",
        params={"eurio_id": f"eq.{eurio_id}"},
    )
    if not rows:
        raise HTTPException(404, f"coin {eurio_id} not found")
    coin = rows[0]
    sources = [s for s in (coin.get("sources_used") or []) if s != "numista"]
    today = date.today().isoformat()

    note = (payload.note or "").strip()
    patch = {
        "needs_review": False,
        "review_reason": (
            f"3e resolved: no Numista coverage — {note}" if note
            else "3e resolved: no Numista coverage"
        ),
        "review_action_hint": None,
        "review_payload": None,
        "sources_used": sources,
        "last_updated": today,
    }
    sb.patch("coins", filters={"eurio_id": f"eq.{eurio_id}"}, payload=patch)
    return {"eurio_id": eurio_id, "status": "no_coverage"}


# ─── POST /coins-review/{eurio_id}/delete-redirect ───────────────────────────


@router.post("/{eurio_id}/delete-redirect")
def delete_redirect(
    eurio_id: str, payload: DeleteRedirectPayload
) -> dict[str, Any]:
    """Migre les dépendants vers `target_eurio_id` et supprime le coin source.

    Pré-flight (refuse si non-trivial) :
      - target_eurio_id doit exister dans coins
      - source ne doit pas avoir de coin_variants ni coin_mint_releases
        (slug variant = `{parent}/{finish}` → casse silencieuse au rename)
      - payload.confirm doit être true (gard-rail explicite)

    Migration des FKs (best-effort, conflits gérés par DELETE en fallback) :
      - coin_source_refs   (coin_type_id)
      - coin_market_prices (eurio_id)
      - set_members        (eurio_id)
      - coin_embeddings    (eurio_id) si présent
      - coin_confusion_map (eurio_id et nearest_eurio_id)
      - source_observations, user_collections, matching_decisions

    DELETE final du coin source.
    """
    if not payload.confirm:
        raise HTTPException(
            400,
            "delete-redirect requires confirm=true in payload (explicit guard-rail)",
        )
    if payload.target_eurio_id == eurio_id:
        raise HTTPException(400, "target_eurio_id must differ from source eurio_id")

    sb = _sb()
    src = sb.query("coins", select="eurio_id", params={"eurio_id": f"eq.{eurio_id}"})
    if not src:
        raise HTTPException(404, f"source coin {eurio_id} not found")
    tgt = sb.query(
        "coins", select="eurio_id", params={"eurio_id": f"eq.{payload.target_eurio_id}"}
    )
    if not tgt:
        raise HTTPException(404, f"target coin {payload.target_eurio_id} not found")

    # Pre-flight: refuse if has variants or mint_releases (slug refactor needed)
    variants = sb.query(
        "coin_variants",
        select="id",
        params={"parent_type_id": f"eq.{eurio_id}"},
    )
    if variants:
        raise HTTPException(
            409,
            f"source has {len(variants)} coin_variants — manual cleanup required "
            f"(variant ids embed the parent eurio_id slug)",
        )
    mint_rels = sb.query(
        "coin_mint_releases",
        select="id",
        params={"parent_type_id": f"eq.{eurio_id}"},
    )
    if mint_rels:
        raise HTTPException(
            409,
            f"source has {len(mint_rels)} coin_mint_releases — manual cleanup required",
        )

    migrations: list[tuple[str, str]] = [
        ("coin_source_refs", "coin_type_id"),
        ("coin_market_prices", "eurio_id"),
        ("set_members", "eurio_id"),
        ("coin_embeddings", "eurio_id"),
        ("source_observations", "eurio_id"),
        ("user_collections", "eurio_id"),
        ("matching_decisions", "eurio_id"),
        ("coin_confusion_map", "eurio_id"),
        ("coin_confusion_map", "nearest_eurio_id"),
    ]
    migrated: list[dict[str, Any]] = []
    for table, col in migrations:
        try:
            sb.patch(
                table,
                filters={col: f"eq.{eurio_id}"},
                payload={col: payload.target_eurio_id},
            )
            migrated.append({"table": table, "col": col, "status": "patched"})
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code in (409, 400):
                # Unique conflict on the target side — drop the source rows
                try:
                    sb.delete(table, filters={col: f"eq.{eurio_id}"})
                    migrated.append({"table": table, "col": col, "status": "deleted_on_conflict"})
                except httpx.HTTPStatusError as exc2:
                    logger.warning("delete on conflict failed %s.%s: %s", table, col, exc2)
                    migrated.append({"table": table, "col": col, "status": f"error_{exc2.response.status_code}"})
            elif exc.response.status_code == 404:
                migrated.append({"table": table, "col": col, "status": "skipped_404"})
            else:
                logger.error("migration failed %s.%s: %s", table, col, exc)
                migrated.append({"table": table, "col": col, "status": f"error_{exc.response.status_code}"})

    try:
        sb.delete("coins", filters={"eurio_id": f"eq.{eurio_id}"})
    except httpx.HTTPStatusError as exc:
        raise HTTPException(
            500,
            f"failed to delete source coin (FK still referencing it ?): {exc.response.text}",
        )

    return {
        "eurio_id": eurio_id,
        "target_eurio_id": payload.target_eurio_id,
        "status": "redirected",
        "migrations": migrated,
    }
