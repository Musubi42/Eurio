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


def push_dino_references(build: dict[str, Any], references: list[dict[str, Any]]) -> dict | None:
    """POST ``/ingest/dino-references`` si la sync est activée, sinon ``None``.

    La trace d'un build de banque est de l'état : sous Direction A elle ne peut
    pas s'écrire localement (Mac/PC lisent une réplique, que le prochain pull
    écrase). Le calcul reste local, la trace part au canonique — même partage
    que ``push_dino_predictions``.
    """
    from client.http import sync_enabled  # noqa: PLC0415

    if not build or not sync_enabled():
        return None
    from client import http as _http  # noqa: PLC0415

    return _http.post_json(
        "/ingest/dino-references", {"build": build, "references": references},
    )


def push_exclude_crops(run_id: str, asset_ids: list[str]) -> dict | None:
    """POST ``/ingest/crops/exclude`` si la sync est activée, sinon no-op (``None``).

    ``asset_ids`` = crops à exclure du training. Le serveur reste autoritaire sur
    l'appartenance au run (retourne ``skipped``). Liste vide → pas d'appel réseau.
    Retourne ``{"excluded": n, "skipped": [...]}`` ou ``None`` si sync off / vide.
    """
    from client.http import sync_enabled  # noqa: PLC0415 — évite import cycle au chargement

    if not asset_ids or not sync_enabled():
        return None
    from client import http as _http  # noqa: PLC0415

    return _http.post_json(
        "/ingest/crops/exclude", {"run_id": run_id, "asset_ids": list(asset_ids)}
    )


def push_gate_reject(
    *, review_id: str, asset_id: str, label: str,
    confidence: float | None, engine_version: str,
) -> dict | None:
    """POST ``/ingest/gate/reject`` si la sync est activée, sinon no-op (``None``).

    Comme un delete, un rejet non propagé ressuscite au pull-replica → l'appelant
    DOIT traiter un ``None`` (sync off) comme le signal de retomber sur l'écriture
    locale, et un échec réseau comme bloquant. Retourne ``{"written": bool}`` ou
    ``None`` si sync désactivée.
    """
    from client.http import sync_enabled  # noqa: PLC0415 — évite import cycle au chargement

    if not sync_enabled():
        return None
    from client import http as _http  # noqa: PLC0415

    return _http.post_json(
        "/ingest/gate/reject",
        {"review_id": review_id, "asset_id": asset_id, "label": label,
         "confidence": confidence, "engine_version": engine_version},
    )


def push_referential_fix(diff: dict[str, Any]) -> dict | None:
    """POST ``/ingest/referential-fix`` si la sync est activée, sinon no-op (``None``).

    ``diff`` = ``{case_id, preflight, coins_insert, coins_update, canonical_images}``
    calculé côté client (réplique + FS + fetch image). Une erreur HTTP (409
    preflight divergent) ou réseau est levée à l'appelant → le fix est fatal (pas
    de fallback local qui écrirait la réplique). Retourne
    ``{applied, coins_inserted, coins_updated, canonical_rows}`` ou ``None`` si
    sync désactivée (Model A → l'appelant applique localement).
    """
    from client.http import sync_enabled  # noqa: PLC0415 — évite import cycle au chargement

    if not sync_enabled():
        return None
    from client import http as _http  # noqa: PLC0415

    return _http.post_json("/ingest/referential-fix", diff)


def push_confusion_map(
    encoder_version: str, rows: list[dict[str, Any]]
) -> dict | None:
    """POST ``/ingest/confusion-map`` si la sync est activée, sinon no-op (``None``).

    ``rows`` = lignes de cartographie (``eurio_id, nearest_eurio_id,
    nearest_similarity, top_k_neighbors, zone, computed_at?``). Une erreur HTTP
    ou réseau est levée à l'appelant — une cartographie non propagée laisserait le
    canonique sur des zones périmées (le compute est lourd/manuel, on échoue
    bruyamment plutôt que d'avaler la perte). Retourne ``{"upserted": n}`` ou
    ``None`` si sync désactivée (Model A → l'appelant écrit la DB locale).
    """
    from client.http import sync_enabled  # noqa: PLC0415 — évite import cycle au chargement

    if not sync_enabled():
        return None
    from client import http as _http  # noqa: PLC0415

    return _http.post_json(
        "/ingest/confusion-map",
        {"encoder_version": encoder_version, "rows": rows},
    )


