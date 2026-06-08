"""Server-side auto-validate verdict — port de useAutoValidateVerdict.ts.

Mirror EXACT de la logique JS du front (admin/.../review/composables/
useAutoValidateVerdict.ts). Une seule règle de décision, deux consommateurs :
le front pour colorer la queue, le pipeline pour auto-accepter.

Seuils : ``DINO_VERDICT_THRESHOLDS`` (foundation/thresholds.py).
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from typing import Literal, NamedTuple

from training.foundation.thresholds import DINO_VERDICT_THRESHOLDS

AutoValidateLevel = Literal["auto_candidate", "partial", "divergent", "unknown"]


@dataclass(frozen=True)
class AutoValidateVerdict:
    level: AutoValidateLevel
    reason: str
    # ``decided_eurio_id`` : ce qu'on écrirait en cas d'auto-accept (= target,
    # validé par la convergence). NULL pour partial/divergent/unknown.
    decided_eurio_id: str | None
    face_detected: str | None
    # Snapshots des signaux Dino qui ont motivé le verdict — utilisés
    # pour le ``decision_metadata_json`` côté auto-accept (audit
    # post-hoc indépendant des tables REPLACE-ables Dino).
    top1_eurio_id: str | None = None
    sim: float | None = None
    spread: float | None = None
    text_verdict: str | None = None


CriterionState = Literal["pass", "fail", "absent"]
CriterionKey = Literal["top1_target", "top1_country_sim", "country_spread"]


@dataclass(frozen=True)
class DinoCriterion:
    """État d'un critère Dino — mirror de ``computeDinoVerdict`` côté front."""

    key: CriterionKey
    state: CriterionState


@dataclass(frozen=True)
class AutoValidateView:
    """Vue complète pour le front : verdict global + détail par critère.

    Source unique — le front ne recalcule plus rien (C0 du redesign
    auto-validation, docs/work-in-progress/autovalidation-redesign.md).
    """

    level: AutoValidateLevel
    reason: str
    criteria: tuple[DinoCriterion, ...]


# JOIN partagé par toutes les entrées : signaux Dino (country-restricted +
# global) + verdict texte, pour un image_asset donné. Une seule définition.
_SIGNALS_SQL = """
    SELECT a.face,
           si.target_eurio_id,
           p.top1_country_eurio_id,
           p.top1_country_sim,
           p.country_spread,
           p.top1_eurio_id,
           p.top1_sim,
           p.spread,
           lts.vs_target_verdict
      FROM image_assets a
      JOIN source_images si ON si.id = a.source_image_id
      LEFT JOIN image_asset_dino_predictions p
             ON p.asset_id = a.id
            AND p.encoder_version = ?
            AND p.anchors_kind = ?
      LEFT JOIN listing_text_signals lts
             ON lts.source_image_id = si.id
     WHERE a.id = ?
"""


def _fetch_signals(
    conn: sqlite3.Connection,
    asset_id: str,
    encoder_version: str,
    anchors_kind: str,
) -> sqlite3.Row | None:
    return conn.execute(
        _SIGNALS_SQL, (encoder_version, anchors_kind, asset_id)
    ).fetchone()


class ResolvedSignals(NamedTuple):
    """Signaux résolus d'un asset (préférence country-restricted appliquée).
    Source unique consommée par le verdict (foundation) ET les experts
    d'auto-validation (review/validation)."""

    face: str | None
    target: str | None
    top1: str | None
    sim: float | None
    spread: float | None
    text_verdict: str | None


def _resolve_signals(row: sqlite3.Row) -> ResolvedSignals:
    """Résout les signaux d'une row JOIN : préfère la band country-restricted
    (plus discriminante), fallback global. Une seule définition de la
    préférence, partagée par le verdict global et le détail par critère."""
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
    return ResolvedSignals(
        face=row["face"],
        target=target,
        top1=top1,
        sim=sim,
        spread=spread,
        text_verdict=row["vs_target_verdict"],
    )


