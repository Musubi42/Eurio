"""FastAPI routes — studio bench du theme-matcher eBay (local-only).

Sert le gold gelé (`ml/state/discovery_bench/theme_match_gold.jsonl`)
rejoué par le pipeline, pour que l'admin puisse *juger* lui-même chaque
décision de filtrage au lieu de faire confiance au juge LLM.

Chunk 1 — lecture seule : `GET /bench/theme-match` renvoie, par listing,
la donnée + le label humain + les sorties étape par étape + les métriques
agrégées, plus le contexte des groupes (sœurs : thème, titres i18n,
alias). Le ré-étiquetage (POST) arrive au chunk 3.

Le replay est déterministe et hors quota — recalculé à chaque appel
(196 listings, instantané).
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from scripts.bench_theme_match import SEED_YEARS, replay_bench

router = APIRouter(prefix="/bench", tags=["bench"])

# Sidecar images du gold (cf. scripts/enrich_bench_images.py).
_IMAGES_PATH = (
    Path(__file__).resolve().parent.parent
    / "state" / "discovery_bench" / "gold_images.jsonl"
)


def _store():
    """Store partagé du process API (cf. sources_routes._store)."""
    from .server import _store as shared_store
    return shared_store


# ── Modèles de réponse ─────────────────────────────────────────────────────

class BenchGroupCoin(BaseModel):
    eurio_id: str
    theme: str | None
    i18n: dict[str, str]          # {lang: titre}
    aliases: list[str]            # alias normalisés (coin_aliases)
    obverse_url: str | None       # face de la pièce (URL publique Supabase)


class BenchReplayResponse(BaseModel):
    metrics: dict                 # agrégats (cf. replay_bench)
    listings: list[dict]          # une entrée par listing du gold
    groups: dict[str, list[BenchGroupCoin]]  # {année: [sœurs]}


# ── Contexte des groupes ───────────────────────────────────────────────────

def _obverse_url(raw_payload_json: str | None) -> str | None:
    """URL de la face (obverse) depuis `coins.raw_payload_json.images`.

    Legacy : marche pour le gold /bench (BE 2017-2021 importé avant V.1).
    Pour cohort 19 post-V.1, `raw_payload_json.images` est null —
    utilise plutôt `_canonical_obverse_url` (lit `coin_canonical_images`)."""
    if not raw_payload_json:
        return None
    try:
        payload = json.loads(raw_payload_json)
    except (json.JSONDecodeError, TypeError):
        return None
    return (payload.get("images") or {}).get("obverse")


def _canonical_obverse_url(
    conn: sqlite3.Connection, eurio_id: str,
) -> str | None:
    """URL servable de l'avers d'un coin via `coin_canonical_images`.

    Préfère l'URL Numista externe (chargeable directement par l'admin).
    Fallback : endpoint local ``/referential/canonical/{id}/obverse`` qui
    sert le WebP BCE quand l'externe manque."""
    row = conn.execute(
        """
        SELECT source, url, local_path FROM coin_canonical_images
         WHERE eurio_id = ? AND role = 'obverse'
         ORDER BY CASE source
                    WHEN 'numista_api'  THEN 1
                    WHEN 'bce_official' THEN 2
                    ELSE 9 END
         LIMIT 1
        """,
        (eurio_id,),
    ).fetchone()
    if row is None:
        return None
    if row["url"]:
        return row["url"]
    if row["local_path"]:
        return f"/referential/canonical/{eurio_id}/obverse?source={row['source']}"
    return None


def _groups_context(conn: sqlite3.Connection) -> dict[str, list[BenchGroupCoin]]:
    """Pour chaque année du gold, les commémos-sœurs avec leur thème,
    leurs titres i18n, leurs alias et la face de la pièce — le contexte
    de jugement du front."""
    out: dict[str, list[BenchGroupCoin]] = {}
    for year in SEED_YEARS:
        rows = conn.execute(
            "SELECT eurio_id, theme, raw_payload_json FROM coins WHERE "
            "country='BE' AND face_value=2.0 AND is_commemorative=1 "
            "AND year=? ORDER BY eurio_id",
            (year,),
        ).fetchall()
        coins: list[BenchGroupCoin] = []
        for r in rows:
            i18n = {
                lr["lang"]: lr["title"]
                for lr in conn.execute(
                    "SELECT lang, title FROM coin_names_i18n WHERE eurio_id=?",
                    (r["eurio_id"],),
                ).fetchall()
            }
            try:
                aliases = [
                    ar["alias"] for ar in conn.execute(
                        "SELECT alias FROM coin_aliases WHERE eurio_id=? "
                        "ORDER BY alias",
                        (r["eurio_id"],),
                    ).fetchall()
                ]
            except sqlite3.OperationalError:
                aliases = []
            coins.append(BenchGroupCoin(
                eurio_id=r["eurio_id"],
                theme=r["theme"],
                i18n=i18n,
                aliases=aliases,
                obverse_url=_obverse_url(r["raw_payload_json"]),
            ))
        out[str(year)] = coins
    return out


