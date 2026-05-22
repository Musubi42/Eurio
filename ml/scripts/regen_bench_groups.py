"""Régénère `discovery_bench/groups.json` depuis `coins` — Chunk 3.

Harmonisation des données (docs/data-harmonization/).

`groups.json` est le **contexte de jugement** du studio bench : pour chaque
année, les commémos-sœurs candidates (thème + i18n). Après le fix BE 2017
(la pièce 2017 éclatée en Gand + Liège), ce contexte est périmé — il ne
montre encore qu'une entrée. Ce script le régénère depuis le référentiel
canonique pour que le ré-étiquetage du gold se fasse sur les bons candidats.

N'écrit QUE `groups.json` (le contexte). Le `batch.jsonl` (échantillon) et le
gold gelé ne sont pas touchés : le ré-jugement Gand/Liège des entrées 2017
reste une tâche humaine dans le studio bench.

Domaine du bench : commémoratives 2 € belges (cf. `api/bench_routes.py`).

Usage::

    python -m scripts.regen_bench_groups --dry-run
    python -m scripts.regen_bench_groups
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from state.store import Store  # noqa: E402

DEFAULT_DB = ROOT / "state" / "eurio.db"
GROUPS_PATH = ROOT / "state" / "discovery_bench" / "groups.json"
I18N_LANGS = ("fr", "en", "de", "es", "it", "nl")


def regen(store: Store, *, dry_run: bool) -> dict:
    if not GROUPS_PATH.is_file():
        raise FileNotFoundError(f"{GROUPS_PATH} introuvable")
    years = sorted(json.loads(GROUPS_PATH.read_text()).keys())

    conn = store._connection()  # noqa: SLF001
    groups_ctx: dict[str, list[dict]] = {}
    for year in years:
        coins = []
        rows = conn.execute(
            "SELECT eurio_id, theme FROM coins "
            "WHERE country='BE' AND face_value=2.0 AND is_commemorative=1 AND year=? "
            "ORDER BY eurio_id",
            (int(year),),
        ).fetchall()
        for r in rows:
            i18n = {
                lr["lang"]: lr["title"]
                for lr in conn.execute(
                    "SELECT lang, title FROM coin_names_i18n WHERE eurio_id=?",
                    (r["eurio_id"],),
                ).fetchall()
            }
            coins.append({
                "eurio_id": r["eurio_id"],
                "theme": r["theme"],
                "i18n": {k: i18n[k] for k in I18N_LANGS if k in i18n},
            })
        groups_ctx[year] = coins

    summary = {
        "dry_run": dry_run,
        "years": {y: [c["eurio_id"] for c in cs] for y, cs in groups_ctx.items()},
        "missing_i18n": [
            c["eurio_id"] for cs in groups_ctx.values() for c in cs if not c["i18n"]
        ],
    }
    if not dry_run:
        GROUPS_PATH.write_text(json.dumps(groups_ctx, ensure_ascii=False, indent=2))
    return summary


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--db", type=Path, default=DEFAULT_DB)
    return ap.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    summary = regen(Store(args.db), dry_run=args.dry_run)
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
