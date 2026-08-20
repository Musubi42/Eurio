"""Statistiques de banc — stdlib uniquement, importables par l'image lean du VPS.

Deux besoins, tous deux nés du banc multi-encodeurs (P6-3 / P6-4) :
  - `paired` : comparer deux encodeurs sur les MÊMES crops (McNemar exact) ;
  - `sweep`  : balayer les seuils dans la plage observée d'un encodeur, et en
    tirer le seuil qui atteint la précision cible ;
  - `calibration` : refuser de rendre ce seuil comme « officiel » tant que des
    bloqueurs (P3, P1) sont mesurés — le chiffre sort marqué provisoire, ou
    ne sort pas.

Aucun import lourd ici : numpy/torch/cv2 sont absents de l'image lean, et un
import lourd y fait disparaître le module **en silence**.
"""
from __future__ import annotations

from shared.stats.paired import PairedResult, mcnemar_exact, paired_compare
from shared.stats.calibration import (
    DEFAULT_MIN_COVERED,
    DEFAULT_TARGET_PRECISION,
    P3_BLOCKER,
    CalibrationBlocked,
    ThresholdProposal,
    propose_threshold,
)
from shared.stats.sweep import (
    SweepPoint,
    curve_to_json,
    precision_coverage_curve,
    threshold_for_precision,
)

__all__ = [
    "DEFAULT_MIN_COVERED",
    "DEFAULT_TARGET_PRECISION",
    "P3_BLOCKER",
    "CalibrationBlocked",
    "PairedResult",
    "SweepPoint",
    "ThresholdProposal",
    "curve_to_json",
    "mcnemar_exact",
    "paired_compare",
    "precision_coverage_curve",
    "propose_threshold",
    "threshold_for_precision",
]
