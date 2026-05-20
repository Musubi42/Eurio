"""Tests du routage marketplace eBay (chunk B2).

Vérifie que chaque pays eurozone + 'eu' a une entrée explicite, que les
profils (natif, fallback langue, GB-only) respectent marketplace-map.md,
et que les pays inconnus lèvent UnknownCountry plutôt que de retourner
un défaut silencieux.
"""

from __future__ import annotations

import pytest

from sources.ebay.marketplaces import (
    EBAY_GB,
    MarketplaceRoute,
    UnknownCountry,
    all_routes,
    route_for,
)


# Source de vérité — alignée sur marketplace-map.md (commit B1).
EUROZONE_21 = {
    "AT", "BE", "BG", "CY", "DE", "EE", "ES", "FI", "FR", "GR", "HR",
    "IE", "IT", "LT", "LU", "LV", "MT", "NL", "PT", "SI", "SK",
}
NATIVE_MARKETPLACES = {
    "AT": ("EBAY_AT", "de"),
    "BE": ("EBAY_BE", "fr"),
    "DE": ("EBAY_DE", "de"),
    "ES": ("EBAY_ES", "es"),
    "FR": ("EBAY_FR", "fr"),
    "IE": ("EBAY_IE", "en"),
    "IT": ("EBAY_IT", "it"),
    "NL": ("EBAY_NL", "nl"),
}
LANG_FALLBACK = {
    "AD": ("EBAY_ES", "es"),
    "LU": ("EBAY_FR", "fr"),
    "MC": ("EBAY_FR", "fr"),
    "SM": ("EBAY_IT", "it"),
    "VA": ("EBAY_IT", "it"),
}
# PT : probe V1 (2026-05-20) → recall ES/GB = 1.68× < seuil ×2 → GB-only.
GB_ONLY = {"BG", "CY", "EE", "FI", "GR", "HR", "LT", "LV", "MT", "PT", "SI", "SK", "eu"}


def test_native_marketplaces() -> None:
    for country, (mkt, lang) in NATIVE_MARKETPLACES.items():
        r = route_for(country)
        assert r.primary == mkt, (country, r)
        assert r.query_lang == lang, (country, r)
        assert r.global_ == EBAY_GB


def test_lang_fallback() -> None:
    for country, (mkt, lang) in LANG_FALLBACK.items():
        r = route_for(country)
        assert r.primary == mkt, (country, r)
        assert r.query_lang == lang, (country, r)


def test_gb_only_countries() -> None:
    for country in GB_ONLY:
        r = route_for(country)
        assert r.primary is None, (country, r)
        assert r.global_ == EBAY_GB
        assert r.query_lang == "en"


def test_eurozone_21_plus_eu_all_mapped() -> None:
    """Aucun pays eurozone (+ 'eu' joint + 6 micro-États) ne tombe en KeyError."""
    must_map = EUROZONE_21 | {"AD", "MC", "SM", "VA", "eu"}
    for country in must_map:
        route_for(country)  # ne lève pas


def test_unknown_country_raises() -> None:
    with pytest.raises(UnknownCountry):
        route_for("XX")
    with pytest.raises(UnknownCountry):
        route_for("us")  # case-sensitive, on n'accepte pas us minuscule


def test_routes_are_frozen() -> None:
    r = route_for("FR")
    with pytest.raises(Exception):
        r.primary = "EBAY_DE"  # type: ignore[misc]


def test_all_routes_returns_copy() -> None:
    snapshot = all_routes()
    snapshot["XX"] = MarketplaceRoute(primary=None)
    # Le dict canonique ne doit pas être muté
    with pytest.raises(UnknownCountry):
        route_for("XX")
