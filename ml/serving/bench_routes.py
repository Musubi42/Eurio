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
import logging
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

from serving._coin_helpers import canonical_obverse_url
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
    """Délègue au helper partagé (cf. ``api._coin_helpers``)."""
    return canonical_obverse_url(conn, eurio_id)


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
    # Raison du NON-match auto, dérivée des text_signals (chantier lisibilité
    # matcher). None quand l'annonce est attribuée (target_eurio_id non NULL).
    # Le matcher ne persiste pas son verdict ; on le RECONSTRUIT depuis les
    # signaux extraits (denoms multiples, tokens set/coffret/« au choix », lot).
    match_reason: str | None = None


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
    group_id: str           # 'AT-2005-2.0' ; 'AD-std-2.0' pour un standard
    country: str
    year: int | None        # NULL = groupe standard (recherche sans millésime)
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
    "all_crops_rejected": "tous les crops rejetés",
    "face_reverse": "revers commun 2€",
    "not_2eur": "pas un 2€ (cent/médaille/mire)",
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
    # eBay (1 search par denom×country×année). Les **standards** ont
    # ``listing_year = NULL`` (le design couvre toutes les années, recherche
    # large sans millésime) → on NE filtre PAS sur year, sinon un run 100 %
    # standard remonte 0 groupe (bench vide). GROUP BY met les NULL dans leur
    # propre seau. On ne joint pas sur denomination (cohorte = 2€ partout).
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
         GROUP BY listing_country, listing_year
         ORDER BY listing_country, listing_year
        """,
        (run_id,),
    ).fetchall()

    groups: list[BenchRunGroup] = []
    for gr in group_rows:
        country = gr["country"]
        year = gr["year"]
        # ``listing_year = ?`` ne matche jamais une valeur NULL (sémantique SQL)
        # → pour les groupes standard (year NULL) on bascule sur ``IS NULL``,
        # sinon les sous-requêtes ci-dessous renverraient 0 (cibles/drops vides).
        if year is None:
            year_sql, year_args = "listing_year IS NULL", []
        else:
            year_sql, year_args = "listing_year = ?", [year]

        # eurio_ids cibles : tous les coins du référentiel sur (country, year)
        # pour ce denom. On suppose denom = 2.0 (cohorte V.3), on filtre les
        # commémos sinon on ramasse aussi les standards qui ne sont pas
        # cherchés dans ce run.
        eurio_rows = conn.execute(
            f"""
            SELECT DISTINCT target_eurio_id FROM source_images
             WHERE run_id = ? AND listing_country = ? AND {year_sql}
               AND target_eurio_id IS NOT NULL
             ORDER BY target_eurio_id
            """,
            (run_id, country, *year_args),
        ).fetchall()
        target_eurio_ids = [r["target_eurio_id"] for r in eurio_rows]

        # Drops : groupés par (route_decision, route_reason)
        drop_rows = conn.execute(
            f"""
            SELECT route_decision, route_reason, COUNT(*) AS n
              FROM source_images
             WHERE run_id = ? AND listing_country = ? AND {year_sql}
               AND route_decision IS NOT NULL
             GROUP BY route_decision, route_reason
             ORDER BY route_decision, route_reason
            """,
            (run_id, country, *year_args),
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
            group_id=f"{country}-{year if year is not None else 'std'}-{denom}",
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


# Tokens (normalisés sans accents par l'extracteur) qui signalent un objet
# NON-attribuable à une pièce isolée → cause récurrente du verdict ambiguous.
_SET_TOKENS = {
    "kursmunzensatz", "kms", "munzset", "satz", "sammlerbox", "coincard",
    "coincards", "coffret", "set", "blister", "etui",
}
_CHOICE_TOKENS = {
    "wahlen", "zwischen", "unter", "auswahl", "auswahlen",
    "elige", "elegir", "choisir", "select", "scegli",
}


def _derive_match_reason(
    *,
    target_eurio_id: str | None,
    theme_tokens: list[str],
    denoms: list[float],
    is_lot: bool,
    is_lot_suspected: bool,
    rejected_markers: list[str],
) -> str | None:
    """Reconstruit la cause probable du non-match depuis les text_signals.

    Le theme-matcher ne persiste pas son verdict (single/ambiguous/lot) ; on
    le ré-explique a posteriori. None si l'annonce EST attribuée (rien à dire).
    Heuristique transparente — pas la vérité du matcher, mais l'évidence
    textuelle qui a vraisemblablement empêché de trancher UNE pièce.
    """
    if target_eurio_id:
        return None
    toks = set(theme_tokens or [])
    if rejected_markers:
        return f"Marqueur de rejet : {', '.join(rejected_markers[:3])}"
    if toks & _SET_TOKENS:
        return "Set / coffret — plusieurs pièces, ère indéterminable"
    if toks & _CHOICE_TOKENS:
        return "Annonce « au choix » — plusieurs pièces / années"
    if is_lot or is_lot_suspected:
        return "Lot suspecté — plusieurs pièces"
    if denoms and len(denoms) > 1:
        return "Plusieurs valeurs faciales — pas une pièce isolée"
    return "Ambigu — plusieurs ères possibles (le matcher n'a pas tranché)"


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

    # Signaux texte pour la page courante uniquement (batch) — sert à
    # reconstruire la raison du non-match des annonces sans target.
    sig_map: dict[str, sqlite3.Row] = {}
    ids = [r["id"] for r in rows]
    if ids:
        ph = ",".join("?" * len(ids))
        for s in conn.execute(
            f"""
            SELECT source_image_id, denominations_json, theme_tokens_json,
                   is_lot, rejected_markers_json
              FROM listing_text_signals
             WHERE source_image_id IN ({ph})
            """,
            ids,
        ).fetchall():
            sig_map[s["source_image_id"]] = s

    def _reason(r: sqlite3.Row) -> str | None:
        if r["target_eurio_id"]:
            return None
        sig = sig_map.get(r["id"])
        if sig is None:
            return "Non auto-attribuée (pas de signal texte)"
        return _derive_match_reason(
            target_eurio_id=None,
            theme_tokens=json.loads(sig["theme_tokens_json"] or "[]"),
            denoms=json.loads(sig["denominations_json"] or "[]"),
            is_lot=bool(sig["is_lot"] or 0),
            is_lot_suspected=bool(r["is_lot_suspected"] or 0),
            rejected_markers=json.loads(sig["rejected_markers_json"] or "[]"),
        )

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
            match_reason=_reason(r),
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


# ── Run audit — CROP FORENSICS (P10-G, 2026-05-26) ────────────────────────
#
# Variante "crop" du run audit : au lieu d'auditer les décisions du
# theme-matcher (route_decision/route_reason sur les listings), on audit
# le **résultat du crop** (YOLO+Hough+polish) sur chaque image_asset
# produit pendant le run.
#
# Pas de notion d'eurio_id résolu ici : la majorité des image_assets d'un
# run eBay sont en `pending_match`. L'axe d'entrée est le raw eBay + sa
# bbox, pour que l'admin repère visuellement les undercrops (bug bimétal :
# Hough vote le cercle intérieur or au lieu du rim extérieur silver).

# Seuil par défaut undercrop : aire bbox / min(raw_w, raw_h)² < seuil.
#
# LIMITE CONNUE (sondage 2026-05-26 sur run 059dc8d9, 1 678 crops eBay) :
# à 0.50 → 99 % flag, à 0.05 → 49 %, à 0.03 → 14 %. La distribution est
# graduelle SANS palier méthode-spécifique — area_ratio ne distingue pas
# un vrai undercrop bimétal (Hough qui vote l'inner ring) d'un crop OK
# sur une photo eBay cadrée large (pièce légitimement petite dans le
# cadre). Pour le vrai signal bimétal, il faut un oracle indépendant
# (Otsu+contour, cf. scripts/bench_listing_bimetal.py), à brancher dans
# un chunk dédié. En attendant, 0.10 donne un compromis utile : on flag
# les pièces qui occupent < ~10 % de l'inscription max, ce qui couvre
# les bimétal sévères + une partie du bruit. Toujours surridable côté
# query via `?undercrop_threshold=X`.
UNDERCROP_AREA_RATIO_DEFAULT = 0.10

_QUALITY_BUCKETS: list[tuple[str, float, float]] = [
    (".0–.2", 0.0, 0.2),
    (".2–.4", 0.2, 0.4),
    (".4–.6", 0.4, 0.6),
    (".6–.8", 0.6, 0.8),
    (".8–1.", 0.8, 1.0001),
]


class BenchRunCropBbox(BaseModel):
    x: float
    y: float
    w: float
    h: float
    conf: float | None = None


class BenchRunCropBboxPct(BaseModel):
    """Bbox normalisée en % du raw (0..100), prête pour overlay CSS.

    Calculée côté serveur dès qu'on a `source_images.width/height` et que
    les valeurs de `bbox_json` ressemblent à des pixels (max(x+w, y+h) >
    raw_dims*1.01 → skipped). Si l'amont passe déjà du normalisé 0..1, on
    le détecte aussi (max ≤ 1.0).
    """
    x: float
    y: float
    w: float
    h: float


class BenchRunCropCard(BaseModel):
    asset_id: str
    source: str
    source_image_id: str
    crop_index: int
    raw_url: str | None              # /sources/{source}/raws/{source_image_id}/file
    crop_url: str | None             # /sources/{source}/assets/{asset_id}/file
    raw_width: int | None
    raw_height: int | None
    crop_width: int | None
    crop_height: int | None
    bbox: BenchRunCropBbox | None
    bbox_pct: BenchRunCropBboxPct | None
    detection_method: str | None
    resolution_status: str | None
    quality_score: float | None
    is_undercrop_suspect: bool
    area_ratio: float | None         # aire bbox / min(raw_w,raw_h)² (debug)
    target_eurio_id: str | None      # eurio_id visé par le listing (pas vérité)
    listing_title: str | None
    listing_country: str | None
    listing_year: int | None
    listing_url: str | None
    fetched_at: str | None
    composite_score: float | None    # score is_coin de crop_exp/score_crops (sidecar)
    # Chantier crop-quality-overhaul — inclinaison mesurée via measure_tilt.
    tilt_deg: float | None           # angle estimé [0–90°], None si backfill absent
    axis_ratio: float | None         # minor/major — 1.0 = cercle parfait
    tilt_trustworthy: bool | None    # True si les 3 critères (center_drift/r_ratio/arc_cov) OK


class BenchRunCropsMethodBucket(BaseModel):
    method: str                      # 'yolo'|'hough'|'merged'|'manual'|'unknown'
    n: int
    n_undercrops: int
    pct: float                       # 0..100 (part du total crops)


class BenchRunCropsQualityBucket(BaseModel):
    label: str                       # '.0–.2'
    range_lo: float
    range_hi: float
    n: int


class BenchRunCropsStatusBucket(BaseModel):
    status: str
    n: int


class BenchRunCropsDiagnostic(BaseModel):
    """Pépite humaine au-dessus de l'analytics. None si rien à dire."""
    top_method_in_undercrops: str | None
    top_method_share: float | None        # 0..1 — part des undercrops portée par cette méthode
    note: str | None                      # phrase FR pour le bloc Diagnostic


