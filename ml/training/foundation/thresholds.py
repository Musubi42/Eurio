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


class DinoAbstentionThresholds(TypedDict):
    """Seuils d'abstention des SUGGESTIONS (spread du top-K global)."""

    spread_uncertain_max: float
    spread_confident_min: float


# Abstention des suggestions (P5 du chantier dino-suggestions) — calibrée
# sur l'audit Phase 0 (478 crops décidés en review, scripts/
# audit_dino_suggestions.py, 2026-06-11) :
#   - la SIM top1 ne sépare RIEN (vits14 : médiane hors-scope 0.834 ≈
#     médiane des top1 corrects 0.836) → aucun seuil de sim exploitable ;
#   - le SPREAD global (top1 − top2) sépare bien.
# Re-validée après la bascule suggestions → vitl14 (même jour) : la
# séparation s'élargit encore — spread médian 0.097 (correct) vs 0.011
# (faux) ; sous 0.02 on ne perd que 8 % des top1 corrects, et au-dessus de
# 0.05 la précision top1 est de 97.8 %. Les mêmes seuils servent les deux
# encodeurs (le consensus vits14 ne consomme PAS ces seuils d'abstention).
# spread < 0.02  → « incertain » (probablement hors banque / design ambigu)
# spread ≥ 0.05 → « net » ; entre les deux : « faible marge ».
DINO_ABSTENTION_THRESHOLDS: Final[DinoAbstentionThresholds] = {
    "spread_uncertain_max": 0.02,
    "spread_confident_min": 0.05,
}
