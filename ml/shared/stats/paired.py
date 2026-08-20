"""Comparaison appariée de deux systèmes sur le MÊME jeu — McNemar exact.

Le corps de ``mcnemar_exact`` vient de ``scripts/replay_corpus.py`` (§8bis de
``docs/work-in-progress/scan-quality/corpus-spec.md``), où il a été écrit pour
le replay du corpus de scan. Il est **déplacé**, pas réécrit : le banc
multi-encodeurs a exactement le même besoin, et deux copies d'un test
statistique divergent toujours.

Contrat d'import : stdlib uniquement.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Mapping


def mcnemar_exact(b: int, c: int) -> float:
    """Test de McNemar exact (binomial bilatéral) sur les paires discordantes.

    b = baseline correcte & candidat incorrect ; c = l'inverse. À petit n le
    χ² asymptotique ment — on somme la binomiale exacte (p=0.5).
    """
    n = b + c
    if n == 0:
        return 1.0
    k = min(b, c)
    tail = sum(math.comb(n, i) for i in range(0, k + 1)) / (2**n)
    return min(1.0, 2.0 * tail)


@dataclass(frozen=True)
class PairedResult:
    """La table de contingence 2×2 et ce qui s'en déduit.

    ``n_paired`` n'est pas décoratif : c'est la taille de l'INTERSECTION des
    clés. Deux runs qui n'ont pas tourné sur le même sous-ensemble donneraient
    sinon une comparaison biaisée sans que rien ne le signale.

    **Intersection vide → tout ce qui se déduit d'une comparaison vaut None**
    (``acc_a``, ``acc_b``, ``delta_acc``, ``p_value``). Le traitement précédent
    rendait ``delta_acc=0.0, p_value=1.0`` : « aucune différence
    significative » entre deux encodeurs qui n'ont pas partagé un seul crop.
    Ce ``1.0`` partait tel quel dans ``encoder_bench_runs.mcnemar_p``, où plus
    rien ne le distinguait d'un vrai test non concluant. Un test qui n'a pas eu
    lieu n'a pas de p-valeur ; la colonne est nullable, on s'en sert.
    ``comparable`` donne le statut d'un coup d'œil.
    """

    n_paired: int
    both_correct: int
    a_only: int  # A correct, B faux
    b_only: int  # B correct, A faux
    neither: int
    acc_a: float | None
    acc_b: float | None
    delta_acc: float | None  # acc_b - acc_a
    p_value: float | None

    @property
    def comparable(self) -> bool:
        """Faux quand l'intersection est vide : rien n'a été comparé."""
        return self.n_paired > 0

    def to_dict(self) -> dict:
        return dict(self.__dict__, comparable=self.comparable)


def paired_compare(a: Mapping[str, bool], b: Mapping[str, bool]) -> PairedResult:
    """Apparie ``a`` et ``b`` par clé (asset_id) et rend la contingence.

    N'utilise QUE l'intersection des clés. Les accuracies sont calculées sur
    cette intersection, pas sur les jeux complets : comparer 1900 crops d'un
    côté à 1200 de l'autre ne serait pas une comparaison.

    Intersection vide : ``acc_a/acc_b/delta_acc/p_value`` valent ``None`` et
    ``comparable`` est faux — cf. la docstring de :class:`PairedResult`.
    """
    common = sorted(set(a) & set(b))
    both = a_only = b_only = neither = 0
    for key in common:
        ok_a, ok_b = bool(a[key]), bool(b[key])
        if ok_a and ok_b:
            both += 1
        elif ok_a:
            a_only += 1
        elif ok_b:
            b_only += 1
        else:
            neither += 1
    n = len(common)
    if not n:
        return PairedResult(
            n_paired=0,
            both_correct=0,
            a_only=0,
            b_only=0,
            neither=0,
            acc_a=None,
            acc_b=None,
            delta_acc=None,
            p_value=None,
        )
    acc_a = (both + a_only) / n
    acc_b = (both + b_only) / n
    return PairedResult(
        n_paired=n,
        both_correct=both,
        a_only=a_only,
        b_only=b_only,
        neither=neither,
        acc_a=acc_a,
        acc_b=acc_b,
        delta_acc=acc_b - acc_a,
        p_value=mcnemar_exact(a_only, b_only),
    )
