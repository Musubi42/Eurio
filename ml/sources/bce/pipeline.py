"""Pipeline d'ingestion BCE — version fs-as-SOT.

Architecture (acté 2026-05-25 session 3, suite à la discussion FS vs DB) :

- Source of truth = **filesystem** sous ``ml/canonical_images/`` et
  ``ml/state/bce_runs/``. Si eurio.db est perdue, le pipeline rejoue
  depuis BCE sans dépendance DB.
- Le pipeline **n'écrit plus** dans ``coin_canonical_images`` ni
  ``coin_observations`` — ces tables sont alimentées exclusivement par
  Numista pour ses propres canoniques. Pour BCE, l'UI lit le fs.
- Pour limiter le bruit DB, on n'utilise pas non plus les callbacks
  ``discovery_searches`` / ``discarded_listings`` (qui spammaient à
  300+ et 1k+ rows/run respectivement).
- Restent en DB : ``source_runs`` (1 row/run, journal d'exécution
  partagé avec eBay) + ``source_images`` (1 row/image téléchargée,
  utilisé par le step ``download_local`` pour la reprise/idempotence)
  + ``discovery_log`` (dedup spine du pipeline générique).

Sortie filesystem par image canonique :
- ``ml/canonical_images/{eurio_id}/{role}_bce.webp``       — image 400 px
- ``ml/canonical_images/{eurio_id}/{role}_bce_thumb.webp`` — thumb 120 px
- ``ml/canonical_images/{eurio_id}/{role}_bce.json``       — sidecar metadata

Sortie filesystem par run :
- ``ml/state/bce_runs/{run_id}.json`` — manifest avec matched/unmatched
  + stats (durée, n_pages, n_promoted, …).

Séquence : discover → persist → download local → canonical_promote (fs).
"""

from __future__ import annotations

import hashlib
import json
import logging
import sqlite3
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

import httpx

import dataclasses

from sources._base.adapter import DiscoveredItem, SourceQuery
from sources._base.dedup import upsert_discovery_log
from sources._base.query_sig import compute_query_signature
from sources._base.registry_map import to_registry_source
from sources._base.run_logger import RunHandle, start_run
from sources._base.steps.persist import run_persist
from state.source_status import bce_axes, upsert_source_status
from sources._base.storage import raw_cache_path
from sources.bce.adapter import BceAdapter
from sources.bce.cropper import crop_coins_from_bytes
from sources.bce.sidecar import RunManifest, write_sidecar
from state.sources_runs import record_run

logger = logging.getLogger(__name__)

# Aligné avec ``coin_image_storage.source_file_tag('bce_comm')`` qui retourne 'bce'.
_BCE_SOURCE_LONG = "bce_comm"
# Registry id écrit dans les tables data-aware (FK source_registry).
_BCE_REGISTRY_SOURCE = to_registry_source("bce")  # → 'bce_official'


