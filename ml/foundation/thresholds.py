"""Seuils de convergence pour l'auto-validation V1.

Source de vérité unique pour les seuils consommés à la fois par le front
(``DinoVerdict.vue`` / ``AutoValidateVerdict.vue``) et — à terme — par
l'étape pipeline d'auto-accept (chunk 8 de
``docs/sources-refacto/auto-validation/vision.md``).

V1 = display-only. Aucun code ML ne décide encore sur la base de ces
seuils ; ils servent uniquement à colorier la review queue pour que
Raphaël voie où la convergence Dino+Texte est suffisante (= candidats
auto-accept potentiels) versus où elle ne l'est pas (= vrais cas de
review humaine).

Valeurs provisoires, à calibrer après collecte d'au moins 200 reviews
annotées (cf. vision §P5). Bouger ici suffit — le front les lit via le
champ ``verdict_thresholds`` de ``GET /review-queue/.../dino-suggestions``.
"""

from __future__ import annotations

from typing import Final, TypedDict


class DinoVerdictThresholds(TypedDict):
    """Seuils Dino exposés au front pour calcul du verdict par critère."""

    top1_country_sim_min: float
    country_spread_min: float


# Dino sims sont tassées sur euros (memory ``feedback_dino_thresholds``) :
# top1 obverse-vs-obverse vit en p25=0.81 / p75=0.88 sur la confusion map,
# encore plus comprimé sur crops scrapés (p10..p90 = 0.56..0.83). Le seuil
# 0.55 retient « il y a au moins une ressemblance défendable » sans
# prétendre départager des designs proches.
#
# Le spread (top1 − top2 en band country-restricted) est plus discriminant
# que la sim absolue : 0.05 = δ_low de la vision (zone tiède en dessous).
DINO_VERDICT_THRESHOLDS: Final[DinoVerdictThresholds] = {
    "top1_country_sim_min": 0.55,
    "country_spread_min": 0.05,
}
