"""build_fragment_probe_set.py — dataset de crops census pour la probe face-vs-fragment.

Piste 3 (census-detector-design.md) : la cause dominante de fragments (gros plans
tranche/partiel, capsule) est circulaire ET coin-like → ni la géométrie ni la sim
DINO « coin-ness » ne la séparent. Une probe entraînée (régression log. sur
features DINO) « face entière vs fragment » est le seul levier restant.

Ce script génère les crops census (mode `EURIO_CENSUS_DETECT=1`, mêmes circuits
que la prod sous flag) à partir des raws téléchargés, en deux splits :
  - TRAIN : classes diverses (cap raws/classe), pour entraîner la probe.
  - TEST  : at-2002 (held-out, jamais en train) — la classe étudiée tout le chantier.

⚠️ Anti-fuite : on EXCLUT les `source_image_id` du bench census (`bench_v0.json`)
de TOUT le dataset (le bench sert à mesurer le plafond — y piocher fausserait toute
comparaison ultérieure). On exclut au niveau de l'IMAGE, pas de la classe (le bench
ne couvre qu'une fraction des images de chaque classe).

Sorties (dans state/fragment_probe/) :
  - crops/<split>/<crop_id>.png     — un crop 224×224 par détection acceptée
  - manifest_<split>.jsonl          — {crop_id, class, raw_id, idx, cx, cy, r}
  - sheet_<split>_<n>.jpg           — contact sheets indexés (24 tuiles, pour labelliser)

Usage (depuis ml/, PYTHONPATH=.):
  .venv/bin/python scripts/build_fragment_probe_set.py
"""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
from pathlib import Path

import cv2
import numpy as np

cv2.setNumThreads(1)
ML_DIR = Path(__file__).resolve().parents[1]
DB_PATH = ML_DIR / "state" / "eurio.db"
BENCH = ML_DIR / "state" / "coin_census_bench" / "bench_v0.json"
OUT = ML_DIR / "state" / "fragment_probe"

TEST_CLASS = "at-2002-2eur-standard-1st-map"
TRAIN_CLASSES = [
    "at-2005-2eur-50th-anniversary-of-the-austrian-state-treaty",
    "fr-2016-2eur-100th-anniversary-of-the-birth-of-francois-mitterrand",
    "fr-2008-2eur-french-presidency-of-the-council-of-the-european-union",
    "es-2016-2eur-old-town-of-segovia-and-its-aqueduct",
    "fi-2017-2eur-100-years-of-independence",
    "de-2010-2eur-state-of-bremen",
    "be-2011-2eur-100th-international-womens-day",
    "it-2016-2eur-2200th-anniversary-of-the-death-of-plautus",
]
TRAIN_RAWS_PER_CLASS = 16


def _bench_excluded() -> set[str]:
    if not BENCH.exists():
        return set()
    data = json.loads(BENCH.read_text())
    items = data if isinstance(data, list) else data.get("items", [])
    return {it["source_image_id"] for it in items if it.get("source_image_id")}


def _gen_split(conn, split: str, classes: list[str], cap: int | None,
               excluded: set[str]) -> list[dict]:
    from vision.normalize_snap import normalize_listing
    from shared.storage.local_cache import local_path

    crop_dir = OUT / "crops" / split
    crop_dir.mkdir(parents=True, exist_ok=True)
    records = []
    for cls in classes:
        rows = conn.execute(
            "SELECT id, storage_path FROM source_images "
            "WHERE target_eurio_id = ? AND storage_path IS NOT NULL",
            (cls,),
        ).fetchall()
        rows = [r for r in rows if r["id"] not in excluded]
        if cap:
            rows = rows[:cap]
        n_crops_cls = 0
        for r in rows:
            try:
                p = local_path("enrichment-raws", r["storage_path"])
            except FileNotFoundError:
                continue
            bgr = cv2.imread(str(p), cv2.IMREAD_COLOR)
            if bgr is None:
                continue
            for idx, res in enumerate(normalize_listing(bgr)):
                if res.image is None:
                    continue
                crop_id = f"{r['id'][:12]}_{idx}"
                cv2.imwrite(str(crop_dir / f"{crop_id}.png"), res.image)
                records.append({"crop_id": crop_id, "class": cls,
                                "raw_id": r["id"][:12], "idx": idx,
                                "cx": res.cx, "cy": res.cy, "r": res.r})
                n_crops_cls += 1
        print(f"  [{split}] {cls[:45]:45s} {len(rows):3d} raws → {n_crops_cls:3d} crops")

    man = OUT / f"manifest_{split}.jsonl"
    with open(man, "w") as f:
        for rec in records:
            f.write(json.dumps(rec) + "\n")

    # Contact sheets indexés (24 tuiles 200px, 6 cols) pour labelling.
    cols, tile = 6, 200
    per_sheet = 24
    for s in range(0, len(records), per_sheet):
        chunk = records[s:s + per_sheet]
        rows_n = (len(chunk) + cols - 1) // cols
        sheet = np.zeros((rows_n * tile, cols * tile, 3), np.uint8)
        for i, rec in enumerate(chunk):
            img = cv2.imread(str(crop_dir / f"{rec['crop_id']}.png"))
            t = cv2.resize(img, (tile, tile))
            cv2.putText(t, f"#{s + i}", (4, 22), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2)
            rr, cc = divmod(i, cols)
            sheet[rr * tile:(rr + 1) * tile, cc * tile:(cc + 1) * tile] = t
        cv2.imwrite(str(OUT / f"sheet_{split}_{s // per_sheet:02d}.jpg"), sheet)
    print(f"  [{split}] total {len(records)} crops, manifest {man.name}, "
          f"{(len(records) + per_sheet - 1) // per_sheet} sheets")
    return records


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--train-cap", type=int, default=TRAIN_RAWS_PER_CLASS)
    args = ap.parse_args()

    OUT.mkdir(parents=True, exist_ok=True)
    os.environ["EURIO_CENSUS_DETECT"] = "1"
    excluded = _bench_excluded()
    print(f"Anti-fuite : {len(excluded)} source_image_id du bench exclus\n")

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    print("TRAIN :")
    _gen_split(conn, "train", TRAIN_CLASSES, args.train_cap, excluded)
    print("\nTEST (held-out) :")
    _gen_split(conn, "test", [TEST_CLASS], None, excluded)
    print(f"\n→ {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
