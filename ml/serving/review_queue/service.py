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
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Final, Literal

from shared.dino_threshold_defaults import defaults_for as _threshold_defaults_for
from shared.verdict_scope import (
    SUGGESTIONS_ANCHORS_KIND,
    SUGGESTIONS_ENCODER_VERSION,
    VERDICT_ANCHORS_KIND,
    VERDICT_ENCODER_VERSION,
)

from shared.listing_titles import is_multi_country_lot

from . import repository
from .models import (
    AutoValidateVerdictOut,
    ConsensusVerdictOut,
    DinoCriterionOut,
    DinoAbstentionThresholdsOut,
    DinoSuggestionsResponse,
    DinoVerdictThresholdsOut,
    TriageLaneCounts,
    TriageStats,
    TriageVerdictCounts,
)


# Seuils Dino — mirror de `training.foundation.thresholds.DINO_VERDICT_THRESHOLDS`.
DINO_VERDICT_THRESHOLDS: Final[dict[str, float]] = {
    "top1_country_sim_min": 0.55,
    "country_spread_min": 0.05,
}

# Abstention des SUGGESTIONS (spread du top-K global). Lus depuis
# `shared/dino_threshold_defaults` plutôt que re-recopiés : ce module est
# stdlib-only et déjà la source lean des seuils. Les valeurs y sont identiques à
# `training.foundation.thresholds.DINO_ABSTENTION_THRESHOLDS` (0,02 / 0,05),
# vérifié par `tests/test_dino_suggestions_lean.py`.
#
# `defaults_for()` et NON `DEFAULTS[couple]` : le module expose un FALLBACK
# précisément parce qu'un encodeur candidat peut ne pas avoir d'entrée. Indexer
# en dur lèverait un `KeyError` À L'IMPORT le jour où les suggestions passent sur
# un encodeur non calibré — l'API lean entière refuserait de démarrer, au lieu de
# dégrader sur des seuils par défaut.
_SUGGESTION_DEFAULTS = _threshold_defaults_for(
    SUGGESTIONS_ANCHORS_KIND, SUGGESTIONS_ENCODER_VERSION,
)
DINO_ABSTENTION_THRESHOLDS: Final[dict[str, float]] = {
    k: _SUGGESTION_DEFAULTS[k]
    for k in ("spread_uncertain_max", "spread_confident_min")
}


VerdictLevel = Literal["auto_candidate", "partial", "divergent", "unknown"]
CriterionState = Literal["pass", "fail", "absent"]


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


def auto_validate_view(row: sqlite3.Row) -> tuple[
    VerdictLevel, str, list[tuple[str, CriterionState]],
]:
    """(level, reason, criteria) — port lean de
    ``training.foundation.auto_validate.compute_auto_validate_view``.

    Le module d'origine est stdlib-only, mais il vit sous
    ``training/foundation/``, dont le ``__init__`` tire numpy et torch : l'image
    lean ne peut pas l'importer, et `training/` n'y est même pas copié. D'où ce
    port — MÊME échelle de décision, MÊMES seuils, MÊMES libellés de raison.
    Le miroir est verrouillé par ``tests/test_dino_suggestions_lean.py``.

    Décision (mirror exact JS + legacy Python) :
      1. Pas de Dino prediction           → unknown
      2. text == contradict               → divergent
      3. target absent                    → unknown
      4. top1 != target                   → divergent
      5. Tous Dino pass (le texte est un VETO rendu en 2) → auto_candidate
      6. Sinon                            → partial
    """
    target, top1, sim, spread, text_verdict = _resolve_signals(row)

    sim_min = DINO_VERDICT_THRESHOLDS["top1_country_sim_min"]
    spread_min = DINO_VERDICT_THRESHOLDS["country_spread_min"]
    criteria: list[tuple[str, CriterionState]] = [
        ("top1_target",
         "absent" if not target else ("pass" if top1 == target else "fail")),
        ("top1_country_sim",
         "absent" if sim is None else ("pass" if sim >= sim_min else "fail")),
        ("country_spread",
         "absent" if spread is None else ("pass" if spread >= spread_min else "fail")),
    ]

    if top1 is None and sim is None:
        return "unknown", "Hors scope V1 ou Dino pas encore exécuté", criteria
    if text_verdict == "contradict":
        return "divergent", "Texte du listing contredit la cible", criteria
    if target is None:
        return "unknown", "Pas de target connu", criteria
    if top1 != target:
        return "divergent", "Dino top-1 diffère de la cible", criteria

    sim_pass = sim is not None and sim >= sim_min
    spread_pass = spread is not None and spread >= spread_min
    # Q1 (2026-08-27) : le texte n'est plus une CONDITION ici, seulement un VETO
    # rendu à l'étape 2. Miroir exact du legacy — cf. le commentaire long dans
    # `training/foundation/auto_validate._verdict_from_signals`, qui porte la
    # mesure. `tests/test_dino_suggestions_lean.py` verrouille l'égalité.
    if sim_pass and spread_pass:
        return ("auto_candidate",
                "Dino concorde avec la cible, texte non contredisant", criteria)
    return "partial", "Concordance partielle", criteria


