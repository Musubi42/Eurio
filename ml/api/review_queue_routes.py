"""FastAPI router for `/review-queue`.

Surfaces the queue managed by `ml/sources/_base/steps/enqueue.py`. The
admin front (`admin/packages/web/src/features/review/`) consumes this
router single-item-style: list 20 → pick one → decide / skip / reject
→ go back to list. No multi-select per D-16.

Decisions write back to `image_assets` (resolution_status, eurio_id,
face, variant_kind) AND to `review_queue` (decided_*, status='done').
The two writes happen in a single transaction so the queue and the
asset never disagree.
"""

from __future__ import annotations

import json
import logging
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import cv2
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from foundation.thresholds import DINO_VERDICT_THRESHOLDS, DinoVerdictThresholds
from scan.normalize_snap import detect_circles_multi
from state import Store

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/review-queue", tags=["review-queue"])

_VALID_FACES = ("obverse", "reverse", "unknown")
_SKIP_PRIORITY_BUMP = 50
_VALID_KINDS = ("single", "lot", "all")
_VALID_REJECT_REASONS = (
    "not_a_coin", "out_of_scope", "duplicate_in_listing", "unreadable", "other",
)

# listing_key extraction — eBay : `ebay_<itemId>` via raw_payload_json.
# Pour les autres sources (catawiki, etc.), fallback à `source_ref` en
# attendant que l'adapter dédié arrive avec son propre pattern.
_LISTING_KEY_SQL = """
CASE
  WHEN si.source = 'ebay'
   AND json_extract(si.raw_payload_json, '$.ebay_item_id') IS NOT NULL
    THEN 'ebay_' || json_extract(si.raw_payload_json, '$.ebay_item_id')
  ELSE si.source_ref
END
"""


def _store() -> Store:
    from .server import _store as shared_store
    return shared_store


# ── List ──────────────────────────────────────────────────────────────────


class ReviewBbox(BaseModel):
    x: float
    y: float
    w: float
    h: float


class ReviewCandidate(BaseModel):
    eurio_id: str
    score: float
    label: str
    country: str
    denomination: str
    year: int | None = None
    canonical_thumb_url: str = ""


class ReviewItem(BaseModel):
    id: str
    crop_url: str
    bbox: ReviewBbox | None
    source: str
    source_ref: str
    listing_title: str | None
    listing_url: str | None
    listing_price: float | None
    # Chunk C4 — contexte listing pour la carte d'audit « Listing & marché ».
    # Issu de listing_text_signals (C2) + source_images (C1). None sur les
    # rows antérieures aux chunks C1/C2.
    listing_kind: str | None = None
    listing_kind_confidence: float | None = None
    condition: str | None = None
    condition_confidence: float | None = None
    listing_origin_date: str | None = None
    sold_qty: int | None = None
    candidates: list[ReviewCandidate]
    face_detected: str | None
    priority: int
    is_multi_coin_lot: bool
    quality_score: float
    enqueued_at: str
    # eurio_id attribué au listing par le theme-match
    # (source_images.target_eurio_id). Sert au front à afficher la « pièce
    # proposée » en haut de la colonne de droite, pré-sélectionnée par
    # défaut — ~80 % des reviews valident la proposition. None quand le
    # matcher n'a pas tranché (verdict ambigu) ou pour les sources legacy
    # (mock, scans manuels).
    target_eurio_id: str | None = None
    # ReviewCandidate enrichi (image, label, pays/année) de la pièce
    # proposée — prêt à consommer côté front comme suggestion par défaut.
    # None quand target_eurio_id est None ou que la coin n'est pas dans le catalog.
    target_candidate: ReviewCandidate | None = None
    # Chunk 5b — pièces du groupe de découverte (dénom, pays, année) :
    # toutes les 2 € commémoratives du même pays/année. Peuplé seulement
    # quand le theme-match n'a pas tranché (target_candidate is None,
    # verdict ambigu) — le reviewer choisit la sœur d'un clic sans passer
    # par la recherche libre. Vide sinon.
    group_candidates: list[ReviewCandidate] = []


def _build_target_candidate(
    row: sqlite3.Row,
    target_eurio_id: str | None,
) -> ReviewCandidate | None:
    """Construit le ReviewCandidate enrichi de la pièce proposée (attribuée
    au listing par le theme-match) à partir d'une row SQL où on a JOIN
    coins. Attendu en colonnes :
    t_eurio_id, t_country, t_country_name, t_year, t_theme,
    t_face_value, t_numista_id. None si target_eurio_id absent ou la
    coin n'est pas dans le catalog. Partagé entre /review-queue (queue
    single) et /review-queue/lots/{key} (détail lot)."""
    if not target_eurio_id or "t_eurio_id" not in row.keys() or not row["t_eurio_id"]:
        return None
    label_bits = [
        row["t_country_name"],
        str(row["t_year"]) if row["t_year"] else None,
        row["t_theme"],
    ]
    denom = (
        f"{float(row['t_face_value']):.2f} EUR"
        if row["t_face_value"] is not None
        else ""
    )
    thumb = (
        f"/images/{int(row['t_numista_id'])}/source"
        if row["t_numista_id"]
        else ""
    )
    return ReviewCandidate(
        eurio_id=row["t_eurio_id"],
        score=1.0,  # prior — pas un score Dino, juste un marqueur "défaut"
        label=" · ".join([b for b in label_bits if b]) or row["t_eurio_id"],
        country=row["t_country"] or "",
        denomination=denom,
        year=row["t_year"],
        canonical_thumb_url=thumb,
    )


def _fetch_group_candidates(
    conn: sqlite3.Connection,
    pairs: set[tuple[str, int]],
) -> dict[tuple[str, int], list[ReviewCandidate]]:
    """Pour chaque groupe `(pays, année)`, les pièces 2 € commémoratives —
    candidats sélectionnables quand le theme-match n'a pas tranché (chunk
    5b). `pairs` est petit (≤ nb de groupes du run), une requête par paire
    reste cheap. Clé du dict : `(country, year)`."""
    out: dict[tuple[str, int], list[ReviewCandidate]] = {}
    for country, year in pairs:
        rows = conn.execute(
            """
            SELECT eurio_id, country, country_name, year, theme,
                   face_value, numista_id
              FROM coins
             WHERE country = ? AND year = ?
               AND face_value = 2.0 AND is_commemorative = 1
             ORDER BY theme
            """,
            (country, year),
        ).fetchall()
        cands: list[ReviewCandidate] = []
        for r in rows:
            label_bits = [
                r["country_name"],
                str(r["year"]) if r["year"] else None,
                r["theme"],
            ]
            cands.append(ReviewCandidate(
                eurio_id=r["eurio_id"],
                score=0.0,  # pas un score — juste un membre du groupe
                label=" · ".join([b for b in label_bits if b]) or r["eurio_id"],
                country=r["country"] or "",
                denomination=(
                    f"{float(r['face_value']):.2f} EUR"
                    if r["face_value"] is not None else ""
                ),
                year=r["year"],
                canonical_thumb_url=(
                    f"/images/{int(r['numista_id'])}/source"
                    if r["numista_id"] else ""
                ),
            ))
        out[(country, year)] = cands
    return out


