"""Calcule `inner_feature_score` pour chaque image_asset d'un run (S5).

Signal anti-B (théorie 02) — relancer Hough sur le RAW entier et comparer
le plus gros cercle plausible au bbox courant :

  raw_max_circle_diameter  : 2 * r_max trouvé par HoughCircles sur le raw
                             complet (downscalé à WR=1024, params relaxés).
  bbox_max_dim             : max(bbox.w, bbox.h) en coordonnées raw.
  inner_feature_score      : raw_max_circle_diameter / bbox_max_dim.

Interprétation : score >> 1 ⇒ Hough a trouvé un cercle bien plus gros que
le bbox du producer → suspect undercrop B (le pipeline a voté un cercle
INTÉRIEUR). Score ≤ 1 ⇒ le bbox capte déjà le plus gros cercle plausible
(donc soit c'est le bon crop, soit l'image n'a pas de cercle géant à
trouver — cat A ou D bien-cropée).

Persiste dans `ml/state/crop_scores/{run_id}_inner.json` (sidecar additif).

Usage::

    cd ml
    python -m scripts.crop_exp.score_crops_inner --run-id <id>
    python -m scripts.crop_exp.score_crops_inner --run-id <id> --limit 100
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import cv2
import numpy as np

_ML_DIR = Path(__file__).resolve().parents[2]
if str(_ML_DIR) not in sys.path:
    sys.path.insert(0, str(_ML_DIR))

from state import Store
from storage.local_cache import local_path


_WORKING_RES = 1024
# Params modérés. param2 monté à 30 pour éviter les faux cercles
# qui saturent maxRadius. Le filtre dur est en aval : on garde
# uniquement les cercles qui CONTIENNENT le bbox courant — sinon
# Hough trouve juste une autre pièce dans un album ou un bord.
_HOUGH_PARAM1 = 80.0
_HOUGH_PARAM2 = 30.0
_RMIN_FRAC = 0.08
_RMAX_FRAC = 0.48   # cap < 0.5 = le cercle reste dans le cadre du raw


def _downscale(bgr: np.ndarray, target: int = _WORKING_RES) -> tuple[np.ndarray, float]:
    h, w = bgr.shape[:2]
    short = min(h, w)
    if short <= target:
        return bgr, 1.0
    scale = target / float(short)
    work = cv2.resize(bgr, (int(w * scale), int(h * scale)),
                      interpolation=cv2.INTER_AREA)
    return work, 1.0 / scale  # scale-back factor (work → native)


def hough_candidates(raw_bgr: np.ndarray) -> list[tuple[float, float, float]]:
    """Retourne tous les cercles plausibles `(cx, cy, r)` en pixels natifs."""
    work, back = _downscale(raw_bgr, _WORKING_RES)
    sh, sw = work.shape[:2]
    short = min(sh, sw)
    gray = cv2.cvtColor(work, cv2.COLOR_BGR2GRAY)
    gray = cv2.medianBlur(gray, 5)

    circles = cv2.HoughCircles(
        gray, cv2.HOUGH_GRADIENT, dp=1.0,
        minDist=int(short * 0.20),
        param1=_HOUGH_PARAM1, param2=_HOUGH_PARAM2,
        minRadius=int(short * _RMIN_FRAC),
        maxRadius=int(short * _RMAX_FRAC),
    )
    if circles is None or len(circles[0]) == 0:
        return []
    return [(float(c[0] * back), float(c[1] * back), float(c[2] * back))
            for c in circles[0]]


def best_containing_circle(candidates: list[tuple[float, float, float]],
                           bbox: dict) -> tuple[float, float, float] | None:
    """Le plus gros cercle dont l'intérieur contient le CENTRE du bbox.

    Filtre clé : on ne s'intéresse qu'aux cercles qui pourraient être le
    PARENT du crop courant (ie le bbox vit à l'intérieur). Sinon dans un
    album multi-pièces Hough remonterait une AUTRE pièce et le score
    serait trompeur.
    """
    if not candidates:
        return None
    bx = bbox["x"] + bbox["w"] / 2.0
    by = bbox["y"] + bbox["h"] / 2.0
    containing = [(cx, cy, r) for cx, cy, r in candidates
                  if (cx - bx) ** 2 + (cy - by) ** 2 < (r * r)]
    if not containing:
        return None
    return max(containing, key=lambda c: c[2])


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run-id", required=True)
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--country", default=None,
                    help="Filtre listing_country (ex: DE).")
    ap.add_argument("--year", type=int, default=None,
                    help="Filtre listing_year (ex: 2010).")
    ap.add_argument("--output", default=None,
                    help="Sortie par défaut : {run_id}_inner[_country_year].json.")
    args = ap.parse_args()

    store = Store(_ML_DIR / "state" / "eurio.db")
    conn = store._connection()

    sql = """
        SELECT a.id AS asset_id, a.bbox_json AS bbox_json,
               a.detection_method AS method, a.crop_index AS crop_index,
               s.id AS source_id, s.storage_path AS raw_path,
               s.width AS raw_w, s.height AS raw_h,
               s.listing_country AS country, s.listing_year AS year
          FROM image_assets a
          JOIN source_images s ON s.id = a.source_image_id
         WHERE a.run_id = ?
    """
    params: list[object] = [args.run_id]
    if args.country:
        sql += " AND s.listing_country = ?"
        params.append(args.country)
    if args.year is not None:
        sql += " AND s.listing_year = ?"
        params.append(args.year)
    sql += " ORDER BY a.fetched_at DESC"
    rows = conn.execute(sql, params).fetchall()
    if args.limit:
        rows = rows[: args.limit]

    if args.output:
        out_path = Path(args.output)
    else:
        suffix = "_inner"
        if args.country:
            suffix += f"_{args.country.lower()}"
        if args.year is not None:
            suffix += f"_{args.year}"
        out_path = _ML_DIR / "state" / "crop_scores" / f"{args.run_id}{suffix}.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)

    print(f"[score_crops_inner] run={args.run_id}  processing {len(rows)} assets…")

    # Cache: plusieurs assets partagent souvent le même raw (multi-crops album).
    raw_cache: dict[str, list[tuple[float, float, float]]] = {}

    records: list[dict] = []
    n_err = 0
    n_no_circle = 0
    for i, r in enumerate(rows, 1):
        try:
            bbox = json.loads(r["bbox_json"]) if r["bbox_json"] else None
            if not bbox:
                n_err += 1
                continue
            bbox_max_dim = float(max(bbox.get("w", 0), bbox.get("h", 0)))
            if bbox_max_dim <= 0:
                n_err += 1
                continue

            src_id = r["source_id"]
            if src_id in raw_cache:
                cands = raw_cache[src_id]
            else:
                p = local_path("enrichment-raws", r["raw_path"])
                raw = cv2.imread(str(p), cv2.IMREAD_COLOR)
                if raw is None:
                    raw_cache[src_id] = []
                    n_err += 1
                    continue
                cands = hough_candidates(raw)
                raw_cache[src_id] = cands

            circle = best_containing_circle(cands, bbox)
            if circle is None:
                n_no_circle += 1
                rec = {
                    "asset_id": r["asset_id"],
                    "source_id": src_id,
                    "method": r["method"],
                    "crop_index": r["crop_index"],
                    "country": r["country"],
                    "year": r["year"],
                    "bbox_max_dim": bbox_max_dim,
                    "raw_max_circle_diameter": 0.0,
                    "raw_max_circle_radius": 0.0,
                    "raw_max_circle_cx": -1.0,
                    "raw_max_circle_cy": -1.0,
                    "inner_feature_score": 0.0,
                }
            else:
                cx, cy, rad = circle
                diam = 2.0 * rad
                score = diam / bbox_max_dim
                rec = {
                    "asset_id": r["asset_id"],
                    "source_id": src_id,
                    "method": r["method"],
                    "crop_index": r["crop_index"],
                    "country": r["country"],
                    "year": r["year"],
                    "bbox_max_dim": bbox_max_dim,
                    "raw_max_circle_diameter": diam,
                    "raw_max_circle_radius": rad,
                    "raw_max_circle_cx": cx,
                    "raw_max_circle_cy": cy,
                    "inner_feature_score": score,
                }
            records.append(rec)
        except Exception as exc:  # noqa: BLE001
            n_err += 1
            if n_err < 5:
                print(f"  ! err on {r['asset_id'][:8]} : {exc}")
        if i % 200 == 0 or i == len(rows):
            print(f"  [{i}/{len(rows)}] (errs={n_err}, no_circle={n_no_circle}, raws_loaded={len(raw_cache)})")

    out_path.write_text(json.dumps(records, indent=1), encoding="utf-8")
    print(f"[score_crops_inner] wrote {len(records)} records → {out_path}")

    if records:
        def dist(key: str) -> str:
            vals = sorted(rr[key] for rr in records)
            n = len(vals)
            return (
                f"min={vals[0]:.3f}  p10={vals[n//10]:.3f}  "
                f"median={vals[n//2]:.3f}  p90={vals[(9*n)//10]:.3f}  "
                f"max={vals[-1]:.3f}"
            )
        print(f"  inner_feature_score  : {dist('inner_feature_score')}")
        high = sum(1 for rr in records if rr["inner_feature_score"] >= 1.3)
        very_high = sum(1 for rr in records if rr["inner_feature_score"] >= 2.0)
        print(f"  score ≥ 1.3 : {high} ({100*high/len(records):.1f} %)")
        print(f"  score ≥ 2.0 : {very_high} ({100*very_high/len(records):.1f} %)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
