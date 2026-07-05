"""Migration one-time : bookkeeping cohort_* du canonique → `eurio.local.db`.

Précondition du flip Direction A (« split bookkeeping », fiche
`docs/work-in-progress/hardening-2026-07/01-…md §6`). Après le split, les 3 tables
d'observabilité lab vivent dans le store d'état LOCAL (`eurio.local.db`, writable).
Leurs lignes HISTORIQUES sont encore dans le eurio.db canonique local (Model A) ;
le flip va remplacer ce canonique par la réplique VPS (où ces tables sont vides,
le VPS ne tourne pas le lab). Sans cette migration, l'historique des jobs/scans
serait perdu au flip et `replay._mix_zone_assets` (provenance mix_zone_17) verrait
du vide.

Idempotent (`INSERT OR IGNORE` sur la PK) : re-run = no-op. À lancer UNE fois,
avant d'appliquer le patch flip.

Usage::

    .venv/bin/python -m scripts.migrate_bookkeeping_to_local          # eurio.db → eurio.local.db
    .venv/bin/python -m scripts.migrate_bookkeeping_to_local --source /chemin/eurio.db
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ML_DIR = Path(__file__).resolve().parent.parent
if str(ML_DIR) not in sys.path:
    sys.path.insert(0, str(ML_DIR))

from store import local_state_store  # noqa: E402

# Les 3 tables du split (ordre : parents avant enfants pour les FK internes).
_TABLES = ("cohort_jobs", "cohort_training_scans", "cohort_training_scan_results")


def migrate(source: Path) -> int:
    if not source.is_file():
        print(f"source introuvable : {source}", file=sys.stderr)
        return 1

    lconn = local_state_store()._connection()  # noqa: SLF001 — dest writable
    # ATTACH la source (chemin simple : la connexion Store n'active pas `uri=True`,
    # donc pas de `file:…?mode=ro`). On ne fait QUE des SELECT sur `src` — aucune
    # écriture — donc l'ouvrir en read-write est inoffensif.
    lconn.execute(f"ATTACH DATABASE ? AS src", (str(source),))
    try:
        total = 0
        for t in _TABLES:
            before = lconn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
            # INSERT OR IGNORE : ne réécrit jamais une ligne déjà migrée (PK).
            # SELECT * : les deux DB sont bootstrapées par le même schema.sql →
            # colonnes identiques. Un mismatch échouerait bruyamment (voulu).
            lconn.execute(f"INSERT OR IGNORE INTO {t} SELECT * FROM src.{t}")
            after = lconn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
            added = after - before
            total += added
            print(f"  {t:32s} {before:>6d} → {after:<6d}  (+{added})")
        print(f"migration bookkeeping → {local_state_store().db_path} : +{total} lignes")
        return 0
    finally:
        lconn.execute("DETACH DATABASE src")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--source",
        type=Path,
        default=ML_DIR / "state" / "eurio.db",
        help="eurio.db canonique source (défaut: ml/state/eurio.db, pré-flip).",
    )
    args = parser.parse_args()
    return migrate(args.source)


if __name__ == "__main__":
    raise SystemExit(main())