def _row_to_item(
    row: sqlite3.Row,
    group_map: dict[tuple[str, int], list[ReviewCandidate]] | None = None,
) -> ReviewItem:
    bbox: ReviewBbox | None = None
    if row["bbox_json"]:
        try:
            d = json.loads(row["bbox_json"])
            bbox = ReviewBbox(x=d.get("x", 0), y=d.get("y", 0),
                              w=d.get("w", 0), h=d.get("h", 0))
        except (json.JSONDecodeError, TypeError):
            bbox = None

    candidates: list[ReviewCandidate] = []
    if row["candidate_eurio_ids_json"]:
        try:
            raw = json.loads(row["candidate_eurio_ids_json"])
            for c in raw if isinstance(raw, list) else []:
                if not isinstance(c, dict) or "eurio_id" not in c:
                    continue
                candidates.append(ReviewCandidate(
                    eurio_id=c["eurio_id"],
                    score=float(c.get("score", 0)),
                    label=c.get("label", c["eurio_id"]),
                    country=c.get("country", ""),
                    denomination=c.get("denomination", ""),
                    year=c.get("year"),
                    canonical_thumb_url=c.get("canonical_thumb_url", ""),
                ))
        except json.JSONDecodeError:
            pass

    target_eurio_id: str | None = (
        row["target_eurio_id"] if "target_eurio_id" in row.keys() else None
    )
    target_candidate = _build_target_candidate(row, target_eurio_id)

    cols = row.keys()

    def _opt(name: str):
        return row[name] if name in cols else None

    # Pièces du groupe : seulement quand le theme-match n'a pas tranché
    # (pas de proposition) et que pays/année du listing sont connus.
    group_candidates: list[ReviewCandidate] = []
    if target_candidate is None and group_map is not None:
        gc_country = _opt("listing_country")
        gc_year = _opt("listing_year")
        if gc_country and gc_year is not None:
            group_candidates = group_map.get((gc_country, gc_year), [])

    return ReviewItem(
        id=row["id"],
        crop_url=f"/sources/{row['source']}/assets/{row['image_asset_id']}/file",
        bbox=bbox,
        source=row["source"],
        source_ref=row["source_ref"],
        listing_title=row["listing_title"],
        listing_url=row["source_url"],
        listing_price=row["listing_price"],
        listing_kind=_opt("listing_kind"),
        listing_kind_confidence=_opt("listing_kind_confidence"),
        condition=_opt("condition_normalized"),
        condition_confidence=_opt("condition_confidence"),
        listing_origin_date=_opt("listing_origin_date"),
        sold_qty=_opt("sold_qty"),
        candidates=candidates,
        face_detected=row["face"],
        priority=row["priority"],
        is_multi_coin_lot=False,  # detection landing later
        quality_score=row["quality_score"] or 0.0,
        enqueued_at=row["enqueued_at"],
        target_eurio_id=target_eurio_id,
        target_candidate=target_candidate,
        group_candidates=group_candidates,
    )


# Consumed by: admin/packages/web/src/features/review/composables/useReviewApi.ts (fetchReviewQueue)
@router.get("", response_model=list[ReviewItem])
def list_queue(
    status: str = Query(default="open"),
    limit: int = Query(default=20, ge=1, le=200),
    order: str = Query(default="priority"),
    kind: str = Query(default="single"),
) -> list[ReviewItem]:
    if order not in ("priority", "enqueued_at"):
        raise HTTPException(status_code=422, detail="order must be 'priority' or 'enqueued_at'")
    if kind not in _VALID_KINDS:
        raise HTTPException(
            status_code=422, detail=f"kind must be one of {_VALID_KINDS}",
        )
    order_clause = "rq.priority ASC, rq.enqueued_at ASC" \
        if order == "priority" else "rq.enqueued_at ASC"

    conn = _store()._connection()  # noqa: SLF001
    where = "rq.status = ?"
    args: list[Any] = [status]
    if kind != "all":
        where += " AND rq.kind = ?"
        args.append(kind)
    args.append(limit)

    rows = conn.execute(
        f"""
        SELECT rq.id, rq.image_asset_id, rq.priority, rq.enqueued_at,
               rq.candidate_eurio_ids_json AS rq_candidates,
               a.bbox_json, a.candidate_eurio_ids_json, a.face, a.quality_score,
               s.source, s.source_ref, s.listing_title, s.source_url,
               s.listing_price, s.target_eurio_id,
               s.listing_country, s.listing_year,
               s.listing_origin_date, s.sold_qty,
               lts.listing_kind, lts.listing_kind_confidence,
               lts.condition_normalized, lts.condition_confidence,
               t.eurio_id     AS t_eurio_id,
               t.country      AS t_country,
               t.country_name AS t_country_name,
               t.year         AS t_year,
               t.theme        AS t_theme,
               t.face_value   AS t_face_value,
               t.numista_id   AS t_numista_id
          FROM review_queue rq
          JOIN image_assets a ON a.id = rq.image_asset_id
          JOIN source_images s ON s.id = a.source_image_id
          LEFT JOIN listing_text_signals lts ON lts.source_image_id = s.id
          LEFT JOIN coins t   ON t.eurio_id = s.target_eurio_id
         WHERE {where}
         ORDER BY {order_clause}
         LIMIT ?
        """,
        args,
    ).fetchall()

    # Chunk 5b — batch-fetch des pièces du groupe pour les seuls items
    # sans proposition (target_eurio_id NULL → verdict ambigu). Une
    # requête par (pays, année) distinct ; l'ensemble est petit.
    pairs: set[tuple[str, int]] = set()
    for r in rows:
        if r["target_eurio_id"]:
            continue
        c, y = r["listing_country"], r["listing_year"]
        if c and y is not None:
            pairs.add((c, y))
    group_map = _fetch_group_candidates(conn, pairs)

    return [_row_to_item(r, group_map) for r in rows]