def push_cohort(cohort: dict[str, Any]) -> dict | None:
    """POST ``/ingest/cohort`` si un canonique DISTANT est configuré, sinon no-op.

    ``cohort`` = dict au schéma ``ExperimentCohortRow.to_dict()`` (F09). Gate =
    ``remote_sync_enabled()`` (PAS ``sync_enabled()`` : pousser une dimension
    lab vers le serveur local :8042 n'a pas de sens). Best-effort : les erreurs
    HTTP/réseau sont levées à l'appelant — c'est LUI qui décide (lab_routes /
    runner les avalent, le backfill les compte). Retourne ``{id, op}`` ou
    ``None`` si sync distante désactivée.
    """
    from client.http import remote_sync_enabled  # noqa: PLC0415 — évite import cycle au chargement

    if not remote_sync_enabled():
        return None
    from client import http as _http  # noqa: PLC0415

    return _http.post_json("/ingest/cohort", cohort, timeout=15)


def push_cohort_delete(cohort_id: str) -> dict | None:
    """DELETE ``/ingest/cohort/{id}`` si un canonique DISTANT est configuré,
    sinon no-op (``None``). Idempotent côté serveur (``op='absent'`` si déjà
    parti) ; 409 si des itérations canoniques la référencent encore — l'erreur
    est levée à l'appelant (F09)."""
    from client.http import remote_sync_enabled  # noqa: PLC0415 — évite import cycle au chargement

    if not remote_sync_enabled():
        return None
    from client import http as _http  # noqa: PLC0415

    return _http.delete_json(f"/ingest/cohort/{cohort_id}", timeout=15)


def push_iteration_delete(iteration_id: str) -> dict | None:
    """DELETE ``/iterations/{id}`` si un canonique DISTANT est configuré, sinon
    no-op (``None``). Idempotent côté serveur (F09). Erreurs levées à
    l'appelant."""
    from client.http import remote_sync_enabled  # noqa: PLC0415 — évite import cycle au chargement

    if not remote_sync_enabled():
        return None
    from client import http as _http  # noqa: PLC0415

    return _http.delete_json(f"/iterations/{iteration_id}", timeout=15)


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


def push_detections(source_image_id: str, detections_json: str) -> dict | None:
    """POST ``/ingest/detections`` si la sync est activée, sinon no-op (``None``).

    Remonte le constat de re-détection LIVE (``source_images.detections_json``)
    calculé côté lab (cv2). Best-effort : la re-détection est recomputable. Retourne
    le payload serveur ``{"updated": n, "missing": bool}`` ou ``None`` si désactivée."""
    from client.http import sync_enabled  # noqa: PLC0415 — évite import cycle au chargement

    if not sync_enabled():
        return None
    from client import http as _http  # noqa: PLC0415

    return _http.post_json("/ingest/detections", {
        "source_image_id": source_image_id, "detections_json": detections_json,
    })


def push_encoder_bench(
    run: dict[str, Any], predictions: list[dict[str, Any]]
) -> dict | None:
    """POST ``/ingest/encoder-bench`` si la sync est activée, sinon ``None``.

    Même doctrine que ``push_dino_references`` : le calcul (encodage, matching)
    est local à la machine qui a le GPU, la trace part au canonique — sous
    Direction A elle ne peut de toute façon pas s'écrire ici, la réplique est
    en lecture seule et le prochain pull l'écraserait.
    """
    from client.http import sync_enabled  # noqa: PLC0415

    if not run or not sync_enabled():
        return None
    from client import http as _http  # noqa: PLC0415

    return _http.post_json(
        "/ingest/encoder-bench", {"run": run, "predictions": predictions},
    )