def fetch_and_resolve_signals(
    conn: sqlite3.Connection,
    asset_id: str,
    *,
    encoder_version: str = "dinov2-vits14",
    anchors_kind: str = "2eur_commemo",
) -> ResolvedSignals | None:
    """Surface publique de la résolution des signaux d'un asset (None s'il est
    introuvable). Partagée par le verdict (foundation) et les experts
    d'auto-validation (review/validation) → une seule définition de la
    préférence country-restricted, pas de dérive."""
    row = _fetch_signals(conn, asset_id, encoder_version, anchors_kind)
    if row is None:
        return None
    return _resolve_signals(row)


def compute_auto_validate_verdict_from_row(row: sqlite3.Row) -> AutoValidateVerdict:
    """Variante pour un usage batch : la row contient déjà les colonnes du
    JOIN (cf. ``compute_auto_validate_verdict`` pour la liste). Permet à
    l'endpoint ``triage-stats`` de scanner toute la queue en une requête.

    Colonnes attendues (``_SIGNALS_SQL``) :
      face, target_eurio_id, top1_country_eurio_id, top1_country_sim,
      country_spread, top1_eurio_id, top1_sim, spread, vs_target_verdict.
    """
    face, target, top1, sim, spread, text_verdict = _resolve_signals(row)
    return _verdict_from_signals(
        face=face, target=target, top1=top1, sim=sim, spread=spread,
        text_verdict=text_verdict,
    )


def compute_auto_validate_verdict(
    conn: sqlite3.Connection,
    asset_id: str,
    *,
    encoder_version: str = "dinov2-vits14",
    anchors_kind: str = "2eur_commemo",
) -> AutoValidateVerdict:
    """Compute le verdict d'auto-validation pour un image_asset donné.

    Décision (mirror exact du JS) :
      1. Pas de Dino prediction          → ``unknown``
      2. text == contradict              → ``divergent``
      3. target absent                   → ``unknown``
      4. top1 != target                  → ``divergent``
      5. Tous Dino pass + text=convergent → ``auto_candidate``
      6. Sinon                           → ``partial``
    """
    row = _fetch_signals(conn, asset_id, encoder_version, anchors_kind)

    if row is None:
        return AutoValidateVerdict(
            level="unknown",
            reason="Asset introuvable",
            decided_eurio_id=None,
            face_detected=None,
            top1_eurio_id=None,
            sim=None,
            spread=None,
            text_verdict=None,
        )

    return compute_auto_validate_verdict_from_row(row)


def _verdict_from_signals(
    *,
    face: str | None,
    target: str | None,
    top1: str | None,
    sim: float | None,
    spread: float | None,
    text_verdict: str | None,
) -> AutoValidateVerdict:
    """Cœur de la décision — extrait pour partage par les deux entrées
    publiques (single-asset vs batch). Ne touche pas à la DB."""

    # Signaux Dino re-attachés à toutes les réponses pour audit (chunk B).
    signals = {
        "top1_eurio_id": top1,
        "sim": sim,
        "spread": spread,
        "text_verdict": text_verdict,
    }

    # 1. Pas de Dino prediction (out of scope V1, ou pas encore exécuté).
    if top1 is None and sim is None:
        return AutoValidateVerdict(
            level="unknown",
            reason="Hors scope V1 ou Dino pas encore exécuté",
            decided_eurio_id=None,
            face_detected=face,
            **signals,
        )

    # 2. Texte contradictoire → divergent net (signal fort).
    if text_verdict == "contradict":
        return AutoValidateVerdict(
            level="divergent",
            reason="Texte du listing contredit la cible",
            decided_eurio_id=None,
            face_detected=face,
            **signals,
        )

    # 3. Pas de target → unknown (impossible de comparer).
    if target is None:
        return AutoValidateVerdict(
            level="unknown",
            reason="Pas de target connu",
            decided_eurio_id=None,
            face_detected=face,
            **signals,
        )

    # 4. top1 != target → divergent.
    if top1 != target:
        return AutoValidateVerdict(
            level="divergent",
            reason="Top1 Dino != cible",
            decided_eurio_id=None,
            face_detected=face,
            **signals,
        )

    # 5. Critères Dino + texte.
    sim_min = DINO_VERDICT_THRESHOLDS["top1_country_sim_min"]
    spread_min = DINO_VERDICT_THRESHOLDS["country_spread_min"]
    sim_pass = sim is not None and sim >= sim_min
    spread_pass = spread is not None and spread >= spread_min
    dino_all_pass = sim_pass and spread_pass

    if dino_all_pass and text_verdict == "convergent":
        return AutoValidateVerdict(
            level="auto_candidate",
            reason="Dino + texte convergent",
            decided_eurio_id=target,
            face_detected=face,
            **signals,
        )

    # 6. Reste → partial avec raisons détaillées.
    reasons: list[str] = []
    if not sim_pass:
        reasons.append(
            f"sim {sim:.3f} < {sim_min:.2f}" if sim is not None else "sim absent"
        )
    if not spread_pass:
        reasons.append(
            f"spread {spread:.3f} < {spread_min:.2f}"
            if spread is not None
            else "spread absent"
        )
    if text_verdict and text_verdict != "convergent":
        reasons.append(f"texte {text_verdict}")
    elif text_verdict is None:
        reasons.append("texte non comparé")

    return AutoValidateVerdict(
        level="partial",
        reason=" · ".join(reasons) if reasons else "Convergence partielle",
        decided_eurio_id=None,
        face_detected=face,
        **signals,
    )


