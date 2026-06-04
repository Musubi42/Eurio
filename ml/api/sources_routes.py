"""FastAPI router for the sources orchestrator (`/sources/...`).

Two surfaces:
- `GET /sources/status` — aggregated overview (delegated to
  `sources_aggregator.build_status`). Predates the orchestrator
  refacto, kept verbatim.
- Per-source orchestrator endpoints — wrap `ml/sources/_base/orchestrator`
  and the `source_runs` / `source_images` / `image_assets` /
  `coin_market_quotes` tables defined in `state/schema.sql`.

Long-running runs (`POST /sources/:id/runs`) are dispatched in a
background daemon thread. Polling is done via `GET /sources/:id/runs/:run_id`
which reads straight from `source_runs` — that table is the source of
truth, no in-memory job dict.
"""

from __future__ import annotations

import json
import logging
import sqlite3
import threading
from dataclasses import asdict
from typing import Any

from pathlib import Path

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from sources._base.adapter import DiscoveryGroup, SourceQuery
from sources._base.dedup import SourceImageRow, upsert_source_image
from sources._base.orchestrator import run_pipeline
from sources._base.run_logger import RunAlreadyRunning
from sources.ebay.standards import COMMEMO_IN_STANDARD_PREFIX
from state import Store

from . import sources_aggregator

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/sources", tags=["sources"])


# ── Adapter dispatch ──────────────────────────────────────────────────────
# Real sources land here as they get implemented. Until then, only `mock`
# can be triggered (CLI/front will get a clear 501 otherwise).

def _load_adapter(source_id: str, *, store: "Store" | None = None):
    if source_id == "mock":
        from sources._mock import MockAdapter
        return MockAdapter()
    if source_id == "ebay":
        import os
        from market.ebay_client import EbayClient, get_app_token
        from sources.ebay import EbayAdapter

        client_id = os.environ.get("EBAY_CLIENT_ID")
        client_secret = os.environ.get("EBAY_CLIENT_SECRET")
        if not client_id or not client_secret:
            raise HTTPException(
                status_code=503,
                detail="EBAY_CLIENT_ID / EBAY_CLIENT_SECRET not set in env (.envrc).",
            )
        token = get_app_token(client_id, client_secret)
        s = store or _store()
        conn = s._connection()  # noqa: SLF001
        # B4 — factory pour les N clients par mkt avec tracker partagé.
        from api_quota import QuotaTracker
        from market.ebay_client import EBAY_DAILY_LIMIT
        shared_tracker = QuotaTracker("ebay", "daily", EBAY_DAILY_LIMIT)
        make_client = lambda mkt: EbayClient(  # noqa: E731
            token, marketplace=mkt, tracker=shared_tracker,
        )
        return EbayAdapter(make_client=make_client, conn=conn)
    if source_id == "bce":
        from sources.bce import BceAdapter
        s = store or _store()
        conn = s._connection()  # noqa: SLF001
        return BceAdapter(conn=conn)
    raise HTTPException(
        status_code=501,
        detail=(
            f"Source '{source_id}' has no orchestrator adapter yet. "
            "Available: mock, ebay, bce. Real sources land as their adapters are written."
        ),
    )


def _store() -> Store:
    """The Store is a sibling of the runner-owned one, but pointing at the
    same SQLite file. We re-open lazily so background threads get their own
    thread-local connection (Store handles thread-locality)."""
    from .server import _store as shared_store
    return shared_store


# ── Status (existing) ─────────────────────────────────────────────────────


# Consumed by: admin/packages/web/src/features/sources/composables/useSourcesApi.ts (fetchSourcesStatus)
@router.get("/status")
def sources_status() -> dict:
    return sources_aggregator.build_status()


# ── Trigger a run (background thread) ─────────────────────────────────────


class GroupSpec(BaseModel):
    """Un groupe de découverte eBay.

    ``kind='commemorative'`` → ``(dénomination, pays, année)``.
    ``kind='standard'`` → ``(dénomination, pays)`` avec ``year=None`` (le
    design d'un standard couvre toutes les années — cf. ``DiscoveryGroup``).
    """

    denomination: float
    country: str
    year: int | None = None
    kind: str = "commemorative"


class RunQueryBody(BaseModel):
    """Filters forwarded to `SourceAdapter.discover()`.

    `discovery_groups` est le mode de découverte eBay (une recherche par
    groupe). `target_eurio_id(s)` reste le mode per-pièce des sources
    génériques ; pour eBay un `target_eurio_id` singulier est résolu vers
    *son* groupe.
    """

    country: str | None = None
    denomination: str | None = None
    year: int | None = None
    target_eurio_id: str | None = None
    target_eurio_ids: list[str] | None = None
    discovery_groups: list[GroupSpec] | None = None
    cohort_id: str | None = None
    limit: int | None = Field(default=None, ge=1, le=10_000)
    extra: dict[str, Any] = Field(default_factory=dict)

    def to_source_query(self, source_id: str) -> SourceQuery:
        d = self.model_dump()
        # cohort_id is an API-only convenience expanded to discovery_groups in
        # trigger_run; SourceQuery doesn't carry it.
        d.pop("cohort_id", None)
        if d.get("target_eurio_ids") is not None:
            d["target_eurio_ids"] = tuple(d["target_eurio_ids"])
        groups = d.pop("discovery_groups", None)
        if groups:
            d["discovery_groups"] = tuple(
                DiscoveryGroup(
                    denomination=g["denomination"],
                    country=g["country"],
                    year=g["year"],
                    kind=g.get("kind", "commemorative"),
                )
                for g in groups
            )
        return SourceQuery(source_id=source_id, **d)


class TriggerResponse(BaseModel):
    run_id: str
    status: str
    source_id: str
    kind: str
    # Cohort coins skipped because their (denom,country,year) isn't in the
    # commemorative eBay discovery view (standards/eu/variants — Numista-only).
    non_scrapable: list[str] | None = None


# Consumed by: admin/packages/web/src/features/sources/composables/useSourceDetail.ts (triggerSourceRun)
@router.post("/{source_id}/runs", response_model=TriggerResponse, status_code=202)
def trigger_run(
    source_id: str,
    body: RunQueryBody | None = None,
    dry_run: bool = Query(default=False),
    download_only: bool = Query(default=False),
    force: bool = Query(default=False),
) -> TriggerResponse:
    payload = body or RunQueryBody()
    store = _store()

    # Cohort-scoped eBay run : expand the cohort to its discovery groups before
    # building the query (only when no explicit groups were passed).
    non_scrapable: list[str] = []
    if source_id == "ebay" and payload.cohort_id and not payload.discovery_groups:
        from sources.cohort_scope import cohort_ebay_groups

        try:
            groups, non_scrapable = cohort_ebay_groups(store, payload.cohort_id)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        if not groups:
            raise HTTPException(
                status_code=400,
                detail={
                    "code": "cohort_no_groups",
                    "message": (
                        f"Cohort {payload.cohort_id}: aucun groupe eBay-scrapable "
                        "(que des standards/eu/variants ?)."
                    ),
                    "non_scrapable": non_scrapable,
                },
            )
        payload.discovery_groups = [
            GroupSpec(
                denomination=g.denomination, country=g.country,
                year=g.year, kind=g.kind,
            )
            for g in groups
        ]
        if non_scrapable:
            logger.info(
                "[ebay] cohort %s: %d coin(s) hors découverte groupée (Numista-only): %s",
                payload.cohort_id, len(non_scrapable), ", ".join(non_scrapable),
            )

    query = payload.to_source_query(source_id)

    # Garde-fou : un run eBay sans périmètre de découverte ne ferait
    # qu'échouer au step Discover. On rejette tôt et clairement plutôt
    # que de créer un run condamné (cas typique : front périmé qui POST
    # un body vide). Validé avant même de charger l'adapter. Chunk 1/3.
    if source_id == "ebay":
        has_scope = bool(
            query.discovery_groups or query.discovery_group
            or query.target_eurio_ids or query.target_eurio_id
        )
        if not has_scope:
            raise HTTPException(
                status_code=400,
                detail={
                    "code": "empty_discovery_scope",
                    "message": (
                        "Run eBay sans périmètre : aucun discovery_groups reçu. "
                        "Le front est probablement périmé — recharge la page "
                        "(hard reload) ou rebuild l'admin."
                    ),
                },
            )

    adapter = _load_adapter(source_id, store=store)
    if dry_run and hasattr(adapter, "dry_run"):
        adapter.dry_run = True

    # Pre-flight quota check (D-27) — eBay only, skip if dry_run.
    if source_id == "ebay" and not dry_run:
        n = _count_query_coins(store, query)
        if n > 0:
            preflight = check_ebay_quota(store, n_eurio_ids=n)
            if not preflight["ok"]:
                raise HTTPException(
                    status_code=409,
                    detail={
                        "code": "quota_insufficient",
                        "estimate": preflight["estimate"],
                        "remaining": preflight["remaining"],
                        "max_safe_batch": preflight["max_safe_batch"],
                        "message": (
                            f"Estimated {preflight['estimate']} calls × 1.3 safety > "
                            f"{preflight['remaining']} remaining today. "
                            f"Reduce batch to ≤{preflight['max_safe_batch']} or wait."
                        ),
                    },
                )

    # Pre-flight: open the run synchronously so the caller gets a real
    # run_id (and a clean 409 if anti-double-run trips). The actual
    # pipeline executes in a daemon thread.
    conn = store._connection()  # noqa: SLF001
    try:
        existing = conn.execute(
            "SELECT id FROM source_runs WHERE source = ? AND status = 'running' LIMIT 1",
            (source_id,),
        ).fetchone()
    except sqlite3.Error as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    if existing and not force:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "run_already_running",
                "run_id": existing["id"],
                "message": (
                    f"A run for '{source_id}' is already running. "
                    "Pass ?force=true to override."
                ),
            },
        )

    run_id_holder: dict[str, str] = {}
    started = threading.Event()

    def _runner() -> None:
        try:
            # BCE a son pipeline dédié (pas de MinIO, pas de detect/resolve/
            # price_aggregate — cible = coin_canonical_images). Cf.
            # ml/sources/bce/pipeline.py.
            if source_id == "bce":
                from sources.bce.pipeline import run_bce_pipeline
                rid = run_bce_pipeline(
                    adapter, query, store=store, dry_run=dry_run, force=force,
                )
            else:
                rid = run_pipeline(
                    adapter, query, store=store,
                    dry_run=dry_run, download_only=download_only, force=force,
                )
            run_id_holder["run_id"] = rid
        except RunAlreadyRunning as exc:
            logger.warning("[%s] anti-double-run tripped: %s", source_id, exc)
            run_id_holder["error"] = str(exc)
        except Exception:
            logger.exception("[%s] orchestrator crashed", source_id)
            # The run row (if it was opened) is marked 'failed' by the
            # run_logger context manager. Nothing else to do here.
        finally:
            started.set()

    # We need the run_id back synchronously; the cleanest way is to
    # have run_pipeline open the row before the thread returns. Since
    # start_run() runs at the top of run_pipeline(), the row exists
    # within ms — we wait briefly so the response carries the real id.
    thread = threading.Thread(
        target=_runner, name=f"src-run-{source_id}", daemon=True
    )
    thread.start()

    # Block up to 2s waiting for the row to materialize. On timeout we
    # fall back to the most recent 'running' row for this source — the
    # thread has surely opened it by then in any plausible scenario.
    started.wait(timeout=2.0)
    rid = run_id_holder.get("run_id")
    if rid is None:
        row = conn.execute(
            "SELECT id, kind FROM source_runs WHERE source = ? "
            "ORDER BY started_at DESC LIMIT 1",
            (source_id,),
        ).fetchone()
        if row is None:
            raise HTTPException(
                status_code=500,
                detail="Run thread did not register a source_runs row in time.",
            )
        rid = row["id"]

    return TriggerResponse(
        run_id=rid,
        status="started",
        source_id=source_id,
        kind="dry" if dry_run else "run",
        non_scrapable=non_scrapable or None,
    )


