"""Idempotent upserts into the four ingestion tables.

Every helper here can be called any number of times with the same
input and converge on the same DB state. That's what makes step-by-step
reruns safe (orchestration.md, D-13).

Unique keys (kept in sync with `ml/state/schema.sql`):
- source_images       : (source, source_ref)
- image_assets        : (source_image_id, crop_index)
- coin_market_quotes  : (source, eurio_id, period_start, condition_raw)
- pending_quotes      : no natural key — we insert by source_image_id;
                        callers are expected to delete pending rows
                        when promoting to coin_market_quotes.
"""

from __future__ import annotations

import json
import sqlite3
import uuid
from dataclasses import asdict, dataclass, field
from typing import Any


# ── Dataclasses ─────────────────────────────────────────────────────────────


@dataclass
class SourceImageRow:
    source: str
    source_ref: str
    source_url: str | None = None
    target_eurio_id: str | None = None
    listing_title: str | None = None
    listing_country: str | None = None
    listing_year: int | None = None
    listing_price: float | None = None
    listing_currency: str = "EUR"
    condition_raw: str | None = None
    seller_id: str | None = None
    storage_path: str | None = None
    width: int | None = None
    height: int | None = None
    bytes: int | None = None
    sha256: str | None = None
    n_crops_detected: int = 0
    license: str = "unknown"
    redistributable: bool = False
    is_lot_suspected: bool = False
    raw_payload: dict[str, Any] | None = None
    run_id: str | None = None
    # eBay multi-mkt (B4). Voir docs/sources-refacto/ebay-multi-marketplace/
    # schema.md §"Stratégie d'écriture" — merge en RAM avant INSERT, pas
    # de ON CONFLICT DO UPDATE.
    marketplace: str | None = None
    marketplace_found_json: str | None = None


@dataclass
class ImageAssetRow:
    source_image_id: str
    crop_index: int = 0
    # Pre-generated id (write-through caller computes the S3 key before
    # upserting). If None, upsert_image_asset generates a fresh uuid.hex.
    id: str | None = None
    bbox: dict[str, float] | None = None
    detection_method: str | None = None
    eurio_id: str | None = None
    resolution_status: str = "pending_match"
    resolution_confidence: float | None = None
    resolution_attempts: list[dict[str, Any]] | None = None
    candidate_eurio_ids: list[dict[str, Any]] | None = None
    face: str | None = None
    variant_kind: str = "unknown"
    quality_score: float | None = None
    training_eligible: bool = False
    quality_reason: str | None = None
    quality_pipeline_version: int | None = None
    phash: int | None = None
    storage_path: str = ""
    width: int | None = None
    height: int | None = None
    sha256: str | None = None
    run_id: str | None = None


@dataclass
class CoinMarketQuoteRow:
    eurio_id: str
    source: str
    period_start: str                     # ISO timestamp
    period_end: str
    condition_raw: str | None = None
    condition_normalized: str = "unknown"
    currency: str = "EUR"
    p10: float | None = None
    p50: float | None = None
    p90: float | None = None
    sample_size: int = 1
    raw_payload: dict[str, Any] | None = None
    run_id: str | None = None


@dataclass
class PendingQuoteRow:
    source_image_id: str
    source: str
    price: float | None = None
    currency: str = "EUR"
    condition_raw: str | None = None
    raw_payload: dict[str, Any] | None = None


# ── Upserts ─────────────────────────────────────────────────────────────────