class BenchRunCropsGroupSummary(BaseModel):
    """Une recherche eBay (groupe de découverte), version crop."""
    group_id: str                    # 'DE-2007-2.0'
    country: str | None
    year: int | None
    denomination: float | None
    n_raws: int
    n_crops: int
    n_undercrops: int


class BenchRunCropsSummary(BaseModel):
    run_id: str
    n_groups: int
    n_raws: int
    n_crops: int
    n_undercrops: int
    pct_undercrops: float            # 0..100
    quality_mean: float | None
    quality_median: float | None
    quality_std: float | None
    methods: list[BenchRunCropsMethodBucket]
    quality_histogram: list[BenchRunCropsQualityBucket]
    statuses: list[BenchRunCropsStatusBucket]
    diagnostic: BenchRunCropsDiagnostic
    # paramètre utilisé pour calculer is_undercrop_suspect (debug, replay)
    undercrop_threshold: float


class BenchRunCropsResponse(BaseModel):
    summary: BenchRunCropsSummary
    groups: list[BenchRunCropsGroupSummary]
    cards: list[BenchRunCropCard]
    cards_total: int                 # après filtres, avant pagination


def _parse_bbox(bbox_json: str | None) -> BenchRunCropBbox | None:
    if not bbox_json:
        return None
    try:
        d = json.loads(bbox_json)
    except (json.JSONDecodeError, TypeError):
        return None
    if not isinstance(d, dict):
        return None
    try:
        return BenchRunCropBbox(
            x=float(d.get("x", 0)),
            y=float(d.get("y", 0)),
            w=float(d.get("w", 0)),
            h=float(d.get("h", 0)),
            conf=float(d["conf"]) if d.get("conf") is not None else None,
        )
    except (TypeError, ValueError):
        return None


