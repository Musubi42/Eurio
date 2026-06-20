"""Accès SQL pur pour le domaine `review_queue`.

Cf. ARCHITECTURE.md §2.2.
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta

from .models import RejectedCrop, ReviewStats, TextSignalsResponse


class ReviewItemNotFound(Exception):
    """Lève par get_review / text-signals quand id introuvable."""


class TextSignalsNotFound(Exception):
    """Lève quand listing_text_signals n'a pas (encore) de row pour ce listing.

    Cas habituel : step text_signal pas encore exécuté pour ce source_image.
    """


# ─── /review-queue/stats ────────────────────────────────────────────────────


def queue_stats(conn: sqlite3.Connection) -> ReviewStats:
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

    # Médiane proxy : diff (decided_at, enqueued_at) sur les 100 derniers done.
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

    return ReviewStats(
        n_pending=n_pending,
        n_done_today=n_done_today,
        n_done_this_week=n_done_week,
        median_seconds_per_decision=round(median, 1),
    )


# ─── /review-queue/rejected ─────────────────────────────────────────────────


def list_rejected(
    conn: sqlite3.Connection, *, cohort_id: str | None, limit: int,
) -> list[RejectedCrop]:
    """Liste des crops rejetés (image_assets.resolution_status='rejected').

    `cohort_id` scope sur les target_eurio_id de la cohort. Cohort inconnue ou
    sans coin → liste vide (au lieu de 404, plus simple côté front).
    """
    cohort_clause = ""
    cohort_args: list[object] = []
    if cohort_id:
        cohort_row = conn.execute(
            "SELECT eurio_ids_json FROM cohort_jobs WHERE id = ?",
            (cohort_id,),
        ).fetchone()
        if cohort_row is None:
            return []
        try:
            eurio_ids = json.loads(cohort_row["eurio_ids_json"] or "[]")
        except (TypeError, json.JSONDecodeError):
            eurio_ids = []
        if not eurio_ids:
            return []
        cohort_clause = (
            f" AND s.target_eurio_id IN ({','.join('?' * len(eurio_ids))})"
        )
        cohort_args = list(eurio_ids)

    rows = conn.execute(
        f"""
        SELECT rq.id AS review_id, rq.image_asset_id, rq.decided_at,
               a.quality_reason,
               s.source, s.listing_title, s.target_eurio_id,
               t.country_name AS t_country_name, t.year AS t_year,
               t.theme AS t_theme
          FROM review_queue rq
          JOIN image_assets a ON a.id = rq.image_asset_id
          JOIN source_images s ON s.id = a.source_image_id
          LEFT JOIN coins t ON t.eurio_id = s.target_eurio_id
         WHERE a.resolution_status = 'rejected'{cohort_clause}
         ORDER BY rq.decided_at DESC
         LIMIT ?
        """,
        [*cohort_args, limit],
    ).fetchall()

    return [
        RejectedCrop(
            review_id=r["review_id"],
            image_asset_id=r["image_asset_id"],
            crop_url=f"/sources/{r['source']}/assets/{r['image_asset_id']}/file",
            listing_title=r["listing_title"],
            quality_reason=r["quality_reason"],
            decided_at=r["decided_at"],
            target_eurio_id=r["target_eurio_id"],
            target_label=_format_target_label(
                r["t_country_name"], r["t_year"], r["t_theme"],
            ),
        )
        for r in rows
    ]


def _format_target_label(country: str | None, year: int | None, theme: str | None) -> str | None:
    parts = [country, str(year) if year else None, theme]
    return " · ".join(b for b in parts if b) or None


# ─── /review-queue/{id}/text-signals + /asset/{id}/text-signals ─────────────


def text_signals_by_source_image(
    conn: sqlite3.Connection, source_image_id: str,
) -> TextSignalsResponse:
    """Lit `listing_text_signals` pour un source_image_id.

    Lève `TextSignalsNotFound` si la row n'existe pas (text_signal step pas
    encore exécuté pour ce listing).
    """
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
        raise TextSignalsNotFound(source_image_id)

    cols = row.keys()

    def _col(name: str) -> object:
        return row[name] if name in cols else None

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
        vs_target_verdict=_col("vs_target_verdict"),  # type: ignore[arg-type]
        contradictions=json.loads(_col("contradictions_json") or "[]"),  # type: ignore[arg-type]
        convergences=json.loads(_col("convergences_json") or "[]"),  # type: ignore[arg-type]
        computed_at=row["computed_at"],
    )


def source_image_id_for_asset(
    conn: sqlite3.Connection, asset_id: str,
) -> str:
    row = conn.execute(
        "SELECT source_image_id FROM image_assets WHERE id = ?", (asset_id,),
    ).fetchone()
    if row is None:
        raise ReviewItemNotFound(asset_id)
    return row["source_image_id"]


def source_image_id_for_review(
    conn: sqlite3.Connection, review_id: str,
) -> str:
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
        raise ReviewItemNotFound(review_id)
    return row["source_image_id"]
