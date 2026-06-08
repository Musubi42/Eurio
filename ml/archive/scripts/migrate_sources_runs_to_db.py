"""Migration one-shot : ``ml/state/sources_runs.json`` → ``source_runs`` table.

Acte la décision D-05 (decisions.md) : la source de vérité des runs par
source bascule de fichier JSON vers SQLite. Le JSON est conservé
en lecture seule pour audit historique, mais ``sources_runs.py`` est
déprécié — les nouveaux runs écrivent directement en DB via Store.

Usage::

    .venv/bin/python -m scripts.migrate_sources_runs_to_db
    .venv/bin/python -m scripts.migrate_sources_runs_to_db --dry-run

Idempotence : chaque entrée du JSON produit une row d'``id`` déterministe
``migrated:<source>:<last_run_at>``, ré-exécuter la migration ne crée pas
de doublons (INSERT OR IGNORE).

Limites assumées :
  - Le JSON n'a qu'un seul timestamp par source (``last_run_at``) ;
    on l'utilise pour ``started_at`` ET ``ended_at``, ce qui sous-estime
    la durée à 0s. Ce n'est pas un drame : l'audit pré-migration n'a
    jamais distingué les deux.
  - Le ``last_run_kind`` du JSON (``scrape``, ``batch_match``,
    ``enrich``, ``fetch``…) est mappé sur ``kind='run'`` (le seul kind
    "réel" du schéma) et conservé intégralement dans ``filters_json``
    sous la clé ``legacy_kind`` pour traçabilité.
  - ``last_run_added_coins`` est mappé sur ``n_raws_added`` (proxy le
    plus proche dans le nouveau schéma — un "coin ajouté" pré-refacto
    correspondait à un raw nouvellement ingéré).
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

# Permettre l'exécution depuis ``ml/`` ou ``Eurio/`` racine.
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from store import Store  # noqa: E402  (after sys.path tweak)

LOG = logging.getLogger("migrate_sources_runs")

DEFAULT_JSON = ROOT / "state" / "sources_runs.json"
DEFAULT_DB = ROOT / "state" / "eurio.db"


def migrate(json_path: Path, db_path: Path, *, dry_run: bool) -> dict:
    if not json_path.exists():
        LOG.warning("Pas de fichier %s — rien à migrer.", json_path)
        return {"inserted": 0, "skipped": 0, "total": 0}

    raw = json.loads(json_path.read_text())
    if not raw:
        LOG.info("Fichier %s vide — rien à migrer.", json_path)
        return {"inserted": 0, "skipped": 0, "total": 0}

    store = Store(db_path)
    conn = store._connection()  # noqa: SLF001 — usage interne légitime

    inserted = 0
    skipped = 0

    for source_id, payload in raw.items():
        last_run_at = payload.get("last_run_at")
        if not last_run_at:
            LOG.warning("Source %s : pas de last_run_at, skip.", source_id)
            skipped += 1
            continue

        legacy_kind = payload.get("last_run_kind") or "run"
        n_calls = int(payload.get("last_run_calls") or 0)
        n_added = int(payload.get("last_run_added_coins") or 0)

        run_id = f"migrated:{source_id}:{last_run_at}"
        filters_json = json.dumps(
            {"legacy_kind": legacy_kind, "migrated_from": "sources_runs.json"},
            ensure_ascii=False,
        )

        if dry_run:
            LOG.info(
                "[dry] %s — kind=%s calls=%d added=%d at=%s",
                source_id,
                legacy_kind,
                n_calls,
                n_added,
                last_run_at,
            )
            inserted += 1
            continue

        cursor = conn.execute(
            """
            INSERT OR IGNORE INTO source_runs (
                id, source, kind, started_at, ended_at, status,
                n_calls, n_raws_added, filters_json
            ) VALUES (?, ?, 'run', ?, ?, 'success', ?, ?, ?)
            """,
            (run_id, source_id, last_run_at, last_run_at, n_calls, n_added, filters_json),
        )
        if cursor.rowcount == 1:
            inserted += 1
            LOG.info("✓ %s migré (%s, +%d raws, %d calls)", source_id, legacy_kind, n_added, n_calls)
        else:
            skipped += 1
            LOG.info("· %s déjà migré, skip", source_id)

    return {"inserted": inserted, "skipped": skipped, "total": len(raw)}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", type=Path, default=DEFAULT_JSON, help="Chemin du JSON source")
    parser.add_argument("--db", type=Path, default=DEFAULT_DB, help="Chemin de la DB cible")
    parser.add_argument("--dry-run", action="store_true", help="N'écrit rien, log seulement")
    parser.add_argument("--verbose", "-v", action="store_true")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(message)s",
    )

    summary = migrate(args.json, args.db, dry_run=args.dry_run)
    LOG.info(
        "Migration %s : %d inséré · %d skipped · %d total",
        "dry-run" if args.dry_run else "OK",
        summary["inserted"],
        summary["skipped"],
        summary["total"],
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