def _bbox_pct_and_ratio(
    bbox: BenchRunCropBbox | None,
    raw_w: int | None,
    raw_h: int | None,
) -> tuple[BenchRunCropBboxPct | None, float | None]:
    """Convertit la bbox en % du raw + calcule l'aire ratio bbox / min(raw)².

    Accepte les bbox pixels ou déjà normalisées (0..1). Si raw_w/h manquent
    ou que la bbox ne fait pas sens (négative, hors-cadre), renvoie None,
    None — la carte sera affichée sans overlay côté front.
    """
    if bbox is None or not raw_w or not raw_h:
        return None, None
    if bbox.w <= 0 or bbox.h <= 0:
        return None, None

    # Détecte le format : si max coord ≤ 1.01, on est en normalisé [0,1].
    max_coord = max(bbox.x + bbox.w, bbox.y + bbox.h)
    if max_coord <= 1.01:
        px_x, px_y, px_w, px_h = (bbox.x * raw_w, bbox.y * raw_h,
                                  bbox.w * raw_w, bbox.h * raw_h)
    else:
        px_x, px_y, px_w, px_h = bbox.x, bbox.y, bbox.w, bbox.h

    # bbox hors-cadre franchement → pas de pct
    if px_x < -1 or px_y < -1 or px_x + px_w > raw_w + 1 or px_y + px_h > raw_h + 1:
        return None, None

    bbox_pct = BenchRunCropBboxPct(
        x=max(0.0, px_x / raw_w * 100.0),
        y=max(0.0, px_y / raw_h * 100.0),
        w=min(100.0, px_w / raw_w * 100.0),
        h=min(100.0, px_h / raw_h * 100.0),
    )
    ref = float(min(raw_w, raw_h))
    area_ratio = (px_w * px_h) / (ref * ref) if ref > 0 else None
    return bbox_pct, area_ratio


