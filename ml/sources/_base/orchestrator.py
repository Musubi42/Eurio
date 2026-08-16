"""Generic 9-step ingestion pipeline (D-13 ; +price_aggregate, chunk C3).

Drives any `SourceAdapter` through Discover → Persist → Text-signal →
Download → Detect → Resolve → Auto-validate → Enqueue, writing to
`source_runs` after each step. Step implementations live under
`ml/sources/_base/steps/`. The canonical step list is
`PIPELINE_STEPS` in `run_logger.py`.

Idempotence is the contract: a re-run must produce zero new rows /
zero new files / zero new crops. Each step owns its upserts; the
orchestrator only sequences them.
"""

from __future__ import annotations

import logging
import os
from dataclasses import asdict, dataclass
from typing import TYPE_CHECKING

from sources._base.adapter import SourceAdapter, SourceQuery
from sources._base.run_logger import PIPELINE_STEPS, RunHandle, start_run

__all__ = [
    "PIPELINE_STEPS",
    "run_pipeline",
    "resume_failed_downloads",
    "ResumeResult",
    "process_downloaded",
    "CropPendingResult",
]
from sources._base.steps.auto_validate import run_auto_validate_dino
from sources._base.steps.detect_crop import run_detect_crop
from sources._base.steps.discover import run_discover
from sources._base.steps.download import run_download
from sources._base.steps.enqueue import run_enqueue
from sources._base.steps.persist import run_persist
from sources._base.steps.price_aggregate import run_price_aggregate
from sources._base.steps.resolve import run_resolve
from sources._base.steps.text_signal import run_text_signal_extract

if TYPE_CHECKING:
    from store import Store

logger = logging.getLogger(__name__)


def _maybe_push_run(store: "Store", run_id: str, *, push: bool | None = None) -> None:
    """Direction A : pousse le run au canonique VPS si la sync est activée.

    Transport générique (chunk C4c) — remplace le ``--push`` opt-in de
    ``sources.cli`` comme SEUL point de bascule. Tout appelant de
    ``run_pipeline``/``process_downloaded``/``resume_failed_downloads``
    (CLI, ``serving.sources_routes``, scripts futurs) traverse ce même
    chemin : plus d'entrypoint qui écrirait silencieusement en Modèle A
    alors qu'``EURIO_API_URL`` est configuré. Sans ``EURIO_API_URL``
    (``client.http.sync_enabled()`` faux), no-op — Modèle A dev inchangé.

    ``push`` : ``None``/``True`` (défaut) = pousse automatiquement si la
    sync est configurée ; ``False`` = échappatoire explicite (``--no-push``
    CLI) qui force le Modèle A local même quand ``EURIO_API_URL`` est set.

    Best-effort : une erreur réseau/HTTP est loguée, pas levée (le run local
    reste valide même si le push échoue ; à rejouer via ``--push`` CLI ou un
    retry manuel — pas de compensation automatique dans ce chunk).
    """
    if push is False:
        return
    from client.http import sync_enabled  # noqa: PLC0415 — évite import cycle au chargement

    if not sync_enabled():
        return
    from client.runbatch import push_run  # noqa: PLC0415

    try:
        res = push_run(store._connection(), run_id)  # noqa: SLF001
    except Exception:  # noqa: BLE001
        logger.exception(
            "[direction-a] push run=%s vers le canonique a échoué (run local "
            "conservé, à repousser manuellement)", run_id,
        )
        return
    if res.get("already_applied"):
        logger.info("[direction-a] push run=%s → déjà appliqué (no-op)", run_id)
    else:
        counts = res.get("counts", {})
        total = sum(counts.values()) if isinstance(counts, dict) else 0
        logger.info("[direction-a] push run=%s → %d ligne(s) appliquée(s)", run_id, total)