def _gold_image_urls() -> dict[str, str]:
    """{listing_id → image_url} depuis le sidecar gold_images.jsonl."""
    if not _IMAGES_PATH.exists():
        return {}
    out: dict[str, str] = {}
    for ln in _IMAGES_PATH.read_text().splitlines():
        if not ln.strip():
            continue
        rec = json.loads(ln)
        if rec.get("image_url"):
            out[rec["listing_id"]] = rec["image_url"]
    return out


# ── Endpoints ──────────────────────────────────────────────────────────────

# ── Run audit (P10-F, 2026-05-26) ─────────────────────────────────────────
#
# Audit live d'un run eBay (par opposition au gold replay historique
# de /bench/theme-match). Pas de scoring (pas de labels humains pour les
# runs courants) ; on renvoie l'état de chaque listing + le contexte du
# groupe cible, pour que Raphaël juge visuellement chaque décision du
# matcher. Utilise les champs route_decision/route_reason déjà persistés
# par le pipeline eBay.

class BenchRunListing(BaseModel):
    source_image_id: str
    listing_title: str | None
    listing_year: int | None
    listing_price: float | None
    listing_currency: str | None
    target_eurio_id: str | None
    route_decision: str | None
    route_reason: str | None
    is_lot_suspected: bool
    image_url: str | None
    source_url: str | None
    marketplace: str | None


class BenchRunGroupDrop(BaseModel):
    """Une étape de l'entonnoir où des listings se "perdent" — ce que
    l'admin clique pour drill par raison."""
    node_id: str            # slug cliquable, ex: 'matcher/unmatched', 'router/review_lot/is_lot_suspected'
    stage: str              # 'matcher' | 'router'
    label: str              # FR human-readable, ex: "Theme matcher — unmatched"
    reason: str | None      # route_reason raw
    route_decision: str | None  # filtre listings (combiné avec reason)
    count: int


class BenchRunGroup(BaseModel):
    group_id: str           # 'AT-2005-2.0'
    country: str
    year: int
    denomination: float
    target_eurio_ids: list[str]   # eurio_ids cible(s) du groupe (≥1)
    total_listings: int           # source_images du groupe (mailled par (country, year))
    n_unmatched: int              # target_eurio_id NULL
    n_pending: int                # route_decision='pending'
    n_review_single: int          # route_decision='review_single'
    n_review_lot: int             # route_decision='review_lot'
    n_auto: int                   # route_decision='auto_*' (0 pour V.3, prévu Phase F)
    n_quotes: int                 # coin_market_quotes générés pour ce groupe sur ce run
    drops: list[BenchRunGroupDrop]


class BenchRunSummary(BaseModel):
    run_id: str
    source: str
    started_at: str | None
    status: str
    total_listings: int
    total_unmatched: int
    total_pending: int
    total_review_single: int
    total_review_lot: int
    total_auto: int
    total_quotes: int
    n_groups: int


class BenchRunCoinContext(BaseModel):
    eurio_id: str
    display_name: str | None
    is_commemorative: bool
    country: str | None
    year: int | None
    theme: str | None
    obverse_url: str | None
    i18n: dict[str, str]
    topics: list[dict]                  # [{source, lang, topic}]
    aliases: list[str]


class BenchRunResponse(BaseModel):
    summary: BenchRunSummary
    groups: list[BenchRunGroup]                 # un par (country, year, denom)
    coins: dict[str, BenchRunCoinContext]       # eurio_id → contexte


class BenchRunListingsResponse(BaseModel):
    listings: list[BenchRunListing]
    listings_total: int


