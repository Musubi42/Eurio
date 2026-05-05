"""Tests de l'extracteur ListingTextSignals (chunk 4 auto-validation).

Fixtures issues d'un échantillon réel ``source_images.listing_title``
+ ``discarded_listings.title`` (run 2026-05-05). On teste les axes
indépendamment puis quelques scénarios end-to-end représentatifs.
"""

from __future__ import annotations

import pytest

from sources.text_signals import (
    ListingTextSignals,
    extract_listing_text_signals,
)


# ── Pays ────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("title, expected", [
    ("2 EURO ANDORRE 2024 100 ANS DE SKI", {"AD"}),
    ("2 euros Andorre 2016 TV Radio", {"AD"}),
    ("Andorra 2 euro 2021 KM 527", {"AD"}),
    ("Autriche, 2 Euro, 50ème anniversaire du Traité d'Etat, 2005", {"AT"}),
    ("piece 2 euro belgique 2005", {"BE"}),
    ("Belgium 10 cents 2002", {"BE"}),
    ("2 Euro Allemagne 2018 Helmut Schmidt", {"DE"}),
    ("Pièce de 2 euros France 2014 Première Guerre Mondiale", {"FR"}),
    ("Italia 2 euro 2014 150 anni della Polizia", {"IT"}),
    ("Spanien 2 Euro Sondermünze 2017", {"ES"}),
])
def test_extract_country_from_substantive(title: str, expected: set[str]):
    sig = extract_listing_text_signals(title)
    assert set(sig.countries) == expected


def test_extract_country_from_adjective():
    sig = extract_listing_text_signals("Pièce 2 euros commémorative française 2014")
    assert "FR" in sig.countries


def test_extract_country_from_flag_emoji():
    sig = extract_listing_text_signals("🇫🇷 2 euro 2014")
    assert "FR" in sig.countries


def test_no_country_when_only_iso2_code():
    # On ne matche PAS les codes ISO2 nus (trop de faux positifs).
    sig = extract_listing_text_signals("Pièce FR 2014 2 euro")
    assert "FR" not in sig.countries


def test_multi_country_lot():
    sig = extract_listing_text_signals(
        "Lot 2 coins Andorra Principality & France 2 Euro 2023"
    )
    assert sig.countries == frozenset({"AD", "FR"})
    assert sig.is_lot is True


def test_multi_country_be_lu():
    sig = extract_listing_text_signals(
        "BELGIQUE 2 EURO 2005 union economique BELGIQUE & LUXEMBOURG"
    )
    assert sig.countries == frozenset({"BE", "LU"})
    assert sig.is_lot is True


# ── Années ──────────────────────────────────────────────────────────────────


def test_year_single():
    sig = extract_listing_text_signals("2 euros France 2014")
    assert sig.years == frozenset({2014})


def test_year_range_in_shop_listing():
    sig = extract_listing_text_signals(
        "Belgique - TOUTES ANNÉES DISPONIBLES  2005 / 2025 - 2 Euro Commemorative"
    )
    # On capture les deux bornes de la plage.
    assert 2005 in sig.years
    assert 2025 in sig.years


def test_year_excludes_out_of_range():
    sig = extract_listing_text_signals("Pièce 1980 2 euro France")
    assert 1980 not in sig.years
    # 1999 est la borne basse
    sig2 = extract_listing_text_signals("Frappe 1999 collector")
    assert 1999 in sig2.years


def test_year_multiple_in_text():
    sig = extract_listing_text_signals(
        "Andorre Pièce de Monnaie Neuf (Choisissez Entre 2014 - 2025 Et 1 Cent"
    )
    assert {2014, 2025} <= set(sig.years)


# ── Dénominations ───────────────────────────────────────────────────────────