def _median(values: list[float]) -> float | None:
    if not values:
        return None
    s = sorted(values)
    n = len(s)
    mid = n // 2
    if n % 2 == 1:
        return float(s[mid])
    return float((s[mid - 1] + s[mid]) / 2)


def _stdev(values: list[float], mean: float) -> float | None:
    if len(values) < 2:
        return None
    var = sum((v - mean) ** 2 for v in values) / (len(values) - 1)
    return float(var ** 0.5)


def _build_diagnostic(
    methods: list[BenchRunCropsMethodBucket],
    n_undercrops: int,
) -> BenchRunCropsDiagnostic:
    """Cherche la méthode qui concentre le plus d'undercrops. Si une seule
    méthode pèse ≥ 50 % des undercrops ET a un taux undercrop > 30 % de
    ses propres crops, on émet une note."""
    if n_undercrops < 5:
        return BenchRunCropsDiagnostic(
            top_method_in_undercrops=None, top_method_share=None, note=None,
        )
    by_share = sorted(methods, key=lambda m: m.n_undercrops, reverse=True)
    top = by_share[0] if by_share else None
    if top is None or top.n_undercrops == 0:
        return BenchRunCropsDiagnostic(
            top_method_in_undercrops=None, top_method_share=None, note=None,
        )
    share = top.n_undercrops / n_undercrops
    own_rate = top.n_undercrops / top.n if top.n else 0
    if share >= 0.50 and own_rate >= 0.30:
        note = (
            f"{top.method} concentre {round(share * 100)} % des undercrops "
            f"({top.n_undercrops}/{n_undercrops}) avec un taux interne de "
            f"{round(own_rate * 100)} %. Probable bug bimétal — vote du "
            f"cercle intérieur or au lieu du rim silver."
        )
    else:
        note = None
    return BenchRunCropsDiagnostic(
        top_method_in_undercrops=top.method,
        top_method_share=share,
        note=note,
    )


def _group_id(country: str | None, year: int | None, denom: float | None) -> str:
    parts = [
        country or "?",
        str(year) if year is not None else "?",
        f"{denom:.1f}" if denom is not None else "?",
    ]
    return "-".join(parts)


# Consumed by: admin/.../features/bench (Crop mode of BenchRunAuditPage)
# Sidecar composite scores (crop_exp/score_crops.py) — cache mémoire par run_id.
# Le fichier est petit (~1k records) et change rarement (re-généré sur demande).
_CROP_SCORES_CACHE: dict[str, dict[str, float]] = {}


