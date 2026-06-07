"""Port des `design_groups` Supabase → `eurio.db` — Chunk 3.

Harmonisation des données (docs/data-harmonization/).

Les `design_groups` (groupes de design partagé — unité de classe ArcFace) ont
été bootstrappés *dans Supabase* (`referential/bootstrap_design_groups_2eur.py`).
Or l'architecture pose `eurio.db` comme canonique : ce script rapatrie la table
et les affectations `coins.design_group_id` dans `eurio.db`.

C'est aussi le prérequis du recalcul du cycle de vie (`recompute_coin_status`) :
une pièce est `trained` notamment quand son `design_group` a été entraîné.

Tolérant aux orphelins : une affectation Supabase dont l'`eurio_id` n'existe
pas dans `eurio.db` (référentiels désormais divergents) est loguée, pas posée.
Idempotent.

Usage::

    python -m scripts.port_design_groups --dry-run
    python -m scripts.port_design_groups
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

from serving.supabase_client import SupabaseClient, load_env  # noqa: E402
from store import Store  # noqa: E402

DEFAULT_DB = ROOT / "state" / "eurio.db"


def port(store: Store, *, dry_run: bool) -> dict:
    env = load_env()
    url, key = env.get("SUPABASE_URL"), env.get("SUPABASE_SERVICE_ROLE_KEY")
    if not url or not key:
        raise SystemExit("SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY manquants")
    sb = SupabaseClient(url, key)

    groups = sb.query(
        "design_groups",
        select="id,designation,designation_i18n,description,shared_obverse_url",
    )
    assignments = sb.query(
        "coins", select="eurio_id,design_group_id", params={"design_group_id": "not.is.null"}
    )
    sb.close()

    conn = store._connection()  # noqa: SLF001
    known_coins = {r[0] for r in conn.execute("SELECT eurio_id FROM coins")}
    known_groups = {g["id"] for g in groups}

    matched = [a for a in assignments if a["eurio_id"] in known_coins]
    orphans = [
        a for a in assignments
        if a["eurio_id"] not in known_coins or a["design_group_id"] not in known_groups
    ]

    summary = {
        "dry_run": dry_run,
        "design_groups": len(groups),
        "assignments_supabase": len(assignments),
        "assignments_applicable": len(matched),
        "assignments_orphan": len(orphans),
        "orphan_sample": orphans[:15],
    }
    if dry_run:
        return summary

    now = datetime.now(timezone.utc).isoformat()
    group_rows = [
        (
            g["id"], g["designation"],
            json.dumps(g["designation_i18n"], ensure_ascii=False) if g.get("designation_i18n") else None,
            g.get("description"), g.get("shared_obverse_url"), now, now,
        )
        for g in groups
    ]

    conn.execute("BEGIN")
    try:
        conn.executemany(
            "INSERT OR REPLACE INTO design_groups "
            "(id, designation, designation_i18n_json, description, shared_obverse_url, "
            " created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            group_rows,
        )
        # Reset puis ré-affecte — le recalcul du statut doit refléter l'état Supabase.
        conn.execute("UPDATE coins SET design_group_id=NULL WHERE design_group_id IS NOT NULL")
        conn.executemany(
            "UPDATE coins SET design_group_id=? WHERE eurio_id=?",
            [(a["design_group_id"], a["eurio_id"]) for a in matched],
        )
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise

    summary["coins_assigned"] = conn.execute(
        "SELECT count(*) AS n FROM coins WHERE design_group_id IS NOT NULL"
    ).fetchone()["n"]
    return summary


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--db", type=Path, default=DEFAULT_DB)
    return ap.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    store = Store(args.db)
    summary = port(store, dry_run=args.dry_run)
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
