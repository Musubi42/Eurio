"""Régression : `arc_coverage` de `measure_tilt` ne doit jamais dépasser 1.0.

Cf. `docs/work-in-progress/juge-du-crop/SUIVI.md` (journal, 2026-08-28). Le
même défaut avait déjà été corrigé côté juge du bench (`bench/gold_crop/judge.py`,
`_arc_coverage`) mais pas ici, dans `vision/crop_detectors.py`, où vit le vrai
calcul utilisé par `measure_tilt`.

Le défaut : `np.degrees(...) % 360.0` rend EXACTEMENT `360.0` pour un angle
négatif infinitésimal (ex. -1e-12 rad). `int(360.0 / 30.0) = 12` tombe alors
hors de `range(12)`, ce qui ouvre un 13ᵉ secteur fantôme et peut faire
`arc_coverage = 13/12 > 1.0`.
"""

from __future__ import annotations

import numpy as np

from vision.crop_detectors import _sector_indices


def test_angle_exactement_360_ne_cree_pas_de_treizieme_secteur():
    """Le cas qui reproduit le bug : un angle qui module à 360.0 pile."""
    angles_deg = np.array([360.0])

    occupied = _sector_indices(angles_deg, n_sectors=12)

    assert occupied == {0}
    assert max(occupied) < 12


def test_angle_infinitesimal_negatif_module_a_360():
    """Le cas réel : atan2 d'un point juste sous l'axe des x, angle -1e-14°,
    donne `% 360.0` == 360.0 en flottant — pas 0.0."""
    angle = -1e-14 % 360.0
    assert angle == 360.0  # documente le piège flottant lui-même

    occupied = _sector_indices(np.array([angle]), n_sectors=12)

    assert occupied == {0}
    assert max(occupied) < 12


def test_arc_coverage_ne_depasse_jamais_1():
    """Un anneau de points couvrant tous les secteurs PLUS le cas 360.0 ne
    doit jamais faire dépasser arc_coverage = occupied / n_sectors au-delà de 1.0."""
    n_sectors = 12
    # Un point par secteur (0°, 30°, ..., 330°) + le cas dégénéré 360.0.
    angles_deg = np.array([i * 30.0 for i in range(n_sectors)] + [360.0])

    occupied = _sector_indices(angles_deg, n_sectors=n_sectors)
    arc_coverage = len(occupied) / n_sectors

    assert len(occupied) <= n_sectors
    assert arc_coverage <= 1.0
