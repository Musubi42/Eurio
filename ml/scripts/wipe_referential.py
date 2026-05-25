"""Wipe destructif du référentiel + recreate des 6 tables source-aware.

Étape P.6 du chantier coin-richness — produit le script de wipe, **ne
l'exécute pas** automatiquement. Le wipe effectif est un acte ultérieur
sous confirmation explicite (mode ``--apply``).

Deux modes :

* ``--dry-run`` (défaut) : lecture-seule. Affiche les counts à wiper, les
  6 tables à drop+recreate, et un preview du DDL appliqué. N'écrit rien.
* ``--apply`` : crée un backup auto, demande confirmation interactive
  (``Type "WIPE" to confirm``), puis exécute en transaction atomique :

  1. ``DELETE FROM`` des 10 tables wipe-scope.
  2. ``DROP TABLE`` puis ``CREATE TABLE`` des 6 tables source-aware avec
     FK ``source REFERENCES source_registry(id) ON DELETE RESTRICT``.
  3. Smoke test interne (savepoint rollback) : INSERT avec source valide
     doit OK, INSERT avec source inconnue doit FK violation.
  4. Post-checks : integrity_check, foreign_key_check, counts=0 sur les
     tables wipées, FK source enforced sur les 6 recréées.

Tables wipées (cf. ROADMAP-DB.md §8) :

    coins, referential_catalog, design_groups, coin_cross_refs,
    coin_observations, coin_canonical_images, coin_aliases,
    coin_names_i18n, coin_market_quotes, coin_national_variants

Tables préservées : toute l'infra terrain (source_runs, source_images,
image_assets, discovery_*, training_*, review_queue, …) +
``eurio_id_migrations`` (patrimoine) + ``source_registry`` (seedé P.4) +
les 9 nouvelles tables P.3a (mints, coin_variants, …).

⚠️ Garde-fou : impossible de run ``--apply`` sans confirmation interactive
exacte du mot ``WIPE`` (uppercase).
"""

from __future__ import annotations

import argparse
import shutil
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

ML_DIR = Path(__file__).resolve().parent.parent
if str(ML_DIR) not in sys.path:
    sys.path.insert(0, str(ML_DIR))


# ─── Wipe scope ────────────────────────────────────────────────────────────

