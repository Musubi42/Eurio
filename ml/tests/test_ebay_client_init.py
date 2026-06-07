"""Tests d'initialisation EbayClient (chunk B3 — multi-marketplace).

Couvre la nouvelle signature paramétrique : marketplace obligatoire,
header X-EBAY-C-MARKETPLACE-ID et Accept-Language correctement câblés,
SUPPORTED_MARKETPLACES et MARKETPLACE_ACCEPT_LANGUAGE alignés.
"""

from __future__ import annotations

import pytest

from sources.market.ebay_client import (
    MARKETPLACE_ACCEPT_LANGUAGE,
    SUPPORTED_MARKETPLACES,
    EbayClient,
)


def test_marketplace_required_no_default() -> None:
    with pytest.raises(TypeError):
        # marketplace est keyword-only et sans défaut
        EbayClient("fake-token")  # type: ignore[call-arg]


def test_unknown_marketplace_rejected() -> None:
    with pytest.raises(ValueError, match="SUPPORTED_MARKETPLACES"):
        EbayClient("fake-token", marketplace="EBAY_US")


def test_marketplace_de_sets_headers() -> None:
    with EbayClient("fake-token", marketplace="EBAY_DE") as client:
        headers = client._client.headers
        assert headers["X-EBAY-C-MARKETPLACE-ID"] == "EBAY_DE"
        assert headers["Accept-Language"] == "de-DE"
        assert headers["Authorization"] == "Bearer fake-token"


def test_marketplace_gb_sets_headers() -> None:
    with EbayClient("fake-token", marketplace="EBAY_GB") as client:
        assert client._client.headers["X-EBAY-C-MARKETPLACE-ID"] == "EBAY_GB"
        assert client._client.headers["Accept-Language"] == "en-GB"


def test_accept_language_override() -> None:
    """L'override custom prime sur le mapping par défaut."""
    with EbayClient(
        "fake-token", marketplace="EBAY_BE", accept_language="nl-BE"
    ) as client:
        assert client._client.headers["Accept-Language"] == "nl-BE"
        assert client.accept_language == "nl-BE"


def test_supported_marketplaces_have_accept_language_mapping() -> None:
    """Tout marketplace supporté doit avoir son entrée Accept-Language."""
    assert set(MARKETPLACE_ACCEPT_LANGUAGE) == SUPPORTED_MARKETPLACES


def test_marketplace_attribute_exposed() -> None:
    with EbayClient("fake-token", marketplace="EBAY_FR") as client:
        assert client.marketplace == "EBAY_FR"
