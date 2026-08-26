"""Route d'ingestion des run-batches (Modèle B, chunk C3).

Le serveur canonique (writer unique) reçoit les résultats du calcul lourd par run
et les applique via ``client.runbatch.ingest_run`` (1 tx, idempotent). Protégé par
le scope ``ingest:run`` (PAT owner/admin via ``serving.auth_principal.require_scope``).
"""
from __future__ import annotations

import logging
import sqlite3

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from client.runbatch import ingest_run
from serving.auth_principal import require_scope
from store import ExperimentCohortRow
from store.confusion import apply_ingest_confusion_map
from store.consensus_verdicts import apply_ingest_consensus
from store.crops import (
    apply_delete_assets,
    apply_exclude_crops,
    apply_ingest_crops,
    apply_ingest_detections,
)
from store.dino import apply_ingest_dino
from store.eval_corpus import apply_ingest_eval_corpus
from store.faces import apply_ingest_faces
from store.gate import ENGINE_VERSION as _GATE_ENGINE_VERSION
from store.gate import apply_gate_reject
from store.quality import apply_ingest_quality_scores
from store.referential_fix import ReferentialFixConflict, apply_referential_fix

logger = logging.getLogger(__name__)

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


class DetectionsPayload(BaseModel):
    source_image_id: str
    detections_json: str


@router.post("/detections", dependencies=[Depends(require_scope("ingest:write"))])
def ingest_detections_route(payload: DetectionsPayload) -> dict:
    """Persiste le constat de re-détection LIVE d'une source_image (cv2 calculé
    côté lab). SQL-pur, atomique. Retourne ``{updated, missing}``."""
    if _store is None:
        raise HTTPException(status_code=500, detail="ingest non câblé (bind manquant)")
    conn = _store._connection()  # noqa: SLF001
    conn.execute("BEGIN")
    try:
        result = apply_ingest_detections(
            conn, payload.source_image_id, payload.detections_json)
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


class QualityScoreRow(BaseModel):
    """Une mesure de CADRAGE déjà calculée. Le canonique ne la recalcule pas :
    l'oracle a besoin des raws (~12 Go de cache local) qu'il n'a pas."""

    asset_id: str
    quality_pipeline_version: int
    quality_score: float | None = None
    tilt_deg: float | None = None
    axis_ratio: float | None = None
    tilt_trustworthy: int | None = None


class IngestQualityScoresPayload(BaseModel):
    scores: list[QualityScoreRow] = []


@router.post("/quality-scores", dependencies=[Depends(require_scope("ingest:write"))])
def ingest_quality_scores_route(payload: IngestQualityScoresPayload) -> dict:
    """Écrit les mesures de cadrage de crop calculées client-side. SQL pur,
    atomique. Retourne ``{updated, skipped, missing}``.

    Pourquoi cette route existe : l'oracle (Otsu ``_probe_true_rim`` +
    ``measure_tilt``) tourne sur les RAWS, et les raws sont en cache sur le Mac,
    pas au VPS. Le Mac a le moteur et les images mais lit une réplique
    read-only ; le VPS écrit mais n'a pas les images. Sans transport, ce calcul
    n'a aucun endroit où atterrir — le même constat, mot pour mot, que celui qui
    a fait écrire ``/ingest/consensus`` et ``/ingest/faces``.

    C'est cette route qui remplace le garde ``guard_vps_only`` de
    ``scripts/backfill_quality_score.py`` : le garde existait parce qu'aucune
    voie ne transportait cette écriture. Une fois la voie ouverte, le laisser en
    ferait un garde décoratif protégeant d'un danger disparu.

    ⚠️ **Limite de méthode — à lire avant d'appeler cette colonne « qualité ».**
    ``quality_score`` mesure le **CADRAGE** (distance du rayon croppé au rim
    vrai), pas la qualité de l'image. L'oracle **plafonne** (~35 % du parc reste
    NULL = *non mesuré*, jamais *mauvais*) et il est **AVEUGLE aux vraies
    pannes** : un crop sur le mauvais objet (capsule, coincard, tissu, pièce
    voisine) est scoré « ok » parce qu'Otsu re-probe autour du centre choisi par
    le pipeline. La vraie question se lit avec le DINO ``top1_sim``.

    Deux gardes (cf. ``store/quality.py``) : jamais de rétrogradation d'un
    ``quality_pipeline_version`` supérieur ou égal, et ``quality_reason`` —
    labels HUMAINS — n'est jamais touchée.
    """
    if _store is None:
        raise HTTPException(status_code=500, detail="ingest non câblé (bind manquant)")
    conn = _store._connection()  # noqa: SLF001
    conn.execute("BEGIN")
    try:
        result = apply_ingest_quality_scores(
            conn, [s.model_dump() for s in payload.scores])
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise
    return result