def run_bce_pipeline(
    adapter: BceAdapter,
    query: SourceQuery,
    *,
    store,
    dry_run: bool = False,
    force: bool = False,
) -> str:
    """Exécute le pipeline BCE et retourne le ``run_id``."""
    kind = "dry" if dry_run else "run"
    conn = store._connection()  # noqa: SLF001
    manifest = RunManifest(
        run_id="",  # rempli après start_run
        started_at=datetime.now(timezone.utc).isoformat(),
        kind=kind,
        query=asdict(query),
    )

    with start_run(
        conn,
        source=adapter.source_id,
        kind=kind,
        filters=asdict(query),
        force=force,
    ) as run:
        manifest.run_id = run.run_id
        logger.info("[bce] run_id=%s kind=%s query=%s", run.run_id, kind, query)

        if dry_run:
            run.set_step("discover")
            discover_result = _bce_discover(adapter, query, conn=conn, run=run)
            logger.info("[bce] dry-run : on s'arrête après discover")
            manifest.status = "success"
            manifest.ended_at = datetime.now(timezone.utc).isoformat()
            manifest.write()
            run.end("success")
            return run.run_id

        steps = run_bce_steps(adapter, query, conn=conn, run=run, manifest=manifest)

        manifest.n_errors = steps.n_errors
        status = "partial" if steps.n_errors > 0 else "success"
        manifest.status = status
        manifest.error_summary = (
            f"{steps.n_errors} item(s) failed — see logs" if steps.n_errors else None
        )
        manifest.ended_at = datetime.now(timezone.utc).isoformat()
        manifest_path = manifest.write()
        logger.info("[bce] manifest written → %s", manifest_path)

        run.end(status, error_summary=manifest.error_summary)
        logger.info(
            "[bce] run %s done — discovered=%d persisted=%d downloaded=%d promoted=%d errors=%d",
            run.run_id, steps.n_discovered, steps.n_persisted,
            steps.n_downloaded, steps.n_promoted, steps.n_errors,
        )
        # Marker partagé `/sources/status` (sources_runs.json).
        record_run("bce", kind, calls=steps.n_discovered, added_coins=steps.n_promoted)
        return run.run_id


@dataclasses.dataclass
class BceStepsResult:
    n_discovered: int
    n_persisted: int
    n_downloaded: int
    n_promoted: int
    n_errors: int


def run_bce_steps(
    adapter: BceAdapter,
    query: SourceQuery,
    *,
    conn: sqlite3.Connection,
    run: RunHandle,
    manifest: RunManifest,
) -> BceStepsResult:
    """Steps non-dry du pipeline BCE (discover→persist→download→promote) sous
    un ``run`` déjà ouvert. Factorisé pour être réutilisé par le refresh par
    coin (1 run unique couvrant images + i18n + facts). N'ouvre PAS de run,
    n'écrit PAS le manifest (laissé à l'appelant)."""
    # 1. Discover (BCE-spécifique, no DB spam : pas de record_search/discarded,
    # seul discovery_log est upsert comme dedup spine).
    run.set_step("discover")
    discover_result = _bce_discover(adapter, query, conn=conn, run=run)

    # 2. Persist
    run.set_step("persist")
    persist_result = run_persist(
        discover_result.items, conn=conn, run=run, source_id=adapter.source_id,
    )

    # 3. Download local
    run.set_step("download")
    n_downloaded = _bce_download_local(
        conn=conn, run=run, adapter=adapter,
        source_image_ids=persist_result.source_image_ids,
    )
    manifest.n_downloaded = n_downloaded

    # 4. Canonical promote (fs only)
    conn.execute(
        "UPDATE source_runs SET current_step = ? WHERE id = ?",
        ("canonical_promote", run.run_id),
    )
    n_promoted = _bce_canonical_promote_fs(
        conn=conn, run=run,
        source_image_ids=persist_result.source_image_ids,
        manifest=manifest,
    )
    manifest.n_promoted = n_promoted

    n_errors = conn.execute(
        "SELECT n_errors FROM source_runs WHERE id = ?", (run.run_id,)
    ).fetchone()["n_errors"]
    return BceStepsResult(
        n_discovered=len(discover_result.items),
        n_persisted=persist_result.n_added + persist_result.n_updated,
        n_downloaded=n_downloaded,
        n_promoted=n_promoted,
        n_errors=n_errors,
    )


# ── steps BCE-spécifiques ───────────────────────────────────────────────


@dataclasses.dataclass
class _BceDiscoverResult:
    items: list[DiscoveredItem]
    query_signature: str


