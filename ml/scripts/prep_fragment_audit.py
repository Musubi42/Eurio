"""Prépare les données d'audit du gate anti-fragment (page one-shot /fragment-audit).

Pour un run eBay, régénère TOUS les crops qui ont passé le filtre rayon (donc
scorés par la probe `face_scores` du gate), sauve chaque crop en PNG et écrit un
manifeste avec son score + s'il serait éjecté (score < τ). LECTURE SEULE sur la DB.

L'humain assess ensuite visuellement dans la page : combien de VRAIS coins sont
sous le palier qui les éjecte.

Usage : .venv/bin/python -m scripts.prep_fragment_audit --run <run_id>
"""

from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path

ML_DIR = Path(__file__).resolve().parent.parent
DB_PATH = ML_DIR / "state" / "eurio.db"
OUT_DIR = ML_DIR / "state" / "fragment_audit"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", required=True)
    ap.add_argument("--include-zero-only", action="store_true", default=True,
                    help="seulement les images crop_status=zero_crops (où tout a été éjecté)")
    ap.add_argument("--max-imgs", type=int, default=None)
    args = ap.parse_args()

    import cv2

    from shared.storage.local_cache import local_path
    from vision.census import face_scores
    from vision.normalize_snap import (
        CropConfig,
        _census_fragment_tau,
        _crop_mask_resize_int,
        detect_circles_multi,
    )

    tau = _census_fragment_tau()
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for old in OUT_DIR.glob("*.png"):
        old.unlink()

    conn = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    q = ("SELECT id, source_ref, storage_path, listing_title, source_url, crop_status "
         "FROM source_images WHERE source='ebay' AND run_id=? AND storage_path IS NOT NULL")
    if args.include_zero_only:
        q += " AND crop_status='zero_crops'"
    simgs = conn.execute(q, (args.run,)).fetchall()
    if args.max_imgs:
        simgs = simgs[: args.max_imgs]
    print(f"{len(simgs)} images à ré-analyser (τ={tau})…")

    cfg = CropConfig()
    manifest: list[dict] = []
    n = 0
    for i, row in enumerate(simgs):
        try:
            bgr = cv2.imread(str(local_path("enrichment-raws", row["storage_path"])), cv2.IMREAD_COLOR)
        except Exception:
            continue
        if bgr is None:
            continue
        dets = detect_circles_multi(bgr, census=True)
        crops, meta = [], []
        for det in dets:
            if not det.accepted:  # filtré par rayon/structure, pas par le gate fragment
                continue
            res = _crop_mask_resize_int(bgr, det.cx, det.cy, det.r, method=det.method, config=cfg)
            if res.image is not None:
                crops.append(res.image)
                meta.append((int(det.r), int(det.cx), int(det.cy)))
        if not crops:
            continue
        scores = face_scores(crops)
        for (r, cx, cy), score, img in zip(meta, scores, crops):
            name = f"{n:04d}.png"
            cv2.imwrite(str(OUT_DIR / name), img)
            manifest.append({
                "name": name,
                "score": round(float(score), 4),
                "r": r,
                "ejected": bool(score < tau),
                "source_ref": row["source_ref"],
                "listing_title": row["listing_title"],
                "source_url": row["source_url"],
            })
            n += 1
        if (i + 1) % 50 == 0:
            print(f"  …{i + 1}/{len(simgs)}  ({n} crops)")

    manifest.sort(key=lambda m: -m["score"])  # plus hauts d'abord (les + proches du palier)
    (OUT_DIR / "manifest.json").write_text(json.dumps({"tau": tau, "run": args.run, "items": manifest}))
    ej = sum(1 for m in manifest if m["ejected"])
    print(f"\n{n} crops sauvés · {ej} éjectés (<{tau}) · {n - ej} gardés · → {OUT_DIR}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