@dataclass(frozen=True)
class AutoValidateDecision:
    """Ce que l'auto-acceptation a besoin de savoir, en plus du niveau.

    DÉRIVÉ de ``auto_validate_view`` — la règle n'est pas recopiée. Deux champs
    s'y ajoutent, et ils ne sortent d'aucune décision nouvelle :

    · ``decided_eurio_id`` — au niveau ``auto_candidate``, la règle 4 a déjà
      exigé ``top1 == cible``. Ce qu'on écrirait EST donc la cible du listing ;
    · ``face`` — lu tel quel sur la ligne, jamais deviné. ``None`` devient
      ``'unknown'`` à l'écriture plutôt qu'un ``obverse`` par défaut : masquer
      l'incertitude derrière une valeur plausible est ce qui rend une panne
      muette (G7).
    """

    level: VerdictLevel
    reason: str
    decided_eurio_id: str | None
    face: str | None


def auto_validate_decision(row: sqlite3.Row) -> AutoValidateDecision:
    """Port lean de ce que l'auto-accept consommait via
    ``training.foundation.auto_validate`` — indisponible sur l'image du VPS.

    Le VPS est le seul writer (Direction A) : sans ce port, l'auto-acceptation
    ne pouvait s'exécuter nulle part. Cf. ``serving/review_queue/auto_accept.py``.
    """
    level, reason, _criteria = auto_validate_view(row)
    target, _top1, _sim, _spread, _text = _resolve_signals(row)
    decided = target if level == "auto_candidate" else None
    face = row["face"] if "face" in row.keys() else None
    return AutoValidateDecision(
        level=level, reason=reason, decided_eurio_id=decided, face=face,
    )


def compute_auto_validate_verdict(row: sqlite3.Row) -> VerdictLevel:
    """Niveau seul — conservé pour `/review-queue/triage-stats`."""
    level, _reason, _criteria = auto_validate_view(row)
    return level


