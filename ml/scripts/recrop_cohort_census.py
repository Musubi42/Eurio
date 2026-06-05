"""recrop_cohort_census.py — récupère les zéro-crops d'une cohorte en mode census+gate.

ADDITIF & SÛR (R0) : ne touche QUE les source_images eBay de la cohorte qui n'ont
**aucun** crop présent (`image_assets` storage_status=present = 0) — typiquement les
`crop_status='zero_crops'`. Aucune écriture sur des crops existants / déjà reviewés
(`training_eligible`). Les crops récupérés sont créés en `pending_match`/`auto_phash`,
`training_eligible=0` → ils passent par la review humaine comme tout crop pipeline.

Détection = mode census (`EURIO_CENSUS_DETECT=1`) + gate anti-fragment DINO
(`EURIO_CENSUS_FRAGMENT_TAU`, défaut 0.45) : on ne récupère que des **faces propres**,
pas le flot de fragments (cf. census-detector-design.md §8-9).

Persistance identique au pipeline (`sources/_base/steps/detect_crop.py`) :
crop_key → cache + MinIO (upload_through) → upsert_image_asset + storage_status=present,
dédup phash (Hamming ≤4) pour auto-résoudre l'eurio_id, bbox reconstruite pour la
forensics admin. run_id traçable `census-recover-<cohort>`.

Dry-run par défaut (compte seulement). `--commit` pour écrire.

Usage (depuis ml/, PYTHONPATH=.):
  .venv/bin/python scripts/recrop_cohort_census.py --cohort b0299ca0252b           # dry
  .venv/bin/python scripts/recrop_cohort_census.py --cohort b0299ca0252b --commit  # écrit
"""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import uuid
from pathlib import Path

import cv2

cv2.setNumThreads(1)
ML_DIR = Path(__file__).resolve().parents[1]
DB_PATH = ML_DIR / "state" / "eurio.db"
_PHASH_HAMMING_THRESHOLD = 4   # D-07, identique à detect_crop