class EvalCorpusRow(BaseModel):
    """Un crop et le corpus d'évaluation auquel il est réservé.

    ``eval_corpus`` ``None`` = retrait ; il exige alors ``expect`` (le corpus
    courant), sinon la ligne part en ``conflict``. Rien ne s'efface par
    omission.

    ``storage_path`` optionnel = le RANGEMENT qui suit le rôle (D9) : la clé du
    crop une fois ses octets déplacés dans le bucket ``eval-corpus``. Il arrive
    dans la MÊME transaction que le rôle, pour qu'aucun état ne dise l'un sans
    l'autre."""

    asset_id: str
    eval_corpus: str | None = None
    expect: str | None = None
    storage_path: str | None = None


class IngestEvalCorpusPayload(BaseModel):
    rows: list[EvalCorpusRow] = []


@router.post("/eval-corpus", dependencies=[Depends(require_scope("ingest:write"))])
def ingest_eval_corpus_route(payload: IngestEvalCorpusPayload) -> dict:
    """Marque des crops comme JEU D'ÉVALUATION, donc hors entraînement.

    Pourquoi cette route existe : la sélection (chantier `juge-et-banc`,
    étape 2) doit lire les mesures géométriques du parc et tirer un rang
    déterministe par classe — elle tourne donc sur le Mac, qui lit une réplique
    read-only. Le VPS écrit mais ne fait pas ce calcul. Sans transport, le
    marquage n'a aucun endroit où atterrir : le même constat que
    ``/ingest/quality-scores``, ``/ingest/consensus`` et ``/ingest/faces``.

    **Les octets bougent, eux aussi** (D9, réouverte puis tranchée le
    2026-08-26). La réponse initiale — « la clé S3 est immuable, c'est la ligne
    qui porte le rôle » — était un argument de COÛT déguisé en argument de
    PRINCIPE : un crop passé en évaluation n'est plus le même objet
    fonctionnellement, et laisser le stockage l'ignorer fait tenir la séparation
    par un seul `WHERE`. Les octets partent donc dans le bucket ``eval-corpus``,
    sous le préfixe ``eval/<corpus>/``, et ``storage_path`` suit dans la même
    transaction. Le déplacement lui-même est fait AVANT l'appel par
    ``ml/scripts/move_eval_corpus_objects.py`` : on ne réécrit jamais une clé
    vers un objet qui n'est pas encore là.

    Deux gardes (cf. ``store/eval_corpus.py``) : un crop ne change jamais de
    corpus en silence (``conflict``), et ``training_eligible`` — le verdict de
    la review — n'est pas touché.

    Retourne ``{updated, skipped, conflict, missing}``. SQL pur, atomique.
    """
    if _store is None:
        raise HTTPException(status_code=500, detail="ingest non câblé (bind manquant)")
    conn = _store._connection()  # noqa: SLF001
    conn.execute("BEGIN")
    try:
        result = apply_ingest_eval_corpus(conn, [r.model_dump() for r in payload.rows])
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