def _criterion_states(
    *,
    target: str | None,
    top1: str | None,
    sim: float | None,
    spread: float | None,
) -> tuple[CriterionState, CriterionState, CriterionState]:
    """États des 3 critères Dino — mirror exact de ``computeDinoVerdict``
    (front). Lit les mêmes seuils que ``_verdict_from_signals`` → cohérence
    garantie entre le détail par critère et le verdict global."""
    sim_min = DINO_VERDICT_THRESHOLDS["top1_country_sim_min"]
    spread_min = DINO_VERDICT_THRESHOLDS["country_spread_min"]

    top1_state: CriterionState = (
        "absent" if not target else ("pass" if top1 == target else "fail")
    )
    sim_state: CriterionState = (
        "absent" if sim is None else ("pass" if sim >= sim_min else "fail")
    )
    spread_state: CriterionState = (
        "absent"
        if spread is None
        else ("pass" if spread >= spread_min else "fail")
    )
    return top1_state, sim_state, spread_state


def _dino_criteria_from_signals(
    *,
    target: str | None,
    top1: str | None,
    sim: float | None,
    spread: float | None,
) -> tuple[DinoCriterion, ...]:
    top1_state, sim_state, spread_state = _criterion_states(
        target=target, top1=top1, sim=sim, spread=spread
    )
    return (
        DinoCriterion(key="top1_target", state=top1_state),
        DinoCriterion(key="top1_country_sim", state=sim_state),
        DinoCriterion(key="country_spread", state=spread_state),
    )


def compute_auto_validate_view(
    conn: sqlite3.Connection,
    asset_id: str,
    *,
    encoder_version: str = "dinov2-vits14",
    anchors_kind: str = "2eur_commemo",
) -> AutoValidateView:
    """Verdict global + détail par critère pour un image_asset.

    Source unique consommée par l'endpoint ``dino-suggestions`` : le front
    affiche ``level``/``reason``/``criteria`` tels quels, sans recalculer
    (C0 du redesign auto-validation). Le verdict global réutilise
    ``_verdict_from_signals`` → strictement le même que ``triage-stats`` et
    ``auto-accept``.
    """
    row = _fetch_signals(conn, asset_id, encoder_version, anchors_kind)
    if row is None:
        return AutoValidateView(
            level="unknown", reason="Asset introuvable", criteria=()
        )
    _face, target, top1, sim, spread, _text = _resolve_signals(row)
    verdict = compute_auto_validate_verdict_from_row(row)
    criteria = _dino_criteria_from_signals(
        target=target, top1=top1, sim=sim, spread=spread
    )
    return AutoValidateView(
        level=verdict.level, reason=verdict.reason, criteria=criteria
    )