def _bce_discover(
    adapter: BceAdapter,
    query: SourceQuery,
    *,
    conn: sqlite3.Connection,
    run: RunHandle,
) -> _BceDiscoverResult:
    """Variante minimale de ``run_discover`` qui n'écrit pas dans
    ``discovery_searches`` ni ``discarded_listings``.

    On garde ``discovery_log`` (dedup) pour rester compatible avec les
    steps downstream (persist) qui itèrent les rows correspondants au run.
    Itère les sub-queries (target_eurio_ids → 1 sub-query par eurio_id)
    comme le step générique.
    """
    signature = compute_query_signature(query)
    items: list[DiscoveredItem] = []

    subqueries: list[SourceQuery]
    if query.target_eurio_ids:
        base = dataclasses.replace(query, target_eurio_ids=None)
        subqueries = [
            dataclasses.replace(base, target_eurio_id=eid)
            for eid in query.target_eurio_ids
        ]
    else:
        subqueries = [query]

    for subq in subqueries:
        # record_search/record_discarded=None ⇒ pas de write DB côté
        # discovery_searches / discarded_listings.
        for item in adapter.discover(subq):
            items.append(item)
            upsert_discovery_log(
                conn,
                source=adapter.source_id,
                source_ref=item.source_ref,
                query_signature=signature,
                run_id=run.run_id,
            )
        run.bump(n_calls=1)

    logger.info(
        "[bce] discover sig=%s subqueries=%d → %d items",
        signature, len(subqueries), len(items),
    )
    return _BceDiscoverResult(items=items, query_signature=signature)


def _bce_download_local(
    *,
    conn: sqlite3.Connection,
    run: RunHandle,
    adapter: BceAdapter,
    source_image_ids: dict[str, str],
) -> int:
    """Variante de ``run_download`` sans write-through MinIO.

    Écrit le JPG dans le cache local (``raw_cache_path``) puis met à
    jour ``source_images``. Idempotent : skip les rows déjà téléchargées.
    """
    from sources._base.adapter import DiscoveredItem
    from sources._base.dedup import set_discovery_pipeline_state

    n_downloaded = 0

    for source_ref, sid in source_image_ids.items():
        row = conn.execute(
            "SELECT id, source_url, listing_title, raw_payload_json, "
            "       storage_path, storage_status, download_status "
            "FROM source_images WHERE id = ?",
            (sid,),
        ).fetchone()
        if row is None:
            run.bump(n_errors=1)
            continue

        if (row["storage_path"]
                and row["storage_status"] == "present"
                and row["download_status"] == "success"):
            continue

        payload = json.loads(row["raw_payload_json"]) if row["raw_payload_json"] else None
        item = DiscoveredItem(
            source_ref=source_ref,
            source_url=row["source_url"],
            listing_title=row["listing_title"],
            raw_payload=payload,
        )
        cache_dest = raw_cache_path(adapter.source_id, run.run_id, sid)
        cache_dest.parent.mkdir(parents=True, exist_ok=True)
        try:
            res = adapter.download_raw(item, cache_dest)
        except Exception as exc:  # noqa: BLE001
            http_status = (
                exc.response.status_code
                if isinstance(exc, httpx.HTTPStatusError) else None
            )
            conn.execute(
                """
                UPDATE source_images
                   SET download_endpoint    = ?,
                       download_status      = 'failed',
                       download_http_status = ?,
                       download_error       = ?
                 WHERE id = ?
                """,
                (item.source_url, http_status, str(exc)[:500], sid),
            )
            run.bump(n_errors=1)
            logger.warning("[bce] download FAILED %s: %s", source_ref, exc)
            continue

        conn.execute(
            """
            UPDATE source_images
               SET storage_path         = ?,
                   storage_status       = 'present',
                   bytes                = ?,
                   sha256               = ?,
                   width                = COALESCE(?, width),
                   height               = COALESCE(?, height),
                   download_endpoint    = ?,
                   download_status      = 'success',
                   download_http_status = ?,
                   download_error       = NULL
             WHERE id = ?
            """,
            (
                str(cache_dest), res.bytes, res.sha256, res.width, res.height,
                res.endpoint_url or item.source_url,
                res.http_status,
                sid,
            ),
        )
        set_discovery_pipeline_state(
            conn, source=adapter.source_id, source_ref=source_ref, state="downloaded",
        )
        n_downloaded += 1
        run.bump(n_raws_added=1)

    return n_downloaded


