"""Import i18n scrape results JSONL into ``coin_names_i18n``.

Runs on **PC** after the VPS scrape, once ``i18n_results.jsonl`` has
been rsync'd back.

Idempotent : default mode is ``INSERT OR IGNORE``. ``--replace`` switches
to ``INSERT OR REPLACE`` for a forced refresh.

Migration: the script triggers ``Store(...)`` which runs ``_bootstrap``
and adds ``confidence`` + ``model`` columns if missing (additive).

Cf. ``docs/sources-refacto/ebay-multi-marketplace/i18n-scrape-numista.md``.

Usage::

    .venv/bin/python -m scripts.import_i18n_results
    .venv/bin/python -m scripts.import_i18n_results --dry-run
    .venv/bin/python -m scripts.import_i18n_results --replace
    .venv/bin/python -m scripts.import_i18n_results \\
        --results ml/state/i18n_results.jsonl
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

LOGGER = logging.getLogger("import_i18n_results")

DEFAULT_DB = ROOT / "state" / "eurio.db"
DEFAULT_RESULTS = ROOT / "state" / "i18n_results.jsonl"

REQUIRED_FIELDS = ("eurio_id", "lang", "title")


def _read_results(path: Path) -> list[dict]:
    rows: list[dict] = []
    with path.open("r", encoding="utf-8") as f:
        for n, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError as e:
                raise ValueError(f"{path}:{n} — invalid JSON: {e}") from e
            missing = [k for k in REQUIRED_FIELDS if k not in obj]
            if missing:
                raise ValueError(f"{path}:{n} — missing fields {missing}: {obj}")
            rows.append(obj)
    return rows


def import_results(
    store: Store,
    rows: list[dict],
    *,
    replace: bool,
    dry_run: bool,
) -> dict:
    verb = "INSERT OR REPLACE" if replace else "INSERT OR IGNORE"
    sql = (
        f"{verb} INTO coin_names_i18n "
        "(eurio_id, lang, title, source, method, confidence, model, fetched_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)"
    )
    # P.3b : source = registry id (numista_api default), method = NULL pour
    # un titre Numista direct. Legacy JSONL peut porter un `source` (string
    # libre) → mappé vers `method`, source forcé à 'numista_api' (l'origine
    # underlying du titre i18n est toujours Numista pour ce script).
    payload = [
        (
            r["eurio_id"],
            r["lang"],
            r["title"],
            "numista_api",
            r.get("source"),  # legacy field → moved to method
            r.get("confidence", "canon"),
            r.get("model"),
            r.get("fetched_at"),
        )
        for r in rows
    ]

    summary = {
        "n_rows": len(payload),
        "mode": "replace" if replace else "ignore",
        "dry_run": dry_run,
    }

    if dry_run:
        LOGGER.info("dry-run: would %s %d rows", verb, len(payload))
        return summary

    conn = store._connection()  # noqa: SLF001
    with conn:
        # rowcount on executemany is unreliable across drivers; we just
        # report n_rows submitted. Real persisted count is checkable via
        # SELECT count(*) post-run.
        conn.executemany(sql, payload)
    LOGGER.info("%s %d rows into coin_names_i18n", verb, len(payload))

    # Coverage stats
    cur = conn.execute(
        "SELECT lang, count(*) AS n FROM coin_names_i18n "
        "WHERE source='numista' GROUP BY lang ORDER BY lang"
    )
    summary["coverage_by_lang"] = {row["lang"]: row["n"] for row in cur}
    return summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    parser.add_argument("--results", type=Path, default=DEFAULT_RESULTS)
    parser.add_argument("--replace", action="store_true",
                        help="INSERT OR REPLACE instead of INSERT OR IGNORE")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(message)s")

    if not args.results.is_file():
        parser.error(f"results file not found: {args.results}")

    rows = _read_results(args.results)
    LOGGER.info("loaded %d rows from %s", len(rows), args.results)

    store = Store(args.db)  # triggers schema migration (confidence/model)
    summary = import_results(store, rows, replace=args.replace, dry_run=args.dry_run)
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
