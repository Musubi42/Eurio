"""Route d'ingestion des run-batches (Modèle B, chunk C3).

Le serveur canonique (writer unique) reçoit les résultats du calcul lourd par run
et les applique via ``client.runbatch.ingest_run`` (1 tx, idempotent). Protégé par
le scope ``ingest:run`` (PAT owner/admin via ``serving.auth_principal.require_scope``).
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from client.runbatch import ingest_run
from serving.auth_principal import require_scope
from store.confusion import apply_ingest_confusion_map
from store.crops import apply_delete_assets, apply_exclude_crops, apply_ingest_crops
from store.dino import apply_ingest_dino
from store.faces import apply_ingest_faces
from store.gate import ENGINE_VERSION as _GATE_ENGINE_VERSION
from store.gate import apply_gate_reject
from store.referential_fix import ReferentialFixConflict, apply_referential_fix

router = APIRouter(prefix="/ingest", tags=["ingest"])

_store = None


def bind(store) -> None:
    global _store
    _store = store


class RunBatch(BaseModel):
    run_id: str
    tables: dict[str, list[dict]]


@router.post("/run", dependencies=[Depends(require_scope("ingest:run"))])
def ingest_run_route(batch: RunBatch) -> dict:
    """Applique un run-batch au canonique (UPSERT clé naturelle, idempotent)."""
    if _store is None:
        raise HTTPException(status_code=500, detail="ingest non câblé (bind manquant)")
    return ingest_run(_store._connection(), batch.model_dump())  # noqa: SLF001


class CropGeometry(BaseModel):
    asset_id: str
    bbox_json: str
    detection_method: str
    width: int
    height: int
    phash: int | None = None
    storage_status: str | None = None


class IngestCropsPayload(BaseModel):
    crops: list[CropGeometry]


@router.post("/crops", dependencies=[Depends(require_scope("ingest:write"))])
def ingest_crops_route(payload: IngestCropsPayload) -> dict:
    """Écrit la géométrie de recrop (bbox/method/dims/phash/storage_status)
    calculée client-side. SQL-pur (le PNG est déjà sur la même clé MinIO), UPSERT
    idempotent, atomique. Retourne ``{updated, missing}``."""
    if _store is None:
        raise HTTPException(status_code=500, detail="ingest non câblé (bind manquant)")
    conn = _store._connection()  # noqa: SLF001
    conn.execute("BEGIN")
    try:
        result = apply_ingest_crops(conn, payload.crops)
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise
    return result


class CropsExcludePayload(BaseModel):
    run_id: str
    asset_ids: list[str]


@router.post("/crops/exclude", dependencies=[Depends(require_scope("ingest:write"))])
def ingest_crops_exclude_route(payload: CropsExcludePayload) -> dict:
    """Exclut des crops du training (verdict éditorial calculé côté lab). SQL-pur,
    garde d'appartenance au run canonique-side, atomique. Retourne
    ``{excluded, skipped}``."""
    if _store is None:
        raise HTTPException(status_code=500, detail="ingest non câblé (bind manquant)")
    conn = _store._connection()  # noqa: SLF001
    conn.execute("BEGIN")
    try:
        result = apply_exclude_crops(conn, payload.run_id, payload.asset_ids)
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise
    return result


class GateRejectPayload(BaseModel):
    review_id: str
    asset_id: str
    label: str
    confidence: float | None = None
    engine_version: str = _GATE_ENGINE_VERSION


@router.post("/gate/reject", dependencies=[Depends(require_scope("ingest:write"))])
def ingest_gate_reject_route(payload: GateRejectPayload) -> dict:
    """Rejet canonique du gate vision standard (wrong_coin/junk). 3 écritures
    atomiques (review_queue done + image_assets rejected + state event) ; si la
    review n'est plus ``open`` → ``{written: false}`` sans mutation. Retourne
    ``{written: bool}``."""
    if _store is None:
        raise HTTPException(status_code=500, detail="ingest non câblé (bind manquant)")
    conn = _store._connection()  # noqa: SLF001
    conn.execute("BEGIN IMMEDIATE")
    try:
        result = apply_gate_reject(
            conn, review_id=payload.review_id, asset_id=payload.asset_id,
            label=payload.label, confidence=payload.confidence,
            engine_version=payload.engine_version,
        )
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise
    return result


@router.delete("/assets/{asset_id}", dependencies=[Depends(require_scope("ingest:write"))])
def ingest_delete_asset_route(asset_id: str) -> dict:
    """Supprime un crop du canonique (delete propagé, Direction A). La row
    ``image_assets`` part avec sa cascade (review_queue, prédictions Dino,
    state events) ; le binaire MinIO est supprimé par le client initiateur
    (clé partagée). Idempotent : un id déjà absent → ``missing``, pas de 404
    (un retry après succès réussit). Retourne ``{deleted, missing}``."""
    if _store is None:
        raise HTTPException(status_code=500, detail="ingest non câblé (bind manquant)")
    conn = _store._connection()  # noqa: SLF001
    conn.execute("BEGIN")
    try:
        result = apply_delete_assets(conn, [asset_id])
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise
    return result


class FaceVerdict(BaseModel):
    asset_id: str
    face: str


class IngestFacesPayload(BaseModel):
    faces: list[FaceVerdict]


@router.post("/faces", dependencies=[Depends(require_scope("ingest:write"))])
def ingest_faces_route(payload: IngestFacesPayload) -> dict:
    """Écrit les verdicts de face (obverse/reverse) calculés client-side (scan
    Dino GPU). SQL-pur, garde NULL/unknown (jamais par-dessus un label existant),
    atomique. Retourne ``{updated, skipped, missing}``."""
    if _store is None:
        raise HTTPException(status_code=500, detail="ingest non câblé (bind manquant)")
    conn = _store._connection()  # noqa: SLF001
    conn.execute("BEGIN")
    try:
        result = apply_ingest_faces(conn, payload.faces)
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise
    return result


class DinoPrediction(BaseModel):
    asset_id: str
    encoder_version: str
    anchors_kind: str
    anchors_count: int
    top_k: list[dict] = []
    top1_eurio_id: str | None = None
    top1_sim: float | None = None
    top2_eurio_id: str | None = None
    top2_sim: float | None = None
    spread: float | None = None
    target_country: str | None = None
    country_anchors_count: int | None = None
    top_k_country: list[dict] | None = None
    top1_country_eurio_id: str | None = None
    top1_country_sim: float | None = None
    top2_country_eurio_id: str | None = None
    top2_country_sim: float | None = None
    country_spread: float | None = None
    reverse_sim: float | None = None
    face_margin: float | None = None
    denom_2eur_score: float | None = None
    duration_ms: int | None = None
    run_id: str | None = None


class IngestDinoPayload(BaseModel):
    predictions: list[DinoPrediction]


@router.post("/dino", dependencies=[Depends(require_scope("ingest:write"))])
def ingest_dino_route(payload: IngestDinoPayload) -> dict:
    """Écrit des prédictions Dino (rescore consensus/suggestions/face/denom)
    calculées client-side (recrop manuel, review score-guided). SQL-pur, UPSERT
    idempotent (préserve ``run_id`` backfill existant), atomique. Retourne
    ``{updated, missing}``."""
    if _store is None:
        raise HTTPException(status_code=500, detail="ingest non câblé (bind manquant)")
    conn = _store._connection()  # noqa: SLF001
    conn.execute("BEGIN")
    try:
        result = apply_ingest_dino(conn, payload.predictions)
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise
    return result


class ReferentialFixPayload(BaseModel):
    case_id: str
    preflight: dict
    coins_insert: dict
    coins_update: dict
    canonical_images: list[dict] = []


@router.post("/referential-fix", dependencies=[Depends(require_scope("ingest:write"))])
def ingest_referential_fix_route(payload: ReferentialFixPayload) -> dict:
    """Applique un fix référentiel (shape B) calculé client-side : 2 rows ``coins``
    (swap numista_id + nouvelle commémo) + re-parents ``coin_canonical_images``.
    SQL-pur, preflight ré-vérifié canonique-side (409 si divergent), atomique.
    Retourne ``{applied, coins_inserted, coins_updated, canonical_rows}``."""
    if _store is None:
        raise HTTPException(status_code=500, detail="ingest non câblé (bind manquant)")
    conn = _store._connection()  # noqa: SLF001
    conn.execute("BEGIN IMMEDIATE")
    try:
        result = apply_referential_fix(conn, payload.model_dump())
        conn.execute("COMMIT")
    except ReferentialFixConflict as exc:
        conn.execute("ROLLBACK")
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except Exception:
        conn.execute("ROLLBACK")
        raise
    return result


class ConfusionMapRow(BaseModel):
    eurio_id: str
    nearest_eurio_id: str | None = None
    nearest_similarity: float
    top_k_neighbors: list[dict] = []
    zone: str
    computed_at: str | None = None


class ConfusionMapIngestPayload(BaseModel):
    encoder_version: str
    rows: list[ConfusionMapRow]


@router.post("/confusion-map", dependencies=[Depends(require_scope("ingest:write"))])
def ingest_confusion_map_route(payload: ConfusionMapIngestPayload) -> dict:
    """Écrit la cartographie de confusion (``coin_confusion_map``) calculée
    client-side (DINOv2, Mac/PC). SQL-pur, UPSERT idempotent sur la clé naturelle
    ``(eurio_id, encoder_version)``, atomique. Retourne ``{"upserted": n}``."""
    if _store is None:
        raise HTTPException(status_code=500, detail="ingest non câblé (bind manquant)")
    conn = _store._connection()  # noqa: SLF001
    conn.execute("BEGIN")
    try:
        result = apply_ingest_confusion_map(
            conn,
            payload.encoder_version,
            [r.model_dump() for r in payload.rows],
        )
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise
    return result


@router.get("/run/{run_id}", dependencies=[Depends(require_scope("ingest:run"))])
def run_status(run_id: str) -> dict:
    """État d'un run déjà ingéré (depuis ``ingested_runs``)."""
    if _store is None:
        raise HTTPException(status_code=500, detail="ingest non câblé (bind manquant)")
    row = _store._connection().execute(  # noqa: SLF001
        "SELECT run_id, batch_sha, applied_at, counts_json FROM ingested_runs "
        "WHERE run_id=?",
        (run_id,),
    ).fetchone()
    if row is None:
        return {"run_id": run_id, "applied": False}
    return {
        "run_id": row["run_id"],
        "applied": True,
        "batch_sha": row["batch_sha"],
        "applied_at": row["applied_at"],
        "counts_json": row["counts_json"],
    }
