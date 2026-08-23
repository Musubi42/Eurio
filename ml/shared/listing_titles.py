"""Lecture des titres de listing — stdlib-only, lisible par l'image lean du VPS.

POURQUOI CE MODULE EXISTE
-------------------------
La règle vivait dans ``review/review_queue_routes.py``, module qui fait
``import cv2`` en tête et n'est donc pas monté sur l'image lean. Or c'est
justement l'image lean qui sert la review à distance
(review-collaborative-v2, lot 6a). Même raison que ``shared/verdict_scope.py``
et ``shared/dino_threshold_defaults.py`` : la valeur est légère, seul son
voisinage était lourd.

Une SEULE définition, importée par les deux voies — dupliquer la regex
signifierait qu'un jour la bande pays serait démotée d'un côté et pas de
l'autre, sans que rien ne le signale.
"""
from __future__ import annotations

import re
from typing import Final

# Titres de lots multi-pays — le pays cible du listing n'y contraint pas le
# pays de chaque crop (cas kickoff : « 2 Euro Kursmünze 2011 — Diverse Länder
# nach Wahl », target BE, crops de toute la zone euro). Volontairement court
# et haute-précision : un faux négatif laisse l'UI actuelle, un faux positif
# démote la bande pays qui aide massivement sur les listings mono-pays
# (recall@5 90,7 % contre 71,6 % global, audit Phase 0).
# L'adjectif (divers/verschiedene/mixed…) doit être à ≤ 2 mots d'un mot
# « pays » — « verschiedene Jahre » (multi-années mono-pays) ne matche pas.
MULTI_COUNTRY_TITLE_RE: Final[re.Pattern[str]] = re.compile(
    r"(divers\w*|verschieden\w*|gemischt\w*|mixed|various|assortit?\w*"
    r"|misti|vari[oe]?s?|diff[ée]rente?s?)"
    r"\W+(?:\w+\W+){0,2}"
    r"(l[äa]nder\w*|countr\w*|pays|paesi|pa[íi]ses)"
    r"|aus\s+allen\s+l[äa]ndern|alle\s+l[äa]nder|eurol[äa]nder",
    re.IGNORECASE,
)


def is_multi_country_lot(listing_title: str | None) -> bool:
    """Vrai si le titre annonce un lot de pays MÊLÉS.

    Conséquence côté review : la bande de suggestions restreinte au pays cible
    n'a plus de sens pour ce listing, et le front la démote.
    """
    return bool(listing_title and MULTI_COUNTRY_TITLE_RE.search(listing_title))