def _listing_image_url(raw_payload_json: str | None) -> str | None:
    """URL externe de la 1ère image du listing (i.ebayimg.com), depuis
    ``source_images.raw_payload_json.image_url`` posée à l'ingest eBay."""
    if not raw_payload_json:
        return None
    try:
        payload = json.loads(raw_payload_json)
    except (json.JSONDecodeError, TypeError):
        return None
    return payload.get("image_url")


_HUMAN_REASON: dict[str, str] = {
    "no_crops_yet": "pas encore croppé",
    "single_unmatched": "single sans match unique",
    "multi_coin_photo": "photo multi-pièces",
    "is_lot_suspected": "lot suspecté (titre)",
}


def _human_reason(reason: str | None) -> str:
    if not reason:
        return "(sans raison)"
    return _HUMAN_REASON.get(reason, reason)


def _run_groups(
    conn: sqlite3.Connection, run_id: str,
) -> tuple[list[BenchRunGroup], BenchRunSummary]:
    run_row = conn.execute(
        "SELECT id, source, started_at, status FROM source_runs WHERE id = ?",
        (run_id,),
    ).fetchone()
    if run_row is None:
        raise HTTPException(status_code=404, detail=f"run {run_id} not found")

    # Group key = (listing_country, listing_year) — la maille de la discovery
    # eBay (1 search par denom×country×year). On ne joint pas sur denomination
    # car cohorte 19 = 2€ partout ; on récupère la valeur depuis le 1er coin.
    group_rows = conn.execute(
        """
        SELECT listing_country AS country,
               listing_year    AS year,
               COUNT(*)        AS n_total,
               SUM(CASE WHEN target_eurio_id IS NULL THEN 1 ELSE 0 END) AS n_unmatched,
               SUM(CASE WHEN route_decision = 'pending' THEN 1 ELSE 0 END) AS n_pending,
               SUM(CASE WHEN route_decision = 'review_single' THEN 1 ELSE 0 END) AS n_review_single,
               SUM(CASE WHEN route_decision = 'review_lot' THEN 1 ELSE 0 END) AS n_review_lot,
               SUM(CASE WHEN route_decision LIKE 'auto%' THEN 1 ELSE 0 END) AS n_auto
          FROM source_images
         WHERE run_id = ?
           AND listing_country IS NOT NULL
           AND listing_year IS NOT NULL
         GROUP BY listing_country, listing_year
         ORDER BY listing_country, listing_year
        """,
        (run_id,),
    ).fetchall()

    groups: list[BenchRunGroup] = []
    for gr in group_rows:
        country = gr["country"]
        year = gr["year"]

        # eurio_ids cibles : tous les coins du référentiel sur (country, year)
        # pour ce denom. On suppose denom = 2.0 (cohorte V.3), on filtre les
        # commémos sinon on ramasse aussi les standards qui ne sont pas
        # cherchés dans ce run.
        eurio_rows = conn.execute(
            """
            SELECT DISTINCT target_eurio_id FROM source_images
             WHERE run_id = ? AND listing_country = ? AND listing_year = ?
               AND target_eurio_id IS NOT NULL
             ORDER BY target_eurio_id
            """,
            (run_id, country, year),
        ).fetchall()
        target_eurio_ids = [r["target_eurio_id"] for r in eurio_rows]

        # Drops : groupés par (route_decision, route_reason)
        drop_rows = conn.execute(
            """
            SELECT route_decision, route_reason, COUNT(*) AS n
              FROM source_images
             WHERE run_id = ? AND listing_country = ? AND listing_year = ?
               AND route_decision IS NOT NULL
             GROUP BY route_decision, route_reason
             ORDER BY route_decision, route_reason
            """,
            (run_id, country, year),
        ).fetchall()
        drops = [
            BenchRunGroupDrop(
                node_id=f"{r['route_decision']}/{r['route_reason'] or 'none'}",
                stage="matcher" if r["route_decision"] == "pending" else "router",
                label=f"{r['route_decision']} — {_human_reason(r['route_reason'])}",
                reason=r["route_reason"],
                route_decision=r["route_decision"],
                count=r["n"],
            )
            for r in drop_rows
        ]
        # Append "unmatched" bucket if any (target_eurio_id NULL means matcher
        # dropped the listing before routing decided).
        n_unmatched = gr["n_unmatched"] or 0
        if n_unmatched:
            drops.insert(0, BenchRunGroupDrop(
                node_id="matcher/unmatched",
                stage="matcher",
                label=f"theme-matcher — unmatched (target NULL)",
                reason="unmatched",
                route_decision=None,
                count=n_unmatched,
            ))

        # n_quotes : market_quotes générés sur ce run pour les eurio_ids du
        # groupe.
        if target_eurio_ids:
            placeholders = ",".join("?" * len(target_eurio_ids))
            n_quotes = conn.execute(
                f"SELECT COUNT(*) FROM coin_market_quotes "
                f"WHERE run_id = ? AND eurio_id IN ({placeholders})",
                [run_id, *target_eurio_ids],
            ).fetchone()[0]
        else:
            n_quotes = 0

        # Denomination depuis le 1er coin résolu ; fallback 2.0
        denom = 2.0
        if target_eurio_ids:
            row = conn.execute(
                "SELECT face_value FROM coins WHERE eurio_id = ?",
                (target_eurio_ids[0],),
            ).fetchone()
            if row and row["face_value"]:
                denom = float(row["face_value"])

        groups.append(BenchRunGroup(
            group_id=f"{country}-{year}-{denom}",
            country=country,
            year=year,
            denomination=denom,
            target_eurio_ids=target_eurio_ids,
            total_listings=gr["n_total"],
            n_unmatched=n_unmatched,
            n_pending=gr["n_pending"] or 0,
            n_review_single=gr["n_review_single"] or 0,
            n_review_lot=gr["n_review_lot"] or 0,
            n_auto=gr["n_auto"] or 0,
            n_quotes=n_quotes,
            drops=drops,
        ))

    summary = BenchRunSummary(
        run_id=run_row["id"],
        source=run_row["source"],
        started_at=run_row["started_at"],
        status=run_row["status"],
        total_listings=sum(g.total_listings for g in groups),
        total_unmatched=sum(g.n_unmatched for g in groups),
        total_pending=sum(g.n_pending for g in groups),
        total_review_single=sum(g.n_review_single for g in groups),
        total_review_lot=sum(g.n_review_lot for g in groups),
        total_auto=sum(g.n_auto for g in groups),
        total_quotes=sum(g.n_quotes for g in groups),
        n_groups=len(groups),
    )
    return groups, summary


