"""Helper commun pour pousser les écritures géométrie/verdict vers le canonique
(Direction A, chunks C4a/C4d).

Factorise les appels ``POST /ingest/crops`` (C2b, ``store/crops.py``) et
``POST /ingest/dino`` (C4d, ``store/dino.py``) pour les scripts/routes qui
calculent la géométrie ou les prédictions Dino côté Mac/PC (cv2/torch,
GPU-less côté VPS) et doivent pousser les colonnes résultantes au canonique.
Gating identique au reste du client : ``client.http.sync_enabled()``
(= ``bool(EURIO_API_URL)``) — si la sync n'est pas configurée (dev Model A
pur), l'appelant garde son fallback d'écriture locale (voir
``ml/scripts/recrop_*.py``, ``sources/_base/steps/auto_validate.py``).
"""
from __future__ import annotations

from typing import Any


def push_crops(crops: list[dict[str, Any]], *, cache_invalidate: bool = True) -> dict | None:
    """POST ``/ingest/crops`` si la sync est activée, sinon no-op (``None``).

    ``crops`` = liste de dicts au schéma ``CropGeometry`` (asset_id, bbox_json,
    detection_method, width, height, phash?, storage_status?). Une liste vide
    ne déclenche pas d'appel réseau. Retourne le payload serveur
    ``{"updated": n, "missing": [...]}`` ou ``None`` si sync désactivée / liste
    vide.
    """
    from client.http import sync_enabled  # noqa: PLC0415 — évite import cycle au chargement

    if not crops or not sync_enabled():
        return None
    from client import http as _http  # noqa: PLC0415

    payload: dict[str, Any] = {"crops": crops}
    if cache_invalidate:
        payload["cache_invalidate"] = True
    return _http.post_json("/ingest/crops", payload)


def push_dino_predictions(predictions: list[dict[str, Any]]) -> dict | None:
    """POST ``/ingest/dino`` si la sync est activée, sinon no-op (``None``).

    ``predictions`` = liste de dicts au schéma ``DinoPredictionRow.to_dict()``
    (asset_id, encoder_version, anchors_kind, anchors_count, top_k, ...). Une
    liste vide ne déclenche pas d'appel réseau. Retourne le payload serveur
    ``{"updated": n, "missing": [...]}`` ou ``None`` si sync désactivée / liste
    vide.
    """
    from client.http import sync_enabled  # noqa: PLC0415 — évite import cycle au chargement

    if not predictions or not sync_enabled():
        return None
    from client import http as _http  # noqa: PLC0415

    return _http.post_json("/ingest/dino", {"predictions": predictions})


def push_delete_asset(asset_id: str) -> dict | None:
    """DELETE ``/ingest/assets/{id}`` si la sync est activée, sinon no-op (``None``).

    Contrairement aux push géométrie/verdict (best-effort : recomputables),
    l'appelant d'un delete DOIT traiter un échec comme bloquant — un delete
    non propagé ressuscite au prochain pull-replica (gap MAJOR 1, Direction A).
    Retourne le payload serveur ``{"deleted": n, "missing": [...]}`` ou ``None``
    si sync désactivée.
    """
    from client.http import sync_enabled  # noqa: PLC0415 — évite import cycle au chargement

    if not sync_enabled():
        return None
    from client import http as _http  # noqa: PLC0415

    return _http.delete_json(f"/ingest/assets/{asset_id}")