# ── Single run snapshot (polling target) ──────────────────────────────────


class RunSnapshot(BaseModel):
    id: str
    source: str
    kind: str
    status: str
    current_step: str | None
    started_at: str
    ended_at: str | None
    duration_s: float | None
    n_calls: int
    n_raws_added: int
    n_crops_added: int
    n_quotes_added: int
    n_pending_added: int
    n_auto_resolved: int
    n_review_enqueued: int
    n_errors: int
    # Compteur LIVE (recalculé à chaque lecture) des listings dont le
    # téléchargement a échoué — c'est l'erreur actionnable : un bouton
    # « réessayer » la cible. Distinct de `n_errors` (cumulatif historique).
    n_downloads_failed: int = 0
    filters: dict[str, Any]
    error_summary: str | None
    log_path: str | None


def _count_downloads_failed(conn: sqlite3.Connection, run_id: str) -> int:
    row = conn.execute(
        "SELECT count(*) AS n FROM source_images "
        "WHERE run_id = ? AND download_status = 'failed'",
        (run_id,),
    ).fetchone()
    return int(row["n"] or 0)


# Consumed by: admin/packages/web/src/features/sources/composables/useSourceDetail.ts (fetchSourceRun, pollSourceRun)
@router.get("/{source_id}/runs/{run_id}", response_model=RunSnapshot)
def get_run(source_id: str, run_id: str) -> RunSnapshot:
    conn = _store()._connection()  # noqa: SLF001
    row = conn.execute(
        "SELECT * FROM source_runs WHERE id = ? AND source = ?",
        (run_id, source_id),
    ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail=f"Run '{run_id}' not found.")
    return _row_to_snapshot(row, n_downloads_failed=_count_downloads_failed(conn, run_id))


def _row_to_snapshot(row: sqlite3.Row, *, n_downloads_failed: int = 0) -> RunSnapshot:
    started = row["started_at"]
    ended = row["ended_at"]
    duration: float | None = None
    if started and ended:
        try:
            from datetime import datetime
            t0 = datetime.fromisoformat(started.replace(" ", "T"))
            t1 = datetime.fromisoformat(ended.replace(" ", "T"))
            duration = (t1 - t0).total_seconds()
        except Exception:  # noqa: BLE001 — duration is informational
            duration = None

    filters: dict[str, Any] = {}
    if row["filters_json"]:
        try:
            filters = json.loads(row["filters_json"])
        except json.JSONDecodeError:
            filters = {"_raw": row["filters_json"]}

    return RunSnapshot(
        id=row["id"],
        source=row["source"],
        kind=row["kind"],
        status=row["status"],
        current_step=row["current_step"],
        started_at=started,
        ended_at=ended,
        duration_s=duration,
        n_calls=row["n_calls"],
        n_raws_added=row["n_raws_added"],
        n_crops_added=row["n_crops_added"],
        n_quotes_added=row["n_quotes_added"],
        n_pending_added=row["n_pending_added"],
        n_auto_resolved=row["n_auto_resolved"],
        n_review_enqueued=row["n_review_enqueued"],
        n_errors=row["n_errors"],
        n_downloads_failed=n_downloads_failed,
        filters=filters,
        error_summary=row["error_summary"],
        log_path=row["log_path"],
    )


# ── Retry des téléchargements échoués d'un run ────────────────────────────


class RetryDownloadsResponse(BaseModel):
    run_id: str
    status: str               # 'started'
    n_downloads_failed: int   # nombre de DL en échec relancés


# Consumed by: admin/packages/web/src/features/sources/composables/useSourceDetail.ts (retryRunDownloads)
@router.post(
    "/{source_id}/runs/{run_id}/retry-downloads",
    response_model=RetryDownloadsResponse,
    status_code=202,
)
def retry_run_downloads(source_id: str, run_id: str) -> RetryDownloadsResponse:
    """Relance les téléchargements échoués d'un run (connexion instable).

    Rejoue download → detect → resolve → enqueue sur les seuls listings
    dont le DL avait échoué, puis ré-agrège les prix. Exécuté en thread
    daemon ; le front suit la progression via ``GET /runs/{run_id}``.
    """
    store = _store()
    conn = store._connection()  # noqa: SLF001
    row = conn.execute(
        "SELECT id, status FROM source_runs WHERE id = ? AND source = ?",
        (run_id, source_id),
    ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail=f"Run '{run_id}' not found.")
    if row["status"] == "running":
        raise HTTPException(
            status_code=409,
            detail={"code": "run_running", "message": "Run en cours — attends la fin."},
        )
    n_failed = _count_downloads_failed(conn, run_id)
    if n_failed == 0:
        raise HTTPException(
            status_code=400,
            detail={
                "code": "nothing_to_retry",
                "message": "Aucun téléchargement en échec sur ce run.",
            },
        )

    adapter = _load_adapter(source_id, store=store)

    def _runner() -> None:
        try:
            from sources._base.orchestrator import resume_failed_downloads
            resume_failed_downloads(adapter, store=store, run_id=run_id)
        except Exception:  # noqa: BLE001
            logger.exception("[%s] retry-downloads crashed run=%s", source_id, run_id)

    threading.Thread(
        target=_runner, name=f"retry-dl-{run_id}", daemon=True,
    ).start()
    return RetryDownloadsResponse(
        run_id=run_id, status="started", n_downloads_failed=n_failed,
    )


# ── Crop à la demande d'un run lancé en download-only ─────────────────────


class CropPendingResponse(BaseModel):
    run_id: str
    status: str       # 'started'
    n_pending: int    # source_images téléchargées en attente de crop


def _count_downloaded_pending(conn: sqlite3.Connection, run_id: str) -> int:
    """Images téléchargées du run pas encore croppées (aucun image_assets)."""
    row = conn.execute(
        """
        SELECT count(*) AS n FROM source_images si
         WHERE si.run_id = ?
           AND si.download_status = 'success'
           AND NOT EXISTS (
                 SELECT 1 FROM image_assets ia
                  WHERE ia.source_image_id = si.id
                    AND ia.storage_path IS NOT NULL
                    AND ia.storage_status = 'present'
           )
        """,
        (run_id,),
    ).fetchone()
    return int(row["n"] or 0)


# Consumed by: admin front /sources (bouton "Cropper" sur un run download-only)
@router.post(
    "/{source_id}/runs/{run_id}/crop",
    response_model=CropPendingResponse,
    status_code=202,
)
def crop_run_pending(source_id: str, run_id: str) -> CropPendingResponse:
    """Déclenche le crop différé d'un run lancé en download-only.

    Enchaîne detect → resolve → auto_validate → enqueue → price_aggregate sur
    les raws du run, en thread daemon. Le front suit via ``GET /runs/{run_id}``.
    Idempotent : les images déjà croppées sont sautées.
    """
    store = _store()
    conn = store._connection()  # noqa: SLF001
    row = conn.execute(
        "SELECT id, status FROM source_runs WHERE id = ? AND source = ?",
        (run_id, source_id),
    ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail=f"Run '{run_id}' not found.")
    if row["status"] == "running":
        raise HTTPException(
            status_code=409,
            detail={"code": "run_running", "message": "Run en cours — attends la fin."},
        )
    n_pending = _count_downloaded_pending(conn, run_id)
    if n_pending == 0:
        raise HTTPException(
            status_code=400,
            detail={
                "code": "nothing_to_crop",
                "message": "Aucune image téléchargée en attente de crop sur ce run.",
            },
        )

    def _runner() -> None:
        try:
            from sources._base.orchestrator import process_downloaded
            process_downloaded(store=store, run_id=run_id)
        except Exception:  # noqa: BLE001
            logger.exception("[%s] crop-pending crashed run=%s", source_id, run_id)

    threading.Thread(
        target=_runner, name=f"crop-{run_id}", daemon=True,
    ).start()
    return CropPendingResponse(run_id=run_id, status="started", n_pending=n_pending)


# ── Run breakdown (per-eurio_id drill-down) ───────────────────────────────
#
# Cf. docs/sources-refacto/run-breakdown-kickoff.md.
#
# Pure aggregation over existing FK (source_images.run_id, image_assets.run_id,
# coin_market_quotes.run_id, review_queue joined via image_asset_id). No
# schema change. ONE flat list `per_eurio`, ordered: was_targeted=True first
# (preserving user-provided order), then discovered eurios alphabetical.
#
# Counter semantics — designed to leave NO ambiguity, no double-count.
# Each crop belongs to exactly ONE listing with ONE target_eurio_id, so we
# split stats into two strictly disjoint axes per eurio_id E:
#
#   - Search axis (joined via si.target_eurio_id = E): "what came back when
#     we searched for E?" Crops in those listings are partitioned by
#     resolution status — n_searched_auto + n_searched_review_single +
#     n_searched_review_lot + n_searched_pending + n_searched_rejected
#     equals n_crops_searched (the partition is exhaustive).
#
#   - Attribution axis (joined via ia.eurio_id = E AND si.target_eurio_id
#     != E or NULL): "crops attributed to E from listings searched for
#     something else" — typical lot routing case. Disjoint from search axis
#     by construction.
#
# Total crops "ever attributed to E this run" = n_searched_auto + n_attributed_from_other.
# Total crops "in searches for E"             = n_crops_searched.


_AUTO_STATUSES = ("auto_name", "auto_phash", "manual")
_PENDING_STATUSES = ("pending_match", "pending_crop", "needs_review")


class RunBreakdownEntry(BaseModel):
    eurio_id: str
    was_targeted: bool

    # ── Search axis (si.target_eurio_id = E) ──────────────────────────
    n_listings: int                # source_images cherchés pour E
    n_crops_searched: int          # crops dans ces listings

    # Partition exhaustive de n_crops_searched par statut :
    n_searched_auto: int           # status IN auto_name|auto_phash|manual
    n_searched_review_single: int  # rq.kind='single' AND rq.status='open'
    n_searched_review_lot: int     # rq.kind='lot'    AND rq.status='open'
    n_searched_pending: int        # status IN pending_match|pending_crop|needs_review
                                   # ET pas d'entrée review_queue open
    n_searched_rejected: int       # status = 'rejected'

    # ── Attribution axis (ia.eurio_id = E AND si.target_eurio_id != E) ──
    n_attributed_from_other: int   # crops résolus à E depuis un listing
                                   # cherché pour autre chose (cas lot)
    via_lot: bool                  # au moins un de ces crops vient d'un
                                   # listing is_lot_suspected ou multi-crop

    # ── Output ────────────────────────────────────────────────────────
    n_quotes: int                  # coin_market_quotes.eurio_id = E

    # ── Marketplaces (B4 multi-mkt) ─────────────────────────────────────
    marketplaces: list[str]        # mkts ayant produit ≥1 listing pour E
                                   # (source_images.marketplace distinct)


