"""Nettoyage des rejets `text_contradict_*` legacy (auto-validation C5).

Avant C3, un verdict texte `contradict` tuait le listing à l'étape 2.5 :
`discarded_listings(reason='text_contradict_*')` + `source_images.route_decision
='rejected_text'` (download sauté). C3 a supprimé ce kill : un contradict
traverse maintenant le consensus. Restent en base les **rejets legacy** d'avant
la bascule — données orphelines (sans image_asset, donc non ré-ouvrables comme
rejets ; cf. doc §7 « ré-ouvrable seulement une fois l'image existante »).

Ce script les efface pour qu'un **re-run de leur cohorte les redécouvre et les
fasse passer par le consensus** (rescue mesuré : `scripts/contradict_rescue.py`).
Deux effets :
  - DELETE des `discarded_listings(reason LIKE 'text_contradict_%')` ;
  - reset `source_images.route_decision='rejected_text'` → NULL (marqueur de kill
    legacy ; le download ne le lit plus depuis C3, on le neutralise pour l'audit).

⚠️ Effet de bord : le panneau front « Listings rejetés pré-ingestion » perd ces
lignes. Dry-run par défaut ; `--apply` pour exécuter ; idempotent.

    python scripts/clean_legacy_text_contradict.py            # preview
    python scripts/clean_legacy_text_contradict.py --apply     # exécute
"""

from __future__ import annotations

import argparse
import sqlite3
from collections import Counter
from pathlib import Path

_DB = Path(__file__).resolve().parents[1] / "state" / "eurio.db"


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--db", type=Path, default=_DB)
    ap.add_argument("--apply", action="store_true", help="exécute (sinon dry-run)")
    args = ap.parse_args()

    conn = sqlite3.connect(args.db)
    by_axis = dict(
        conn.execute(
            "SELECT reason, COUNT(*) FROM discarded_listings "
            "WHERE reason LIKE 'text_contradict_%' GROUP BY reason"
        ).fetchall()
    )
    n_disc = sum(by_axis.values())
    n_routed = conn.execute(
        "SELECT COUNT(*) FROM source_images WHERE route_decision = 'rejected_text'"
    ).fetchone()[0]

    mode = "APPLY" if args.apply else "DRY-RUN"
    print(f"=== clean_legacy_text_contradict [{mode}] ===")
    print(f"  discarded_listings text_contradict_* : {n_disc}  {by_axis}")
    print(f"  source_images route_decision='rejected_text' : {n_routed}")

    if not args.apply:
        print("  (dry-run — rien supprimé ; --apply pour exécuter)")
        return

    cur_d = conn.execute(
        "DELETE FROM discarded_listings WHERE reason LIKE 'text_contradict_%'"
    )
    cur_s = conn.execute(
        "UPDATE source_images SET route_decision = NULL, route_reason = NULL "
        "WHERE route_decision = 'rejected_text'"
    )
    conn.commit()
    print(f"  → discarded_listings supprimés : {cur_d.rowcount}")
    print(f"  → source_images réinitialisés  : {cur_s.rowcount}")
    remaining = conn.execute(
        "SELECT COUNT(*) FROM discarded_listings WHERE reason LIKE 'text_contradict_%'"
    ).fetchone()[0]
    print(f"  → restants (doit être 0)       : {remaining}")


if __name__ == "__main__":
    main()
