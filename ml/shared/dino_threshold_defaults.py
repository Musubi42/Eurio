"""Défauts des seuils DINO — stdlib-only, lisibles par l'image lean du VPS.

POURQUOI CE MODULE EXISTE, ET PAS SEULEMENT `training/foundation/thresholds.py`
------------------------------------------------------------------------------
Les valeurs vivaient là-bas. Le fichier lui-même n'importe que `typing`, mais
il est sous `training/foundation/`, dont le `__init__.py` tire `anchors` →
numpy et torch. L'image lean du VPS ne peut donc pas l'importer, et c'est
justement elle qui sert la file de review. Même raison que
`shared/verdict_scope.py`.

CE QUE CES VALEURS SONT, ET NE SONT PAS
---------------------------------------
Ce sont des **défauts** : la valeur qui s'applique est résolue en base
(`store/dino_thresholds.py`), par couple `(banque, encodeur)`. Elles restent le
filet — l'image lean et le préflight doivent démarrer sur une base qui n'a pas
encore reçu la migration 0008.

LE POINT QUI COMPTE : UN SEUIL APPARTIENT À UN ENCODEUR
-------------------------------------------------------
Les similarités de `dinov2-vits14` et de `dinov2-vitl14` ne sont pas sur la
même échelle. Un seuil de 0,55 calibré sur la première ne veut rien dire pour
la seconde. C'est pourquoi la clé est ici un couple, et pas une simple chaîne :
servir la mauvaise valeur ne lèverait aucune erreur, elle déplacerait
silencieusement le taux de faux positifs.

Cf. docs/work-in-progress/banque-dino/DECISIONS.md §D5.
"""
from __future__ import annotations

from typing import Final

#: Les seules clés acceptées. Une clé libre deviendrait un fourre-tout.
KEYS: Final[tuple[str, ...]] = (
    "top1_country_sim_min",
    "country_spread_min",
    "spread_uncertain_max",
    "spread_confident_min",
    "spread_auto_accept_min",
)

#: Bornes de bon sens vérifiées à l'écriture. Elles n'encodent pas une
#: doctrine, seulement l'absurde : une similarité au-delà de 1 n'existe pas,
#: un spread de 0,9 n'arriverait jamais et gèlerait l'auto-acceptation.
BOUNDS: Final[dict[str, tuple[float, float]]] = {
    "top1_country_sim_min": (0.0, 1.0),
    "country_spread_min": (0.0, 0.5),
    "spread_uncertain_max": (0.0, 0.5),
    "spread_confident_min": (0.0, 0.5),
    "spread_auto_accept_min": (0.0, 0.5),
}

#: Défauts par couple (banque, encodeur).
#:
#: `2eur_commemo`/vits14 : valeurs historiques du verdict, calibrées sur les
#: sims vits14 (cf. training/foundation/thresholds.py).
#: `2eur_all`/vitl14 : seuils d'abstention des suggestions, calibrés en juin sur
#: 478 crops ; `spread_auto_accept_min` = 0,10, mesuré le 2026-08-19 sur 1 952
#: crops étiquetés (97,1 % de précision du top-1 au-dessus de ce palier).
DEFAULTS: Final[dict[tuple[str, str], dict[str, float]]] = {
    ("2eur_commemo", "dinov2-vits14"): {
        "top1_country_sim_min": 0.55,
        "country_spread_min": 0.05,
        "spread_uncertain_max": 0.02,
        "spread_confident_min": 0.05,
        "spread_auto_accept_min": 0.10,
    },
    ("2eur_all", "dinov2-vitl14"): {
        "top1_country_sim_min": 0.55,
        "country_spread_min": 0.05,
        "spread_uncertain_max": 0.02,
        "spread_confident_min": 0.05,
        "spread_auto_accept_min": 0.10,
    },
}

#: Le filet du filet : couple inconnu (un encodeur candidat en cours d'essai).
#: Servir les valeurs de vitl14 plutôt que rien, et le DIRE côté appelant —
#: elles ne valent pour lui que le temps de sa calibration.
FALLBACK: Final[dict[str, float]] = DEFAULTS[("2eur_all", "dinov2-vitl14")]


def defaults_for(anchors_kind: str, encoder_version: str) -> dict[str, float]:
    """Défauts du couple, ou ceux de la banque des suggestions à défaut."""
    return dict(DEFAULTS.get((anchors_kind, encoder_version), FALLBACK))
