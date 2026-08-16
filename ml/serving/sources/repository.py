"""Accès SQL pur pour le domaine `sources`.

Aucune logique métier ici — uniquement SELECT sur ``eurio.db``. Pas de
``HTTPException`` (exceptions Python typées). Repositories prennent une
``sqlite3.Connection`` injectée via la dépendance `serving.deps.db_connection`.

Cf. ARCHITECTURE.md §2.2.
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta, timezone
from typing import Any

from .models import (
    DiscardedListing,
    DiscardedReasonGroup,
    DiscoverySearchItem,
    FreshnessBuckets,
    FreshnessGroupItem,
    FunnelStep,
    ListingCropAsset,
    ListingDetail,
    MarketQuoteEntry,
    RunBreakdown,
    RunBreakdownEntry,
    RunDiscarded,
    RunFunnel,
    RunListings,
    RunSearches,
    RunSnapshot,
    SourceRunListItem,
)

# Pipeline steps (cf. sources._base.run_logger.PIPELINE_STEPS). Reproduit en
# constante locale car le module ml/sources/ n'est pas livré dans l'image lean.
PIPELINE_STEPS: tuple[str, ...] = (
    "discover", "persist", "text_signal", "download", "detect",
    "resolve", "auto_validate", "enqueue", "price_aggregate",
)

_AUTO_STATUSES = ("auto_name", "auto_phash", "manual")
_PENDING_STATUSES = ("pending_match", "pending_crop", "needs_review")
_STALE_DAYS = 90


# ─── Exceptions ─────────────────────────────────────────────────────────────


class SourceRunNotFound(Exception):
    """Lève par get_run / get_funnel / etc. quand run_id introuvable."""


class SourceNotFound(Exception):
    """Lève par get_source quand source_id introuvable dans source_registry."""


# ─── Helpers communs ────────────────────────────────────────────────────────


def _parse_filters(filters_json: str | None) -> dict[str, Any]:
    if not filters_json:
        return {}
    try:
        return json.loads(filters_json)
    except json.JSONDecodeError:
        return {"_raw": filters_json}


def _duration_s(started_at: str | None, ended_at: str | None) -> float | None:
    if not (started_at and ended_at):
        return None
    try:
        t0 = datetime.fromisoformat(started_at.replace(" ", "T"))
        t1 = datetime.fromisoformat(ended_at.replace(" ", "T"))
        return (t1 - t0).total_seconds()
    except ValueError:
        return None


def _row_to_snapshot(row: sqlite3.Row, *, n_downloads_failed: int = 0) -> RunSnapshot:
    return RunSnapshot(
        id=row["id"],
        source=row["source"],
        kind=row["kind"],
        status=row["status"],
        current_step=row["current_step"],
        started_at=row["started_at"],
        ended_at=row["ended_at"],
        duration_s=_duration_s(row["started_at"], row["ended_at"]),
        n_calls=row["n_calls"],
        n_raws_added=row["n_raws_added"],
        n_crops_added=row["n_crops_added"],
        n_quotes_added=row["n_quotes_added"],
        n_pending_added=row["n_pending_added"],
        n_auto_resolved=row["n_auto_resolved"],
        n_review_enqueued=row["n_review_enqueued"],
        n_errors=row["n_errors"],
        n_downloads_failed=n_downloads_failed,
        filters=_parse_filters(row["filters_json"]),
        error_summary=row["error_summary"],
        log_path=row["log_path"],
    )


def _count_downloads_failed(conn: sqlite3.Connection, run_id: str) -> int:
    row = conn.execute(
        "SELECT count(*) AS n FROM source_images "
        "WHERE run_id = ? AND download_status = 'failed'",
        (run_id,),
    ).fetchone()
    return int(row["n"] or 0)


# ─── /source-runs/{run_id} ──────────────────────────────────────────────────


def get_run(conn: sqlite3.Connection, run_id: str) -> RunSnapshot:
    row = conn.execute(
        "SELECT * FROM source_runs WHERE id = ?",
        (run_id,),
    ).fetchone()
    if row is None:
        raise SourceRunNotFound(run_id)
    return _row_to_snapshot(row, n_downloads_failed=_count_downloads_failed(conn, run_id))


# ─── /sources/{id}/runs ─────────────────────────────────────────────────────


def list_runs_for_source(
    conn: sqlite3.Connection,
    *,
    source_id: str,
    limit: int,
    status: str | None,
) -> list[SourceRunListItem]:
    sql = "SELECT * FROM source_runs WHERE source = ?"
    args: list[Any] = [source_id]
    if status:
        sql += " AND status = ?"
        args.append(status)
    sql += " ORDER BY started_at DESC LIMIT ?"
    args.append(limit)
    rows = conn.execute(sql, args).fetchall()

    out: list[SourceRunListItem] = []
    for r in rows:
        snap = _row_to_snapshot(r)
        out.append(SourceRunListItem(
            id=snap.id,
            started_at=snap.started_at,
            kind=snap.kind,
            duration_s=snap.duration_s or 0.0,
            n_calls=snap.n_calls,
            n_images=snap.n_raws_added + snap.n_crops_added,
            n_quotes=snap.n_quotes_added,
            n_errors=snap.n_errors,
            status=snap.status,
            filters=snap.filters,
            log_path=snap.log_path or "",
        ))
    return out


# ─── /source-runs/{run_id}/funnel ───────────────────────────────────────────


def _funnel_steps(current_step: str | None, run_status: str) -> list[FunnelStep]:
    if run_status in ("success", "partial"):
        return [FunnelStep(name=s, status="done") for s in PIPELINE_STEPS]
    idx = PIPELINE_STEPS.index(current_step) if current_step in PIPELINE_STEPS else -1
    out: list[FunnelStep] = []
    for i, step in enumerate(PIPELINE_STEPS):
        if i < idx:
            status = "done"
        elif i == idx:
            status = "failed" if run_status == "failed" else "running"
        else:
            status = "pending"
        out.append(FunnelStep(name=step, status=status))
    return out


def get_run_funnel(conn: sqlite3.Connection, run_id: str) -> RunFunnel:
    run = conn.execute(
        "SELECT * FROM source_runs WHERE id = ?", (run_id,),
    ).fetchone()
    if run is None:
        raise SourceRunNotFound(run_id)

    disc = conn.execute(
        """
        SELECT COUNT(*) n, COALESCE(SUM(n_summaries),0) s0,
               COALESCE(SUM(n_after_groups),0) s1,
               COALESCE(SUM(n_kept_results),0) s3
          FROM discovery_searches WHERE run_id = ?
        """,
        (run_id,),
    ).fetchone()

    crop_rows = conn.execute(
        "SELECT crop_status, COUNT(*) n FROM source_images "
        "WHERE run_id = ? GROUP BY crop_status",
        (run_id,),
    ).fetchall()
    n_cropped = n_zero = n_crop_pending = 0
    for r in crop_rows:
        if r["crop_status"] == "success":
            n_cropped = r["n"]
        elif r["crop_status"] == "zero_crops":
            n_zero = r["n"]
        else:
            n_crop_pending += r["n"]
    n_images = n_cropped + n_zero + n_crop_pending

    by_reason_rows = conn.execute(
        "SELECT reason, COUNT(*) n FROM discarded_listings "
        "WHERE run_id = ? GROUP BY reason ORDER BY n DESC, reason ASC",
        (run_id,),
    ).fetchall()
    discards = [
        DiscardedReasonGroup(reason=r["reason"], count=int(r["n"]))
        for r in by_reason_rows
    ]

    return RunFunnel(
        run_id=run_id,
        source_id=run["source"],
        status=run["status"],
        current_step=run["current_step"],
        duration_s=_duration_s(run["started_at"], run["ended_at"]),
        n_errors=run["n_errors"] or 0,
        error_summary=run["error_summary"],
        steps=_funnel_steps(run["current_step"], run["status"]),
        n_searches=int(disc["n"]),
        n_summaries=int(disc["s0"]),
        n_after_groups=int(disc["s1"]),
        n_kept=int(disc["s3"]),
        n_images=n_images,
        n_cropped=n_cropped,
        n_zero_crops=n_zero,
        n_crop_pending=n_crop_pending,
        n_discarded=sum(g.count for g in discards),
        discards=discards,
        n_review_enqueued=run["n_review_enqueued"] or 0,
        n_pending_quotes=run["n_pending_added"] or 0,
        n_quotes=run["n_quotes_added"] or 0,
    )


# ─── /source-runs/{run_id}/listings ─────────────────────────────────────────


def get_run_listings(
    conn: sqlite3.Connection,
    *,
    run_id: str,
    eurio_id: str | None,
) -> RunListings:
    # On valide d'abord le run pour distinguer 404 d'un run-vide.
    run = conn.execute(
        "SELECT id, source FROM source_runs WHERE id = ?", (run_id,),
    ).fetchone()
    if run is None:
        raise SourceRunNotFound(run_id)

    sql = """
        SELECT id AS source_image_id, source_ref, source_url, target_eurio_id,
               listing_title, listing_country, listing_year, listing_price,
               listing_currency, seller_id, is_lot_suspected, fetched_at,
               download_endpoint, download_status, download_http_status, download_error,
               crop_status, crop_error, n_crops_detected,
               route_decision, route_reason
          FROM source_images
         WHERE run_id = ?
    """
    params: list[Any] = [run_id]
    if eurio_id is not None:
        sql += " AND target_eurio_id = ?"
        params.append(eurio_id)
    sql += " ORDER BY fetched_at ASC, source_ref ASC"

    rows = conn.execute(sql, params).fetchall()
    if not rows:
        return RunListings(run_id=run_id, source_id=run["source"], listings=[])

    sids = [r["source_image_id"] for r in rows]
    placeholders = ",".join("?" * len(sids))
    asset_rows = conn.execute(
        f"""
        SELECT a.id AS asset_id, a.source_image_id, a.crop_index,
               a.resolution_status, a.eurio_id,
               rq.id AS review_id, rq.kind AS review_kind
          FROM image_assets a
          LEFT JOIN review_queue rq ON rq.image_asset_id = a.id
         WHERE a.source_image_id IN ({placeholders})
         ORDER BY a.source_image_id, a.crop_index
        """,
        sids,
    ).fetchall()

    crops_by_sid: dict[str, list[ListingCropAsset]] = {}
    for ar in asset_rows:
        crops_by_sid.setdefault(ar["source_image_id"], []).append(
            ListingCropAsset(
                asset_id=ar["asset_id"],
                crop_index=ar["crop_index"],
                resolution_status=ar["resolution_status"],
                eurio_id=ar["eurio_id"],
                review_id=ar["review_id"],
                review_kind=ar["review_kind"],
            )
        )

    listings = [
        ListingDetail(
            source_image_id=r["source_image_id"],
            source_ref=r["source_ref"],
            source_url=r["source_url"],
            target_eurio_id=r["target_eurio_id"],
            listing_title=r["listing_title"],
            listing_country=r["listing_country"],
            listing_year=r["listing_year"],
            listing_price=r["listing_price"],
            listing_currency=r["listing_currency"],
            seller_id=r["seller_id"],
            is_lot_suspected=bool(r["is_lot_suspected"]),
            fetched_at=r["fetched_at"],
            download_endpoint=r["download_endpoint"],
            download_status=r["download_status"],
            download_http_status=r["download_http_status"],
            download_error=r["download_error"],
            crop_status=r["crop_status"],
            crop_error=r["crop_error"],
            n_crops_detected=r["n_crops_detected"],
            route_decision=r["route_decision"],
            route_reason=r["route_reason"],
            crops=crops_by_sid.get(r["source_image_id"], []),
        )
        for r in rows
    ]
    return RunListings(run_id=run_id, source_id=run["source"], listings=listings)


# ─── /source-runs/{run_id}/searches ─────────────────────────────────────────


def get_run_searches(
    conn: sqlite3.Connection,
    *,
    run_id: str,
    eurio_id: str | None,
) -> RunSearches:
    run = conn.execute(
        "SELECT source FROM source_runs WHERE id = ?", (run_id,),
    ).fetchone()
    if run is None:
        raise SourceRunNotFound(run_id)

    sql = """
        SELECT id, target_eurio_id, endpoint, query_q, query_filters_json,
               status, http_status,
               n_summaries, n_after_groups, n_raw_results, n_kept_results,
               duration_ms, error, marketplace, browse_url, created_at
          FROM discovery_searches
         WHERE run_id = ?
    """
    params: list[Any] = [run_id]
    if eurio_id is not None:
        # Une recherche groupée a target_eurio_id NULL — on couvre alors le
        # groupe (denom, pays, année) auquel appartient eurio_id.
        coin = conn.execute(
            "SELECT face_value, country, year FROM coins WHERE eurio_id = ?",
            (eurio_id,),
        ).fetchone()
        if coin is not None:
            sql += (
                " AND ( target_eurio_id = ?"
                "       OR ( json_extract(query_filters_json, '$.group.denomination') = ?"
                "            AND json_extract(query_filters_json, '$.group.country') = ?"
                "            AND json_extract(query_filters_json, '$.group.year') = ? ) )"
            )
            params += [eurio_id, coin["face_value"], coin["country"], coin["year"]]
        else:
            sql += " AND target_eurio_id = ?"
            params.append(eurio_id)
    sql += " ORDER BY created_at ASC"

    rows = conn.execute(sql, params).fetchall()
    searches = [
        DiscoverySearchItem(
            id=r["id"],
            target_eurio_id=r["target_eurio_id"],
            endpoint=r["endpoint"],
            query_q=r["query_q"],
            query_filters=json.loads(r["query_filters_json"]) if r["query_filters_json"] else None,
            status=r["status"],
            http_status=r["http_status"],
            n_summaries=r["n_summaries"],
            n_after_groups=r["n_after_groups"],
            n_raw_results=r["n_raw_results"],
            n_kept_results=r["n_kept_results"],
            duration_ms=r["duration_ms"],
            error=r["error"],
            marketplace=r["marketplace"],
            browse_url=r["browse_url"],
            created_at=r["created_at"],
        )
        for r in rows
    ]
    return RunSearches(run_id=run_id, source_id=run["source"], searches=searches)


# ─── /source-runs/{run_id}/discarded ────────────────────────────────────────


def get_run_discarded(
    conn: sqlite3.Connection,
    *,
    run_id: str,
    eurio_id: str | None,
    reason: str | None,
) -> RunDiscarded:
    run = conn.execute(
        "SELECT source FROM source_runs WHERE id = ?", (run_id,),
    ).fetchone()
    if run is None:
        raise SourceRunNotFound(run_id)

    sql = """
        SELECT id, source_ref, target_eurio_id, reason, title,
               raw_payload, created_at
          FROM discarded_listings
         WHERE run_id = ?
    """
    params: list[Any] = [run_id]
    if eurio_id is not None:
        sql += " AND target_eurio_id = ?"
        params.append(eurio_id)
    if reason is not None:
        sql += " AND reason = ?"
        params.append(reason)
    sql += " ORDER BY created_at ASC"

    rows = conn.execute(sql, params).fetchall()

    listings: list[DiscardedListing] = []
    for r in rows:
        payload: dict[str, Any] | None = None
        if r["raw_payload"]:
            try:
                payload = json.loads(r["raw_payload"])
            except (TypeError, ValueError):
                payload = None
        item_id = (payload or {}).get("item_id") if payload else None
        item_web_url = (payload or {}).get("item_web_url") if payload else None
        price = (payload or {}).get("price") if payload else None
        currency = (payload or {}).get("currency") if payload else None
        listings.append(DiscardedListing(
            id=r["id"],
            source_ref=r["source_ref"],
            target_eurio_id=r["target_eurio_id"],
            reason=r["reason"],
            title=r["title"],
            item_id=str(item_id) if item_id is not None else None,
            item_web_url=item_web_url if isinstance(item_web_url, str) else None,
            price=float(price) if isinstance(price, (int, float)) else None,
            currency=currency if isinstance(currency, str) else None,
            raw_payload=payload,
            created_at=r["created_at"],
        ))

    by_reason_rows = conn.execute(
        """
        SELECT reason, COUNT(*) AS n
          FROM discarded_listings
         WHERE run_id = ?
         GROUP BY reason
         ORDER BY n DESC, reason ASC
        """,
        (run_id,),
    ).fetchall()
    by_reason = [
        DiscardedReasonGroup(reason=r["reason"], count=int(r["n"]))
        for r in by_reason_rows
    ]
    total = sum(g.count for g in by_reason)

    return RunDiscarded(
        run_id=run_id,
        source_id=run["source"],
        total=total,
        by_reason=by_reason,
        listings=listings,
    )


# ─── /source-runs/{run_id}/breakdown ────────────────────────────────────────


def _search_axis_stats(
    conn: sqlite3.Connection, *, run_id: str, eurio_id: str,
) -> dict[str, int]:
    cands_pattern = f'%"{eurio_id}"%'
    n_listings = conn.execute(
        """
        SELECT COUNT(*) AS n
          FROM source_images si
         WHERE si.run_id = ?
           AND (
             si.target_eurio_id = ?
             OR (si.target_eurio_id IS NULL
                 AND si.raw_payload_json LIKE ?)
           )
        """,
        (run_id, eurio_id, cands_pattern),
    ).fetchone()["n"]

    crops = conn.execute(
        """
        SELECT DISTINCT ia.id, ia.resolution_status
          FROM image_assets ia
          JOIN source_images si ON si.id = ia.source_image_id
         WHERE ia.run_id = ?
           AND (
             si.target_eurio_id = ?
             OR (si.target_eurio_id IS NULL
                 AND ia.candidate_eurio_ids_json LIKE ?)
           )
        """,
        (run_id, eurio_id, cands_pattern),
    ).fetchall()

    n_auto = n_pending = n_rejected = 0
    review_assets: list[str] = []
    for c in crops:
        st = c["resolution_status"]
        if st in _AUTO_STATUSES:
            n_auto += 1
        elif st == "rejected":
            n_rejected += 1
        else:
            review_assets.append(c["id"])
            if st in _PENDING_STATUSES:
                n_pending += 1

    n_rev_single = n_rev_lot = 0
    if review_assets:
        placeholders = ",".join("?" * len(review_assets))
        rows = conn.execute(
            f"SELECT kind, COUNT(*) AS n FROM review_queue "
            f"WHERE status = 'open' AND image_asset_id IN ({placeholders}) "
            f"GROUP BY kind",
            review_assets,
        ).fetchall()
        for r in rows:
            if r["kind"] == "single":
                n_rev_single = r["n"]
            elif r["kind"] == "lot":
                n_rev_lot = r["n"]
        n_pending = max(0, n_pending - (n_rev_single + n_rev_lot))

    return {
        "n_listings": n_listings,
        "n_crops_searched": len(crops),
        "n_searched_auto": n_auto,
        "n_searched_review_single": n_rev_single,
        "n_searched_review_lot": n_rev_lot,
        "n_searched_pending": n_pending,
        "n_searched_rejected": n_rejected,
    }


def _attribution_axis_stats(
    conn: sqlite3.Connection, *, run_id: str, eurio_id: str,
) -> int:
    n = conn.execute(
        """
        SELECT COUNT(*) AS n
          FROM image_assets ia
          JOIN source_images si ON si.id = ia.source_image_id
         WHERE ia.run_id = ?
           AND ia.eurio_id = ?
           AND (si.target_eurio_id IS NULL OR si.target_eurio_id != ?)
        """,
        (run_id, eurio_id, eurio_id),
    ).fetchone()["n"]
    return int(n or 0)


def _has_lot_context(
    conn: sqlite3.Connection, *, run_id: str, eurio_id: str,
) -> bool:
    row = conn.execute(
        """
        SELECT 1
          FROM source_images si
         WHERE si.run_id = ?
           AND (
             si.target_eurio_id = ?
             OR EXISTS (
               SELECT 1 FROM image_assets ia
                WHERE ia.source_image_id = si.id
                  AND ia.run_id = ?
                  AND ia.eurio_id = ?
             )
           )
           AND (
             si.is_lot_suspected = 1
             OR (
               SELECT COUNT(*) FROM image_assets ia2
                WHERE ia2.source_image_id = si.id
             ) > 1
           )
         LIMIT 1
        """,
        (run_id, eurio_id, run_id, eurio_id),
    ).fetchone()
    return row is not None


def _quotes_for(
    conn: sqlite3.Connection, *, run_id: str, eurio_id: str,
) -> int:
    return conn.execute(
        "SELECT COUNT(*) AS n FROM coin_market_quotes "
        "WHERE run_id = ? AND eurio_id = ?",
        (run_id, eurio_id),
    ).fetchone()["n"]


def _marketplaces_for(
    conn: sqlite3.Connection, *, run_id: str, eurio_id: str,
) -> list[str]:
    rows = conn.execute(
        """
        SELECT DISTINCT marketplace
          FROM source_images
         WHERE run_id = ? AND target_eurio_id = ? AND marketplace IS NOT NULL
         ORDER BY marketplace
        """,
        (run_id, eurio_id),
    ).fetchall()
    return [r["marketplace"] for r in rows]


def get_run_breakdown(
    conn: sqlite3.Connection, run_id: str,
) -> RunBreakdown:
    row = conn.execute(
        "SELECT * FROM source_runs WHERE id = ?", (run_id,),
    ).fetchone()
    if row is None:
        raise SourceRunNotFound(run_id)
    filters = _parse_filters(row["filters_json"])

    targeted_set: set[str] = set()
    targeted_ordered: list[str] = []
    groups = filters.get("discovery_groups")
    if isinstance(groups, list) and groups:
        for g in groups:
            if not isinstance(g, dict):
                continue
            try:
                coin_rows = conn.execute(
                    "SELECT eurio_id FROM coins "
                    "WHERE face_value = ? AND country = ? AND year = ? "
                    "AND is_commemorative = 1 ORDER BY eurio_id",
                    (g["denomination"], g["country"], g["year"]),
                ).fetchall()
            except (KeyError, sqlite3.Error):
                continue
            for r in coin_rows:
                eid = r["eurio_id"]
                if eid not in targeted_set:
                    targeted_set.add(eid)
                    targeted_ordered.append(eid)
    else:
        raw_targets = filters.get("target_eurio_ids") or []
        if not isinstance(raw_targets, list):
            raw_targets = []
        for eid in raw_targets:
            if isinstance(eid, str) and eid not in targeted_set:
                targeted_set.add(eid)
                targeted_ordered.append(eid)

    resolved_rows = conn.execute(
        """
        SELECT DISTINCT eurio_id
          FROM image_assets
         WHERE run_id = ? AND eurio_id IS NOT NULL
        """,
        (run_id,),
    ).fetchall()
    discovered_ordered = sorted(
        r["eurio_id"] for r in resolved_rows
        if r["eurio_id"] not in targeted_set
    )

    def _build_entry(eid: str, *, was_targeted: bool) -> RunBreakdownEntry:
        search_stats = _search_axis_stats(conn, run_id=run_id, eurio_id=eid)
        return RunBreakdownEntry(
            eurio_id=eid,
            was_targeted=was_targeted,
            n_attributed_from_other=_attribution_axis_stats(conn, run_id=run_id, eurio_id=eid),
            via_lot=_has_lot_context(conn, run_id=run_id, eurio_id=eid),
            n_quotes=_quotes_for(conn, run_id=run_id, eurio_id=eid),
            marketplaces=_marketplaces_for(conn, run_id=run_id, eurio_id=eid),
            **search_stats,
        )

    per_eurio = [
        _build_entry(eid, was_targeted=True) for eid in targeted_ordered
    ] + [
        _build_entry(eid, was_targeted=False) for eid in discovered_ordered
    ]

    return RunBreakdown(
        run_id=row["id"],
        source_id=row["source"],
        started_at=row["started_at"],
        status=row["status"],
        filters=filters,
        per_eurio=per_eurio,
    )


# ─── /source-runs/{run_id}/log ──────────────────────────────────────────────


def get_run_log_meta(
    conn: sqlite3.Connection, run_id: str,
) -> tuple[str, str | None]:
    """Renvoie (status, log_path). 404 si run inconnu."""
    row = conn.execute(
        "SELECT log_path, status FROM source_runs WHERE id = ?", (run_id,),
    ).fetchone()
    if row is None:
        raise SourceRunNotFound(run_id)
    return row["status"], row["log_path"]


def read_run_log_tail(log_path: str, tail: int) -> str | None:
    """Tail des `tail` dernières lignes du fichier `log_path`.

    Le répertoire racine vient de `EURIO_RUN_LOGS_DIR` (défaut
    `/srv/ml/state` — emplacement de `state/` côté lean image VPS).
    Retourne None si le fichier n'existe pas (run pré-câblage logs ou
    fichier purgé / pas synchronisé sur lean).
    """
    import os
    from pathlib import Path
    root = Path(os.environ.get("EURIO_RUN_LOGS_DIR", "/srv/ml/state"))
    candidate = root / log_path
    if not candidate.is_file():
        return None
    lines = candidate.read_text(encoding="utf-8", errors="replace").splitlines()
    return "\n".join(lines[-tail:])


# ─── /sources/ebay/quota-status ─────────────────────────────────────────────


EBAY_DAILY_QUOTA = 5000
_ESTIMATE_BOOTSTRAP = 7
_ESTIMATE_SAFETY_FACTOR = 1.3


def _today_period() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def ebay_calls_today() -> int:
    """Lu via le `QuotaTracker` qui écrit, pas via le canonique — cf. B1
    (`docs/work-in-progress/scan-quality/pipeline-findings-and-debt.md`).

    ⚠️ Ne PAS importer `sources.market.ebay_client` ici pour la limite :
    `infra/eurio-api/Dockerfile` ne copie pas `ml/sources` dans l'image lean
    (« On NE copie PAS sources/vision/training »), et ce module tourne sous
    `server_serve.py`. L'import lèverait `ModuleNotFoundError` à la requête,
    donc un 500 sur `/sources/ebay/quota-status`. La constante locale
    `EBAY_DAILY_QUOTA` porte la même valeur.
    """
    from shared.api_quota import QuotaTracker

    return QuotaTracker("ebay", "daily", EBAY_DAILY_QUOTA).total().calls


def _count_group_coins(
    conn: sqlite3.Connection, denomination: float, country: str, year: int,
) -> int:
    row = conn.execute(
        "SELECT count(*) AS n FROM coins "
        "WHERE face_value = ? AND country = ? AND year = ? "
        "AND is_commemorative = 1",
        (denomination, country, year),
    ).fetchone()
    return int(row["n"] or 0)


def _filters_targets_count(conn: sqlite3.Connection, filters_json: str | None) -> int:
    if not filters_json:
        return 1
    try:
        f = json.loads(filters_json)
    except json.JSONDecodeError:
        return 1
    groups = f.get("discovery_groups")
    if groups:
        total = sum(
            _count_group_coins(conn, g["denomination"], g["country"], g["year"])
            for g in groups
        )
        return max(total, 1)
    if f.get("target_eurio_ids"):
        return max(len(f["target_eurio_ids"]), 1)
    return 1


def estimate_calls_per_eurio_id(conn: sqlite3.Connection) -> float:
    rows = conn.execute(
        """
        SELECT n_calls, filters_json
          FROM source_runs
         WHERE source = 'ebay'
           AND status IN ('success', 'partial')
           AND n_calls > 0
         ORDER BY started_at DESC
         LIMIT 5
        """
    ).fetchall()
    if len(rows) < 3:
        return float(_ESTIMATE_BOOTSTRAP)
    ratios = [
        r["n_calls"] / _filters_targets_count(conn, r["filters_json"])
        for r in rows
    ]
    return sum(ratios) / len(ratios)


def ebay_quota_status(conn: sqlite3.Connection) -> dict[str, Any]:
    calls = ebay_calls_today()
    return {
        "calls_today": calls,
        "limit": EBAY_DAILY_QUOTA,
        "remaining": max(EBAY_DAILY_QUOTA - calls, 0),
        "exhausted": calls >= EBAY_DAILY_QUOTA,
        "period": _today_period(),
        "avg_calls_per_eurio_id": round(estimate_calls_per_eurio_id(conn), 2),
    }


# ─── /sources/ebay/freshness-groups ─────────────────────────────────────────


def _classify_freshness(last_enriched_at: str | None) -> str:
    if last_enriched_at is None:
        return "never"
    try:
        dt = datetime.fromisoformat(last_enriched_at.replace(" ", "T"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
    except ValueError:
        return "never"
    if datetime.now(timezone.utc) - dt > timedelta(days=_STALE_DAYS):
        return "stale"
    return "fresh"


def ebay_freshness_groups(
    conn: sqlite3.Connection, limit: int,
) -> tuple[list[FreshnessGroupItem], FreshnessBuckets]:
    all_rows = conn.execute(
        """
        SELECT denomination, country, year, n_coins,
               last_enriched_at, n_images, n_crops
          FROM v_ebay_freshness_groups
         ORDER BY last_enriched_at ASC NULLS FIRST, country, year
        """
    ).fetchall()

    buckets = {"never": 0, "stale": 0, "fresh": 0}
    classified: list[tuple[sqlite3.Row, str]] = []
    for r in all_rows:
        status = _classify_freshness(r["last_enriched_at"])
        buckets[status] += 1
        classified.append((r, status))

    items = [
        FreshnessGroupItem(
            denomination=r["denomination"],
            country=r["country"],
            year=r["year"],
            n_coins=r["n_coins"] or 0,
            last_enriched_at=r["last_enriched_at"],
            n_images=r["n_images"] or 0,
            n_crops=r["n_crops"] or 0,
            status=status,
        )
        for r, status in classified[:limit]
    ]
    return items, FreshnessBuckets(
        never=buckets["never"],
        stale_90d=buckets["stale"],
        fresh=buckets["fresh"],
        total=len(all_rows),
    )


# ─── /sources/ebay/market-quotes ────────────────────────────────────────────


def ebay_market_quotes(
    conn: sqlite3.Connection, eurio_ids: list[str],
) -> dict[str, list[MarketQuoteEntry]]:
    """Renvoie le dernier `coin_market_quotes` par (pièce, tier d'état).

    Pour chaque eurio_id, garde uniquement les rows du `period_start` le plus
    récent (par condition). Source `ebay` uniquement (C4).
    """
    if not eurio_ids:
        return {}
    placeholders = ",".join("?" * len(eurio_ids))
    # Note (Phase 2b bonus) : la table `coin_market_quotes` utilise
    # `source='ebay_browse'` (cf. `source_registry.id`). Le legacy
    # `sources_routes.py` filtrait `source='ebay'` — retournait toujours
    # vide. On corrige ici en passant à `ebay_browse`.
    rows = conn.execute(
        f"""
        SELECT eurio_id, condition_raw, p10, p50, p90, sample_size, period_start
          FROM coin_market_quotes c
         WHERE source = 'ebay_browse' AND eurio_id IN ({placeholders})
           AND period_start = (
               SELECT MAX(period_start) FROM coin_market_quotes c2
                WHERE c2.source = c.source AND c2.eurio_id = c.eurio_id
                  AND COALESCE(c2.condition_raw, '') = COALESCE(c.condition_raw, '')
           )
        """,
        eurio_ids,
    ).fetchall()
    out: dict[str, list[MarketQuoteEntry]] = {}
    for r in rows:
        out.setdefault(r["eurio_id"], []).append(MarketQuoteEntry(
            condition=r["condition_raw"] or "unknown",
            p10=r["p10"], p50=r["p50"], p90=r["p90"],
            sample_size=r["sample_size"], period_start=r["period_start"],
        ))
    return out


# ─── /sources (list) ────────────────────────────────────────────────────────


def list_source_registry(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    """Retourne la table `source_registry` (11 lignes : id, display_name, kind)."""
    rows = conn.execute(
        "SELECT id, display_name, kind, base_url, notes, created_at "
        "FROM source_registry ORDER BY id"
    ).fetchall()
    return [dict(r) for r in rows]


# ─── /sources/{id} (last run summary) ───────────────────────────────────────


def last_completed_run(
    conn: sqlite3.Connection, source_id: str,
) -> sqlite3.Row | None:
    return conn.execute(
        """
        SELECT status, n_calls, n_raws_added, n_crops_added, n_quotes_added,
               started_at, ended_at
          FROM source_runs
         WHERE source = ? AND status != 'running'
         ORDER BY started_at DESC LIMIT 1
        """,
        (source_id,),
    ).fetchone()