def _bce_canonical_promote_fs(
    *,
    conn: sqlite3.Connection,
    run: RunHandle,
    source_image_ids: dict[str, str],
    manifest: RunManifest,
) -> int:
    """Pour chaque image téléchargée : cropper → write_variants → sidecar +
    upsert provenance DB.

    Le filesystem reste la source of truth (les binaires WebP vivent sous
    ``ml/canonical_images/``). Mais on écrit aussi un index DB minimal :

    - ``coin_canonical_images(eurio_id, source='bce_official', role, url,
      local_path)`` — pour que les endpoints "has_bce" / source-counts
      puissent agréger sans scanner le FS.
    - ``coin_source_refs(target_kind='coin', target_id=eurio_id,
      source='bce_official', source_native_id='{country}-{year}-{theme}',
      source_url=bce_page_url)`` — provenance first-class (doctrine §2.2).
    """
    from referential.canonical_image_local import (
        canonical_path,
        relative_path,
        write_variants,
    )

    n_promoted = 0
    promoted_ids: set[str] = set()

    for source_ref, sid in source_image_ids.items():
        row = conn.execute(
            "SELECT id, target_eurio_id, storage_path, download_status, "
            "       raw_payload_json, source_url, listing_title "
            "FROM source_images WHERE id = ?",
            (sid,),
        ).fetchone()
        if row is None:
            continue
        if row["download_status"] != "success":
            continue
        eurio_id = row["target_eurio_id"]
        if not eurio_id:
            logger.warning("[bce] promote: source_image %s has no target_eurio_id", sid)
            continue
        storage_path = Path(row["storage_path"])
        if not storage_path.is_file():
            logger.warning("[bce] promote: %s missing on disk", storage_path)
            run.bump(n_errors=1)
            continue

        try:
            raw_bytes = storage_path.read_bytes()
            crops = crop_coins_from_bytes(raw_bytes)
        except Exception as exc:  # noqa: BLE001
            logger.warning("[bce] crop FAILED %s: %s", source_ref, exc)
            run.bump(n_errors=1)
            continue

        payload = json.loads(row["raw_payload_json"]) if row["raw_payload_json"] else {}
        sha = hashlib.sha256(raw_bytes).hexdigest()
        feature = payload.get("feature") or row["listing_title"] or ""
        image_url = payload.get("image_url") or row["source_url"]

        country = payload.get("country") or ""
        year = payload.get("year")
        theme_slug = payload.get("theme_slug") or ""
        bce_page_url = payload.get("bce_page_url")
        source_native_id = f"{country}-{year}-{theme_slug}" if theme_slug else f"{country}-{year}"
        wrote_source_ref = False

        for crop in crops:
            try:
                write_variants(eurio_id, crop.role, _BCE_SOURCE_LONG, crop.image_bytes)
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "[bce] write_variants FAILED eurio=%s role=%s: %s",
                    eurio_id, crop.role, exc,
                )
                run.bump(n_errors=1)
                continue

            # Provenance DB — coin_canonical_images (idempotent UPSERT).
            try:
                conn.execute(
                    """
                    INSERT INTO coin_canonical_images
                      (eurio_id, source, role, url, local_path)
                    VALUES (?, ?, ?, ?, ?)
                    ON CONFLICT (eurio_id, source, role) DO UPDATE SET
                      url        = excluded.url,
                      local_path = excluded.local_path
                    """,
                    (
                        eurio_id, _BCE_REGISTRY_SOURCE, crop.role,
                        image_url, relative_path(eurio_id, crop.role, _BCE_SOURCE_LONG),
                    ),
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "[bce] DB upsert coin_canonical_images FAILED eurio=%s: %s",
                    eurio_id, exc,
                )
                run.bump(n_errors=1)

            # 1 row coin_source_refs par (coin, source) — UPSERT idempotent.
            if not wrote_source_ref:
                try:
                    conn.execute(
                        """
                        INSERT INTO coin_source_refs
                          (target_kind, target_id, source, source_native_id, source_url)
                        VALUES ('coin', ?, ?, ?, ?)
                        ON CONFLICT (target_kind, target_id, source) DO UPDATE SET
                          source_native_id = excluded.source_native_id,
                          source_url       = excluded.source_url,
                          fetched_at       = datetime('now')
                        """,
                        (eurio_id, _BCE_REGISTRY_SOURCE, source_native_id, bce_page_url),
                    )
                    wrote_source_ref = True
                except Exception as exc:  # noqa: BLE001
                    logger.warning(
                        "[bce] DB upsert coin_source_refs FAILED eurio=%s: %s",
                        eurio_id, exc,
                    )
                    run.bump(n_errors=1)

                # E.4 (chantier D) — coin_topics : capture le feature BCE
                # verbeux ("100th anniversary of Finland's independence",
                # "Bundesländer - 'Bremen'"). 1 row par (coin, source=bce_official,
                # lang). Le scrape adapter actuel ne fetch que la page EN, donc
                # on stocke lang='en'. Future amélioration : scrape .fr.html
                # aussi pour avoir le FR canon BCE.
                if feature:
                    try:
                        conn.execute(
                            """
                            INSERT INTO coin_topics
                              (eurio_id, source, lang, topic, method, confidence)
                            VALUES (?, ?, 'en', ?, 'scrape', 'canon')
                            ON CONFLICT (eurio_id, source, lang) DO UPDATE SET
                              topic      = excluded.topic,
                              method     = excluded.method,
                              confidence = excluded.confidence,
                              fetched_at = datetime('now')
                            """,
                            (eurio_id, _BCE_REGISTRY_SOURCE, feature),
                        )
                    except Exception as exc:  # noqa: BLE001
                        logger.warning(
                            "[bce] DB upsert coin_topics FAILED eurio=%s: %s",
                            eurio_id, exc,
                        )
                        run.bump(n_errors=1)

            # Sidecar JSON à côté du WebP detail (1 par image).
            sidecar_meta = {
                "year": payload.get("year"),
                "country": payload.get("country"),
                "feature": feature,
                "description": payload.get("description"),
                "issuing_volume": payload.get("issuing_volume"),
                "issuing_date": payload.get("issuing_date"),
                "image_url": image_url,
                "bce_page_url": payload.get("bce_page_url"),
                "raw_sha256": sha,
                "crop_width": crop.width,
                "crop_height": crop.height,
                "run_id": run.run_id,
            }
            webp_path = canonical_path(eurio_id, crop.role, _BCE_SOURCE_LONG)
            write_sidecar(
                webp_path,
                eurio_id=eurio_id,
                role=crop.role,
                source=_BCE_SOURCE_LONG,
                metadata=sidecar_meta,
            )

            manifest.add_matched(
                eurio_id=eurio_id,
                role=crop.role,
                image_url=image_url or "",
                feature=feature,
                local_path=relative_path(eurio_id, crop.role, _BCE_SOURCE_LONG),
            )
            n_promoted += 1
            promoted_ids.add(eurio_id)
            run.bump(n_crops_added=1)

    # Instrumentation disponibilité : marque ok (axes ré-dérivés depuis la DB,
    # ne clobbe pas les axes d'autres sources) pour chaque coin promu.
    for eid in promoted_ids:
        try:
            upsert_source_status(
                conn, eurio_id=eid, source=_BCE_REGISTRY_SOURCE,
                state="ok", axes=bce_axes(conn, eid), run_id=run.run_id,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("[bce] source_status upsert FAILED eurio=%s: %s", eid, exc)

    conn.commit()
    return n_promoted