def upsert_source_image(conn: sqlite3.Connection, row: SourceImageRow) -> str:
    """Insert or update a `source_images` row by (source, source_ref).

    Returns the row id. Existing files on disk are not touched — only
    the DB row is refreshed.
    """
    existing = conn.execute(
        "SELECT id FROM source_images WHERE source = ? AND source_ref = ?",
        (row.source, row.source_ref),
    ).fetchone()
    payload = json.dumps(row.raw_payload, ensure_ascii=False) if row.raw_payload else None
    if existing:
        sid = existing["id"] if isinstance(existing, sqlite3.Row) else existing[0]
        # Note (V-1 anomaly A3 fix 2026-05-18) : `n_crops_detected` is
        # owned by the detect_crop step — every other writer leaves it
        # alone. persist.py always passes the dataclass default (0) so
        # listing it here used to reset the count to 0 on every rerun.
        # B4 — marketplace/marketplace_found via COALESCE : sur refresh,
        # on garde la valeur du first-insert (pas d'écrasement). Le merge
        # cross-run sera adressé en V2 (V1 : merge en RAM intra-run).
        conn.execute(
            """
            UPDATE source_images SET
              source_url=?, target_eurio_id=?,
              listing_title=?, listing_country=?, listing_year=?,
              listing_price=?, listing_currency=?, condition_raw=?, seller_id=?,
              storage_path=COALESCE(?, storage_path),
              width=COALESCE(?, width), height=COALESCE(?, height),
              bytes=COALESCE(?, bytes), sha256=COALESCE(?, sha256),
              license=?, redistributable=?,
              is_lot_suspected=?,
              raw_payload_json=COALESCE(?, raw_payload_json),
              run_id=COALESCE(?, run_id),
              marketplace=COALESCE(marketplace, ?),
              marketplace_found_json=COALESCE(marketplace_found_json, ?),
              fetched_at=datetime('now')
            WHERE id=?
            """,
            (
                row.source_url, row.target_eurio_id,
                row.listing_title, row.listing_country, row.listing_year,
                row.listing_price, row.listing_currency, row.condition_raw, row.seller_id,
                row.storage_path,
                row.width, row.height, row.bytes, row.sha256,
                row.license, int(row.redistributable),
                int(row.is_lot_suspected),
                payload,
                row.run_id,
                row.marketplace, row.marketplace_found_json,
                sid,
            ),
        )
        return sid

    sid = uuid.uuid4().hex
    conn.execute(
        """
        INSERT INTO source_images (
          id, source, source_ref, source_url, target_eurio_id,
          listing_title, listing_country, listing_year,
          listing_price, listing_currency, condition_raw, seller_id,
          storage_path, width, height, bytes, sha256,
          n_crops_detected, license, redistributable, is_lot_suspected,
          raw_payload_json, run_id,
          marketplace, marketplace_found_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            sid, row.source, row.source_ref, row.source_url, row.target_eurio_id,
            row.listing_title, row.listing_country, row.listing_year,
            row.listing_price, row.listing_currency, row.condition_raw, row.seller_id,
            row.storage_path, row.width, row.height, row.bytes, row.sha256,
            row.n_crops_detected, row.license, int(row.redistributable),
            int(row.is_lot_suspected),
            payload, row.run_id,
            row.marketplace, row.marketplace_found_json,
        ),
    )
    return sid


def upsert_image_asset(conn: sqlite3.Connection, row: ImageAssetRow) -> str:
    """Insert or update an `image_assets` row by (source_image_id, crop_index)."""
    existing = conn.execute(
        "SELECT id FROM image_assets WHERE source_image_id = ? AND crop_index = ?",
        (row.source_image_id, row.crop_index),
    ).fetchone()

    bbox = json.dumps(row.bbox, ensure_ascii=False) if row.bbox is not None else None
    attempts = json.dumps(row.resolution_attempts, ensure_ascii=False) if row.resolution_attempts is not None else None
    candidates = json.dumps(row.candidate_eurio_ids, ensure_ascii=False) if row.candidate_eurio_ids is not None else None

    if existing:
        aid = existing["id"] if isinstance(existing, sqlite3.Row) else existing[0]
        conn.execute(
            """
            UPDATE image_assets SET
              bbox_json=COALESCE(?, bbox_json),
              detection_method=COALESCE(?, detection_method),
              eurio_id=?,
              resolution_status=?,
              resolution_confidence=?,
              resolution_attempts_json=COALESCE(?, resolution_attempts_json),
              candidate_eurio_ids_json=COALESCE(?, candidate_eurio_ids_json),
              face=COALESCE(?, face),
              variant_kind=?,
              quality_score=COALESCE(?, quality_score),
              training_eligible=?,
              quality_reason=COALESCE(?, quality_reason),
              quality_pipeline_version=COALESCE(?, quality_pipeline_version),
              phash=COALESCE(?, phash),
              storage_path=?,
              width=COALESCE(?, width), height=COALESCE(?, height),
              sha256=COALESCE(?, sha256),
              run_id=COALESCE(?, run_id),
              resolved_at=CASE
                WHEN resolution_status != ? THEN datetime('now')
                ELSE resolved_at
              END
            WHERE id=?
            """,
            (
                bbox,
                row.detection_method,
                row.eurio_id,
                row.resolution_status,
                row.resolution_confidence,
                attempts,
                candidates,
                row.face,
                row.variant_kind,
                row.quality_score,
                int(row.training_eligible),
                row.quality_reason,
                row.quality_pipeline_version,
                row.phash,
                row.storage_path,
                row.width, row.height,
                row.sha256,
                row.run_id,
                row.resolution_status,
                aid,
            ),
        )
        return aid

    aid = row.id or uuid.uuid4().hex
    conn.execute(
        """
        INSERT INTO image_assets (
          id, source_image_id, crop_index, bbox_json, detection_method,
          eurio_id, resolution_status, resolution_confidence,
          resolution_attempts_json, candidate_eurio_ids_json,
          face, variant_kind,
          quality_score, training_eligible, quality_reason, quality_pipeline_version,
          phash, storage_path, width, height, sha256, run_id
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            aid, row.source_image_id, row.crop_index, bbox, row.detection_method,
            row.eurio_id, row.resolution_status, row.resolution_confidence,
            attempts, candidates,
            row.face, row.variant_kind,
            row.quality_score, int(row.training_eligible), row.quality_reason, row.quality_pipeline_version,
            row.phash, row.storage_path, row.width, row.height, row.sha256, row.run_id,
        ),
    )
    return aid