class RunBreakdown(BaseModel):
    run_id: str
    source_id: str
    started_at: str
    status: str
    filters: dict[str, Any]
    per_eurio: list[RunBreakdownEntry]


def _search_axis_stats(
    conn: sqlite3.Connection, *, run_id: str, eurio_id: str,
) -> dict[str, int]:
    """Stats par eurio_id : listings/crops attribués ou candidats.

    Inclut deux cas :
    - **target résolu** (verdict theme-match 'single') : `si.target_eurio_id
      = eurio_id`. Attribution nette.
    - **candidat ambigu** (verdict 'ambiguous' ou 'lot' multi-coin) :
      `si.target_eurio_id IS NULL` mais l'eurio apparaît dans
      `image_assets.candidate_eurio_ids_json` de l'une de ses crops.
      Permet aux coins en groupes multi-coins (ex: FR/2018 Bleuet ↔
      Simone Veil) d'afficher le pool de listings désambiguables côté
      review. Conséquence : double-count entre coins sœurs — assumé.
    """
    cands_pattern = f'%"{eurio_id}"%'
    # source_images : target résolu OU group_candidates contient l'eurio
    # (couvre les listings zero-crops sans image_assets pour les multi-coin
    # groups — la donnée existe côté raw_payload_json même si la crop n'a
    # rien donné).
    n_listings = conn.execute(
        """
        SELECT COUNT(*) AS n
          FROM source_images si
         WHERE si.run_id = ?
           AND (
             si.target_eurio_id = ?
             OR (si.target_eurio_id IS NULL
                 AND si.raw_payload_json LIKE ?)
           )
        """,
        (run_id, eurio_id, cands_pattern),
    ).fetchone()["n"]

    crops = conn.execute(
        """
        SELECT DISTINCT ia.id, ia.resolution_status
          FROM image_assets ia
          JOIN source_images si ON si.id = ia.source_image_id
         WHERE ia.run_id = ?
           AND (
             si.target_eurio_id = ?
             OR (si.target_eurio_id IS NULL
                 AND ia.candidate_eurio_ids_json LIKE ?)
           )
        """,
        (run_id, eurio_id, cands_pattern),
    ).fetchall()

    n_auto = 0
    n_pending = 0
    n_rejected = 0
    review_assets: list[str] = []
    for c in crops:
        st = c["resolution_status"]
        if st in _AUTO_STATUSES:
            n_auto += 1
        elif st == "rejected":
            n_rejected += 1
        else:
            # pending_*, needs_review — review_queue may or may not have a row
            review_assets.append(c["id"])
            if st in _PENDING_STATUSES:
                n_pending += 1

    n_rev_single = 0
    n_rev_lot = 0
    if review_assets:
        placeholders = ",".join("?" * len(review_assets))
        rows = conn.execute(
            f"SELECT kind, COUNT(*) AS n FROM review_queue "
            f"WHERE status = 'open' AND image_asset_id IN ({placeholders}) "
            f"GROUP BY kind",
            review_assets,
        ).fetchall()
        for r in rows:
            if r["kind"] == "single":
                n_rev_single = r["n"]
            elif r["kind"] == "lot":
                n_rev_lot = r["n"]
        # Anything in review_queue moves out of "pending" bucket — review
        # is the active state. Pending = needs the resolver/reviewer but
        # not yet enqueued.
        n_pending = max(0, n_pending - (n_rev_single + n_rev_lot))

    return {
        "n_listings": n_listings,
        "n_crops_searched": len(crops),
        "n_searched_auto": n_auto,
        "n_searched_review_single": n_rev_single,
        "n_searched_review_lot": n_rev_lot,
        "n_searched_pending": n_pending,
        "n_searched_rejected": n_rejected,
    }


def _attribution_axis_stats(
    conn: sqlite3.Connection, *, run_id: str, eurio_id: str,
) -> int:
    """Crops resolved to `eurio_id` from listings searched for OTHER eurios."""
    n = conn.execute(
        """
        SELECT COUNT(*) AS n
          FROM image_assets ia
          JOIN source_images si ON si.id = ia.source_image_id
         WHERE ia.run_id = ?
           AND ia.eurio_id = ?
           AND (si.target_eurio_id IS NULL OR si.target_eurio_id != ?)
        """,
        (run_id, eurio_id, eurio_id),
    ).fetchone()["n"]
    return int(n or 0)


def _has_lot_context(
    conn: sqlite3.Connection, *, run_id: str, eurio_id: str,
) -> bool:
    """True if any source_image touched by `eurio_id` (via search axis OR
    attribution axis) is is_lot_suspected OR multi-crop.

    Search axis  : si.target_eurio_id = E
    Attribution  : ia.eurio_id = E (ia.run_id = run, ia inside si)
    """
    row = conn.execute(
        """
        SELECT 1
          FROM source_images si
         WHERE si.run_id = ?
           AND (
             si.target_eurio_id = ?
             OR EXISTS (
               SELECT 1 FROM image_assets ia
                WHERE ia.source_image_id = si.id
                  AND ia.run_id = ?
                  AND ia.eurio_id = ?
             )
           )
           AND (
             si.is_lot_suspected = 1
             OR (
               SELECT COUNT(*) FROM image_assets ia2
                WHERE ia2.source_image_id = si.id
             ) > 1
           )
         LIMIT 1
        """,
        (run_id, eurio_id, run_id, eurio_id),
    ).fetchone()
    return row is not None


def _quotes_for(
    conn: sqlite3.Connection, *, run_id: str, eurio_id: str,
) -> int:
    return conn.execute(
        "SELECT COUNT(*) AS n FROM coin_market_quotes "
        "WHERE run_id = ? AND eurio_id = ?",
        (run_id, eurio_id),
    ).fetchone()["n"]


def _marketplaces_for(
    conn: sqlite3.Connection, *, run_id: str, eurio_id: str,
) -> list[str]:
    """Marketplaces ayant produit ≥ 1 listing cherché pour cet eurio_id.

    Lit ``source_images.marketplace`` (renseigné par l'adapter multi-mkt
    B4). Les rows pré-bascule ont ``marketplace`` NULL → exclues. Tri
    alphabétique pour un rendu stable des badges côté front.
    """
    rows = conn.execute(
        """
        SELECT DISTINCT marketplace
          FROM source_images
         WHERE run_id = ? AND target_eurio_id = ? AND marketplace IS NOT NULL
         ORDER BY marketplace
        """,
        (run_id, eurio_id),
    ).fetchall()
    return [r["marketplace"] for r in rows]


def compute_run_breakdown(
    conn: sqlite3.Connection, *, run_id: str, source_id: str,
) -> RunBreakdown:
    """Build the per-eurio_id breakdown for a single run.

    Raises HTTPException(404) if the run doesn't exist.
    """
    row = conn.execute(
        "SELECT * FROM source_runs WHERE id = ? AND source = ?",
        (run_id, source_id),
    ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail=f"Run '{run_id}' not found.")

    filters: dict[str, Any] = {}
    if row["filters_json"]:
        try:
            filters = json.loads(row["filters_json"])
        except json.JSONDecodeError:
            filters = {"_raw": row["filters_json"]}

    # Périmètre « ciblé » du run. Deux modes :
    # - découverte groupée (`discovery_groups`) : ciblé = toute commémo
    #   d'un groupe (denom, pays, année) interrogé — y compris celles sans
    #   listing, pour rendre visibles les trous de couverture ;
    # - découverte per-pièce (`target_eurio_ids`) : ciblé = la liste brute.
    targeted_set: set[str] = set()
    targeted_ordered: list[str] = []

    groups = filters.get("discovery_groups")
    if isinstance(groups, list) and groups:
        for g in groups:
            if not isinstance(g, dict):
                continue
            try:
                coin_rows = conn.execute(
                    "SELECT eurio_id FROM coins "
                    "WHERE face_value = ? AND country = ? AND year = ? "
                    "AND is_commemorative = 1 ORDER BY eurio_id",
                    (g["denomination"], g["country"], g["year"]),
                ).fetchall()
            except (KeyError, sqlite3.Error):
                continue
            for r in coin_rows:
                eid = r["eurio_id"]
                if eid not in targeted_set:
                    targeted_set.add(eid)
                    targeted_ordered.append(eid)
    else:
        raw_targets = filters.get("target_eurio_ids") or []
        if not isinstance(raw_targets, list):
            raw_targets = []
        for eid in raw_targets:
            if isinstance(eid, str) and eid not in targeted_set:
                targeted_set.add(eid)
                targeted_ordered.append(eid)

    # Discovered eurios = resolved this run AND not in targets.
    resolved_rows = conn.execute(
        """
        SELECT DISTINCT eurio_id
          FROM image_assets
         WHERE run_id = ? AND eurio_id IS NOT NULL
        """,
        (run_id,),
    ).fetchall()
    discovered_ordered = sorted(
        r["eurio_id"] for r in resolved_rows
        if r["eurio_id"] not in targeted_set
    )

    def _build_entry(eid: str, *, was_targeted: bool) -> RunBreakdownEntry:
        search_stats = _search_axis_stats(conn, run_id=run_id, eurio_id=eid)
        attr_count = _attribution_axis_stats(
            conn, run_id=run_id, eurio_id=eid,
        )
        via_lot = _has_lot_context(conn, run_id=run_id, eurio_id=eid)
        n_quotes = _quotes_for(conn, run_id=run_id, eurio_id=eid)
        marketplaces = _marketplaces_for(conn, run_id=run_id, eurio_id=eid)
        return RunBreakdownEntry(
            eurio_id=eid,
            was_targeted=was_targeted,
            n_attributed_from_other=attr_count,
            via_lot=via_lot,
            n_quotes=n_quotes,
            marketplaces=marketplaces,
            **search_stats,
        )

    per_eurio = [
        _build_entry(eid, was_targeted=True) for eid in targeted_ordered
    ] + [
        _build_entry(eid, was_targeted=False) for eid in discovered_ordered
    ]

    return RunBreakdown(
        run_id=row["id"],
        source_id=row["source"],
        started_at=row["started_at"],
        status=row["status"],
        filters=filters,
        per_eurio=per_eurio,
    )


# Consumed by: admin/packages/web/src/features/sources/composables/useRunBreakdown.ts (fetchRunBreakdown)
@router.get(
    "/{source_id}/runs/{run_id}/breakdown",
    response_model=RunBreakdown,
)
def get_run_breakdown(source_id: str, run_id: str) -> RunBreakdown:
    conn = _store()._connection()  # noqa: SLF001
    return compute_run_breakdown(conn, run_id=run_id, source_id=source_id)


