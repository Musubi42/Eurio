"""Migration de données — Chunk 1b, harmonisation des données.

⚠️ DEPRECATED (P.3b 2026-05-25). Ce script lit ``coins.raw_payload_json``
qui sera droppé post-wipe (P.6). Il écrit aussi dans ``coin_observations``
avec des valeurs ``source`` libres (legacy : 'wikipedia', 'lmdlp_variants',
'mdp_issue', etc.) qui violeront la FK source_registry post-recreate.

À ne PAS re-jouer après P.6. Conservé en lecture pour traçabilité ; sera
archivé sous ``scripts/_legacy/`` en P.9.

Voir docs/data-harmonization/{architecture,schema-design,plan}.md.

Le SCHÉMA (colonnes canoniques de `coins`, tables filles, index) est posé
par ``Store._bootstrap`` — ce script ne fait que de la **donnée** :

  1. Backfille les colonnes canoniques de ``coins`` depuis ``raw_payload_json``
     (ref_source/ref_native_id, currency, collector_only, design_description,
     mintage, needs_review, review_reason, updated_at).
  2. Remplit les tables filles depuis le même blob : ``coin_cross_refs``,
     ``coin_observations``, ``coin_canonical_images``, ``coin_national_variants``.
  3. Backfille ``cohort_members`` depuis ``experiment_cohorts.eurio_ids_json``
     (tolère les eurio_id orphelins — cohorte gelée pointant une pièce
     disparue → logué, pas inséré).
  4. Pose ``image_assets.origin = 'collected'`` sur les images existantes.

Idempotent et re-jouable. ``raw_payload_json`` n'est PAS supprimé (transitoire).

Usage::

    python -m scripts.migrate_canonical_schema --dry-run
    python -m scripts.migrate_canonical_schema
"""

from __future__ import annotations

import argparse
import json
import shutil
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from store import Store  # noqa: E402

DEFAULT_DB = ROOT / "state" / "eurio.db"


def backup_db(db_path: Path) -> Path:
    """Checkpoint WAL puis copie horodatée du fichier .db."""
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    conn.close()
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    dst = db_path.with_name(f"{db_path.name}.bak-premigration-{ts}")
    shutil.copy2(db_path, dst)
    return dst


def _as_text(value: object) -> str:
    """Une valeur de cross_ref en TEXT : str tel quel, sinon JSON."""
    return value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)


def _coin_updates(payload: dict) -> dict:
    """Colonnes canoniques de `coins` dérivées du blob référentiel."""
    ident = payload.get("identity") or {}
    prov = payload.get("provenance") or {}
    cross = payload.get("cross_refs") or {}
    nid = cross.get("numista_id")
    mintage = ident.get("mintage")
    mintage = mintage if isinstance(mintage, int) and mintage > 0 else None
    return {
        "ref_source": "numista" if nid is not None else None,
        "ref_native_id": str(nid) if nid is not None else None,
        "currency": ident.get("currency") or "EUR",
        "collector_only": 1 if ident.get("collector_only") else 0,
        "design_description": ident.get("design_description"),
        "mintage": mintage,
        "mintage_source": "numista" if mintage is not None else None,
        "needs_review": 1 if prov.get("needs_review") else 0,
        "review_reason": prov.get("review_reason"),
        "updated_at": prov.get("last_updated"),
    }


def _child_rows(eurio_id: str, payload: dict) -> dict[str, list[tuple]]:
    """Lignes des tables filles décomposées du blob."""
    cross = payload.get("cross_refs") or {}
    obs = payload.get("observations") or {}
    images = payload.get("images")
    ident = payload.get("identity") or {}

    cross_refs = [
        (eurio_id, k, _as_text(v))
        for k, v in cross.items()
        if k != "numista_id" and v is not None
    ]
    observations = [
        (eurio_id, src, "legacy_import", json.dumps(val, ensure_ascii=False))
        for src, val in obs.items()
        if val is not None
    ]

    canonical_images: list[tuple] = []
    # `images` historiquement : dict {obverse, obverse_source, …} OU liste de
    # dicts {role, url, source}. On gère les deux, on ignore le reste.
    if isinstance(images, dict):
        for role in ("obverse", "reverse"):
            url = images.get(role)
            if url:
                canonical_images.append(
                    (eurio_id, images.get(f"{role}_source") or "unknown", role, url, None)
                )
    elif isinstance(images, list):
        for item in images:
            if not isinstance(item, dict):
                continue
            role = item.get("role")
            url = item.get("url")
            if role in ("obverse", "reverse") and url:
                canonical_images.append(
                    (eurio_id, item.get("source") or "unknown", role, url, None)
                )

    variants = ident.get("national_variants") or []
    national_variants = [
        (eurio_id, iso2) for iso2 in variants if isinstance(iso2, str)
    ]
    return {
        "coin_cross_refs": cross_refs,
        "coin_observations": observations,
        "coin_canonical_images": canonical_images,
        "coin_national_variants": national_variants,
    }


