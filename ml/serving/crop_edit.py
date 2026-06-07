"""Cœur du re-crop manuel, keyé par ``asset_id``.

Historiquement la logique vivait inline dans ``review_queue_routes`` et était
keyée par ``review_id`` (l'éditeur de cercle s'ouvrait depuis la review queue).
Le re-crop est en réalité une opération sur l'ASSET, pas sur la review : la
page coin-detail veut recadrer une vignette en place, sans passer par la queue.

Ce module porte les deux primitives keyées asset :
  - ``load_crop_edit_context`` : raw + cercle de départ pour l'éditeur.
  - ``apply_manual_crop``      : écrase le crop (cache + MinIO + DB) au format prod.

Les deux routers (review keyé review_id, coins keyé asset_id) délèguent ici —
zéro divergence de format ni de comportement entre les deux points d'entrée.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path

import cv2
from fastapi import HTTPException

from store import Store

logger = logging.getLogger(__name__)


@dataclass
class CropEditContextData:
    """Contexte de l'éditeur de cercle (px NATIFS du raw)."""

    asset_id: str
    source: str
    source_image_id: str
    raw_storage_path: str
    raw_width: int | None
    raw_height: int | None
    hint: dict | None  # {cx, cy, r} reconstruit depuis la bbox actuelle, ou None


@dataclass
class ManualCropData:
    """Résultat d'un re-crop manuel appliqué."""

    asset_id: str
    cx: float
    cy: float
    r: float
    bbox: dict
    width: int
    height: int
    detection_method: str
    png_bytes: bytes
    minio_ok: bool
    dino_recomputed: bool


@dataclass
class NewCropData:
    """Résultat d'un add-crop manuel (nouvel asset créé)."""

    asset_id: str
    review_id: str
    source_image_id: str
    crop_index: int
    bbox: dict
    width: int
    height: int
    phash: int | None
    storage_path: str
    candidate_eurio_ids: list[dict]
    minio_ok: bool
    dino_recomputed: bool


def _hint_from_bbox(bbox_json: str | None) -> dict | None:
    """Reconstruit le cercle de départ (centre + rayon) depuis la bbox carrée."""
    if not bbox_json:
        return None
    try:
        d = json.loads(bbox_json)
        w, h = float(d.get("w", 0)), float(d.get("h", 0))
        if w > 0 and h > 0:
            return {
                "cx": float(d.get("x", 0)) + w / 2.0,
                "cy": float(d.get("y", 0)) + h / 2.0,
                "r": (w + h) / 4.0,  # moyenne des demi-côtés (bbox carrée)
            }
    except (json.JSONDecodeError, TypeError):
        return None
    return None