def run_pipeline(
    adapter: SourceAdapter,
    query: SourceQuery,
    *,
    store: "Store",
    dry_run: bool = False,
    download_only: bool = False,
    force: bool = False,
    push: bool | None = None,
) -> str:
    """Execute the 9-step pipeline for one source.

    `dry_run=True` runs Discover only and writes nothing past the
    `source_runs` row (kind='dry') and the `discovery_log` upserts.

    `download_only=True` runs Discover → Persist → Text-signal → Download
    then stops, leaving the raws in MinIO and the `source_images` rows at
    `pipeline_state='downloaded'`. The crop (CPU-intensive Hough/YOLO) is
    deferred — call [process_downloaded] on the returned run_id to crop on
    demand. Lets a big scrape persist raws without burning the CPU on crops.
    `dry_run` wins if both are set (it stops earlier).

    `push` (chunk C4c) : transmis à [_maybe_push_run] — ``None``/``True``
    (défaut) pousse automatiquement le run au canonique VPS si
    ``EURIO_API_URL`` est configuré ; ``False`` force le Modèle A local
    (aucun push) même quand la sync est configurée.

    Returns the run_id either way so the caller (CLI / front) can
    fetch counters and the log.
    """
    kind = "dry" if dry_run else "run"

    conn = store._connection()  # noqa: SLF001
    with start_run(
        conn,
        source=adapter.source_id,
        kind=kind,
        filters=asdict(query),
        force=force,
    ) as run:
        logger.info(
            "[%s] run_id=%s kind=%s query=%s",
            adapter.source_id, run.run_id, kind, query,
        )

        # ── 1. Discover ──────────────────────────────────────────────
        run.set_step("discover")
        discover_result = run_discover(adapter, query, conn=conn, run=run)

        if dry_run:
            logger.info("[%s] dry-run: stopping after discover", adapter.source_id)
            run.end("success")
            return run.run_id

        # ── 2. Persist raw ───────────────────────────────────────────
        run.set_step("persist")
        persist_result = run_persist(
            discover_result.items,
            conn=conn,
            run=run,
            source_id=adapter.source_id,
        )

        # ── 2.5. Text-signal extraction (chunk 5 auto-validation) ────
        # Pure regex/dict, no I/O on the listing API. Persiste 1 row par
        # source_image dans listing_text_signals. Pas un step de
        # décision en V1 — le filtre dur arrivera au chunk 6.
        run.set_step("text_signal")
        run_text_signal_extract(
            conn=conn,
            run=run,
            source_image_ids=persist_result.source_image_ids,
            store=store,
        )

        # ── 3. Download ──────────────────────────────────────────────
        run.set_step("download")
        run_download(
            conn=conn,
            run=run,
            adapter=adapter,
            source_image_ids=persist_result.source_image_ids,
        )

        if download_only:
            # Stop here — raws persisted, crop deferred (see [process_downloaded]).
            # Mirror the final n_errors check so a flaky download surfaces as
            # 'partial' rather than a falsely-green 'success'.
            n_errors = conn.execute(
                "SELECT n_errors FROM source_runs WHERE id = ?", (run.run_id,)
            ).fetchone()["n_errors"]
            if n_errors > 0:
                run.end("partial", error_summary=f"{n_errors} item(s) failed — see logs")
            else:
                run.end("success")
            logger.info(
                "[%s] download-only: stopping after download (crop deferred)",
                adapter.source_id,
            )
            conn.commit()
            _maybe_push_run(store, run.run_id, push=push)
            return run.run_id

        # ── 4. Detect & crop ─────────────────────────────────────────
        run.set_step("detect")
        run_detect_crop(
            conn=conn,
            run=run,
            source_id=adapter.source_id,
            source_image_ids=persist_result.source_image_ids,
        )

        # ── 5. Resolve ───────────────────────────────────────────────
        run.set_step("resolve")
        run_resolve(
            conn=conn,
            run=run,
            source_id=adapter.source_id,
            source_image_ids=persist_result.source_image_ids,
        )

        # ── 5.5. Auto-validate via DINOv2 ────────────────────────────
        # Suggestion layer (V1, no decision). Skipped if anchor bank
        # missing — does not fail the pipeline. See
        # docs/sources-refacto/auto-validation/.
        run.set_step("auto_validate")
        run_auto_validate_dino(
            conn=conn,
            run=run,
            source_id=adapter.source_id,
            source_image_ids=persist_result.source_image_ids,
        )

        # ── 6. Enqueue review ────────────────────────────────────────
        run.set_step("enqueue")
        run_enqueue(
            conn=conn,
            run=run,
            source_id=adapter.source_id,
            source_image_ids=persist_result.source_image_ids,
        )

        # ── 7. Agrégation prix (chunk C3) ────────────────────────────
        # Agrège les annonces single du run en prix de référence par
        # tier d'état → coin_market_quotes. Cf. steps/price_aggregate.
        run.set_step("price_aggregate")
        run_price_aggregate(
            conn=conn,
            run_id=run.run_id,
            source=adapter.source_id,
        )

        n_errors = conn.execute(
            "SELECT n_errors FROM source_runs WHERE id = ?", (run.run_id,)
        ).fetchone()["n_errors"]
        if n_errors > 0:
            run.end("partial", error_summary=f"{n_errors} item(s) failed — see logs")
        else:
            run.end("success")
        conn.commit()
        _maybe_push_run(store, run.run_id, push=push)
        return run.run_id