class ConsensusRowPayload(BaseModel):
    """Un verdict de consensus DÉJÀ CALCULÉ. Le canonique ne le recalcule pas —
    il n'a ni le moteur ni numpy (cf. `store/consensus_verdicts.py`)."""

    image_asset_id: str
    rule_version: int
    outcome: str
    lane: str
    confidence: float = 0.0
    reason: str | None = None
    rule: str | None = None
    signals_json: str | None = None


class IngestConsensusPayload(BaseModel):
    verdicts: list[ConsensusRowPayload] = []


@router.post("/consensus", dependencies=[Depends(require_scope("ingest:write"))])
def ingest_consensus_route(payload: IngestConsensusPayload) -> dict:
    """Écrit des verdicts de consensus calculés client-side. SQL pur, UPSERT
    idempotent sur `(image_asset_id, rule_version)`, atomique.

    Pourquoi cette route existe : sous Direction A, le Mac a le moteur mais lit
    une réplique read-only, et le VPS écrit mais n'embarque pas `training/`. Sans
    elle, un recalcul de consensus n'a **aucun endroit où atterrir** — c'est le
    constat qui a bloqué le lot B3 de la bascule de banque, le 2026-08-24.

    Retourne ``{written, missing}`` : `missing` = assets inconnus du canonique,
    non écrits.
    """
    if _store is None:
        raise HTTPException(status_code=500, detail="ingest non câblé (bind manquant)")
    conn = _store._connection()  # noqa: SLF001
    conn.execute("BEGIN")
    try:
        result = apply_ingest_consensus(
            conn, [v.model_dump() for v in payload.verdicts])
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise
    return result


# ── Traçabilité de la banque d'ancres ───────────────────────────────────────
#
# Pourquoi une route d'ingestion et pas une écriture locale : sous Direction A,
# Mac et PC lisent une RÉPLIQUE. Le build écrivait sa trace dans cette réplique
# — quand il y arrivait — et le prochain `pull-replica` l'écrasait. Résultat
# mesuré : `dino_class_references` vide dans les 8 bases locales ET au
# canonique, alors que la banque servie date du 2026-08-16. Le calcul reste
# local (c'est du GPU), la trace part ici.


class DinoBuildPayload(BaseModel):
    build_id: str
    anchors_kind: str
    encoder_version: str
    built_at: str
    n_classes: int
    n_rows: int
    n_canonical: int
    n_exemplars: int
    n_no_canonical: int = 0
    exemplars_per_class: int | None = None
    floor_sim: float | None = None
    host: str | None = None
    note: str | None = None


class DinoReferenceRowPayload(BaseModel):
    class_id: str
    eurio_id: str
    asset_id: str | None = None
    method: str
    rank: int | None = None
    selected_sim: float | None = None
    source_path: str | None = None


class IngestDinoReferencesPayload(BaseModel):
    build: DinoBuildPayload
    references: list[DinoReferenceRowPayload] = []


@router.post("/dino-references", dependencies=[Depends(require_scope("ingest:write"))])
def ingest_dino_references_route(payload: IngestDinoReferencesPayload) -> dict:
    """Enregistre un build de banque et la sélection qui le compose.

    Remplace en bloc les lignes AUTO du couple (kind, encodeur) en préservant
    les overrides humains — même contrat que `replace_auto_references`."""
    if _store is None:
        raise HTTPException(status_code=500, detail="ingest non câblé (bind manquant)")
    from store.dino_references import DinoBuild, DinoRefRow, record_build
    from store.dino_references import replace_auto_references as _replace

    build = DinoBuild(**payload.build.model_dump())
    rows = [DinoRefRow(**r.model_dump()) for r in payload.references]

    conn = _store._connection()  # noqa: SLF001
    conn.execute("BEGIN")
    try:
        record_build(conn, build)
        _replace(
            conn, build.anchors_kind, rows,
            encoder_version=build.encoder_version, build_id=build.build_id,
        )
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise
    return {"build_id": build.build_id, "n_rows": len(rows)}


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