# ── Run listings (per-listing pipeline-decision drill-down) ───────────────
#
# Cf. docs/sources-refacto/listing-debug-view-kickoff.md.
# Lecture seule, orientée debug : pour chaque source_image du run on retourne
# les verdicts persistés par les steps (download/crop/route) + la trace par
# crop (image_assets + review_queue).


class ListingCropAsset(BaseModel):
    asset_id: str
    crop_index: int
    resolution_status: str | None = None
    eurio_id: str | None = None
    review_id: str | None = None
    review_kind: str | None = None  # 'lot' | 'single' (review_queue.kind)


class ListingDetail(BaseModel):
    source_image_id: str
    source_ref: str
    source_url: str | None = None
    target_eurio_id: str | None = None
    listing_title: str | None = None
    listing_country: str | None = None
    listing_year: int | None = None
    listing_price: float | None = None
    listing_currency: str | None = None
    seller_id: str | None = None
    is_lot_suspected: bool = False
    fetched_at: str | None = None

    download_endpoint: str | None = None
    download_status: str | None = None
    download_http_status: int | None = None
    download_error: str | None = None

    crop_status: str | None = None
    crop_error: str | None = None
    n_crops_detected: int | None = None

    route_decision: str | None = None
    route_reason: str | None = None

    crops: list[ListingCropAsset] = []


class RunListings(BaseModel):
    run_id: str
    source_id: str
    listings: list[ListingDetail]


# Consumed by: admin/packages/web/src/features/sources/composables/useRunListings.ts (fetchRunListings)
@router.get(
    "/{source_id}/runs/{run_id}/listings",
    response_model=RunListings,
)
def get_run_listings(
    source_id: str,
    run_id: str,
    eurio_id: str | None = Query(default=None, description="Filtrer sur un eurio_id ciblé"),
) -> RunListings:
    conn = _store()._connection()  # noqa: SLF001

    sql = """
        SELECT id AS source_image_id, source_ref, source_url, target_eurio_id,
               listing_title, listing_country, listing_year, listing_price,
               listing_currency, seller_id, is_lot_suspected, fetched_at,
               download_endpoint, download_status, download_http_status, download_error,
               crop_status, crop_error, n_crops_detected,
               route_decision, route_reason
          FROM source_images
         WHERE source = ? AND run_id = ?
    """
    params: list[Any] = [source_id, run_id]
    if eurio_id is not None:
        sql += " AND target_eurio_id = ?"
        params.append(eurio_id)
    sql += " ORDER BY fetched_at ASC, source_ref ASC"

    rows = conn.execute(sql, params).fetchall()
    if not rows:
        return RunListings(run_id=run_id, source_id=source_id, listings=[])

    sids = [r["source_image_id"] for r in rows]
    placeholders = ",".join("?" * len(sids))
    asset_rows = conn.execute(
        f"""
        SELECT a.id AS asset_id, a.source_image_id, a.crop_index,
               a.resolution_status, a.eurio_id,
               rq.id AS review_id, rq.kind AS review_kind
          FROM image_assets a
          LEFT JOIN review_queue rq ON rq.image_asset_id = a.id
         WHERE a.source_image_id IN ({placeholders})
         ORDER BY a.source_image_id, a.crop_index
        """,
        sids,
    ).fetchall()

    crops_by_sid: dict[str, list[ListingCropAsset]] = {}
    for ar in asset_rows:
        crops_by_sid.setdefault(ar["source_image_id"], []).append(
            ListingCropAsset(
                asset_id=ar["asset_id"],
                crop_index=ar["crop_index"],
                resolution_status=ar["resolution_status"],
                eurio_id=ar["eurio_id"],
                review_id=ar["review_id"],
                review_kind=ar["review_kind"],
            )
        )

    listings = [
        ListingDetail(
            source_image_id=r["source_image_id"],
            source_ref=r["source_ref"],
            source_url=r["source_url"],
            target_eurio_id=r["target_eurio_id"],
            listing_title=r["listing_title"],
            listing_country=r["listing_country"],
            listing_year=r["listing_year"],
            listing_price=r["listing_price"],
            listing_currency=r["listing_currency"],
            seller_id=r["seller_id"],
            is_lot_suspected=bool(r["is_lot_suspected"]),
            fetched_at=r["fetched_at"],
            download_endpoint=r["download_endpoint"],
            download_status=r["download_status"],
            download_http_status=r["download_http_status"],
            download_error=r["download_error"],
            crop_status=r["crop_status"],
            crop_error=r["crop_error"],
            n_crops_detected=r["n_crops_detected"],
            route_decision=r["route_decision"],
            route_reason=r["route_reason"],
            crops=crops_by_sid.get(r["source_image_id"], []),
        )
        for r in rows
    ]
    return RunListings(run_id=run_id, source_id=source_id, listings=listings)


# ── Discovery searches (per-call API debug log) ───────────────────────────
#
# Cf. docs/sources-refacto/listing-debug-view-kickoff.md.
# 1 row par appel adapter.discover() pour un (run, target_eurio_id). Permet
# de distinguer "vraiment 0 résultat" de "scrape pas exécuté / failed /
# post-filter trop strict".


class DiscoverySearchItem(BaseModel):
    id: str
    target_eurio_id: str | None = None
    endpoint: str | None = None
    query_q: str | None = None
    query_filters: dict[str, Any] | None = None
    status: str
    http_status: int | None = None
    # Funnel ventilé (chunk 0 auto-validation : "visibilité du stream") :
    # n_summaries → n_after_groups → n_raw_results → n_kept_results.
    n_summaries: int | None = None
    n_after_groups: int | None = None
    n_raw_results: int | None = None
    n_kept_results: int | None = None
    duration_ms: int | None = None
    error: str | None = None
    # eBay multi-mkt : marketplace ciblé par cette search (distingue les
    # 2 rows DE/ES d'un même groupe). NULL pour les sources mono-mkt.
    marketplace: str | None = None
    # F3 — URL d'appel Browse exacte (rejouable). NULL si l'appel n'a pas
    # atteint le serveur, ou sur les runs antérieurs au chunk F3.
    browse_url: str | None = None
    created_at: str


class RunSearches(BaseModel):
    run_id: str
    source_id: str
    searches: list[DiscoverySearchItem]


# Consumed by: admin/packages/web/src/features/sources/composables/useRunSearches.ts (fetchRunSearches)
@router.get(
    "/{source_id}/runs/{run_id}/searches",
    response_model=RunSearches,
)
def get_run_searches(
    source_id: str,
    run_id: str,
    eurio_id: str | None = Query(default=None, description="Filtrer sur un eurio_id ciblé"),
) -> RunSearches:
    conn = _store()._connection()  # noqa: SLF001

    sql = """
        SELECT id, target_eurio_id, endpoint, query_q, query_filters_json,
               status, http_status,
               n_summaries, n_after_groups, n_raw_results, n_kept_results,
               duration_ms, error, marketplace, browse_url, created_at
          FROM discovery_searches
         WHERE source = ? AND run_id = ?
    """
    params: list[Any] = [source_id, run_id]
    if eurio_id is not None:
        # Une recherche groupée n'a pas de target_eurio_id (NULL) : elle
        # couvre un groupe (denom, pays, année). On résout l'eurio_id vers
        # son groupe et on matche aussi les searches de ce groupe.
        coin = conn.execute(
            "SELECT face_value, country, year FROM coins WHERE eurio_id = ?",
            (eurio_id,),
        ).fetchone()
        if coin is not None:
            sql += (
                " AND ( target_eurio_id = ?"
                "       OR ( json_extract(query_filters_json, '$.group.denomination') = ?"
                "            AND json_extract(query_filters_json, '$.group.country') = ?"
                "            AND json_extract(query_filters_json, '$.group.year') = ? ) )"
            )
            params += [eurio_id, coin["face_value"], coin["country"], coin["year"]]
        else:
            sql += " AND target_eurio_id = ?"
            params.append(eurio_id)
    sql += " ORDER BY created_at ASC"

    rows = conn.execute(sql, params).fetchall()
    searches = [
        DiscoverySearchItem(
            id=r["id"],
            target_eurio_id=r["target_eurio_id"],
            endpoint=r["endpoint"],
            query_q=r["query_q"],
            query_filters=json.loads(r["query_filters_json"]) if r["query_filters_json"] else None,
            status=r["status"],
            http_status=r["http_status"],
            n_summaries=r["n_summaries"],
            n_after_groups=r["n_after_groups"],
            n_raw_results=r["n_raw_results"],
            n_kept_results=r["n_kept_results"],
            duration_ms=r["duration_ms"],
            error=r["error"],
            marketplace=r["marketplace"],
            browse_url=r["browse_url"],
            created_at=r["created_at"],
        )
        for r in rows
    ]
    return RunSearches(run_id=run_id, source_id=source_id, searches=searches)


# ── Discarded listings (audit trail des rejets pré-ingestion) ─────────────
#
# Chunk 0 auto-validation ("visibilité du stream") : expose les rejets
# accept_listing + theme_mismatch déjà persistés en `discarded_listings`
# pour les rendre lisibles côté admin. Le but est de comprendre pourquoi
# le funnel raw → kept rétrécit, raison par raison.


class DiscardedListingItem(BaseModel):
    id: str
    source_ref: str
    target_eurio_id: str | None = None
    reason: str
    title: str | None = None
    item_id: str | None = None
    item_web_url: str | None = None
    price: float | None = None
    currency: str | None = None
    raw_payload: dict[str, Any] | None = None
    created_at: str


class DiscardedReasonGroup(BaseModel):
    reason: str
    count: int


class RunDiscarded(BaseModel):
    run_id: str
    source_id: str
    total: int
    by_reason: list[DiscardedReasonGroup]
    listings: list[DiscardedListingItem]