@dataclass
class CropPendingResult:
    """Bilan d'un `process_downloaded` (crop à la demande)."""

    run_id: str
    n_pending: int     # source_images téléchargées (download_status='success')
    n_crops_added: int  # crops ajoutés cette passe (delta n_crops_added du run)


def process_downloaded(
    *,
    store: "Store",
    run_id: str,
    push: bool | None = None,
) -> CropPendingResult:
    """Crop à la demande les raws d'un run lancé en `download_only`.

    Reprend le **même** run et enchaîne detect → resolve → auto_validate →
    enqueue → price_aggregate sur les images dont le download a réussi. Pensé
    pour le mode scrape découplé : `run_pipeline(download_only=True)` persiste
    les raws sans cropper (CPU économisé), ce process déclenche le crop quand on
    le décide (front / CLI). Idempotent : `run_detect_crop` saute les images
    déjà croppées, donc relancer ne double rien.

    N'a pas besoin de l'adapter (les steps crop→… ne prennent qu'un `source_id`),
    donc tourne sans credentials de la source (pas de token eBay requis).

    `push` (chunk C4c) : cf. [_maybe_push_run] — ``None``/``True`` pousse
    automatiquement si ``EURIO_API_URL`` est configuré, ``False`` force le
    Modèle A local.
    """
    conn = store._connection()  # noqa: SLF001
    run_row = conn.execute(
        "SELECT id, source, status, n_crops_added FROM source_runs WHERE id = ?",
        (run_id,),
    ).fetchone()
    if run_row is None:
        raise ValueError(f"Unknown run_id {run_id!r}")
    if run_row["status"] == "running":
        raise ValueError(f"Run {run_id!r} is still running — wait for it to finish.")
    source = run_row["source"]
    crops_before = run_row["n_crops_added"]

    downloaded = conn.execute(
        "SELECT id, source_ref FROM source_images "
        "WHERE run_id = ? AND download_status = 'success'",
        (run_id,),
    ).fetchall()
    n_pending = len(downloaded)
    if not downloaded:
        return CropPendingResult(run_id, 0, 0)

    source_image_ids = {r["source_ref"]: r["id"] for r in downloaded}
    run = RunHandle(run_id=run_id, source=source, _conn=conn)
    conn.execute(
        # Réclame le pid du process courant (CLI foreground / thread serving) au
        # reattach : sinon le pid périmé du run initial survit et `reset_orphan_runs`
        # (startup backend / --reload) tue ce run vivant comme « orphan run » (B5).
        "UPDATE source_runs SET status='running', ended_at=NULL, error_summary=NULL, "
        "pid=? WHERE id = ?",
        (os.getpid(), run_id),
    )
    conn.commit()
    logger.info(
        "[%s] crop-pending run=%s — cropping %d downloaded image(s)",
        source, run_id, n_pending,
    )

    try:
        run.set_step("detect")
        run_detect_crop(
            conn=conn, run=run, source_id=source, source_image_ids=source_image_ids,
        )
        run.set_step("resolve")
        run_resolve(
            conn=conn, run=run, source_id=source, source_image_ids=source_image_ids,
        )
        run.set_step("auto_validate")
        run_auto_validate_dino(
            conn=conn, run=run, source_id=source, source_image_ids=source_image_ids,
        )
        run.set_step("enqueue")
        run_enqueue(
            conn=conn, run=run, source_id=source, source_image_ids=source_image_ids,
        )
        run.set_step("price_aggregate")
        run_price_aggregate(conn=conn, run_id=run_id, source=source)

        row = conn.execute(
            "SELECT n_errors, n_crops_added FROM source_runs WHERE id = ?", (run_id,)
        ).fetchone()
        n_errors = row["n_errors"]
        run.end(
            "success" if n_errors == 0 else "partial",
            error_summary=None if n_errors == 0
            else f"{n_errors} item(s) failed — see logs",
        )
        conn.commit()
        logger.info(
            "[%s] crop-pending run=%s done — crops_added=%d",
            source, run_id, row["n_crops_added"] - crops_before,
        )
        _maybe_push_run(store, run_id, push=push)
        return CropPendingResult(
            run_id, n_pending, row["n_crops_added"] - crops_before,
        )
    except Exception as exc:  # noqa: BLE001
        run.end("failed", error_summary=f"process_downloaded crashed: {exc}")
        conn.commit()
        raise


