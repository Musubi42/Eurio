"""Listing text-signal extractor.

Pure module : depuis un titre (et optionnellement quelques aspects eBay
déjà parsés), produit un :class:`ListingTextSignals` qui résume ce que
le texte du listing dit explicitement (pays, année, dénomination, lot,
markers de rejet, tokens de thème).

Aucune comparaison vs target ici (chunk 6), aucune persistance
(chunk 5), aucune intégration pipeline (chunk 5). Le module est
intentionnellement pur pour qu'il puisse être testé sur un grand
échantillon de titres réels et itéré rapidement.

Cf. docs/sources-refacto/auto-validation/vision.md — chunk 4.
"""

from .comparator import (
    TargetIdentity,
    VsTargetComparison,
    VsTargetVerdict,
    compare_to_target,
    load_target_identity,
)
from .extractor import (
    ConditionTier,
    Coverage,
    ListingKind,
    ListingTextSignals,
    extract_listing_text_signals,
)

__all__ = [
    "ConditionTier",
    "Coverage",
    "ListingKind",
    "ListingTextSignals",
    "TargetIdentity",
    "VsTargetComparison",
    "VsTargetVerdict",
    "compare_to_target",
    "extract_listing_text_signals",
    "load_target_identity",
]
