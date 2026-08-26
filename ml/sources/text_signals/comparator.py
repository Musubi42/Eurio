"""Comparateur ``vs_target`` (chunk 6 auto-validation).

Prend un :class:`ListingTextSignals` (sortie pure de l'extracteur) + une
:class:`TargetIdentity` (le prior porté par ``source_images.target_eurio_id``)
et retourne un verdict typé :

- ``convergent`` : tous les axes signalés pointent target.
- ``partial``   : certains axes convergent, le reste muet.
- ``absent``    : rien d'exploitable côté texte.
- ``contradict``: ≥ 1 axe ferme contredit target.

Pas de décision pipeline ici (chunk 6.c). Pas de DB I/O dans le compareur
lui-même — la fonction est pure et testable. ``load_target_identity`` est
le helper DB qui lit la table ``coins`` du eurio.db.

Normalisation des pays : l'extracteur produit les ISO2 en majuscules
(``"AD"``, ``"FR"``) alors que la table ``coins`` les stocke également en
majuscules — par sécurité on normalise les deux côtés en minuscules au
moment de la comparaison (le slug ``eurio_id`` est lui en minuscules).
Aucune migration nécessaire.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from typing import Literal

from .extractor import ListingTextSignals

VsTargetVerdict = Literal["convergent", "partial", "absent", "contradict"]


@dataclass(frozen=True)
class TargetIdentity:
    """Identité minimale du target à confronter aux signaux texte.

    Issu de la table ``coins``. ``country`` est normalisé en lowercase
    pour s'aligner avec le slug ``eurio_id`` et la comparaison.
    """

    eurio_id: str
    country: str          # ISO2 lowercase ('ad', 'fr', ...)
    year: int
    face_value: float
    theme: str | None = None


@dataclass(frozen=True)
class GroupIdentity:
    """Identité partagée par toutes les sœurs d'un groupe de découverte.

    Un groupe eBay = ``(pays, année, dénomination)`` ; les N commémos-
    sœurs partagent ces trois axes. Sert au garde-fou de contradiction
    *avant* l'attribution à une sœur précise (``compare_to_group``).
    """

    country: str          # ISO2 lowercase ('be', 'fr', ...)
    year: int
    face_value: float


@dataclass(frozen=True)
class VsTargetComparison:
    """Résultat typé de :func:`compare_to_target`.

    - ``contradictions`` / ``convergences`` : axes en désaccord / accord,
      parmi ``country``, ``year``, ``denomination``. Ordre stable
      (country, year, denomination) pour tests déterministes.
    """

    verdict: VsTargetVerdict
    contradictions: tuple[str, ...] = ()
    convergences: tuple[str, ...] = ()
    target_eurio_id: str = ""
    target_country: str = ""
    target_year: int = 0
    target_face_value: float = 0.0


_AXIS_ORDER = ("country", "year", "denomination")


def _country_axis(
    signals_countries: frozenset[str],
    target_country: str,
) -> Literal["convergent", "contradict", "absent"]:
    if not signals_countries:
        return "absent"
    sig_lower = {c.lower() for c in signals_countries}
    if target_country.lower() in sig_lower:
        # Multi-country avec target présent = convergent (lot
        # transfrontalier, traité comme tel via signals.is_lot).
        return "convergent"
    return "contradict"


def _year_axis(
    signals_years: frozenset[int],
    target_year: int,
    *,
    years_are_range: bool = False,
) -> Literal["convergent", "contradict", "absent"]:
    if not signals_years:
        return "absent"
    # Une PLAGE n'affirme rien sur la pièce photographiée — « Italien 2 Euro
    # 2004 bis 2022 » veut dire « choisis ton millésime ». La traiter comme
    # une affirmation produisait un `contradict` sur un titre honnête, donc
    # un `divergent`, donc de la review humaine pour rien. L'axe est `absent`.
    # ⚠️ Ce n'est PAS couvert par la plage englobante ci-dessous : celle-ci
    # ne rattrape que les cibles STRICTEMENT à l'intérieur, et laissait donc
    # contredire toute cible tombant sur une borne ou au-delà.
    if years_are_range:
        return "absent"
    if target_year in signals_years:
        return "convergent"
    # Plage englobante : un titre type "2005-2025" ne contredit pas un
    # target=2014 (l'année cible est dans la plage). Convergent faible.
    y_min, y_max = min(signals_years), max(signals_years)
    if y_min < target_year < y_max:
        return "convergent"
    return "contradict"


def _denomination_axis(
    signals_denoms: frozenset[float],
    target_face_value: float,
) -> Literal["convergent", "contradict", "absent"]:
    if not signals_denoms:
        return "absent"
    # Tolérance flottante : les valeurs viennent toutes de
    # VALID_FACE_VALUES (extractor) ou de coins.face_value (REAL SQLite).
    if any(abs(d - target_face_value) < 1e-6 for d in signals_denoms):
        return "convergent"
    return "contradict"


def compare_to_target(
    signals: ListingTextSignals,
    target: TargetIdentity,
) -> VsTargetComparison:
    """Confronte les signaux texte à l'identité du target.

    Verdict global (1-axe contradict suffit, cf. doc chunk 6 §"Verdict
    global") :

    - ≥ 1 axe contradict           → ``contradict``
    - 0 signal présent             → ``absent``
    - tous axes présents convergent → ``convergent``
    - sinon                         → ``partial``
    """
    axis_results = {
        "country": _country_axis(signals.countries, target.country),
        "year": _year_axis(
            signals.years, target.year,
            years_are_range=signals.years_are_range,
        ),
        "denomination": _denomination_axis(
            signals.denominations, target.face_value
        ),
    }

    contradictions = tuple(
        a for a in _AXIS_ORDER if axis_results[a] == "contradict"
    )
    convergences = tuple(
        a for a in _AXIS_ORDER if axis_results[a] == "convergent"
    )
    n_present = sum(
        1 for a in _AXIS_ORDER if axis_results[a] != "absent"
    )

    # ``convergent`` exige les 3 axes confirmés (cf. cas #1 et #3 du
    # kickoff chunk 6 : "country absent + year/denom OK" est explicitement
    # ``partial``, pas ``convergent``). Discrimination importante pour
    # chunk 8 : seul ``convergent`` 3/3 + ``is_lot=False`` est candidat
    # à l'auto-accept.
    if contradictions:
        verdict: VsTargetVerdict = "contradict"
    elif n_present == 0:
        verdict = "absent"
    elif len(convergences) == len(_AXIS_ORDER):
        verdict = "convergent"
    else:
        verdict = "partial"

    return VsTargetComparison(
        verdict=verdict,
        contradictions=contradictions,
        convergences=convergences,
        target_eurio_id=target.eurio_id,
        target_country=target.country,
        target_year=target.year,
        target_face_value=target.face_value,
    )


def compare_to_group(
    signals: ListingTextSignals,
    group: GroupIdentity,
) -> tuple[str, ...]:
    """Axes où le titre **contredit fermement** le groupe de découverte.

    Renvoie le tuple des axes (``country`` / ``year`` / ``denomination``)
    en contradiction franche — vide si aucun. Réutilise les trois axes de
    :func:`compare_to_target` : les sœurs partageant pays/année/dénom, un
    axe qui contredit le groupe les contredit toutes.

    À la différence de ``compare_to_target`` on ne mesure QUE la
    contradiction : pas de ``convergent`` / ``partial`` au niveau groupe
    (on ne sait pas encore quelle sœur — c'est le rôle du theme-match).
    Sémantique « contradiction positive ≠ absence d'évidence » : un axe
    *absent* ne contredit pas (Finding 3 de la recherche entity-matching).
    """
    axis_results = {
        "country": _country_axis(signals.countries, group.country),
        "year": _year_axis(signals.years, group.year),
        "denomination": _denomination_axis(
            signals.denominations, group.face_value
        ),
    }
    return tuple(
        a for a in _AXIS_ORDER if axis_results[a] == "contradict"
    )


def load_target_identity(
    conn: sqlite3.Connection,
    eurio_id: str,
) -> TargetIdentity | None:
    """Charge l'identité du target depuis ``coins``. None si inconnu.

    Country est normalisé lowercase pour matcher le slug ``eurio_id`` et
    le pipeline de comparaison.
    """
    row = conn.execute(
        "SELECT eurio_id, country, year, face_value, theme "
        "  FROM coins WHERE eurio_id = ?",
        (eurio_id,),
    ).fetchone()
    if row is None:
        return None
    return TargetIdentity(
        eurio_id=row["eurio_id"],
        country=(row["country"] or "").lower(),
        year=int(row["year"]),
        face_value=float(row["face_value"]),
        theme=row["theme"],
    )
