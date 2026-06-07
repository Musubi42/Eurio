"""recrop_zero — récupère les zéro-crops d'UNE pièce en mode census+gate.

Cœur partagé (R0, source unique) entre le CLI batch
``scripts/recrop_cohort_census.py`` (boucle sur les classes d'une cohorte) et
l'endpoint admin ``POST /lab/cohorts/{id}/coins/{eurio_id}/recrop-zero`` (une
pièce, en arrière-plan).

ADDITIF & SÛR : ne touche QUE les ``source_images`` eBay de la pièce sans aucun
crop présent (``image_assets`` storage_status=present = 0). Aucune écriture sur
des crops existants / déjà reviewés (``training_eligible``). Crops récupérés créés
en ``pending_match``/``auto_phash``, ``training_eligible=0`` → review humaine
normale. Détection = census + gate anti-fragment DINO (``normalize_listing(census=
True)``). Persistance identique au pipeline (crop_key → cache+MinIO → upsert +
storage_status=present, dédup phash Hamming ≤4, bbox reconstruite). Idempotent : le
scope additif re-skippe les raws déjà cropés si on relance.
"""

from __future__ import annotations

import json
import sqlite3
import uuid
from pathlib import Path

import cv2

cv2.setNumThreads(1)  # évite l'oversubscription (recrop tourne hors du thread principal)

_PHASH_HAMMING_THRESHOLD = 4  # D-07, identique à detect_crop


def _group_candidates(raw_payload_json: str | None) -> list[str]:
    if not raw_payload_json:
        return []
    try:
        payload = json.loads(raw_payload_json)
    except (json.JSONDecodeError, TypeError, ValueError):
        return []
    cands = payload.get("group_candidates") if isinstance(payload, dict) else None
    return [str(x) for x in cands if isinstance(x, str)] if isinstance(cands, list) else []


def recrop_zero_for_coin(
    conn: sqlite3.Connection,
    eurio_id: str,
    *,
    run_id: str,
    commit: bool = False,
    limit: int = 0,
    progress_cb=None,
) -> dict:
    """Re-crope les raws eBay zéro-crop de ``eurio_id``. Retourne les compteurs
    ``{scanned, recovered, crops, auto_phash}``. ``commit=False`` = dry-run (compte
    seulement). ``conn`` doit avoir les UDFs phash enregistrées
    (``_register_phash_udfs``). Imports lourds (cv2/scan/storage) en lazy."""
    from vision.normalize_snap import normalize_listing
    from sources._base.dedup import ImageAssetRow, upsert_image_asset
    from sources._base.phash import compute_phash
    from sources._base.storage import crop_cache_path, crop_key
    from shared.storage.local_cache import local_path, upload_through

    rows = conn.execute(
        """
        SELECT si.id, si.source_ref, si.storage_path, si.raw_payload_json
          FROM source_images si
         WHERE si.source = 'ebay' AND si.target_eurio_id = ?
           AND si.storage_path IS NOT NULL
           AND (SELECT COUNT(*) FROM image_assets ia
                 WHERE ia.source_image_id = si.id
                   AND ia.storage_status = 'present') = 0
        """,
        (eurio_id,),
    ).fetchall()
    if limit:
        rows = rows[:limit]

    counts = dict(scanned=0, recovered=0, crops=0, auto_phash=0)
    enqueued: dict[str, str] = {}  # source_ref → sid des raws ayant produit des crops
    for i, r in enumerate(rows):
        if progress_cb is not None:
            progress_cb(i)  # n raws traités (0-based → reflète l'avancement)
        try:
            raw = local_path("enrichment-raws", r["storage_path"])
        except FileNotFoundError:
            continue
        bgr = cv2.imread(str(raw), cv2.IMREAD_COLOR)
        if bgr is None:
            continue
        counts["scanned"] += 1
        results = [res for res in normalize_listing(bgr, census=True) if res.image is not None]
        if not results:
            continue
        counts["recovered"] += 1
        counts["crops"] += len(results)
        cands = _group_candidates(r["raw_payload_json"])
        if not commit:
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
            matched_eurio_id = match["eurio_id"] if match else None
            status = "auto_phash" if matched_eurio_id else "pending_match"
            if matched_eurio_id:
                counts["auto_phash"] += 1
            bbox = None
            if res.r and res.r > 0:
                bbox = {"x": float(res.cx - res.r), "y": float(res.cy - res.r),
                        "w": float(2 * res.r), "h": float(2 * res.r)}
            upsert_image_asset(conn, ImageAssetRow(
                id=asset_id, source_image_id=r["id"], crop_index=idx, bbox=bbox,
                detection_method=res.method, eurio_id=matched_eurio_id,
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
        enqueued[r["source_ref"]] = r["id"]
    # Fix T1 : clôturer la pipeline pour les crops récupérés (resolve → enqueue)
    # sinon ils restent en 'pending_match' SANS review_queue (= orphelins,
    # invisibles à la review). Réutilise les steps canoniques. RunHandle minimal
    # (run_id recrop hors source_runs → bump no-op, sans effet de bord).
    if commit and enqueued:
        from sources._base.run_logger import RunHandle
        from sources._base.steps.enqueue import run_enqueue
        from sources._base.steps.resolve import run_resolve
        handle = RunHandle(run_id=run_id, source="ebay", _conn=conn)
        run_resolve(conn=conn, run=handle, source_id="ebay", source_image_ids=enqueued)
        run_enqueue(conn=conn, run=handle, source_id="ebay", source_image_ids=enqueued)
    if commit:
        conn.commit()
    return counts
