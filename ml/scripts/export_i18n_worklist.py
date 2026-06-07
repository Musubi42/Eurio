"""Export the i18n scrape worklist from ``coins`` table to JSON.

Runs on **PC** (where ``eurio.db`` lives). Produces a small JSON file
that gets rsync'd to the VPS for the actual scrape (which has no DB).

Filter: ``face_value=2.0 AND numista_id IS NOT NULL`` — the ~578
commemoratives + standard maps that need localized titles for the
eBay multi-marketplace matcher.

Skip-existing : by default, rows already present in ``coin_names_i18n``
for **both** target langs (fr+en) are excluded. Pass ``--include-done``
to emit the full list anyway (e.g. for a forced refresh).

Cf. ``docs/sources-refacto/ebay-multi-marketplace/i18n-scrape-numista.md``.

Usage::

    .venv/bin/python -m scripts.export_i18n_worklist
    .venv/bin/python -m scripts.export_i18n_worklist --include-done
    .venv/bin/python -m scripts.export_i18n_worklist \\
        --langs fr,en --out ml/state/i18n_worklist.json
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from store import Store  # noqa: E402

LOGGER = logging.getLogger("export_i18n_worklist")

DEFAULT_DB = ROOT / "state" / "eurio.db"
DEFAULT_OUT = ROOT / "state" / "i18n_worklist.json"
DEFAULT_LANGS = ("fr", "en")


def build_worklist(
    store: Store,
    langs: list[str],
    *,
    include_done: bool,
) -> dict:
    conn = store._connection()  # noqa: SLF001
    coins = conn.execute(
        "SELECT eurio_id, numista_id FROM coins "
        "WHERE face_value=2.0 AND numista_id IS NOT NULL "
        "ORDER BY eurio_id"
    ).fetchall()

    done_by_coin: dict[str, set[str]] = {}
    if not include_done:
        placeholders = ",".join("?" * len(langs))
        rows = conn.execute(
            f"SELECT eurio_id, lang FROM coin_names_i18n "
            f"WHERE source='numista' AND lang IN ({placeholders})",
            langs,
        ).fetchall()
        for r in rows:
            done_by_coin.setdefault(r["eurio_id"], set()).add(r["lang"])

    items = []
    n_skipped = 0
    for row in coins:
        eurio_id = row["eurio_id"]
        numista_id = row["numista_id"]
        done = done_by_coin.get(eurio_id, set())
        missing = [l for l in langs if l not in done]
        if not missing and not include_done:
            n_skipped += 1
            continue
        items.append({
            "eurio_id": eurio_id,
            "numista_id": numista_id,
            "langs": missing if not include_done else list(langs),
        })

    payload = {
        "exported_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "filter": "face_value=2.0 AND numista_id IS NOT NULL",
        "langs": list(langs),
        "include_done": include_done,
        "n_coins_total": len(coins),
        "n_skipped_already_done": n_skipped,
        "n_items": len(items),
        "items": items,
    }
    return payload


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument(
        "--langs",
        default=",".join(DEFAULT_LANGS),
        help=f"Comma-separated target langs (default: {','.join(DEFAULT_LANGS)})",
    )
    parser.add_argument(
        "--include-done",
        action="store_true",
        help="Emit all rows even if both langs already in DB (forced refresh)",
    )
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(message)s")

    langs = [l.strip() for l in args.langs.split(",") if l.strip()]
    if not langs:
        parser.error("--langs is empty")

    store = Store(args.db)
    payload = build_worklist(store, langs, include_done=args.include_done)

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    LOGGER.info(
        "wrote %s — %d items (skipped %d already-done)",
        args.out, payload["n_items"], payload["n_skipped_already_done"],
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
