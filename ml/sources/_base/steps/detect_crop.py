"""Step 4 — Detect & crop.

Runs `scan.normalize_studio_path` on every freshly-downloaded raw,
writes the 224×224 crop to disk, computes a 64-bit pHash, and upserts
one `image_assets` row per crop. Re-runs are no-ops because the
`(source_image_id, crop_index)` UNIQUE on `image_assets` keeps the
write set empty when the crop already exists.

No silent fallback: if `normalize_studio` returns no image, the item
is left at `pipeline_state='downloaded'`, the run counter `n_errors`
is bumped, and a structured error message goes through the logger.
The failure is reprocessable on the next run.

Dedup layer 4 (pHash): after computing the hash we look for an
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
from scan.normalize_snap import normalize_studio_path

logger = logging.getLogger(__name__)

_PHASH_HAMMING_THRESHOLD = 4   # D-07


@dataclass
class DetectCropResult:
    n_crops_added: int
    n_skipped: int
    n_errors: int
    n_auto_phash: int
    crop_paths: list[Path]


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
            n_errors += 1
            run.bump(n_errors=1)
            continue

        # Idempotence check: skip if a crop_index=0 asset already
        # exists with its file present on disk.
        existing = conn.execute(
            """
            SELECT id, storage_path FROM image_assets
             WHERE source_image_id = ? AND crop_index = 0
            """,
            (sid,),
        ).fetchone()
        if existing and existing["storage_path"] and Path(existing["storage_path"]).is_file():
            n_skipped += 1
            crop_paths.append(Path(existing["storage_path"]))
            continue

        result = normalize_studio_path(raw)
        if result.image is None:
            logger.error(
                "[%s] normalize_studio FAILED source_ref=%s reason=%s debug=%s",
                source_id, source_ref, result.method, result.debug,
            )
            n_errors += 1
            run.bump(n_errors=1)
            continue

        crop_p = crop_path(source_id, source_ref, crop_index=0)
        crop_p.parent.mkdir(parents=True, exist_ok=True)
        ok = cv2.imwrite(str(crop_p), result.image)
        if not ok:
            logger.error(
                "[%s] cv2.imwrite FAILED source_ref=%s path=%s",
                source_id, source_ref, crop_p,
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
                crop_index=0,
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
        # Mirror n_crops_detected on the parent source_image.
        conn.execute(
            "UPDATE source_images SET n_crops_detected = 1 WHERE id = ?",
            (sid,),
        )
        set_discovery_pipeline_state(
            conn, source=source_id, source_ref=source_ref, state="cropped"
        )
        n_crops_added += 1
        crop_paths.append(crop_p)

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
