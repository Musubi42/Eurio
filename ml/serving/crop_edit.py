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

from store import Store, emit_field_event, resolve_db_readonly

logger = logging.getLogger(__name__)


@dataclass
class CropEditContextData:
    """Contexte de l'éditeur de cercle (px NATIFS du raw)."""

    asset_id: str
    source: str
    source_image_id: str
    raw_storage_path: str
    # Clé MinIO du crop actuel — nécessaire pour SIGNER son URL (lot 6b) : le
    # chemin relatif `/sources/…/file` n'est servi que par l'app full.
    crop_storage_path: str | None
    raw_width: int | None
    raw_height: int | None
    hint: dict | None  # {cx, cy, r} reconstruit depuis la bbox actuelle, ou None
    # {cx, cy, r} : cercle dominant détecté dans le raw, proposé comme point de
    # départ de l'éditeur quand la source est mono-pièce (le crop stocké est
    # souvent sous-dimensionné/excentré sur les macros eBay). None sinon.
    suggested: dict | None = None


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


def _dominant_circle(raw_storage_path: str) -> dict | None:
    """Cercle dominant du raw via Hough (le plus grand cercle bien dimensionné)
    — point de départ de l'éditeur quand le crop détecté est sous-dimensionné /
    excentré (macro eBay où la pièce remplit le cadre). Heuristique LOCALE
    « pièce qui remplit le cadre » : ne relance PAS la pipeline de crop. None si
    raw illisible ou aucun cercle ≥ 0.30·petit-côté trouvé (pièce trop petite /
    cadrage atypique → on garde le hint bbox)."""
    from shared.storage.local_cache import local_path
    try:
        p = local_path("enrichment-raws", raw_storage_path)
    except FileNotFoundError:
        return None
    bgr = cv2.imread(str(p), cv2.IMREAD_COLOR)
    if bgr is None or bgr.size == 0:
        return None
    H, W = bgr.shape[:2]
    # HoughCircles à pleine résolution explose (jusqu'à ~35 s sur un raw 1600²,
    # pire cas observé en review) : le coût de l'accumulateur croît avec la
    # résolution ET la largeur de la plage de rayons (ici 0.30→0.50·petit-côté).
    # On borne donc le petit côté de l'image de travail à WORK_SHORT puis on remet
    # le cercle trouvé à l'échelle native. Le cercle n'est qu'un POINT DE DÉPART
    # que l'éditeur laisse ajuster à la main (et que _plausible_suggestion filtre)
    # → la précision sub-pixel pleine résolution est inutile. Les raws dont le
    # petit côté est déjà ≤ WORK_SHORT ne sont PAS redimensionnés (comportement
    # identique, et ils étaient déjà rapides). Mesuré : 1600² 35 s → ~0,1 s.
    WORK_SHORT = 768
    src_short = min(H, W)
    scale = min(1.0, WORK_SHORT / src_short) if src_short > 0 else 1.0
    work = (
        cv2.resize(bgr, (round(W * scale), round(H * scale)),
                   interpolation=cv2.INTER_AREA)
        if scale < 1.0 else bgr
    )
    short = min(work.shape[:2])
    gray = cv2.medianBlur(cv2.cvtColor(work, cv2.COLOR_BGR2GRAY), 5)
    circles = cv2.HoughCircles(
        gray, cv2.HOUGH_GRADIENT, dp=1.0, minDist=short,
        param1=100, param2=30,
        minRadius=int(short * 0.30), maxRadius=int(short * 0.50),
    )
    if circles is None or len(circles[0]) == 0:
        return None
    best = max(circles[0], key=lambda c: c[2])
    inv = 1.0 / scale
    return {
        "cx": float(best[0]) * inv,
        "cy": float(best[1]) * inv,
        "r": float(best[2]) * inv,
    }