@dataclass
class ResumeResult:
    """Bilan d'un `resume_failed_downloads`."""

    run_id: str
    n_failed_before: int   # source_images en download_status='failed' avant
    n_recovered: int       # téléchargements réussis cette fois
    n_still_failed: int    # toujours en échec après le resume


def resume_failed_downloads(
    adapter: SourceAdapter,
    *,
    store: "Store",
    run_id: str,
    push: bool | None = None,
) -> ResumeResult:
    """Rejoue download → … → price_aggregate pour les listings échoués d'un run.

    Pensé pour les connexions instables : le download initial échoue
    « simplement » (1 tentative, état persisté en DB via
    ``source_images.download_status='failed'``). Ce resume reprend les
    seuls listings échoués, les re-télécharge, puis enchaîne detect →
    resolve → auto_validate → enqueue sur ceux récupérés et ré-agrège les
    prix du run. Idempotent : les images déjà en MinIO sont sautées.

    Le resume s'attache au **même** ``source_runs`` (pas de nouveau run) :
    les compteurs cumulent, le statut final est recalculé (success si plus
    aucun échec, partial sinon).

    `push` (chunk C4c) : cf. [_maybe_push_run].
    """
    conn = store._connection()  # noqa: SLF001
    run_row = conn.execute(
        "SELECT id, source, status FROM source_runs WHERE id = ?", (run_id,)
    ).fetchone()
    if run_row is None:
        raise ValueError(f"Unknown run_id {run_id!r}")
    if run_row["status"] == "running":
        raise ValueError(f"Run {run_id!r} is still running — wait for it to finish.")
    source = run_row["source"]

    failed = conn.execute(
        "SELECT id, source_ref FROM source_images "
        "WHERE run_id = ? AND download_status = 'failed'",
        (run_id,),
    ).fetchall()
    n_failed_before = len(failed)
    if not failed:
        return ResumeResult(run_id, 0, 0, 0)

    source_image_ids = {r["source_ref"]: r["id"] for r in failed}
    run = RunHandle(run_id=run_id, source=source, _conn=conn)
    conn.execute(
        # Réclame le pid du process courant (CLI foreground / thread serving) au
        # reattach : sinon le pid périmé du run initial survit et `reset_orphan_runs`
        # (startup backend / --reload) tue ce run vivant comme « orphan run » (B5).
        "UPDATE source_runs SET status='running', ended_at=NULL, error_summary=NULL, "
        "pid=? WHERE id = ?",
        (os.getpid(), run_id),
    )
    conn.commit()
    logger.info(
        "[%s] resume run=%s — retrying %d failed download(s)",
        source, run_id, n_failed_before,
    )

    try:
        run.set_step("download")
        run_download(
            conn=conn, run=run, adapter=adapter, source_image_ids=source_image_ids,
        )

        # Quels listings ont effectivement été récupérés ce coup-ci ?
        recovered = {
            sref: sid for sref, sid in source_image_ids.items()
            if (conn.execute(
                "SELECT download_status FROM source_images WHERE id = ?", (sid,)
            ).fetchone() or {})["download_status"] == "success"
        }

        if recovered:
            run.set_step("detect")
            run_detect_crop(
                conn=conn, run=run, source_id=source, source_image_ids=recovered,
            )
            run.set_step("resolve")
            run_resolve(
                conn=conn, run=run, source_id=source, source_image_ids=recovered,
            )
            run.set_step("auto_validate")
            run_auto_validate_dino(
                conn=conn, run=run, source_id=source, source_image_ids=recovered,
            )
            run.set_step("enqueue")
            run_enqueue(
                conn=conn, run=run, source_id=source, source_image_ids=recovered,
            )

        run.set_step("price_aggregate")
        run_price_aggregate(conn=conn, run_id=run_id, source=source)

        n_still_failed = conn.execute(
            "SELECT count(*) AS n FROM source_images "
            "WHERE run_id = ? AND download_status = 'failed'",
            (run_id,),
        ).fetchone()["n"]
        run.end(
            "success" if n_still_failed == 0 else "partial",
            error_summary=None if n_still_failed == 0
            else f"{n_still_failed} download(s) toujours en échec — réessayer",
        )
        conn.commit()
        logger.info(
            "[%s] resume run=%s done — recovered %d / still failed %d",
            source, run_id, len(recovered), n_still_failed,
        )
        _maybe_push_run(store, run_id, push=push)
        return ResumeResult(run_id, n_failed_before, len(recovered), n_still_failed)
    except Exception as exc:  # noqa: BLE001
        run.end("failed", error_summary=f"resume_failed_downloads crashed: {exc}")
        conn.commit()
        raise