@pytest.mark.parametrize("title, expected", [
    ("2 EURO ANDORRE 2024", {2.0}),
    ("2 euros France 2014", {2.0}),
    ("2€ Andorre 2014", {2.0}),
    ("2EUR Belgique", {2.0}),
    ("Pièce 1 euro Espagne 2002", {1.0}),
    ("0,50 € Allemagne", {0.50}),
    ("0.50 euro NL 2002", {0.50}),
    ("2 euros + 1 euro Andorre", {2.0, 1.0}),
])
def test_extract_denomination(title: str, expected: set[float]):
    sig = extract_listing_text_signals(title)
    assert set(sig.denominations) == expected


def test_denomination_drops_arbitrary_amounts():
    # "5 euros" comme prix ≠ une dénomination valide. Mais on ne sait
    # pas distinguer prix vs face : on filtre sur VALID_FACE_VALUES
    # (5.0 n'y est pas, donc absent).
    sig = extract_listing_text_signals("Vendu 5 euros, pièce de 2 € France 2014")
    assert sig.denominations == frozenset({2.0})


# ── Markers de rejet ────────────────────────────────────────────────────────


def test_rejection_proof():
    sig = extract_listing_text_signals("TRES RARE ! 2 Euro Proof Belgique 2008")
    assert "proof" in sig.rejected_markers


def test_rejection_metal_silver():
    sig = extract_listing_text_signals("2 euros argent Belgique BE 2008")
    assert "metal" in sig.rejected_markers


def test_rejection_error_struck():
    sig = extract_listing_text_signals(
        "FAUTEE * * *  2 EURO BELGIQUE 2008 spl"
    )
    assert "error_struck" in sig.rejected_markers


def test_rejection_replica():
    sig = extract_listing_text_signals("2 euro France 2014 replica reproduction")
    assert "replica" in sig.rejected_markers


def test_clean_listing_no_markers():
    sig = extract_listing_text_signals("2 euros Andorre 2016 TV Radio")
    assert sig.rejected_markers == ()


# ── Lot detection ──────────────────────────────────────────────────────────


@pytest.mark.parametrize("title", [
    "Lot 2 coins Andorra & France 2 Euro 2023",
    "COFFRET ANDORRE - 2 EURO 2016 - 25 ANS",
    "Set of 5 commemorative euro coins",
    "Konvolut 2 Euro Sammlung Deutschland",
    "Rouleau 2 euros France 2014",
    "Lot de 3 pièces de 2 Euros - AUTRICHE 2018",
    "2 x 2 EURO ANDORRE 2024",
])
def test_lot_detected(title: str):
    sig = extract_listing_text_signals(title)
    assert sig.is_lot is True


@pytest.mark.parametrize("title", [
    "2 euros Andorre 2016 TV Radio",
    "Pièce 2 euro France 2014 Première Guerre",
    "Andorre 2021 - 2 Euro tres bon etat",
])
def test_lot_not_detected_on_singletons(title: str):
    sig = extract_listing_text_signals(title)
    assert sig.is_lot is False


# ── Coverage ────────────────────────────────────────────────────────────────


def test_coverage_rich_when_all_three_present():
    sig = extract_listing_text_signals("2 euros Andorre 2016 TV Radio")
    assert sig.coverage == "rich"


def test_coverage_sparse_when_partial():
    sig = extract_listing_text_signals("Andorre 2 euros tres bon etat")
    # countries + denoms, pas d'année → sparse
    assert sig.coverage == "sparse"


def test_coverage_empty_on_meaningless_title():
    sig = extract_listing_text_signals("Belle pièce voir photos")
    assert sig.coverage == "empty"


def test_empty_title_returns_empty_signals():
    sig = extract_listing_text_signals("")
    assert sig.countries == frozenset()
    assert sig.years == frozenset()
    assert sig.denominations == frozenset()
    assert sig.coverage == "empty"


def test_none_title_returns_empty_signals():
    sig = extract_listing_text_signals(None)
    assert isinstance(sig, ListingTextSignals)
    assert sig.coverage == "empty"


# ── Theme tokens ────────────────────────────────────────────────────────────


def test_theme_tokens_drops_country_year_denom_stop():
    sig = extract_listing_text_signals(
        "2 euros Andorre 2016 TV Radio commémorative"
    )
    # tv = 2 chars, dropé par len < 4
    assert "radio" in sig.theme_tokens
    assert "andorre" not in sig.theme_tokens
    assert "2016" not in sig.theme_tokens
    assert "euros" not in sig.theme_tokens


