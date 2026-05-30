"""Pipeline d'ingestion JO (EUR-Lex) — fs-as-SOT, calqué sur BCE.

Séquence : discover → persist → download local → canonical promote (fs).

Doctrine (cf. discussion sources 2026-05-30, memory ``project_eurlex_source``) :
le JO ne ré-écrit **pas** mintage ni description (redondants BCE, écart de
traduction). Il pose uniquement, par pièce commémorative matchée :

- image canonique du côté national : ``ml/canonical_images/{eurio_id}/obverse_jo.webp``
  + index ``coin_canonical_images(source='eurlex_jo')`` ;
- provenance ``coin_source_refs(source='eurlex_jo', source_native_id=CELEX,
  source_url=notice JO)`` ;
- date d'émission ``coin_observations(source='eurlex_jo',
  observation_type='issuing_date')`` ;
- disponibilité ``coin_source_status(source='eurlex_jo')``.

Source of truth = filesystem ; eurio.db = index. Rejouable depuis EUR-Lex.
"""

from __future__ import annotations

import dataclasses
import json
import logging
import sqlite3
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

import httpx

from sources._base.adapter import DiscoveredItem, SourceQuery
from sources._base.dedup import set_discovery_pipeline_state, upsert_discovery_log
from sources._base.query_sig import compute_query_signature
from sources._base.registry_map import to_registry_source
from sources._base.run_logger import RunHandle, start_run
from sources._base.steps.persist import run_persist
from sources._base.storage import raw_cache_path
from sources.jo.adapter import JoAdapter
from state.source_status import jo_axes, upsert_source_status
from state.sources_runs import record_run

logger = logging.getLogger(__name__)

# Source longue passée à write_variants (→ tag fichier 'jo' via source_file_tag).
_JO_SOURCE_LONG = "eurlex_jo"
_JO_REGISTRY_SOURCE = to_registry_source("jo")  # → 'eurlex_jo'


def run_jo_pipeline(
    adapter: JoAdapter,
    query: SourceQuery,
    *,
    store,
    dry_run: bool = False,
    force: bool = False,
) -> str:
    kind = "dry" if dry_run else "run"
    conn = store._connection()  # noqa: SLF001

    with start_run(
        conn, source=adapter.source_id, kind=kind,
        filters=asdict(query), force=force,
    ) as run:
        logger.info("[jo] run_id=%s kind=%s query=%s", run.run_id, kind, query)

        run.set_step("discover")
        discover = _jo_discover(adapter, query, conn=conn, run=run)
        logger.info("[jo] discovered %d commemorative notices", len(discover.items))

        if dry_run:
            run.end("success")
            return run.run_id

        run.set_step("persist")
        persist = run_persist(
            discover.items, conn=conn, run=run, source_id=adapter.source_id,
        )

        run.set_step("download")
        n_downloaded = _jo_download_local(
            conn=conn, run=run, adapter=adapter,
            source_image_ids=persist.source_image_ids,
        )

        conn.execute(
            "UPDATE source_runs SET current_step = ? WHERE id = ?",
            ("canonical_promote", run.run_id),
        )
        n_promoted = _jo_promote_fs(
            conn=conn, run=run, source_image_ids=persist.source_image_ids,
        )

        n_errors = conn.execute(
            "SELECT n_errors FROM source_runs WHERE id = ?", (run.run_id,)
        ).fetchone()["n_errors"]
        status = "partial" if n_errors > 0 else "success"
        run.end(status)
        logger.info(
            "[jo] run %s done — discovered=%d downloaded=%d promoted=%d errors=%d",
            run.run_id, len(discover.items), n_downloaded, n_promoted, n_errors,
        )
        record_run("jo", kind, calls=len(discover.items), added_coins=n_promoted)
        return run.run_id


@dataclass
class _JoDiscoverResult:
    items: list[DiscoveredItem]
    query_signature: str


def _jo_discover(
    adapter: JoAdapter, query: SourceQuery, *,
    conn: sqlite3.Connection, run: RunHandle,
) -> _JoDiscoverResult:
    signature = compute_query_signature(query)
    items: list[DiscoveredItem] = []
    for item in adapter.discover(query):
        items.append(item)
        upsert_discovery_log(
            conn, source=adapter.source_id, source_ref=item.source_ref,
            query_signature=signature, run_id=run.run_id,
        )
    run.bump(n_calls=1)
    return _JoDiscoverResult(items=items, query_signature=signature)


