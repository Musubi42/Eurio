"""Détection de dérive `eurio.db` ↔ Supabase — Chunk 4.

Compare le canonique (eurio.db) à sa projection app (Supabase) et remonte les
écarts. Lecture seule, idempotent, à invoquer après un sync ou en CI.

Trois écarts remontés :

  - **supabase_only** : `eurio_id` présent côté Supabase, absent côté
    eurio.db. Typiquement : un slug pré-Chunk-2 jamais nettoyé (la sync ne
    supprime jamais — architecture R0).
  - **eurio_only**    : `eurio_id` côté eurio.db jamais poussé. Devrait être
    vide après un `sync-supabase` propre.
  - **field_drift**   : `eurio_id` présent des deux côtés mais avec un
    `theme` / `design_group_id` divergent (spot-check sur un échantillon).

Usage::

    python -m scripts.detect_supabase_drift
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from export.sync_to_supabase import PostgrestClient, load_env  # noqa: E402
from state.store import Store  # noqa: E402

DEFAULT_DB = ROOT / "state" / "eurio.db"
PAGE = 1000


def _fetch_all(client: PostgrestClient, table: str, select: str) -> list[dict]:
    out: list[dict] = []
    offset = 0
    while True:
        params = {"select": select, "limit": str(PAGE), "offset": str(offset)}
        rows = client.get(table, params)
        out.extend(rows)
        if len(rows) < PAGE:
            break
        offset += PAGE
    return out


def detect(store: Store, *, sample_drift: int = 50) -> dict:
    env = load_env()
    url, key = env.get("SUPABASE_URL"), env.get("SUPABASE_SERVICE_ROLE_KEY")
    if not url or not key:
        raise SystemExit("SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY manquants")

    with PostgrestClient(url, key) as client:
        sb_coins = _fetch_all(client, "coins", "eurio_id,theme,design_group_id")

    sb_by_eid = {r["eurio_id"]: r for r in sb_coins}
    conn = store._connection()  # noqa: SLF001
    db_by_eid: dict[str, dict] = {}
    for r in conn.execute("SELECT eurio_id, theme, design_group_id FROM coins"):
        db_by_eid[r["eurio_id"]] = {
            "eurio_id": r["eurio_id"],
            "theme": r["theme"],
            "design_group_id": r["design_group_id"],
        }

    db_ids, sb_ids = set(db_by_eid), set(sb_by_eid)
    supabase_only = sorted(sb_ids - db_ids)
    eurio_only = sorted(db_ids - sb_ids)

    field_drift: list[dict] = []
    common = sorted(db_ids & sb_ids)
    for eid in common:
        d, s = db_by_eid[eid], sb_by_eid[eid]
        diffs = {k: {"db": d.get(k), "supabase": s.get(k)}
                 for k in ("theme", "design_group_id") if d.get(k) != s.get(k)}
        if diffs:
            field_drift.append({"eurio_id": eid, "diffs": diffs})

    return {
        "n_eurio_db": len(db_ids),
        "n_supabase": len(sb_ids),
        "n_common": len(common),
        "supabase_only": {
            "count": len(supabase_only),
            "sample": supabase_only[:sample_drift],
        },
        "eurio_only": {
            "count": len(eurio_only),
            "sample": eurio_only[:sample_drift],
        },
        "field_drift": {
            "count": len(field_drift),
            "sample": field_drift[:sample_drift],
        },
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--db", type=Path, default=DEFAULT_DB)
    ap.add_argument("--sample", type=int, default=50)
    args = ap.parse_args()
    report = detect(Store(args.db), sample_drift=args.sample)

    print(json.dumps(
        {k: v if not isinstance(v, dict) else {**v, "sample": v["sample"][:10]}
         for k, v in report.items()},
        indent=2, ensure_ascii=False,
    ))
    exit_code = 1 if report["eurio_only"]["count"] or report["field_drift"]["count"] else 0
    if exit_code:
        print("\n⚠️  Dérive détectée (eurio.db a des entrées non synchronisées "
              "ou des champs divergents). Lance `go-task ml:sync-supabase`.")
    elif report["supabase_only"]["count"]:
        print(f"\nℹ️  {report['supabase_only']['count']} entrées orphelines côté "
              "Supabase (legacy non-nettoyés). Cf. plan.md.")
    else:
        print("\n✅ Aucune dérive.")
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
