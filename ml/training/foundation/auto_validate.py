"""Server-side auto-validate verdict — port de useAutoValidateVerdict.ts.

Mirror EXACT de la logique JS du front (admin/.../review/composables/
useAutoValidateVerdict.ts). Une seule règle de décision, deux consommateurs :
le front pour colorer la queue, le pipeline pour auto-accepter.

Seuils : ``DINO_VERDICT_THRESHOLDS`` (foundation/thresholds.py).
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from typing import Literal

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


def compute_auto_validate_verdict_from_row(row: sqlite3.Row) -> AutoValidateVerdict:
    """Variante pour un usage batch : la row contient déjà les colonnes du
    JOIN (cf. ``compute_auto_validate_verdict`` pour la liste). Permet à
    l'endpoint ``triage-stats`` de scanner toute la queue en une requête.

    Colonnes attendues :
      face, target_eurio_id, top1_country_eurio_id, top1_country_sim,
      country_spread, top1_eurio_id, top1_sim, spread, vs_target_verdict.
    """
    face = row["face"]
    target = row["target_eurio_id"]
    text_verdict = row["vs_target_verdict"]

    # Préfère la band country-restricted (plus discriminante), fallback global.
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
    row = conn.execute(
        """
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
        """,
        (encoder_version, anchors_kind, asset_id),
    ).fetchone()

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
