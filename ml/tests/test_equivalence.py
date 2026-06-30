"""Tests for the design-group equivalence rule (phase 3, Option B).

These verrouillent le **contrat** que doit appliquer le matcher Android :
si l'implémentation Kotlin diverge, ces tests gardent la référence
Python. Cf. docs/lab-prod-refacto/phase-3-promote.md §"Critère 7" et
``feedback_output_contract_parity.md``.
"""

from __future__ import annotations

import sys
from pathlib import Path

ML_DIR = Path(__file__).parent.parent
if str(ML_DIR) not in sys.path:
    sys.path.insert(0, str(ML_DIR))

from training.eval.equivalence import EquivalenceMap


def _map():
    return EquivalenceMap(
        eurio_to_group={
            "be-2007-2eur-treaty-of-rome": "treaty-of-rome-2007",
            "de-2007-2eur-treaty-of-rome": "treaty-of-rome-2007",
            "fr-2007-2eur-treaty-of-rome": "treaty-of-rome-2007",
            "at-2002-2eur-standard": None,
            "at-2008-2eur-standard": None,
            "es-1999-2eur-standard": None,
        }
    )


def test_strict_match_is_equivalent():
    m = _map()
    assert m.are_equivalent("at-2002-2eur-standard", "at-2002-2eur-standard")


def test_same_design_group_is_equivalent():
    m = _map()
    assert m.are_equivalent(
        "be-2007-2eur-treaty-of-rome", "de-2007-2eur-treaty-of-rome",
    )
    assert m.are_equivalent(
        "fr-2007-2eur-treaty-of-rome", "be-2007-2eur-treaty-of-rome",
    )


def test_different_groups_not_equivalent():
    m = _map()
    assert not m.are_equivalent(
        "at-2002-2eur-standard", "es-1999-2eur-standard",
    )


def test_null_group_means_no_equivalence_beyond_strict():
    m = _map()
    # Both have design_group=None → only strict eurio_id match is equivalent.
    assert not m.are_equivalent(
        "at-2002-2eur-standard", "at-2008-2eur-standard",
    )


def test_one_has_group_one_doesnt_not_equivalent():
    m = _map()
    assert not m.are_equivalent(
        "be-2007-2eur-treaty-of-rome", "at-2002-2eur-standard",
    )


def test_unknown_eurio_id_not_equivalent():
    m = _map()
    # Unknown predicted → not equivalent to anything except strict self.
    assert not m.are_equivalent("xx-9999-2eur-mystery", "at-2002-2eur-standard")
    assert m.are_equivalent("xx-9999-2eur-mystery", "xx-9999-2eur-mystery")


def test_group_id_as_input_is_equivalent():
    """The lab predicts mesh labels (design_group ids), not eurio_ids.

    Parité avec Android bc17d955 : `are_equivalent` doit traiter un id de
    groupe en entrée (passthrough) et le matcher à un eurio_id du même groupe.
    Régression du faux R@1 strict du §5 (cf.
    project_live_tests_strict_recall_bug).
    """
    m = _map()
    # predicted = group id, ground_truth = eurio_id of that group.
    assert m.are_equivalent("treaty-of-rome-2007", "be-2007-2eur-treaty-of-rome")
    # symmetric.
    assert m.are_equivalent("be-2007-2eur-treaty-of-rome", "treaty-of-rome-2007")
    # group id vs eurio_id of a different group → not equivalent.
    assert not m.are_equivalent("treaty-of-rome-2007", "at-2002-2eur-standard")


def test_none_prediction_not_equivalent():
    m = _map()
    assert not m.are_equivalent(None, "at-2002-2eur-standard")


def test_coalesce():
    m = _map()
    assert m.coalesce("be-2007-2eur-treaty-of-rome") == "treaty-of-rome-2007"
    # already a group id → passthrough.
    assert m.coalesce("treaty-of-rome-2007") == "treaty-of-rome-2007"
    # standalone eurio_id (group=None) → passthrough.
    assert m.coalesce("at-2002-2eur-standard") == "at-2002-2eur-standard"
    # unknown → passthrough.
    assert m.coalesce("xx-9999-2eur-mystery") == "xx-9999-2eur-mystery"
    assert m.coalesce(None) is None


def test_design_group_lookup():
    m = _map()
    assert m.design_group("be-2007-2eur-treaty-of-rome") == "treaty-of-rome-2007"
    assert m.design_group("at-2002-2eur-standard") is None
    assert m.design_group("xx-9999-2eur-mystery") is None


def test_roundtrip_json():
    m = _map()
    text = m.to_json()
    m2 = EquivalenceMap.from_json(text)
    assert m2.eurio_to_group == m.eurio_to_group
    # Re-test a representative case to make sure the loaded map works.
    assert m2.are_equivalent(
        "be-2007-2eur-treaty-of-rome", "de-2007-2eur-treaty-of-rome",
    )
