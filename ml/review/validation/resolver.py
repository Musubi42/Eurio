"""Resolver d'attribution unifié commémo + standard (C4 du redesign).

Un listing (titre + coordonnées catalogue) → une attribution à une pièce, **quel
que soit le type** : commémo (theme-match positif) ou standard (appartenance de
plage d'années). Avant C4, l'adapter eBay portait DEUX chemins divergents
(``_attribute_commemo_row`` / ``_attribute_standard_row``) avec deux types de
résultat (``GroupMatch`` / ``StandardMatch``) et une branche de rescue qui
parsait une chaîne de raison. Ici : **une entrée, un type de résultat**
(``ListingAttribution``), interface **source-agnostique** (pas de ``DiscoveryGroup``
ni de contexte eBay — juste ``denomination/country/year/kind``).

Les *stratégies* de matching (``match_listing_to_group`` theme-match,
``attribute_standard_listing`` plage d'années) restent leurs implémentations
actuelles sous ``sources/ebay`` — importées **paresseusement** (au call, pas au
load) : c'est le motif déjà en place dans ce code (cf. ``_group_contradiction``,
``theme_match_state``), et ça évite le cycle d'import
``sources.ebay.__init__`` → adapter → resolver. Une source non-eBay appelle
``resolve_listing`` avec ses propres coordonnées ; aucune dépendance à eBay dans
le *contrat*.

Cf. docs/work-in-progress/autovalidation-redesign.md §3.2.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass


@dataclass(frozen=True)
class ListingAttribution:
    """Verdict d'attribution d'un listing, indépendant de la source.

    - ``verdict`` : ``single`` | ``lot`` | ``ambiguous`` | ``rescued`` |
      ``commemo`` | ``no_match`` | ``no_eras``.
    - ``target_eurio_id`` : prior résolu (None si ambigu / discard).
    - ``candidates`` : eurio_ids portés en review (vide → aucun).
    - ``keep`` : True → le listing est ingéré (→ images) ; False → discard pur.
    - ``reason`` : motif logué dans ``discarded_listings`` si non-None. Posé
      pour les discards ET pour le **rescue** (``rescued_to:<eid>`` — gardé ET
      audité). None pour un keep ordinaire (single/lot/ambiguous).
    """

    verdict: str
    target_eurio_id: str | None
    candidates: tuple[str, ...]
    keep: bool
    reason: str | None = None


def resolve_listing(
    title: str,
    *,
    kind: str,                       # 'commemorative' | 'standard'
    denomination: float,
    country: str,
    year: int | None = None,
    conn: sqlite3.Connection,
    coin_ids: list[str] | None = None,
) -> ListingAttribution:
    """Attribue un listing à une pièce du catalogue (commémo ou standard).

    ``coin_ids`` (commémo) : les sœurs du groupe, pré-chargées par l'appelant
    pour éviter une requête par listing ; rechargées via ``load_group_coins``
    (denom, country, year) si None. Ignoré pour ``kind='standard'`` (les ères
    sont chargées par millésime dans la stratégie standard)."""
    if kind == "standard":
        return _resolve_standard(title, denomination, country, conn)
    if coin_ids is None:
        from sources.ebay.queries import load_group_coins

        if year is None:
            raise ValueError("resolve_listing(commemorative) needs coin_ids or year")
        coin_ids = [c.eurio_id for c in load_group_coins(conn, denomination, country, year)]
    return _resolve_commemo(title, list(coin_ids), conn)


def _resolve_commemo(
    title: str, coin_ids: list[str], conn: sqlite3.Connection
) -> ListingAttribution:
    """Theme-match vs les commémos-sœurs du groupe (cf. ``match_listing_to_group``)."""
    from sources.ebay.queries import match_listing_to_group

    gm = match_listing_to_group(title, coin_ids, conn=conn)
    if gm.verdict == "no_match":
        axe = gm.contradictions[0] if gm.contradictions else "unknown"
        return ListingAttribution(
            "no_match", None, (), keep=False, reason=f"group_contradict_{axe}"
        )
    # single → cible résolue, pas de candidates ; lot → le sous-ensemble matché ;
    # ambiguous → toutes les sœurs portées en review (parité _attribute_commemo_row).
    if gm.verdict == "ambiguous":
        candidates: tuple[str, ...] = tuple(coin_ids)
    elif gm.verdict == "lot":
        candidates = tuple(gm.matched)
    else:  # single
        candidates = ()
    return ListingAttribution(
        gm.verdict, gm.target_eurio_id, candidates, keep=True, reason=None
    )


def _resolve_standard(
    title: str, denomination: float, country: str, conn: sqlite3.Connection
) -> ListingAttribution:
    """Appartenance de plage vs les ères standard du pays (cf.
    ``attribute_standard_listing``). Le ``commemo`` détecté par theme-hit dans un
    run standard est **rescué** (gardé + audité ``rescued_to:``), pas jeté."""
    from sources.ebay.standards import (
        COMMEMO_IN_STANDARD_PREFIX,
        attribute_standard_listing,
    )

    sm = attribute_standard_listing(title, denomination, country, conn=conn)

    # Commémo détectée par theme-hit dans un run standard → rescue (gardée avec
    # son eurio_id, tracée en audit). Remplace le parsing de chaîne de l'adapter.
    if sm.verdict == "commemo" and sm.reason.startswith(COMMEMO_IN_STANDARD_PREFIX):
        eid = sm.reason.split(":", 1)[1]
        return ListingAttribution(
            "rescued", eid, (), keep=True, reason=f"rescued_to:{eid}"
        )

    if sm.verdict in ("commemo", "no_match", "no_eras"):
        return ListingAttribution(
            sm.verdict, None, sm.candidates, keep=False, reason=sm.reason
        )

    # single | ambiguous : gardé, target = prior (None si ambiguous), toutes les
    # ères du pays en candidates (doctrine standards « tout en review »).
    return ListingAttribution(
        sm.verdict, sm.target_eurio_id, sm.candidates, keep=True, reason=None
    )