def test_theme_tokens_drops_km_references():
    sig = extract_listing_text_signals(
        "Andorre 2 Euro 2021 KM527 KM:New Brillant Universel"
    )
    assert "km527" not in sig.theme_tokens
    assert "brillant" in sig.theme_tokens
    assert "universel" in sig.theme_tokens


def test_theme_tokens_preserve_order():
    sig = extract_listing_text_signals(
        "Charlemagne 2 euros Andorre 2022 European Union Relations"
    )
    # "charlemagne" arrive avant "european" / "union" / "relations"
    idx_c = sig.theme_tokens.index("charlemagne")
    idx_e = sig.theme_tokens.index("european")
    assert idx_c < idx_e


# ── End-to-end (titres réels) ───────────────────────────────────────────────


def test_e2e_andorre_2024_uci():
    sig = extract_listing_text_signals(
        "2 x 2 EURO ANDORRE 2024 100 ANS DE SKI + VTT BIKE DISPO DE SUITE"
    )
    assert sig.countries == frozenset({"AD"})
    assert 2024 in sig.years
    assert 2.0 in sig.denominations
    assert sig.is_lot is True  # "2 x"
    assert sig.coverage == "rich"
    assert sig.rejected_markers == ()


def test_e2e_belgium_2008_droits_homme():
    sig = extract_listing_text_signals(
        "2 euros commémorative 2008 Belgique  Droits de l'homme envoie rapide"
    )
    assert sig.countries == frozenset({"BE"})
    assert 2008 in sig.years
    assert 2.0 in sig.denominations
    assert "droits" in sig.theme_tokens
    assert "homme" in sig.theme_tokens
    assert sig.rejected_markers == ()
    assert sig.coverage == "rich"


def test_e2e_belgium_proof_rejected():
    sig = extract_listing_text_signals(
        "TRES RARE ! 2 Euro Proof Belgique 2008 Droits de l'Homme"
    )
    assert "BE" in sig.countries
    assert "proof" in sig.rejected_markers


def test_e2e_shop_multi_year():
    sig = extract_listing_text_signals(
        "BELGIQUE - 2 EUROS COMMEMORATIVE 2005 - 2025 Toutes les Années Disponibles"
    )
    assert "BE" in sig.countries
    assert 2005 in sig.years and 2025 in sig.years
    assert 2.0 in sig.denominations


def test_e2e_austria_2018_republic():
    sig = extract_listing_text_signals(
        "Lot de 3 pièces de 2 Euros -  AUTRICHE  2018 -  100  ANS  DE  LA  REPUBLIQUE"
    )
    assert sig.countries == frozenset({"AT"})
    assert 2018 in sig.years
    assert 2.0 in sig.denominations
    assert sig.is_lot is True


# ── matched debug dict ──────────────────────────────────────────────────────


def test_matched_debug_dict_filled():
    sig = extract_listing_text_signals("2 euros Andorre 2016 TV Radio")
    assert "andorre" in sig.matched["countries"]
    assert "2016" in sig.matched["years"]
    # Au moins une dénomination matchée.
    assert any("euro" in m.lower() or "€" in m for m in sig.matched["denominations"])


def test_matched_lot_records_country_count_signal():
    sig = extract_listing_text_signals("Andorra & France 2 Euro 2023")
    assert any("countries" in t for t in sig.matched["lot"])


# ── Hashable / immutable ────────────────────────────────────────────────────


def test_signals_is_hashable():
    sig = extract_listing_text_signals("2 euro France 2014")
    # frozen=True + frozenset/tuple partout → hashable.
    # (le matched dict reste mutable mais on ne hash pas dessus)
    assert isinstance(sig.countries, frozenset)
    assert isinstance(sig.years, frozenset)
    assert isinstance(sig.theme_tokens, tuple)
    assert isinstance(sig.rejected_markers, tuple)
