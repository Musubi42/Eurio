"""Calcule `bg_uniformity` + `near_white_ratio` pour chaque crop d'un run.

Signal anti-A (théorie 01 révisée) — deux métriques dans l'anneau/disque :

  bg_uniformity  : std des pixels gris HORS du disque inscrit.
                   Toujours 0 pour les crops normalisés (normalize_snap
                   masque le fond en noir) → signal DÉGÉNÉRÉ sur ce run,
                   gardé pour traçabilité.

  near_white_ratio : fraction de pixels avec V > 220 (HSV) DANS le
                     disque inscrit (80 % du rayon). Proxy pour
                     "fond blanc de papier / sticker / strip". Élevé =
                     probable cat A. Faible = pièce métallique (cat D).
                     Orthogonal à disc_metalness qui couvre grey/or mais
                     PAS le blanc pur (V > 235 exclus du test silver).

Persiste dans `ml/state/crop_scores/{run_id}_bg.json` (sidecar additif).

Usage::

    cd ml
    python -m scripts.crop_exp.score_crops_bg --run-id <id>
    python -m scripts.crop_exp.score_crops_bg --run-id <id> --limit 100
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

from store import Store
from storage.local_cache import local_path


def _outer_mask(size: int, r: int) -> np.ndarray:
    """Pixels hors du disque inscrit (coins + anneau extérieur)."""
    cy = cx = size // 2
    yy, xx = np.ogrid[:size, :size]
    d2 = (yy - cy) ** 2 + (xx - cx) ** 2
    return d2 >= (r * r)


def _inner_disk_mask(size: int, r_frac: float = 0.80) -> np.ndarray:
    """Pixels dans le disque central (80 % du rayon par défaut)."""
    cy = cx = size // 2
    r = int(size // 2 * r_frac)
    yy, xx = np.ogrid[:size, :size]
    d2 = (yy - cy) ** 2 + (xx - cx) ** 2
    return d2 < (r * r)


def score_bg(crop_bgr: np.ndarray) -> dict[str, float] | None:
    h, w = crop_bgr.shape[:2]
    if h != w or h < 64:
        return None

    size = h
    r_nominal = size // 2

    # ── bg_uniformity (dégénéré sur crops masqués) ───────────────────────
    gray = cv2.cvtColor(crop_bgr, cv2.COLOR_BGR2GRAY).astype(np.float32)
    outer = _outer_mask(size, r_nominal)
    bg_px = gray[outer]
    bg_uniformity = float(np.std(bg_px)) if len(bg_px) > 0 else 0.0

    # ── near_white_ratio (signal actif — V > 220 dans disque intérieur) ──
    hsv = cv2.cvtColor(crop_bgr, cv2.COLOR_BGR2HSV)
    V = hsv[..., 2]
    inner = _inner_disk_mask(size, r_frac=0.80)
    total_inner = int(inner.sum())
    near_white = int(((V > 220) & inner).sum())
    near_white_ratio = near_white / total_inner if total_inner > 0 else 0.0

    return {
        "bg_uniformity": bg_uniformity,
        "near_white_ratio": near_white_ratio,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run-id", required=True)
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--output", default=None)
    args = ap.parse_args()

    store = Store(_ML_DIR / "state" / "eurio.db")
    conn = store._connection()

    rows = conn.execute(
        """
        SELECT a.id AS asset_id, a.storage_path AS storage_path,
               a.detection_method AS method, a.crop_index AS crop_index,
               s.listing_country AS country, s.listing_year AS year
          FROM image_assets a
          JOIN source_images s ON s.id = a.source_image_id
         WHERE a.run_id = ?
         ORDER BY a.fetched_at DESC
        """,
        (args.run_id,),
    ).fetchall()
    if args.limit:
        rows = rows[: args.limit]

    out_path = Path(args.output) if args.output else (
        _ML_DIR / "state" / "crop_scores" / f"{args.run_id}_bg.json"
    )
    out_path.parent.mkdir(parents=True, exist_ok=True)

    print(f"[score_crops_bg] run={args.run_id}  processing {len(rows)} crops…")
    records: list[dict] = []
    n_err = 0
    for i, r in enumerate(rows, 1):
        try:
            p = local_path("enrichment-crops", r["storage_path"])
            crop = cv2.imread(str(p), cv2.IMREAD_COLOR)
            if crop is None:
                n_err += 1
                continue
            scores = score_bg(crop)
            if scores is None:
                n_err += 1
                continue
            records.append({
                "asset_id": r["asset_id"],
                "method": r["method"],
                "crop_index": r["crop_index"],
                "country": r["country"],
                "year": r["year"],
                **scores,
            })
        except Exception as exc:  # noqa: BLE001
            n_err += 1
            if n_err < 5:
                print(f"  ! err on {r['asset_id'][:8]} : {exc}")
        if i % 200 == 0 or i == len(rows):
            print(f"  [{i}/{len(rows)}] (errs={n_err})")

    out_path.write_text(json.dumps(records, indent=1), encoding="utf-8")
    print(f"[score_crops_bg] wrote {len(records)} records → {out_path}")

    if records:
        def dist(key: str) -> str:
            vals = sorted(r[key] for r in records)
            n = len(vals)
            return (
                f"min={vals[0]:.3f}  p10={vals[n//10]:.3f}  "
                f"median={vals[n//2]:.3f}  p90={vals[(9*n)//10]:.3f}  "
                f"max={vals[-1]:.3f}"
            )
        print(f"  bg_uniformity   : {dist('bg_uniformity')}")
        print(f"  near_white_ratio: {dist('near_white_ratio')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