def _plausible_suggestion(suggested: dict | None, hint: dict | None) -> dict | None:
    """Garde le cercle dominant SEULEMENT s'il est cohérent avec la bbox connue.

    La bbox (`hint`) est l'emplacement fiable de la pièce. Le Hough `_dominant_circle`
    cherche un grand cercle (≥0.30·petit-côté) : sur un undercrop macro il trouve la pièce
    entière (CONCENTRIQUE, un peu plus grande → bon point de départ), mais sur un COINCARD /
    capsule / COFFRET (pièce petite dans une boîte) il accroche le rebord de la boîte → un
    cercle plus grand et DÉCENTRÉ. On le rejette alors (l'éditeur repart de la bbox, sur la
    pièce).

    Critères de confiance (un « meilleur cadrage de la MÊME pièce ») :
      - concentrique : centre ≤ 0,7·r_bbox de la bbox ;
      - taille bornée : rayon ≤ 2,2·r_bbox (l'undercrop type = pièce entière ≈ 2× le
        disque bimétal détecté ; au-delà c'est une boîte/capsule, pas la pièce).

    Asymétrie de coût assumée : un rejet retombe sur la bbox (toujours SUR la pièce →
    sûr) ; un faux positif donne un cercle géant inutile (le bug). On biaise donc vers
    le rejet. Seuils d'origine (1,2 / 3,5) trop lâches : ils laissaient passer un coffret
    proof (ex. eBay Donatello : r=3,05·r_bbox, centre à 1,12·r_bbox → cercle sur la boîte)."""
    if suggested is None or hint is None:
        return suggested
    hr = float(hint.get("r") or 0.0)
    if hr <= 0:
        return suggested
    dist = ((suggested["cx"] - hint["cx"]) ** 2 + (suggested["cy"] - hint["cy"]) ** 2) ** 0.5
    if dist > 0.7 * hr or suggested["r"] > 2.2 * hr:
        return None  # cercle dominant aberrant (coincard/capsule/coffret) → garder la bbox
    return suggested