# Consumed by: admin/packages/web/src/features/sources/composables/useRunDiscarded.ts (fetchRunDiscarded)
@router.get(
    "/{source_id}/runs/{run_id}/discarded",
    response_model=RunDiscarded,
)
def get_run_discarded(
    source_id: str,
    run_id: str,
    eurio_id: str | None = Query(default=None, description="Filtrer sur un eurio_id ciblé"),
    reason: str | None = Query(default=None, description="Filtrer sur une raison de rejet"),
) -> RunDiscarded:
    """Retourne les listings rejetés pré-ingestion pour un run.

    Sources des rejets : `accept_listing` (`noise_title`, `year_mismatch`,
    `non_eur`, `below_face`, `above_extreme`, `no_price`) et le filtre
    theme-tokens (`theme_mismatch`, depuis chunk 0).
    """
    conn = _store()._connection()  # noqa: SLF001

    sql = """
        SELECT id, source_ref, target_eurio_id, reason, title,
               raw_payload, created_at
          FROM discarded_listings
         WHERE source = ? AND run_id = ?
    """
    params: list[Any] = [source_id, run_id]
    if eurio_id is not None:
        sql += " AND target_eurio_id = ?"
        params.append(eurio_id)
    if reason is not None:
        sql += " AND reason = ?"
        params.append(reason)
    sql += " ORDER BY created_at ASC"

    rows = conn.execute(sql, params).fetchall()

    listings: list[DiscardedListingItem] = []
    for r in rows:
        payload: dict[str, Any] | None = None
        if r["raw_payload"]:
            try:
                payload = json.loads(r["raw_payload"])
            except (TypeError, ValueError):
                payload = None
        item_id = (payload or {}).get("item_id") if payload else None
        item_web_url = (payload or {}).get("item_web_url") if payload else None
        price = (payload or {}).get("price") if payload else None
        currency = (payload or {}).get("currency") if payload else None
        listings.append(DiscardedListingItem(
            id=r["id"],
            source_ref=r["source_ref"],
            target_eurio_id=r["target_eurio_id"],
            reason=r["reason"],
            title=r["title"],
            item_id=str(item_id) if item_id is not None else None,
            item_web_url=item_web_url if isinstance(item_web_url, str) else None,
            price=float(price) if isinstance(price, (int, float)) else None,
            currency=currency if isinstance(currency, str) else None,
            raw_payload=payload,
            created_at=r["created_at"],
        ))

    by_reason_rows = conn.execute(
        """
        SELECT reason, COUNT(*) AS n
          FROM discarded_listings
         WHERE source = ? AND run_id = ?
         GROUP BY reason
         ORDER BY n DESC, reason ASC
        """,
        (source_id, run_id),
    ).fetchall()
    by_reason = [
        DiscardedReasonGroup(reason=r["reason"], count=int(r["n"]))
        for r in by_reason_rows
    ]
    total = sum(g.count for g in by_reason)

    return RunDiscarded(
        run_id=run_id,
        source_id=source_id,
        total=total,
        by_reason=by_reason,
        listings=listings,
    )


# ── Rescue rétroactif d'un discard commémo ───────────────────────────────
#
# C1 cohort-pipeline : un listing rejeté avec reason=commemo_in_standard_run:{X}
# peut être rescapé après coup (les 120 discards historiques). L'endpoint :
#   1. vérifie que la reason commence bien par COMMEMO_IN_STANDARD_PREFIX ;
#   2. extrait l'eurio_id cible depuis la reason ;
#   3. vérifie son existence dans `coins` ;
#   4. upserte une row source_images avec route_decision='pending' ;
#   5. met à jour discarded_listings.rescued_source_image_id + reason.
# training_eligible reste 0 — l'attribution définitive est 1-clic assisté.


class RescueResult(BaseModel):
    rescued_to: str
    source_image_id: str
    was_already_rescued: bool


@router.post(
    "/discarded/{discard_id}/rescue",
    response_model=RescueResult,
)
def rescue_discarded(discard_id: str) -> RescueResult:
    """Sauve rétroactivement un listing rejeté commemo_in_standard_run.

    Crée une row ``source_images`` avec ``route_decision='pending'`` et
    ``target_eurio_id`` extrait du motif de rejet.  Met à jour
    ``discarded_listings.reason`` → ``rescued_to:{eurio_id}`` et pose
    ``rescued_source_image_id``. Idempotent : un double appel retourne
    ``was_already_rescued=True`` sans modifier la DB.

    Seuls les discards ``commemo_in_standard_run:…`` sont acceptés — les
    autres motifs (noise_title, year_mismatch, …) ne qualifient pas (400).
    """
    conn = _store()._connection()  # noqa: SLF001

    discard = conn.execute(
        """
        SELECT id, source, source_ref, target_eurio_id, reason, title,
               raw_payload, marketplace, run_id, rescued_source_image_id
          FROM discarded_listings
         WHERE id = ?
        """,
        (discard_id,),
    ).fetchone()
    if discard is None:
        raise HTTPException(status_code=404, detail=f"Discard {discard_id!r} not found.")

    reason: str = discard["reason"]

    # Déjà rescapé → retourne l'état existant sans modification.
    if discard["rescued_source_image_id"] is not None:
        return RescueResult(
            rescued_to=reason.replace("rescued_to:", "", 1),
            source_image_id=discard["rescued_source_image_id"],
            was_already_rescued=True,
        )

    if not reason.startswith(COMMEMO_IN_STANDARD_PREFIX):
        raise HTTPException(
            status_code=400,
            detail=(
                f"Discard reason {reason!r} is not a commemo rescue candidate. "
                f"Only reasons starting with {COMMEMO_IN_STANDARD_PREFIX!r} are supported."
            ),
        )

    eurio_id: str = reason.split(":", 1)[1]

    # Vérifie que la pièce cible existe.
    coin_row = conn.execute(
        "SELECT eurio_id FROM coins WHERE eurio_id = ?", (eurio_id,)
    ).fetchone()
    if coin_row is None:
        raise HTTPException(
            status_code=404,
            detail=f"eurio_id {eurio_id!r} extracted from discard reason not found in coins table.",
        )

    # Reconstruit les champs du listing depuis raw_payload.
    raw_payload: dict[str, Any] | None = None
    if discard["raw_payload"]:
        try:
            raw_payload = json.loads(discard["raw_payload"])
        except (TypeError, ValueError):
            raw_payload = None

    source_url: str | None = (raw_payload or {}).get("item_web_url")
    listing_price_raw = (raw_payload or {}).get("price")
    listing_price: float | None = (
        float(listing_price_raw) if isinstance(listing_price_raw, (int, float)) else None
    )
    currency_raw = (raw_payload or {}).get("currency")
    listing_currency: str = currency_raw if isinstance(currency_raw, str) else "EUR"

    sid = upsert_source_image(
        conn,
        SourceImageRow(
            source="ebay",
            source_ref=discard["source_ref"],
            source_url=source_url,
            target_eurio_id=eurio_id,
            listing_title=discard["title"],
            listing_price=listing_price,
            listing_currency=listing_currency,
            marketplace=discard["marketplace"],
            route_decision="pending",
            route_reason=f"rescued_from_discard:{discard_id}",
            run_id=discard["run_id"],
            raw_payload=raw_payload,
        ),
    )

    # Met à jour le discard : trace le rescue dans reason + pose le FK.
    conn.execute(
        """
        UPDATE discarded_listings
           SET reason = ?,
               rescued_source_image_id = ?
         WHERE id = ?
        """,
        (f"rescued_to:{eurio_id}", sid, discard_id),
    )
    conn.commit()

    return RescueResult(
        rescued_to=eurio_id,
        source_image_id=sid,
        was_already_rescued=False,
    )


# ── Run funnel — page Logs/Entonnoir du run-detail ────────────────────────


class FunnelStep(BaseModel):
    name: str               # id du step (PIPELINE_STEPS)
    status: str             # done | running | pending | failed


class RunFunnel(BaseModel):
    """Vue entonnoir d'un run : steps + funnel discovery→détection→review.

    Tout est dérivé de `source_runs` + `discovery_searches` +
    `source_images` + `discarded_listings` — aucune capture de log texte.
    """

    run_id: str
    source_id: str
    status: str
    current_step: str | None
    duration_s: float | None
    n_errors: int
    error_summary: str | None
    steps: list[FunnelStep]
    # Discovery
    n_searches: int
    n_summaries: int
    n_after_groups: int
    n_kept: int
    # Détection (crop)
    n_images: int
    n_cropped: int
    n_zero_crops: int
    n_crop_pending: int
    # Rejets pré-ingestion
    n_discarded: int
    discards: list[DiscardedReasonGroup]
    # Sortie
    n_review_enqueued: int
    n_pending_quotes: int
    n_quotes: int


def _funnel_steps(current_step: str | None, run_status: str) -> list[FunnelStep]:
    """Statut de chaque step du pipeline, dérivé de current_step + status.

    - run terminé (success/partial) → tous les steps `done` ;
    - run `running` → steps avant le courant `done`, le courant
      `running`, les suivants `pending` ;
    - run `failed` → steps avant `done`, le courant `failed`, suivants
      `pending` (non atteints).
    """
    from sources._base.run_logger import PIPELINE_STEPS

    if run_status in ("success", "partial"):
        return [FunnelStep(name=s, status="done") for s in PIPELINE_STEPS]

    idx = PIPELINE_STEPS.index(current_step) if current_step in PIPELINE_STEPS else -1
    out: list[FunnelStep] = []
    for i, step in enumerate(PIPELINE_STEPS):
        if i < idx:
            status = "done"
        elif i == idx:
            status = "failed" if run_status == "failed" else "running"
        else:
            status = "pending"
        out.append(FunnelStep(name=step, status=status))
    return out


# Consumed by: admin/.../sources/composables/useRunFunnel.ts
@router.get(
    "/{source_id}/runs/{run_id}/funnel",
    response_model=RunFunnel,
)
def get_run_funnel(source_id: str, run_id: str) -> RunFunnel:
    conn = _store()._connection()  # noqa: SLF001
    run = conn.execute(
        "SELECT * FROM source_runs WHERE id = ? AND source = ?",
        (run_id, source_id),
    ).fetchone()
    if run is None:
        raise HTTPException(status_code=404, detail=f"Run {run_id} introuvable.")

    duration_s: float | None = None
    if run["started_at"] and run["ended_at"]:
        from datetime import datetime as _dt
        try:
            t0 = _dt.fromisoformat(run["started_at"].replace(" ", "T"))
            t1 = _dt.fromisoformat(run["ended_at"].replace(" ", "T"))
            duration_s = (t1 - t0).total_seconds()
        except ValueError:
            duration_s = None

    disc = conn.execute(
        """
        SELECT COUNT(*) n, COALESCE(SUM(n_summaries),0) s0,
               COALESCE(SUM(n_after_groups),0) s1,
               COALESCE(SUM(n_kept_results),0) s3
          FROM discovery_searches WHERE source = ? AND run_id = ?
        """,
        (source_id, run_id),
    ).fetchone()

    crop_rows = conn.execute(
        "SELECT crop_status, COUNT(*) n FROM source_images "
        "WHERE source = ? AND run_id = ? GROUP BY crop_status",
        (source_id, run_id),
    ).fetchall()
    n_cropped = n_zero = n_crop_pending = 0
    for r in crop_rows:
        if r["crop_status"] == "success":
            n_cropped = r["n"]
        elif r["crop_status"] == "zero_crops":
            n_zero = r["n"]
        else:  # NULL ou erreur de crop → en attente / non abouti
            n_crop_pending += r["n"]
    n_images = n_cropped + n_zero + n_crop_pending

    by_reason_rows = conn.execute(
        "SELECT reason, COUNT(*) n FROM discarded_listings "
        "WHERE source = ? AND run_id = ? GROUP BY reason ORDER BY n DESC, reason ASC",
        (source_id, run_id),
    ).fetchall()
    discards = [
        DiscardedReasonGroup(reason=r["reason"], count=int(r["n"]))
        for r in by_reason_rows
    ]

    return RunFunnel(
        run_id=run_id,
        source_id=source_id,
        status=run["status"],
        current_step=run["current_step"],
        duration_s=duration_s,
        n_errors=run["n_errors"] or 0,
        error_summary=run["error_summary"],
        steps=_funnel_steps(run["current_step"], run["status"]),
        n_searches=int(disc["n"]),
        n_summaries=int(disc["s0"]),
        n_after_groups=int(disc["s1"]),
        n_kept=int(disc["s3"]),
        n_images=n_images,
        n_cropped=n_cropped,
        n_zero_crops=n_zero,
        n_crop_pending=n_crop_pending,
        n_discarded=sum(g.count for g in discards),
        discards=discards,
        n_review_enqueued=run["n_review_enqueued"] or 0,
        n_pending_quotes=run["n_pending_added"] or 0,
        n_quotes=run["n_quotes_added"] or 0,
    )


