"""Step 4 — Detect & crop.

Runs `scan.normalize_listing_path` on every freshly-downloaded raw
(multi-Hough), writes the 224×224 crops to disk, computes a 64-bit
pHash per crop, and upserts one `image_assets` row per detected coin
(``crop_index = 0..N-1``). Re-runs skip a source_image entirely if it
already has at least one image_asset (the `(source_image_id, crop_index)`
UNIQUE plus the early-skip keep the write set empty).

No silent fallback: if `normalize_listing` returns 0 crops, the item
is left at `pipeline_state='downloaded'`, the run counter `n_errors`
is bumped, and a structured error message goes through the logger.
The failure is reprocessable on the next run.

Dedup layer 4 (pHash): after computing each crop's hash we look for an
existing `image_assets` row with `phash_match(phash, ?, 4)` AND a
resolved `eurio_id`. On a hit we copy `eurio_id` and set
`resolution_status='auto_phash'`.
"""

from __future__ import annotations

import logging
import sqlite3
from dataclasses import dataclass
from pathlib import Path

import cv2

from sources._base.dedup import ImageAssetRow, set_discovery_pipeline_state, upsert_image_asset
from sources._base.phash import compute_phash
from sources._base.run_logger import RunHandle
from sources._base.storage import crop_path
from scan.normalize_snap import (
    NormalizationResult, normalize_listing_path, normalize_studio_path,
)

logger = logging.getLogger(__name__)

_PHASH_HAMMING_THRESHOLD = 4   # D-07

# Crop strategy routing.
#
# - `studio` (Numista mirror, mock fixtures) : 1 raw = 1 coin, BG uniforme,
#   Otsu+contour est très précis. `normalize_studio` est la bonne pipeline
#   et reste appelée pour ces sources.
# - `listing` (eBay, catawiki, …) : 1 raw peut contenir 1..N pièces sur des
#   BG hétérogènes. `normalize_listing` (multi-Hough) émet 0..N crops.
#
# Map explicite : tout source non listé tombe en `listing` par défaut
# (= comportement multi-coin tolerant qui marche mieux dès qu'il y a du
# BG complexe).
_STUDIO_SOURCES: frozenset[str] = frozenset({"mock", "numista"})


def _crop_strategy(source_id: str) -> str:
    return "studio" if source_id in _STUDIO_SOURCES else "listing"


@dataclass
class DetectCropResult:
    n_crops_added: int
    n_skipped: int
    n_errors: int
    n_auto_phash: int
    crop_paths: list[Path]


