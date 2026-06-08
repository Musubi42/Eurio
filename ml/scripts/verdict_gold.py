"""CLI du gold de replay du verdict d'auto-validation (C2.5).

    python scripts/verdict_gold.py build    # fige le gold (assets + verdict actuel)
    python scripts/verdict_gold.py replay    # recompute + diff before↔after + correction

``build`` snapshote la vérité terrain (human_admin + mix_zone_17) et le verdict
courant. ``replay`` est le gate de C3 : tout changement de la règle de consensus
doit être rejoué ici, le diff inspecté, et toute régression justifiée.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
from collections import Counter
from pathlib import Path

from review.validation.replay import (
    DEFAULT_GOLD,
    build_gold,
    load_gold,
    replay_gold,
    save_gold,
)

_DB = Path(__file__).resolve().parents[1] / "state" / "eurio.db"


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build", help="fige le gold")
    b.add_argument("--db", type=Path, default=_DB)
    b.add_argument("--out", type=Path, default=DEFAULT_GOLD)
    r = sub.add_parser("replay", help="recompute + diff")
    r.add_argument("--db", type=Path, default=_DB)
    r.add_argument("--gold", type=Path, default=DEFAULT_GOLD)
    args = ap.parse_args()

    conn = sqlite3.connect(args.db)
    if args.cmd == "build":
        gold = build_gold(conn)
        save_gold(gold, args.out)
        print(f"gold figé: {len(gold)} assets → {args.out}")
        print("par source:", dict(Counter(g.source for g in gold)))
        print("verdict before:", dict(Counter(g.before_level for g in gold)))
        return

    gold = load_gold(args.gold)
    rep = replay_gold(conn, gold)
    print(json.dumps({k: v for k, v in rep.items() if k != "changes"}, indent=2, ensure_ascii=False))
    if rep["changes"]:
        print(f"\n{rep['n_changes']} CHANGEMENT(S) de verdict :")
        for ch in rep["changes"][:30]:
            print(f"  {ch['asset_id'][:16]} [{ch['source']}] {ch['before']} → {ch['after']}")
    else:
        print("\nDIFF VIDE — aucune régression (règle inchangée). Harness OK.")


if __name__ == "__main__":
    main()