# ── Startup hook: reset orphan 'running' rows ─────────────────────────────


# ── Detail endpoints (read-only, replace front mocks) ─────────────────────


def _aggregator_source(source_id: str) -> dict[str, Any]:
    """Look up the source's metadata block from `build_status()`.

    Fallback: if the aggregator doesn't know the source but the
    orchestrator registry does (case for `mock` and any future source
    where the adapter lands before the aggregator metadata), synthesize
    a minimal block from `SourceSpec` so the detail endpoints stay
    usable. Raises 404 only if neither registry knows the id.
    """
    status = sources_aggregator.build_status()
    for src in status.get("sources", []):
        if src["id"] == source_id:
            return src

    # Fallback to the orchestrator registry.
    from sources._base.sources_registry import SOURCES
    spec = SOURCES.get(source_id)
    if spec is None:
        raise HTTPException(
            status_code=404, detail=f"Source '{source_id}' not declared.",
        )
    return {
        "id": spec.id,
        "label": spec.label,
        "subtitle": spec.notes or f"{spec.kind} · {spec.default_variant_kind}",
        "kind": spec.kind,
        "is_future": spec.is_future,
        "health": "healthy",
        "health_reason": None,
        "temporal": {
            "expected_cadence_days": spec.expected_cadence_days,
            "last_run_at": None,
        },
        "coverage": {
            "enriched": 0,
            "total_target": 0,
            "pct": 0.0,
            "unit": "items",
        },
    }


class SourceDetailHeader(BaseModel):
    id: str
    label: str
    subtitle: str
    health: str
    health_reason: str | None
    expected_cadence_days: int
    last_run_at: str | None
    last_run_summary: dict[str, Any] | None
    coverage_pct: float
    coverage_label: str


# Consumed by: admin/packages/web/src/features/sources/composables/useSourceDetail.ts (fetchSourceDetail)
@router.get("/{source_id}", response_model=SourceDetailHeader)
def source_detail(source_id: str) -> SourceDetailHeader:
    src = _aggregator_source(source_id)
    conn = _store()._connection()  # noqa: SLF001
    last = conn.execute(
        """
        SELECT status, n_calls, n_raws_added, n_crops_added, n_quotes_added,
               started_at, ended_at
          FROM source_runs
         WHERE source = ? AND status != 'running'
         ORDER BY started_at DESC LIMIT 1
        """,
        (source_id,),
    ).fetchone()

    last_summary: dict[str, Any] | None = None
    if last:
        duration = None
        if last["started_at"] and last["ended_at"]:
            try:
                from datetime import datetime
                t0 = datetime.fromisoformat(last["started_at"].replace(" ", "T"))
                t1 = datetime.fromisoformat(last["ended_at"].replace(" ", "T"))
                duration = (t1 - t0).total_seconds()
            except Exception:  # noqa: BLE001
                duration = None
        last_summary = {
            "n_images": last["n_raws_added"] + last["n_crops_added"],
            "n_quotes": last["n_quotes_added"],
            "n_calls": last["n_calls"],
            "duration_s": duration or 0,
            "status": last["status"],
        }

    coverage = src["coverage"]
    return SourceDetailHeader(
        id=src["id"],
        label=src["label"],
        subtitle=src["subtitle"],
        health=src["health"],
        health_reason=src.get("health_reason"),
        expected_cadence_days=src["temporal"]["expected_cadence_days"],
        last_run_at=src["temporal"].get("last_run_at"),
        last_run_summary=last_summary,
        coverage_pct=coverage.get("pct", 0.0),
        coverage_label=(
            f"{coverage.get('enriched', 0):,} / {coverage.get('total_target', 0):,} "
            f"{coverage.get('unit', '')}"
        ).replace(",", " "),
    )


class SourceRunListItem(BaseModel):
    id: str
    started_at: str
    kind: str
    duration_s: float
    n_calls: int
    n_images: int
    n_quotes: int
    n_errors: int
    status: str
    current_step: str | None
    n_raws_added: int
    n_crops_added: int
    filters: dict[str, Any]
    log_path: str | None


# Consumed by: admin/packages/web/src/features/sources/composables/useSourceDetail.ts (listSourceRuns)
@router.get("/{source_id}/runs", response_model=list[SourceRunListItem])
def list_runs(
    source_id: str,
    limit: int = Query(default=50, ge=1, le=500),
    status: str | None = Query(default=None),
) -> list[SourceRunListItem]:
    conn = _store()._connection()  # noqa: SLF001
    sql = "SELECT * FROM source_runs WHERE source = ?"
    args: list[Any] = [source_id]
    if status:
        sql += " AND status = ?"
        args.append(status)
    sql += " ORDER BY started_at DESC LIMIT ?"
    args.append(limit)
    rows = conn.execute(sql, args).fetchall()

    out: list[SourceRunListItem] = []
    for r in rows:
        snap = _row_to_snapshot(r)
        out.append(SourceRunListItem(
            id=snap.id,
            started_at=snap.started_at,
            kind=snap.kind,
            duration_s=snap.duration_s or 0.0,
            n_calls=snap.n_calls,
            n_images=snap.n_raws_added + snap.n_crops_added,
            n_quotes=snap.n_quotes_added,
            n_errors=snap.n_errors,
            status=snap.status,
            current_step=snap.current_step,
            n_raws_added=snap.n_raws_added,
            n_crops_added=snap.n_crops_added,
            filters=snap.filters,
            log_path=snap.log_path,
        ))
    return out


class SourceImageItem(BaseModel):
    id: str
    thumb_url: str
    full_url: str
    eurio_id: str | None
    variant_kind: str | None
    quality_score: float | None
    training_eligible: bool
    fetched_at: str


class PaginatedImages(BaseModel):
    items: list[SourceImageItem]
    total: int


# Consumed by: admin/packages/web/src/features/sources/composables/useSourceDetail.ts (fetchSourceImages)
@router.get("/{source_id}/images", response_model=PaginatedImages)
def list_images(
    source_id: str,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=24, ge=1, le=200, alias="pageSize"),
) -> PaginatedImages:
    conn = _store()._connection()  # noqa: SLF001
    total = conn.execute(
        """
        SELECT COUNT(*) AS c
          FROM image_assets a
          JOIN source_images s ON s.id = a.source_image_id
         WHERE s.source = ?
        """,
        (source_id,),
    ).fetchone()["c"]

    offset = (page - 1) * page_size
    rows = conn.execute(
        """
        SELECT a.id, a.eurio_id, a.variant_kind, a.quality_score,
               a.training_eligible, a.fetched_at
          FROM image_assets a
          JOIN source_images s ON s.id = a.source_image_id
         WHERE s.source = ?
         ORDER BY a.fetched_at DESC
         LIMIT ? OFFSET ?
        """,
        (source_id, page_size, offset),
    ).fetchall()

    items = [
        SourceImageItem(
            id=r["id"],
            # File-serving routes will land in 4.C — for now return a
            # data-URI-style placeholder so the front renders gracefully.
            thumb_url=f"/sources/{source_id}/assets/{r['id']}/file",
            full_url=f"/sources/{source_id}/assets/{r['id']}/file",
            eurio_id=r["eurio_id"],
            variant_kind=r["variant_kind"] if r["variant_kind"] != "unknown" else None,
            quality_score=r["quality_score"],
            training_eligible=bool(r["training_eligible"]),
            fetched_at=r["fetched_at"],
        )
        for r in rows
    ]
    return PaginatedImages(items=items, total=total)


class SourceQuoteItem(BaseModel):
    id: str
    eurio_id: str
    condition: str
    p10: float
    p50: float
    p90: float
    n: int
    period: str
    fetched_at: str


class PaginatedQuotes(BaseModel):
    items: list[SourceQuoteItem]
    total: int


# Consumed by: admin/packages/web/src/features/sources/composables/useSourceDetail.ts (fetchSourceQuotes)
@router.get("/{source_id}/quotes", response_model=PaginatedQuotes)
def list_quotes(
    source_id: str,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=25, ge=1, le=200, alias="pageSize"),
) -> PaginatedQuotes:
    conn = _store()._connection()  # noqa: SLF001
    total = conn.execute(
        "SELECT COUNT(*) AS c FROM coin_market_quotes WHERE source = ?",
        (source_id,),
    ).fetchone()["c"]

    offset = (page - 1) * page_size
    rows = conn.execute(
        """
        SELECT id, eurio_id, condition_normalized, p10, p50, p90, sample_size,
               period_start, fetched_at
          FROM coin_market_quotes
         WHERE source = ?
         ORDER BY fetched_at DESC
         LIMIT ? OFFSET ?
        """,
        (source_id, page_size, offset),
    ).fetchall()

    items = [
        SourceQuoteItem(
            id=r["id"],
            eurio_id=r["eurio_id"],
            condition=r["condition_normalized"] or "unknown",
            p10=r["p10"] or 0.0,
            p50=r["p50"] or 0.0,
            p90=r["p90"] or 0.0,
            n=r["sample_size"],
            period=r["period_start"][:7] if r["period_start"] else "",
            fetched_at=r["fetched_at"],
        )
        for r in rows
    ]
    return PaginatedQuotes(items=items, total=total)


class CoverageBreakdownEntry(BaseModel):
    key: str
    enriched: int
    total: int
    pct: float


class SourceCoverage(BaseModel):
    global_: dict[str, Any] = Field(alias="global")
    breakdown_dimension: str
    breakdown: list[CoverageBreakdownEntry]
    uncovered_eurio_ids: list[str]

    class Config:
        populate_by_name = True


# Consumed by: admin/packages/web/src/features/sources/composables/useSourceDetail.ts (fetchSourceCoverage)
@router.get("/{source_id}/coverage", response_model=SourceCoverage)
def get_coverage(source_id: str) -> SourceCoverage:
    src = _aggregator_source(source_id)
    cov = src["coverage"]
    # V1: breakdown / uncovered ids would need richer joins against the
    # coins table — left empty for now. The header global is enough to
    # power the page; the breakdown widget falls back to "no data".
    return SourceCoverage(
        **{"global": {
            "enriched": cov.get("enriched", 0),
            "total": cov.get("total_target", 0),
            "pct": cov.get("pct", 0.0),
            "unit": cov.get("unit", ""),
        }},
        breakdown_dimension="—",
        breakdown=[],
        uncovered_eurio_ids=[],
    )


# ── File serving (image_assets crops) ─────────────────────────────────────