# Called by: ml/sources/_base/orchestrator.py (step 5/8 — after download, dispatches studio vs listing crop strategy)
def run_detect_crop(
    *,
    conn: sqlite3.Connection,
    run: RunHandle,
    source_id: str,
    source_image_ids: dict[str, str],
) -> DetectCropResult:
    n_crops_added = 0
    n_skipped = 0
    n_errors = 0
    n_auto_phash = 0
    crop_paths: list[Path] = []

    for source_ref, sid in source_image_ids.items():
        row = conn.execute(
            "SELECT id, storage_path FROM source_images WHERE id = ?", (sid,)
        ).fetchone()
        if row is None or not row["storage_path"]:
            continue
        raw = Path(row["storage_path"])
        if not raw.is_file():
            logger.error(
                "[%s] detect: missing raw on disk for source_ref=%s path=%s",
                source_id, source_ref, raw,
            )
            conn.execute(
                "UPDATE source_images SET crop_status='error', crop_error=? WHERE id=?",
                (f"raw missing on disk: {raw}", sid),
            )
            n_errors += 1
            run.bump(n_errors=1)
            continue

        # Idempotence : skip si au moins un image_asset existe déjà pour ce
        # source_image (avec son fichier sur disque). Le multi-crop émet
        # crop_index=0..N-1 ; on ne re-detect pas une image déjà processée.
        existing_count = conn.execute(
            """
            SELECT COUNT(*) AS n FROM image_assets
             WHERE source_image_id = ? AND storage_path IS NOT NULL
            """,
            (sid,),
        ).fetchone()
        if existing_count and existing_count["n"] > 0:
            # Verify at least one file exists on disk before claiming skip.
            paths_row = conn.execute(
                "SELECT storage_path FROM image_assets WHERE source_image_id = ?",
                (sid,),
            ).fetchall()
            on_disk = [Path(r["storage_path"]) for r in paths_row
                       if r["storage_path"] and Path(r["storage_path"]).is_file()]
            if on_disk:
                n_skipped += 1
                crop_paths.extend(on_disk)
                conn.execute(
                    "UPDATE source_images SET crop_status=COALESCE(crop_status,'success') WHERE id=?",
                    (sid,),
                )
                continue

        if _crop_strategy(source_id) == "studio":
            single = normalize_studio_path(raw)
            results: list[NormalizationResult] = [single] if single.image is not None else []
        else:
            results = normalize_listing_path(raw)
        if not results:
            logger.error(
                "[%s] detect (%s) returned 0 crops source_ref=%s",
                source_id, _crop_strategy(source_id), source_ref,
            )
            conn.execute(
                """
                UPDATE source_images
                   SET crop_status      = 'zero_crops',
                       crop_error       = ?,
                       n_crops_detected = 0
                 WHERE id = ?
                """,
                (f"normalize_{_crop_strategy(source_id)} returned 0 crops", sid),
            )
            n_errors += 1
            run.bump(n_errors=1)
            continue

        crops_for_image = 0
        for crop_index, result in enumerate(results):
            crop_p = crop_path(source_id, source_ref, crop_index=crop_index)
            crop_p.parent.mkdir(parents=True, exist_ok=True)
            ok = cv2.imwrite(str(crop_p), result.image)
            if not ok:
                logger.error(
                    "[%s] cv2.imwrite FAILED source_ref=%s crop_index=%d path=%s",
                    source_id, source_ref, crop_index, crop_p,
                )
                n_errors += 1
                run.bump(n_errors=1)
                continue

            phash_value = compute_phash(result.image)

            # Dedup C4: look for an already-resolved asset within Hamming ≤ 4.
            match = conn.execute(
                """
                SELECT eurio_id FROM image_assets
                 WHERE eurio_id IS NOT NULL
                   AND phash IS NOT NULL
                   AND phash_match(phash, ?, ?) = 1
                 ORDER BY hamming(phash, ?) ASC
                 LIMIT 1
                """,
                (phash_value, _PHASH_HAMMING_THRESHOLD, phash_value),
            ).fetchone()
            eurio_id = match["eurio_id"] if match else None
            status = "auto_phash" if eurio_id else "pending_match"
            if eurio_id:
                n_auto_phash += 1

            upsert_image_asset(
                conn,
                ImageAssetRow(
                    source_image_id=sid,
                    crop_index=crop_index,
                    detection_method=result.method,
                    eurio_id=eurio_id,
                    resolution_status=status,
                    phash=phash_value,
                    storage_path=str(crop_p),
                    width=result.image.shape[1],
                    height=result.image.shape[0],
                    run_id=run.run_id,
                ),
            )
            n_crops_added += 1
            crops_for_image += 1
            crop_paths.append(crop_p)

        if crops_for_image > 0:
            conn.execute(
                """
                UPDATE source_images
                   SET n_crops_detected = ?,
                       crop_status      = 'success',
                       crop_error       = NULL
                 WHERE id = ?
                """,
                (crops_for_image, sid),
            )
            set_discovery_pipeline_state(
                conn, source=source_id, source_ref=source_ref, state="cropped"
            )

    run.bump(n_crops_added=n_crops_added, n_auto_resolved=n_auto_phash)
    logger.info(
        "[%s] detect → %d crops / %d skipped / %d errors / %d auto_phash",
        source_id, n_crops_added, n_skipped, n_errors, n_auto_phash,
    )
    return DetectCropResult(
        n_crops_added=n_crops_added,
        n_skipped=n_skipped,
        n_errors=n_errors,
        n_auto_phash=n_auto_phash,
        crop_paths=crop_paths,
    )
