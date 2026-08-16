"""FastAPI router pour `/coins/{eurio_id}/assets`.

Surface les image_assets enrichis liés à un eurio_id (donnée du
référentiel Eurio) — avec pagination et un toggle pour exposer aussi
les `needs_review` / `rejected`. Consommé par la page Coin Detail
(``admin/packages/web/src/features/coins/pages/CoinDetailPage.vue``).

Couvre aussi l'action bulk "re-flagger en needs_review" (rollback
admin vers la review queue), anticipée par la vision auto-validation
§P3 — utile dès maintenant pour corriger des assignations douteuses
sans attendre le branchement de l'auto-accept (chunk 8).

Stockage filesystem aujourd'hui : les fichiers résident à
``image_assets.storage_path`` sur la machine qui a fait tourner la
pipeline et sont servis via ``GET /sources/{source}/assets/{asset_id}/file``
(cf. ``sources_routes.py``). Quand on basculera vers un service S3
distant (cf. doc kickoff storage), seul l'URL exposée dans la réponse
de cet endpoint changera — les consommateurs front sont protégés.
"""

from __future__ import annotations

import logging
import sqlite3
import uuid
from datetime import datetime
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from shared.storage import signed_url
from store import (
    Store,
    clear_reference_override,
    emit_field_event,
    emit_state_event,
    get_class_references,
    get_references_for_assets,
    set_reference_override,
)

# Les deux imports ci-dessous tirent cv2 (édition de crop). L'image lean du VPS
# ne l'embarque pas : au niveau module, ils faisaient échouer l'import de TOUT
# ce fichier, et `server_serve.py` skippait le routeur entier — y compris
# `/coins/enrichment-counts` et `/coins/{id}/assets`, qui ne sont pourtant que
# du SQL. Ils étaient lourds **par voisinage, pas par nature**, et c'est ce qui
# rendait le compteur d'enrichissement impossible à servir depuis le canonique
# (B3). On gate donc les deux routes d'édition, pas le fichier.
try:
    from .crop_edit import apply_manual_crop, load_crop_edit_context
    from review.review_queue_routes import (
        CropEditContext,
        ManualCropPayload,
        ManualCropResponse,
        _crop_edit_context_response,
        _manual_crop_response,
    )
    CROP_EDIT_AVAILABLE = True
except ImportError:
    # Pas de repli en 503 : on n'enregistre tout simplement pas ces routes.
    # Une route qui existe et explose vaut moins qu'une route absente — le front
    # découvre la capacité par `hasLocalMlApi`, pas par un essai/erreur HTTP.
    CROP_EDIT_AVAILABLE = False

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/coins", tags=["coins"])


_RESOLVED_STATUSES = ("auto_name", "auto_phash", "manual")
_UNRESOLVED_STATUSES = ("needs_review", "rejected")


# ── Module-level state (set by bind() at server boot) ─────────────────────
_store: Store | None = None


def bind(store: Store) -> None:
    """Wire le router au Store partagé du serveur."""
    global _store
    _store = store


def _conn() -> sqlite3.Connection:
    if _store is None:
        raise RuntimeError("coin_assets_routes not bound — call bind() first.")
    return _store._connection()  # noqa: SLF001


# ── Models ────────────────────────────────────────────────────────────────


class CoinAsset(BaseModel):
    id: str
    source: str
    source_ref: str
    listing_url: str | None = None
    listing_title: str | None = None
    file_url: str
    face: str | None = None
    variant_kind: str
    resolution_status: str
    resolution_confidence: float | None = None
    decided_by: str | None = None
    resolved_at: str | None = None
    width: int | None = None
    height: int | None = None
    # improvement-loop B : si ce crop sert de référence Dino (banque de
    # suggestions), sa méthode ('fps'|'manual_pin'|'manual_exclude') — pour
    # badger la vignette dans la galerie. None = n'est pas une référence.
    dino_reference: str | None = None


class CoinAssetsPage(BaseModel):
    eurio_id: str
    total: int
    assets: list[CoinAsset]
    next_offset: int | None = None


