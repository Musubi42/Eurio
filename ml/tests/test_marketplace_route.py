"""Tests du routage marketplace eBay.

Le routage est uniforme depuis le benchmark itération 3 (2026-05-21) :
``{EBAY_DE, EBAY_ES}`` pour toutes les origines, chacun queryé dans sa
langue native. Cf. ``marketplaces.py`` et
``docs/sources-refacto/ebay-multi-marketplace/research/marketplace-routing-benchmark.md``.
"""

from __future__ import annotations

from sources.ebay.marketplaces import (
    DISCOVERY_MARKETPLACES,
    MarketplaceCall,
    discovery_marketplaces,
)


def test_discovery_is_de_then_es() -> None:
    """Discovery interroge EBAY_DE puis EBAY_ES, dans cet ordre."""
    calls = discovery_marketplaces()
    assert [c.marketplace for c in calls] == ["EBAY_DE", "EBAY_ES"]


def test_each_marketplace_queried_in_native_lang() -> None:
    """DE → query 'de', ES → query 'es' (config gagnante du benchmark)."""
    langs = {c.marketplace: c.query_lang for c in discovery_marketplaces()}
    assert langs == {"EBAY_DE": "de", "EBAY_ES": "es"}


def test_gb_removed() -> None:
    """EBAY_GB est retiré du routage (0 listing EUR exploitable)."""
    assert "EBAY_GB" not in {c.marketplace for c in discovery_marketplaces()}


def test_marketplace_call_is_frozen() -> None:
    call = DISCOVERY_MARKETPLACES[0]
    try:
        call.marketplace = "EBAY_GB"  # type: ignore[misc]
    except Exception:
        return
    raise AssertionError("MarketplaceCall doit être frozen")


def test_discovery_marketplaces_is_stable() -> None:
    """Routage uniforme : la même paire quelle que soit l'origine."""
    assert discovery_marketplaces() is DISCOVERY_MARKETPLACES
    assert discovery_marketplaces() == (
        MarketplaceCall("EBAY_DE", "de"),
        MarketplaceCall("EBAY_ES", "es"),
    )
