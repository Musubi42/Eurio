"""diag_fragment_geometry.py — les fragments ont-ils une boîte « pièce entière » parente ?

Pour chaque raw d'une classe, en mode census : liste les détections ACCEPTÉES
(cx,cy,r natifs) triées par rayon décroissant, et pour chaque détection plus
petite indique si son centre tombe DANS une détection plus grande et le ratio de
rayon. But : décider si la fragmentation est un problème de DEDUP (parent existe →
clustering/NMS plus agressif suffit) ou de PROPOSEUR (pas de parent → probe).

Usage (depuis ml/, PYTHONPATH=.):
  .venv/bin/python scripts/diag_fragment_geometry.py --target at-2002-2eur-standard-1st-map
"""

from __future__ import annotations

import argparse
import os
import sqlite3
from pathlib import Path

import cv2

cv2.setNumThreads(1)
ML_DIR = Path(__file__).resolve().parents[1]
DB_PATH = ML_DIR / "state" / "eurio.db"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--target", default="at-2002-2eur-standard-1st-map")
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()

    os.environ["EURIO_CENSUS_DETECT"] = "1"
    from vision.normalize_snap import detect_circles_multi
    from shared.storage.local_cache import local_path

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT id, storage_path FROM source_images "
        "WHERE target_eurio_id = ? AND storage_path IS NOT NULL",
        (args.target,),
    ).fetchall()
    if args.limit:
        rows = rows[: args.limit]

    n_raws = 0
    n_acc = 0
    n_multi = 0          # raws avec ≥2 détections acceptées
    n_child_in_parent = 0   # détections dont le centre ∈ une plus grande
    child_ratios = []       # r_child / r_parent pour ces cas
    raws_with_child = 0
    per_raw_counts = {}

    for r in rows:
        try:
            p = local_path("enrichment-raws", r["storage_path"])
        except FileNotFoundError:
            continue
        bgr = cv2.imread(str(p), cv2.IMREAD_COLOR)
        if bgr is None:
            continue
        n_raws += 1
        dets = [d for d in detect_circles_multi(bgr) if d.accepted]
        per_raw_counts[len(dets)] = per_raw_counts.get(len(dets), 0) + 1
        n_acc += len(dets)
        if len(dets) >= 2:
            n_multi += 1
        dets_sorted = sorted(dets, key=lambda d: d.r, reverse=True)
        raw_has_child = False
        for i, c in enumerate(dets_sorted):
            for parent in dets_sorted[:i]:
                dx = c.cx - parent.cx
                dy = c.cy - parent.cy
                if (dx * dx + dy * dy) ** 0.5 <= parent.r and c.r < parent.r:
                    n_child_in_parent += 1
                    child_ratios.append(c.r / parent.r)
                    raw_has_child = True
                    break
        if raw_has_child:
            raws_with_child += 1

    print(f"Classe {args.target}")
    print(f"Raws lus                       : {n_raws}")
    print(f"Détections acceptées (total)   : {n_acc}")
    print(f"Raws ≥2 détections             : {n_multi}")
    print(f"Détections enfant-dans-parent  : {n_child_in_parent}")
    print(f"Raws avec ≥1 enfant-dans-parent: {raws_with_child}")
    if child_ratios:
        import statistics
        print(f"  ratio r_enfant/r_parent : min={min(child_ratios):.2f} "
              f"médiane={statistics.median(child_ratios):.2f} max={max(child_ratios):.2f}")
        print(f"  enfants ratio <0.70 (absorbables): {sum(1 for x in child_ratios if x < 0.70)}")
        print(f"  enfants ratio ≥0.70 (gardés par garde taille): {sum(1 for x in child_ratios if x >= 0.70)}")
    print(f"\nDistribution #détections/raw :")
    for k in sorted(per_raw_counts):
        print(f"  {k} dét : {per_raw_counts[k]} raws")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
