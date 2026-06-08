"""Auto-validation par ensemble/consensus (redesign).

Domaine unique qui possède la décision d'auto-validation : experts (avis
normalisés), règle de consensus (C3), verdict→lane. C1 introduit l'interface
``Expert``/``Signal`` + les experts text & dino ; C2 ajoute crop_quality. Voir
docs/work-in-progress/autovalidation-redesign.md.
"""

from .experts import (
    EXPERTS,
    AssetContext,
    CropQuality,
    CropQualityExpert,
    DinoExpert,
    Expert,
    Signal,
    TextExpert,
    collect_signals,
    crop_signal,
    dino_signal,
    fetch_crop_quality,
    text_signal,
)

__all__ = [
    "EXPERTS",
    "AssetContext",
    "CropQuality",
    "CropQualityExpert",
    "DinoExpert",
    "Expert",
    "Signal",
    "TextExpert",
    "collect_signals",
    "crop_signal",
    "dino_signal",
    "fetch_crop_quality",
    "text_signal",
]