def _group_candidates(raw_payload_json: str | None) -> list[str]:
    if not raw_payload_json:
        return []
    try:
        payload = json.loads(raw_payload_json)
    except (json.JSONDecodeError, TypeError, ValueError):
        return []
    cands = payload.get("group_candidates") if isinstance(payload, dict) else None
    return [str(x) for x in cands if isinstance(x, str)] if isinstance(cands, list) else []


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cohort", default="b0299ca0252b")
    ap.add_argument("--commit", action="store_true", help="écrit (défaut = dry-run)")
    ap.add_argument("--tau", default=None, help="override EURIO_CENSUS_FRAGMENT_TAU")
    ap.add_argument("--limit", type=int, default=0, help="cap raws/classe (0=tous)")
    args = ap.parse_args()

    os.environ["EURIO_CENSUS_DETECT"] = "1"
    if args.tau is not None:
        os.environ["EURIO_CENSUS_FRAGMENT_TAU"] = args.tau
    run_id = f"census-recover-{args.cohort}"

    from scan.normalize_snap import _census_fragment_tau, normalize_listing
    from sources._base.dedup import ImageAssetRow, upsert_image_asset
    from sources._base.phash import compute_phash
    from sources._base.storage import crop_cache_path, crop_key
    from state.store import _register_phash_udfs
    from storage.local_cache import local_path, upload_through

    tau = _census_fragment_tau()   # vraie τ appliquée par le gate (source unique)

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    _register_phash_udfs(conn)   # hamming() / phash_match() UDFs (dédup C4)
    row = conn.execute("SELECT eurio_ids_json FROM experiment_cohorts WHERE id = ?",
                       (args.cohort,)).fetchone()
    classes = json.loads(row["eurio_ids_json"]) if row and row["eurio_ids_json"] else []
    mode = "COMMIT" if args.commit else "DRY-RUN"
    print(f"[{mode}] cohorte {args.cohort} : {len(classes)} classes, τ={tau}, run_id={run_id}\n")

    T = dict(scanned=0, recovered=0, crops=0, auto_phash=0)
    print(f"{'classe':45s}{'cand0':>7}{'récup':>7}{'crops':>7}")
    print("-" * 66)
    for cls in sorted(classes):
        rows = conn.execute(
            """
            SELECT si.id, si.storage_path, si.raw_payload_json
              FROM source_images si
             WHERE si.source = 'ebay' AND si.target_eurio_id = ?
               AND si.storage_path IS NOT NULL
               AND (SELECT COUNT(*) FROM image_assets ia
                     WHERE ia.source_image_id = si.id
                       AND ia.storage_status = 'present') = 0
            """,
            (cls,),
        ).fetchall()
        if args.limit:
            rows = rows[: args.limit]
        c = dict(scanned=0, recovered=0, crops=0)
        for r in rows:
            try:
                raw = local_path("enrichment-raws", r["storage_path"])
            except FileNotFoundError:
                continue
            bgr = cv2.imread(str(raw), cv2.IMREAD_COLOR)
            if bgr is None:
                continue
            c["scanned"] += 1
            results = [res for res in normalize_listing(bgr) if res.image is not None]
            if not results:
                continue
            c["recovered"] += 1
            c["crops"] += len(results)
            cands = _group_candidates(r["raw_payload_json"])
            if not args.commit:
                continue
            for idx, res in enumerate(results):
                asset_id = uuid.uuid4().hex
                storage_key = crop_key("ebay", run_id, asset_id)
                cache_p = crop_cache_path("ebay", run_id, asset_id)
                cache_p.parent.mkdir(parents=True, exist_ok=True)
                if not cv2.imwrite(str(cache_p), res.image):
                    continue
                upload_through("enrichment-crops", storage_key, cache_p.read_bytes())
                phash_value = compute_phash(res.image)
                match = conn.execute(
                    """
                    SELECT eurio_id FROM image_assets
                     WHERE eurio_id IS NOT NULL AND phash IS NOT NULL
                       AND phash_match(phash, ?, ?) = 1
                     ORDER BY hamming(phash, ?) ASC LIMIT 1
                    """,
                    (phash_value, _PHASH_HAMMING_THRESHOLD, phash_value),
                ).fetchone()
                eurio_id = match["eurio_id"] if match else None
                status = "auto_phash" if eurio_id else "pending_match"
                if eurio_id:
                    T["auto_phash"] += 1
                bbox = None
                if res.r and res.r > 0:
                    bbox = {"x": float(res.cx - res.r), "y": float(res.cy - res.r),
                            "w": float(2 * res.r), "h": float(2 * res.r)}
                upsert_image_asset(conn, ImageAssetRow(
                    id=asset_id, source_image_id=r["id"], crop_index=idx, bbox=bbox,
                    detection_method=res.method, eurio_id=eurio_id,
                    resolution_status=status,
                    candidate_eurio_ids=([{"eurio_id": e} for e in cands] if cands else None),
                    phash=phash_value, storage_path=storage_key,
                    width=res.image.shape[1], height=res.image.shape[0], run_id=run_id,
                ))
                conn.execute("UPDATE image_assets SET storage_status='present' WHERE id=?",
                             (asset_id,))
            conn.execute(
                "UPDATE source_images SET n_crops_detected=?, crop_status='success', "
                "crop_error=NULL WHERE id=?", (len(results), r["id"]))
        # Commit par classe : transaction courte (évite les locks SQLite avec
        # l'API admin) et reprise propre (le scope additif re-skippe les raws déjà
        # faits si on relance après interruption).
        if args.commit:
            conn.commit()
        if c["scanned"]:
            print(f"{cls[:45]:45s}{c['scanned']:>7}{c['recovered']:>7}{c['crops']:>7}",
                  flush=True)
        for k in c:
            T[k] += c[k]

    if args.commit:
        conn.commit()
    print("-" * 66)
    print(f"{'TOTAL':45s}{T['scanned']:>7}{T['recovered']:>7}{T['crops']:>7}")
    print(f"\n{'[COMMITTÉ]' if args.commit else '[DRY-RUN — rien écrit]'} "
          f"candidats zéro-crop {T['scanned']} → {T['recovered']} raws récupérés, "
          f"+{T['crops']} crops ({T['auto_phash']} auto-phash) → review queue (training_eligible=0)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