def abstention_state(spread: float | None) -> str:
    """État d'abstention des SUGGESTIONS depuis le spread GLOBAL.

    Ce que ça dit au panneau : sous le seuil bas, présenter une liste classée
    serait trompeur — le crop est probablement hors banque ou son design est
    ambigu. Calibré sur l'audit Phase 0 (la sim, elle, ne sépare rien)."""
    if spread is None:
        return "unknown"
    if spread >= DINO_ABSTENTION_THRESHOLDS["spread_confident_min"]:
        return "confident"
    if spread < DINO_ABSTENTION_THRESHOLDS["spread_uncertain_max"]:
        return "uncertain"
    return "low_margin"


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

    # Même population que `list_queue` — quarantaine exclue. Sans ça le bandeau
    # annonce des items que la file ne sert pas (cf. NOT_QUARANTINED_SQL).
    _OPEN = "rq.status = 'open'" + repository.NOT_QUARANTINED_SQL
    n_pending = _count(_OPEN, [], kind_clause=True)
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
            "rq.status = 'open' AND (rq.lane = 'manual' OR rq.lane IS NULL)"
            + repository.NOT_QUARANTINED_SQL,
            [], kind_clause=True,
        ),
        auto_accept=_count(
            "rq.status = 'open' AND rq.lane = ?" + repository.NOT_QUARANTINED_SQL,
            ["auto_accept"], kind_clause=True,
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


# ─── /review-queue/{…}/dino-suggestions (lot 6a) ────────────────────────────


def dino_suggestions(
    conn: sqlite3.Connection, asset_id: str, *, anchors_kind: str,
) -> DinoSuggestionsResponse:
    """Top-K Dino persisté + enrichi, SANS jamais encoder quoi que ce soit.

    C'est la différence avec le jumeau lourd (`review/review_queue_routes.py`),
    qui calcule à la demande quand la prédiction manque. Mesuré le 2026-08-23 :
    **0 crop sans prédiction de suggestions sur les 12 823** de la file — ce
    chemin lourd ne s'allume jamais en pratique, et le porter ici tirerait torch
    sur le VPS pour rien. Prédiction absente ⇒ ``repository.DinoPredictionMissing``
    ⇒ 404, que le panneau front sait déjà afficher (Dino est une aide, pas un
    prérequis pour reviewer).
    """
    import json

    encoder_version = (
        SUGGESTIONS_ENCODER_VERSION if anchors_kind == SUGGESTIONS_ANCHORS_KIND
        else VERDICT_ENCODER_VERSION
    )
    pred = repository.dino_prediction(
        conn, asset_id, encoder_version=encoder_version, anchors_kind=anchors_kind,
    )
    ctx = repository.asset_listing_context(conn, asset_id)

    # Les couches verdict/consensus restent calibrées sur le kind CONSENSUS quel
    # que soit le kind des SUGGESTIONS servi — le badge ne doit pas bouger parce
    # que la banque affichée est plus large.
    sig = repository.verdict_signals(
        conn, asset_id,
        encoder_version=VERDICT_ENCODER_VERSION, anchors_kind=VERDICT_ANCHORS_KIND,
    )
    verdict_out: AutoValidateVerdictOut | None = None
    if sig is not None:
        level, reason, criteria = auto_validate_view(sig)
        verdict_out = AutoValidateVerdictOut(
            level=level, reason=reason,
            criteria=[DinoCriterionOut(key=k, state=s) for k, s in criteria],
        )

    # Verdict de consensus : la row PERSISTÉE seulement. La voie lourde le
    # recalcule à la volée quand elle manque, via des experts qui vivent sous
    # `training.foundation` (numpy/torch) — absent de l'image lean. Le contrat
    # front prévoit déjà `null`, et le badge retombe sur le verdict par critère.
    cv = repository.consensus_verdict_row(conn, asset_id)
    consensus_out = (
        ConsensusVerdictOut(
            outcome=cv["outcome"], lane=cv["lane"], reason=cv["reason"],
            rule=cv["rule"], confidence=float(cv["confidence"] or 0.0),
        )
        if cv is not None else None
    )

    return DinoSuggestionsResponse(
        asset_id=pred["asset_id"],
        encoder_version=pred["encoder_version"],
        anchors_kind=pred["anchors_kind"],
        anchors_count=pred["anchors_count"],
        computed_at=pred["computed_at"],
        duration_ms=pred["duration_ms"],
        # Servie même périmée (0013) — c'est l'écran qui le dit, pas le silence.
        stale_since=pred["stale_since"] if "stale_since" in pred.keys() else None,
        spread=pred["spread"],
        top1_eurio_id=pred["top1_eurio_id"],
        top1_sim=pred["top1_sim"],
        top_k=repository.enrich_top_k(conn, json.loads(pred["top_k_json"] or "[]")),
        target_country=pred["target_country"],
        country_anchors_count=pred["country_anchors_count"],
        country_spread=pred["country_spread"],
        top1_country_eurio_id=pred["top1_country_eurio_id"],
        top1_country_sim=pred["top1_country_sim"],
        top_k_country=repository.enrich_top_k(
            conn, json.loads(pred["top_k_country_json"] or "[]")),
        target_eurio_id=ctx["target_eurio_id"] if ctx else None,
        verdict_thresholds=DinoVerdictThresholdsOut(**DINO_VERDICT_THRESHOLDS),
        abstention_thresholds=DinoAbstentionThresholdsOut(
            **DINO_ABSTENTION_THRESHOLDS),
        auto_validate_verdict=verdict_out,
        consensus_verdict=consensus_out,
        abstention_state=abstention_state(pred["spread"]),
        multi_country_lot=is_multi_country_lot(
            ctx["listing_title"] if ctx else None),
    )
