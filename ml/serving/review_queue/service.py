"""Logique métier `review_queue` — orchestre les repository calls.

Cf. ARCHITECTURE.md §2.3.

Port pure-Python (sans dep heavy `training.foundation`) de :
- `compute_auto_validate_verdict_from_row` (verdict d'auto-validation)
- `DINO_VERDICT_THRESHOLDS` (constantes)

Source de vérité unique pour `/review-queue/triage-stats`. Mirror exact du
legacy `ml/training/foundation/auto_validate.py` — toute évolution doit
être propagée des deux côtés tant que le module training n'est pas
livré sur l'image lean.
"""
from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta
from typing import Final, Literal

from . import repository
from .models import TriageLaneCounts, TriageStats, TriageVerdictCounts


# Seuils Dino — mirror de `training.foundation.thresholds.DINO_VERDICT_THRESHOLDS`.
DINO_VERDICT_THRESHOLDS: Final[dict[str, float]] = {
    "top1_country_sim_min": 0.55,
    "country_spread_min": 0.05,
}


VerdictLevel = Literal["auto_candidate", "partial", "divergent", "unknown"]


def _resolve_signals(row: sqlite3.Row) -> tuple[
    str | None, str | None, float | None, float | None, str | None,
]:
    """(target, top1, sim, spread, text_verdict).

    Préfère la band country-restricted (plus discriminante) ; fallback global.
    """
    target = row["target_eurio_id"]
    top1 = row["top1_country_eurio_id"] or row["top1_eurio_id"]
    sim = (
        row["top1_country_sim"]
        if row["top1_country_sim"] is not None
        else row["top1_sim"]
    )
    spread = (
        row["country_spread"]
        if row["country_spread"] is not None
        else row["spread"]
    )
    return target, top1, sim, spread, row["vs_target_verdict"]


def compute_auto_validate_verdict(row: sqlite3.Row) -> VerdictLevel:
    """Verdict niveau pour une row JOIN (face, target, top1*, sim, spread, …).

    Décision (mirror exact JS + legacy Python) :
      1. Pas de Dino prediction          → unknown
      2. text == contradict              → divergent
      3. target absent                   → unknown
      4. top1 != target                  → divergent
      5. Tous Dino pass + text=convergent → auto_candidate
      6. Sinon                           → partial
    """
    target, top1, sim, spread, text_verdict = _resolve_signals(row)

    if top1 is None and sim is None:
        return "unknown"
    if text_verdict == "contradict":
        return "divergent"
    if target is None:
        return "unknown"
    if top1 != target:
        return "divergent"

    sim_min = DINO_VERDICT_THRESHOLDS["top1_country_sim_min"]
    spread_min = DINO_VERDICT_THRESHOLDS["country_spread_min"]
    sim_pass = sim is not None and sim >= sim_min
    spread_pass = spread is not None and spread >= spread_min
    if sim_pass and spread_pass and text_verdict == "convergent":
        return "auto_candidate"
    return "partial"


# ─── /review-queue/triage-stats ─────────────────────────────────────────────


