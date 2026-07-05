"""Vérifie qu'un backup `eurio.db` est restaurable et fidèle à la DB courante.

Étape P.5 du chantier coin-richness — filet de sécurité non négociable avant
le wipe destructif (P.6 produit le script, exécution ultérieure).

Mécanique :
1. Copie le backup dans un fichier temporaire (`/tmp/eurio_restore_test.db`),
   sans toucher la DB courante.
2. `PRAGMA integrity_check` → doit être ``ok``.
3. `PRAGMA foreign_key_check` → doit être vide.
4. Compare les row counts entre backup et DB courante sur les 10 tables
   référentielles "wipe-scope" (cf. ROADMAP-DB.md §8). Les counts doivent
   être strictement égaux (P.3 a été additif, ne touche pas aux rows).
5. Sample query métier : coin Bremen
   (`de-2010-2eur-city-hall-and-roland-bremen`) → la même triplette
   (observations, canonical_images, cross_refs) doit ressortir des deux DBs.

Exit 0 si tout vert, ≥1 sinon. Lecture-seule sur les deux DBs.

Usage::

    .venv/bin/python -m scripts.verify_backup_restore
    .venv/bin/python -m scripts.verify_backup_restore \
        --backup ml/state/eurio.db.bak-pre-p3-2026-05-25 \
        --current ml/state/eurio.db
"""

from __future__ import annotations

import argparse
import shutil
import sqlite3
import sys
from pathlib import Path

ML_DIR = Path(__file__).resolve().parent.parent
if str(ML_DIR) not in sys.path:
    sys.path.insert(0, str(ML_DIR))

from store import resolve_db_path  # noqa: E402


WIPE_SCOPE_TABLES: list[str] = [
    "coins",
    "referential_catalog",
    "design_groups",
    "coin_cross_refs",
    "coin_observations",
    "coin_canonical_images",
    "coin_aliases",
    "coin_names_i18n",
    "coin_market_quotes",
    "coin_national_variants",
]

SAMPLE_COIN_EURIO_ID = "de-2010-2eur-city-hall-and-roland-bremen"


def _open_ro(path: Path) -> sqlite3.Connection:
    uri = f"file:{path}?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def _count(conn: sqlite3.Connection, table: str) -> int:
    return conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]


def _sample_triplet(conn: sqlite3.Connection, eurio_id: str) -> tuple[int, int, int]:
    obs = conn.execute(
        "SELECT COUNT(*) FROM coin_observations WHERE eurio_id=?", (eurio_id,)
    ).fetchone()[0]
    img = conn.execute(
        "SELECT COUNT(*) FROM coin_canonical_images WHERE eurio_id=?", (eurio_id,)
    ).fetchone()[0]
    xref = conn.execute(
        "SELECT COUNT(*) FROM coin_cross_refs WHERE eurio_id=?", (eurio_id,)
    ).fetchone()[0]
    return (obs, img, xref)


def verify(backup_path: Path, current_path: Path, tmp_path: Path) -> list[str]:
    """Retourne la liste des erreurs (vide = OK)."""
    errors: list[str] = []

    if not backup_path.exists():
        return [f"backup not found: {backup_path}"]
    if not current_path.exists():
        return [f"current DB not found: {current_path}"]

    # 1. Restauration dans tmp
    shutil.copy2(backup_path, tmp_path)
    print(f"[1/5] copied {backup_path} → {tmp_path} ({tmp_path.stat().st_size / 1e6:.1f} MB)")

    # 2. integrity_check
    with sqlite3.connect(tmp_path) as t:
        result = t.execute("PRAGMA integrity_check").fetchone()[0]
        if result != "ok":
            errors.append(f"integrity_check failed: {result!r}")
        else:
            print("[2/5] integrity_check: ok")

        # 3. foreign_key_check
        fk_violations = t.execute("PRAGMA foreign_key_check").fetchall()
        if fk_violations:
            errors.append(f"foreign_key_check returned {len(fk_violations)} rows")
        else:
            print("[3/5] foreign_key_check: clean")

    # 4. Counts equality
    bak = _open_ro(tmp_path)
    cur = _open_ro(current_path)
    try:
        diffs: list[str] = []
        for table in WIPE_SCOPE_TABLES:
            b = _count(bak, table)
            c = _count(cur, table)
            tag = "OK" if b == c else "DIFF"
            print(f"      {table:32s} bak={b:<6d} cur={c:<6d} {tag}")
            if b != c:
                diffs.append(f"{table}: backup={b} current={c}")
        if diffs:
            errors.append("count mismatches: " + ", ".join(diffs))
        else:
            print("[4/5] counts: 10 tables wipe-scope égaux backup ↔ current")

        # 5. Sample query métier
        b_triplet = _sample_triplet(bak, SAMPLE_COIN_EURIO_ID)
        c_triplet = _sample_triplet(cur, SAMPLE_COIN_EURIO_ID)
        print(
            f"      Bremen ({SAMPLE_COIN_EURIO_ID}): "
            f"bak (obs={b_triplet[0]}, img={b_triplet[1]}, xref={b_triplet[2]}) "
            f"cur (obs={c_triplet[0]}, img={c_triplet[1]}, xref={c_triplet[2]})"
        )
        if b_triplet != c_triplet:
            errors.append(
                f"sample query Bremen differs: backup={b_triplet} current={c_triplet}"
            )
        elif sum(b_triplet) == 0:
            errors.append(
                f"sample coin {SAMPLE_COIN_EURIO_ID} returns zero rows in both DBs "
                "(coin missing? eurio_id renamed?)"
            )
        else:
            print(
                f"[5/5] sample query Bremen: triplet identique "
                f"(obs={b_triplet[0]}, img={b_triplet[1]}, xref={b_triplet[2]})"
            )
    finally:
        bak.close()
        cur.close()

    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--backup",
        default=str(ML_DIR / "state" / "eurio.db.bak-pre-p3-2026-05-25"),
        help="Path to backup file (default: ml/state/eurio.db.bak-pre-p3-2026-05-25)",
    )
    parser.add_argument(
        "--current",
        default=str(resolve_db_path(ML_DIR / "state" / "eurio.db")),
        help="Path to current eurio.db (default: ml/state/eurio.db)",
    )
    parser.add_argument(
        "--tmp",
        default="/tmp/eurio_restore_test.db",
        help="Temp path for restoration (default: /tmp/eurio_restore_test.db)",
    )
    args = parser.parse_args()

    errors = verify(Path(args.backup), Path(args.current), Path(args.tmp))

    if errors:
        print("\n❌ FAIL — backup verification failed:", file=sys.stderr)
        for e in errors:
            print(f"  - {e}", file=sys.stderr)
        return 1
    print("\n✅ OK — backup restorable and faithful to current DB")
    return 0


if __name__ == "__main__":
    sys.exit(main())
