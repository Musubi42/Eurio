"""Interface commune des stratégies de recrop + registre.

Une stratégie = une fonction `recrop(raw_bgr, hint) -> list[Candidate]` enregistrée via
`@register("nom")`. Le harness fait le reste. C'est le SEUL code que les sessions A/B
écrivent (dans leur propre module, qu'elles enregistrent ici).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

import numpy as np


@dataclass
class Candidate:
    cx: float
    cy: float
    r: float
    source: str                       # "baseline" | "A:..." | "B:..." (traçable dans le JSON)
    debug: dict = field(default_factory=dict)


Strategy = Callable[[np.ndarray, dict], "list[Candidate]"]

_REGISTRY: dict[str, Strategy] = {}


def register(name: str) -> Callable[[Strategy], Strategy]:
    def deco(fn: Strategy) -> Strategy:
        if name in _REGISTRY:
            raise ValueError(f"stratégie déjà enregistrée: {name}")
        _REGISTRY[name] = fn
        return fn
    return deco


def get_strategy(name: str) -> Strategy:
    if name not in _REGISTRY:
        raise KeyError(f"stratégie inconnue: {name!r}. Disponibles: {list_strategies()}")
    return _REGISTRY[name]


def list_strategies() -> list[str]:
    return sorted(_REGISTRY)


@register("baseline")
def _baseline(raw_bgr: np.ndarray, hint: dict) -> list[Candidate]:
    """Le crop prod actuel = le hint tel quel. Toujours loggé (référence du lift)."""
    return [Candidate(hint["cx"], hint["cy"], hint["r_final"], "baseline")]
