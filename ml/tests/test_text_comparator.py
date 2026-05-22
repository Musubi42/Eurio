"""Tests du comparateur vs_target (chunk 6 auto-validation).

Module pur — pas de DB. ``load_target_identity`` est testé séparément
dans test_text_signal_step.py via une fixture coins.
"""

from __future__ import annotations

from sources.text_signals import (
    GroupIdentity,
    ListingTextSignals,
    TargetIdentity,
    compare_to_group,
    compare_to_target,
)


def _signals(
    *,
    countries: set[str] = frozenset(),
    years: set[int] = frozenset(),
    denominations: set[float] = frozenset(),
    is_lot: bool = False,
) -> ListingTextSignals:
    n_present = sum([bool(countries), bool(years), bool(denominations)])
    coverage = "rich" if n_present == 3 else ("sparse" if n_present else "empty")
    return ListingTextSignals(
        countries=frozenset(countries),
        years=frozenset(years),
        denominations=frozenset(denominations),
        theme_tokens=(),
        rejected_markers=(),
        is_lot=is_lot,
        coverage=coverage,
        matched={},
    )


def _target(country: str = "fr", year: int = 2014, fv: float = 2.0) -> TargetIdentity:
    return TargetIdentity(
        eurio_id=f"{country}-{year}-2eur-test",
        country=country,
        year=year,
        face_value=fv,
    )


# ── 1-9 cas du kickoff ──────────────────────────────────────────────────────


def test_convergent_when_all_signals_match():
    sig = _signals(countries={"FR"}, years={2014}, denominations={2.0})
    cmp = compare_to_target(sig, _target())
    assert cmp.verdict == "convergent"
    assert set(cmp.convergences) == {"country", "year", "denomination"}
    assert cmp.contradictions == ()


def test_contradict_on_country_mismatch():
    sig = _signals(countries={"BE"}, years={2014}, denominations={2.0})
    cmp = compare_to_target(sig, _target())
    assert cmp.verdict == "contradict"
    assert "country" in cmp.contradictions
    # year + denom restent convergent (audit trace)
    assert set(cmp.convergences) == {"year", "denomination"}


def test_contradict_on_year_mismatch():
    sig = _signals(countries={"FR"}, years={2018}, denominations={2.0})
    cmp = compare_to_target(sig, _target(year=2014))
    assert cmp.verdict == "contradict"
    assert "year" in cmp.contradictions


def test_contradict_on_face_value_mismatch():
    sig = _signals(countries={"FR"}, years={2014}, denominations={1.0})
    cmp = compare_to_target(sig, _target(fv=2.0))
    assert cmp.verdict == "contradict"
    assert "denomination" in cmp.contradictions


def test_partial_when_country_absent_but_others_match():
    # Pas de pays détecté → axis country="absent". Les 2 autres convergent.
    sig = _signals(countries=set(), years={2014}, denominations={2.0})
    cmp = compare_to_target(sig, _target())
    assert cmp.verdict == "partial"
    assert set(cmp.convergences) == {"year", "denomination"}
    assert cmp.contradictions == ()


def test_absent_on_empty_signals():
    sig = _signals(countries=set(), years=set(), denominations=set())
    cmp = compare_to_target(sig, _target())
    assert cmp.verdict == "absent"
    assert cmp.contradictions == ()
    assert cmp.convergences == ()


def test_year_range_envelops_target_is_not_contradict():
    # Titre "2005-2025" → years={2005, 2025}. Target=2014 dans la plage.
    sig = _signals(countries={"FR"}, years={2005, 2025}, denominations={2.0})
    cmp = compare_to_target(sig, _target(year=2014))
    assert cmp.verdict == "convergent"
    assert "year" in cmp.convergences


def test_multi_country_with_target_present_not_contradict():
    sig = _signals(countries={"FR", "IT"}, years={2014}, denominations={2.0})
    cmp = compare_to_target(sig, _target(country="fr"))
    assert cmp.verdict == "convergent"


def test_lot_with_target_country_is_convergent_not_contradict():
    sig = _signals(
        countries={"AT"}, years={2018}, denominations={2.0}, is_lot=True
    )
    cmp = compare_to_target(sig, _target(country="at", year=2018))
    assert cmp.verdict == "convergent"
    # is_lot ne change pas le verdict — c'est un signal séparé pour
    # bloquer l'auto-accept au chunk 8, pas pour rejeter ici.