class ReflagPayload(BaseModel):
    asset_ids: list[str] = Field(min_length=1, max_length=200)


class ReflagResponse(BaseModel):
    n_reflagged: int
    n_skipped: int
    skipped_reasons: list[str] = []
    # Lignes review_queue OPEN des assets fournis (reflaggés OU déjà
    # unresolved) — la galerie navigue vers /review/manual?ids=… pour les
    # traiter tout de suite (recadrer / re-choisir la pièce) au lieu d'aller
    # les chercher en queue. Robuste aux crops rescués (filtre rq.id IN, pas
    # target_eurio_id).
    review_ids: list[str] = []


# ── Helpers ───────────────────────────────────────────────────────────────


def _asset_file_url(row: sqlite3.Row) -> str:
    """URL d'affichage du crop.

    **Absolue et signée** dès que possible : le chemin relatif
    `/sources/{source}/assets/{id}/file` est servi par `sources_routes.py`, qui
    n'est monté QUE sur le ML API local — le canonique ne l'expose pas. Depuis
    que la galerie lit le canonique (B3, direction 1), un chemin relatif
    donnerait des images cassées.

    Le front promeut déjà les URLs relatives en absolues via `ML_API` et
    documente que « le jour où le serveur renverra des URLs absolues, la
    promotion sera un no-op » — c'est ce jour-là.

    Repli sur le chemin relatif si la signature échoue (creds MinIO absentes,
    typiquement un test) : mieux vaut une URL que le ML API local sait servir
    qu'une exception qui ferait échouer toute la page.
    """
    if row["storage_path"]:
        try:
            return signed_url("enrichment-crops", row["storage_path"])
        except Exception:  # noqa: BLE001 — creds absentes, MinIO injoignable…
            logger.warning("signature d'URL impossible pour l'asset %s", row["id"])
    return f"/sources/{row['source']}/assets/{row['id']}/file"


def _row_to_asset(row: sqlite3.Row) -> CoinAsset:
    return CoinAsset(
        id=row["id"],
        source=row["source"],
        source_ref=row["source_ref"],
        listing_url=row["source_url"],
        listing_title=row["listing_title"],
        file_url=_asset_file_url(row),
        face=row["face"],
        variant_kind=row["variant_kind"],
        resolution_status=row["resolution_status"],
        resolution_confidence=row["resolution_confidence"],
        decided_by=row["decided_by"],
        resolved_at=row["resolved_at"],
        width=row["width"],
        height=row["height"],
    )


# ── Endpoints ─────────────────────────────────────────────────────────────


# Consumed by: admin/packages/web/src/features/coins/composables/useCoinAssets.ts (fetchEnrichmentCounts)
@router.get("/enrichment-counts", response_model=dict[str, int])
def enrichment_counts(include_unresolved: bool = Query(default=False)) -> dict[str, int]:
    """Compteur global d'images d'enrichment par eurio_id.

    Une seule query GROUP BY → consommée par la liste des coins (badge
    par card). Default : ne compte que les statuts validés. Le toggle
    sur la liste pourra plus tard demander `include_unresolved=true`
    pour tracker aussi les pendings.
    """
    conn = _conn()
    statuses = list(_RESOLVED_STATUSES)
    if include_unresolved:
        statuses += list(_UNRESOLVED_STATUSES)
    placeholders = ",".join("?" for _ in statuses)
    rows = conn.execute(
        f"""
        SELECT eurio_id, COUNT(*) AS c
          FROM image_assets
         WHERE eurio_id IS NOT NULL
           AND resolution_status IN ({placeholders})
         GROUP BY eurio_id
        """,
        statuses,
    ).fetchall()
    return {r["eurio_id"]: int(r["c"]) for r in rows}