def upsert_coin_market_quote(conn: sqlite3.Connection, row: CoinMarketQuoteRow) -> str:
    """Insert or update by (source, eurio_id, period_start, condition_raw).

    Note: unique key uses `condition_raw` (not `condition_normalized`)
    so fine grades like 'SUP-62' vs 'FDC' don't collide. See schema.md.
    """
    existing = conn.execute(
        """
        SELECT id FROM coin_market_quotes
         WHERE source=? AND eurio_id=? AND period_start=?
           AND COALESCE(condition_raw,'') = COALESCE(?, '')
        """,
        (row.source, row.eurio_id, row.period_start, row.condition_raw),
    ).fetchone()
    payload = json.dumps(row.raw_payload, ensure_ascii=False) if row.raw_payload else None
    if existing:
        qid = existing["id"] if isinstance(existing, sqlite3.Row) else existing[0]
        conn.execute(
            """
            UPDATE coin_market_quotes SET
              condition_normalized=?, currency=?,
              p10=?, p50=?, p90=?, sample_size=?,
              period_end=?,
              raw_payload_json=COALESCE(?, raw_payload_json),
              run_id=COALESCE(?, run_id),
              fetched_at=datetime('now')
            WHERE id=?
            """,
            (
                row.condition_normalized, row.currency,
                row.p10, row.p50, row.p90, row.sample_size,
                row.period_end,
                payload, row.run_id, qid,
            ),
        )
        return qid

    qid = uuid.uuid4().hex
    conn.execute(
        """
        INSERT INTO coin_market_quotes (
          id, eurio_id, source, condition_raw, condition_normalized,
          currency, p10, p50, p90, sample_size,
          period_start, period_end, raw_payload_json, run_id
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            qid, row.eurio_id, row.source, row.condition_raw, row.condition_normalized,
            row.currency, row.p10, row.p50, row.p90, row.sample_size,
            row.period_start, row.period_end, payload, row.run_id,
        ),
    )
    return qid


def insert_pending_quote(conn: sqlite3.Connection, row: PendingQuoteRow) -> str:
    """Insert a pending quote linked to a not-yet-resolved source_image."""
    pid = uuid.uuid4().hex
    payload = json.dumps(row.raw_payload, ensure_ascii=False) if row.raw_payload else None
    conn.execute(
        """
        INSERT INTO pending_quotes (
          id, source_image_id, source, price, currency, condition_raw, raw_payload_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (pid, row.source_image_id, row.source, row.price, row.currency, row.condition_raw, payload),
    )
    return pid


def upsert_discovery_log(
    conn: sqlite3.Connection,
    *,
    source: str,
    source_ref: str,
    query_signature: str | None,
    run_id: str | None,
) -> tuple[str, bool]:
    """Insert or refresh a `discovery_log` row.

    Returns `(row_id, is_new)` so the caller can count truly new
    discoveries vs re-discoveries. Preserves `first_seen_at` and
    `pipeline_state` on update — only `last_seen_at`, `last_run_id`
    and `query_signature` are refreshed.
    """
    existing = conn.execute(
        "SELECT id FROM discovery_log WHERE source = ? AND source_ref = ?",
        (source, source_ref),
    ).fetchone()
    if existing:
        rid = existing["id"] if isinstance(existing, sqlite3.Row) else existing[0]
        conn.execute(
            """
            UPDATE discovery_log
               SET last_seen_at = datetime('now'),
                   last_run_id = ?,
                   query_signature = COALESCE(?, query_signature)
             WHERE id = ?
            """,
            (run_id, query_signature, rid),
        )
        return rid, False

    rid = uuid.uuid4().hex
    conn.execute(
        """
        INSERT INTO discovery_log (id, source, source_ref, query_signature, last_run_id)
        VALUES (?, ?, ?, ?, ?)
        """,
        (rid, source, source_ref, query_signature, run_id),
    )
    return rid, True


def set_discovery_pipeline_state(
    conn: sqlite3.Connection,
    *,
    source: str,
    source_ref: str,
    state: str,
) -> None:
    """Advance `discovery_log.pipeline_state` for one item.

    Valid states are enforced by the table CHECK constraint
    ('discovered'|'persisted'|'downloaded'|'cropped'|'resolved'|'rejected').
    """
    conn.execute(
        """
        UPDATE discovery_log
           SET pipeline_state = ?
         WHERE source = ? AND source_ref = ?
        """,
        (state, source, source_ref),
    )


def delete_pending_quotes_for(conn: sqlite3.Connection, source_image_id: str) -> int:
    """Used when promoting a pending_quote to coin_market_quotes after review."""
    cur = conn.execute(
        "DELETE FROM pending_quotes WHERE source_image_id = ?", (source_image_id,)
    )
    return cur.rowcount or 0


# ── Discovery searches (per-call API debug log) ─────────────────────────────


@dataclass
class DiscoverySearchRecord:
    """One adapter.discover() logical call, persisted for debug.

    Funnel ventilé (chunk 0 auto-validation — "visibilité du stream") :

    - ``n_summaries``    — N0 : ``itemSummaries`` retournés brut par la
                           search API, avant toute expansion ou filtre.
    - ``n_after_groups`` — N1 : N0 + lignes ajoutées par expansion type
                           ``getItemsByGroup`` (top-K limité).
    - ``n_raw_results``  — N2 : après theme-token drop (silencieux si non
                           ambigu). Alias historique.
    - ``n_kept_results`` — N3 : après ``accept_listing`` (noise_title,
                           year_mismatch, prix, devise…).

    Pour les sources sans étape ``groups`` ou ``theme drop`` (ex. mock,
    numista), N0 = N1 = N2. Quand l'API errored out, tous les compteurs
    restent NULL.
    """

    run_id: str
    source: str
    target_eurio_id: str | None = None
    endpoint: str | None = None
    query_q: str | None = None
    query_filters: dict[str, Any] | None = None
    status: str = "success"  # 'success' | 'empty' | 'failed'
    http_status: int | None = None
    n_summaries: int | None = None
    n_after_groups: int | None = None
    n_raw_results: int | None = None
    n_kept_results: int | None = None
    duration_ms: int | None = None
    error: str | None = None
    # eBay multi-mkt (B4). Identifie le marketplace ciblé par cette
    # discovery search (1 row par run × eurio × marketplace).
    marketplace: str | None = None
    # F3 — URL d'appel Browse exacte (q + params résolus). NULL si l'appel
    # n'a pas atteint le serveur (erreur réseau).
    browse_url: str | None = None


def record_discarded_listing(
    conn: sqlite3.Connection,
    *,
    run_id: str | None,
    source: str,
    source_ref: str,
    target_eurio_id: str | None,
    reason: str,
    title: str | None = None,
    raw_payload: dict[str, Any] | None = None,
    marketplace: str | None = None,
) -> str:
    """Trace un listing rejeté par accept_listing avant ingestion.

    But : audit. Si on assouplit une règle plus tard, on peut interroger
    cette table pour évaluer combien de listings auraient passé le filtre.
    """
    rid = uuid.uuid4().hex
    payload_json = json.dumps(raw_payload) if raw_payload is not None else None
    conn.execute(
        """
        INSERT INTO discarded_listings (
          id, run_id, source, source_ref, target_eurio_id,
          reason, title, raw_payload, marketplace
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (rid, run_id, source, source_ref, target_eurio_id, reason, title,
         payload_json, marketplace),
    )
    return rid


def record_discovery_search(conn: sqlite3.Connection, rec: DiscoverySearchRecord) -> str:
    """Insert one row in discovery_searches. Returns its id."""
    rid = uuid.uuid4().hex
    filters_json = json.dumps(rec.query_filters) if rec.query_filters is not None else None
    conn.execute(
        """
        INSERT INTO discovery_searches (
          id, run_id, source, target_eurio_id, endpoint,
          query_q, query_filters_json, status, http_status,
          n_summaries, n_after_groups, n_raw_results, n_kept_results,
          duration_ms, error, marketplace, browse_url
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            rid, rec.run_id, rec.source, rec.target_eurio_id, rec.endpoint,
            rec.query_q, filters_json, rec.status, rec.http_status,
            rec.n_summaries, rec.n_after_groups,
            rec.n_raw_results, rec.n_kept_results,
            rec.duration_ms, rec.error, rec.marketplace, rec.browse_url,
        ),
    )
    return rid