# Consumed by: admin/packages/web/src/features/sources/composables/useRunListings.ts (assetFileUrl, URL builder for <img src>)
@router.get("/{source_id}/assets/{asset_id}/file")
def get_asset_file(source_id: str, asset_id: str):
    conn = _store()._connection()  # noqa: SLF001
    row = conn.execute(
        """
        SELECT a.storage_path
          FROM image_assets a
          JOIN source_images s ON s.id = a.source_image_id
         WHERE a.id = ? AND s.source = ?
        """,
        (asset_id, source_id),
    ).fetchone()
    if row is None or not row["storage_path"]:
        raise HTTPException(status_code=404, detail="Asset not found.")
    from storage.local_cache import local_path as _local_path
    try:
        p = _local_path("enrichment-crops", row["storage_path"])
    except FileNotFoundError as exc:
        raise HTTPException(status_code=410,
                            detail=f"Asset missing in MinIO: {exc}") from exc
    return FileResponse(p, media_type="image/png")


# Consumed by: admin/packages/web/src/features/sources/composables/useRunListings.ts (rawFileUrl, URL builder for <img src>)
@router.get("/{source_id}/raws/{source_image_id}/file")
def get_raw_file(source_id: str, source_image_id: str):
    """Sert le fichier original (raw) d'un source_image.

    Différent de `/assets/<asset_id>/file` qui sert un crop. Utile pour
    afficher la photo originale d'un listing dans la lot review (pour
    contextualiser les crops). Cf. lot-review-kickoff.md §L.A.
    """
    conn = _store()._connection()  # noqa: SLF001
    row = conn.execute(
        "SELECT storage_path FROM source_images WHERE id = ? AND source = ?",
        (source_image_id, source_id),
    ).fetchone()
    if row is None or not row["storage_path"]:
        raise HTTPException(status_code=404, detail="Raw image not found.")
    from storage.local_cache import local_path as _local_path
    try:
        p = _local_path("enrichment-raws", row["storage_path"])
    except FileNotFoundError as exc:
        raise HTTPException(status_code=410,
                            detail=f"Raw missing in MinIO: {exc}") from exc
    return FileResponse(p, media_type="image/jpeg")


# ── eBay-specific: quota status + freshness queue (D-19/D-20/D-27) ───────


EBAY_DAILY_QUOTA = 5000
ESTIMATE_BOOTSTRAP = 7         # calls/eurio_id avant 3 runs réussis
ESTIMATE_SAFETY_FACTOR = 1.3   # marge appliquée au pre-flight


def _today_period() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def ebay_calls_today(store: Store) -> int:
    """Total calls eBay sur la période 'daily' du jour courant."""
    conn = store._connection()  # noqa: SLF001
    row = conn.execute(
        """
        SELECT COALESCE(SUM(calls), 0) AS n
          FROM api_call_log
         WHERE source = 'ebay' AND window = 'daily' AND period = ?
        """,
        (_today_period(),),
    ).fetchone()
    return int(row["n"] or 0)


def _count_group_coins(
    conn: sqlite3.Connection, denomination: float, country: str, year: int,
) -> int:
    """Nombre de commémos d'un groupe (dénomination, pays, année)."""
    row = conn.execute(
        "SELECT count(*) AS n FROM coins "
        "WHERE face_value = ? AND country = ? AND year = ? "
        "AND is_commemorative = 1",
        (denomination, country, year),
    ).fetchone()
    return int(row["n"] or 0)


def _filters_targets_count(conn: sqlite3.Connection, filters_json: str | None) -> int:
    """Nombre de pièces visées par une run, depuis son `filters_json`.

    Gère les deux modes de découverte : `discovery_groups` (somme des
    commémos de chaque groupe) et `target_eurio_id(s)`.
    """
    if not filters_json:
        return 1
    try:
        f = json.loads(filters_json)
    except json.JSONDecodeError:
        return 1
    groups = f.get("discovery_groups")
    if groups:
        total = sum(
            _count_group_coins(conn, g["denomination"], g["country"], g["year"])
            for g in groups
        )
        return max(total, 1)
    if f.get("target_eurio_ids"):
        return max(len(f["target_eurio_ids"]), 1)
    return 1


def _count_query_coins(store: Store, query: SourceQuery) -> int:
    """Nombre de commémos visées par une SourceQuery (pre-flight quota)."""
    conn = store._connection()  # noqa: SLF001
    if query.discovery_groups:
        return sum(
            _count_group_coins(conn, g.denomination, g.country, g.year)
            for g in query.discovery_groups
        )
    if query.target_eurio_ids:
        return len(query.target_eurio_ids)
    if query.target_eurio_id:
        return 1
    return 0


def estimate_calls_per_eurio_id(store: Store) -> float:
    """Moyenne mobile sur les 5 derniers runs eBay terminés.

    Fallback à `ESTIMATE_BOOTSTRAP` (= 7) si moins de 3 runs ont
    abouti (success ou partial). On compte `n_calls / max(targets, 1)`
    par run — l'unité reste « par pièce » même pour les runs groupés,
    où `targets` = somme des commémos des groupes interrogés.
    """
    conn = store._connection()  # noqa: SLF001
    rows = conn.execute(
        """
        SELECT n_calls, filters_json
          FROM source_runs
         WHERE source = 'ebay'
           AND status IN ('success', 'partial')
           AND n_calls > 0
         ORDER BY started_at DESC
         LIMIT 5
        """
    ).fetchall()
    if len(rows) < 3:
        return float(ESTIMATE_BOOTSTRAP)

    ratios = [
        r["n_calls"] / _filters_targets_count(conn, r["filters_json"])
        for r in rows
    ]
    return sum(ratios) / len(ratios)


def check_ebay_quota(store: Store, *, n_eurio_ids: int) -> dict[str, Any]:
    """Pre-flight quota check (D-27).

    Returns a dict with `ok`, `estimate`, `remaining`, `max_safe_batch`.
    """
    avg = estimate_calls_per_eurio_id(store)
    estimate = int(round(avg * n_eurio_ids))
    remaining = max(EBAY_DAILY_QUOTA - ebay_calls_today(store), 0)
    safe_threshold = estimate * ESTIMATE_SAFETY_FACTOR
    ok = remaining >= safe_threshold
    max_safe = int(remaining / (avg * ESTIMATE_SAFETY_FACTOR)) if avg > 0 else 0
    return {
        "ok": ok,
        "estimate": estimate,
        "remaining": remaining,
        "limit": EBAY_DAILY_QUOTA,
        "avg_calls_per_eurio_id": round(avg, 2),
        "max_safe_batch": max_safe,
    }


class EbayQuotaStatus(BaseModel):
    calls_today: int
    limit: int
    remaining: int
    exhausted: bool
    period: str
    avg_calls_per_eurio_id: float


# Consumed by: admin/packages/web/src/features/sources/composables/useSourceDetail.ts (fetchEbayQuotaStatus)
@router.get("/ebay/quota-status", response_model=EbayQuotaStatus)
def ebay_quota_status() -> EbayQuotaStatus:
    store = _store()
    calls = ebay_calls_today(store)
    return EbayQuotaStatus(
        calls_today=calls,
        limit=EBAY_DAILY_QUOTA,
        remaining=max(EBAY_DAILY_QUOTA - calls, 0),
        exhausted=calls >= EBAY_DAILY_QUOTA,
        period=_today_period(),
        avg_calls_per_eurio_id=round(estimate_calls_per_eurio_id(store), 2),
    )


class FreshnessItem(BaseModel):
    eurio_id: str
    country: str
    year: int
    last_enriched_at: str | None
    n_images: int
    n_crops: int
    status: str   # 'never' | 'stale' | 'fresh'


class FreshnessBuckets(BaseModel):
    never: int
    stale_90d: int
    fresh: int
    total: int


class EbayFreshnessResponse(BaseModel):
    items: list[FreshnessItem]
    buckets: FreshnessBuckets