def load_crop_edit_context(store: Store, asset_id: str) -> CropEditContextData:
    """Charge le raw + le cercle de départ pour l'éditeur, depuis un asset_id."""
    conn = store._connection()  # noqa: SLF001
    row = conn.execute(
        """
        SELECT a.id AS asset_id, a.bbox_json,
               si.id AS source_image_id, si.source AS source,
               si.width AS raw_width, si.height AS raw_height,
               si.storage_path AS raw_storage_path
          FROM image_assets a
          JOIN source_images si ON si.id = a.source_image_id
         WHERE a.id = ?
        """,
        (asset_id,),
    ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Asset not found.")
    if not row["raw_storage_path"]:
        raise HTTPException(status_code=410, detail="Raw image unavailable.")

    return CropEditContextData(
        asset_id=row["asset_id"],
        source=row["source"],
        source_image_id=row["source_image_id"],
        raw_storage_path=row["raw_storage_path"],
        raw_width=row["raw_width"],
        raw_height=row["raw_height"],
        hint=_hint_from_bbox(row["bbox_json"]),
    )


def apply_manual_crop(
    store: Store, asset_id: str, cx: float, cy: float, r: float,
) -> ManualCropData:
    """Re-croppe l'asset depuis un cercle (cx,cy,r) en px natifs du raw, écrase
    le crop (cache + MinIO + DB) au format prod via ``_crop_mask_resize_float``.

    ``eurio_id``, ``resolution_status``, ``training_eligible`` NON touchés :
    re-crop ≠ décision. Recompute Dino best-effort (la suggestion d'avant
    pointait sur le mauvais cadrage)."""
    from vision.normalize_snap import _crop_mask_resize_float
    from sources._base.phash import compute_phash
    from shared.storage.local_cache import cache_path_for, local_path, upload_through

    conn = store._connection()  # noqa: SLF001
    row = conn.execute(
        """
        SELECT a.id AS asset_id, a.storage_path AS crop_storage_path,
               a.detection_method,
               si.source AS source, si.storage_path AS raw_storage_path,
               si.target_eurio_id AS target_eurio_id
          FROM image_assets a
          JOIN source_images si ON si.id = a.source_image_id
         WHERE a.id = ?
        """,
        (asset_id,),
    ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Asset not found.")
    if not row["crop_storage_path"] or not row["raw_storage_path"]:
        raise HTTPException(status_code=410, detail="Asset storage unavailable.")

    # 1. Charge le raw (cache local, read-through MinIO).
    try:
        raw_p = local_path("enrichment-raws", row["raw_storage_path"])
    except FileNotFoundError as exc:
        raise HTTPException(status_code=410, detail=f"Raw missing: {exc}") from exc
    bgr = cv2.imread(str(raw_p), cv2.IMREAD_COLOR)
    if bgr is None or bgr.size == 0:
        raise HTTPException(status_code=422, detail="Raw image unreadable.")

    H, W = bgr.shape[:2]
    if cx > W or cy > H:
        raise HTTPException(
            status_code=422,
            detail=f"Circle centre ({cx},{cy}) outside raw {W}×{H}.",
        )

    # 2. Crop AU MÊME FORMAT que la prod (marge 0.02, masque dur, 224).
    res = _crop_mask_resize_float(bgr, cx, cy, r, method="manual")
    if res.image is None:
        raise HTTPException(
            status_code=422,
            detail=f"Empty crop ({res.debug.get('error', 'unknown')}).",
        )

    ok, buf = cv2.imencode(".png", res.image)
    if not ok:
        raise HTTPException(status_code=500, detail="PNG encode failed.")
    png_bytes = buf.tobytes()

    # 3. Écriture (calque recrop_ebay_refine) : cache local OVERWRITE direct
    #    (upload_through skip le cache si le fichier existe), puis MinIO.
    crop_sp = row["crop_storage_path"]
    cache_p = cache_path_for("enrichment-crops", crop_sp)
    cache_p.parent.mkdir(parents=True, exist_ok=True)
    cache_p.write_bytes(png_bytes)
    minio_ok = True
    try:
        upload_through("enrichment-crops", crop_sp, png_bytes)
    except Exception as exc:  # noqa: BLE001
        minio_ok = False
        logger.warning("[manual-crop] MinIO write-through failed for %s: %s",
                       crop_sp, exc)

    # 4. DB : nouveau cercle + method 'manual' + dims + phash.
    bbox = {"x": cx - r, "y": cy - r, "w": 2 * r, "h": 2 * r}
    new_h, new_w = res.image.shape[0], res.image.shape[1]
    conn.execute(
        "UPDATE image_assets SET bbox_json = ?, detection_method = 'manual', "
        "width = ?, height = ?, phash = ? WHERE id = ?",
        (json.dumps(bbox), new_w, new_h, compute_phash(res.image), row["asset_id"]),
    )
    conn.commit()

    logger.info("[manual-crop] asset=%s cx=%.1f cy=%.1f r=%.1f minio=%s",
                row["asset_id"], cx, cy, r, minio_ok)

    # Recompute Dino sur le crop recadré (best-effort : un échec ne casse pas
    # le re-crop déjà committé).
    dino_recomputed = False
    try:
        from sources._base.steps.auto_validate import predict_and_persist_one

        target_eid = row["target_eurio_id"]
        target_country = (
            target_eid[:2].lower() if target_eid and len(target_eid) >= 2 else None
        )
        pred = predict_and_persist_one(
            store=store,
            asset_id=row["asset_id"],
            crop_path=cache_p,
            target_country=target_country,
        )
        dino_recomputed = pred is not None
    except Exception as exc:  # noqa: BLE001 — suggestion layer, never fatal
        logger.warning("[manual-crop] Dino recompute failed for asset=%s: %s",
                       row["asset_id"], exc)

    return ManualCropData(
        asset_id=row["asset_id"],
        cx=cx, cy=cy, r=r,
        bbox=bbox,
        width=new_w, height=new_h,
        detection_method="manual",
        png_bytes=png_bytes,
        minio_ok=minio_ok,
        dino_recomputed=dino_recomputed,
    )


def _group_candidates_from_payload(raw_payload_json: str | None,
                                   target_eurio_id: str | None) -> list[dict]:
    """Candidats seed pour un crop ajouté à la main : reprend les
    ``group_candidates`` du payload eBay (comme detect_crop), fallback sur la
    cible du listing pour qu'au moins celle-ci soit proposée dans la review."""
    cands: list[str] = []
    if raw_payload_json:
        try:
            payload = json.loads(raw_payload_json)
            raw = payload.get("group_candidates") if isinstance(payload, dict) else None
            if isinstance(raw, list):
                cands = [str(x) for x in raw if isinstance(x, str)]
        except (json.JSONDecodeError, TypeError):
            pass
    if not cands and target_eurio_id:
        cands = [target_eurio_id]
    return [{"eurio_id": eid} for eid in cands]


def create_manual_crop(
    store: Store, source_image_id: str, cx: float, cy: float, r: float,
) -> NewCropData:
    """Crée un NOUVEAU crop (add-crop) sur une source_image depuis un cercle
    (cx,cy,r) en px natifs du raw. Mirroir de ``detect_crop`` pour UN crop :
    crop format prod → upload cache+MinIO → INSERT image_assets → Dino →
    enqueue review (kind lot/single). Scopé au nouvel asset : les crops frères
    ne sont jamais touchés (cf. garde recrop multi-pièces).

    Sert au rattrapage des pièces que la détection a ratées (depuis un cercle
    détecté cliqué OU un cercle tracé à la main — même chemin)."""
    import uuid

    from vision.normalize_snap import _crop_mask_resize_float
    from sources._base.phash import compute_phash
    from sources._base.storage import crop_key, crop_cache_path
    from sources._base.dedup import ImageAssetRow, upsert_image_asset
    from sources._base.steps.enqueue import _compute_priority, _kind_for_source_image
    from training.foundation.review_lanes import compute_lane
    from shared.storage.local_cache import upload_through, local_path
    from store import emit_state_event

    conn = store._connection()  # noqa: SLF001
    si = conn.execute(
        """
        SELECT id, source, storage_path, run_id, target_eurio_id,
               raw_payload_json, is_lot_suspected
          FROM source_images WHERE id = ?
        """,
        (source_image_id,),
    ).fetchone()
    if si is None:
        raise HTTPException(status_code=404, detail="Source image not found.")
    if not si["storage_path"]:
        raise HTTPException(status_code=410, detail="Raw image unavailable.")

    try:
        raw_p = local_path("enrichment-raws", si["storage_path"])
    except FileNotFoundError as exc:
        raise HTTPException(status_code=410, detail=f"Raw missing: {exc}") from exc
    bgr = cv2.imread(str(raw_p), cv2.IMREAD_COLOR)
    if bgr is None or bgr.size == 0:
        raise HTTPException(status_code=422, detail="Raw image unreadable.")
    H, W = bgr.shape[:2]
    if cx > W or cy > H or cx < 0 or cy < 0:
        raise HTTPException(
            status_code=422,
            detail=f"Circle centre ({cx},{cy}) outside raw {W}×{H}.",
        )

    res = _crop_mask_resize_float(bgr, cx, cy, r, method="manual_add")
    if res.image is None:
        raise HTTPException(
            status_code=422,
            detail=f"Empty crop ({res.debug.get('error', 'unknown')}).",
        )
    ok, buf = cv2.imencode(".png", res.image)
    if not ok:
        raise HTTPException(status_code=500, detail="PNG encode failed.")
    png_bytes = buf.tobytes()

    crop_index = (conn.execute(
        "SELECT COALESCE(MAX(crop_index), -1) AS m FROM image_assets "
        "WHERE source_image_id = ?",
        (source_image_id,),
    ).fetchone()["m"]) + 1

    asset_id = uuid.uuid4().hex
    run_id = si["run_id"]
    # run_id peut être NULL (vieux source_images) → fallback 'manual' dans la clé.
    storage_key = crop_key(si["source"], run_id or "manual", asset_id)
    cache_p = crop_cache_path(si["source"], run_id or "manual", asset_id)
    cache_p.parent.mkdir(parents=True, exist_ok=True)
    cache_p.write_bytes(png_bytes)
    minio_ok = True
    try:
        upload_through("enrichment-crops", storage_key, png_bytes)
    except Exception as exc:  # noqa: BLE001
        minio_ok = False
        logger.warning("[add-crop] MinIO write-through failed for %s: %s",
                       storage_key, exc)

    phash_value = compute_phash(res.image)
    bbox = {"x": cx - r, "y": cy - r, "w": 2 * r, "h": 2 * r}
    new_h, new_w = res.image.shape[0], res.image.shape[1]
    candidate_list = _group_candidates_from_payload(
        si["raw_payload_json"], si["target_eurio_id"])

    upsert_image_asset(
        conn,
        ImageAssetRow(
            id=asset_id,
            source_image_id=source_image_id,
            crop_index=crop_index,
            bbox=bbox,
            detection_method="manual_add",
            resolution_status="needs_review",
            candidate_eurio_ids=candidate_list or None,
            phash=phash_value,
            storage_path=storage_key,
            width=new_w,
            height=new_h,
            run_id=run_id,
        ),
    )
    conn.execute(
        "UPDATE image_assets SET storage_status='present' WHERE id = ?",
        (asset_id,),
    )
    emit_state_event(
        conn, asset_id=asset_id, to_state="detected", actor="human",
        reason="manual_add_crop", target_eurio_id=si["target_eurio_id"],
        run_id=run_id,
    )
    conn.commit()

    # Dino best-effort (suggestion layer, jamais fatal) — avant compute_lane
    # pour que la lane soit informée.
    dino_recomputed = False
    try:
        from sources._base.steps.auto_validate import predict_and_persist_one
        target_eid = si["target_eurio_id"]
        target_country = (
            target_eid[:2].lower() if target_eid and len(target_eid) >= 2 else None
        )
        pred = predict_and_persist_one(
            store=store, asset_id=asset_id, crop_path=cache_p,
            target_country=target_country,
        )
        dino_recomputed = pred is not None
    except Exception as exc:  # noqa: BLE001
        logger.warning("[add-crop] Dino failed for asset=%s: %s", asset_id, exc)

    # Enqueue review (réplique l'INSERT de run_enqueue, scopé au nouvel asset —
    # les frères ont déjà leur row et ne sont pas touchés).
    kind = _kind_for_source_image(
        conn, source_image_id=source_image_id,
        is_lot_suspected=bool(si["is_lot_suspected"]),
    )
    priority = _compute_priority(target_eurio_id=si["target_eurio_id"])
    _verdict, lane = compute_lane(conn, asset_id)
    review_id = uuid.uuid4().hex
    conn.execute(
        """
        INSERT INTO review_queue (
          id, image_asset_id, priority, candidate_eurio_ids_json,
          kind, lane, status
        ) VALUES (?, ?, ?, ?, ?, ?, 'open')
        """,
        (review_id, asset_id, priority,
         json.dumps(candidate_list) if candidate_list else None, kind, lane),
    )
    emit_state_event(
        conn, asset_id=asset_id, to_state="queued", actor="human",
        reason="manual_add_enqueued", target_eurio_id=si["target_eurio_id"],
        run_id=run_id,
    )
    conn.commit()

    logger.info("[add-crop] asset=%s si=%s idx=%d kind=%s lane=%s minio=%s",
                asset_id, source_image_id, crop_index, kind, lane, minio_ok)

    return NewCropData(
        asset_id=asset_id,
        review_id=review_id,
        source_image_id=source_image_id,
        crop_index=crop_index,
        bbox=bbox,
        width=new_w,
        height=new_h,
        phash=phash_value,
        storage_path=storage_key,
        candidate_eurio_ids=candidate_list,
        minio_ok=minio_ok,
        dino_recomputed=dino_recomputed,
    )
