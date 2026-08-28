"""L'interface des bras, et la séparation juge / méthode rendue structurelle.

Un bras = `bras(raw_bgr, contexte) -> list[Candidat]`, enregistré ici. Le banc
seul mesure ; aucun bras ne duplique la mesure. C'est la seule chose que
`crop-recovery` avait bien faite, et elle a tenu.

**RE-2 n'est pas une consigne, c'est une frontière de type.** Un bras candidat
reçoit un `ContexteCandidat` qui **ne porte pas l'or** — il ne peut pas le lire,
même en le voulant. Seules les *bornes* (`gold_replay`, `human_2nd_pass`)
reçoivent un `ContexteBorne`, et elles ne sont pas des candidats : elles sont
là pour rendre le tableau lisible.
"""

from __future__ import annotations

import ast
import inspect
from dataclasses import dataclass, field
from typing import Callable

import numpy as np

from bench.gold_crop.geometry import Ellipse


@dataclass
class Candidat:
    cx: float
    cy: float
    r: float
    source: str                       # traçable dans le JSON de run
    debug: dict = field(default_factory=dict)


@dataclass
class ContexteCandidat:
    """Ce qu'un candidat a le droit de savoir. Pas d'or, pas de verdict humain."""

    largeur: int
    hauteur: int
    hint: dict                        # le crop actuel : {cx, cy, r}


@dataclass
class ContexteBorne(ContexteCandidat):
    """Réservé aux bornes. En porter l'or est précisément ce qui les disqualifie
    comme candidats — et c'est écrit dans le type."""

    gold: Ellipse | None = None
    gold_2e_passe: Ellipse | None = None


Bras = Callable[[np.ndarray | None, ContexteCandidat], "list[Candidat]"]

_REGISTRE: dict[str, tuple[Bras, bool]] = {}


def enregistrer(nom: str, *, borne: bool = False):
    """`borne=True` : ce bras n'est pas un candidat, il fixe une frontière."""
    def deco(fn: Bras) -> Bras:
        if nom in _REGISTRE:
            raise ValueError(f"bras déjà enregistré : {nom}")
        _REGISTRE[nom] = (fn, borne)
        return fn
    return deco


def get_bras(nom: str) -> tuple[Bras, bool]:
    if nom not in _REGISTRE:
        raise KeyError(f"bras inconnu : {nom} (connus : {sorted(_REGISTRE)})")
    return _REGISTRE[nom]


def noms(*, bornes: bool | None = None) -> list[str]:
    return sorted(n for n, (_, b) in _REGISTRE.items()
                  if bornes is None or b == bornes)


_INTERDITS = ("bench.gold_crop.judge", "gold.json", "gold.pass2.json")


def controler_re2(nom: str) -> list[str]:
    """Un bras candidat importe-t-il le juge, ou lit-il l'or ?

    Contrôle syntaxique du module qui définit le bras. Ce n'est pas une preuve —
    un `__import__` dynamique passerait — mais c'est le geste qui manquait aux
    sept chantiers : *personne n'avait vérifié*. Rend la liste des infractions.
    """
    fn, borne = get_bras(nom)
    if borne:
        return []
    try:
        source = inspect.getsource(inspect.getmodule(fn))
    except (OSError, TypeError):
        return ["source illisible"]
    fautes = []
    arbre = ast.parse(source)
    for n in ast.walk(arbre):
        if isinstance(n, ast.ImportFrom) and n.module and "gold_crop.judge" in n.module:
            fautes.append(f"importe le juge : {n.module}")
        elif isinstance(n, ast.Import):
            for a in n.names:
                if "gold_crop.judge" in a.name:
                    fautes.append(f"importe le juge : {a.name}")
        elif isinstance(n, ast.Constant) and isinstance(n.value, str):
            if n.value in ("gold.json", "gold.pass2.json"):
                fautes.append(f"cite l'or : {n.value!r}")
    return fautes
