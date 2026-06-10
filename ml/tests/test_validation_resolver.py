"""Resolver d'attribution unifié (C4) — mapping commémo/standard → ListingAttribution.

Les *stratégies* (match_listing_to_group, attribute_standard_listing) sont déjà
testées (test_ebay_standards / test_ebay_adapter). Ici on teste la FUSION : que
les deux types de résultat se mappent fidèlement vers le type unique, et que le
rescue commémo-dans-standard est géré sans parsing côté appelant. On monkeypatch
les stratégies (lazy-importées) pour isoler le mapping de la DB.
"""

from __future__ import annotations

import pytest

import sources.ebay.queries as queries
import sources.ebay.standards as standards
from review.validation.resolver import ListingAttribution, resolve_listing


def _commemo(monkeypatch, gm):
    monkeypatch.setattr(queries, "match_listing_to_group", lambda *a, **k: gm)


def _standard(monkeypatch, sm):
    monkeypatch.setattr(standards, "attribute_standard_listing", lambda *a, **k: sm)


def _resolve_commemo(**kw):
    return resolve_listing(
        "titre", kind="commemorative", denomination=2.0, country="FR",
        year=2014, conn=None, coin_ids=["fr-a", "fr-b"], **kw,
    )


def _resolve_standard():
    return resolve_listing(
        "titre", kind="standard", denomination=2.0, country="BE", conn=None,
    )


# ── Commémo ──────────────────────────────────────────────────────────────

def test_commemo_single(monkeypatch):
    _commemo(monkeypatch, queries.GroupMatch(("fr-a",), "single"))
    att = _resolve_commemo()
    assert att == ListingAttribution("single", "fr-a", (), keep=True, reason=None)


def test_commemo_lot_carries_matched_candidates(monkeypatch):
    _commemo(monkeypatch, queries.GroupMatch(("fr-a", "fr-b"), "lot"))
    att = _resolve_commemo()
    assert att.verdict == "lot" and att.keep
    assert att.target_eurio_id == "fr-a" and att.candidates == ("fr-a", "fr-b")


def test_commemo_ambiguous_carries_all_siblings(monkeypatch):
    _commemo(monkeypatch, queries.GroupMatch((), "ambiguous"))
    att = _resolve_commemo()
    assert att.verdict == "ambiguous" and att.keep
    assert att.target_eurio_id is None and att.candidates == ("fr-a", "fr-b")


def test_commemo_no_match_discards_with_axis(monkeypatch):
    _commemo(monkeypatch, queries.GroupMatch((), "no_match", contradictions=("country",)))
    att = _resolve_commemo()
    assert att.keep is False and att.reason == "group_contradict_country"
    assert att.target_eurio_id is None


# ── Standard ─────────────────────────────────────────────────────────────

def test_standard_single(monkeypatch):
    _standard(monkeypatch, standards.StandardMatch(
        "single", "be-2014", ("be-1999", "be-2014"), "year_resolved:[2015]"))
    att = _resolve_standard()
    assert att.verdict == "single" and att.keep
    assert att.target_eurio_id == "be-2014"
    assert att.candidates == ("be-1999", "be-2014")


def test_standard_ambiguous_keeps_with_candidates(monkeypatch):
    _standard(monkeypatch, standards.StandardMatch(
        "ambiguous", None, ("be-1999", "be-2014"), "year_absent"))
    att = _resolve_standard()
    assert att.verdict == "ambiguous" and att.keep
    assert att.target_eurio_id is None and att.candidates == ("be-1999", "be-2014")


def test_standard_no_match_discards(monkeypatch):
    _standard(monkeypatch, standards.StandardMatch(
        "no_match", None, ("be-1999",), "group_contradict_denomination"))
    att = _resolve_standard()
    assert att.keep is False and att.reason == "group_contradict_denomination"


def test_standard_no_eras_discards(monkeypatch):
    _standard(monkeypatch, standards.StandardMatch("no_eras", None, (), "no_standard_eras"))
    att = _resolve_standard()
    assert att.keep is False and att.reason == "no_standard_eras"


def test_standard_commemo_keyword_discards(monkeypatch):
    _standard(monkeypatch, standards.StandardMatch(
        "commemo", None, ("be-1999",), "commemo_keyword"))
    att = _resolve_standard()
    assert att.keep is False and att.reason == "commemo_keyword"


def test_standard_commemo_theme_hit_is_rescued(monkeypatch):
    # LE cas clé du resolver : un theme-hit commémo dans un run standard est
    # rescué (gardé + audité), plus de parsing de chaîne côté adapter.
    _standard(monkeypatch, standards.StandardMatch(
        "commemo", None, ("be-1999",),
        f"{standards.COMMEMO_IN_STANDARD_PREFIX}be-2016-commemo"))
    att = _resolve_standard()
    assert att.verdict == "rescued" and att.keep is True
    assert att.target_eurio_id == "be-2016-commemo"
    assert att.reason == "rescued_to:be-2016-commemo"
    assert att.candidates == ()  # parité : rescue ne porte pas de candidates


def test_commemo_needs_coin_ids_or_year():
    with pytest.raises(ValueError):
        resolve_listing("t", kind="commemorative", denomination=2.0,
                        country="FR", year=None, conn=None, coin_ids=None)
