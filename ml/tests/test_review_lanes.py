"""Tests du routage centralisé verdict → lane (foundation/review_lanes.py)."""

import sys
from pathlib import Path

ML_DIR = Path(__file__).resolve().parents[1]
if str(ML_DIR) not in sys.path:
    sys.path.insert(0, str(ML_DIR))

from training.foundation.review_lanes import (  # noqa: E402
    DEFAULT_LANE,
    LANES,
    VERDICT_TO_LANE,
    verdict_to_lane,
)


def test_verdict_to_lane_mapping():
    # Les 4 niveaux de verdict Dino → 3 lanes (mapping verrouillé WS1).
    assert verdict_to_lane("auto_candidate") == "auto_accept"
    assert verdict_to_lane("partial") == "ccproxy"
    assert verdict_to_lane("divergent") == "ccproxy"
    assert verdict_to_lane("unknown") == "manual"


def test_verdict_to_lane_fallback_is_manual():
    # Verdict inconnu / None → filet de sécurité = manual.
    assert verdict_to_lane(None) == DEFAULT_LANE
    assert verdict_to_lane("") == DEFAULT_LANE
    assert verdict_to_lane("nimporte_quoi") == DEFAULT_LANE
    assert DEFAULT_LANE == "manual"


def test_every_mapped_lane_is_valid():
    # Toute lane produite par la règle appartient à l'ensemble valide (CHECK DB).
    for lane in VERDICT_TO_LANE.values():
        assert lane in LANES
    assert set(LANES) == {"manual", "auto_accept", "ccproxy"}
