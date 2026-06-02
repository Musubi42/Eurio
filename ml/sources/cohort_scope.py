"""Expand a lab cohort into eBay discovery groups.

eBay discovery is group-based — one Browse search per ``(denomination, country,
year)`` group, then listings are theme-matched to the coins of that group. To
scope a scrape to a lab cohort, we map the cohort's eurio_ids to their groups
and keep the ones that exist in ``v_ebay_freshness_groups`` (the commemorative,
non-eu, canonical-only universe eBay enriches).

Coins whose group isn't in that view — standards (``is_commemorative = 0``),
eu-issues, variants — are reported as ``non_scrapable`` rather than silently
dropped: they get trained on Numista-only sources, not eBay.
"""
from __future__ import annotations

# (denomination, country, year, n_coins) — same shape as cli._resolve_ebay_groups.
EbayGroup = tuple[float, str, int, int]


def cohort_ebay_groups(store, cohort_id: str) -> tuple[list[EbayGroup], list[str]]:
    """Map a cohort's coins to eBay discovery groups.

    Returns ``(groups, non_scrapable_eurio_ids)``:
    - ``groups`` — deduped ``(denom, country, year, n_coins)`` rows from
      ``v_ebay_freshness_groups`` that contain ≥1 cohort coin. ``n_coins`` is the
      group's full member count (all coins searched, not just cohort members).
    - ``non_scrapable_eurio_ids`` — cohort coins with no group in the view.

    Raises ``ValueError`` if the cohort doesn't exist or is empty.
    """
    cohort = store.get_cohort(cohort_id)
    if cohort is None:
        raise ValueError(f"Cohort {cohort_id!r} introuvable")
    eids = list(cohort.eurio_ids)
    if not eids:
        raise ValueError(f"Cohort {cohort_id!r} est vide")

    conn = store._connection()  # noqa: SLF001
    placeholders = ",".join("?" * len(eids))
    coin_group: dict[str, tuple[float, str, int]] = {
        r["eurio_id"]: (r["face_value"], r["country"], r["year"])
        for r in conn.execute(
            f"SELECT eurio_id, face_value, country, year "
            f"FROM coins WHERE eurio_id IN ({placeholders})",
            eids,
        )
    }
    view: dict[tuple[float, str, int], int] = {
        (r["denomination"], r["country"], r["year"]): r["n_coins"]
        for r in conn.execute(
            "SELECT denomination, country, year, n_coins FROM v_ebay_freshness_groups"
        )
    }

    groups: list[EbayGroup] = []
    seen: set[tuple[float, str, int]] = set()
    non_scrapable: list[str] = []
    for eid in eids:
        g = coin_group.get(eid)
        if g is None or g not in view:
            non_scrapable.append(eid)
            continue
        if g not in seen:
            seen.add(g)
            groups.append((g[0], g[1], g[2], view[g]))
    return groups, non_scrapable
