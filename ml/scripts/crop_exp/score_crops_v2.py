"""Expé 02 — Composite v2 : combine v1 is_coin + area_ratio anti-undercrop.

Expé 01 (cf. docs/crop-forensics/experiments/01-*.md) a montré que le
composite is_coin v1 marche bien sur le TOP (83 % cat D) mais que les
top-scorers contiennent en pratique des UNDERCROP SUSPECTS — quand le
pipeline crop a tiny-cropped sur une feature intérieure d'une grosse
pièce bimétal, le crop 224×224 contient bien un rim métallique → score
v1 haut. C'est cat B (inner feature) qui slip à travers v1.

V2 plug le signal orthogonal `area_ratio` (= bbox / min(raw)²) : si le
crop est tiny par rapport au raw, on punit. L'effet : un undercrop B
garde un composite v1 haut mais voit son `unified_score` chuter.

Approche :

    area_ratio_factor = clip(area_ratio / 0.15, 0, 1)
    unified_score = composite_v1 * area_ratio_factor

À area_ratio ≥ 0.15 (= la bbox couvre ≥ 15 % du min-dim du raw, soit
∼38 % de l'aire min²), le factor sature à 1 → no penalty. En-dessous,
linéaire : à 0.075 = factor 0.5, à 0 = factor 0.

Sidecar : `state/crop_scores/{run_id}_v2.json` — préserve v1 intact pour
comparaison A/B.

Usage::

    cd ml && .venv/bin/python -m scripts.crop_exp.score_crops_v2 \\
        --run-id <id>
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_ML_DIR = Path(__file__).resolve().parents[2]
if str(_ML_DIR) not in sys.path:
    sys.path.insert(0, str(_ML_DIR))

from store import Store


AREA_RATIO_SATURATION = 0.15
"""Au-dessus, `area_ratio_factor = 1` (pas de pénalité). En-dessous,
pénalité linéaire vers 0. Calibré sur la distribution cohorte V.3 :
median area_ratio ≈ 0.12, p90 ≈ 0.45, donc 0.15 sépare le bottom
suspect du milieu sain."""


def area_ratio_factor(area_ratio: float | None) -> float:
    """0 ≤ factor ≤ 1. None → 0 (on n'a pas la donnée, on pénalise)."""
    if area_ratio is None:
        return 0.0
    return max(0.0, min(1.0, area_ratio / AREA_RATIO_SATURATION))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run-id", required=True)
    ap.add_argument("--v1-sidecar", default=None,
                    help="path v1 sidecar (default: state/crop_scores/{run}.json)")
    ap.add_argument("--output", default=None,
                    help="path v2 sidecar (default: state/crop_scores/{run}_v2.json)")
    args = ap.parse_args()

    v1_path = Path(args.v1_sidecar) if args.v1_sidecar else (
        _ML_DIR / "state" / "crop_scores" / f"{args.run_id}.json"
    )
    if not v1_path.exists():
        print(f"[score_crops_v2] v1 sidecar absent : {v1_path}")
        print("  Run `score_crops.py --run-id ...` d'abord.")
        return 1

    v1_records: list[dict] = json.loads(v1_path.read_text())
    v1_by_asset = {r["asset_id"]: r for r in v1_records}

    # Fetch area_ratio depuis le DB (calculé live côté backend, on le
    # reproduit ici depuis bbox_json + raw_w/raw_h).
    store = Store(_ML_DIR / "state" / "eurio.db")
    conn = store._connection()
    rows = conn.execute(
        """
        SELECT a.id AS asset_id, a.bbox_json AS bbox_json,
               s.width AS raw_w, s.height AS raw_h
          FROM image_assets a
          JOIN source_images s ON s.id = a.source_image_id
         WHERE a.run_id = ?
        """,
        (args.run_id,),
    ).fetchall()

    records: list[dict] = []
    n_no_v1 = 0
    n_no_bbox = 0
    for r in rows:
        v1 = v1_by_asset.get(r["asset_id"])
        if v1 is None:
            n_no_v1 += 1
            continue
        # area_ratio = aire bbox / min(raw_w, raw_h)² (cf. bench_routes)
        ratio: float | None = None
        bbox_raw = r["bbox_json"]
        if bbox_raw:
            try:
                bbox = json.loads(bbox_raw)
                w, h = bbox.get("w"), bbox.get("h")
                rw, rh = r["raw_w"], r["raw_h"]
                if all(x for x in (w, h, rw, rh)):
                    min_d = min(rw, rh)
                    ratio = (w * h) / (min_d * min_d)
            except (json.JSONDecodeError, TypeError, ZeroDivisionError):
                pass
        if ratio is None:
            n_no_bbox += 1

        factor = area_ratio_factor(ratio)
        composite_v1 = float(v1.get("composite") or 0.0)
        unified = composite_v1 * factor
        records.append({
            **v1,                           # asset_id, method, crop_index,
                                            # country, year, rim_peak,
                                            # rim_continuity, disc_metalness,
                                            # composite, ok
            "area_ratio": ratio,
            "area_ratio_factor": factor,
            "unified_score": unified,
        })

    out_path = Path(args.output) if args.output else (
        _ML_DIR / "state" / "crop_scores" / f"{args.run_id}_v2.json"
    )
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(records, indent=1), encoding="utf-8")
    print(f"[score_crops_v2] wrote {len(records)} records to {out_path}")
    if n_no_v1:
        print(f"  · {n_no_v1} assets sans entrée v1 (peut-être pas dans le run)")
    if n_no_bbox:
        print(f"  · {n_no_bbox} assets sans bbox exploitable")

    if records:
        uni = sorted(r["unified_score"] for r in records)
        n = len(uni)
        print(f"  unified_score distribution : "
              f"min={uni[0]:.3f}  p10={uni[n//10]:.3f}  "
              f"median={uni[n//2]:.3f}  p90={uni[(9*n)//10]:.3f}  "
              f"max={uni[-1]:.3f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