def _classify_freshness(last_enriched_at: str | None, stale_days: int = 90) -> str:
    if last_enriched_at is None:
        return "never"
    from datetime import datetime, timedelta, timezone
    try:
        dt = datetime.fromisoformat(last_enriched_at.replace(" ", "T"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
    except ValueError:
        return "never"
    if datetime.now(timezone.utc) - dt > timedelta(days=stale_days):
        return "stale"
    return "fresh"


# Consumed by: ml/sources/ebay/status_cli.py (go-task ml:src:ebay:status).
# Vue per-eurio_id ; la découverte groupée passe par /ebay/freshness-groups.
@router.get("/ebay/freshness", response_model=EbayFreshnessResponse)
def ebay_freshness(
    limit: int = Query(default=50, ge=1, le=500),
) -> EbayFreshnessResponse:
    """Freshness queue : eurio_ids commémo 2€ non-EU triés par `last_enriched_at ASC NULLS FIRST`.

    Lit la vue SQL `v_ebay_freshness` (D-20). Depuis chunk 6 cette vue est
    la projection per-eurio_id de `v_ebay_freshness_groups` : chaque pièce
    porte la freshness de SON groupe de découverte (cf. schema.sql).
    Buckets calculés sur l'ensemble (pas le slice `limit`).
    """
    conn = _store()._connection()  # noqa: SLF001

    all_rows = conn.execute(
        """
        SELECT eurio_id, country, year, last_enriched_at, n_images, n_crops
          FROM v_ebay_freshness
         ORDER BY last_enriched_at ASC NULLS FIRST, eurio_id
        """
    ).fetchall()

    buckets = {"never": 0, "stale": 0, "fresh": 0}
    classified: list[tuple[Any, str]] = []
    for r in all_rows:
        status = _classify_freshness(r["last_enriched_at"])
        buckets[status] += 1
        classified.append((r, status))

    items = [
        FreshnessItem(
            eurio_id=r["eurio_id"],
            country=r["country"],
            year=r["year"],
            last_enriched_at=r["last_enriched_at"],
            n_images=r["n_images"] or 0,
            n_crops=r["n_crops"] or 0,
            status=status,
        )
        for r, status in classified[:limit]
    ]
    return EbayFreshnessResponse(
        items=items,
        buckets=FreshnessBuckets(
            never=buckets["never"],
            stale_90d=buckets["stale"],
            fresh=buckets["fresh"],
            total=len(all_rows),
        ),
    )


# ── eBay freshness queue par GROUPE (chunk 2 — découverte groupée) ────────


class FreshnessGroupItem(BaseModel):
    denomination: float
    country: str
    year: int
    n_coins: int
    last_enriched_at: str | None
    n_images: int
    n_crops: int
    status: str   # 'never' | 'stale' | 'fresh'


class EbayFreshnessGroupsResponse(BaseModel):
    items: list[FreshnessGroupItem]
    buckets: FreshnessBuckets


# Consumed by: admin/packages/web/src/features/sources/composables/useSourceDetail.ts (fetchEbayFreshnessGroups)
@router.get("/ebay/freshness-groups", response_model=EbayFreshnessGroupsResponse)
def ebay_freshness_groups(
    limit: int = Query(default=200, ge=1, le=2000),
) -> EbayFreshnessGroupsResponse:
    """Freshness queue à la maille GROUPE (dénomination, pays, année).

    Lit `v_ebay_freshness_groups`, triée stalest-first. C'est l'unité de
    rafraîchissement du modèle de découverte groupée : une recherche eBay
    couvre tout un groupe.
    """
    conn = _store()._connection()  # noqa: SLF001
    all_rows = conn.execute(
        """
        SELECT denomination, country, year, n_coins,
               last_enriched_at, n_images, n_crops
          FROM v_ebay_freshness_groups
         ORDER BY last_enriched_at ASC NULLS FIRST, country, year
        """
    ).fetchall()

    buckets = {"never": 0, "stale": 0, "fresh": 0}
    classified: list[tuple[Any, str]] = []
    for r in all_rows:
        status = _classify_freshness(r["last_enriched_at"])
        buckets[status] += 1
        classified.append((r, status))

    items = [
        FreshnessGroupItem(
            denomination=r["denomination"],
            country=r["country"],
            year=r["year"],
            n_coins=r["n_coins"] or 0,
            last_enriched_at=r["last_enriched_at"],
            n_images=r["n_images"] or 0,
            n_crops=r["n_crops"] or 0,
            status=status,
        )
        for r, status in classified[:limit]
    ]
    return EbayFreshnessGroupsResponse(
        items=items,
        buckets=FreshnessBuckets(
            never=buckets["never"],
            stale_90d=buckets["stale"],
            fresh=buckets["fresh"],
            total=len(all_rows),
        ),
    )


# ── eBay run preview (chunk 2 — « ce groupe = N pièces = N appels ») ──────


class RunPreviewBody(BaseModel):
    discovery_groups: list[GroupSpec]


class RunPreviewGroup(BaseModel):
    denomination: float
    country: str
    year: int
    n_coins: int


class RunPreviewResponse(BaseModel):
    groups: list[RunPreviewGroup]
    n_groups: int
    total_coins: int
    estimate_calls: int
    avg_calls_per_eurio_id: float
    remaining: int
    limit: int
    ok: bool
    max_safe_coins: int


# Consumed by: admin/packages/web/src/features/sources/composables/useSourceDetail.ts (fetchEbayRunPreview)
@router.post("/ebay/run-preview", response_model=RunPreviewResponse)
def ebay_run_preview(body: RunPreviewBody) -> RunPreviewResponse:
    """Estime, avant lancement, ce que coûtera un run groupé.

    Pour chaque groupe (dénomination, pays, année) : combien de commémos
    il couvre. Total des pièces + estimation d'appels API + check quota.
    """
    store = _store()
    conn = store._connection()  # noqa: SLF001
    groups: list[RunPreviewGroup] = []
    total_coins = 0
    for g in body.discovery_groups:
        n = _count_group_coins(conn, g.denomination, g.country, g.year)
        total_coins += n
        groups.append(RunPreviewGroup(
            denomination=g.denomination, country=g.country, year=g.year, n_coins=n,
        ))
    quota = check_ebay_quota(store, n_eurio_ids=total_coins)
    return RunPreviewResponse(
        groups=groups,
        n_groups=len(groups),
        total_coins=total_coins,
        estimate_calls=quota["estimate"],
        avg_calls_per_eurio_id=quota["avg_calls_per_eurio_id"],
        remaining=quota["remaining"],
        limit=quota["limit"],
        ok=quota["ok"],
        max_safe_coins=quota["max_safe_batch"],
    )


# ── eBay multi-marketplace (B5/B6) ────────────────────────────────────────


class MarketplaceCallEntry(BaseModel):
    marketplace: str       # ex: 'EBAY_DE'
    query_lang: str        # langue native de la query, ex: 'de'

    model_config = {
        "json_schema_extra": {
            "example": {"marketplace": "EBAY_DE", "query_lang": "de"}
        }
    }


class MarketplaceMapResponse(BaseModel):
    """Marketplaces eBay interrogés en discovery.

    Routage uniforme (cf. `ml/sources/ebay/marketplaces.py`) : la même
    paire `{EBAY_DE, EBAY_ES}` pour toutes les origines, dans l'ordre.
    """

    marketplaces: list[MarketplaceCallEntry]


# Consumed by: admin/.../sources/composables/useMarketplaceMap.ts (B5 client).
@router.get("/ebay/marketplace-map", response_model=MarketplaceMapResponse)
def ebay_marketplace_map() -> MarketplaceMapResponse:
    """Renvoie les marketplaces discovery de `ml/sources/ebay/marketplaces.py`."""
    from sources.ebay.marketplaces import discovery_marketplaces
    return MarketplaceMapResponse(
        marketplaces=[
            MarketplaceCallEntry(marketplace=c.marketplace, query_lang=c.query_lang)
            for c in discovery_marketplaces()
        ]
    )


# ── Prix de référence marché (chunk C4 — cross-check review) ──────────────


class MarketQuoteEntry(BaseModel):
    condition: str             # tier d'état : 'UNC' | 'TTB' | 'TB'
    p10: float | None
    p50: float | None
    p90: float | None
    sample_size: int
    period_start: str


class MarketQuotesResponse(BaseModel):
    """Derniers prix de référence par pièce (un par tier d'état).

    Clé = eurio_id ; valeur = liste des quotes les plus récentes
    (`coin_market_quotes`, source ebay). Une pièce sans agrégation n'a
    pas d'entrée — le front dégrade proprement.
    """

    quotes: dict[str, list[MarketQuoteEntry]]


# Consumed by: admin/.../review/composables/useReviewApi.ts (fetchMarketQuotes)
@router.get("/ebay/market-quotes", response_model=MarketQuotesResponse)
def ebay_market_quotes(
    eurio_ids: str = Query(..., description="CSV d'eurio_id"),
) -> MarketQuotesResponse:
    """Renvoie le dernier `coin_market_quotes` par (pièce, tier d'état)."""
    ids = [e.strip() for e in eurio_ids.split(",") if e.strip()]
    if not ids:
        return MarketQuotesResponse(quotes={})

    conn = _store()._connection()  # noqa: SLF001
    placeholders = ",".join("?" * len(ids))
    rows = conn.execute(
        f"""
        SELECT eurio_id, condition_raw, p10, p50, p90, sample_size, period_start
          FROM coin_market_quotes c
         WHERE source = 'ebay' AND eurio_id IN ({placeholders})
           AND period_start = (
               SELECT MAX(period_start) FROM coin_market_quotes c2
                WHERE c2.source = c.source AND c2.eurio_id = c.eurio_id
                  AND COALESCE(c2.condition_raw, '') = COALESCE(c.condition_raw, '')
           )
        """,  # noqa: S608 — placeholders = '?' répétés, pas d'injection
        ids,
    ).fetchall()

    quotes: dict[str, list[MarketQuoteEntry]] = {}
    for r in rows:
        quotes.setdefault(r["eurio_id"], []).append(MarketQuoteEntry(
            condition=r["condition_raw"] or "unknown",
            p10=r["p10"], p50=r["p50"], p90=r["p90"],
            sample_size=r["sample_size"], period_start=r["period_start"],
        ))
    return MarketQuotesResponse(quotes=quotes)


class FilterRule(BaseModel):
    name: str               # 'noise_title' | 'below_face' | …
    kind: str               # 'reject' | 'flag'
    description: str
    pattern: str | None = None     # regex source si pertinent
    threshold: float | None = None  # seuil numérique si pertinent
    policy: str | None = None       # ex: 'accept-on-missing' pour year


class EbayFilterConfig(BaseModel):
    """Snapshot lisible des règles de filtrage actives (cf. front-ux.md §3.B).

    Reflète les constantes de `ml/sources/ebay/filters.py`. V1 lecture
    seule — toute modif passe par PR.
    """

    rules: list[FilterRule]
    source_path: str        # chemin du fichier code pour le "Source" link


# Consumed by: admin/.../sources/composables/useFilterConfig.ts (B6 client).
@router.get("/ebay/filter-config", response_model=EbayFilterConfig)
def ebay_filter_config() -> EbayFilterConfig:
    from sources.ebay import filters as ebay_filters
    return EbayFilterConfig(
        rules=[
            FilterRule(
                name="noise_title",
                kind="reject",
                description="Reject si le titre matche un mot-clé hors-scope (proof, argent, plaqué, …).",
                pattern=ebay_filters.NOISE_PATTERNS.pattern,
            ),
            FilterRule(
                name="below_face",
                kind="reject",
                description=(
                    f"Reject si prix < face × {ebay_filters.FACE_VALUE_FACTOR_LOW} "
                    "(= 1.60 € pour les 2 €)."
                ),
                threshold=ebay_filters.FACE_VALUE_FACTOR_LOW,
            ),
            FilterRule(
                name="above_extreme",
                kind="reject",
                description=(
                    f"Reject si prix > face × {ebay_filters.FACE_VALUE_FACTOR_HIGH} "
                    "(= 1000 € pour les 2 €)."
                ),
                threshold=ebay_filters.FACE_VALUE_FACTOR_HIGH,
            ),
            FilterRule(
                name="non_eur",
                kind="reject",
                description="Reject si currency != EUR.",
            ),
            FilterRule(
                name="year_mismatch",
                kind="reject",
                description=(
                    "Reject si une année trouvée dans le titre ≠ année attendue "
                    "(commémos uniquement)."
                ),
                pattern=ebay_filters.YEAR_IN_TITLE_RE.pattern,
                policy="accept-on-missing",
            ),
            FilterRule(
                name="theme_mismatch",
                kind="reject",
                description=(
                    "Découverte groupée : chaque listing est attribué à une "
                    "commémo de son groupe (denom, pays, année) via le matcher "
                    "de thème multilingue. Reject si le titre ne matche AUCUNE "
                    "commémo du groupe (sinon : attribué, ou routé en review si "
                    "ambigu / multi-pièces)."
                ),
            ),
            FilterRule(
                name="text_contradict_*",
                kind="reject",
                description=(
                    "Filtre dur du step text_signal : reject si le titre "
                    "contredit franchement la pièce attendue sur un axe "
                    "(pays / année / dénomination). Suffixe = l'axe en cause."
                ),
            ),
            FilterRule(
                name="is_lot_suspected",
                kind="flag",
                description=(
                    "Flag (pas reject) : titre matche lot|coffret|série|rouleau|set. "
                    "Le listing est gardé mais routé vers review_queue.kind='lot'."
                ),
                pattern=ebay_filters.LOT_PATTERNS.pattern,
            ),
        ],
        source_path="ml/sources/ebay/filters.py",
    )


# ── Startup hook ──────────────────────────────────────────────────────────


def reset_orphan_runs(store: Store) -> int:
    """Flip rows left in `status='running'` from a previous process to
    `'failed'`. Returns the number of rows touched.

    Called by the FastAPI startup hook in `server.py`. Without this,
    if uvicorn is killed mid-run, the next request sees the orphan as
    "still running" and refuses to start a new one (anti-double-run).
    """
    conn = store._connection()  # noqa: SLF001
    cur = conn.execute(
        """
        UPDATE source_runs
           SET status = 'failed',
               ended_at = COALESCE(ended_at, datetime('now')),
               error_summary = COALESCE(error_summary, 'process restart — orphan run')
         WHERE status = 'running'
        """
    )
    return cur.rowcount or 0
