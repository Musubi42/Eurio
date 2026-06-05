"""build_hardneg_set.py — set de hard-negatives (probe v2) depuis un run census.

Les crops récupérés par `recrop_cohort_census` (run_id census-recover-*) à τ=0.45
contiennent les FAUX POSITIFS du gate v1 (disques vierges, cartes/certificats
packaging, sombres/flous) + de vraies faces. En les labellisant on obtient exactement
les hard-negatives qui manquaient à la probe v1 → carburant pour la v2.

Copie les crops (depuis le cache MinIO) dans state/fragment_probe/crops/hardneg/,
écrit manifest_hardneg.jsonl ({crop_id=asset_id, class, raw_id}) et des contact
sheets indexés GLOBALEMENT (sheet_hardneg_NN.jpg) pour labelliser par index.

Usage (depuis ml/, PYTHONPATH=.):
  .venv/bin/python scripts/build_hardneg_set.py --run census-recover-b0299ca0252b
"""

from __future__ import annotations

import argparse
import json
import shutil
import sqlite3
from pathlib import Path

import cv2
import numpy as np

ML_DIR = Path(__file__).resolve().parents[1]
DB_PATH = ML_DIR / "state" / "eurio.db"
OUT = ML_DIR / "state" / "fragment_probe"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", default="census-recover-b0299ca0252b")
    ap.add_argument("--per-sheet", type=int, default=24)
    args = ap.parse_args()

    from storage.local_cache import local_path

    crop_dir = OUT / "crops" / "hardneg"
    crop_dir.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        """
        SELECT ia.id, ia.storage_path, si.target_eurio_id AS cls, ia.source_image_id
          FROM image_assets ia JOIN source_images si ON si.id = ia.source_image_id
         WHERE ia.run_id = ?
         ORDER BY si.target_eurio_id, ia.source_image_id, ia.crop_index
        """,
        (args.run,),
    ).fetchall()

    records = []
    for r in rows:
        try:
            p = local_path("enrichment-crops", r["storage_path"])
        except FileNotFoundError:
            continue
        dst = crop_dir / f"{r['id']}.png"
        shutil.copyfile(p, dst)
        records.append({"crop_id": r["id"], "class": r["cls"],
                        "raw_id": r["source_image_id"][:12]})

    with open(OUT / "manifest_hardneg.jsonl", "w") as f:
        for rec in records:
            f.write(json.dumps(rec) + "\n")
    print(f"{len(records)} crops copiés → {crop_dir}")

    per, cols, tile = args.per_sheet, 6, 200
    for s in range(0, len(records), per):
        chunk = records[s:s + per]
        rows_n = (len(chunk) + cols - 1) // cols
        sheet = np.zeros((rows_n * tile, cols * tile, 3), np.uint8)
        for i, rec in enumerate(chunk):
            im = cv2.imread(str(crop_dir / f"{rec['crop_id']}.png"))
            t = cv2.resize(im, (tile, tile)) if im is not None else np.full(
                (tile, tile, 3), 40, np.uint8)
            cv2.putText(t, f"#{s+i}", (4, 22), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2)
            rr, cc = divmod(i, cols)
            sheet[rr*tile:(rr+1)*tile, cc*tile:(cc+1)*tile] = t
        cv2.imwrite(str(OUT / f"sheet_hardneg_{s//per:02d}.jpg"), sheet)
    print(f"{(len(records)+per-1)//per} sheets sheet_hardneg_NN.jpg dans {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
