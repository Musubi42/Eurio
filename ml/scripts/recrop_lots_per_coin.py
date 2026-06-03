"""Re-crop des images MULTI-PIÈCES (lots / coffrets) en crops serrés par-pièce.

Bug corrigé : ``recrop_ebay_refine`` (bbox_refine) a été appliqué aussi aux
images multi-pièces, où l'expansion vers le « rim externe » engloutit toute la
planche → tous les crops d'une même photo collapsent sur la même image entière
(observé : 8 crops d'un coffret, tous bbox identique frac≈1.16). Le refine n'est
valable que pour les images MONO-pièce (undercrop bimétal).

La vérité per-pièce est récupérable : ``detect_circles_multi(raw)`` (déterministe)
redonne les cercles serrés, matchés aux ``image_assets`` par ORDRE (les détections
acceptées dans l'ordre == ordre des ``crop_index``), exactement comme l'overlay de
la review lot (``_compute_detections``) et le pipeline d'origine (``normalize_listing``).

Pour chaque source_image eBay ayant ≥2 crops présents, on régénère chaque crop
depuis SON cercle per-pièce via ``_crop_mask_resize_float`` (format prod : marge
0.02, masque dur, 224). Écrit cache local + MinIO (write-through) + DB
(bbox_json, detection_method, width/height, phash). eurio_id / resolution_status
PRÉSERVÉS. Raws JAMAIS touchés.

Garde-fou : on ne traite une image que si ``len(accepted) == n_assets`` (sinon le
mapping par ordre est ambigu → skip + log). Idempotent : un asset dont le method
ne contient plus ``refine`` est déjà corrigé → skip (sauf ``--force``).

Usage :
    cd ml
    .venv/bin/python -m scripts.recrop_lots_per_coin                       # dry-run (compte)
    .venv/bin/python -m scripts.recrop_lots_per_coin --listing-key 'ebay_v1|177589737310|0' --commit
    .venv/bin/python -m scripts.recrop_lots_per_coin --commit              # tout le parc
    .venv/bin/python -m scripts.recrop_lots_per_coin --commit --no-minio   # cache+DB only
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

from scan.normalize_snap import (  # noqa: E402
    _crop_mask_resize_float,
    detect_circles_multi,
)
from scripts.crop_quality_diag import _raw_local_path  # noqa: E402
from sources._base.phash import compute_phash  # noqa: E402

_DB = _ML / "state" / "eurio.db"
_CACHE = Path.home() / ".cache" / "eurio"

# Clé listing eBay (même CASE que review_queue_routes._LISTING_KEY_SQL).
_LISTING_KEY_SQL = (
    "CASE WHEN si.source='ebay' "
    "AND json_extract(si.raw_payload_json,'$.ebay_item_id') IS NOT NULL "
    "THEN 'ebay_'||json_extract(si.raw_payload_json,'$.ebay_item_id') "
    "ELSE si.source_ref END"
)


def _crop_local_path(storage_path: str) -> Path:
    return _CACHE / "enrichment-crops" / storage_path


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--commit", action="store_true", help="Écrit (sinon dry-run).")
    ap.add_argument("--listing-key", default=None, help="Restreint à un listing (debug).")
    ap.add_argument("--limit", type=int, default=0, help="Max source_images (0 = toutes).")
    ap.add_argument("--no-minio", action="store_true", help="Cache+DB seulement.")
    ap.add_argument("--force", action="store_true", help="Re-traite même les assets déjà corrigés.")
    args = ap.parse_args()

    upload_through = None
    if args.commit and not args.no_minio:
        from storage.local_cache import upload_through as _ut  # noqa: E402
        upload_through = _ut

    conn = sqlite3.connect(str(_DB))
    conn.row_factory = sqlite3.Row

    # source_images eBay multi-pièces (≥2 crops présents), + leur raw key.
    where_lk = ""
    params: list = []
    if args.listing_key:
        where_lk = f"AND {_LISTING_KEY_SQL} = ?"
        params.append(args.listing_key)
    si_rows = conn.execute(
        f"""
        SELECT si.id AS si_id, si.storage_path AS raw_sp
          FROM source_images si
          JOIN image_assets a ON a.source_image_id = si.id
         WHERE si.source='ebay' AND si.storage_status='present'
           AND a.storage_status='present' {where_lk}
         GROUP BY si.id
        HAVING COUNT(a.id) >= 2
         ORDER BY si.id
        """,
        params,
    ).fetchall()

    n = {"si_seen": 0, "si_skip_noraw": 0, "si_skip_mismatch": 0, "si_done": 0,
         "assets_changed": 0, "assets_skip_corrected": 0, "minio_fail": 0}
    t0 = time.time()

    for si in si_rows:
        if args.limit and n["si_seen"] >= args.limit:
            break
        n["si_seen"] += 1

        assets = conn.execute(
            """
            SELECT id AS aid, crop_index, storage_path AS crop_sp, detection_method
              FROM image_assets
             WHERE source_image_id = ? AND storage_status='present'
             ORDER BY crop_index
            """,
            (si["si_id"],),
        ).fetchall()

        raw_p = _raw_local_path(si["raw_sp"])
        if not raw_p.exists():
            n["si_skip_noraw"] += 1
            continue
        bgr = cv2.imread(str(raw_p))
        if bgr is None:
            n["si_skip_noraw"] += 1
            continue

        dets = detect_circles_multi(bgr)
        accepted = [d for d in dets if d.accepted]
        # Mapping par ordre : il FAUT autant de cercles acceptés que d'assets.
        if len(accepted) != len(assets):
            n["si_skip_mismatch"] += 1
            continue

        for asset, det in zip(assets, accepted):
            method0 = asset["detection_method"] or ""
            # ``detect_circles_multi`` produit nativement des methods contenant
            # 'refine'/'polish' (sa pipeline interne) → on ne peut pas s'en servir
            # comme marqueur. On tague la correction avec '+lotcrop'.
            if "lotcrop" in method0 and not args.force:
                n["assets_skip_corrected"] += 1
                continue
            res = _crop_mask_resize_float(bgr, det.cx, det.cy, det.r, det.method)
            if res.image is None:
                continue
            n["assets_changed"] += 1
            if not args.commit:
                continue

            ok, buf = cv2.imencode(".png", res.image)
            if not ok:
                continue
            data = buf.tobytes()
            # 1. cache local (overwrite même storage_path)
            cp = _crop_local_path(asset["crop_sp"])
            cp.parent.mkdir(parents=True, exist_ok=True)
            cp.write_bytes(data)
            # 2. MinIO write-through (best-effort)
            if upload_through is not None:
                try:
                    upload_through("enrichment-crops", asset["crop_sp"], data)
                except Exception:  # noqa: BLE001
                    n["minio_fail"] += 1
            # 3. DB : bbox per-pièce + method nettoyé (sans refine) + dims + phash
            bbox = {"x": float(det.cx - det.r), "y": float(det.cy - det.r),
                    "w": float(2 * det.r), "h": float(2 * det.r)}
            conn.execute(
                "UPDATE image_assets SET bbox_json=?, detection_method=?, "
                "width=?, height=?, phash=? WHERE id=?",
                (json.dumps(bbox), det.method + "+lotcrop", res.image.shape[1],
                 res.image.shape[0], compute_phash(res.image), asset["aid"]),
            )
        n["si_done"] += 1
        if args.commit and n["si_done"] % 50 == 0:
            conn.commit()
            print(f"  {n['si_done']} images traitées ({time.time()-t0:.0f}s)", flush=True)

    if args.commit:
        conn.commit()
    conn.close()
    mode = "COMMIT" if args.commit else "DRY-RUN"
    print(f"\n[{mode}] {n}")
    print(f"durée {time.time()-t0:.0f}s")


if __name__ == "__main__":
    main()
