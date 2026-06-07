"""Ingestion du catalogue de la source référentielle → table `referential_catalog`.

Chunk 2 — harmonisation des données (docs/data-harmonization/).

Lit `ml/datasets/coin_catalog.json` (le produit du scrape Numista, 688 types)
et le miroite dans la table `referential_catalog` d'`eurio.db`. C'est la
**provenance brute** : `raw_json` est la vérité, les colonnes typées ne servent
qu'au QA / à la génération de `coins` (audit & Chunk 2b).

Aujourd'hui une seule source référentielle : `numista`. Le jour où la BCE (ou
une autre) en devient une, ce script gagne un `--source` ; le schéma le porte
déjà (`referential_catalog.source`).

Idempotent : `INSERT OR REPLACE` sur la PK `(source, source_native_id)`.

Usage::

    python -m scripts.ingest_referential_catalog --dry-run
    python -m scripts.ingest_referential_catalog
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from store import Store  # noqa: E402

DEFAULT_DB = ROOT / "state" / "eurio.db"
CATALOG_PATH = ROOT / "datasets" / "coin_catalog.json"
SNAPSHOT_REF = "datasets/coin_catalog.json"


def _rows_from_catalog(catalog_path: Path) -> tuple[list[tuple], str]:
    """Construit les lignes referential_catalog depuis coin_catalog.json."""
    payload = json.loads(catalog_path.read_text())
    coins = payload.get("coins") or {}
    if not isinstance(coins, dict):
        raise ValueError("coin_catalog.json: clé 'coins' attendue en dict")

    scraped_at = datetime.fromtimestamp(
        catalog_path.stat().st_mtime, tz=timezone.utc
    ).isoformat()

    rows: list[tuple] = []
    for native_id, entry in coins.items():
        rows.append(
            (
                # P.3b : registry vocabulary (was 'numista').
                "numista_api",
                str(native_id),
                entry.get("country"),
                entry.get("year"),
                entry.get("face_value"),
                entry.get("type"),
                json.dumps(entry, ensure_ascii=False),
                SNAPSHOT_REF,
                scraped_at,
            )
        )
    return rows, scraped_at


def ingest(store: Store, *, catalog_path: Path = CATALOG_PATH, dry_run: bool) -> dict:
    if not catalog_path.is_file():
        raise FileNotFoundError(f"Catalogue introuvable : {catalog_path}")

    rows, scraped_at = _rows_from_catalog(catalog_path)
    by_type: dict[str, int] = {}
    for r in rows:
        by_type[r[5] or "unknown"] = by_type.get(r[5] or "unknown", 0) + 1

    summary = {
        "dry_run": dry_run,
        "catalog_path": str(catalog_path),
        "scraped_at": scraped_at,
        "n_rows": len(rows),
        "by_type": by_type,
    }
    if dry_run:
        return summary

    conn = store._connection()  # noqa: SLF001
    conn.execute("BEGIN")
    try:
        conn.executemany(
            "INSERT OR REPLACE INTO referential_catalog "
            "(source, source_native_id, country_name, year, face_value, type, "
            " raw_json, scrape_snapshot_ref, scraped_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            rows,
        )
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise
    summary["n_in_table"] = conn.execute(
        "SELECT count(*) AS n FROM referential_catalog"
    ).fetchone()["n"]
    return summary


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dry-run", action="store_true", help="N'écrit rien.")
    ap.add_argument("--db", type=Path, default=DEFAULT_DB)
    ap.add_argument("--catalog", type=Path, default=CATALOG_PATH)
    return ap.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    store = Store(args.db)
    summary = ingest(store, catalog_path=args.catalog, dry_run=args.dry_run)
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
