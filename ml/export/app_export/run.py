"""Entrypoint for the app-facing Supabase exporter (v2).

Usage::

    python -m export.app_export.run                  # dry-run (default)
    python -m export.app_export.run --apply          # push to Supabase
    python -m export.app_export.run --only coin      # one table, dry-run
    python -m export.app_export.run --apply --only mint

FK-safe table order (parents before children):

    design_group
    shared_reverse
    mint
    coin
    coin_mint_release
    coin_credit
    coin_topic
    coin_name_i18n
    coin_description_i18n
    coin_price

Sets tables (sets, set_members) are intentionally skipped — they are empty
in eurio.db and will be populated separately.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Callable

# Ensure ml/ is on sys.path when run as __main__ from the repo root.
_ML_ROOT = Path(__file__).resolve().parents[2]
if str(_ML_ROOT) not in sys.path:
    sys.path.insert(0, str(_ML_ROOT))

from export.app_export.io import delete_all, get_pg_client, get_sqlite_con, upsert  # noqa: E402

# ---------------------------------------------------------------------------
# FK-safe table order
# ---------------------------------------------------------------------------

TABLES = [
    "design_group",
    "shared_reverse",
    "mint",
    "coin",
    "coin_mint_release",
    "coin_credit",
    "coin_topic",
    "coin_name_i18n",
    "coin_description_i18n",
    "coin_price",
]

# Apply = full refresh : on vide chaque table (ordre FK inverse) puis on insère
# (ordre FK direct). Pattern projection idempotent — pas d'upsert, car les tables
# à PK surrogate (coin_credit, coin_topic, coin_price) n'ont pas de clé métier
# unique sur laquelle un ON CONFLICT pourrait s'appuyer.
#
# DELETE_COL = une colonne NOT NULL par table, pour le filtre PostgREST
# `<col>=not.is.null` qui matche toutes les lignes (DELETE exige un filtre).
DELETE_COL: dict[str, str] = {
    "design_group":           "id",
    "shared_reverse":         "id",
    "mint":                   "id",
    "coin":                   "eurio_id",
    "coin_mint_release":      "id",
    "coin_credit":            "id",
    "coin_topic":             "id",
    "coin_name_i18n":         "eurio_id",
    "coin_description_i18n":  "eurio_id",
    "coin_price":             "id",
}

# ---------------------------------------------------------------------------
# Builder registry — populated lazily via try-imports below.
# Each builder: (sqlite3.Connection) -> list[dict]
# ---------------------------------------------------------------------------

BuilderFn = Callable[..., list[dict]]

_BUILDERS: dict[str, BuilderFn | None] = {t: None for t in TABLES}

# Tables dont le builder module a échoué à l'IMPORT (dépendance manquante, import
# circulaire, typo dans un import transitif…). Distinct d'un builder simplement
# pas encore écrit : ici le module EXISTE mais casse — on doit le voir, pas l'avaler
# en "skipped". Voir run() qui transforme ça en exit_code=1.
_IMPORT_FAILED: dict[str, str] = {}

# Domain builders live in consolidated modules (one module per domain, not per
# table).  We import from the actual files produced by the domain agents.

# --- coin.py: build_coin + build_shared_reverse ---
try:
    from export.app_export.builders.coin import build_coin, build_shared_reverse
    _BUILDERS["coin"] = build_coin
    _BUILDERS["shared_reverse"] = build_shared_reverse
except ImportError as exc:
    for _t in ("coin", "shared_reverse"):
        _IMPORT_FAILED[_t] = str(exc)

# --- relational.py: build_design_group, build_mint, build_coin_mint_release,
#                    build_coin_credit, build_coin_topic ---
try:
    from export.app_export.builders.relational import (
        build_design_group,
        build_mint,
        build_coin_mint_release,
        build_coin_credit,
        build_coin_topic,
    )
    _BUILDERS["design_group"] = build_design_group
    _BUILDERS["mint"] = build_mint
    _BUILDERS["coin_mint_release"] = build_coin_mint_release
    _BUILDERS["coin_credit"] = build_coin_credit
    _BUILDERS["coin_topic"] = build_coin_topic
except ImportError as exc:
    for _t in ("design_group", "mint", "coin_mint_release", "coin_credit", "coin_topic"):
        _IMPORT_FAILED[_t] = str(exc)

# --- i18n.py: build_coin_name_i18n + build_coin_description_i18n ---
try:
    from export.app_export.builders.i18n import (
        build_coin_name_i18n,
        build_coin_description_i18n,
    )
    _BUILDERS["coin_name_i18n"] = build_coin_name_i18n
    _BUILDERS["coin_description_i18n"] = build_coin_description_i18n
except ImportError as exc:
    for _t in ("coin_name_i18n", "coin_description_i18n"):
        _IMPORT_FAILED[_t] = str(exc)

# --- coin_price.py: build_coin_price ---
try:
    from export.app_export.builders.coin_price import build_coin_price
    _BUILDERS["coin_price"] = build_coin_price
except ImportError as exc:
    _IMPORT_FAILED["coin_price"] = str(exc)


# ---------------------------------------------------------------------------
# Core logic
# ---------------------------------------------------------------------------

def run(apply: bool, only: str | None) -> int:
    """Build rows from eurio.db and either print (dry-run) or upsert (apply).

    Returns an exit code: 0 = success, 1 = one or more builders failed.
    """
    from export.app_export.io import announce_source

    announce_source()
    tables = [only] if only else TABLES
    for t in tables:
        if t not in TABLES:
            print(f"ERROR: unknown table '{t}'. Valid: {', '.join(TABLES)}", file=sys.stderr)
            return 1

    con = get_sqlite_con()
    pg = get_pg_client() if apply else None

    exit_code = 0
    try:
        # Build every table's rows first (pure, no side effects), so a build
        # error aborts before we touch Supabase.
        built: dict[str, list[dict]] = {}
        for table in tables:
            builder = _BUILDERS.get(table)
            if builder is None:
                if table in _IMPORT_FAILED:
                    # Le module builder existe mais casse à l'import : NE PAS traiter comme
                    # un skip normal — sinon la table n'est jamais rafraîchie en silence.
                    print(f"  {table}: BUILDER IMPORT ERROR — {_IMPORT_FAILED[table]}",
                          file=sys.stderr)
                    exit_code = 1
                else:
                    print(f"  {table}: [skipped — builder not implemented yet]")
                continue
            try:
                built[table] = builder(con)
            except Exception as exc:
                print(f"  {table}: BUILD ERROR — {exc}", file=sys.stderr)
                exit_code = 1

        if exit_code:
            return exit_code

        if not apply:
            for table in tables:
                if table not in built:
                    continue
                rows = built[table]
                sample = json.dumps(rows[0], ensure_ascii=False, default=str) if rows else "—"
                print(f"  {table}: {len(rows)} rows  sample={sample[:120]}")
            return 0

        # Full refresh: delete in reverse FK order, then insert in FK order.
        for table in reversed(tables):
            if table in built:
                delete_all(pg, table, DELETE_COL[table])
        for table in tables:
            if table not in built:
                continue
            rows = built[table]
            upsert(pg, table, rows)
            print(f"  {table}: {len(rows)} rows upserted")
    finally:
        con.close()
        if pg is not None:
            pg.close()

    return exit_code


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(
        description="Export eurio.db to Supabase app-facing schema (v2).",
    )
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument(
        "--apply",
        action="store_true",
        default=False,
        help="Push rows to Supabase (default: dry-run, print counts only).",
    )
    mode.add_argument(
        "--dry-run",
        action="store_true",
        default=False,
        help="Print row counts and a sample row per table (default behaviour).",
    )
    ap.add_argument(
        "--only",
        metavar="TABLE",
        default=None,
        help=f"Process a single table. One of: {', '.join(TABLES)}.",
    )
    return ap.parse_args()


def main() -> int:
    args = parse_args()
    apply = args.apply
    mode_label = "apply" if apply else "dry-run"
    only_label = f" (only: {args.only})" if args.only else ""
    print(f"[{mode_label}]{only_label}")
    return run(apply=apply, only=args.only)


if __name__ == "__main__":
    sys.exit(main())
