"""Migration one-shot Supabase → eurio.db SQLite pour les 2 tables orphelines.

Usage (depuis le container eurio-api) :

    docker exec eurio-api python -m serving.migrate_orphan_supabase \\
        --table coin_confusion_map
    docker exec eurio-api python -m serving.migrate_orphan_supabase \\
        --table sets_audit
    docker exec eurio-api python -m serving.migrate_orphan_supabase --all

Idempotent : utilise ``INSERT OR REPLACE`` (clé conflit = ``id`` pour
``sets_audit``, ``(eurio_id, encoder_version)`` pour ``coin_confusion_map``).
Imprime un récap row-count source vs cible à la fin.

Source : Supabase via PostgREST (anon key suffit pour SELECT, RLS = public read).
Cible : ``eurio.db`` SQLite via path env ``EURIO_DB_PATH``.

Cf. ``docs/work-in-progress/data-layer-unification/IMPLEMENTATION.md`` §1.3.
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
import urllib.parse
import urllib.request
from pathlib import Path

_PAGE_SIZE = 1000

_TABLES = {
    "coin_confusion_map": {
        "select": (
            "id,eurio_id,encoder_version,nearest_eurio_id,nearest_similarity,"
            "top_k_neighbors,zone,computed_at"
        ),
        "order": "id.asc",
        "jsonb_cols": {"top_k_neighbors"},
        "insert_sql": (
            "INSERT OR REPLACE INTO coin_confusion_map"
            "(id, eurio_id, encoder_version, nearest_eurio_id,"
            " nearest_similarity, top_k_neighbors, zone, computed_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)"
        ),
        "columns": [
            "id", "eurio_id", "encoder_version", "nearest_eurio_id",
            "nearest_similarity", "top_k_neighbors", "zone", "computed_at",
        ],
    },
    "sets_audit": {
        "select": "id,set_id,action,before,after,actor,at",
        "order": "id.asc",
        "jsonb_cols": {"before", "after"},
        "insert_sql": (
            "INSERT OR REPLACE INTO sets_audit"
            "(id, set_id, action, before, after, actor, at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)"
        ),
        "columns": ["id", "set_id", "action", "before", "after", "actor", "at"],
    },
}


def _supabase_url() -> str:
    url = os.environ.get("SUPABASE_URL", "").rstrip("/")
    if not url:
        sys.exit("ERREUR : SUPABASE_URL non défini (vérifier direnv / sops)")
    return url


def _supabase_key() -> str:
    """Service-role key préférée (ignore RLS), fallback anon."""
    key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "").strip()
    if not key:
        key = os.environ.get("SUPABASE_ANON_KEY", "").strip()
    if not key:
        sys.exit(
            "ERREUR : ni SUPABASE_SERVICE_ROLE_KEY ni SUPABASE_ANON_KEY "
            "défini"
        )
    return key


def _db_path() -> Path:
    return Path(os.environ.get("EURIO_DB_PATH", "/var/lib/eurio/eurio.db"))


def _fetch_page(
    table: str, select: str, order: str, offset: int, limit: int
) -> list[dict]:
    """Fetch one page via Postgrest. Returns parsed JSON array."""
    base = _supabase_url()
    key = _supabase_key()
    params = urllib.parse.urlencode(
        {"select": select, "order": order, "limit": limit, "offset": offset}
    )
    url = f"{base}/rest/v1/{table}?{params}"
    req = urllib.request.Request(
        url,
        headers={
            "apikey": key,
            "Authorization": f"Bearer {key}",
            "Accept": "application/json",
        },
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        body = resp.read().decode("utf-8")
    return json.loads(body)


def _supabase_count(table: str) -> int:
    """HEAD request avec Prefer: count=exact pour récupérer le total."""
    base = _supabase_url()
    key = _supabase_key()
    url = f"{base}/rest/v1/{table}?select=id"
    req = urllib.request.Request(
        url,
        method="HEAD",
        headers={
            "apikey": key,
            "Authorization": f"Bearer {key}",
            "Prefer": "count=exact",
            "Range-Unit": "items",
            "Range": "0-0",
        },
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        cr = resp.headers.get("Content-Range", "")  # ex: "0-0/1500"
    if "/" not in cr:
        return -1
    try:
        return int(cr.rsplit("/", 1)[1])
    except ValueError:
        return -1


def _row_to_sqlite_params(row: dict, spec: dict) -> tuple:
    out: list = []
    for col in spec["columns"]:
        v = row.get(col)
        if col in spec["jsonb_cols"] and v is not None and not isinstance(v, str):
            v = json.dumps(v, separators=(",", ":"))
        out.append(v)
    return tuple(out)


def migrate_table(table: str) -> int:
    spec = _TABLES[table]
    src_count = _supabase_count(table)
    if src_count < 0:
        print(f"[{table}] WARN : count Supabase indisponible (sans Content-Range)")
    else:
        print(f"[{table}] Supabase count : {src_count}")

    conn = sqlite3.connect(str(_db_path()))
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        offset = 0
        total = 0
        while True:
            page = _fetch_page(
                table, spec["select"], spec["order"], offset, _PAGE_SIZE
            )
            if not page:
                break
            cur = conn.cursor()
            cur.executemany(
                spec["insert_sql"],
                [_row_to_sqlite_params(r, spec) for r in page],
            )
            conn.commit()
            total += len(page)
            print(f"[{table}]   page offset={offset:>6} → +{len(page)} (total {total})")
            if len(page) < _PAGE_SIZE:
                break
            offset += _PAGE_SIZE

        dst = conn.execute(f'SELECT count(*) FROM "{table}"').fetchone()[0]
    finally:
        conn.close()

    print(f"[{table}] SQLite count : {dst}")
    if src_count >= 0 and src_count != dst:
        print(
            f"[{table}] ⚠ DIVERGE — Supabase={src_count} vs SQLite={dst}. "
            "Vérifier ON CONFLICT / RLS."
        )
    else:
        print(f"[{table}] ✅ OK")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="serving.migrate_orphan_supabase")
    grp = parser.add_mutually_exclusive_group(required=True)
    grp.add_argument("--table", choices=sorted(_TABLES.keys()))
    grp.add_argument("--all", action="store_true", help="migre toutes les tables")
    args = parser.parse_args(argv)

    if args.all:
        for t in _TABLES:
            migrate_table(t)
    else:
        migrate_table(args.table)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