def _load_composite_scores(run_id: str) -> dict[str, float]:
    """``{asset_id → composite}`` depuis le sidecar JSON, ou ``{}`` si absent.

    Cache en mémoire pour éviter de relire le fichier à chaque request.
    Invalidé en redémarrant l'API (run_id-spécifique, pas global)."""
    if run_id in _CROP_SCORES_CACHE:
        return _CROP_SCORES_CACHE[run_id]
    sidecar = (
        Path(__file__).resolve().parents[1]
        / "state" / "crop_scores" / f"{run_id}.json"
    )
    out: dict[str, float] = {}
    if sidecar.exists():
        try:
            data = json.loads(sidecar.read_text())
            for rec in data:
                aid = rec.get("asset_id")
                comp = rec.get("composite")
                if aid and comp is not None:
                    out[aid] = float(comp)
        except (json.JSONDecodeError, OSError):
            pass
    _CROP_SCORES_CACHE[run_id] = out
    return out


@router.get("/runs/{run_id}/crops", response_model=BenchRunCropsResponse)
def get_bench_run_crops(
    run_id: str,
    country: str | None = Query(None),
    year: int | None = Query(None),
    eurio_id: str | None = Query(
        None, description="filtre source_images.target_eurio_id (coin attribué)"
    ),
    method: str | None = Query(None, description="yolo|hough|merged|manual"),
    status: str | None = Query(None, description="resolution_status filter"),
    route_reason: str | None = Query(
        None,
        description="filtre source_images.route_reason du listing parent — "
                    "buckets crop-level du funnel (not_2eur, face_reverse, …) "
                    "où la photo brute du lot ne montre rien d'utile",
    ),
    quality_min: float | None = Query(None, ge=0, le=1),
    quality_max: float | None = Query(None, ge=0, le=1),
    undercrop_only: bool = Query(False),
    tilt_min: float | None = Query(
        None, ge=0, le=90,
        description="Filtre : tilt_deg >= tilt_min ET tilt_trustworthy=1 (ne garde que les pièces inclinées fiables).",
    ),
    sort: str = Query("score_desc",
                      pattern="^(score_desc|score_asc|undercrop_first|quality_asc|quality_desc|recent|tilt_desc)$"),
    undercrop_threshold: float = Query(UNDERCROP_AREA_RATIO_DEFAULT, ge=0, le=1),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
) -> BenchRunCropsResponse:
    """Crops produits durant un run eBay, avec analytics + cartes paginées.

    Le calcul d'undercrop est fait en Python (post-query) car il dépend de
    la geometry bbox/raw qui n'est pas indexable utilement. Pour un run
    eBay typique (~quelques milliers de crops max), c'est négligeable.
    """
    conn = _store()._connection()  # noqa: SLF001

    # 1. Vérifier que le run existe (404 propre si pas).
    run_row = conn.execute(
        "SELECT id, source FROM source_runs WHERE id = ?", (run_id,),
    ).fetchone()
    if run_row is None:
        raise HTTPException(status_code=404, detail=f"Run {run_id} not found.")
    run_source = run_row["source"]

    composite_scores = _load_composite_scores(run_id)

    # 2. Charger tous les image_assets du run + métadonnées raw associées.
    #    Filtres SQL "cheap" appliqués ici (country/year/method/status/quality).
    #    L'undercrop_only et le sort sont appliqués après calcul Python.
    where = ["a.run_id = ?"]
    params: list = [run_id]
    if country:
        where.append("s.listing_country = ?")
        params.append(country)
    if year is not None:
        where.append("s.listing_year = ?")
        params.append(year)
    if eurio_id:
        # Coin attribué (theme-match tranché). Discrimine une commémo précise au
        # sein d'un groupe (country, year) — les sœurs partagent la maille du
        # bench. Indépendant de listing_year (NULL pour les standards).
        where.append("s.target_eurio_id = ?")
        params.append(eurio_id)
    if method:
        where.append("a.detection_method = ?")
        params.append(method)
    if status:
        where.append("a.resolution_status = ?")
        params.append(status)
    if route_reason:
        # Filtre sur le listing parent (cohérent avec les buckets du funnel,
        # construits depuis source_images.route_decision/route_reason).
        where.append("s.route_reason = ?")
        params.append(route_reason)
    if quality_min is not None:
        where.append("(a.quality_score IS NOT NULL AND a.quality_score >= ?)")
        params.append(quality_min)
    if quality_max is not None:
        where.append("(a.quality_score IS NOT NULL AND a.quality_score <= ?)")
        params.append(quality_max)
    if tilt_min is not None:
        # Filtre SQL direct (colonne indexable) : ne retourne que les assets
        # dont l'inclinaison est mesurée, fiable, et au-dessus du seuil.
        where.append("(a.tilt_deg IS NOT NULL AND a.tilt_deg >= ? AND a.tilt_trustworthy = 1)")
        params.append(tilt_min)
    where_sql = " AND ".join(where)

    rows = conn.execute(
        f"""
        SELECT
            a.id              AS asset_id,
            a.source_image_id AS source_image_id,
            a.crop_index      AS crop_index,
            a.bbox_json       AS bbox_json,
            a.detection_method AS detection_method,
            a.resolution_status AS resolution_status,
            a.quality_score   AS quality_score,
            a.width           AS crop_width,
            a.height          AS crop_height,
            a.fetched_at      AS fetched_at,
            a.tilt_deg        AS tilt_deg,
            a.axis_ratio      AS axis_ratio,
            a.tilt_trustworthy AS tilt_trustworthy,
            s.source          AS source,
            s.source_url      AS listing_url,
            s.target_eurio_id AS target_eurio_id,
            s.listing_title   AS listing_title,
            s.listing_country AS listing_country,
            s.listing_year    AS listing_year,
            s.width           AS raw_width,
            s.height          AS raw_height
          FROM image_assets a
          JOIN source_images s ON s.id = a.source_image_id
         WHERE {where_sql}
        """,
        params,
    ).fetchall()

    # 3. Construire les cartes (avec undercrop) et alimenter les agrégats.
    cards: list[BenchRunCropCard] = []
    method_counts: dict[str, int] = {}
    method_undercrops: dict[str, int] = {}
    status_counts: dict[str, int] = {}
    quality_bucket_counts: list[int] = [0] * len(_QUALITY_BUCKETS)
    group_raws: dict[str, set[str]] = {}        # group_id → set(source_image_id)
    group_crops: dict[str, int] = {}
    group_undercrops: dict[str, int] = {}
    group_meta: dict[str, tuple[str | None, int | None, float | None]] = {}
    quality_values: list[float] = []
    n_undercrops_total = 0
    raw_ids_total: set[str] = set()

    for r in rows:
        bbox = _parse_bbox(r["bbox_json"])
        bbox_pct, area_ratio = _bbox_pct_and_ratio(
            bbox, r["raw_width"], r["raw_height"],
        )
        is_undercrop = (
            area_ratio is not None and area_ratio < undercrop_threshold
        )

        # Group bookkeeping. eBay groupe = (country, year). Denom dérivée
        # si dispo (P10-F passe par listing meta) — pour le run audit
        # crop on assume 2 € sur les recherches "année + pays + 2€"
        # mais on garde None si pas inférable.
        gid = _group_id(r["listing_country"], r["listing_year"], 2.0
                         if r["listing_country"] else None)
        group_meta.setdefault(gid, (r["listing_country"], r["listing_year"], 2.0))
        group_raws.setdefault(gid, set()).add(r["source_image_id"])
        group_crops[gid] = group_crops.get(gid, 0) + 1
        if is_undercrop:
            group_undercrops[gid] = group_undercrops.get(gid, 0) + 1
            n_undercrops_total += 1

        raw_ids_total.add(r["source_image_id"])

        m = r["detection_method"] or "unknown"
        method_counts[m] = method_counts.get(m, 0) + 1
        if is_undercrop:
            method_undercrops[m] = method_undercrops.get(m, 0) + 1

        st = r["resolution_status"] or "unknown"
        status_counts[st] = status_counts.get(st, 0) + 1

        q = r["quality_score"]
        if q is not None:
            quality_values.append(float(q))
            for i, (_, lo, hi) in enumerate(_QUALITY_BUCKETS):
                if lo <= q < hi:
                    quality_bucket_counts[i] += 1
                    break

        raw_url = (
            f"/sources/{r['source']}/raws/{r['source_image_id']}/file"
            if r["source"] and r["source_image_id"] else None
        )
        crop_url = (
            f"/sources/{r['source']}/assets/{r['asset_id']}/file"
            if r["source"] and r["asset_id"] else None
        )

        cards.append(BenchRunCropCard(
            asset_id=r["asset_id"],
            source=r["source"],
            source_image_id=r["source_image_id"],
            crop_index=int(r["crop_index"] or 0),
            raw_url=raw_url,
            crop_url=crop_url,
            raw_width=r["raw_width"],
            raw_height=r["raw_height"],
            crop_width=r["crop_width"],
            crop_height=r["crop_height"],
            bbox=bbox,
            bbox_pct=bbox_pct,
            detection_method=r["detection_method"],
            resolution_status=r["resolution_status"],
            quality_score=float(q) if q is not None else None,
            is_undercrop_suspect=is_undercrop,
            area_ratio=area_ratio,
            target_eurio_id=r["target_eurio_id"],
            listing_title=r["listing_title"],
            listing_country=r["listing_country"],
            listing_year=r["listing_year"],
            listing_url=r["listing_url"],
            fetched_at=r["fetched_at"],
            composite_score=composite_scores.get(r["asset_id"]),
            tilt_deg=r["tilt_deg"],
            axis_ratio=r["axis_ratio"],
            tilt_trustworthy=(
                bool(r["tilt_trustworthy"]) if r["tilt_trustworthy"] is not None else None
            ),
        ))

    # 4. Aggregats globaux.
    n_crops = len(cards)
    n_raws = len(raw_ids_total)

    method_buckets: list[BenchRunCropsMethodBucket] = []
    for m_name, m_n in sorted(method_counts.items(), key=lambda x: -x[1]):
        method_buckets.append(BenchRunCropsMethodBucket(
            method=m_name,
            n=m_n,
            n_undercrops=method_undercrops.get(m_name, 0),
            pct=(m_n / n_crops * 100.0) if n_crops else 0.0,
        ))

    quality_buckets: list[BenchRunCropsQualityBucket] = [
        BenchRunCropsQualityBucket(
            label=lbl, range_lo=lo, range_hi=min(hi, 1.0), n=quality_bucket_counts[i],
        )
        for i, (lbl, lo, hi) in enumerate(_QUALITY_BUCKETS)
    ]

    status_buckets: list[BenchRunCropsStatusBucket] = [
        BenchRunCropsStatusBucket(status=s, n=n)
        for s, n in sorted(status_counts.items(), key=lambda x: -x[1])
    ]

    q_mean = (sum(quality_values) / len(quality_values)) if quality_values else None
    q_median = _median(quality_values)
    q_std = _stdev(quality_values, q_mean) if q_mean is not None else None
    pct_undercrops = (n_undercrops_total / n_crops * 100.0) if n_crops else 0.0

    diagnostic = _build_diagnostic(method_buckets, n_undercrops_total)

    groups_summary: list[BenchRunCropsGroupSummary] = []
    for gid, (gc, gy, gd) in group_meta.items():
        groups_summary.append(BenchRunCropsGroupSummary(
            group_id=gid,
            country=gc,
            year=gy,
            denomination=gd,
            n_raws=len(group_raws.get(gid, set())),
            n_crops=group_crops.get(gid, 0),
            n_undercrops=group_undercrops.get(gid, 0),
        ))
    # Tri pertinent : par nb undercrops desc puis n_crops desc.
    groups_summary.sort(key=lambda g: (-g.n_undercrops, -g.n_crops))

    summary = BenchRunCropsSummary(
        run_id=run_id,
        n_groups=len(group_meta),
        n_raws=n_raws,
        n_crops=n_crops,
        n_undercrops=n_undercrops_total,
        pct_undercrops=pct_undercrops,
        quality_mean=q_mean,
        quality_median=q_median,
        quality_std=q_std,
        methods=method_buckets,
        quality_histogram=quality_buckets,
        statuses=status_buckets,
        diagnostic=diagnostic,
        undercrop_threshold=undercrop_threshold,
    )

    # 5. Filtres post-calcul + tri + pagination des cartes.
    filtered = (
        [c for c in cards if c.is_undercrop_suspect]
        if undercrop_only else cards
    )

    if sort == "score_desc":
        # Composite is_coin descendant : haut-scorers en premier (cf. expé 01
        # docs/crop-forensics/experiments/01-*.md : TOP 30 = 83 % cat D).
        # Tie-break par fetched_at desc pour stabilité.
        filtered.sort(
            key=lambda c: (
                -(c.composite_score if c.composite_score is not None else -1.0),
                c.fetched_at or "",
            ),
        )
    elif sort == "score_asc":
        # Bas-scorers en premier — utile pour audit des cas suspects.
        filtered.sort(
            key=lambda c: (
                c.composite_score if c.composite_score is not None else 2.0,
                c.fetched_at or "",
            ),
        )
    elif sort == "undercrop_first":
        # undercrops d'abord (True trie après False par défaut → reverse=True),
        # puis quality ascendante (les pires en haut).
        filtered.sort(
            key=lambda c: (not c.is_undercrop_suspect,
                           c.quality_score if c.quality_score is not None else 1.0),
        )
    elif sort == "quality_asc":
        filtered.sort(
            key=lambda c: c.quality_score if c.quality_score is not None else 1.0,
        )
    elif sort == "quality_desc":
        filtered.sort(
            key=lambda c: c.quality_score if c.quality_score is not None else 0.0,
            reverse=True,
        )
    elif sort == "recent":
        filtered.sort(key=lambda c: c.fetched_at or "", reverse=True)
    elif sort == "tilt_desc":
        # Tilts les plus forts en premier (tri pour audit exclusion).
        # Les cartes sans tilt_deg (backfill absent) tombent en fin via sentinel -1.
        filtered.sort(
            key=lambda c: c.tilt_deg if c.tilt_deg is not None else -1.0,
            reverse=True,
        )

    cards_total = len(filtered)
    paginated = filtered[offset:offset + limit]

    # Silence linter (utile pour Pydantic v2 — pas de validation runtime).
    _ = run_source

    return BenchRunCropsResponse(
        summary=summary,
        groups=groups_summary,
        cards=paginated,
        cards_total=cards_total,
    )


