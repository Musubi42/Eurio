#!/usr/bin/env python3
"""Construit le manifeste du staging de sauvegarde Eurio.

Le manifeste est l'unique contrat entre `eurio-backup.sh stage` (qui le produit)
et `verify_invariants.py` (qui le consomme). Il joue trois rôles :

1. **Sentinelle d'atomicité** — il est écrit EN DERNIER et porte le sha256 de
   chaque fichier qu'il décrit. Un fichier modifié après lui produit un écart de
   sha, donc un staging à moitié écrit est détecté au lieu d'être sauvegardé.
2. **Enregistrement d'intégrité** — sha256, `integrity_check`, violations de clés
   étrangères, au moment de la capture.
3. **Base de comparaison** — comptages par table, pour l'invariant de
   non-décroissance (cf. VERIFICATION.md §3, invariant 3).

Usage : build_manifest.py <staging_dir> [--minio-root DIR] [--t2 ISO8601]

Contrat détaillé : docs/work-in-progress/backup-pipeline/ARCHITECTURE.md §1
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import sqlite3
import sys

MANIFEST_SCHEMA = 1

# Tables dont la décroissance est une anomalie. Liste FIGÉE : l'ajout d'une
# entrée resserre la surveillance, le retrait la relâche — les deux sont des
# décisions, pas des détails. Cf. ROADMAP.md lot 2.
WATCHED = {
    "eurio.db": [
        "coins",
        "coin_names_i18n",
        "coin_descriptions_i18n",
        "coin_canonical_images",
        "coin_observations",
        "image_assets",
        "image_state_events",
        "image_asset_dino_predictions",
        "source_images",
        "source_image_runs",
        "review_queue",
        "consensus_verdicts",
        "listing_text_signals",
        "discovery_log",
        "mint_release_prices",
        "training_runs",
        "_schema_migrations",
    ],
    "review.db": ["review_items", "decisions", "reviewers", "meta"],
}


def sha256_of(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def utc_now() -> str:
    return dt.datetime.now(dt.UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def utc_of(epoch: float) -> str:
    return dt.datetime.fromtimestamp(epoch, dt.UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def describe_db(path: str, source: str, source_mtime: str | None) -> dict:
    """Ouvre la base EN LECTURE SEULE et en extrait tout ce que le verify compare."""
    con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        integrity = con.execute("pragma integrity_check").fetchone()[0]
        fk_violations = len(con.execute("pragma foreign_key_check").fetchall())
        user_version = con.execute("pragma user_version").fetchone()[0]
        tables = [
            r[0]
            for r in con.execute(
                "select name from sqlite_master "
                "where type='table' and name not like 'sqlite_%' order by name"
            )
        ]
        counts = {}
        for table in tables:
            counts[table] = con.execute(f'select count(*) from "{table}"').fetchone()[0]
        migrations = []
        if "_schema_migrations" in tables:
            migrations = [
                r[0] for r in con.execute("select filename from _schema_migrations order by filename")
            ]
    finally:
        con.close()

    return {
        "source": source,
        "source_mtime_utc": source_mtime,
        "size": os.path.getsize(path),
        "sha256": sha256_of(path),
        "integrity_check": integrity,
        "foreign_key_violations": fk_violations,
        "user_version": user_version,
        "table_count": len(tables),
        "migrations": migrations,
        "row_counts": counts,
        "watched": WATCHED.get(os.path.basename(path), []),
    }


def describe_minio(root: str) -> dict:
    """Inventaire du miroir MinIO : un bloc par bucket (objets + octets).

    Volontairement sans sha256 par objet — 34 000 hachages à chaque passe serait
    absurde. La vérification de contenu se fait par échantillonnage côté verify
    (invariant 6), ce qui couvre statistiquement le corpus sans le relire.
    """
    buckets = {}
    for name in sorted(os.listdir(root)):
        bucket_dir = os.path.join(root, name)
        if not os.path.isdir(bucket_dir):
            continue
        objects = 0
        total = 0
        for dirpath, _dirnames, filenames in os.walk(bucket_dir):
            for filename in filenames:
                objects += 1
                total += os.path.getsize(os.path.join(dirpath, filename))
        buckets[name] = {"objects": objects, "bytes": total}
    return buckets


def main() -> int:
    parser = argparse.ArgumentParser(description="Construit le manifeste du staging Eurio.")
    parser.add_argument("staging", help="Répertoire de staging")
    parser.add_argument("--minio-root", default=None, help="Répertoire du miroir MinIO (lot 3)")
    parser.add_argument("--t1", default=None, help="Horodatage ISO du snapshot des bases")
    parser.add_argument("--t2", default=None, help="Horodatage ISO de la fin du miroir MinIO")
    parser.add_argument(
        "--source-mtime",
        action="append",
        default=[],
        metavar="FICHIER=EPOCH",
        help="mtime de la source vivante, pour l'invariant de fraîcheur",
    )
    args = parser.parse_args()

    mtimes = {}
    for item in args.source_mtime:
        name, _, epoch = item.partition("=")
        if epoch:
            mtimes[name] = utc_of(float(epoch))

    sources = {
        "eurio.db": "eurio-api:/var/lib/eurio/eurio.db",
        "review.db": "eurio-review:/var/lib/eurio/review.db",
    }

    files = {}
    for name, source in sources.items():
        path = os.path.join(args.staging, name)
        if not os.path.exists(path):
            print(f"❌ absent du staging : {name}", file=sys.stderr)
            return 1
        files[name] = describe_db(path, source, mtimes.get(name))

    manifest = {
        "manifest_schema": MANIFEST_SCHEMA,
        "created_utc": utc_now(),
        "host": os.uname().nodename,
        "capture": {
            # t1 AVANT t2 : on capture le store référençant avant le store
            # référencé, pour que le décalage ne produise que des orphelins
            # (bénins) et jamais des dangling. Cf. DONNEES.md §3.
            "t1_databases_utc": args.t1,
            "t2_minio_utc": args.t2,
        },
        "files": files,
        "minio": describe_minio(args.minio_root) if args.minio_root else None,
    }

    # Écrit EN DERNIER par l'appelant : c'est la sentinelle du staging.
    with open(os.path.join(args.staging, "manifest.json"), "w") as fh:
        json.dump(manifest, fh, indent=2, ensure_ascii=False)
        fh.write("\n")

    for name, info in files.items():
        print(
            f"  {name:<12} {info['size']:>12} o  integrity={info['integrity_check']}  "
            f"fk={info['foreign_key_violations']}  tables={info['table_count']}"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
