"""Contrat HTTP du re-crop manuel — modèles + habillage, sans rien de lourd.

Ces modèles vivaient dans ``review/review_queue_routes.py``, le gros router
legacy. Conséquence : quiconque voulait juste le CONTRAT devait importer tout
le module — `sources.ebay.standards`, `review.validation.experts`, la chaîne
d'expertise complète. C'est ce qui empêchait `coin_assets_routes` d'enregistrer
ses routes de recadrage sur l'image lean du VPS alors que sa seule vraie
dépendance, `cv2`, y est désormais présente (lot 6b).

Ici : pydantic, base64, et le signeur MinIO. Rien d'autre. Le cœur du calcul
reste dans ``serving/crop_edit.py`` (cv2), les routes chez leurs routers
respectifs — review (keyé `review_id`), coins (keyé `asset_id`), et la voie
lean du VPS.

⚠️ Les URLs sont **absolues** (MinIO présignées), pas `/sources/…/file` : ce
chemin-là n'est servi que par l'app full de la workstation. Même doctrine et
même raison qu'au lot 1 — sans elle l'éditeur de cercle est aveugle partout
ailleurs que sur le Mac, c'est-à-dire là où il sert.
"""

from __future__ import annotations

import base64
import logging

from pydantic import BaseModel, Field

from serving.crop_edit import CropEditContextData, ManualCropData

logger = logging.getLogger(__name__)


class CropBbox(BaseModel):
    x: float
    y: float
    w: float
    h: float


class CropEditContext(BaseModel):
    asset_id: str
    source: str
    raw_url: str                 # URL MinIO présignée du RAW (on dessine dessus)
    crop_url: str                # URL MinIO présignée du crop actuel
    raw_width: int | None
    raw_height: int | None
    # Cercle de départ de l'éditeur = crop actuel, en px NATIFS du raw,
    # reconstruit depuis bbox_json (x,y,w,h → centre + rayon). None si la
    # bbox est absente (l'éditeur démarre alors sur un cercle par défaut).
    hint: dict | None
    # Cercle dominant détecté dans le raw (px natifs), proposé comme point de
    # départ quand la source est mono-pièce et le crop stocké mal dimensionné.
    # null sur les lots / quand aucun cercle probant.
    suggested_circle: dict | None = None


class CropSuggestion(BaseModel):
    """Réponse du second appel de la modale : le cercle proposé, seul.

    `circle` est `null` quand il n'y a rien à proposer — source multi-crops,
    raw injoignable, ou cercle jugé aberrant par `_plausible_suggestion`.
    `reason` dit lequel des trois, pour que l'écran puisse le DIRE au lieu de
    laisser croire que le détecteur n'a rien vu.
    """

    asset_id: str
    circle: dict | None = None
    reason: str | None = None


class ManualCropPayload(BaseModel):
    cx: float = Field(ge=0)
    cy: float = Field(ge=0)
    r: float = Field(gt=0)


class ManualCropResponse(BaseModel):
    asset_id: str
    cx: float
    cy: float
    r: float
    bbox: CropBbox
    width: int
    height: int
    detection_method: str
    crop_b64: str                # data URI PNG du nouveau crop 224
    minio_ok: bool               # False si le write-through MinIO a échoué
    dino_recomputed: bool = False  # True si Dino a été recalculé sur le crop


def _signed(bucket: str, storage_path: str | None, fallback: str) -> str:
    """URL servable d'un objet MinIO, repli sur le chemin relatif de l'app full."""
    if storage_path:
        try:
            from shared.storage import signed_url

            return signed_url(bucket, storage_path)
        except Exception:  # noqa: BLE001 — couche d'affichage, jamais fatale
            logger.warning("[crop-edit] signature MinIO échouée pour %s", storage_path)
    return fallback


def crop_edit_context_response(ctx: CropEditContextData) -> CropEditContext:
    """Habille le contexte (keyé asset) en réponse API + URLs servables."""
    return CropEditContext(
        asset_id=ctx.asset_id,
        source=ctx.source,
        raw_url=_signed(
            "enrichment-raws", ctx.raw_storage_path,
            f"/sources/{ctx.source}/raws/{ctx.source_image_id}/file",
        ),
        crop_url=_signed(
            "enrichment-crops", ctx.crop_storage_path,
            f"/sources/{ctx.source}/assets/{ctx.asset_id}/file",
        ),
        raw_width=ctx.raw_width,
        raw_height=ctx.raw_height,
        hint=ctx.hint,
        suggested_circle=ctx.suggested,
    )


def manual_crop_response(data: ManualCropData) -> ManualCropResponse:
    """Habille le résultat (keyé asset) en réponse API (+ data-URI base64).

    Le PNG revient en base64 dans la réponse : l'éditeur affiche le crop
    recadré immédiatement, sans dépendre de la propagation du cache MinIO.
    """
    crop_b64 = "data:image/png;base64," + base64.b64encode(data.png_bytes).decode("ascii")
    return ManualCropResponse(
        asset_id=data.asset_id,
        cx=data.cx, cy=data.cy, r=data.r,
        bbox=CropBbox(x=data.bbox["x"], y=data.bbox["y"],
                      w=data.bbox["w"], h=data.bbox["h"]),
        width=data.width, height=data.height,
        detection_method=data.detection_method,
        crop_b64=crop_b64,
        minio_ok=data.minio_ok,
        dino_recomputed=data.dino_recomputed,
    )
