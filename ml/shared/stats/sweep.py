"""Balayage précision/couverture — le seuil d'abstention se MESURE, pas se copie.

Chaque encodeur a sa propre échelle de spread : un seuil de 0,10 calibré sur
``dinov2-vitl14`` ne veut rien dire pour un ViT-S/16 DINOv3. Comparer deux
encodeurs à seuils gelés mesure « qui gagne avec les seuils de l'autre ».
D'où la règle de ce module : **les seuils balayés sont dérivés des scores
observés**, jamais posés en dur sur [0, 1].

Contrat d'import : stdlib uniquement.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Sequence


@dataclass(frozen=True)
class SweepPoint:
    """Un point de la courbe : ce qu'on répond, et à quel prix."""

    threshold: float
    n_covered: int
    coverage: float  # n_covered / n_total
    n_correct: int
    precision: float  # n_correct / n_covered, 0.0 si n_covered == 0

    def to_dict(self) -> dict:
        return dict(self.__dict__)


def precision_coverage_curve(
    items: Sequence[tuple[float, bool]],
    *,
    thresholds: Sequence[float] | None = None,
    n_steps: int = 101,
) -> list[SweepPoint]:
    """Balaye ``score >= seuil`` sur ``items = [(score, correct), ...]``.

    ``thresholds=None`` → ``n_steps`` valeurs équiréparties entre le min et le
    max des scores OBSERVÉS. C'est tout l'objet de P6-4 : un jeu dont les
    spreads vivent dans [0,02 ; 0,06] doit être balayé dans cette plage.
    """
    total = len(items)
    if thresholds is None:
        if total == 0:
            thresholds = []
        else:
            lo = min(s for s, _ in items)
            hi = max(s for s, _ in items)
            steps = max(1, int(n_steps))
            if steps == 1 or hi == lo:
                thresholds = [lo]
            else:
                span = hi - lo
                thresholds = [lo + span * i / (steps - 1) for i in range(steps)]
    curve: list[SweepPoint] = []
    for thr in thresholds:
        covered = [ok for score, ok in items if score >= thr]
        n_cov = len(covered)
        n_ok = sum(1 for ok in covered if ok)
        curve.append(
            SweepPoint(
                threshold=float(thr),
                n_covered=n_cov,
                coverage=(n_cov / total) if total else 0.0,
                n_correct=n_ok,
                precision=(n_ok / n_cov) if n_cov else 0.0,
            )
        )
    return curve


def threshold_for_precision(
    curve: Sequence[SweepPoint],
    target_precision: float = 0.97,
    *,
    min_covered: int = 30,
) -> SweepPoint | None:
    """Le seuil LE PLUS BAS (donc la couverture la plus haute) qui atteint la
    précision cible avec au moins ``min_covered`` échantillons.

    ``None`` quand aucun ne l'atteint : « aucun seuil ne tient 97 % sur ce jeu »
    est une réponse, pas une erreur.
    """
    qualifying = [
        p
        for p in curve
        if p.n_covered >= min_covered and p.precision >= target_precision
    ]
    if not qualifying:
        return None
    return min(qualifying, key=lambda p: p.threshold)


def curve_to_json(curve: Sequence[SweepPoint], *, max_points: int = 64) -> str:
    """Sérialise la courbe pour ``encoder_bench_runs.sweep_json``.

    Sous-échantillonne uniformément au-delà de ``max_points``, en conservant
    toujours les deux extrémités : une courbe tronquée par le milieu reste
    lisible, une courbe amputée de sa fin ne dit plus où s'arrête la couverture.
    """
    pts = list(curve)
    if max_points >= 1 and len(pts) > max_points:
        if max_points == 1:
            pts = [pts[0]]
        else:
            last = len(pts) - 1
            idx = sorted({round(i * last / (max_points - 1)) for i in range(max_points)})
            pts = [pts[i] for i in idx]
    return json.dumps(
        [
            {
                "threshold": round(p.threshold, 6),
                "n_covered": p.n_covered,
                "coverage": round(p.coverage, 6),
                "n_correct": p.n_correct,
                "precision": round(p.precision, 6),
            }
            for p in pts
        ],
        separators=(",", ":"),
    )