def migrate(conn: sqlite3.Connection, *, dry_run: bool) -> dict:
    summary: dict = {
        "dry_run": dry_run,
        "coins_total": 0,
        "coins_backfilled": 0,
        "coins_no_payload": 0,
        "coins_with_numista": 0,
        "coin_cross_refs": 0,
        "coin_observations": 0,
        "coin_canonical_images": 0,
        "coin_national_variants": 0,
        "cohort_members": 0,
        "cohort_orphans": [],
        "image_assets_origin_set": 0,
        "fk_violations": 0,
    }

    coins = conn.execute(
        "SELECT eurio_id, numista_id, raw_payload_json FROM coins"
    ).fetchall()
    summary["coins_total"] = len(coins)

    child_totals = {
        "coin_cross_refs": [],
        "coin_observations": [],
        "coin_canonical_images": [],
        "coin_national_variants": [],
    }
    coin_updates: list[tuple] = []

    for row in coins:
        eurio_id = row["eurio_id"]
        raw = row["raw_payload_json"]
        if not raw:
            summary["coins_no_payload"] += 1
            continue
        try:
            payload = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            summary["coins_no_payload"] += 1
            continue

        upd = _coin_updates(payload)
        if upd["ref_source"] == "numista":
            summary["coins_with_numista"] += 1
        coin_updates.append(
            (
                upd["ref_source"], upd["ref_native_id"], upd["currency"],
                upd["collector_only"], upd["design_description"], upd["mintage"],
                upd["mintage_source"], upd["needs_review"], upd["review_reason"],
                upd["updated_at"], eurio_id,
            )
        )
        summary["coins_backfilled"] += 1

        for table, rows in _child_rows(eurio_id, payload).items():
            child_totals[table].extend(rows)

    for table, rows in child_totals.items():
        summary[table] = len(rows)

    # ── cohort_members ────────────────────────────────────────────────────
    coin_ids = {r["eurio_id"] for r in coins}
    cohort_rows: list[tuple] = []
    for c in conn.execute(
        "SELECT id, name, eurio_ids_json FROM experiment_cohorts"
    ).fetchall():
        try:
            members = json.loads(c["eurio_ids_json"] or "[]")
        except (json.JSONDecodeError, TypeError):
            members = []
        for eid in members:
            if eid in coin_ids:
                cohort_rows.append((c["id"], eid))
            else:
                summary["cohort_orphans"].append(
                    {"cohort": c["name"], "eurio_id": eid}
                )
    summary["cohort_members"] = len(cohort_rows)

    n_origin = conn.execute(
        "SELECT count(*) AS n FROM image_assets WHERE origin IS NULL"
    ).fetchone()["n"]
    summary["image_assets_origin_set"] = n_origin

    if dry_run:
        return summary

    # ── écritures (transaction) ───────────────────────────────────────────
    conn.execute("BEGIN")
    try:
        conn.executemany(
            "UPDATE coins SET ref_source=?, ref_native_id=?, currency=?, "
            "collector_only=?, design_description=?, mintage=?, mintage_source=?, "
            "needs_review=?, review_reason=?, updated_at=? WHERE eurio_id=?",
            coin_updates,
        )
        conn.executemany(
            "INSERT OR REPLACE INTO coin_cross_refs (eurio_id, ref_type, ref_value) "
            "VALUES (?, ?, ?)",
            child_totals["coin_cross_refs"],
        )
        conn.executemany(
            "INSERT OR REPLACE INTO coin_observations "
            "(eurio_id, source, observation_type, payload_json) VALUES (?, ?, ?, ?)",
            child_totals["coin_observations"],
        )
        conn.executemany(
            "INSERT OR REPLACE INTO coin_canonical_images "
            "(eurio_id, source, role, url, local_path) VALUES (?, ?, ?, ?, ?)",
            child_totals["coin_canonical_images"],
        )
        conn.executemany(
            "INSERT OR IGNORE INTO coin_national_variants (eurio_id, country_iso2) "
            "VALUES (?, ?)",
            child_totals["coin_national_variants"],
        )
        conn.executemany(
            "INSERT OR IGNORE INTO cohort_members (cohort_id, eurio_id) VALUES (?, ?)",
            cohort_rows,
        )
        conn.execute(
            "UPDATE image_assets SET origin='collected' WHERE origin IS NULL"
        )
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise

    violations = conn.execute("PRAGMA foreign_key_check").fetchall()
    summary["fk_violations"] = len(violations)
    if violations:
        summary["fk_violation_sample"] = [tuple(v) for v in violations[:10]]
    return summary


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dry-run", action="store_true", help="Aucune écriture, affiche le plan.")
    ap.add_argument("--db", type=Path, default=DEFAULT_DB, help="Chemin DB.")
    return ap.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if not args.db.is_file():
        print(f"ERREUR : DB introuvable : {args.db}", file=sys.stderr)
        return 2

    if not args.dry_run:
        backup = backup_db(args.db)
        print(f"Backup : {backup.name}")

    # Store._bootstrap pose le schéma (colonnes, tables filles, index).
    store = Store(args.db)
    conn = store._connection()  # noqa: SLF001

    summary = migrate(conn, dry_run=args.dry_run)
    print(json.dumps(summary, indent=2, ensure_ascii=False))

    if summary["fk_violations"]:
        print("\n⚠️  Violations FK détectées — voir fk_violation_sample.", file=sys.stderr)
        return 1
    mode = "dry-run — rien écrit" if args.dry_run else "migration appliquée"
    print(f"\n✅ {mode}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
