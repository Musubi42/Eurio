"""Cible d'enrichissement training par classe — source de vérité UNIQUE.

Avant : la cible était codée en dur `×10` à trois endroits (affichage cockpit
``api/lab_routes.py``, bake réel ``training/iteration_augmentations.py``, fallback
front), avec des « seed » qui ne comptaient même pas les mêmes sources. Résultat :
des compteurs toujours ronds (10/100, 220/100) qui ne reflétaient pas le travail.

Doctrine PO (2026-06-05) : on veut **au moins 100** images par classe, atteintes
par un facteur d'augmentation **entier, dynamique, le même pour toutes les images
réelles de la classe** :

    facteur = ceil(100 / seed)          # entier, appliqué uniformément
    projeté = facteur × seed            # ≥ 100 dès seed ≥ 1, jamais un rond imposé

Exemples : 15 réels → ×7 → 105 ; 21 réels → ×5 → 105 ; 3 réels → ×34 → 102.

``seed`` = nombre de sources RÉELLES distinctes de la classe = crops eBay validés
(``image_assets.training_eligible=1``) + avers Numista (FS) + réfs canoniques
officielles (BCE / EUR-Lex JO). En-dessous de ``MIN_REAL`` sources eBay réelles, la
classe est flaggée « trop pauvre » : l'augmentation seule gonfle artificiellement
(100 variantes depuis 3 photos ≠ 100 vraies vues) → aller chercher plus d'eBay.

L'affichage (``lab_routes``) et le bake (``iteration_augmentations``) DOIVENT
importer ce module pour ne jamais diverger.
"""

from __future__ import annotations

import math

# Plancher cible : au moins 100 images de training par classe.
TRAINING_TARGET = 100

# Plancher de sources eBay RÉELLES en-dessous duquel la classe est flaggée pauvre.
MIN_REAL = 10

# Réfs canoniques officielles utilisables comme sources de training (avers).
# numista_api est exclu : pas de local_path — l'avers Numista est lu sur le FS
# (``datasets/<numista_id>/obverse.*``). Source unique pour le bake ET l'affichage.
CANONICAL_REF_SOURCES = ("bce_official", "eurlex_jo")


def aug_factor(seed: int) -> int:
    """Facteur d'augmentation entier pour atteindre ≥ ``TRAINING_TARGET``.

    ``ceil(100 / seed)`` borné à ≥ 1 (avec beaucoup de sources réelles, on
    n'augmente pas : ×1 = on garde les réels tels quels, déjà ≥ 100).
    """
    return max(1, math.ceil(TRAINING_TARGET / max(int(seed), 1)))


def projection(seed: int) -> tuple[int, int]:
    """``(facteur, projeté)`` pour un nombre de sources réelles ``seed``.

    ``projeté = facteur × seed`` : ≥ 100 dès ``seed ≥ 1``, et 0 si ``seed == 0``
    (aucune source → impossible d'atteindre la cible, à flagger en amont).
    """
    factor = aug_factor(seed)
    return factor, factor * max(int(seed), 0)
