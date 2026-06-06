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
from datetime import datetime
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from state import Store, emit_state_event

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


# ── Helpers ───────────────────────────────────────────────────────────────


def _row_to_asset(row: sqlite3.Row) -> CoinAsset:
    return CoinAsset(
        id=row["id"],
        source=row["source"],
        source_ref=row["source_ref"],
        listing_url=row["source_url"],
        listing_title=row["listing_title"],
        file_url=f"/sources/{row['source']}/assets/{row['id']}/file",
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
        if row["resolution_status"] in ("needs_review", "pending_crop", "pending_match"):
            n_skipped += 1
            reasons.append(f"{asset_id}: already_unresolved")
            continue

        with conn:  # transaction
            conn.execute(
                """
                UPDATE image_assets
                   SET resolution_status = 'needs_review',
                       resolved_at = NULL
                 WHERE id = ?
                """,
                (asset_id,),
            )
            existing = conn.execute(
                """
                SELECT id FROM review_queue
                 WHERE image_asset_id = ? AND status = 'open'
                """,
                (asset_id,),
            ).fetchone()
            if existing is None:
                conn.execute(
                    """
                    INSERT INTO review_queue (
                        id, image_asset_id, status, priority, enqueued_at,
                        kind, decision_notes
                    ) VALUES (
                        lower(hex(randomblob(16))), ?, 'open', 100, ?,
                        'single', 're-flagged from coin detail'
                    )
                    """,
                    (asset_id, now),
                )
            emit_state_event(
                conn, asset_id=asset_id, to_state="queued", actor="human",
                reason="reflagged_from_coin",
            )
        n_reflagged += 1

    logger.info(
        "[coin_assets] reflag asset_ids=%d reflagged=%d skipped=%d",
        len(payload.asset_ids), n_reflagged, n_skipped,
    )
    return ReflagResponse(
        n_reflagged=n_reflagged,
        n_skipped=n_skipped,
        skipped_reasons=reasons,
    )
