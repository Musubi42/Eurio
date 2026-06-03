"""Expand a lab cohort into eBay discovery groups.

eBay discovery is group-based — one Browse search per group, then listings are
attributed to coins of that group. Two group kinds :

- **commemorative** — ``(dénomination, pays, année)`` ; source ``v_ebay_freshness_groups``
  (``is_commemorative=1``). Attribution par theme-match.
- **standard** — ``(dénomination, pays)`` (PAS l'année) ; source
  ``v_ebay_standard_groups`` (``is_commemorative=0``). Une recherche large couvre
  toutes les ères de design du pays, attribuées en aval par appartenance de plage
  d'années (``sources/ebay/standards.py``).

To scope a scrape to a lab cohort, we map each cohort eurio_id to its group
(commémo par ``(denom,pays,année)``, standard par ``(denom,pays)``) and keep the
ones present in la vue correspondante.

Coins sans groupe (eu-issues, variantes ``canonical_eurio_id`` non-NULL, ou
commémos hors-vue) sont reportés ``non_scrapable`` plutôt que silencieusement
droppés : ils s'entraînent sur Numista uniquement.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class EbayGroup:
    """Un groupe de découverte eBay résolu + son cardinal, prêt à devenir une
    ``DiscoveryGroup``.

    ``year`` est ``None`` pour les standards (le design couvre toutes les
    années). ``n_coins`` = cardinal du groupe cherché par la recherche large
    (commémos-sœurs pour un groupe commémo, ères de design pour un standard) —
    sert au préflight quota.
    """

    denomination: float
    country: str
    year: int | None
    n_coins: int
    kind: str  # "commemorative" | "standard"


def cohort_ebay_groups(store, cohort_id: str) -> tuple[list[EbayGroup], list[str]]:
    """Map a cohort's coins to eBay discovery groups (commémo + standard).

    Returns ``(groups, non_scrapable_eurio_ids)``:
    - ``groups`` — ``EbayGroup`` dédupliqués contenant ≥1 coin de la cohort.
    - ``non_scrapable_eurio_ids`` — coins sans groupe dans aucune vue (eu,
      variantes, commémos hors-vue).

    Raises ``ValueError`` si la cohort n'existe pas ou est vide.
    """
    cohort = store.get_cohort(cohort_id)
    if cohort is None:
        raise ValueError(f"Cohort {cohort_id!r} introuvable")
    eids = list(cohort.eurio_ids)
    if not eids:
        raise ValueError(f"Cohort {cohort_id!r} est vide")

    conn = store._connection()  # noqa: SLF001
    placeholders = ",".join("?" * len(eids))
    coins: dict[str, tuple[float, str, int, int, str | None]] = {
        r["eurio_id"]: (
            r["face_value"], r["country"], r["year"],
            r["is_commemorative"], r["canonical_eurio_id"],
        )
        for r in conn.execute(
            f"SELECT eurio_id, face_value, country, year, is_commemorative, "
            f"canonical_eurio_id FROM coins WHERE eurio_id IN ({placeholders})",
            eids,
        )
    }
    comm_view: dict[tuple[float, str, int], int] = {
        (r["denomination"], r["country"], r["year"]): r["n_coins"]
        for r in conn.execute(
            "SELECT denomination, country, year, n_coins FROM v_ebay_freshness_groups"
        )
    }
    std_view: dict[tuple[float, str], int] = {
        (r["denomination"], r["country"]): r["n_eras"]
        for r in conn.execute(
            "SELECT denomination, country, n_eras FROM v_ebay_standard_groups"
        )
    }

    groups: list[EbayGroup] = []
    seen: set[tuple[str, tuple]] = set()
    non_scrapable: list[str] = []
    for eid in eids:
        coin = coins.get(eid)
        if coin is None:
            non_scrapable.append(eid)
            continue
        fv, country, year, is_comm, canonical = coin
        # Variantes (pattern/mule/coloured…) : on scrape la canonique, pas la
        # variante — son eurio_id n'a pas de groupe propre.
        if canonical is not None:
            non_scrapable.append(eid)
            continue
        if is_comm:
            key = (fv, country, year)
            if key in comm_view:
                if ("commemorative", key) not in seen:
                    seen.add(("commemorative", key))
                    groups.append(
                        EbayGroup(fv, country, year, comm_view[key], "commemorative")
                    )
                continue
        else:
            skey = (fv, country)
            if skey in std_view:
                if ("standard", skey) not in seen:
                    seen.add(("standard", skey))
                    groups.append(
                        EbayGroup(fv, country, None, std_view[skey], "standard")
                    )
                continue
        non_scrapable.append(eid)
    return groups, non_scrapable
