"""Recalcul du cycle de vie `coins.status` — Chunk 3, harmonisation des données.

Voir docs/data-harmonization/{architecture,plan}.md.

`status` est **matérialisé** mais sa vérité est une **dérivation** :

    referenced  →  une pièce du référentiel, connue.
    trained     →  le modèle sait la reconnaître.

Une pièce est `trained` si elle a servi de classe dans un run d'entraînement
**réussi** (`training_runs.status='completed'`), soit directement
(`class_kind='eurio_id'`), soit via son `design_group`
(`class_kind='design_group_id'` → on expanse vers les pièces membres).

Re-dérivation **totale** et idempotente : peut promouvoir `referenced→trained`
*et* rétrograder `trained→referenced` si une pièce n'est plus couverte par
aucun run réussi. À déclencher sur événement (fin de run, sync).

Usage::

    python -m scripts.recompute_coin_status --dry-run
    python -m scripts.recompute_coin_status
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from store import Store  # noqa: E402

DEFAULT_DB = ROOT / "state" / "eurio.db"


def _trained_eurio_ids(conn: sqlite3.Connection) -> tuple[set[str], dict]:
    """Ensemble des eurio_id `trained` + ventilation pour le rapport."""
    direct = {
        r[0] for r in conn.execute(
            "SELECT DISTINCT trc.class_id "
            "FROM training_run_classes trc JOIN training_runs tr ON tr.id=trc.run_id "
            "WHERE tr.status='completed' AND trc.class_kind='eurio_id'"
        )
    }
    trained_groups = {
        r[0] for r in conn.execute(
            "SELECT DISTINCT trc.class_id "
            "FROM training_run_classes trc JOIN training_runs tr ON tr.id=trc.run_id "
            "WHERE tr.status='completed' AND trc.class_kind='design_group_id'"
        )
    }
    via_group: set[str] = set()
    if trained_groups:
        ph = ",".join("?" * len(trained_groups))
        via_group = {
            r[0] for r in conn.execute(
                f"SELECT eurio_id FROM coins WHERE design_group_id IN ({ph})",
                tuple(trained_groups),
            )
        }
    all_coins = {r[0] for r in conn.execute("SELECT eurio_id FROM coins")}
    direct &= all_coins  # une classe peut référencer un eurio_id disparu
    trained = direct | via_group
    stats = {
        "completed_runs": conn.execute(
            "SELECT count(*) FROM training_runs WHERE status='completed'"
        ).fetchone()[0],
        "trained_design_groups": len(trained_groups),
        "trained_via_eurio_id_class": len(direct),
        "trained_via_design_group": len(via_group),
        "trained_total": len(trained),
    }
    return trained, stats


def recompute(conn: sqlite3.Connection, *, dry_run: bool) -> dict:
    trained, stats = _trained_eurio_ids(conn)
    before = dict(conn.execute("SELECT status, count(*) FROM coins GROUP BY status"))

    cur = {r[0]: r[1] for r in conn.execute("SELECT eurio_id, status FROM coins")}
    to_promote = [e for e, s in cur.items() if e in trained and s != "trained"]
    to_demote = [e for e, s in cur.items() if e not in trained and s != "referenced"]

    summary = {
        "dry_run": dry_run,
        **stats,
        "status_before": before,
        "to_promote": len(to_promote),
        "to_demote": len(to_demote),
    }
    if dry_run:
        return summary

    now = datetime.now(timezone.utc).isoformat()
    conn.execute("BEGIN")
    try:
        conn.executemany(
            "UPDATE coins SET status='trained', status_computed_at=? WHERE eurio_id=?",
            [(now, e) for e in to_promote],
        )
        conn.executemany(
            "UPDATE coins SET status='referenced', status_computed_at=? WHERE eurio_id=?",
            [(now, e) for e in to_demote],
        )
        # status_computed_at sur tout le monde : le recalcul a bien tourné.
        conn.execute(
            "UPDATE coins SET status_computed_at=? WHERE status_computed_at IS NULL",
            (now,),
        )
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise

    summary["status_after"] = dict(
        conn.execute("SELECT status, count(*) FROM coins GROUP BY status")
    )
    return summary


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--db", type=Path, default=DEFAULT_DB)
    return ap.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    store = Store(args.db)
    summary = recompute(store._connection(), dry_run=args.dry_run)  # noqa: SLF001
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    print(f"\n✅ {'dry-run' if args.dry_run else 'statut recalculé'}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