def triage_stats(
    conn: sqlite3.Connection,
    *,
    kind: str,
    cohort_id: str | None,
) -> TriageStats:
    """Counts agrégés pour le dashboard /review."""
    today = datetime.utcnow().strftime("%Y-%m-%d")
    week_start = (datetime.utcnow() - timedelta(days=7)).strftime("%Y-%m-%d")

    eids, empty = repository._cohort_eurio_ids(conn, cohort_id)
    if cohort_id and empty:
        # Cohort introuvable ou vide → tous compteurs à 0.
        zeros = TriageVerdictCounts(auto_candidate=0, partial=0, divergent=0, unknown=0)
        lanes_zero = TriageLaneCounts(manual=0, auto_accept=0)
        return TriageStats(
            n_pending=0, n_done_today=0, n_done_today_auto_dino=0,
            n_done_this_week=0, by_verdict=zeros,
            by_lane=lanes_zero, by_lane_lot=lanes_zero,
            n_lot_crops=0, n_rejected=0, n_skipped=0,
        )
    cohort_clause = ""
    cohort_args: list[object] = []
    if eids:
        cohort_clause = f" AND si.target_eurio_id IN ({','.join('?' * len(eids))})"
        cohort_args = list(eids)

    def _count(status_clause: str, status_args: list[object], kind_clause: bool) -> int:
        kc = " AND rq.kind = ?" if (kind_clause and kind != "all") else ""
        ka = [kind] if (kind_clause and kind != "all") else []
        if cohort_clause:
            sql = (
                "SELECT COUNT(*) AS c FROM review_queue rq "
                "JOIN image_assets a ON a.id = rq.image_asset_id "
                "JOIN source_images si ON si.id = a.source_image_id "
                f"WHERE {status_clause}{kc}{cohort_clause}"
            )
            return conn.execute(sql, [*status_args, *ka, *cohort_args]).fetchone()["c"]
        sql = f"SELECT COUNT(*) AS c FROM review_queue rq WHERE {status_clause}{kc}"
        return conn.execute(sql, [*status_args, *ka]).fetchone()["c"]

    n_pending = _count("rq.status = 'open'", [], kind_clause=True)
    n_done_today = _count("rq.status = 'done' AND rq.decided_at >= ?", [today], kind_clause=False)
    n_done_today_auto = _count(
        "rq.decided_by = 'auto_dino' AND rq.decided_at >= ?", [today], kind_clause=False)
    n_done_week = _count("rq.status = 'done' AND rq.decided_at >= ?", [week_start], kind_clause=False)

    # Verdicts — un scan SQL puis pure Python.
    where = f"rq.status = 'open' AND {repository.NOT_RESTORED_SQL}"
    args: list[object] = []
    if kind != "all":
        where += " AND rq.kind = ?"
        args.append(kind)
    rows = conn.execute(
        f"""
        SELECT a.face,
               si.target_eurio_id,
               p.top1_country_eurio_id, p.top1_country_sim, p.country_spread,
               p.top1_eurio_id, p.top1_sim, p.spread,
               lts.vs_target_verdict
          FROM review_queue rq
          JOIN image_assets a ON a.id = rq.image_asset_id
          JOIN source_images si ON si.id = a.source_image_id
          LEFT JOIN image_asset_dino_predictions p
                 ON p.asset_id = a.id
                AND p.encoder_version = 'dinov2-vits14'
                AND p.anchors_kind = '2eur_commemo'
          LEFT JOIN listing_text_signals lts
                 ON lts.source_image_id = si.id
         WHERE {where}{cohort_clause}
        """,
        [*args, *cohort_args],
    ).fetchall()

    by_verdict = {"auto_candidate": 0, "partial": 0, "divergent": 0, "unknown": 0}
    for r in rows:
        v = compute_auto_validate_verdict(r)
        by_verdict[v] += 1

    if cohort_clause:
        n_lot_crops = conn.execute(
            "SELECT COUNT(*) AS c FROM review_queue rq "
            "JOIN image_assets a ON a.id = rq.image_asset_id "
            "JOIN source_images si ON si.id = a.source_image_id "
            f"WHERE rq.status = 'open' AND rq.kind = 'lot'{cohort_clause}",
            cohort_args,
        ).fetchone()["c"]
        n_rejected = conn.execute(
            "SELECT COUNT(*) AS c FROM review_queue rq "
            "JOIN image_assets a ON a.id = rq.image_asset_id "
            "JOIN source_images si ON si.id = a.source_image_id "
            f"WHERE a.resolution_status = 'rejected'{cohort_clause}",
            cohort_args,
        ).fetchone()["c"]
        n_skipped = conn.execute(
            "SELECT COUNT(*) AS c FROM review_queue rq "
            "JOIN image_assets a ON a.id = rq.image_asset_id "
            "JOIN source_images si ON si.id = a.source_image_id "
            f"WHERE rq.status = 'open' AND rq.decision_notes = 'skipped'{cohort_clause}",
            cohort_args,
        ).fetchone()["c"]
    else:
        n_lot_crops = conn.execute(
            "SELECT COUNT(*) AS c FROM review_queue rq "
            "WHERE rq.status = 'open' AND rq.kind = 'lot'"
        ).fetchone()["c"]
        n_rejected = conn.execute(
            "SELECT COUNT(*) AS c FROM review_queue rq "
            "JOIN image_assets a ON a.id = rq.image_asset_id "
            "WHERE a.resolution_status = 'rejected'"
        ).fetchone()["c"]
        n_skipped = conn.execute(
            "SELECT COUNT(*) AS c FROM review_queue rq "
            "WHERE rq.status = 'open' AND rq.decision_notes = 'skipped'"
        ).fetchone()["c"]

    by_lane = TriageLaneCounts(
        manual=_count(
            "rq.status = 'open' AND (rq.lane = 'manual' OR rq.lane IS NULL)",
            [], kind_clause=True,
        ),
        auto_accept=_count(
            "rq.status = 'open' AND rq.lane = ?", ["auto_accept"], kind_clause=True,
        ),
    )

    def _count_lot(lane_clause: str, lane_args: list[object]) -> int:
        if cohort_clause:
            sql = (
                "SELECT COUNT(*) AS c FROM review_queue rq "
                "JOIN image_assets a ON a.id = rq.image_asset_id "
                "JOIN source_images si ON si.id = a.source_image_id "
                f"WHERE rq.status='open' AND rq.kind='lot' AND {lane_clause}{cohort_clause}"
            )
            return conn.execute(sql, [*lane_args, *cohort_args]).fetchone()["c"]
        sql = ("SELECT COUNT(*) AS c FROM review_queue rq "
               f"WHERE rq.status='open' AND rq.kind='lot' AND {lane_clause}")
        return conn.execute(sql, lane_args).fetchone()["c"]

    by_lane_lot = TriageLaneCounts(
        manual=_count_lot("(rq.lane='manual' OR rq.lane IS NULL)", []),
        auto_accept=_count_lot("rq.lane = ?", ["auto_accept"]),
    )

    return TriageStats(
        n_pending=n_pending,
        n_done_today=n_done_today,
        n_done_today_auto_dino=n_done_today_auto,
        n_done_this_week=n_done_week,
        by_verdict=TriageVerdictCounts(**by_verdict),
        by_lane=by_lane,
        by_lane_lot=by_lane_lot,
        n_lot_crops=n_lot_crops,
        n_rejected=n_rejected,
        n_skipped=n_skipped,
    )