# ── Edge cases additionnels ─────────────────────────────────────────────────


def test_case_insensitive_country_match():
    """L'extracteur produit ISO2 uppercase, target stocké lowercase. Le
    comparateur normalise les deux côtés."""
    sig = _signals(countries={"FR"}, years={2014}, denominations={2.0})
    cmp = compare_to_target(sig, _target(country="fr"))
    assert cmp.verdict == "convergent"

    cmp2 = compare_to_target(sig, _target(country="FR"))  # tolerant
    assert cmp2.verdict == "convergent"


def test_year_outside_range_contradicts():
    # Titre "2005-2010" → target=2014 hors plage.
    sig = _signals(countries={"FR"}, years={2005, 2010}, denominations={2.0})
    cmp = compare_to_target(sig, _target(year=2014))
    assert cmp.verdict == "contradict"
    assert "year" in cmp.contradictions


def test_year_equals_range_boundary_is_convergent():
    # Bordure : year ∈ {2014, 2025}, target=2014 → présence directe.
    sig = _signals(countries={"FR"}, years={2014, 2025}, denominations={2.0})
    cmp = compare_to_target(sig, _target(year=2014))
    assert cmp.verdict == "convergent"


def test_convergences_axis_order_is_stable():
    sig = _signals(countries={"FR"}, years={2014}, denominations={2.0})
    cmp = compare_to_target(sig, _target())
    assert cmp.convergences == ("country", "year", "denomination")


def test_multiple_contradictions_aggregated():
    sig = _signals(countries={"BE"}, years={2018}, denominations={1.0})
    cmp = compare_to_target(sig, _target(country="fr", year=2014, fv=2.0))
    assert cmp.verdict == "contradict"
    assert cmp.contradictions == ("country", "year", "denomination")
    assert cmp.convergences == ()


def test_partial_when_one_axis_absent_one_convergent():
    # Year absent, country et denom convergent.
    sig = _signals(countries={"FR"}, years=set(), denominations={2.0})
    cmp = compare_to_target(sig, _target())
    assert cmp.verdict == "partial"
    assert set(cmp.convergences) == {"country", "denomination"}


def test_target_identity_carried_in_result():
    sig = _signals(countries={"FR"})
    target = _target(country="fr", year=2014, fv=2.0)
    cmp = compare_to_target(sig, target)
    assert cmp.target_eurio_id == target.eurio_id
    assert cmp.target_country == "fr"
    assert cmp.target_year == 2014
    assert cmp.target_face_value == 2.0


# ── compare_to_group (garde-fou de contradiction) ───────────────────────────

def _group(country: str = "be", year: int = 2018, fv: float = 2.0) -> GroupIdentity:
    return GroupIdentity(country=country, year=year, face_value=fv)


def test_group_no_contradiction_when_convergent():
    sig = _signals(countries={"BE"}, years={2018}, denominations={2.0})
    assert compare_to_group(sig, _group()) == ()


def test_group_no_contradiction_when_signals_absent():
    # « évidence absente ≠ contradiction » — un titre muet ne contredit pas
    assert compare_to_group(_signals(), _group()) == ()


def test_group_contradiction_on_country():
    # « Eslovenia 2€ 2018 » dans un groupe BE
    sig = _signals(countries={"SI"}, years={2018}, denominations={2.0})
    assert compare_to_group(sig, _group()) == ("country",)


def test_group_contradiction_on_denomination():
    # un 5 € dans un groupe 2 €
    sig = _signals(countries={"BE"}, years={2018}, denominations={5.0})
    assert compare_to_group(sig, _group()) == ("denomination",)


def test_group_contradiction_on_year():
    sig = _signals(countries={"BE"}, years={2010}, denominations={2.0})
    assert compare_to_group(sig, _group()) == ("year",)


def test_group_contradiction_multi_axis_ordered():
    sig = _signals(countries={"SI"}, years={2010}, denominations={5.0})
    assert compare_to_group(sig, _group()) == ("country", "year", "denomination")


def test_group_year_range_does_not_contradict():
    # un titre « 2000-2025 » n'invalide pas un groupe 2018 (plage englobante)
    sig = _signals(countries={"BE"}, years={2000, 2025}, denominations={2.0})
    assert compare_to_group(sig, _group()) == ()