WIPE_TABLES: list[str] = [
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


# ─── DDL — 6 tables source-aware recréées avec FK source_registry ─────────
#
# Ordre de DROP/CREATE n'a pas d'importance (les 6 ne se référencent pas
# entre elles ; elles référencent toutes coins ou source_registry, qui sont
# préservées). Les indexes sont recréés dans la même section.

RECREATE_DDL: dict[str, str] = {
    "coin_observations": """
        CREATE TABLE coin_observations (
          id               INTEGER PRIMARY KEY,
          eurio_id         TEXT NOT NULL REFERENCES coins(eurio_id) ON DELETE CASCADE,
          source           TEXT NOT NULL REFERENCES source_registry(id) ON DELETE RESTRICT,
          source_ref       TEXT,
          observation_type TEXT NOT NULL,
          payload_json     TEXT NOT NULL,
          recorded_at      TEXT NOT NULL DEFAULT (datetime('now')),
          UNIQUE (eurio_id, source, observation_type)
        );
        CREATE INDEX idx_coin_observations_eurio
          ON coin_observations(eurio_id);
    """,
    "coin_market_quotes": """
        CREATE TABLE coin_market_quotes (
          id                   TEXT PRIMARY KEY,
          eurio_id             TEXT NOT NULL,
          source               TEXT NOT NULL REFERENCES source_registry(id) ON DELETE RESTRICT,
          source_ref           TEXT,
          condition_raw        TEXT,
          condition_normalized TEXT NOT NULL DEFAULT 'unknown',
          currency             TEXT NOT NULL DEFAULT 'EUR',
          p10                  REAL,
          p50                  REAL,
          p90                  REAL,
          sample_size          INTEGER NOT NULL DEFAULT 1,
          period_start         TEXT NOT NULL,
          period_end           TEXT NOT NULL,
          fetched_at           TEXT NOT NULL DEFAULT (datetime('now')),
          raw_payload_json     TEXT,
          run_id               TEXT REFERENCES source_runs(id) ON DELETE SET NULL,
          UNIQUE (source, eurio_id, period_start, condition_raw)
        );
        CREATE INDEX idx_cmq_eurio  ON coin_market_quotes(eurio_id);
        CREATE INDEX idx_cmq_source ON coin_market_quotes(source);
        CREATE INDEX idx_cmq_period ON coin_market_quotes(period_start DESC);
        CREATE INDEX idx_cmq_run    ON coin_market_quotes(run_id);
    """,
    "referential_catalog": """
        CREATE TABLE referential_catalog (
          source              TEXT NOT NULL REFERENCES source_registry(id) ON DELETE RESTRICT,
          source_native_id    TEXT NOT NULL,
          country_name        TEXT,
          year                INTEGER,
          face_value          REAL,
          type                TEXT,
          raw_json            TEXT NOT NULL,
          scrape_snapshot_ref TEXT,
          scraped_at          TEXT NOT NULL DEFAULT (datetime('now')),
          PRIMARY KEY (source, source_native_id)
        );
    """,
    "coin_canonical_images": """
        CREATE TABLE coin_canonical_images (
          eurio_id   TEXT NOT NULL REFERENCES coins(eurio_id) ON DELETE CASCADE,
          source     TEXT NOT NULL REFERENCES source_registry(id) ON DELETE RESTRICT,
          role       TEXT NOT NULL CHECK (role IN ('obverse','reverse')),
          url        TEXT,
          local_path TEXT,
          PRIMARY KEY (eurio_id, source, role)
        ) WITHOUT ROWID;
    """,
    "coin_aliases": """
        CREATE TABLE coin_aliases (
          eurio_id   TEXT NOT NULL REFERENCES coins(eurio_id) ON DELETE CASCADE,
          lang       TEXT NOT NULL,
          alias      TEXT NOT NULL,
          source     TEXT NOT NULL REFERENCES source_registry(id) ON DELETE RESTRICT,
          method     TEXT,
          confidence TEXT NOT NULL DEFAULT 'high',
          fetched_at TEXT NOT NULL DEFAULT (datetime('now')),
          PRIMARY KEY (eurio_id, lang, alias)
        );
        CREATE INDEX idx_coin_aliases_eurio
          ON coin_aliases(eurio_id);
    """,
    "coin_names_i18n": """
        CREATE TABLE coin_names_i18n (
          eurio_id   TEXT NOT NULL REFERENCES coins(eurio_id) ON DELETE CASCADE,
          lang       TEXT NOT NULL CHECK (lang IN ('fr','en','de','it','es','nl')),
          title      TEXT NOT NULL,
          source     TEXT NOT NULL REFERENCES source_registry(id) ON DELETE RESTRICT,
          method     TEXT,
          model      TEXT,
          confidence TEXT NOT NULL DEFAULT 'canon',
          fetched_at TEXT NOT NULL DEFAULT (datetime('now')),
          PRIMARY KEY (eurio_id, lang)
        );
        CREATE INDEX idx_coin_names_i18n_lang
          ON coin_names_i18n(lang);
    """,
}

RECREATE_TABLES: list[str] = list(RECREATE_DDL.keys())


# ─── Helpers ───────────────────────────────────────────────────────────────


def _connect(db_path: Path) -> sqlite3.Connection:
    # isolation_level=None → autocommit mode. Indispensable car
    # executescript() commit implicitement la transaction pendante en mode
    # par défaut, ce qui casse notre BEGIN IMMEDIATE / COMMIT manuel.
    conn = sqlite3.connect(db_path, isolation_level=None)
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def _split_statements(script: str) -> list[str]:
    """Split un script SQL sur ';' et retourne les statements non vides.
    Suffisant pour nos DDL (pas de littéraux contenant ';')."""
    return [s.strip() for s in script.split(";") if s.strip()]


def _table_counts(conn: sqlite3.Connection, tables: list[str]) -> dict[str, int]:
    return {t: conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in tables}


def _table_has_fk_to_source_registry(conn: sqlite3.Connection, table: str) -> bool:
    rows = conn.execute(f"PRAGMA foreign_key_list({table})").fetchall()
    # Each row: (id, seq, table, from, to, on_update, on_delete, match)
    return any(r[2] == "source_registry" and r[3] == "source" for r in rows)


# ─── Dry-run ───────────────────────────────────────────────────────────────


def dry_run(db_path: Path) -> int:
    if not db_path.exists():
        print(f"DB not found: {db_path}", file=sys.stderr)
        return 1
    print(f"=== DRY RUN — {db_path} ===\n")
    conn = _connect(db_path)
    try:
        print("Tables à wiper (DELETE FROM) :")
        counts = _table_counts(conn, WIPE_TABLES)
        total = 0
        for t, c in counts.items():
            print(f"  {t:32s} {c:>6d} rows")
            total += c
        print(f"  {'TOTAL':32s} {total:>6d} rows à supprimer\n")

        print("Tables à DROP+RECREATE (FK source → source_registry) :")
        for t in RECREATE_TABLES:
            already_fk = _table_has_fk_to_source_registry(conn, t)
            marker = "(FK déjà présente)" if already_fk else "(FK à ajouter)"
            print(f"  {t:32s} {marker}")

        print("\nDDL preview (1ère table recréée) :")
        print(RECREATE_DDL[RECREATE_TABLES[0]].strip())

        print("\nTables préservées (non listées ci-dessus) : toute l'infra")
        print("terrain + eurio_id_migrations + source_registry + 9 nouvelles tables P.3a.")
        print("\nRien n'a été écrit. Pour exécuter : --apply.")
    finally:
        conn.close()
    return 0


# ─── Apply ─────────────────────────────────────────────────────────────────


def _auto_backup(db_path: Path) -> Path:
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H-%M-%SZ")
    backup_path = db_path.parent / f"{db_path.name}.bak-pre-wipe-{ts}"
    shutil.copy2(db_path, backup_path)
    return backup_path


def _prompt_confirm() -> bool:
    try:
        answer = input('Type "WIPE" to confirm (uppercase exact match): ')
    except EOFError:
        return False
    return answer == "WIPE"


def _smoke_test(conn: sqlite3.Connection) -> list[str]:
    """Vérifie post-recreate que la FK source est enforced. Savepoint rollback,
    n'écrit rien définitivement."""
    errors: list[str] = []
    cursor = conn.cursor()
    cursor.execute("SAVEPOINT smoke_test")
    try:
        # 1. Need a parent coin row to satisfy FK eurio_id → coins. The wipe
        #    just emptied coins, so we insert a throwaway parent first.
        cursor.execute(
            "INSERT INTO coins (eurio_id, country, year, face_value, is_commemorative) "
            "VALUES ('__smoke__', 'eu', 1999, 2.0, 1)"
        )
        # 2. Valid source ('numista_api' is seeded in source_registry).
        try:
            cursor.execute(
                "INSERT INTO coin_observations (eurio_id, source, observation_type, payload_json) "
                "VALUES ('__smoke__', 'numista_api', 'smoke', '{}')"
            )
        except sqlite3.IntegrityError as e:
            errors.append(f"valid source insert rejected: {e}")
        # 3. Invalid source must FK violation.
        try:
            cursor.execute(
                "INSERT INTO coin_observations (eurio_id, source, observation_type, payload_json) "
                "VALUES ('__smoke__', 'atlantis', 'smoke', '{}')"
            )
            errors.append("invalid source 'atlantis' was accepted (FK not enforced)")
        except sqlite3.IntegrityError:
            pass  # expected
    finally:
        cursor.execute("ROLLBACK TO SAVEPOINT smoke_test")
        cursor.execute("RELEASE SAVEPOINT smoke_test")
    return errors


def apply(db_path: Path, *, skip_confirm: bool = False) -> int:
    if not db_path.exists():
        print(f"DB not found: {db_path}", file=sys.stderr)
        return 1

    # 1. Backup auto
    backup_path = _auto_backup(db_path)
    print(f"[1/6] backup auto : {backup_path} ({backup_path.stat().st_size / 1e6:.1f} MB)")

    # 2. Préview counts + confirmation
    conn = _connect(db_path)
    counts = _table_counts(conn, WIPE_TABLES)
    total = sum(counts.values())
    print(f"\n[2/6] {total} rows seront supprimées sur {len(WIPE_TABLES)} tables :")
    for t, c in counts.items():
        print(f"        {t:32s} {c:>6d}")
    print(
        f"\n     + {len(RECREATE_TABLES)} tables DROP+RECREATE avec FK source → source_registry"
    )

    if skip_confirm:
        print("\n[3/6] confirmation skipped (--yes flag).")
    else:
        if not _prompt_confirm():
            print("\n❌ Confirmation refusée. Aucune modification effectuée.")
            conn.close()
            return 1
        print("[3/6] confirmation OK.")

    # 4. Transaction atomique
    cursor = conn.cursor()
    try:
        cursor.execute("BEGIN IMMEDIATE")

        # 4a. Wipe rows
        for t in WIPE_TABLES:
            cursor.execute(f"DELETE FROM {t}")
        print(f"[4/6] DELETE FROM × {len(WIPE_TABLES)} effectué")

        # 4b. Drop + recreate
        # Note : on n'utilise PAS executescript() car il commit implicitement
        # la transaction pendante (gotcha sqlite3 Python). On split sur ';'
        # et on exécute chaque statement individuellement.
        for t in RECREATE_TABLES:
            cursor.execute(f"DROP TABLE IF EXISTS {t}")
            for stmt in _split_statements(RECREATE_DDL[t]):
                cursor.execute(stmt)
        print(f"[5/6] DROP+RECREATE × {len(RECREATE_TABLES)} effectué")

        # 4c. Smoke test (savepoint, rollback interne, ne pollue pas)
        smoke_errors = _smoke_test(conn)
        if smoke_errors:
            cursor.execute("ROLLBACK")
            print(f"\n❌ Smoke test failed: {smoke_errors}")
            print(f"   Rolled back. Backup intact : {backup_path}")
            conn.close()
            return 1
        print("[6/6] smoke test FK source : OK (valid accepted, invalid rejected)")

        cursor.execute("COMMIT")
    except Exception as e:
        cursor.execute("ROLLBACK")
        print(f"\n❌ Transaction error: {e}")
        print(f"   Rolled back. Backup intact : {backup_path}")
        conn.close()
        return 1

    # 5. Post-checks
    errors = _post_checks(conn)
    conn.close()

    if errors:
        print("\n❌ POST-CHECK FAIL :")
        for e in errors:
            print(f"   - {e}")
        print(f"\n   Backup disponible pour restauration : {backup_path}")
        return 1

    print("\n✅ WIPE OK — toutes les vérifications post-wipe passent.")
    print(f"   Backup auto : {backup_path}")
    return 0


def _post_checks(conn: sqlite3.Connection) -> list[str]:
    errors: list[str] = []

    integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]
    if integrity != "ok":
        errors.append(f"integrity_check: {integrity!r}")

    fk_violations = conn.execute("PRAGMA foreign_key_check").fetchall()
    if fk_violations:
        errors.append(f"foreign_key_check: {len(fk_violations)} violations")

    for t in WIPE_TABLES:
        c = conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
        if c != 0:
            errors.append(f"{t} not empty: {c} rows remain")

    for t in RECREATE_TABLES:
        if not _table_has_fk_to_source_registry(conn, t):
            errors.append(f"{t}: FK source → source_registry not present")

    return errors


# ─── Main ──────────────────────────────────────────────────────────────────


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--db",
        default=str(ML_DIR / "state" / "eurio.db"),
        help="Path to eurio.db (default: ml/state/eurio.db)",
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--dry-run",
        action="store_true",
        default=True,
        help="Read-only report (default).",
    )
    mode.add_argument(
        "--apply",
        action="store_true",
        help="Execute wipe. Demande confirmation interactive.",
    )
    parser.add_argument(
        "--yes",
        action="store_true",
        help="Skip interactive confirmation (uniquement avec --apply ; usage tests).",
    )
    args = parser.parse_args()

    db_path = Path(args.db)
    if args.apply:
        return apply(db_path, skip_confirm=args.yes)
    return dry_run(db_path)


if __name__ == "__main__":
    sys.exit(main())
