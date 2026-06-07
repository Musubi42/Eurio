"""Census ladder — fonctions pures géométriques (étage ①).

Vérifie `nms_concentric` et ses primitifs : fusion des fragments/anneaux internes,
MAIS préservation de 2 pièces distinctes d'un lot (bug audité `172ac301` : une pièce
qui déborde du cadre, centre tombant dans la voisine, ne doit PAS être absorbée).
Cf. docs/cohort-pipeline/census-detector-design.md.
"""

from __future__ import annotations

import sys
from pathlib import Path

ML_DIR = Path(__file__).parent.parent
if str(ML_DIR) not in sys.path:
    sys.path.insert(0, str(ML_DIR))

import numpy as np  # noqa: E402
import pytest  # noqa: E402

from vision.census import (  # noqa: E402
    FACE_PROBE_PATH,
    _area,
    _center_in,
    _iou,
    load_face_probe,
    nms_concentric,
)


def test_iou_disjoint_and_identical():
    assert _iou((0, 0, 10, 10), (20, 20, 30, 30)) == 0.0
    assert _iou((0, 0, 10, 10), (0, 0, 10, 10)) == 1.0


def test_iou_half_overlap():
    # deux carrés 10×10 chevauchant sur moitié horizontale : inter=50, union=150
    assert abs(_iou((0, 0, 10, 10), (5, 0, 15, 10)) - (50 / 150)) < 1e-6


def test_center_in():
    big = (0, 0, 100, 100)
    assert _center_in((40, 40, 60, 60), big)        # petit centré dedans
    assert not _center_in((90, 90, 130, 130), big)  # centre (110,110) hors


def test_area():
    assert _area((0, 0, 10, 20)) == 200


def test_nms_absorbs_inner_fragment():
    # Anneau bimétal interne : petit fragment (aire 36) centré dans la pièce (aire 10000).
    coin = (0, 0, 100, 100)
    inner = (47, 47, 53, 53)
    out = nms_concentric([coin, inner])
    assert out == [coin]                            # fragment absorbé


def test_nms_absorbs_high_iou_duplicate():
    a = (0, 0, 100, 100)
    b = (3, 3, 103, 103)                            # quasi-doublon, IoU élevé
    assert nms_concentric([a, b]) == [a]


def test_nms_keeps_two_distinct_coins_of_a_lot():
    # Bug audité : 2 pièces de taille comparable, l'une déborde du cadre et son
    # centre tombe DANS la boîte voisine → NE DOIT PAS être absorbée (garde aire ≥ 0.7×).
    big = (0, 0, 100, 100)                          # aire 10000
    neighbor = (50, 50, 140, 140)                   # centre (95,95) ∈ big, aire 8100 ≥ 0.7×
    assert _center_in(neighbor, big)                # centre bien dans la voisine
    assert _iou(big, neighbor) < 0.30               # IoU faible → pas un doublon
    out = nms_concentric([big, neighbor])
    assert len(out) == 2                            # garde de taille → les 2 préservées


def test_nms_edge_guard_keeps_overlapping_partial_coins():
    # Cas audité 172ac301 : 2 boîtes larges débordantes touchant le bord haut, IoU>0.30.
    # Sans img_wh → fusionnées (1) ; avec img_wh → garde bord → préservées (2).
    a = (572, 0, 1293, 161)
    b = (315, 0, 1008, 143)
    assert _iou(a, b) > 0.30
    assert len(nms_concentric([a, b])) == 1               # garde bord OFF
    assert len(nms_concentric([a, b], img_wh=(1300, 900))) == 2  # garde bord ON


def test_nms_edge_guard_still_absorbs_central_fragment():
    # La garde bord ne doit PAS empêcher d'absorber un fragment interne central.
    coin = (100, 100, 300, 300)
    inner = (190, 190, 210, 210)
    assert nms_concentric([coin, inner], img_wh=(1000, 1000)) == [coin]


def test_nms_empty():
    assert nms_concentric([]) == []


# --- Probe face-vs-fragment (gate anti-fragment census) --------------------

def test_face_probe_missing_raises(tmp_path):
    # R0 : pas de fallback silencieux — probe absente ⇒ RuntimeError explicite.
    with pytest.raises(RuntimeError, match="Probe face-vs-fragment absente"):
        load_face_probe(tmp_path / "nope.npz")


@pytest.mark.skipif(not FACE_PROBE_PATH.exists(),
                    reason="probe non générée (build_fragment_probe.py)")
def test_face_probe_shape():
    coef, intercept = load_face_probe()
    assert coef.ndim == 1 and coef.shape[0] == 384   # dim features DINO
    assert isinstance(intercept, float)
