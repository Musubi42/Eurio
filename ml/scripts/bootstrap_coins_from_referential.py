"""Bootstrap de la table ``coins`` SQLite depuis ``eurio_referential.json``.

Décision D-20 (sources-refacto/decisions.md) : le référentiel canonique
vit en JSON aujourd'hui. Pour rendre les vues d'enrichissement
(``v_ebay_freshness`` et futures) faisables en SQL pur, on miroite
le JSON dans une table ``coins`` SQLite. Bootstrap explicite (pas auto
au boot du Store) — voir progress.md 2026-05-03.

Usage::

    .venv/bin/python -m scripts.bootstrap_coins_from_referential
    .venv/bin/python -m scripts.bootstrap_coins_from_referential --dry-run

Idempotent : ``INSERT OR REPLACE`` par ``eurio_id``. Re-runner après
un update du JSON resynchronise la table. Aucune row n'est supprimée
automatiquement (R0 / D-02 esprit non destructif) — un eurio_id qui
disparaît du JSON reste en DB jusqu'à un cleanup explicite.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from state.store import Store  # noqa: E402

logger = logging.getLogger("bootstrap_coins")

REFERENTIAL_PATH = ROOT / "datasets" / "eurio_referential.json"
DEFAULT_DB = ROOT / "state" / "training.db"


def _row_from_entry(entry: dict) -> tuple:
    ident = entry.get("identity") or {}
    cross = entry.get("cross_refs") or {}
    return (
        entry["eurio_id"],
        ident.get("country") or "",
        ident.get("country_name"),
        int(ident["year"]) if ident.get("year") is not None else 0,
        float(ident["face_value"]) if ident.get("face_value") is not None else 0.0,
        1 if ident.get("is_commemorative") else 0,
        ident.get("theme"),
        cross.get("numista_id"),
        json.dumps(entry, ensure_ascii=False),
    )


def bootstrap(store: Store, *, json_path: Path = REFERENTIAL_PATH, dry_run: bool = False) -> dict:
    """Charge le JSON et upsert les rows ``coins``. Retourne un summary."""
    if not json_path.is_file():
        raise FileNotFoundError(f"Référentiel introuvable : {json_path}")

    payload = json.loads(json_path.read_text())
    entries = payload.get("entries") or []
    if not isinstance(entries, list):
        raise ValueError(
            f"Format inattendu : 'entries' devrait être une liste, "
            f"trouvé {type(entries).__name__}"
        )

    rows = [_row_from_entry(e) for e in entries if e.get("eurio_id")]
    n_total = len(rows)

    summary = {
        "json_path": str(json_path),
        "schema_version": payload.get("schema_version"),
        "generated_at": payload.get("generated_at"),
        "n_entries_total": n_total,
        "n_inserted_or_replaced": 0,
        "dry_run": dry_run,
    }

    if dry_run:
        logger.info("dry-run: would upsert %d coin rows", n_total)
        return summary

    conn = store._connection()  # noqa: SLF001
    with conn:
        conn.executemany(
            """
            INSERT OR REPLACE INTO coins (
              eurio_id, country, country_name, year, face_value,
              is_commemorative, theme, numista_id, raw_payload_json,
              imported_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))
            """,
            rows,
        )
    summary["n_inserted_or_replaced"] = n_total
    logger.info("upserted %d coin rows from %s", n_total, json_path.name)
    return summary


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dry-run", action="store_true", help="N'écrit rien, affiche le summary.")
    ap.add_argument(
        "--db",
        type=Path,
        default=DEFAULT_DB,
        help="Chemin DB alternatif (défaut: ml/state/training.db).",
    )
    ap.add_argument(
        "--json",
        dest="json_path",
        type=Path,
        default=REFERENTIAL_PATH,
        help="Chemin du référentiel JSON.",
    )
    return ap.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    args = parse_args(argv)
    store = Store(args.db)
    summary = bootstrap(store, json_path=args.json_path, dry_run=args.dry_run)
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