class CohortSnapshot(BaseModel):
    """Snapshot de cohorte poussé par une machine de calcul (miroir de
    ``ExperimentCohortRow.to_dict()``, F09). ``created_at``/``updated_at``
    viennent de la source ; le canonique n'invente rien."""

    id: str
    name: str
    description: str | None = None
    zone: str | None = None
    eurio_ids: list[str] = []
    status: str = "draft"
    frozen_at: str | None = None
    created_at: str | None = None
    updated_at: str | None = None


@router.post("/cohort", dependencies=[Depends(require_scope("ingest:write"))])
def ingest_cohort_route(payload: CohortSnapshot) -> dict:
    """Upsert d'une cohorte lab (dimension, F09). Le lab local reste la source
    du calcul ; le canonique remplace la row entière par ``id`` (last-writer-
    wins, idempotent). Retourne ``{id, op}``."""
    if _store is None:
        raise HTTPException(status_code=500, detail="ingest non câblé (bind manquant)")
    _store.upsert_cohort(ExperimentCohortRow(**payload.model_dump()))
    return {"id": payload.id, "op": "upserted"}


@router.delete("/cohort/{cohort_id}", dependencies=[Depends(require_scope("ingest:write"))])
def ingest_delete_cohort_route(cohort_id: str) -> dict:
    """Supprime une cohorte du canonique (delete propagé, F09). Idempotent :
    un id déjà absent → ``op='absent'``, pas de 404 (un retry après succès
    réussit). Refuse (409) si des itérations canoniques la référencent encore
    — pousser leur suppression d'abord évite de perdre l'historique par
    cascade silencieuse."""
    if _store is None:
        raise HTTPException(status_code=500, detail="ingest non câblé (bind manquant)")
    conn = _store._connection()  # noqa: SLF001
    referent = conn.execute(
        "SELECT id FROM experiment_iterations WHERE cohort_id = ? LIMIT 1",
        (cohort_id,),
    ).fetchone()
    if referent is not None:
        raise HTTPException(
            status_code=409,
            detail=(
                f"cohorte {cohort_id!r} encore référencée par des itérations "
                f"canoniques (ex. {referent['id']!r}) — supprime-les d'abord "
                "(DELETE /iterations/{id})."
            ),
        )
    try:
        deleted = _store.delete_cohort(cohort_id)
    except sqlite3.IntegrityError as exc:
        raise HTTPException(
            status_code=409,
            detail=f"cohorte {cohort_id!r} encore référencée (FK) : {exc}",
        ) from exc
    return {"id": cohort_id, "op": "deleted" if deleted else "absent"}


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


class EncoderBenchRunPayload(BaseModel):
    """Miroir de ``store.encoder_bench.EncoderBenchRun`` (colonnes obligatoires
    d'abord). ``provisional`` vaut 1 par défaut : un run promouvable est
    l'exception qu'il faut justifier, pas l'inverse."""

    run_id: str
    created_at: str
    gold_version: str
    gold_n_crops: int
    anchors_kind: str
    encoder_spec: str
    encoder_version: str
    n_in_scope: int
    gold_sample_n: int | None = None
    bank_build_id: str | None = None
    bank_n_anchors: int | None = None
    bank_n_classes: int | None = None
    embed_dim: int | None = None
    n_params_m: float | None = None
    input_px: int | None = None
    device: str | None = None
    ms_per_img: float | None = None
    recall1: float | None = None
    recall5: float | None = None
    country_n: int | None = None
    country_recall1: float | None = None
    country_recall5: float | None = None
    spread_at_p97: float | None = None
    coverage_at_p97: float | None = None
    precision_at_p97: float | None = None
    sweep_json: str | None = None
    baseline_run_id: str | None = None
    mcnemar_p: float | None = None
    mcnemar_b: int | None = None
    mcnemar_c: int | None = None
    #: Crops réellement communs au run et à sa baseline (D16). Sans lui, un
    #: McNemar sur recouvrement partiel est indiscernable d'un McNemar complet.
    n_paired: int | None = None
    provisional: int = 1
    provisional_reason: str | None = None
    host: str | None = None
    git_commit: str | None = None
    note: str | None = None
    #: Migration 0015. ⚠️ Ces deux champs DOIVENT être déclarés ici : pydantic
    #: ignore silencieusement un champ non déclaré, et le run monterait au
    #: canonique amputé de sa précision et de son corpus — deux runs
    #: indiscernables, exactement ce que 0015 existe pour éviter.
    quantization: str = "fp32"
    eval_corpus: str | None = None


