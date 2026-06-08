"""Diagnostic offline — attribution des listings STANDARD (zéro appel eBay).

Rejoue ``sources.ebay.standards.attribute_standard_listing`` sur :
  1. un jeu de **cas-limites craftés** avec verdict attendu (assertions dures) ;
  2. des **titres eBay réels déjà en base** (``source_images`` /
     ``discarded_listings``) pour ES/AT — réalisme, pas d'assertion.

N'effectue AUCUN appel réseau : SQL + fonctions pures. Instancie un ``Store``
(applique ``schema.sql`` → crée la vue ``v_ebay_standard_groups``), affiche la
vue + les plages d'ères, puis la table d'attribution. Sort non-zéro si une
assertion dure échoue.

Usage : python -m scripts.standards_attribution_diag [--db state/eurio.db]
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

_ML = Path(__file__).resolve().parents[1]
if str(_ML) not in sys.path:
    sys.path.insert(0, str(_ML))

from sources.cohort_scope import cohort_ebay_groups  # noqa: E402
from sources.ebay.standards import (  # noqa: E402
    attribute_standard_listing,
    load_standard_eras,
)
from store import Store  # noqa: E402

_DB = _ML / "state" / "eurio.db"
_DENOM = 2.0

# (pays, titre, verdict_attendu, sous-chaîne_target_attendue|None)
_CASES: list[tuple[str, str, str, str | None]] = [
    # ── year-range : résolution déterministe ──────────────────────────────
    ("ES", "Spanien 2 Euro Kursmünze 2016, zirkuliert, gut erhalten", "single", "es-2015"),
    ("ES", "Spanien 2 Euro 2003 Juan Carlos bankfrisch aus Rolle", "single", "es-1999"),
    ("ES", "Spanien 2 Euro 2008 Kursmünze", "single", "es-2007"),
    ("ES", "Spanien 2 Euro 2012 Kursmünze unz.", "single", "es-2010"),
    ("AT", "2 Euro Österreich 2015 Kursmünze bankfrisch", "single", "at-2008"),
    ("AT", "2 Euro Österreich 2004 Kursmünze", "single", "at-2002"),
    ("MT", "2 Euro Malta 2015 Kursmünze", "single", "mt-2008"),
    # ── exclusion commémo (theme-match positif) ───────────────────────────
    ("ES", 'Spanien 2 Euro 2016 "Aquädukt von Segovia" bankfrisch', "commemo", None),
    # ── exclusion commémo (mot-clé négatif) : lots « alle Nationen / todos »
    ("ES", "2 Euro Gedenkmünze 2016 Bankfrisch alle Nationen", "commemo", None),
    ("ES", "2 EURO CONMEMORATIVOS 2016 - TODOS LOS PAISES", "commemo", None),
    # double négation : mot-clé standard co-présent → l'exclusion est levée
    ("ES", "Spanien 2 Euro Kursmünze KEINE Gedenkmünze 2016", "single", "es-2015"),
    # ── ambiguous : pas de millésime unique / collision même-année ────────
    ("ES", "Spanien 2 Euro Kursmünze Euromünze Jahr nach Wahl", "ambiguous", None),
    ("ES", "Spanien 2 Euro Kursmünzen 2005-2018 frei wählbar", "ambiguous", None),
    ("MT", "2 Euro Malta 2026 Kursmünze", "ambiguous", None),
    # ── contradiction franche pays / dénomination ─────────────────────────
    ("ES", "Portugal 2 Euro 2016 Kursmünze bankfrisch", "no_match", None),
    # Dénom parseable qui contredit (1 € ≠ 2 €). NB : « 5 Euro » / « Silber »
    # ne sont PAS testés ici — 5 € n'est pas une dénom de circulation
    # (non-parsée) et « Silber » est filtré en amont par accept_listing
    # (NOISE_PATTERNS), pas par l'attribution.
    ("ES", "Spanien 1 Euro 2016 Kursmünze", "no_match", None),
]


def _print_view(conn) -> None:
    print("\n=== v_ebay_standard_groups (maille pays) ===")
    rows = conn.execute(
        "SELECT country, n_eras, n_images, n_crops "
        "FROM v_ebay_standard_groups ORDER BY country"
    ).fetchall()
    print(f"{'pays':5s} {'n_eras':>6s} {'n_images':>8s} {'n_crops':>7s}")
    total = 0
    for r in rows:
        total += r["n_eras"]
        print(f"{r['country']:5s} {r['n_eras']:6d} {r['n_images']:8d} {r['n_crops']:7d}")
    print(f"→ {len(rows)} pays-groupes, {total} ères-standard canoniques")


def _print_eras(conn, countries: list[str]) -> None:
    print("\n=== Plages d'ères (appartenance de millésime) ===")
    for c in countries:
        eras = load_standard_eras(conn, _DENOM, c)
        print(f"\n  {c} :")
        for e in eras:
            hi = "…" if e.year_to >= 9999 else str(e.year_to)
            print(f"    [{e.year_from}–{hi:>4s}]  {e.eurio_id}")


def _run_cases(conn) -> int:
    print("\n=== Cas craftés (assertions dures) ===")
    print(f"{'OK':3s} {'pays':4s} {'verdict':10s} {'target':14s}  titre")
    n_fail = 0
    for country, title, exp_verdict, exp_target in _CASES:
        m = attribute_standard_listing(title, _DENOM, country, conn=conn)
        ok = m.verdict == exp_verdict and (
            exp_target is None or (m.target_eurio_id or "").startswith(exp_target)
        )
        if not ok:
            n_fail += 1
        tgt = (m.target_eurio_id or "—")[:14]
        flag = "✓" if ok else "✗"
        print(f"{flag:3s} {country:4s} {m.verdict:10s} {tgt:14s}  {title[:48]}")
        if not ok:
            print(
                f"      attendu verdict={exp_verdict} target~={exp_target} | "
                f"obtenu verdict={m.verdict} target={m.target_eurio_id} reason={m.reason}"
            )
    print(f"\n→ {len(_CASES) - n_fail}/{len(_CASES)} cas OK")
    return n_fail


def _run_real(conn, country: str, limit: int = 12) -> None:
    print(f"\n=== Titres RÉELS {country} (source_images/discarded) — réalisme ===")
    pfx = f"{country.lower()}-%"
    rows = conn.execute(
        """
        SELECT DISTINCT title FROM (
            SELECT listing_title AS title FROM source_images
             WHERE source='ebay' AND target_eurio_id LIKE ? AND listing_title IS NOT NULL
            UNION
            SELECT title FROM discarded_listings
             WHERE target_eurio_id LIKE ? AND title IS NOT NULL
        ) LIMIT ?
        """,
        (pfx, pfx, limit),
    ).fetchall()
    if not rows:
        print("  (aucun titre réel)")
        return
    print(f"{'verdict':10s} {'target':14s} {'reason':28s}  titre")
    for r in rows:
        title = r["title"]
        m = attribute_standard_listing(title, _DENOM, country, conn=conn)
        tgt = (m.target_eurio_id or "—")[:14]
        print(f"{m.verdict:10s} {tgt:14s} {m.reason[:28]:28s}  {title[:46]}")


def _run_cohort_proof(store, conn, cohort_name: str = "mix-zone-17") -> None:
    """Preuve d'expansion offline : les standards d'une cohort deviennent
    scrapables (aucun appel eBay — pur SQL via cohort_ebay_groups)."""
    print(f"\n=== Expansion cohort '{cohort_name}' (scrapabilité) ===")
    row = conn.execute(
        "SELECT id FROM experiment_cohorts WHERE name = ?", (cohort_name,)
    ).fetchone()
    if row is None:
        print(f"  (cohort '{cohort_name}' absente)")
        return
    groups, non_scrapable = cohort_ebay_groups(store, row["id"])
    std = [g for g in groups if g.kind == "standard"]
    comm = [g for g in groups if g.kind == "commemorative"]
    print(f"  {len(groups)} groupe(s) : {len(comm)} commémo + {len(std)} standard")
    for g in groups:
        yr = g.year if g.year is not None else "—"
        print(f"    {g.kind:13s} {g.country:3s} {str(yr):>5s}  n={g.n_coins}")
    print(f"  non_scrapable ({len(non_scrapable)}) : {non_scrapable or '—'}")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--db", type=Path, default=_DB)
    ap.add_argument("--cohort", default="mix-zone-17")
    args = ap.parse_args(argv)

    store = Store(args.db)  # applique schema.sql → crée la vue
    conn = store._connection()  # noqa: SLF001

    _print_view(conn)
    _print_eras(conn, ["ES", "AT", "MT", "VA"])
    n_fail = _run_cases(conn)
    _run_real(conn, "ES")
    _run_real(conn, "AT")
    _run_cohort_proof(store, conn, args.cohort)

    if n_fail:
        print(f"\n❌ {n_fail} assertion(s) dure(s) en échec")
        return 1
    print("\n✅ Toutes les assertions dures passent")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