def _run_listings(
    conn: sqlite3.Connection,
    run_id: str,
    *,
    country: str | None,
    year: int | None,
    eurio_id: str | None,
    route_decision: str | None,
    route_reason: str | None,
    unmatched_only: bool,
    limit: int,
    offset: int,
) -> tuple[list[BenchRunListing], int]:
    where = ["run_id = ?"]
    params: list = [run_id]
    if country:
        where.append("listing_country = ?")
        params.append(country)
    if year is not None:
        where.append("listing_year = ?")
        params.append(year)
    if unmatched_only:
        where.append("target_eurio_id IS NULL")
    elif eurio_id:
        where.append("target_eurio_id = ?")
        params.append(eurio_id)
    if route_decision:
        where.append("route_decision = ?")
        params.append(route_decision)
    if route_reason:
        where.append("route_reason = ?")
        params.append(route_reason)

    where_sql = " AND ".join(where)
    total = conn.execute(
        f"SELECT COUNT(*) FROM source_images WHERE {where_sql}", params,
    ).fetchone()[0]

    rows = conn.execute(
        f"""
        SELECT id, source, listing_title, listing_year, listing_price,
               listing_currency, target_eurio_id, route_decision,
               route_reason, is_lot_suspected, source_url, marketplace,
               raw_payload_json
          FROM source_images
         WHERE {where_sql}
         ORDER BY target_eurio_id NULLS LAST, route_decision, id
         LIMIT ? OFFSET ?
        """,
        [*params, limit, offset],
    ).fetchall()
    listings = [
        BenchRunListing(
            source_image_id=r["id"],
            listing_title=r["listing_title"],
            listing_year=r["listing_year"],
            listing_price=r["listing_price"],
            listing_currency=r["listing_currency"],
            target_eurio_id=r["target_eurio_id"],
            route_decision=r["route_decision"],
            route_reason=r["route_reason"],
            is_lot_suspected=bool(r["is_lot_suspected"] or 0),
            image_url=_listing_image_url(r["raw_payload_json"]),
            source_url=r["source_url"],
            marketplace=r["marketplace"],
        )
        for r in rows
    ]
    return listings, total