# Consumed by: admin/packages/web/src/features/review/composables/useReviewApi.ts (fetchReviewStats)
@router.get("/stats")
def queue_stats() -> dict[str, Any]:
    """Counts for the queue header strip. Cheap (single query)."""
    conn = _store()._connection()  # noqa: SLF001
    today = datetime.utcnow().strftime("%Y-%m-%d")
    week_start = (datetime.utcnow() - timedelta(days=7)).strftime("%Y-%m-%d")

    n_pending = conn.execute(
        "SELECT COUNT(*) AS c FROM review_queue WHERE status = 'open'"
    ).fetchone()["c"]
    n_done_today = conn.execute(
        "SELECT COUNT(*) AS c FROM review_queue WHERE status = 'done' AND decided_at >= ?",
        (today,),
    ).fetchone()["c"]
    n_done_week = conn.execute(
        "SELECT COUNT(*) AS c FROM review_queue WHERE status = 'done' AND decided_at >= ?",
        (week_start,),
    ).fetchone()["c"]
    # Median seconds: rough proxy — diff between decided_at and enqueued_at
    # over the last 100 done items. Cheap, no real percentile needed yet.
    deltas: list[float] = []
    for r in conn.execute(
        """
        SELECT enqueued_at, decided_at FROM review_queue
         WHERE status = 'done' AND decided_at IS NOT NULL
         ORDER BY decided_at DESC LIMIT 100
        """
    ).fetchall():
        try:
            t0 = datetime.fromisoformat(r["enqueued_at"].replace(" ", "T"))
            t1 = datetime.fromisoformat(r["decided_at"].replace(" ", "T"))
            deltas.append((t1 - t0).total_seconds())
        except Exception:  # noqa: BLE001
            continue
    deltas.sort()
    median = deltas[len(deltas) // 2] if deltas else 0.0

    return {
        "n_pending": n_pending,
        "n_done_today": n_done_today,
        "n_done_this_week": n_done_week,
        "median_seconds_per_decision": round(median, 1),
    }


# ── Lot review (V1.5) ─────────────────────────────────────────────────────
#
# Cf. docs/sources-refacto/lot-review-kickoff.md.
#
# Une listing eBay = N source_images (1 par photo) = N×M image_assets
# (M crops par photo). Le reviewer doit voir toute la listing en une fois,
# pas crop-par-crop. Trois endpoints :
#
#   GET  /review-queue/lots                       — liste paginated, groupée par listing_key
#   GET  /review-queue/lots/{listing_key}         — détail (toutes images + crops)
#   POST /review-queue/lots/{listing_key}/decide  — bulk decide (assignments)
#
# IMPORTANT : ces routes doivent être déclarées AVANT /{review_id} sinon
# FastAPI capture "lots" comme un review_id.


class LotListItem(BaseModel):
    listing_key: str
    source: str
    target_eurio_id: str | None
    listing_title: str | None
    listing_price: float | None
    listing_currency: str
    is_lot_suspected: bool
    n_images: int
    n_crops_in_review: int
    oldest_enqueued_at: str
    thumb_url: str | None  # raw image URL, pour la card grille


class LotListResponse(BaseModel):
    items: list[LotListItem]
    total: int


# Consumed by: admin/packages/web/src/features/review/composables/useLotReview.ts (fetchLots)
@router.get("/lots", response_model=LotListResponse)
def list_lots(
    limit: int = Query(default=24, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> LotListResponse:
    """Liste les listings ayant ≥ 1 row review_queue.kind='lot' status='open'.

    Groupé par listing_key (cf. _LISTING_KEY_SQL — eBay : ebay_<itemId>).
    Tri : oldest_enqueued_at ASC (le reviewer commence par les plus vieux).
    """
    conn = _store()._connection()  # noqa: SLF001

    total = conn.execute(
        f"""
        SELECT COUNT(DISTINCT {_LISTING_KEY_SQL}) AS n
          FROM review_queue rq
          JOIN image_assets a ON a.id = rq.image_asset_id
          JOIN source_images si ON si.id = a.source_image_id
         WHERE rq.kind = 'lot' AND rq.status = 'open'
        """
    ).fetchone()["n"]

    rows = conn.execute(
        f"""
        WITH grouped AS (
          SELECT {_LISTING_KEY_SQL} AS listing_key,
                 si.source             AS source,
                 si.target_eurio_id    AS target_eurio_id,
                 MAX(si.listing_title) AS listing_title,
                 MAX(si.listing_price) AS listing_price,
                 MAX(si.listing_currency) AS listing_currency,
                 MAX(si.is_lot_suspected) AS is_lot_suspected,
                 COUNT(DISTINCT si.id)    AS n_images,
                 COUNT(DISTINCT a.id)     AS n_crops_in_review,
                 MIN(rq.enqueued_at)      AS oldest_enqueued_at,
                 (SELECT si2.id FROM source_images si2
                   WHERE si2.source = si.source
                     AND {_LISTING_KEY_SQL.replace('si.', 'si2.')} = {_LISTING_KEY_SQL}
                   ORDER BY si2.fetched_at ASC LIMIT 1) AS thumb_si_id
            FROM review_queue rq
            JOIN image_assets a ON a.id = rq.image_asset_id
            JOIN source_images si ON si.id = a.source_image_id
           WHERE rq.kind = 'lot' AND rq.status = 'open'
           GROUP BY listing_key
        )
        SELECT * FROM grouped
         ORDER BY oldest_enqueued_at ASC
         LIMIT ? OFFSET ?
        """,
        (limit, offset),
    ).fetchall()

    items = [
        LotListItem(
            listing_key=r["listing_key"],
            source=r["source"],
            target_eurio_id=r["target_eurio_id"],
            listing_title=r["listing_title"],
            listing_price=r["listing_price"],
            listing_currency=r["listing_currency"] or "EUR",
            is_lot_suspected=bool(r["is_lot_suspected"]),
            n_images=r["n_images"],
            n_crops_in_review=r["n_crops_in_review"],
            oldest_enqueued_at=r["oldest_enqueued_at"],
            thumb_url=(
                f"/sources/{r['source']}/raws/{r['thumb_si_id']}/file"
                if r["thumb_si_id"] else None
            ),
        )
        for r in rows
    ]
    return LotListResponse(items=items, total=int(total or 0))


class LotCrop(BaseModel):
    asset_id: str
    review_id: str
    crop_url: str
    crop_index: int
    phash: int | None
    current_eurio_id: str | None
    candidate_eurio_ids: list[ReviewCandidate]
    bbox: ReviewBbox | None


class LotDetection(BaseModel):
    """One circle from `detect_circles_multi`, computed on-the-fly.

    Coordinates en native pixel space du raw (`raw_width × raw_height`).
    `accepted=True` → ce cercle a produit un image_asset (lien via
    `crop_index`). `accepted=False` → cercle écarté par les critères
    stricts, exposé pour la vue debug uniquement (Stage 2). Pas de
    persistance DB — recompute déterministe à chaque requête.
    """
    cx: int
    cy: int
    r: int
    accepted: bool
    reject_reason: str | None
    method: str
    crop_index: int | None  # None si rejected


class LotImage(BaseModel):
    source_image_id: str
    image_index: int | None
    raw_url: str
    raw_width: int | None
    raw_height: int | None
    detections: list[LotDetection]
    crops: list[LotCrop]


class LotDetail(BaseModel):
    listing_key: str
    source: str
    target_eurio_id: str | None
    # ReviewCandidate enrichi de la pièce proposée (idem
    # ReviewItem.target_candidate). Permet au front lot de la
    # pré-sélectionner comme défaut, exactement comme la page single. None
    # si target_eurio_id est None ou la coin n'est pas dans le catalog.
    target_candidate: ReviewCandidate | None = None
    listing_title: str | None
    listing_price: float | None
    listing_currency: str
    is_lot_suspected: bool
    is_multi_crop_single: bool  # niveau 2 D-26 : titre single mais image multi-crop
    images: list[LotImage]
    prev_listing_key: str | None
    next_listing_key: str | None


def _parse_candidates(json_str: str | None) -> list[ReviewCandidate]:
    if not json_str:
        return []
    try:
        raw = json.loads(json_str)
    except json.JSONDecodeError:
        return []
    if not isinstance(raw, list):
        return []
    out: list[ReviewCandidate] = []
    for c in raw:
        if not isinstance(c, dict) or "eurio_id" not in c:
            continue
        out.append(ReviewCandidate(
            eurio_id=c["eurio_id"],
            score=float(c.get("score", 0)),
            label=c.get("label", c["eurio_id"]),
            country=c.get("country", ""),
            denomination=c.get("denomination", ""),
            year=c.get("year"),
            canonical_thumb_url=c.get("canonical_thumb_url", ""),
        ))
    return out


def _parse_bbox(json_str: str | None) -> ReviewBbox | None:
    if not json_str:
        return None
    try:
        d = json.loads(json_str)
    except json.JSONDecodeError:
        return None
    if not isinstance(d, dict):
        return None
    return ReviewBbox(
        x=d.get("x", 0), y=d.get("y", 0), w=d.get("w", 0), h=d.get("h", 0),
    )


def _compute_detections(raw_storage_key: str | None,
                         crop_indices_in_db: list[int]) -> list[LotDetection]:
    """Re-run `detect_circles_multi` on the raw — used for the Stage 2 debug view.

    Compute on-the-fly, no persistence. Latency ~50-200ms per image
    (acceptable for an admin view that's slow by nature). The accepted
    detections are matched to the existing `image_assets` rows by order
    (the pipeline is deterministic so accepted-detection-order ==
    crop_index order).

    `raw_storage_key` is the S3 key in `enrichment-raws` (since SS-1
    write-through MinIO). local_path() does read-through cache fetch.
    """
    if not raw_storage_key:
        return []
    from storage.local_cache import local_path as _local_path
    try:
        p = _local_path("enrichment-raws", raw_storage_key)
    except FileNotFoundError:
        return []
    bgr = cv2.imread(str(p), cv2.IMREAD_COLOR)
    if bgr is None or bgr.size == 0:
        return []
    detections = detect_circles_multi(bgr)
    out: list[LotDetection] = []
    accepted_idx = 0
    for det in detections:
        crop_index: int | None = None
        if det.accepted:
            if accepted_idx < len(crop_indices_in_db):
                crop_index = crop_indices_in_db[accepted_idx]
            accepted_idx += 1
        out.append(LotDetection(
            cx=det.cx, cy=det.cy, r=det.r,
            accepted=det.accepted,
            reject_reason=det.reject_reason,
            method=det.method,
            crop_index=crop_index,
        ))
    return out


def _siblings(conn: sqlite3.Connection, listing_key: str
              ) -> tuple[str | None, str | None]:
    """Find the previous and next listing_key in the open lots queue (by
    oldest enqueued_at — same order as `GET /review-queue/lots`). Returns
    `(prev, next)`, either side ``None`` at the boundaries."""
    rows = conn.execute(
        f"""
        SELECT {_LISTING_KEY_SQL} AS listing_key,
               MIN(rq.enqueued_at) AS oldest_enqueued_at
          FROM review_queue rq
          JOIN image_assets a ON a.id = rq.image_asset_id
          JOIN source_images si ON si.id = a.source_image_id
         WHERE rq.kind = 'lot' AND rq.status = 'open'
         GROUP BY listing_key
         ORDER BY oldest_enqueued_at ASC, listing_key ASC
        """,
    ).fetchall()
    keys = [r["listing_key"] for r in rows]
    if listing_key not in keys:
        return None, None
    i = keys.index(listing_key)
    prev_key = keys[i - 1] if i > 0 else None
    next_key = keys[i + 1] if i + 1 < len(keys) else None
    return prev_key, next_key


# Consumed by: admin/packages/web/src/features/review/composables/useLotReview.ts (fetchLotDetail)
@router.get("/lots/{listing_key}", response_model=LotDetail)
def get_lot(listing_key: str) -> LotDetail:
    conn = _store()._connection()  # noqa: SLF001
    # Header (depuis n'importe quelle source_image du listing).
    # JOIN coins pour enrichir target_candidate (idem _row_to_item).
    header = conn.execute(
        f"""
        SELECT si.source, si.target_eurio_id, si.listing_title,
               si.listing_price, si.listing_currency, si.is_lot_suspected,
               t.eurio_id     AS t_eurio_id,
               t.country      AS t_country,
               t.country_name AS t_country_name,
               t.year         AS t_year,
               t.theme        AS t_theme,
               t.face_value   AS t_face_value,
               t.numista_id   AS t_numista_id
          FROM source_images si
          LEFT JOIN coins t ON t.eurio_id = si.target_eurio_id
         WHERE {_LISTING_KEY_SQL} = ?
         LIMIT 1
        """,
        (listing_key,),
    ).fetchone()
    if header is None:
        raise HTTPException(status_code=404, detail=f"Lot '{listing_key}' not found.")

    # Toutes les source_images du listing (une seule requête JOIN).
    rows = conn.execute(
        f"""
        SELECT si.id AS source_image_id,
               si.raw_payload_json,
               si.storage_path AS raw_storage_path,
               si.width AS raw_width, si.height AS raw_height,
               a.id AS asset_id,
               a.crop_index, a.bbox_json, a.phash, a.eurio_id AS current_eurio_id,
               a.candidate_eurio_ids_json,
               rq.id AS review_id, rq.status AS rq_status, rq.kind AS rq_kind,
               si.source AS source
          FROM source_images si
          LEFT JOIN image_assets a ON a.source_image_id = si.id
          LEFT JOIN review_queue rq ON rq.image_asset_id = a.id
         WHERE {_LISTING_KEY_SQL} = ?
         ORDER BY si.id, a.crop_index
        """,
        (listing_key,),
    ).fetchall()

    # Storage paths kept aside per source_image for detection compute.
    raw_paths: dict[str, str | None] = {}
    by_si: dict[str, LotImage] = {}
    for r in rows:
        si_id = r["source_image_id"]
        if si_id not in by_si:
            image_index: int | None = None
            if r["raw_payload_json"]:
                try:
                    payload = json.loads(r["raw_payload_json"])
                    image_index = payload.get("image_index")
                except json.JSONDecodeError:
                    pass
            raw_paths[si_id] = r["raw_storage_path"]
            by_si[si_id] = LotImage(
                source_image_id=si_id,
                image_index=image_index,
                raw_url=f"/sources/{r['source']}/raws/{si_id}/file",
                raw_width=r["raw_width"],
                raw_height=r["raw_height"],
                detections=[],
                crops=[],
            )
        # Skip rows where the LEFT JOIN didn't produce a crop (image with 0 detect).
        if r["asset_id"] is None:
            continue
        # Only surface crops that are actually in the lot review queue
        # (or any crop on a multi-crop image — useful for context).
        # V1.5 : on liste tous les crops du listing, le front filtrera
        # les actions sur ceux dont rq.kind='lot' AND rq.status='open'.
        by_si[si_id].crops.append(LotCrop(
            asset_id=r["asset_id"],
            review_id=r["review_id"] or "",
            crop_url=f"/sources/{r['source']}/assets/{r['asset_id']}/file",
            crop_index=r["crop_index"] or 0,
            phash=r["phash"],
            current_eurio_id=r["current_eurio_id"],
            candidate_eurio_ids=_parse_candidates(r["candidate_eurio_ids_json"]),
            bbox=_parse_bbox(r["bbox_json"]),
        ))

    # Compute on-the-fly detections per image (Stage 2 debug). Crops in DB
    # are sorted by crop_index already (ORDER BY si.id, a.crop_index).
    for si_id, im in by_si.items():
        crop_indices = [c.crop_index for c in im.crops]
        im.detections = _compute_detections(raw_paths.get(si_id), crop_indices)

    # Tri images par image_index (None à la fin).
    images = sorted(
        by_si.values(),
        key=lambda im: (im.image_index is None, im.image_index or 0),
    )

    # is_multi_crop_single : titre n'est PAS lot mais ≥1 image multi-crop.
    is_multi_crop_single = (
        not bool(header["is_lot_suspected"])
        and any(len(im.crops) > 1 for im in images)
    )

    prev_key, next_key = _siblings(conn, listing_key)

    return LotDetail(
        listing_key=listing_key,
        source=header["source"],
        target_eurio_id=header["target_eurio_id"],
        target_candidate=_build_target_candidate(header, header["target_eurio_id"]),
        listing_title=header["listing_title"],
        listing_price=header["listing_price"],
        listing_currency=header["listing_currency"] or "EUR",
        is_lot_suspected=bool(header["is_lot_suspected"]),
        is_multi_crop_single=is_multi_crop_single,
        images=images,
        prev_listing_key=prev_key,
        next_listing_key=next_key,
    )


class LotAssignment(BaseModel):
    asset_id: str
    eurio_id: str | None = None
    face: str | None = None
    variant_kind: str | None = None
    reject_reason: str | None = None
    skip: bool = False


class LotDecidePayload(BaseModel):
    assignments: list[LotAssignment]


class LotDecideResponse(BaseModel):
    done: int
    rejected: int
    skipped: int
    errors: list[str]


# Consumed by: admin/packages/web/src/features/review/composables/useLotReview.ts (decideLot)
@router.post("/lots/{listing_key}/decide", response_model=LotDecideResponse)
def decide_lot(listing_key: str, payload: LotDecidePayload) -> LotDecideResponse:
    """Bulk decision sur un listing entier.

    Pour chaque assignment :
      - eurio_id → image_assets.resolution_status='manual', eurio_id=X ;
        review_queue.status='done', decided_eurio_id=X
      - reject_reason → image_assets.resolution_status='rejected' ;
        review_queue.status='done', decision_notes=reason
      - skip=True → review_queue.status='skipped' (sans toucher l'asset)

    Idempotence : si une review row n'est plus 'open' (déjà décidée),
    on l'ajoute aux errors mais on poursuit.
    Validation : chaque asset_id doit appartenir au listing — sinon erreur.
    """
    if not payload.assignments:
        return LotDecideResponse(done=0, rejected=0, skipped=0, errors=[])

    conn = _store()._connection()  # noqa: SLF001
    # Récupère tous les assets du listing avec leur review_id.
    listing_assets = {
        r["asset_id"]: r
        for r in conn.execute(
            f"""
            SELECT a.id AS asset_id,
                   rq.id AS review_id,
                   rq.status AS rq_status
              FROM source_images si
              JOIN image_assets a ON a.source_image_id = si.id
              LEFT JOIN review_queue rq ON rq.image_asset_id = a.id
             WHERE {_LISTING_KEY_SQL} = ?
            """,
            (listing_key,),
        ).fetchall()
    }
    if not listing_assets:
        raise HTTPException(status_code=404, detail=f"Lot '{listing_key}' not found.")

    now_iso = datetime.utcnow().isoformat(timespec="seconds")
    n_done = 0
    n_rejected = 0
    n_skipped = 0
    errors: list[str] = []

    conn.execute("BEGIN")
    try:
        for asg in payload.assignments:
            asset_row = listing_assets.get(asg.asset_id)
            if asset_row is None:
                errors.append(f"asset {asg.asset_id} does not belong to lot {listing_key}")
                continue
            review_id = asset_row["review_id"]
            rq_status = asset_row["rq_status"]
            if review_id is None:
                errors.append(f"asset {asg.asset_id} has no review_queue row")
                continue
            if rq_status != "open":
                errors.append(f"asset {asg.asset_id} already {rq_status}")
                continue

            # Decide path
            if asg.eurio_id:
                face = asg.face or "unknown"
                if face not in _VALID_FACES:
                    errors.append(f"asset {asg.asset_id} invalid face '{face}'")
                    continue
                conn.execute(
                    """
                    UPDATE image_assets
                       SET eurio_id = ?, face = ?,
                           variant_kind = COALESCE(?, variant_kind),
                           resolution_status = 'manual',
                           resolution_confidence = 1.0,
                           resolved_at = ?
                     WHERE id = ?
                    """,
                    (asg.eurio_id, face, asg.variant_kind, now_iso, asg.asset_id),
                )
                conn.execute(
                    """
                    UPDATE review_queue
                       SET status = 'done',
                           decided_eurio_id = ?, decided_face = ?,
                           decided_variant_kind = ?, decided_at = ?,
                           decided_by = 'admin'
                     WHERE id = ?
                    """,
                    (asg.eurio_id, face, asg.variant_kind, now_iso, review_id),
                )
                n_done += 1

            # Reject path
            elif asg.reject_reason:
                if asg.reject_reason not in _VALID_REJECT_REASONS:
                    errors.append(
                        f"asset {asg.asset_id} invalid reject_reason "
                        f"'{asg.reject_reason}' — accepted: {_VALID_REJECT_REASONS}"
                    )
                    continue
                conn.execute(
                    """
                    UPDATE image_assets
                       SET resolution_status = 'rejected', resolved_at = ?
                     WHERE id = ?
                    """,
                    (now_iso, asg.asset_id),
                )
                conn.execute(
                    """
                    UPDATE review_queue
                       SET status = 'done',
                           decision_notes = ?, decided_at = ?, decided_by = 'admin'
                     WHERE id = ?
                    """,
                    (asg.reject_reason, now_iso, review_id),
                )
                n_rejected += 1

            # Skip path
            elif asg.skip:
                conn.execute(
                    "UPDATE review_queue SET status = 'skipped' WHERE id = ?",
                    (review_id,),
                )
                n_skipped += 1

            else:
                errors.append(
                    f"asset {asg.asset_id} has no action "
                    "(provide eurio_id, reject_reason, or skip=true)"
                )
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise

    logger.info(
        "[lot] decide listing=%s done=%d rejected=%d skipped=%d errors=%d",
        listing_key, n_done, n_rejected, n_skipped, len(errors),
    )
    return LotDecideResponse(
        done=n_done, rejected=n_rejected, skipped=n_skipped, errors=errors,
    )


# ── Single review fetch / mutations (existing) ────────────────────────────


# Consumed by: admin/packages/web/src/features/review/composables/useReviewApi.ts (fetchReviewItem)
@router.get("/{review_id}", response_model=ReviewItem)
def get_review(review_id: str) -> ReviewItem:
    conn = _store()._connection()  # noqa: SLF001
    row = conn.execute(
        """
        SELECT rq.id, rq.image_asset_id, rq.priority, rq.enqueued_at,
               rq.candidate_eurio_ids_json AS rq_candidates,
               a.bbox_json, a.candidate_eurio_ids_json, a.face, a.quality_score,
               s.source, s.source_ref, s.listing_title, s.source_url,
               s.listing_price, s.target_eurio_id,
               s.listing_country, s.listing_year,
               s.listing_origin_date, s.sold_qty,
               lts.listing_kind, lts.listing_kind_confidence,
               lts.condition_normalized, lts.condition_confidence,
               t.eurio_id     AS t_eurio_id,
               t.country      AS t_country,
               t.country_name AS t_country_name,
               t.year         AS t_year,
               t.theme        AS t_theme,
               t.face_value   AS t_face_value,
               t.numista_id   AS t_numista_id
          FROM review_queue rq
          JOIN image_assets a ON a.id = rq.image_asset_id
          JOIN source_images s ON s.id = a.source_image_id
          LEFT JOIN listing_text_signals lts ON lts.source_image_id = s.id
          LEFT JOIN coins t   ON t.eurio_id = s.target_eurio_id
         WHERE rq.id = ?
        """,
        (review_id,),
    ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Review item not found.")
    return _row_to_item(row)


# ── Mutations ─────────────────────────────────────────────────────────────


class DecidePayload(BaseModel):
    eurio_id: str = Field(min_length=1)
    face: str
    variant_kind: str | None = None
    notes: str | None = None


# Consumed by: admin/packages/web/src/features/review/composables/useReviewApi.ts (decideReview)
@router.post("/{review_id}/decide", status_code=200)
def decide_review(review_id: str, payload: DecidePayload) -> dict[str, str]:
    if payload.face not in _VALID_FACES:
        raise HTTPException(
            status_code=422, detail=f"face must be one of {_VALID_FACES}",
        )

    conn = _store()._connection()  # noqa: SLF001
    rq = conn.execute(
        "SELECT id, image_asset_id, status FROM review_queue WHERE id = ?",
        (review_id,),
    ).fetchone()
    if rq is None:
        raise HTTPException(status_code=404, detail="Review item not found.")
    if rq["status"] != "open":
        raise HTTPException(
            status_code=409,
            detail=f"Review already {rq['status']} — cannot decide twice.",
        )

    now_iso = datetime.utcnow().isoformat(timespec="seconds")
    asset_id = rq["image_asset_id"]

    # Two-step transaction: image_assets + review_queue.
    conn.execute("BEGIN")
    try:
        conn.execute(
            """
            UPDATE image_assets
               SET eurio_id = ?,
                   face = ?,
                   variant_kind = COALESCE(?, variant_kind),
                   resolution_status = 'manual',
                   resolution_confidence = 1.0,
                   resolved_at = ?
             WHERE id = ?
            """,
            (payload.eurio_id, payload.face, payload.variant_kind, now_iso, asset_id),
        )
        conn.execute(
            """
            UPDATE review_queue
               SET status = 'done',
                   decided_eurio_id = ?,
                   decided_face = ?,
                   decided_variant_kind = ?,
                   decision_notes = ?,
                   decided_at = ?,
                   decided_by = 'admin'
             WHERE id = ?
            """,
            (payload.eurio_id, payload.face, payload.variant_kind,
             payload.notes, now_iso, review_id),
        )
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise

    logger.info("[review] decided id=%s eurio_id=%s face=%s",
                review_id, payload.eurio_id, payload.face)
    return {"status": "done", "id": review_id}


# ── Correction listing_kind / condition (chunk C4) ────────────────────────

_VALID_LISTING_KINDS = ("single", "lot", "coffret", "graded_slab")
_VALID_CONDITIONS = ("UNC", "TTB", "TB")


class CorrectListingPayload(BaseModel):
    listing_kind: str | None = None
    condition: str | None = None


# Consumed by: admin/.../review/composables/useReviewApi.ts (correctListing)
@router.post("/{review_id}/correct-listing", status_code=200)
def correct_listing(review_id: str, payload: CorrectListingPayload) -> dict[str, Any]:
    """Corrige manuellement listing_kind et/ou condition d'un listing.

    La correction se propage à **toutes** les source_images du listing
    (N photos → N rows) et marque ``extractor_version='manual'`` : le
    step C2 ``text_signal`` ne ré-écrasera plus ces signaux. Indépendant
    de la décision d'attribution — la review reste ``open``.
    """
    if payload.listing_kind is None and payload.condition is None:
        raise HTTPException(
            status_code=422, detail="Provide listing_kind and/or condition.",
        )
    if payload.listing_kind is not None and payload.listing_kind not in _VALID_LISTING_KINDS:
        raise HTTPException(
            status_code=422,
            detail=f"listing_kind must be one of {_VALID_LISTING_KINDS}",
        )
    if payload.condition is not None and payload.condition not in _VALID_CONDITIONS:
        raise HTTPException(
            status_code=422,
            detail=f"condition must be one of {_VALID_CONDITIONS}",
        )

    conn = _store()._connection()  # noqa: SLF001
    si = conn.execute(
        """
        SELECT s.id AS sid, s.source, s.source_url
          FROM review_queue rq
          JOIN image_assets a ON a.id = rq.image_asset_id
          JOIN source_images s ON s.id = a.source_image_id
         WHERE rq.id = ?
        """,
        (review_id,),
    ).fetchone()
    if si is None:
        raise HTTPException(status_code=404, detail="Review item not found.")

    # Toutes les source_images du même listing — identité = source_url
    # (page de l'annonce, partagée par les N photos). Fallback : la row
    # seule si l'URL est absente.
    if si["source_url"]:
        sibling_ids = [
            r["id"] for r in conn.execute(
                "SELECT id FROM source_images WHERE source = ? AND source_url = ?",
                (si["source"], si["source_url"]),
            ).fetchall()
        ]
    else:
        sibling_ids = [si["sid"]]

    sets = ["extractor_version = 'manual'", "computed_at = datetime('now')"]
    args: list[Any] = []
    if payload.listing_kind is not None:
        sets.append("listing_kind = ?")
        sets.append("listing_kind_confidence = 1.0")
        args.append(payload.listing_kind)
    if payload.condition is not None:
        sets.append("condition_normalized = ?")
        sets.append("condition_confidence = 1.0")
        args.append(payload.condition)

    placeholders = ",".join("?" * len(sibling_ids))
    conn.execute(
        f"UPDATE listing_text_signals SET {', '.join(sets)} "  # noqa: S608
        f"WHERE source_image_id IN ({placeholders})",
        (*args, *sibling_ids),
    )
    conn.commit()
    logger.info(
        "[review] correct-listing id=%s kind=%s condition=%s → %d images",
        review_id, payload.listing_kind, payload.condition, len(sibling_ids),
    )
    return {
        "status": "ok",
        "id": review_id,
        "n_images": len(sibling_ids),
        "listing_kind": payload.listing_kind,
        "condition": payload.condition,
    }


# Consumed by: admin/packages/web/src/features/review/composables/useReviewApi.ts (rejectReview)
@router.post("/{review_id}/reject", status_code=200)
def reject_review(review_id: str) -> dict[str, str]:
    """Mark the IMAGE as unusable (not the review row's status). The row
    is closed with `decision_notes='rejected'` and the underlying
    `image_assets` row gets `resolution_status='rejected'`."""
    conn = _store()._connection()  # noqa: SLF001
    rq = conn.execute(
        "SELECT id, image_asset_id, status FROM review_queue WHERE id = ?",
        (review_id,),
    ).fetchone()
    if rq is None:
        raise HTTPException(status_code=404, detail="Review item not found.")
    if rq["status"] != "open":
        raise HTTPException(
            status_code=409,
            detail=f"Review already {rq['status']} — cannot reject twice.",
        )

    now_iso = datetime.utcnow().isoformat(timespec="seconds")
    conn.execute("BEGIN")
    try:
        conn.execute(
            """
            UPDATE image_assets
               SET resolution_status = 'rejected', resolved_at = ?
             WHERE id = ?
            """,
            (now_iso, rq["image_asset_id"]),
        )
        conn.execute(
            """
            UPDATE review_queue
               SET status = 'done',
                   decision_notes = 'rejected',
                   decided_at = ?,
                   decided_by = 'admin'
             WHERE id = ?
            """,
            (now_iso, review_id),
        )
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise

    logger.info("[review] rejected id=%s", review_id)
    return {"status": "rejected", "id": review_id}


# ── Dino suggestions (auto-validation V1) ─────────────────────────────────


class DinoSuggestion(BaseModel):
    """One top-K candidate enriched with coin metadata for the drawer UI."""

    eurio_id: str
    sim: float
    country: str | None = None
    country_name: str | None = None
    year: int | None = None
    theme: str | None = None
    denomination: float | None = None
    is_commemorative: bool | None = None
    obverse_url: str | None = None  # /images/<numista_id>/source if available


class DinoSuggestionsResponse(BaseModel):
    asset_id: str
    encoder_version: str
    anchors_kind: str
    anchors_count: int
    computed_at: str | None = None
    duration_ms: int | None = None
    spread: float | None = None
    top1_eurio_id: str | None = None
    top1_sim: float | None = None
    top_k: list[DinoSuggestion]
    # Country-restricted re-rank (chunk 3.5). Empty list when the crop
    # has no target country signal (NULL target_eurio_id on the parent
    # source_image), or when the bank has no anchors for the target
    # country. Front renders this band first when populated.
    target_country: str | None = None
    country_anchors_count: int | None = None
    country_spread: float | None = None
    top1_country_eurio_id: str | None = None
    top1_country_sim: float | None = None
    top_k_country: list[DinoSuggestion] = []
    # eurio_id qui a piloté le scrape (depuis source_images). Sert au
    # front à calculer le critère "top1==target" du verdict d'auto-
    # validation. Peut être None pour les sources legacy (mock, scans
    # sans target).
    target_eurio_id: str | None = None
    # Seuils provisoires de l'auto-validation V1 — display-only, lisibles
    # depuis ml/foundation/thresholds.py. Permet au front d'afficher
    # ✓/✗ par critère sans hardcoder de constante.
    verdict_thresholds: DinoVerdictThresholds = DINO_VERDICT_THRESHOLDS


def _enrich_top_k(
    conn: sqlite3.Connection, top_k: list[dict]
) -> list[DinoSuggestion]:
    """Hydrate the bare {eurio_id, sim} top-K with coin metadata + obverse URL."""
    if not top_k:
        return []
    eids = [str(t["eurio_id"]) for t in top_k]
    placeholders = ",".join("?" for _ in eids)
    rows = conn.execute(
        f"""
        SELECT eurio_id, country, country_name, year, theme,
               face_value, is_commemorative, numista_id
          FROM coins WHERE eurio_id IN ({placeholders})
        """,
        eids,
    ).fetchall()
    by_eid = {r["eurio_id"]: r for r in rows}
    enriched: list[DinoSuggestion] = []
    for entry in top_k:
        eid = str(entry["eurio_id"])
        row = by_eid.get(eid)
        if row is None:
            enriched.append(DinoSuggestion(eurio_id=eid, sim=float(entry["sim"])))
            continue
        nid = row["numista_id"]
        enriched.append(
            DinoSuggestion(
                eurio_id=eid,
                sim=float(entry["sim"]),
                country=row["country"],
                country_name=row["country_name"],
                year=row["year"],
                theme=row["theme"],
                denomination=float(row["face_value"]) if row["face_value"] else None,
                is_commemorative=bool(row["is_commemorative"]),
                obverse_url=f"/images/{int(nid)}/source" if nid else None,
            )
        )
    return enriched


def _build_dino_response(
    asset_id: str, anchors_kind: str
) -> DinoSuggestionsResponse:
    store = _store()
    conn = store._connection()  # noqa: SLF001
    pred = store.get_dino_prediction(
        asset_id=asset_id,
        encoder_version="dinov2-vits14",
        anchors_kind=anchors_kind,
    )
    if pred is None:
        raise HTTPException(
            status_code=404,
            detail=(
                f"No Dino prediction for asset_id={asset_id} "
                f"(anchors_kind={anchors_kind}). Either out of scope or "
                "auto_validate hasn't run yet — see "
                "go-task ml:dino-predictions:backfill."
            ),
        )
    target_eurio_row = conn.execute(
        """
        SELECT si.target_eurio_id
          FROM image_assets ia
          JOIN source_images si ON si.id = ia.source_image_id
         WHERE ia.id = ?
        """,
        (asset_id,),
    ).fetchone()
    target_eurio_id = (
        target_eurio_row["target_eurio_id"] if target_eurio_row else None
    )
    return DinoSuggestionsResponse(
        asset_id=pred.asset_id,
        encoder_version=pred.encoder_version,
        anchors_kind=pred.anchors_kind,
        anchors_count=pred.anchors_count,
        computed_at=pred.computed_at,
        duration_ms=pred.duration_ms,
        spread=pred.spread,
        top1_eurio_id=pred.top1_eurio_id,
        top1_sim=pred.top1_sim,
        top_k=_enrich_top_k(conn, pred.top_k),
        target_country=pred.target_country,
        country_anchors_count=pred.country_anchors_count,
        country_spread=pred.country_spread,
        top1_country_eurio_id=pred.top1_country_eurio_id,
        top1_country_sim=pred.top1_country_sim,
        top_k_country=_enrich_top_k(conn, pred.top_k_country or []),
        target_eurio_id=target_eurio_id,
    )


# Consumed by: admin/packages/web/src/features/review/composables/useDinoSuggestions.ts (fetchDinoSuggestionsByAssetId)
@router.get(
    "/asset/{asset_id}/dino-suggestions",
    response_model=DinoSuggestionsResponse,
)
def get_dino_suggestions(
    asset_id: str,
    anchors_kind: str = Query(default="2eur_commemo"),
) -> DinoSuggestionsResponse:
    """Return the persisted Dino top-K for one image_asset, enriched.

    404 if no prediction exists (i.e. the asset is out of scope, or
    auto_validate hasn't run yet on this asset). The reviewer drawer
    falls back gracefully — Dino is an optional aid layer, not a
    requirement to review.
    """
    return _build_dino_response(asset_id, anchors_kind)


# Consumed by: admin/packages/web/src/features/review/composables/useDinoSuggestions.ts (fetchDinoSuggestionsByReviewId)
@router.get(
    "/{review_id}/dino-suggestions",
    response_model=DinoSuggestionsResponse,
)
def get_dino_suggestions_for_review(
    review_id: str,
    anchors_kind: str = Query(default="2eur_commemo"),
) -> DinoSuggestionsResponse:
    """Same payload as /asset/{asset_id}/dino-suggestions, but indexed
    by ``review_queue.id`` — handy for the single review drawer which
    only carries the review_id in its state."""
    conn = _store()._connection()  # noqa: SLF001
    row = conn.execute(
        "SELECT image_asset_id FROM review_queue WHERE id = ?",
        (review_id,),
    ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Review item not found.")
    return _build_dino_response(row["image_asset_id"], anchors_kind)


# ── Listing text signals (chunk 5 auto-validation) ─────────────────────
#
# Expose les signaux extraits par ml/sources/text_signals depuis le
# titre de chaque listing. Pas de comparaison vs target ici (chunk 6) :
# on retourne ce que le titre dit explicitement. 404 propre si pas de
# signal extrait (= source_image hors-scope ou step pas encore exécuté).


class TextSignalsResponse(BaseModel):
    source_image_id: str
    extractor_version: str
    listing_title: str | None = None
    target_eurio_id: str | None = None
    countries: list[str]
    years: list[int]
    denominations: list[float]
    theme_tokens: list[str]
    rejected_markers: list[str]
    is_lot: bool
    coverage: str
    matched: dict[str, list[str]]
    # Chunk 6 — verdict vs target. None quand le target n'est pas connu
    # (pas de target_eurio_id, ou row pré-chunk-6).
    vs_target_verdict: str | None = None
    contradictions: list[str] = []
    convergences: list[str] = []
    computed_at: str | None = None


def _build_text_signals_response(source_image_id: str) -> TextSignalsResponse:
    conn = _store()._connection()  # noqa: SLF001
    row = conn.execute(
        """
        SELECT lts.*, si.listing_title, si.target_eurio_id
          FROM listing_text_signals lts
          JOIN source_images si ON si.id = lts.source_image_id
         WHERE lts.source_image_id = ?
        """,
        (source_image_id,),
    ).fetchone()
    if row is None:
        raise HTTPException(
            status_code=404,
            detail=(
                "No text signals for this source_image. The text_signal step "
                "may not have run yet — try `go-task ml:text-signals:backfill`."
            ),
        )
    cols = row.keys()
    verdict = row["vs_target_verdict"] if "vs_target_verdict" in cols else None
    contradictions_raw = (
        row["contradictions_json"] if "contradictions_json" in cols else None
    )
    convergences_raw = (
        row["convergences_json"] if "convergences_json" in cols else None
    )
    return TextSignalsResponse(
        source_image_id=row["source_image_id"],
        extractor_version=row["extractor_version"],
        listing_title=row["listing_title"],
        target_eurio_id=row["target_eurio_id"],
        countries=json.loads(row["countries_json"] or "[]"),
        years=json.loads(row["years_json"] or "[]"),
        denominations=json.loads(row["denominations_json"] or "[]"),
        theme_tokens=json.loads(row["theme_tokens_json"] or "[]"),
        rejected_markers=json.loads(row["rejected_markers_json"] or "[]"),
        is_lot=bool(row["is_lot"]),
        coverage=row["coverage"],
        matched=json.loads(row["matched_json"] or "{}"),
        vs_target_verdict=verdict,
        contradictions=json.loads(contradictions_raw or "[]"),
        convergences=json.loads(convergences_raw or "[]"),
        computed_at=row["computed_at"],
    )


# Consumed by: admin/packages/web/src/features/review/composables/useTextSignals.ts (fetchTextSignalsByAssetId)
@router.get(
    "/asset/{asset_id}/text-signals",
    response_model=TextSignalsResponse,
)
def get_text_signals_for_asset(asset_id: str) -> TextSignalsResponse:
    """Return text signals for the source_image parent of an image_asset.

    Le signal vit au niveau du listing (= source_image), pas du crop —
    plusieurs assets d'un même listing partagent le même signal.
    """
    conn = _store()._connection()  # noqa: SLF001
    row = conn.execute(
        "SELECT source_image_id FROM image_assets WHERE id = ?",
        (asset_id,),
    ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Asset not found.")
    return _build_text_signals_response(row["source_image_id"])


# Consumed by: admin/packages/web/src/features/review/composables/useTextSignals.ts (fetchTextSignalsByReviewId)
@router.get(
    "/{review_id}/text-signals",
    response_model=TextSignalsResponse,
)
def get_text_signals_for_review(review_id: str) -> TextSignalsResponse:
    """Same payload as /asset/{asset_id}/text-signals, indexed by
    review_queue.id — handy for the single review drawer."""
    conn = _store()._connection()  # noqa: SLF001
    row = conn.execute(
        """
        SELECT a.source_image_id
          FROM review_queue rq
          JOIN image_assets a ON a.id = rq.image_asset_id
         WHERE rq.id = ?
        """,
        (review_id,),
    ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Review item not found.")
    return _build_text_signals_response(row["source_image_id"])


# Consumed by: admin/packages/web/src/features/review/composables/useReviewApi.ts (skipReview)
@router.post("/{review_id}/skip", status_code=200)
def skip_review(review_id: str) -> dict[str, Any]:
    """Defer this item: bump `priority` so it lands further down the
    queue, but keep `status='open'`. No write to `image_assets`."""
    conn = _store()._connection()  # noqa: SLF001
    rq = conn.execute(
        "SELECT id, status, priority FROM review_queue WHERE id = ?",
        (review_id,),
    ).fetchone()
    if rq is None:
        raise HTTPException(status_code=404, detail="Review item not found.")
    if rq["status"] != "open":
        raise HTTPException(
            status_code=409,
            detail=f"Review is {rq['status']} — only open items can be skipped.",
        )
    new_priority = rq["priority"] + _SKIP_PRIORITY_BUMP
    conn.execute(
        "UPDATE review_queue SET priority = ? WHERE id = ?",
        (new_priority, review_id),
    )
    logger.info("[review] skipped id=%s new_priority=%d", review_id, new_priority)
    return {"status": "skipped", "id": review_id, "new_priority": new_priority}