def _jo_download_local(
    *, conn: sqlite3.Connection, run: RunHandle,
    adapter: JoAdapter, source_image_ids: dict[str, str],
) -> int:
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
        if (row["storage_path"] and row["storage_status"] == "present"
                and row["download_status"] == "success"):
            continue

        payload = json.loads(row["raw_payload_json"]) if row["raw_payload_json"] else None
        item = DiscoveredItem(
            source_ref=source_ref, source_url=row["source_url"],
            listing_title=row["listing_title"], raw_payload=payload,
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
                "UPDATE source_images SET download_endpoint=?, download_status='failed', "
                "download_http_status=?, download_error=? WHERE id=?",
                (item.source_url, http_status, str(exc)[:500], sid),
            )
            run.bump(n_errors=1)
            logger.warning("[jo] download FAILED %s: %s", source_ref, exc)
            continue

        conn.execute(
            """
            UPDATE source_images
               SET storage_path=?, storage_status='present', bytes=?, sha256=?,
                   width=COALESCE(?, width), height=COALESCE(?, height),
                   download_endpoint=?, download_status='success',
                   download_http_status=?, download_error=NULL
             WHERE id=?
            """,
            (str(cache_dest), res.bytes, res.sha256, res.width, res.height,
             res.endpoint_url or item.source_url, res.http_status, sid),
        )
        set_discovery_pipeline_state(
            conn, source=adapter.source_id, source_ref=source_ref, state="downloaded",
        )
        n_downloaded += 1
        run.bump(n_raws_added=1)
    return n_downloaded


def _jo_promote_fs(
    *, conn: sqlite3.Connection, run: RunHandle, source_image_ids: dict[str, str],
) -> int:
    from referential.canonical_image_local import relative_path, write_variants

    n_promoted = 0
    promoted_ids: set[str] = set()

    for source_ref, sid in source_image_ids.items():
        row = conn.execute(
            "SELECT id, target_eurio_id, storage_path, download_status, "
            "       raw_payload_json, source_url FROM source_images WHERE id = ?",
            (sid,),
        ).fetchone()
        if row is None or row["download_status"] != "success":
            continue
        eurio_id = row["target_eurio_id"]
        if not eurio_id:
            continue
        storage_path = Path(row["storage_path"])
        if not storage_path.is_file():
            run.bump(n_errors=1)
            continue

        payload = json.loads(row["raw_payload_json"]) if row["raw_payload_json"] else {}
        try:
            write_variants(eurio_id, "obverse", _JO_SOURCE_LONG, storage_path.read_bytes())
        except Exception as exc:  # noqa: BLE001
            logger.warning("[jo] write_variants FAILED eurio=%s: %s", eurio_id, exc)
            run.bump(n_errors=1)
            continue

        celex = payload.get("celex")
        notice_url = payload.get("notice_url") or row["source_url"]
        date_of_issue = payload.get("date_of_issue")

        # coin_canonical_images (index FS).
        conn.execute(
            """
            INSERT INTO coin_canonical_images (eurio_id, source, role, url, local_path)
            VALUES (?, ?, 'obverse', ?, ?)
            ON CONFLICT (eurio_id, source, role) DO UPDATE SET
              url = excluded.url, local_path = excluded.local_path
            """,
            (eurio_id, _JO_REGISTRY_SOURCE, notice_url,
             relative_path(eurio_id, "obverse", _JO_SOURCE_LONG)),
        )
        # coin_source_refs (provenance : CELEX + URL notice).
        conn.execute(
            """
            INSERT INTO coin_source_refs
              (target_kind, target_id, source, source_native_id, source_url)
            VALUES ('coin', ?, ?, ?, ?)
            ON CONFLICT (target_kind, target_id, source) DO UPDATE SET
              source_native_id = excluded.source_native_id,
              source_url = excluded.source_url, fetched_at = datetime('now')
            """,
            (eurio_id, _JO_REGISTRY_SOURCE, celex or "", notice_url),
        )
        # coin_observations : date d'émission (la seule donnée factuelle qu'on
        # retient du JO — pas mintage ni description).
        if date_of_issue:
            conn.execute(
                """
                INSERT INTO coin_observations
                  (eurio_id, source, observation_type, payload_json)
                VALUES (?, ?, 'issuing_date', ?)
                ON CONFLICT (eurio_id, source, observation_type) DO UPDATE SET
                  payload_json = excluded.payload_json, recorded_at = datetime('now')
                """,
                (eurio_id, _JO_REGISTRY_SOURCE,
                 json.dumps({"date_of_issue": date_of_issue, "celex": celex})),
            )
        n_promoted += 1
        promoted_ids.add(eurio_id)
        run.bump(n_crops_added=1)

    for eid in promoted_ids:
        try:
            upsert_source_status(
                conn, eurio_id=eid, source=_JO_REGISTRY_SOURCE,
                state="ok", axes=jo_axes(conn, eid), run_id=run.run_id,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("[jo] source_status upsert FAILED eurio=%s: %s", eid, exc)

    conn.commit()
    return n_promoted