class CropsExcludePayload(BaseModel):
    asset_ids: list[str] = Field(default_factory=list)


class CropsExcludeResult(BaseModel):
    excluded: int
    skipped: list[str]   # asset_ids non trouvés ou n'appartenant pas au run


@router.post("/runs/{run_id}/crops/exclude", response_model=CropsExcludeResult)
def post_bench_run_crops_exclude(
    run_id: str,
    payload: CropsExcludePayload,
) -> CropsExcludeResult:
    """Marque des assets comme exclus du training (trop inclinés ou autre raison
    éditoriale).

    Seuls ``training_eligible`` et ``quality_reason`` sont modifiés :
    ``resolution_status``, ``eurio_id`` et toute autre colonne sont préservés.
    Les asset_ids qui n'appartiennent pas au run courant sont ignorés (skipped).
    Réversible : remettre ``training_eligible=1, quality_reason=NULL``.
    """
    if not payload.asset_ids:
        return CropsExcludeResult(excluded=0, skipped=[])

    conn = _store()._connection()  # noqa: SLF001

    # Vérifier que le run existe (404 propre si pas).
    run_row = conn.execute(
        "SELECT id FROM source_runs WHERE id = ?", (run_id,),
    ).fetchone()
    if run_row is None:
        raise HTTPException(status_code=404, detail=f"Run {run_id} not found.")

    now_iso = datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    excluded = 0
    skipped: list[str] = []

    # Guard d'appartenance : récupère d'un coup les asset_ids du run (set).
    # On évite N requêtes SELECT ; l'ensemble peut être grand (~milliers) mais
    # payload.asset_ids est borné par la UI (typiquement < 200 au total).
    run_asset_ids: set[str] = {
        row[0]
        for row in conn.execute(
            "SELECT id FROM image_assets WHERE run_id = ?", (run_id,)
        ).fetchall()
    }

    to_update = []
    for aid in payload.asset_ids:
        if aid not in run_asset_ids:
            skipped.append(aid)
        else:
            to_update.append(aid)

    if to_update:
        conn.execute("BEGIN")
        try:
            conn.executemany(
                """
                UPDATE image_assets
                   SET training_eligible = 0,
                       quality_reason    = 'too_tilted',
                       resolved_at       = ?
                 WHERE id = ?
                """,
                [(now_iso, aid) for aid in to_update],
            )
            conn.execute("COMMIT")
            excluded = len(to_update)
        except Exception:
            conn.execute("ROLLBACK")
            raise

    logger.info(
        "[bench] crops exclude run=%s excluded=%d skipped=%d",
        run_id, excluded, len(skipped),
    )
    return CropsExcludeResult(excluded=excluded, skipped=skipped)


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