class EncoderBenchPredictionPayload(BaseModel):
    asset_id: str
    # ``class_id`` de la banque, pas un ``coins.eurio_id`` (D5) — cf. le
    # commentaire de la colonne dans state/schema.sql.
    truth_class_id: str
    correct: int
    in_top5: int
    top1_eurio_id: str | None = None
    top1_sim: float | None = None
    top2_sim: float | None = None
    spread: float | None = None
    country_top1_eurio_id: str | None = None
    country_correct: int | None = None


class IngestEncoderBenchPayload(BaseModel):
    run: EncoderBenchRunPayload
    predictions: list[EncoderBenchPredictionPayload] = []


@router.post("/encoder-bench", dependencies=[Depends(require_scope("ingest:write"))])
def ingest_encoder_bench_route(payload: IngestEncoderBenchPayload) -> dict:
    """Enregistre un run du banc multi-encodeurs et ses prédictions.

    Le calcul (encodage, matching) reste local à la machine qui a un GPU ; seuls
    les scalaires de décision montent au canonique — c'est ce qui rend la page
    admin possible depuis le front hébergé, et l'apparié rejouable sans
    ré-encoder.

    Les prédictions ne sont remplacées en bloc QUE si la liste est fournie
    (D9) : ré-envoyer un run pour corriger sa ``note`` ou son ``mcnemar_p``
    ne doit pas effacer ce pour quoi la table existe. La réponse distingue les
    deux cas — ``predictions_replaced=False`` avec ``n_predictions=0`` dit
    « rien reçu, rien touché », pas « zéro ligne écrite ».

    ⚠️ **M2 — le verdict de calibration est REMESURÉ ici, le payload ne fait
    pas foi.** Cette route recopiait ``provisional`` et ``provisional_reason``
    tels quels, et ne confrontait ni ``gold_sample_n`` ni ``n_paired`` à ce que
    la base sait mesurer. (Les deux derniers restent recopiés : ce sont la
    trace de ce que l'appelant a déclaré. Ils ne sont plus CRUS — le premier
    devient un bloqueur, le second est recompté par ``paired_overlap``.) Sonde du
    2026-08-20, contre la vraie route, base ``mkdtemp`` : un payload
    ``gold_n_crops=1958, gold_sample_n=99999, baseline_run_id='une-baseline',
    n_paired=1, provisional=0`` rendait ``HTTP 200`` et laissait en base
    ``provisional=0, provisional_reason=NULL`` — exactement la ligne que la
    page admin lit « ✔ promouvable ». Le même triplet soumis à
    ``calibration_blockers`` rendait quatre bloqueurs (P3, P1, échantillon,
    apparié). Le garde avait la bonne réponse et personne ne le consultait.

    **Corriger plutôt que refuser (4xx) — pourquoi.** Les deux se défendent ;
    ce qui ne se défend pas, c'est le silence. Trois raisons de corriger :

    1. Sous Direction A, l'appelant mesure ses bloqueurs sur une **réplique**,
       le serveur sur le **canonique**. Un désaccord est le cas NORMAL, pas
       une attaque : la réplique retarde. Refuser ferait perdre des heures de
       GPU pour un champ que le serveur sait recalculer seul.
    2. Le run porte des mesures que le serveur ne peut pas refaire (recall,
       ms/img, courbe de balayage) et un seul champ qu'il peut : le verdict.
       Jeter les premières pour la seconde est un mauvais échange — c'est déjà
       la doctrine de ``push_run``, qui dépose son payload sur disque plutôt
       que de le perdre.
    3. Le sens de la correction est toujours le sûr : ``0 → 1``. On ne promeut
       jamais un run que l'appelant disait provisoire ; on démote un run que
       l'appelant disait promouvable.

    La correction est **bruyante** : journal côté serveur, et la réponse porte
    ``provisional``, ``blockers`` et ``corrections``. Une correction que
    l'appelant ne peut pas voir serait la même maladie déplacée d'un cran.
    """
    if _store is None:
        raise HTTPException(status_code=500, detail="ingest non câblé (bind manquant)")
    from store.encoder_bench import EncoderBenchPrediction, EncoderBenchRun
    from store.encoder_bench import (
        measured_blockers,
        measured_overlap,
        record_predictions,
        record_run,
    )

    run = EncoderBenchRun(**payload.run.model_dump())
    rows = [EncoderBenchPrediction(**p.model_dump()) for p in payload.predictions]

    conn = _store._connection()  # noqa: SLF001
    conn.execute("BEGIN")
    try:
        # Les prédictions D'ABORD : c'est ce qui rend le recouvrement apparié
        # mesurable (``measured_overlap`` joint deux jeux de prédictions). Les
        # écrire après la ligne de run laisserait le garde juger un
        # ``n_paired`` déclaré alors que la base pouvait le recompter.
        n = record_predictions(conn, run.run_id, rows)

        corrections: list[str] = []
        if run.baseline_run_id:
            mesure = measured_overlap(conn, run.run_id, run.baseline_run_id)
            if mesure is not None and mesure != run.n_paired:
                corrections.append(
                    f"n_paired: declare {run.n_paired}, mesure {mesure} "
                    "(store.encoder_bench.paired_overlap)"
                )
                run.n_paired = mesure

        blockers = measured_blockers(conn, run)
        if blockers:
            if int(run.provisional or 0) == 0:
                corrections.append(
                    "provisional: declare 0, corrige a 1 — "
                    f"{len(blockers)} bloqueur(s) mesures au canonique"
                )
            raison = " | ".join(blockers)
            if run.provisional_reason != raison:
                corrections.append("provisional_reason: remplace par la mesure serveur")
            run.provisional = 1
            run.provisional_reason = raison

        if corrections:
            # Journalisé ET remonté : l'un pour l'exploitant, l'autre pour
            # l'appelant. Un seul des deux laisserait la correction muette
            # pour quelqu'un.
            #
            # Le niveau distingue deux choses très différentes. Réécrire le
            # SEUL ``provisional_reason`` d'un run déjà provisoire est le cas
            # NORMAL sous Direction A (réplique en retard sur le canonique) :
            # le passer en WARNING mettrait un avertissement sur chaque run du
            # banc et apprendrait à ne plus les lire. Un verdict retourné ou un
            # ``n_paired`` faux, eux, sont des divergences qui décident.
            durs = [c for c in corrections if not c.startswith("provisional_reason:")]
            logger.log(
                logging.WARNING if durs else logging.INFO,
                "ingest/encoder-bench %s : payload corrige par la mesure serveur — %s",
                run.run_id,
                " ; ".join(corrections),
            )

        record_run(conn, run)
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise
    return {
        "run_id": run.run_id,
        "n_predictions": n,
        "predictions_replaced": bool(rows),
        "provisional": int(run.provisional),
        "blockers": blockers,
        "corrections": corrections,
    }