# Consumed by: admin/packages/web/src/features/coins/composables/useCoinAssets.ts (fetchCoinAssets)
@router.get("/{eurio_id}/assets", response_model=CoinAssetsPage)
def list_coin_assets(
    eurio_id: str,
    include_unresolved: bool = Query(default=False),
    limit: int = Query(default=60, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> CoinAssetsPage:
    """Liste paginée des assets d'enrichment associés à `eurio_id`.

    Par défaut ne retourne que les statuts validés
    (`auto_name`, `auto_phash`, `manual`). Mettre `include_unresolved=true`
    expose en plus `needs_review` et `rejected` (utile pour audit
    admin et rollback).

    Tri : `resolved_at DESC` (plus récents d'abord) ;
    fallback `fetched_at DESC` quand non résolu.
    """
    conn = _conn()
    statuses = list(_RESOLVED_STATUSES)
    if include_unresolved:
        statuses += list(_UNRESOLVED_STATUSES)
    placeholders = ",".join("?" for _ in statuses)

    total_row = conn.execute(
        f"""
        SELECT COUNT(*) AS c
          FROM image_assets a
         WHERE a.eurio_id = ?
           AND a.resolution_status IN ({placeholders})
        """,
        (eurio_id, *statuses),
    ).fetchone()
    total = int(total_row["c"]) if total_row else 0

    rows = conn.execute(
        f"""
        SELECT a.id, a.face, a.variant_kind, a.resolution_status,
               a.resolution_confidence, a.resolved_at, a.width, a.height,
               a.storage_path,
               s.source, s.source_ref, s.source_url, s.listing_title,
               (SELECT decided_by FROM review_queue rq
                 WHERE rq.image_asset_id = a.id
                 ORDER BY rq.decided_at DESC LIMIT 1) AS decided_by
          FROM image_assets a
          JOIN source_images s ON s.id = a.source_image_id
         WHERE a.eurio_id = ?
           AND a.resolution_status IN ({placeholders})
         ORDER BY COALESCE(a.resolved_at, a.fetched_at) DESC
         LIMIT ? OFFSET ?
        """,
        (eurio_id, *statuses, limit, offset),
    ).fetchall()

    assets = [_row_to_asset(r) for r in rows]
    # Badge « réf Dino » : marque les crops qui servent d'exemplaires (B).
    ref_map = get_references_for_assets(conn, [a.id for a in assets])
    for a in assets:
        r = ref_map.get(a.id)
        if r is not None:
            a.dino_reference = r["method"]
    next_offset = offset + limit if offset + limit < total else None

    return CoinAssetsPage(
        eurio_id=eurio_id,
        total=total,
        assets=assets,
        next_offset=next_offset,
    )


# Consumed by: admin/packages/web/src/features/coins/composables/useCoinAssets.ts (reflagAssets)
@router.post("/assets/reflag-needs-review", response_model=ReflagResponse)
def reflag_assets(payload: ReflagPayload) -> ReflagResponse:
    """Re-flagge en bulk des assets vers `needs_review`.

    Pour chaque asset :
      - UPDATE image_assets : resolution_status='needs_review',
        resolved_at=NULL (l'eurio_id est conservé comme indice du
        dernier verdict — la review humaine pourra le confirmer ou le
        corriger).
      - INSERT INTO review_queue si pas déjà ouvert.

    Aucune ré-écriture si l'asset est déjà en `needs_review` /
    `pending_*` (skip silencieux). Ne ré-ouvre pas non plus quand
    `review_queue` a déjà une entrée open pour cet asset.
    """
    conn = _conn()
    n_reflagged = 0
    n_skipped = 0
    reasons: list[str] = []
    review_ids: list[str] = []

    now = datetime.utcnow().isoformat(timespec="seconds")

    for asset_id in payload.asset_ids:
        row = conn.execute(
            "SELECT resolution_status FROM image_assets WHERE id = ?",
            (asset_id,),
        ).fetchone()
        if row is None:
            n_skipped += 1
            reasons.append(f"{asset_id}: not_found")
            continue

        # NB : la connexion est en autocommit (isolation_level=None) — chaque
        # statement commit immédiatement ; le `with conn:` est conservé pour
        # l'intention, pas pour l'atomicité.
        with conn:
            conn.execute(
                "UPDATE image_assets SET resolution_status = 'needs_review', "
                "resolved_at = NULL WHERE id = ?",
                (asset_id,),
            )
            # review_queue.UNIQUE(image_asset_id) : un asset déjà reviewé porte
            # une ligne 'done' → un 2ᵉ INSERT violait la contrainte (500, l'asset
            # restait coincé en needs_review sans ligne open). On UPSERT : on
            # ré-ouvre la ligne existante (reset décision + lane manuelle) ou on
            # en crée une. Soigne aussi les lignes corrompues par l'ancien bug.
            new_id = uuid.uuid4().hex
            conn.execute(
                """
                INSERT INTO review_queue (
                    id, image_asset_id, status, priority, enqueued_at, kind,
                    decision_notes, lane, lane_source
                ) VALUES (?, ?, 'open', 100, ?, 'single',
                          're-flagged from coin detail', 'manual', 'human')
                ON CONFLICT(image_asset_id) DO UPDATE SET
                    status = 'open',
                    priority = 100,
                    enqueued_at = excluded.enqueued_at,
                    kind = 'single',
                    decision_notes = 're-flagged from coin detail',
                    lane = 'manual',
                    lane_source = 'human',
                    decided_eurio_id = NULL,
                    decided_face = NULL,
                    decided_variant_kind = NULL,
                    decided_at = NULL,
                    decided_by = NULL
                """,
                (new_id, asset_id, now),
            )
            rid_row = conn.execute(
                "SELECT id FROM review_queue WHERE image_asset_id = ?",
                (asset_id,),
            ).fetchone()
            emit_state_event(
                conn, asset_id=asset_id, to_state="queued", actor="human",
                reason="reflagged_from_coin",
                detail_fields={
                    "image_assets.resolution_status": "needs_review",
                    "image_assets.resolved_at": None,
                    "review_queue.status": "open",
                    "review_queue.priority": 100,
                    "review_queue.enqueued_at": now,
                    "review_queue.kind": "single",
                    "review_queue.decision_notes": "re-flagged from coin detail",
                    "review_queue.lane": "manual",
                    "review_queue.lane_source": "human",
                    "review_queue.decided_eurio_id": None,
                    "review_queue.decided_face": None,
                    "review_queue.decided_variant_kind": None,
                    "review_queue.decided_at": None,
                    "review_queue.decided_by": None,
                },
            )
        review_ids.append(rid_row["id"])
        n_reflagged += 1

    logger.info(
        "[coin_assets] reflag asset_ids=%d reflagged=%d skipped=%d review_ids=%d",
        len(payload.asset_ids), n_reflagged, n_skipped, len(review_ids),
    )
    return ReflagResponse(
        n_reflagged=n_reflagged,
        n_skipped=n_skipped,
        skipped_reasons=reasons,
        review_ids=review_ids,
    )


# ── Références Dino multi-exemplaires (improvement-loop B) ────────────────
# La banque de suggestions garde, par classe, le canonique + ~10 vrais crops
# choisis pour la diversité (FPS). Ces endpoints exposent cette sélection à la
# page coin-detail (section dédiée) et laissent l'humain épingler/bannir un crop
# (override honoré au prochain build d'ancres — la banque n'est pas rebuild live).

DINO_REF_KIND = "2eur_all"


class DinoReferenceEntry(BaseModel):
    asset_id: str | None  # None = ligne canonique (avers Numista, pas un crop)
    eurio_id: str
    method: str           # 'canonical'|'fps'|'manual_pin'|'manual_exclude'
    rank: int | None = None
    selected_sim: float | None = None
    file_url: str | None = None      # None pour le canonique
    face: str | None = None
    resolution_status: str | None = None


class DinoReferencesResponse(BaseModel):
    eurio_id: str
    class_id: str
    anchors_kind: str
    # True si la banque n'a jamais été bâtie en multi-exemplaires (aucune row) —
    # le front invite alors à lancer `go-task ml:dino-anchors:build`.
    never_built: bool
    entries: list[DinoReferenceEntry]


def _class_id_for(conn: sqlite3.Connection, eurio_id: str) -> str | None:
    """class_id d'une pièce EXACTEMENT comme le builder d'ancres le keye
    (``anchors._class_specs_2eur_all``) — sinon la lecture des références et des
    overrides ne retrouve jamais la classe des 2€ standard (le builder keye sur
    l'eurio_id du REPRÉSENTANT du design group, pas sur le slug design_group_id).

    - Commémo : classe = son propre eurio_id (le builder ne groupe pas les
      commémo).
    - Standard : rep du design group = plus ancien millésime (year, eurio_id),
      mêmes filtres que ``_select_2eur_standard_groups`` du builder.
    """
    row = conn.execute(
        "SELECT is_commemorative, COALESCE(design_group_id, eurio_id) AS grp "
        "FROM coins WHERE eurio_id = ?",
        (eurio_id,),
    ).fetchone()
    if row is None:
        return None
    if row["is_commemorative"]:
        return eurio_id
    rep = conn.execute(
        "SELECT eurio_id FROM coins "
        " WHERE face_value = 2.0 AND is_commemorative = 0 "
        "   AND canonical_eurio_id IS NULL "
        "   AND COALESCE(design_group_id, eurio_id) = ? "
        " ORDER BY year ASC, eurio_id ASC LIMIT 1",
        (row["grp"],),
    ).fetchone()
    return rep["eurio_id"] if rep else eurio_id


# Consumed by: admin/.../coins/composables/useCoinAssets.ts (fetchDinoReferences)
@router.get("/{eurio_id}/dino-references", response_model=DinoReferencesResponse)
def list_dino_references(eurio_id: str) -> DinoReferencesResponse:
    """Références Dino de la CLASSE de ``eurio_id`` (canonique + exemplaires +
    overrides), pour la section « Références Dino » de la page coin-detail."""
    conn = _conn()
    class_id = _class_id_for(conn, eurio_id)
    if class_id is None:
        raise HTTPException(status_code=404, detail="Pièce inconnue")
    rows = get_class_references(conn, class_id, DINO_REF_KIND)
    entries: list[DinoReferenceEntry] = []
    for r in rows:
        aid = r["asset_id"]
        file_url = face = status = None
        if aid:
            a = conn.execute(
                "SELECT s.source, a.face, a.resolution_status "
                "FROM image_assets a JOIN source_images s ON s.id = a.source_image_id "
                "WHERE a.id = ?", (aid,),
            ).fetchone()
            if a is not None:
                file_url = f"/sources/{a['source']}/assets/{aid}/file"
                face, status = a["face"], a["resolution_status"]
        entries.append(DinoReferenceEntry(
            asset_id=aid, eurio_id=r["eurio_id"], method=r["method"],
            rank=r["rank"], selected_sim=r["selected_sim"],
            file_url=file_url, face=face, resolution_status=status,
        ))
    return DinoReferencesResponse(
        eurio_id=eurio_id, class_id=class_id, anchors_kind=DINO_REF_KIND,
        never_built=not entries, entries=entries,
    )


class DinoRefActionPayload(BaseModel):
    action: str  # 'pin' | 'exclude' | 'clear'


class DinoRefActionResult(BaseModel):
    asset_id: str
    action: str
    # L'override est persisté, mais la banque n'est réécrite qu'au prochain build
    # (`go-task ml:dino-anchors:build`) — le front l'indique honnêtement.
    applied: bool
    rebuild_required: bool = True


# Consumed by: admin/.../coins/composables/useCoinAssets.ts (setDinoReference)
@router.post("/assets/{asset_id}/dino-reference", response_model=DinoRefActionResult)
def set_asset_dino_reference(
    asset_id: str, payload: DinoRefActionPayload,
) -> DinoRefActionResult:
    """Épingle (``pin``), bannit (``exclude``) ou réinitialise (``clear``) un
    crop comme référence Dino. Persisté dans ``dino_class_references`` ; effet au
    prochain build d'ancres (pas de rebuild live)."""
    conn = _conn()
    a = conn.execute(
        "SELECT eurio_id FROM image_assets WHERE id = ?", (asset_id,),
    ).fetchone()
    if a is None:
        raise HTTPException(status_code=404, detail="Crop introuvable")
    eurio_id = a["eurio_id"]
    if payload.action != "clear" and not eurio_id:
        raise HTTPException(
            status_code=422, detail="Crop sans eurio_id — réassigne-le d'abord",
        )
    class_id = _class_id_for(conn, eurio_id) or eurio_id
    with conn:
        if payload.action == "clear":
            clear_reference_override(conn, asset_id=asset_id, anchors_kind=DINO_REF_KIND)
            # Delete générique par égalité de clé → un row_op par méthode
            # manuelle (le replay ne sait pas exprimer un IN).
            row_ops = [
                {"op": "delete", "table": "dino_class_references",
                 "key": {"anchors_kind": DINO_REF_KIND, "asset_id": asset_id,
                         "method": m}}
                for m in ("manual_pin", "manual_exclude")
            ]
            reason = "dino_ref_clear"
        elif payload.action in ("pin", "exclude"):
            method = "manual_pin" if payload.action == "pin" else "manual_exclude"
            set_reference_override(
                conn, class_id=class_id, eurio_id=eurio_id, asset_id=asset_id,
                method=method, anchors_kind=DINO_REF_KIND,
            )
            row_ops = [{
                "op": "upsert", "table": "dino_class_references",
                "key": {"anchors_kind": DINO_REF_KIND, "class_id": class_id,
                        "asset_id": asset_id},
                "values": {"eurio_id": eurio_id, "method": method,
                           "rank": None, "selected_sim": None},
            }]
            reason = f"dino_ref_{payload.action}"
        else:
            raise HTTPException(status_code=422, detail=f"action invalide : {payload.action}")
        # Override humain de la banque d'ancres = autoritatif (non recomputable) →
        # voyage par row_ops (ligne non adressable par asset_id seul).
        emit_field_event(
            conn, asset_id=asset_id, reason=reason, fields={},
            detail={"row_ops": row_ops},
        )
    return DinoRefActionResult(asset_id=asset_id, action=payload.action, applied=True)


# ── Re-crop manuel EN PLACE (galerie enrichment, page coin-detail) ────────
# Même cœur que la voie review (POST /review-queue/{id}/manual-crop) mais keyé
# par asset_id : on recadre une vignette sans la renvoyer en queue — le statut
# (auto_name/manual) et l'eurio_id sont préservés (un recadrage ≠ une décision).
# Le « mauvaise pièce ? » reste la voie reflag → review. Cf. crop_edit.py.


def _bound_store() -> Store:
    if _store is None:
        raise RuntimeError("coin_assets_routes not bound — call bind() first.")
    return _store


if CROP_EDIT_AVAILABLE:
    # Consumed by: admin/.../coins/composables/useCoinAssets.ts (fetchAssetCropEditContext)
    @router.get("/assets/{asset_id}/crop-edit-context", response_model=CropEditContext)
    def get_asset_crop_edit_context(asset_id: str) -> CropEditContext:
        """Contexte de l'éditeur de cercle pour un asset (raw + cercle de départ)."""
        ctx = load_crop_edit_context(_bound_store(), asset_id)
        return _crop_edit_context_response(ctx)

    # Consumed by: admin/.../coins/composables/useCoinAssets.ts (manualCropAsset)
    @router.post("/assets/{asset_id}/manual-crop", response_model=ManualCropResponse)
    def manual_crop_asset(asset_id: str, payload: ManualCropPayload) -> ManualCropResponse:
        """Re-croppe l'asset en place (écrase cache + MinIO + DB au format prod).
        Statut / eurio_id inchangés."""
        data = apply_manual_crop(_bound_store(), asset_id, payload.cx, payload.cy, payload.r)
        return _manual_crop_response(data)
