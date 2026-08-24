"""Le recadrage manuel, servi par le canonique (lot 6b).

18,4 % des crops sont recadrés à la main. Tant que ce geste vivait uniquement
sur l'API ML locale (`:8042`), un ami invité ne faisait que la moitié du
travail : il pouvait dire QUELLE pièce c'est, jamais corriger un cadrage — et
le bouton lui parlait d'un port qu'il n'atteindra jamais (D11).

**Ce qui bouge ici, et ce qui ne bouge pas** :

- ce qui bouge : les pixels sont recadrés **côté serveur**, sur le VPS, par le
  même `_crop_mask_resize_float` que la prod. `opencv-python-headless` monte
  dans l'image (D5) ;
- ce qui ne bouge PAS : DINO. Ni torch ni banque d'ancres sur le VPS (D6). Le
  crop recadré voit ses prédictions MARQUÉES périmées (`stale_since`, migration
  0013) : elles restent servies — l'écran dit « calculée avant ton recadrage » —
  et le Mac les recalcule en lot. Elles étaient supprimées dans le premier jet ;
  le PO l'a réfuté à l'usage, il recadre AVANT de choisir la pièce.

**Pourquoi pas un crop en Canvas dans le navigateur** (D5) : `canvas.drawImage`
ne rééchantillonne pas comme `INTER_AREA`, et pas pareil selon le navigateur et
le GPU. On obtiendrait des crops qui diffèrent selon la machine de l'ami — une
pollution silencieuse du jeu d'entraînement.

Scope `review:write` : recadrer n'est pas arbitrer. Un ami recadre, et son
recadrage prend effet tout de suite (D9) — c'est sa DÉCISION qui part en
quarantaine, pas son cadrage. Asymétrie assumée : rejeter la décision d'un ami
ne défait pas son recadrage, qui améliore presque toujours.

Enregistré seulement si `cv2` est là : une route qui existe et explose vaut
moins qu'une route absente (même doctrine que `coin_assets_routes`).
"""
from __future__ import annotations

import logging
import sqlite3
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException

from serving.auth_principal import Principal, require_scope
from serving.deps import db_connection

from . import repository

logger = logging.getLogger("eurio-api.review_crop")

router = APIRouter(tags=["review-queue"])

_require_write = require_scope("review:write")
ConnDep = Annotated[sqlite3.Connection, Depends(db_connection)]
PrincipalDep = Annotated[Principal, Depends(_require_write)]

try:
    from serving.crop_edit import apply_manual_crop, load_crop_edit_context
    from serving.crop_edit_api import (
        CropEditContext,
        ManualCropPayload,
        ManualCropResponse,
        crop_edit_context_response,
        manual_crop_response,
    )

    CROP_EDIT_AVAILABLE = True
except ImportError as exc:  # pragma: no cover — dépend de l'image
    logger.info("[review-crop] recadrage indisponible sur cette image : %s", exc)
    CROP_EDIT_AVAILABLE = False


def _store():
    """Le Store partagé de l'app lean (le writer canonique)."""
    from serving.server_serve import _store as shared_store

    return shared_store


if CROP_EDIT_AVAILABLE:

    @router.get(
        "/review-queue/{review_id}/crop-edit-context",
        response_model=CropEditContext,
    )
    def get_crop_edit_context(
        review_id: str, principal: PrincipalDep, conn: ConnDep,
    ) -> CropEditContext:
        """Le RAW sur lequel dessiner + le cercle de départ.

        URLs MinIO **présignées** : le chemin `/sources/…/file` du legacy n'est
        servi que par l'app full de la workstation — l'éditeur ouvert depuis un
        navigateur distant n'y verrait que deux carrés gris (leçon du lot 1).
        """
        asset_id = repository.asset_id_for_review(conn, review_id)
        if asset_id is None:
            raise HTTPException(status_code=404, detail="Review introuvable.")
        return crop_edit_context_response(load_crop_edit_context(_store(), asset_id))

    @router.post(
        "/review-queue/{review_id}/manual-crop",
        response_model=ManualCropResponse,
    )
    def manual_crop(
        review_id: str,
        payload: ManualCropPayload,
        principal: PrincipalDep,
        conn: ConnDep,
    ) -> ManualCropResponse:
        """Recadre l'asset depuis un cercle (cx, cy, r) en px natifs du raw.

        Le navigateur envoie TROIS FLOTTANTS ; le serveur possède les pixels
        (D5). `eurio_id`, `resolution_status` et `training_eligible` ne sont pas
        touchés : recadrer n'est pas décider.
        """
        asset_id = repository.asset_id_for_review(conn, review_id)
        if asset_id is None:
            raise HTTPException(status_code=404, detail="Review introuvable.")
        data = apply_manual_crop(
            _store(), asset_id, payload.cx, payload.cy, payload.r,
        )
        logger.info(
            "[review-crop] asset=%s recadré par %s (dino_recalculé=%s)",
            asset_id, principal.user_id, data.dino_recomputed,
        )
        return manual_crop_response(data)