def _coin_context(
    conn: sqlite3.Connection, eurio_id: str,
) -> BenchRunCoinContext | None:
    coin = conn.execute(
        "SELECT eurio_id, theme, is_commemorative, country, year, raw_payload_json "
        "FROM coins WHERE eurio_id = ?", (eurio_id,),
    ).fetchone()
    if coin is None:
        return None

    i18n = {
        r["lang"]: r["title"]
        for r in conn.execute(
            "SELECT lang, title FROM coin_names_i18n WHERE eurio_id = ?",
            (eurio_id,),
        ).fetchall()
    }
    aliases = [
        r["alias"] for r in conn.execute(
            "SELECT alias FROM coin_aliases WHERE eurio_id = ? ORDER BY alias",
            (eurio_id,),
        ).fetchall()
    ]
    topics = [
        {"source": r["source"], "lang": r["lang"], "topic": r["topic"]}
        for r in conn.execute(
            "SELECT source, lang, topic FROM coin_topics WHERE eurio_id = ? "
            "ORDER BY source, lang",
            (eurio_id,),
        ).fetchall()
    ]

    display_name = None
    fr_topic = next(
        (t["topic"] for t in topics
         if t["source"] == "numista_api" and t["lang"] == "fr"), None,
    )
    if coin["is_commemorative"] and fr_topic:
        display_name = fr_topic
    elif coin["theme"]:
        display_name = coin["theme"]

    return BenchRunCoinContext(
        eurio_id=eurio_id,
        display_name=display_name,
        is_commemorative=bool(coin["is_commemorative"]),
        country=coin["country"],
        year=coin["year"],
        theme=coin["theme"],
        obverse_url=_canonical_obverse_url(conn, eurio_id),
        i18n=i18n,
        topics=topics,
        aliases=aliases,
    )


# Consumed by: admin/.../features/bench (run audit tab)
@router.get("/runs/{run_id}", response_model=BenchRunResponse)
def get_bench_run(run_id: str) -> BenchRunResponse:
    """Audit live d'un run eBay : groups (= discovery searches) + métriques
    + contexte des coins. Pas de listings (cf. ``/bench/runs/{run_id}/listings``
    pour drill par groupe/nœud)."""
    conn = _store()._connection()  # noqa: SLF001
    groups, summary = _run_groups(conn, run_id)

    # Contexte des coins de tous les groupes (dedup via dict).
    coins: dict[str, BenchRunCoinContext] = {}
    for g in groups:
        for eid in g.target_eurio_ids:
            if eid in coins:
                continue
            ctx = _coin_context(conn, eid)
            if ctx is not None:
                coins[eid] = ctx

    return BenchRunResponse(summary=summary, groups=groups, coins=coins)


# Consumed by: admin/.../features/bench (drill panel)
@router.get("/runs/{run_id}/listings", response_model=BenchRunListingsResponse)
def get_bench_run_listings(
    run_id: str,
    country: str | None = Query(None),
    year: int | None = Query(None),
    eurio_id: str | None = Query(None),
    route_decision: str | None = Query(None),
    route_reason: str | None = Query(None),
    unmatched_only: bool = Query(False),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
) -> BenchRunListingsResponse:
    """Listings d'un nœud de l'entonnoir, filtré côté serveur."""
    conn = _store()._connection()  # noqa: SLF001
    listings, total = _run_listings(
        conn, run_id,
        country=country, year=year, eurio_id=eurio_id,
        route_decision=route_decision, route_reason=route_reason,
        unmatched_only=unmatched_only,
        limit=limit, offset=offset,
    )
    return BenchRunListingsResponse(listings=listings, listings_total=total)


# Consumed by: admin/.../features/bench
@router.get("/theme-match", response_model=BenchReplayResponse)
def get_theme_match_bench() -> BenchReplayResponse:
    """Rejoue le gold gelé et renvoie le détail par listing + métriques."""
    conn = _store()._connection()  # noqa: SLF001
    try:
        result = replay_bench(conn)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    images = _gold_image_urls()
    for ls in result["listings"]:
        ls["image_url"] = images.get(ls["listing_id"])
    return BenchReplayResponse(
        metrics=result["metrics"],
        listings=result["listings"],
        groups=_groups_context(conn),
    )
