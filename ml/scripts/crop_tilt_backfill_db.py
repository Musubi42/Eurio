"""Backfill des colonnes de tilt (tilt_deg, axis_ratio, tilt_trustworthy) directement
dans ``image_assets`` d'eurio.db (chantier crop-quality-overhaul — Chunk 1b).

Contrairement à ``crop_tilt_backfill.py`` qui écrit dans ``results.csv``, ce script
écrit directement en base, ce qui permet :
  - le tri « tilt_desc » dans /crop-bench sans dépendre du CSV de diagnostic,
  - la persistance permanente des mesures pour le pipeline de review.

Itère uniquement les assets eBay présents (source_images.source = 'ebay',
storage_status = 'present' pour les deux tables). Passe les assets dont l'image
raw est absente du cache local (pas d'erreur — comptabilisé dans les stats).

La mesure est IDENTIQUE à celle du banc /sample et à crop_tilt_backfill.py :
  _oracle_from_raw(bgr, bbox_json) → hint → measure_tilt(bgr, hint)

Usage :
    cd ml
    .venv/bin/python -m scripts.crop_tilt_backfill_db           # dry-run (affiche stats)
    .venv/bin/python -m scripts.crop_tilt_backfill_db --commit  # écrit en DB
    .venv/bin/python -m scripts.crop_tilt_backfill_db --commit --limit 5  # test rapide
    .venv/bin/python -m scripts.crop_tilt_backfill_db --commit --force    # recalcule tout
"""
from __future__ import annotations

import argparse
import sqlite3
import sys
import time
from pathlib import Path

import cv2

_ML = Path(__file__).resolve().parents[1]
if str(_ML) not in sys.path:
    sys.path.insert(0, str(_ML))

from scan.crop_detectors import measure_tilt  # noqa: E402
from scripts.crop_quality_diag import _oracle_from_raw, _raw_local_path  # noqa: E402

_DB = _ML / "state" / "eurio.db"

# Requête des assets eBay présents (même logique que _asset_map dans crop_bench_routes.py).
_SELECT_ASSETS = """
    SELECT a.id            AS asset_id,
           a.bbox_json     AS bbox_json,
           a.tilt_deg      AS tilt_deg,
           si.storage_path AS raw_storage_path
      FROM image_assets a
      JOIN source_images si ON si.id = a.source_image_id
     WHERE si.source = 'ebay'
       AND a.storage_status = 'present'
       AND si.storage_status = 'present'
"""

_UPDATE_TILT = """
    UPDATE image_assets
       SET tilt_deg         = ?,
           axis_ratio       = ?,
           tilt_trustworthy = ?
     WHERE id = ?
"""


def _open_ro() -> sqlite3.Connection:
    conn = sqlite3.connect(f"file:{_DB}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def _open_rw() -> sqlite3.Connection:
    conn = sqlite3.connect(str(_DB))
    conn.row_factory = sqlite3.Row
    return conn


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Backfill tilt dans image_assets d'eurio.db."
    )
    ap.add_argument(
        "--limit", type=int, default=0,
        help="Nombre max d'assets à traiter (0 = tous). Utile pour les tests.",
    )
    ap.add_argument(
        "--commit", action="store_true", default=False,
        help="Écrit en DB. Sans ce flag, dry-run : calcule mais n'écrit pas.",
    )
    ap.add_argument(
        "--force", action="store_true", default=False,
        help="Recalcule même les assets déjà renseignés (tilt_deg IS NOT NULL).",
    )
    args = ap.parse_args()

    if not _DB.exists():
        raise SystemExit(f"DB absente : {_DB}")

    # Chargement des assets depuis la DB (lecture seule).
    ro = _open_ro()
    query = _SELECT_ASSETS
    if not args.force:
        # Filtre SQL : sauter les assets déjà calculés sauf si --force.
        query = query.rstrip() + "\n       AND a.tilt_deg IS NULL"
    rows = ro.execute(query).fetchall()
    ro.close()

    total = len(rows)
    if args.limit:
        rows = rows[: args.limit]
    print(
        f"[backfill-tilt] {len(rows)} assets à traiter"
        f"{'' if not args.limit else f' (limité à {args.limit})'}"
        f" / {total} eligibles au total"
        f" | commit={'oui' if args.commit else 'NON (dry-run)'}"
        f" | force={'oui' if args.force else 'non'}"
    )

    n = {"traités": 0, "no_raw": 0, "mesurés": 0, "fiables": 0, "erreurs": 0}
    updates: list[tuple] = []  # (tilt_deg, axis_ratio, tilt_trustworthy, asset_id)
    t0 = time.time()

    for row in rows:
        n["traités"] += 1
        raw_path = _raw_local_path(row["raw_storage_path"])
        if not raw_path.exists():
            n["no_raw"] += 1
            continue

        bgr = cv2.imread(str(raw_path), cv2.IMREAD_COLOR)
        if bgr is None:
            n["no_raw"] += 1
            continue

        try:
            oracle = _oracle_from_raw(bgr, row["bbox_json"])
            hint = {
                "cx": oracle["hint_cx"],
                "cy": oracle["hint_cy"],
                "r": oracle["r_pipe"],
            }
            tilt = measure_tilt(bgr, hint)
        except Exception as exc:
            print(f"  ERREUR asset {row['asset_id']} : {exc}", file=sys.stderr)
            n["erreurs"] += 1
            continue

        ar = tilt.get("axis_ratio")
        td = tilt.get("tilt_deg")
        trust = 1 if tilt.get("trustworthy") else 0

        if ar is not None:
            n["mesurés"] += 1
        if trust:
            n["fiables"] += 1

        updates.append((td, ar, trust, row["asset_id"]))

        if n["traités"] % 200 == 0:
            print(f"  {n['traités']}/{len(rows)} traités ({time.time()-t0:.0f}s)", flush=True)

    print(
        f"\n[résumé] traités={n['traités']}  no_raw={n['no_raw']}"
        f"  mesurés={n['mesurés']}  fiables={n['fiables']}  erreurs={n['erreurs']}"
        f"  à écrire={len(updates)}"
    )

    if not args.commit:
        print("[dry-run] Aucune écriture en DB. Relancer avec --commit pour persister.")
        # Affiche les 5 premières mesures calculées pour vérification.
        for td, ar, trust, aid in updates[:5]:
            print(f"  asset={aid}  tilt_deg={td}  axis_ratio={ar}  trustworthy={trust}")
        return

    # Écriture en DB — transaction unique pour l'ensemble des updates.
    rw = _open_rw()
    with rw:
        rw.executemany(_UPDATE_TILT, updates)
    rw.close()

    print(f"[commit] {len(updates)} lignes mises à jour en {time.time()-t0:.0f}s.")

    # Vérification : SELECT des assets mis à jour.
    if updates:
        ids = [u[3] for u in updates[:10]]
        placeholders = ",".join("?" * len(ids))
        ro2 = _open_ro()
        check = ro2.execute(
            f"SELECT id, tilt_deg, axis_ratio, tilt_trustworthy"
            f"  FROM image_assets WHERE id IN ({placeholders})",
            ids,
        ).fetchall()
        ro2.close()
        print(f"\n[vérification] {len(check)} lignes lues en retour :")
        for r in check:
            print(
                f"  id={r['id'][:24]}…  tilt_deg={r['tilt_deg']}"
                f"  axis_ratio={r['axis_ratio']}"
                f"  tilt_trustworthy={r['tilt_trustworthy']}"
            )


if __name__ == "__main__":
    main()
