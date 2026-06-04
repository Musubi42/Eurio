"""compare_census_recrop.py — rendement crop AVANT/APRÈS le mode census, par classe.

Mesure PURE (ne mute PAS la base) : pour chaque raw téléchargé d'une classe
(`source_images.target_eurio_id`), compte les crops produits par `normalize_listing`
en mode prod (flag OFF) vs mode census (`EURIO_CENSUS_DETECT=1`). Sert à décider
l'adoption du câblage census (cf. docs/cohort-pipeline/census-detector-design.md).

Optionnel : `--contact-sheet` tuile les crops des raws RÉCUPÉRÉS (0 crop → ≥1) pour
audit visuel de la qualité.

Usage (depuis ml/, PYTHONPATH=.):
  .venv/bin/python scripts/compare_census_recrop.py --target at-2002-2eur-standard-1st-map
  .venv/bin/python scripts/compare_census_recrop.py --target at-2002-... --contact-sheet out.jpg
"""

from __future__ import annotations

import argparse
import os
import sqlite3
from pathlib import Path

import cv2
import numpy as np

cv2.setNumThreads(1)
ML_DIR = Path(__file__).resolve().parents[1]
DB_PATH = ML_DIR / "state" / "eurio.db"


def _count_crops(bgr, census: bool) -> int:
    if census:
        os.environ["EURIO_CENSUS_DETECT"] = "1"
    else:
        os.environ.pop("EURIO_CENSUS_DETECT", None)
    from scan.normalize_snap import normalize_listing
    return len(normalize_listing(bgr))


def _crops(bgr, census: bool):
    if census:
        os.environ["EURIO_CENSUS_DETECT"] = "1"
    else:
        os.environ.pop("EURIO_CENSUS_DETECT", None)
    from scan.normalize_snap import normalize_listing
    return [r.image for r in normalize_listing(bgr) if r.image is not None]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--target", default="at-2002-2eur-standard-1st-map")
    ap.add_argument("--contact-sheet", default="")
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()

    from storage.local_cache import local_path

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT id, storage_path FROM source_images "
        "WHERE target_eurio_id = ? AND storage_path IS NOT NULL",
        (args.target,),
    ).fetchall()
    if args.limit:
        rows = rows[: args.limit]
    print(f"Classe {args.target} : {len(rows)} raws téléchargés\n")

    old_total = cen_total = 0
    old_zero = cen_zero = 0
    recovered = []   # (sid, bgr, crops_census) où old=0 et census≥1
    n_seen = 0
    for r in rows:
        try:
            p = local_path("enrichment-raws", r["storage_path"])
        except FileNotFoundError:
            continue
        bgr = cv2.imread(str(p), cv2.IMREAD_COLOR)
        if bgr is None:
            continue
        n_seen += 1
        n_old = _count_crops(bgr, census=False)
        cen_crops = _crops(bgr, census=True)
        n_cen = len(cen_crops)
        old_total += n_old
        cen_total += n_cen
        old_zero += (n_old == 0)
        cen_zero += (n_cen == 0)
        if n_old == 0 and n_cen >= 1:
            recovered.append((r["id"][:8], bgr, cen_crops))

    print(f"Raws lus            : {n_seen}")
    print(f"{'':20}{'PROD (off)':>12}{'CENSUS (on)':>14}")
    print(f"{'crops produits':20}{old_total:>12}{cen_total:>14}")
    print(f"{'raws à 0 crop':20}{old_zero:>12}{cen_zero:>14}")
    print(f"\nRaws RÉCUPÉRÉS (0→≥1 crop) : {len(recovered)} / {old_zero} zéro-crops prod")
    print(f"Gain crops : +{cen_total - old_total} ({old_total}→{cen_total})")

    if args.contact_sheet and recovered:
        tiles = []
        for sid, _, crops in recovered:
            for cim in crops[:4]:
                t = cv2.resize(cim, (160, 160))
                cv2.putText(t, sid, (4, 14), cv2.FONT_HERSHEY_SIMPLEX, 0.4, (0, 255, 0), 1)
                tiles.append(t)
        if tiles:
            cols = 8
            rows_n = (len(tiles) + cols - 1) // cols
            sheet = np.zeros((rows_n * 160, cols * 160, 3), np.uint8)
            for i, t in enumerate(tiles):
                rr, cc = divmod(i, cols)
                sheet[rr * 160:(rr + 1) * 160, cc * 160:(cc + 1) * 160] = t
            cv2.imwrite(args.contact_sheet, sheet)
            print(f"→ contact sheet : {args.contact_sheet} ({len(tiles)} crops récupérés)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
