"""Agrégation de prix de référence (chunk C3 — pipeline prix).

Module pur : depuis les annonces ``single`` d'un coin, produit un prix
de référence par tier d'état (UNC/TTB/TB), percentiles pondérés par la
vélocité de l'annonce. Le step ``sources/_base/steps/price_aggregate``
fait l'I/O DB et persiste dans ``coin_market_quotes``.
"""

from .aggregate import (
    PricedListing,
    TierQuote,
    aggregate_priced_listings,
    clean_outliers,
    velocity_weight,
    weighted_quantile,
    years_since,
)

__all__ = [
    "PricedListing",
    "TierQuote",
    "aggregate_priced_listings",
    "clean_outliers",
    "velocity_weight",
    "weighted_quantile",
    "years_since",
]
