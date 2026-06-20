"""Logique métier `review_queue` — orchestre les repository calls.

Cf. ARCHITECTURE.md §2.3. **Pas de SQL ici** (les helpers de comptage
vivent dans `repository.py`).

Port pure-Python (sans dep heavy `training.foundation`) de :
- `compute_auto_validate_verdict` (verdict LEVEL d'auto-validation)
- `DINO_VERDICT_THRESHOLDS` (constantes)

**Note (cf. review interne 2026-06-20)** : c'est un **subset** du legacy
`ml/training/foundation/auto_validate.py` — on retourne uniquement le
`level` (auto_candidate/partial/divergent/unknown), suffisant pour
`/review-queue/triage-stats`. Pour le verdict complet (reason,
decided_eurio_id, signaux Dino re-attachés), il faut le module training
sur l'image full workstation.
"""
from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone
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
    """(target, top1, sim, spread, text_verdict) — préfère la band
    country-restricted (plus discriminante), fallback global.
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
    """Counts agrégés pour le dashboard /review.

    Délégue toute la SQL aux helpers `repository.*` — orchestre seulement.
    """
    now = datetime.now(timezone.utc)
    today = now.strftime("%Y-%m-%d")
    week_start = (now - timedelta(days=7)).strftime("%Y-%m-%d")

    cohort_clause, cohort_args, cohort_empty = repository.cohort_filter_clause(
        conn, cohort_id,
    )
    if cohort_empty:
        zeros = TriageVerdictCounts(auto_candidate=0, partial=0, divergent=0, unknown=0)
        lanes_zero = TriageLaneCounts(manual=0, auto_accept=0)
        return TriageStats(
            n_pending=0, n_done_today=0, n_done_today_auto_dino=0,
            n_done_this_week=0, by_verdict=zeros,
            by_lane=lanes_zero, by_lane_lot=lanes_zero,
            n_lot_crops=0, n_rejected=0, n_skipped=0,
        )

    def _count(status_clause: str, status_args: list[object], kind_clause: bool) -> int:
        return repository.count_with_filter(
            conn,
            status_clause=status_clause, status_args=status_args,
            kind=kind, kind_clause=kind_clause,
            cohort_clause=cohort_clause, cohort_args=cohort_args,
        )

    n_pending = _count("rq.status = 'open'", [], kind_clause=True)
    n_done_today = _count(
        "rq.status = 'done' AND rq.decided_at >= ?", [today], kind_clause=False,
    )
    n_done_today_auto = _count(
        "rq.decided_by = 'auto_dino' AND rq.decided_at >= ?", [today], kind_clause=False,
    )
    n_done_week = _count(
        "rq.status = 'done' AND rq.decided_at >= ?", [week_start], kind_clause=False,
    )

    rows = repository.fetch_verdict_signal_rows(
        conn, kind=kind, cohort_clause=cohort_clause, cohort_args=cohort_args,
    )
    by_verdict = {"auto_candidate": 0, "partial": 0, "divergent": 0, "unknown": 0}
    for r in rows:
        by_verdict[compute_auto_validate_verdict(r)] += 1

    n_lot_crops = repository.count_lot_open_open(
        conn, cohort_clause=cohort_clause, cohort_args=cohort_args,
    )
    n_rejected = repository.count_rejected(
        conn, cohort_clause=cohort_clause, cohort_args=cohort_args,
    )
    n_skipped = repository.count_skipped(
        conn, cohort_clause=cohort_clause, cohort_args=cohort_args,
    )

    by_lane = TriageLaneCounts(
        manual=_count(
            "rq.status = 'open' AND (rq.lane = 'manual' OR rq.lane IS NULL)",
            [], kind_clause=True,
        ),
        auto_accept=_count(
            "rq.status = 'open' AND rq.lane = ?", ["auto_accept"], kind_clause=True,
        ),
    )

    by_lane_lot = TriageLaneCounts(
        manual=repository.count_lot_open_in_lane(
            conn, lane_clause="(rq.lane='manual' OR rq.lane IS NULL)", lane_args=[],
            cohort_clause=cohort_clause, cohort_args=cohort_args,
        ),
        auto_accept=repository.count_lot_open_in_lane(
            conn, lane_clause="rq.lane = ?", lane_args=["auto_accept"],
            cohort_clause=cohort_clause, cohort_args=cohort_args,
        ),
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
