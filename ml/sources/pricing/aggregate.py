"""Agrégation de prix — module pur, no I/O (chunk C3 — pipeline prix).

Depuis les annonces ``single`` (pièce nue) d'un coin, produit un prix de
référence par tier d'état (UNC / TTB / TB) : percentiles p10/p50/p90
pondérés par la **vélocité** de l'annonce, après nettoyage des outliers.

Pondération vélocité : une annonce récente et/ou qui s'est vendue
reflète mieux le prix courant qu'une annonce ancienne invendue — les
vendeurs listent haut et laissent traîner. C'est le proxy V1 du biais
« prix demandé ≠ prix de vente » (la Browse API n'expose pas les ventes
réalisées). Cf. discussion 2026-05-21.

Lots / coffrets / slabs gradés sont exclus EN AMONT (le step filtre
``listing_kind='single'``) — ce module ne voit que des pièces nues.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timezone

# Le prix légitime d'une même pièce dans un même tier dépasse rarement
# un facteur ×4. Au-delà = enchère à prix de départ bradé, ou annonce
# « rare » survendue → outlier écarté avant les percentiles.
OUTLIER_RATIO = 4.0
# En dessous de ce nombre d'annonces, l'échantillon est trop mince pour
# distinguer un outlier d'une vraie dispersion → on ne nettoie pas.
# À 3, la médiane (élément central) reste robuste à un outlier unique.
MIN_SAMPLES_FOR_OUTLIER = 3
# Garde-fou inter-tier : une pièce circulée (TTB/TB) ne vaut pas plus
# qu'une neuve (UNC). Un tier non-UNC dont le p50 dépasse ce facteur ×
# le p50 UNC a un échantillon contaminé (annonce gradée/coffret mal
# taguée, ou mauvaise attribution) → sa quote est supprimée.
MAX_TIER_RATIO_VS_UNC = 3.0


@dataclass(frozen=True)
class PricedListing:
    """Une annonce ``single`` réduite à ce dont l'agrégation a besoin."""

    price: float
    condition: str                  # 'UNC' | 'TTB' | 'TB'
    sold_qty: int = 0
    origin_date: str | None = None   # ISO8601 — mise en ligne de l'annonce


@dataclass(frozen=True)
class TierQuote:
    """Prix de référence agrégé pour un tier d'état d'un coin."""

    condition: str
    p10: float | None
    p50: float | None
    p90: float | None
    sample_size: int   # n annonces retenues (après nettoyage outliers)
    n_raw: int         # n annonces avant nettoyage


def years_since(origin_date: str | None, *, now: datetime | None = None) -> float:
    """Âge de l'annonce en années. Défaut 0.5 si date absente/illisible."""
    if not origin_date:
        return 0.5
    try:
        dt = datetime.fromisoformat(origin_date.replace("Z", "+00:00"))
    except ValueError:
        return 0.5
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    now = now or datetime.now(timezone.utc)
    return max((now - dt).days / 365.25, 0.5)


def velocity_weight(
    listing: PricedListing, *, now: datetime | None = None,
) -> float:
    """Poids d'une annonce dans l'agrégation.

    Favorise les annonces récentes (prix demandé ≈ prix courant) et
    celles qui se sont vendues (``sold_qty > 0`` = prix validé par le
    marché). Une annonce ancienne ET invendue pèse peu — son prix
    demandé est probablement trop haut. Plancher à 0.05 pour qu'aucune
    annonce ne soit totalement ignorée.
    """
    years = years_since(listing.origin_date, now=now)
    recency = 1.0 / (1.0 + years)               # ~1 si récent, →0 si vieux
    sales_per_year = (listing.sold_qty or 0) / years
    velocity = math.log1p(sales_per_year)        # bonus si ça se vend
    return max(recency * (1.0 + velocity), 0.05)


def weighted_quantile(
    values: list[float], weights: list[float], q: float,
) -> float | None:
    """q-quantile pondéré. Fallback non-pondéré si poids totaux ≤ 0."""
    if not values:
        return None
    paired = sorted(zip(values, weights))
    total = sum(w for _, w in paired)
    if total <= 0:
        vals = [v for v, _ in paired]
        return vals[int(q * (len(vals) - 1))]
    target = q * total
    cum = 0.0
    for v, w in paired:
        cum += w
        if cum >= target:
            return v
    return paired[-1][0]


def _median(values: list[float]) -> float:
    s = sorted(values)
    n = len(s)
    return s[n // 2] if n % 2 else (s[n // 2 - 1] + s[n // 2]) / 2.0


def clean_outliers(priced: list[PricedListing]) -> list[PricedListing]:
    """Retire les prix hors ``[médiane/RATIO, médiane×RATIO]``.

    Skip quand l'échantillon est trop mince (< MIN_SAMPLES_FOR_OUTLIER) :
    pas assez de points pour juger.
    """
    if len(priced) < MIN_SAMPLES_FOR_OUTLIER:
        return list(priced)
    median = _median([p.price for p in priced])
    if median <= 0:
        return list(priced)
    lo, hi = median / OUTLIER_RATIO, median * OUTLIER_RATIO
    return [p for p in priced if lo <= p.price <= hi]


def _round(value: float | None) -> float | None:
    return round(value, 2) if value is not None else None


def aggregate_priced_listings(
    listings: list[PricedListing], *, now: datetime | None = None,
) -> list[TierQuote]:
    """Groupe les annonces par tier d'état → un :class:`TierQuote` par tier.

    Un tier sans annonce ne produit pas de quote. Les percentiles sont
    pondérés par :func:`velocity_weight`, calculés après nettoyage des
    outliers.
    """
    by_tier: dict[str, list[PricedListing]] = {}
    for listing in listings:
        by_tier.setdefault(listing.condition, []).append(listing)

    quotes: list[TierQuote] = []
    for tier, group in by_tier.items():
        cleaned = clean_outliers(group)
        if not cleaned:
            continue
        prices = [p.price for p in cleaned]
        weights = [velocity_weight(p, now=now) for p in cleaned]
        quotes.append(TierQuote(
            condition=tier,
            p10=_round(weighted_quantile(prices, weights, 0.10)),
            p50=_round(weighted_quantile(prices, weights, 0.50)),
            p90=_round(weighted_quantile(prices, weights, 0.90)),
            sample_size=len(cleaned),
            n_raw=len(group),
        ))

    # Garde-fou inter-tier : on supprime un tier circulé dont le p50
    # dépasse nettement le p50 UNC — son échantillon est contaminé
    # (un TTB/TB ne vaut pas 3× une pièce neuve).
    unc = next((q for q in quotes if q.condition == "UNC"), None)
    if unc is not None and unc.p50:
        ceiling = MAX_TIER_RATIO_VS_UNC * unc.p50
        quotes = [
            q for q in quotes
            if q.condition == "UNC" or q.p50 is None or q.p50 <= ceiling
        ]
    return quotes
