"""Re-crop des crops eBay existants avec le détecteur de rim (chantier
crop-quality-overhaul, Chunk 4).

Pour chaque image_asset eBay présent, on repart du cercle stocké (bbox_json =
sortie du pipeline actuel) comme HINT et on cherche le RIM EXTERNE via
`crop_detectors.crop_with_detector(algo, raw, hint)` — exactement ce qui a été
validé au banc (gold 25/2) et mesuré sur le parc (79.9 %→91.7 % oracle-good).

Écrit le nouveau crop 224 au MÊME `storage_path` (overwrite) :
  - cache local `~/.cache/eurio/enrichment-crops/<storage_path>`,
  - MinIO (write-through, best-effort ; `--no-minio` pour cache+DB seulement),
  - DB : bbox_json (nouveau cercle), detection_method (+rimrefine), width/height,
    phash recalculé. eurio_id / resolution_status PRÉSERVÉS (même pièce).

Raws JAMAIS touchés. Idempotent : skip les assets déjà '+rimrefine' (sauf
--force). Le tag est volontairement distinct de '+lotcrop' (recrop multi-pièces)
et ne réutilise PAS '+refine' nu (collision historique avec d'autres passes).
Backup DB conseillé avant `--commit` (cf. state/eurio.db.bak-*).

Usage :
    cd ml
    .venv/bin/python -m scripts.recrop_ebay_refine                 # dry-run (compte)
    .venv/bin/python -m scripts.recrop_ebay_refine --commit --limit 3   # test
    .venv/bin/python -m scripts.recrop_ebay_refine --commit            # tout
    .venv/bin/python -m scripts.recrop_ebay_refine --commit --no-minio # cache+DB only
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
import time
from pathlib import Path

import cv2

_ML = Path(__file__).resolve().parents[1]
if str(_ML) not in sys.path:
    sys.path.insert(0, str(_ML))

from vision.crop_detectors import crop_with_detector  # noqa: E402
from scripts.crop_quality_diag import _oracle_from_raw, _raw_local_path  # noqa: E402
from sources._base.phash import compute_phash  # noqa: E402

_DB = _ML / "state" / "eurio.db"
_CACHE = Path.home() / ".cache" / "eurio"


def _crop_local_path(storage_path: str) -> Path:
    return _CACHE / "enrichment-crops" / storage_path


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--commit", action="store_true", help="Écrit (sinon dry-run).")
    ap.add_argument("--limit", type=int, default=0, help="Max assets (0 = tous).")
    ap.add_argument("--algo", default="bbox_refine")
    ap.add_argument("--no-minio", action="store_true", help="Cache+DB seulement.")
    ap.add_argument("--force", action="store_true", help="Re-traite même les '+rimrefine'.")
    args = ap.parse_args()

    upload_through = None
    if args.commit and not args.no_minio:
        from shared.storage.local_cache import upload_through as _ut  # noqa: E402
        upload_through = _ut

    conn = sqlite3.connect(str(_DB))
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        """
        SELECT a.id aid, a.storage_path crop_sp, a.bbox_json, a.detection_method,
               si.storage_path raw_sp
          FROM image_assets a JOIN source_images si ON si.id = a.source_image_id
         WHERE si.source = 'ebay'
           AND a.storage_status = 'present' AND si.storage_status = 'present'
           -- Garde : le refine (mono-pièce, expansion vers le rim externe) ne doit
           -- JAMAIS toucher une image MULTI-pièces (lot/coffret) — il y engloutit
           -- toute la planche. Ces images-là sont (re)cropées par-pièce via
           -- scripts.recrop_lots_per_coin (detect_circles_multi).
           AND (SELECT COUNT(*) FROM image_assets a2
                 WHERE a2.source_image_id = a.source_image_id
                   AND a2.storage_status = 'present') < 2
         ORDER BY a.id
        """
    ).fetchall()

    n = {"seen": 0, "skip_refined": 0, "skip_noraw": 0, "skip_nodet": 0,
         "changed": 0, "minio_fail": 0, "smaller": 0, "bigger": 0}
    t0 = time.time()
    for r in rows:
        if args.limit and n["seen"] >= args.limit:
            break
        n["seen"] += 1
        method0 = r["detection_method"] or ""
        if "rimrefine" in method0 and not args.force:
            n["skip_refined"] += 1
            continue
        raw_p = _raw_local_path(r["raw_sp"])
        if not raw_p.exists():
            n["skip_noraw"] += 1
            continue
        bgr = cv2.imread(str(raw_p))
        if bgr is None:
            n["skip_noraw"] += 1
            continue
        orc = _oracle_from_raw(bgr, r["bbox_json"])
        hint = {"cx": orc["hint_cx"], "cy": orc["hint_cy"], "r": orc["r_pipe"]}
        res, det = crop_with_detector(args.algo, bgr, hint=hint)
        if not det.ok or res is None or res.image is None:
            n["skip_nodet"] += 1
            continue
        if det.r > orc["r_pipe"]:
            n["bigger"] += 1
        elif det.r < orc["r_pipe"]:
            n["smaller"] += 1
        n["changed"] += 1
        if not args.commit:
            continue

        # 1. cache local (overwrite même storage_path)
        cp = _crop_local_path(r["crop_sp"])
        cp.parent.mkdir(parents=True, exist_ok=True)
        ok, buf = cv2.imencode(".png", res.image)
        if not ok:
            n["skip_nodet"] += 1
            continue
        cp.write_bytes(buf.tobytes())
        # 2. MinIO write-through (best-effort)
        if upload_through is not None:
            try:
                upload_through("enrichment-crops", r["crop_sp"], buf.tobytes())
            except Exception:  # noqa: BLE001
                n["minio_fail"] += 1
        # 3. DB : nouveau cercle + method + dims + phash (eurio_id préservé)
        bbox = {"x": float(det.cx - det.r), "y": float(det.cy - det.r),
                "w": float(2 * det.r), "h": float(2 * det.r)}
        # Idempotent : ne re-tague pas si déjà '+rimrefine' (cas --force).
        if not method0:
            new_method = det.method
        elif "rimrefine" in method0:
            new_method = method0
        else:
            new_method = method0 + "+rimrefine"
        conn.execute(
            "UPDATE image_assets SET bbox_json=?, detection_method=?, "
            "width=?, height=?, phash=? WHERE id=?",
            (json.dumps(bbox), new_method, res.image.shape[1], res.image.shape[0],
             compute_phash(res.image), r["aid"]),
        )
        if n["changed"] % 200 == 0:
            conn.commit()
            print(f"  {n['changed']} re-cropés ({time.time()-t0:.0f}s)", flush=True)

    if args.commit:
        conn.commit()
    conn.close()
    mode = "COMMIT" if args.commit else "DRY-RUN"
    print(f"\n[{mode}] {n}")
    print(f"durée {time.time()-t0:.0f}s")


if __name__ == "__main__":
    main()
