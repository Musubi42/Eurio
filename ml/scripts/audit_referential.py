"""Audit de réconciliation `referential_catalog` ↔ `coins` — Chunk 2.

Lecture seule. Compare le catalogue de la source référentielle (Numista,
table `referential_catalog`) au référentiel canonique (`coins`) et remonte les
écarts — sans rien muter. C'est le **worklist** des corrections d'identité
(Chunk 2b), à commencer par le cas BE 2017.

Périmètre : **2 € commémoratives** uniquement — c'est là que vaut le « 1 type
Numista = 1 pièce ». Les pièces de circulation (1 type Numista = N millésimes)
sont hors-périmètre de cet audit.

Écarts remontés :
  - count_mismatch : pour un (pays, année), Numista et `coins` n'ont pas le même
    nombre de 2 € commémo → pièce(s) manquante(s) ou en trop. (BE 2017 : 2 vs 1.)
  - numista_orphan : une pièce dont le `numista_id` n'existe pas dans le catalogue.
  - catalog_unlinked : un type Numista 2 € commémo qu'aucune pièce ne référence.
  - unlinked_coin : une 2 € commémo sans `numista_id` du tout.

Usage::

    python -m scripts.audit_referential
    python -m scripts.audit_referential --json datasets/referential_audit.json
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from store import Store  # noqa: E402

DEFAULT_DB = ROOT / "state" / "eurio.db"
COUNTRY_MAPPING = ROOT / "datasets" / "country_mapping.json"

# Numista emploie parfois des libellés différents de country_mapping.json.
EXTRA_NAME_TO_ISO2 = {
    "Germany, Federal Republic of": "DE",
    "Germany": "DE",
}


def _name_to_iso2() -> dict[str, str]:
    mapping = json.loads(COUNTRY_MAPPING.read_text())
    out = {v["name"]: iso2 for iso2, v in mapping.items()}
    out.update(EXTRA_NAME_TO_ISO2)
    return out


def audit(store: Store) -> dict:
    conn = store._connection()  # noqa: SLF001
    name_to_iso2 = _name_to_iso2()
    unmapped: set[str] = set()

    def iso2(country_name: str | None) -> str | None:
        if not country_name:
            return None
        hit = name_to_iso2.get(country_name)
        if hit is None:
            unmapped.add(country_name)
        return hit

    # ── Catalogue Numista : 2 € commémo ───────────────────────────────────
    cat_rows = conn.execute(
        "SELECT source_native_id, country_name, year, raw_json "
        "FROM referential_catalog "
        "WHERE source='numista' AND type='commemorative' AND face_value=2.0"
    ).fetchall()
    cat_by_cy: Counter = Counter()
    cat_ids: set[int] = set()
    cat_meta: dict[int, dict] = {}
    for r in cat_rows:
        nid = int(r["source_native_id"])
        cat_ids.add(nid)
        cy = (iso2(r["country_name"]), r["year"])
        cat_by_cy[cy] += 1
        cat_meta[nid] = {"country": cy[0], "year": r["year"],
                         "name": json.loads(r["raw_json"]).get("name")}

    # ── coins : 2 € commémo ───────────────────────────────────────────────
    coin_rows = conn.execute(
        "SELECT eurio_id, country, year, numista_id, theme FROM coins "
        "WHERE is_commemorative=1 AND face_value=2.0"
    ).fetchall()
    coin_by_cy: Counter = Counter()
    coin_numista: dict[int, list[str]] = {}
    unlinked: list[dict] = []
    for r in coin_rows:
        coin_by_cy[(r["country"], r["year"])] += 1
        if r["numista_id"] is None:
            unlinked.append({"eurio_id": r["eurio_id"]})
        else:
            coin_numista.setdefault(int(r["numista_id"]), []).append(r["eurio_id"])

    # ── Écarts ────────────────────────────────────────────────────────────
    count_mismatch: list[dict] = []
    for cy in sorted(set(cat_by_cy) | set(coin_by_cy), key=lambda x: (str(x[0]), x[1])):
        n_cat, n_coin = cat_by_cy.get(cy, 0), coin_by_cy.get(cy, 0)
        if n_cat != n_coin:
            count_mismatch.append(
                {"country": cy[0], "year": cy[1],
                 "n_numista": n_cat, "n_coins": n_coin, "delta": n_cat - n_coin}
            )

    numista_orphan = [
        {"numista_id": nid, "coins": eids}
        for nid, eids in sorted(coin_numista.items())
        if nid not in cat_ids
    ]
    catalog_unlinked = [
        {"numista_id": nid, **cat_meta[nid]}
        for nid in sorted(cat_ids)
        if nid not in coin_numista
    ]

    return {
        "scope": "2eur_commemorative",
        "n_numista_types": len(cat_rows),
        "n_coins": len(coin_rows),
        "n_coins_linked": len(coin_numista),
        "n_coins_unlinked": len(unlinked),
        "count_mismatch": count_mismatch,
        "numista_orphan": numista_orphan,
        "catalog_unlinked": catalog_unlinked,
        "unmapped_country_names": sorted(unmapped),
        "unlinked_coins_sample": unlinked[:20],
    }


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--db", type=Path, default=DEFAULT_DB)
    ap.add_argument("--json", type=Path, default=ROOT / "datasets" / "referential_audit.json")
    return ap.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    store = Store(args.db)
    report = audit(store)
    args.json.write_text(json.dumps(report, indent=2, ensure_ascii=False))

    print("=" * 60)
    print("AUDIT referential_catalog ↔ coins  (2 € commémoratives)")
    print("=" * 60)
    print(f"  types Numista (catalogue)  : {report['n_numista_types']}")
    print(f"  pièces coins               : {report['n_coins']}")
    print(f"    dont liées à un numista_id : {report['n_coins_linked']}")
    print(f"    dont SANS numista_id       : {report['n_coins_unlinked']}")
    print()
    print(f"  ⚠ count_mismatch (pays,année) : {len(report['count_mismatch'])}")
    for m in report["count_mismatch"]:
        print(f"      {m['country']} {m['year']} : "
              f"Numista={m['n_numista']} coins={m['n_coins']} (Δ{m['delta']:+d})")
    print(f"  ⚠ numista_orphan (id absent du catalogue) : {len(report['numista_orphan'])}")
    for o in report["numista_orphan"][:15]:
        print(f"      numista {o['numista_id']} ← {o['coins']}")
    print(f"  ⚠ catalog_unlinked (type Numista sans pièce) : {len(report['catalog_unlinked'])}")
    for c in report["catalog_unlinked"][:15]:
        print(f"      numista {c['numista_id']} : {c['country']} {c['year']} — {c['name']}")
    if report["unmapped_country_names"]:
        print(f"  ⚠ pays non mappés : {report['unmapped_country_names']}")
    print()
    print(f"Rapport complet : {args.json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
