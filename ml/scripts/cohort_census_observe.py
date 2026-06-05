"""cohort_census_observe.py — ce que donnerait l'activation census+gate sur une cohorte.

Mesure PURE (ne mute PAS la base). Pour chaque raw d'une cohorte, compare :
  - ACTUEL  = nb de crops déjà persistés (`image_assets`, storage_status=present) —
              l'état réel du pool training (crop prod + recrops + suppressions review) ;
  - CENSUS  = nb de crops que produirait `normalize_listing` en mode census + gate
              anti-fragment (EURIO_CENSUS_DETECT=1, τ via EURIO_CENSUS_FRAGMENT_TAU).

Sort un tableau par classe + agrégat : raws, crops actuels vs census, zéro-crops
récupérés (actuel 0 → census ≥1), et faces perdues (actuel ≥1 → census 0). Échantillon
cappé par classe (`--cap`) pour un coût raisonnable ; `--cap 0` = toute la cohorte.

Usage (depuis ml/, PYTHONPATH=.):
  .venv/bin/python scripts/cohort_census_observe.py --cohort b0299ca0252b --cap 30
"""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
from pathlib import Path

import cv2

cv2.setNumThreads(1)
ML_DIR = Path(__file__).resolve().parents[1]
DB_PATH = ML_DIR / "state" / "eurio.db"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cohort", default="b0299ca0252b")
    ap.add_argument("--cap", type=int, default=30, help="raws/classe (0 = tous)")
    ap.add_argument("--tau", default=None, help="override EURIO_CENSUS_FRAGMENT_TAU")
    args = ap.parse_args()

    os.environ["EURIO_CENSUS_DETECT"] = "1"
    if args.tau is not None:
        os.environ["EURIO_CENSUS_FRAGMENT_TAU"] = args.tau
    tau = os.environ.get("EURIO_CENSUS_FRAGMENT_TAU", "0.45")

    from scan.normalize_snap import normalize_listing
    from storage.local_cache import local_path

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    row = conn.execute("SELECT eurio_ids_json FROM experiment_cohorts WHERE id = ?",
                       (args.cohort,)).fetchone()
    classes = json.loads(row["eurio_ids_json"]) if row and row["eurio_ids_json"] else []
    print(f"Cohorte {args.cohort} : {len(classes)} classes, cap {args.cap}/classe, τ={tau}\n")

    hdr = f"{'classe':45s}{'raws':>6}{'actuel':>8}{'census':>8}{'récup0':>8}{'perdu':>7}"
    print(hdr)
    print("-" * len(hdr))

    T = dict(raws=0, cur=0, cen=0, rec=0, lost=0, cur0=0, cen0=0)
    for cls in sorted(classes):
        rows = conn.execute(
            "SELECT id, storage_path FROM source_images "
            "WHERE target_eurio_id = ? AND storage_path IS NOT NULL",
            (cls,),
        ).fetchall()
        if args.cap:
            rows = rows[: args.cap]
        c = dict(raws=0, cur=0, cen=0, rec=0, lost=0, cur0=0, cen0=0)
        for r in rows:
            try:
                p = local_path("enrichment-raws", r["storage_path"])
            except FileNotFoundError:
                continue
            bgr = cv2.imread(str(p), cv2.IMREAD_COLOR)
            if bgr is None:
                continue
            cur = conn.execute(
                "SELECT COUNT(*) FROM image_assets WHERE source_image_id = ? "
                "AND storage_status = 'present'", (r["id"],)).fetchone()[0]
            cen = len(normalize_listing(bgr))
            c["raws"] += 1; c["cur"] += cur; c["cen"] += cen
            c["cur0"] += (cur == 0); c["cen0"] += (cen == 0)
            if cur == 0 and cen >= 1:
                c["rec"] += 1
            if cur >= 1 and cen == 0:
                c["lost"] += 1
        if c["raws"]:
            print(f"{cls[:45]:45s}{c['raws']:>6}{c['cur']:>8}{c['cen']:>8}"
                  f"{c['rec']:>8}{c['lost']:>7}")
        for k in T:
            T[k] += c[k]

    print("-" * len(hdr))
    print(f"{'TOTAL':45s}{T['raws']:>6}{T['cur']:>8}{T['cen']:>8}{T['rec']:>8}{T['lost']:>7}")
    print(f"\nRaws à 0 crop : actuel {T['cur0']} → census {T['cen0']}")
    print(f"Zéro-crops récupérés (0→≥1) : {T['rec']}")
    print(f"Raws perdus (≥1→0, gate trop strict) : {T['lost']}")
    print(f"Crops : actuel {T['cur']} → census {T['cen']} "
          f"({'+' if T['cen']>=T['cur'] else ''}{T['cen']-T['cur']})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