def load_crop_edit_context(store: Store, asset_id: str) -> CropEditContextData:
    """Charge le raw + le cercle de départ pour l'éditeur, depuis un asset_id."""
    conn = store._connection()  # noqa: SLF001
    row = conn.execute(
        """
        SELECT a.id AS asset_id, a.bbox_json,
               a.storage_path AS crop_storage_path,
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

    # Cercle dominant proposé — UNIQUEMENT pour les sources mono-pièce. Sur un
    # lot (plusieurs crops sur le même raw), un Hough global sauterait sur la
    # plus grosse pièce, pas celle qu'on édite : on garde alors le hint bbox
    # (bon depuis le bridage rim-refine). Coût Hough ~ acceptable (action manuelle).
    n_crops = conn.execute(
        "SELECT COUNT(*) FROM image_assets WHERE source_image_id = ?",
        (row["source_image_id"],),
    ).fetchone()[0]
    hint = _hint_from_bbox(row["bbox_json"])
    suggested = _dominant_circle(row["raw_storage_path"]) if n_crops <= 1 else None
    suggested = _plausible_suggestion(suggested, hint)  # rejette le cercle coincard aberrant

    return CropEditContextData(
        asset_id=row["asset_id"],
        source=row["source"],
        source_image_id=row["source_image_id"],
        raw_storage_path=row["raw_storage_path"],
        crop_storage_path=row["crop_storage_path"],
        raw_width=row["raw_width"],
        raw_height=row["raw_height"],
        hint=hint,
        suggested=suggested,
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
    try:
        upload_through("enrichment-crops", crop_sp, png_bytes)
    except Exception as exc:  # noqa: BLE001
        # ÉCHEC DUR, et volontairement : on n'écrit PAS la géométrie.
        #
        # Avant, l'échec était avalé (`minio_ok=False`) et la suite s'exécutait :
        # la base affirmait un cadrage manuel 224×224 avec un phash tout neuf,
        # l'API répondait 200, le `crop_b64` montrait à l'ami le crop qu'il
        # venait de dessiner — et MinIO gardait l'ANCIEN crop. Ce sont ces
        # pixels-là qui partent à l'entraînement. Personne ne lisait `minio_ok`
        # côté front, donc rien ne le disait.
        #
        # Tant que le geste vivait sur le Mac (cache local = source servie) le
        # trou était théorique. Il traverse maintenant ami → VPS → MinIO, où un
        # échec réseau est un cas NORMAL. Mieux vaut un 502 que l'utilisateur
        # voit qu'un jeu d'entraînement pollué que personne ne voit.
        logger.error("[manual-crop] écriture MinIO échouée pour %s: %s — "
                     "géométrie NON écrite (base et objet resteraient divergents)",
                     crop_sp, exc)
        raise HTTPException(
            status_code=502,
            detail="Le crop recadré n'a pas pu être stocké — rien n'a été "
                   "enregistré. Réessaie dans un instant.",
        ) from exc
    minio_ok = True

    # 4. DB : nouveau cercle + method 'manual' + dims + phash.
    bbox = {"x": cx - r, "y": cy - r, "w": 2 * r, "h": 2 * r}
    new_h, new_w = res.image.shape[0], res.image.shape[1]
    new_phash = compute_phash(res.image)
    # Direction A (C5) : sous le flip (canonique local = réplique READONLY), on
    # NE touche PAS le canonique local — le forward `push_crops` ci-dessous écrit
    # la géométrie au VPS, où `store.crops.apply_ingest_crops` fait le MÊME UPDATE
    # image_assets + emit_field_event canoniquement (vérifié). Guarder ici évite
    # l'`OperationalError: readonly database` (leçon #1) sans rien perdre : la
    # réplique récupère la géométrie au prochain pull. En Model A (pas de flip),
    # on écrit local comme avant ; le forward est alors best-effort (C4d).
    if not resolve_db_readonly():
        conn.execute(
            "UPDATE image_assets SET bbox_json = ?, detection_method = 'manual', "
            "width = ?, height = ?, phash = ? WHERE id = ?",
            (json.dumps(bbox), new_w, new_h, new_phash, row["asset_id"]),
        )
        # Sync : un recrop manuel est autoritatif (non recomputable). Le binaire
        # est ré-uploadé sur la MÊME clé MinIO → seules les colonnes voyagent ;
        # cache_invalidate dit aux autres machines de purger leur PNG périmé.
        emit_field_event(
            conn, asset_id=row["asset_id"], reason="manual_recrop",
            fields={
                "image_assets.bbox_json": json.dumps(bbox),
                "image_assets.detection_method": "manual",
                "image_assets.width": new_w,
                "image_assets.height": new_h,
                "image_assets.phash": new_phash,
            },
            detail={"cache_invalidate": crop_sp},
        )
        conn.commit()

    # Remontée canonique au VPS (Direction A, C4d). L'écriture locale ci-dessus
    # reste (cache réplique servi immédiatement par cette même requête) ; le
    # forward rend la géométrie visible au canonique (gap identifié en C4a :
    # le re-crop manuel n'était pas encore routé, contrairement aux scripts
    # batch recrop_*). Best-effort : un échec réseau ne casse pas le re-crop
    # déjà committé localement.
    from client.http import sync_enabled

    if sync_enabled():
        try:
            from client.ingest import push_crops

            push_crops([{
                "asset_id": row["asset_id"], "bbox_json": json.dumps(bbox),
                "detection_method": "manual", "width": new_w, "height": new_h,
                "phash": new_phash,
            }])
        except Exception as exc:  # noqa: BLE001 — forward best-effort
            logger.warning("[manual-crop] forward /ingest/crops échoué asset=%s: %s",
                           row["asset_id"], exc)

    logger.info("[manual-crop] asset=%s cx=%.1f cy=%.1f r=%.1f minio=%s",
                row["asset_id"], cx, cy, r, minio_ok)

    # Recompute Dino sur le crop recadré (best-effort : un échec ne casse pas
    # le re-crop déjà committé). Tous les kinds live (consensus + suggestions)
    # sont rafraîchis en un seul encodage.
    dino_recomputed = False
    try:
        from sources._base.steps.auto_validate import predict_and_persist_kinds

        target_eid = row["target_eurio_id"]
        target_country = (
            target_eid[:2].lower() if target_eid and len(target_eid) >= 2 else None
        )
        preds = predict_and_persist_kinds(
            store=store,
            asset_id=row["asset_id"],
            crop_path=cache_p,
            target_country=target_country,
        )
        dino_recomputed = bool(preds)
    except ImportError:
        # Machine sans DINO — c'est le cas du VPS, et c'est VOULU (D6) : ni
        # torch ni banque d'ancres n'y montent. Le recadrage prend effet tout de
        # suite (D9), l'encodage se rattrape en lot depuis le Mac.
        _mark_dino_stale(store, row["asset_id"])
    except Exception as exc:  # noqa: BLE001 — suggestion layer, never fatal
        logger.warning("[manual-crop] Dino recompute failed for asset=%s: %s",
                       row["asset_id"], exc)
        _mark_dino_stale(store, row["asset_id"])

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


def _mark_dino_stale(store: Store, asset_id: str) -> None:
    """« DINO à réencoder » — sans retirer la suggestion de l'écran.

    Première version (lot 6b) : on SUPPRIMAIT les prédictions du crop d'avant,
    l'absence servant de marqueur. Techniquement propre, et faux à l'usage — le
    PO l'a dit dès sa première vraie session :

        « moi je commence toujours par faire le recadrage et après je pick la
          bonne pièce. Souvent, la suggestion de Dino de base est bonne. »

    Le geste réel est un ajustement AU MICRO du cadrage, suivi du choix de la
    pièce. Supprimer retirait l'aide juste avant le moment où elle sert, pour un
    recadrage qui ne la change presque jamais. On garde donc la prédiction, et on
    date sa péremption : l'écran peut le dire, l'humain arbitre, et le rattrapage
    reste programmé — `_existing_keys` traite une ligne périmée comme absente,
    donc `go-task ml:dino-predictions:backfill` la réencode SANS `--force`.

    Best-effort : le recadrage est déjà committé, rien ici ne doit le défaire.
    """
    if resolve_db_readonly():
        # Réplique en lecture seule (Direction A) : le canonique du VPS a fait ce
        # marquage de son côté, en même temps que son propre recadrage.
        return
    try:
        conn = store._connection()  # noqa: SLF001
        n = conn.execute(
            "UPDATE image_asset_dino_predictions SET stale_since = datetime('now') "
            " WHERE asset_id = ? AND stale_since IS NULL",
            (asset_id,),
        ).rowcount
        conn.commit()
        logger.info(
            "[manual-crop] asset=%s : %d prédiction(s) DINO marquée(s) périmée(s) — "
            "toujours servies, à réencoder (go-task ml:dino-predictions:backfill)",
            asset_id, n,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("[manual-crop] marquage DINO périmé échoué asset=%s: %s",
                       asset_id, exc)


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
    from review.review_lanes import compute_lane
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
    # Sync : snapshot INSERT complet en row_ops — une machine distante n'a pas
    # cette row, l'event doit suffire à la créer (binaire déjà sur MinIO).
    emit_state_event(
        conn, asset_id=asset_id, to_state="detected", actor="human",
        reason="manual_add_crop", target_eurio_id=si["target_eurio_id"],
        run_id=run_id,
        detail={"row_ops": [{
            "op": "upsert", "table": "image_assets", "key": {"id": asset_id},
            "values": {
                "source_image_id": source_image_id,
                "crop_index": crop_index,
                "bbox_json": json.dumps(bbox),
                "detection_method": "manual_add",
                "resolution_status": "needs_review",
                "candidate_eurio_ids_json":
                    json.dumps(candidate_list) if candidate_list else None,
                "phash": phash_value,
                "storage_path": storage_key,
                "storage_status": "present",
                "width": new_w,
                "height": new_h,
                "run_id": run_id,
            },
        }]},
        detail_fields={},
    )
    conn.commit()

    # Dino best-effort (suggestion layer, jamais fatal) — avant compute_lane
    # pour que la lane soit informée. Tous les kinds live en un encodage.
    dino_recomputed = False
    try:
        from sources._base.steps.auto_validate import predict_and_persist_kinds
        target_eid = si["target_eurio_id"]
        target_country = (
            target_eid[:2].lower() if target_eid and len(target_eid) >= 2 else None
        )
        preds = predict_and_persist_kinds(
            store=store, asset_id=asset_id, crop_path=cache_p,
            target_country=target_country,
        )
        dino_recomputed = bool(preds)
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
        detail_fields={
            "review_queue.status": "open",
            "review_queue.priority": priority,
            "review_queue.candidate_eurio_ids_json":
                json.dumps(candidate_list) if candidate_list else None,
            "review_queue.kind": kind,
            "review_queue.lane": lane,
        },
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


def delete_crop(store: Store, asset_id: str) -> None:
    """Supprime DÉFINITIVEMENT un crop : fichier (MinIO + cache, best-effort)
    puis la row ``image_assets``. Le ``ON DELETE CASCADE`` du schéma purge en
    chaîne ``review_queue`` + prédictions Dino (la connexion Store a
    ``PRAGMA foreign_keys=ON``). Ne touche JAMAIS au raw.

    Le caller DOIT avoir vérifié que le crop est indécidé (review 'open') —
    on ne supprime pas une décision humaine. Sert à la resync crops↔détection
    quand la détection corrigée trouve MOINS de pièces que de crops stockés."""
    conn = store._connection()  # noqa: SLF001
    row = conn.execute(
        "SELECT storage_path FROM image_assets WHERE id = ?", (asset_id,),
    ).fetchone()
    if row is None:
        return

    # Propagation canonique AVANT le delete local (Direction A). Contrairement
    # au forward recrop (best-effort : la géométrie est recomputable), un delete
    # non propagé RESSUSCITE au prochain pull-replica — on refuse donc de
    # supprimer localement si le canonique n'a pas confirmé. Sur le VPS
    # (sync désactivée), le delete local EST le canonique.
    from client.http import sync_enabled

    if sync_enabled():
        try:
            from client.ingest import push_delete_asset

            push_delete_asset(asset_id)
        except Exception as exc:  # noqa: BLE001
            logger.error("[delete-crop] forward DELETE /ingest/assets échoué "
                         "asset=%s: %s", asset_id, exc)
            raise HTTPException(
                status_code=502,
                detail=f"Delete non propagé au canonique ({exc}) — "
                       "suppression locale refusée (le crop ressusciterait).",
            ) from exc

    storage_key = row["storage_path"]
    if storage_key:
        # Fichier d'abord (la cascade DB suit). Best-effort : un orphelin MinIO
        # est rattrapé par la sync périodique, on ne bloque pas la suppression.
        try:
            from shared.storage.cascade import delete_asset_cascade, STATUS_REMOVED
            delete_asset_cascade(
                "enrichment-crops", storage_key, "image_assets", asset_id,
                reason=STATUS_REMOVED,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("[delete-crop] file delete failed asset=%s: %s",
                           asset_id, exc)
    # Direction A (C5) : sous le flip, le canonique local est READONLY et le VPS
    # a DÉJÀ supprimé la row (+cascade) via le forward `push_delete_asset`
    # ci-dessus (`apply_delete_assets`). On saute donc le DELETE local (sinon
    # `OperationalError` → 503 alors que le delete canonique a RÉUSSI). Le binaire
    # MinIO reste supprimé côté client (au-dessus) — `apply_delete_assets` ne le
    # touche pas volontairement. La réplique perd la row au prochain pull. En
    # Model A (pas de flip), le DELETE local EST le canonique, inchangé.
    if not resolve_db_readonly():
        conn.execute("DELETE FROM image_assets WHERE id = ?", (asset_id,))
        conn.commit()
    logger.info("[delete-crop] asset=%s purged (row + cascade)", asset_id)
