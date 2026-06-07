"""Step 5.5 — Auto-validate via DINOv2.

Encodes each crop produced by step 4 (`detect_crop`) and computes its
top-K cosine similarity against a pre-built obverse anchor bank
(``ml/state/foundation_anchors_<kind>.npz``). Persists one row per
``(asset_id, encoder_version, anchors_kind)`` into
``image_asset_dino_predictions``.

This is **not** a decision step in V1: the asset's
``resolution_status`` stays untouched, the review_queue entry stays
``open``. The top-K is exposed as suggestions in the admin review
drawer (chunk 3) so Raphaël sees what Dino proposes alongside each
crop. Auto-accept will plug in here as a later chunk once we observe
real distributions in `/review` (cf. vision §P5).

Idempotence: skip an asset if a row already exists for the same
``(encoder_version, anchors_kind)``. Pass ``force=True`` to recompute.

Scope V1: only crops whose target_eurio_id (on the parent
source_image) points at a 2€ commemorative coin get validated against
the ``2eur_commemo`` bank. Other crops get skipped silently — the bank
isn't relevant to them. Other scopes (``all_2eur``, ``all_commemo``)
will be added when needed.
"""

from __future__ import annotations

import logging
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from foundation import (
    DEFAULT_ENCODER_VERSION,
    AnchorBank,
    build_transform,
    encode_image,
    load_anchors,
    load_encoder,
    spread,
    top_k_match,
    top_k_match_country,
)
from foundation.review_lanes import compute_lane
from sources._base.run_logger import RunHandle
from store import DinoPredictionRow

logger = logging.getLogger(__name__)

_TOP_K_STORE = 5  # how many candidates to persist per asset

# Module-level singletons — torch.hub model load is ~2s, transform is
# stateless. Reuse across calls within the same Python process.
_encoder_cache: dict[str, Any] = {}
_bank_cache: dict[str, AnchorBank] = {}


@dataclass
class AutoValidateResult:
    n_predicted: int
    n_skipped_existing: int
    n_skipped_no_anchor: int
    n_skipped_out_of_scope: int
    n_errors: int


def _get_encoder_singleton():
    """Lazy-load the DINOv2 encoder + transform; cached per-process."""
    if "encoder" not in _encoder_cache:
        encoder, device = load_encoder()
        _encoder_cache["encoder"] = encoder
        _encoder_cache["device"] = device
        _encoder_cache["transform"] = build_transform()
        logger.info("auto_validate: DINOv2 ready on %s", device)
    return (
        _encoder_cache["encoder"],
        _encoder_cache["device"],
        _encoder_cache["transform"],
    )


def _get_bank(anchors_kind: str) -> AnchorBank | None:
    if anchors_kind in _bank_cache:
        return _bank_cache[anchors_kind]
    bank = load_anchors(anchors_kind)
    if bank is None:
        return None
    _bank_cache[anchors_kind] = bank
    logger.info(
        "auto_validate: anchor bank %s loaded (%d anchors, dim=%d, encoder=%s)",
        anchors_kind, bank.count, bank.dim, bank.encoder_version,
    )
    return bank


def _select_assets_for_run(
    conn: sqlite3.Connection,
    source_image_ids: dict[str, str],
) -> list[sqlite3.Row]:
    """Return assets that should be Dino-validated for this orchestrator run.

    Filters:
      - has a storage_path on disk
      - the parent source_image has a target_eurio_id pointing at a 2€ commemo
        (matches the V1 scope ``2eur_commemo``)
    """
    if not source_image_ids:
        return []
    placeholders = ",".join("?" for _ in source_image_ids)
    rows = conn.execute(
        f"""
        SELECT a.id AS asset_id, a.storage_path,
               s.target_eurio_id,
               c.face_value, c.is_commemorative
          FROM image_assets a
          JOIN source_images s ON s.id = a.source_image_id
     LEFT JOIN coins c ON c.eurio_id = s.target_eurio_id
         WHERE a.source_image_id IN ({placeholders})
           AND a.storage_path IS NOT NULL
        """,
        tuple(source_image_ids.values()),
    ).fetchall()
    return list(rows)


def _select_assets_for_backfill(
    conn: sqlite3.Connection,
    *,
    limit: int | None = None,
    only_2eur_commemo: bool = True,
) -> list[sqlite3.Row]:
    """Return all `image_assets` candidates for a standalone backfill run."""
    sql = """
        SELECT a.id AS asset_id, a.storage_path,
               s.target_eurio_id,
               c.face_value, c.is_commemorative
          FROM image_assets a
          JOIN source_images s ON s.id = a.source_image_id
     LEFT JOIN coins c ON c.eurio_id = s.target_eurio_id
         WHERE a.storage_path IS NOT NULL
    """
    if only_2eur_commemo:
        sql += " AND c.face_value = 2.0 AND c.is_commemorative = 1"
    sql += " ORDER BY a.fetched_at ASC"
    if limit:
        sql += f" LIMIT {int(limit)}"
    return list(conn.execute(sql).fetchall())


def _predict_one(
    *,
    asset_id: str,
    crop_path: Path,
    bank: AnchorBank,
    encoder,
    device,
    transform,
    anchors_kind: str,
    target_country: str | None = None,
) -> DinoPredictionRow | None:
    if not crop_path.is_file():
        logger.warning(
            "auto_validate: missing crop file for asset=%s path=%s",
            asset_id, crop_path,
        )
        return None
    t0 = time.perf_counter()
    vec = encode_image(crop_path, encoder=encoder, device=device, transform=transform)
    matches = top_k_match(vec, bank, top_k=_TOP_K_STORE)

    # Country-restricted re-rank — same embedding, masked bank. Cheap.
    country_matches: list = []
    country_anchors_count = 0
    if target_country:
        country_matches = top_k_match_country(
            vec, bank, target_country=target_country, top_k=_TOP_K_STORE,
        )
        country_anchors_count = sum(
            1 for eid in bank.eurio_ids if eid[:2].lower() == target_country.lower()
        )

    duration_ms = int((time.perf_counter() - t0) * 1000)
    if not matches:
        return None
    top1 = matches[0]
    top2 = matches[1] if len(matches) > 1 else None

    c_top1 = country_matches[0] if country_matches else None
    c_top2 = country_matches[1] if len(country_matches) > 1 else None

    return DinoPredictionRow(
        asset_id=asset_id,
        encoder_version=bank.encoder_version,
        anchors_kind=anchors_kind,
        anchors_count=bank.count,
        top_k=[m.to_dict() for m in matches],
        top1_eurio_id=top1.eurio_id,
        top1_sim=float(top1.sim),
        top2_eurio_id=top2.eurio_id if top2 else None,
        top2_sim=float(top2.sim) if top2 else None,
        spread=spread(matches),
        target_country=target_country,
        country_anchors_count=country_anchors_count if target_country else None,
        top_k_country=[m.to_dict() for m in country_matches] if country_matches else None,
        top1_country_eurio_id=c_top1.eurio_id if c_top1 else None,
        top1_country_sim=float(c_top1.sim) if c_top1 else None,
        top2_country_eurio_id=c_top2.eurio_id if c_top2 else None,
        top2_country_sim=float(c_top2.sim) if c_top2 else None,
        country_spread=spread(country_matches) if country_matches else None,
        duration_ms=duration_ms,
    )


def _existing_keys(
    conn: sqlite3.Connection,
    asset_ids: list[str],
    encoder_version: str,
    anchors_kind: str,
) -> set[str]:
    if not asset_ids:
        return set()
    placeholders = ",".join("?" for _ in asset_ids)
    rows = conn.execute(
        f"""
        SELECT asset_id FROM image_asset_dino_predictions
         WHERE asset_id IN ({placeholders})
           AND encoder_version = ? AND anchors_kind = ?
        """,
        (*asset_ids, encoder_version, anchors_kind),
    ).fetchall()
    return {r["asset_id"] for r in rows}


# Called by: ml/sources/_base/orchestrator.py (step 7/8 — after resolve, before enqueue; suggestion layer, no decision in V1)
def run_auto_validate_dino(
    *,
    conn: sqlite3.Connection,
    run: RunHandle | None,
    source_id: str,
    source_image_ids: dict[str, str],
    anchors_kind: str = "2eur_commemo",
    force: bool = False,
) -> AutoValidateResult:
    """Step 5.5 entry point — called by the orchestrator after `resolve`.

    Falls back to a no-op (logged) if the bank file is missing — the
    upstream pipeline should not break because the auto-validation
    layer hasn't been bootstrapped yet.
    """
    bank = _get_bank(anchors_kind)
    if bank is None:
        logger.warning(
            "[%s] auto_validate: anchor bank %s missing — skipping (run "
            "`go-task ml:dino-anchors:build` to bootstrap)",
            source_id, anchors_kind,
        )
        return AutoValidateResult(0, 0, 0, 0, 0)

    candidates = _select_assets_for_run(conn, source_image_ids)
    return _run_inner(
        conn=conn,
        candidates=candidates,
        bank=bank,
        anchors_kind=anchors_kind,
        force=force,
    )


# Called by: ml/scripts/backfill_dino_predictions.py (standalone re-run over all in-scope assets, no run row)
def run_auto_validate_dino_backfill(
    *,
    store,
    anchors_kind: str = "2eur_commemo",
    force: bool = False,
    limit: int | None = None,
) -> AutoValidateResult:
    """Standalone backfill — used by ml/scripts/backfill_dino_predictions.py.

    Selects all `image_assets` matching the V1 scope and runs the same
    inner loop. Bypasses the orchestrator's run handle.
    """
    bank = _get_bank(anchors_kind)
    if bank is None:
        logger.error(
            "auto_validate backfill: anchor bank %s missing — run "
            "`go-task ml:dino-anchors:build` first",
            anchors_kind,
        )
        return AutoValidateResult(0, 0, 0, 0, 0)

    conn = store._connection()  # noqa: SLF001
    candidates = _select_assets_for_backfill(conn, limit=limit)
    logger.info(
        "auto_validate backfill: %d candidate assets in scope %s",
        len(candidates), anchors_kind,
    )
    return _run_inner(
        conn=conn,
        candidates=candidates,
        bank=bank,
        anchors_kind=anchors_kind,
        force=force,
        store=store,
    )


# Called by: ml/api/review_queue_routes.py (manual_crop) — recompute on demand
# after a human re-crop, so the Dino suggestions panel reflects the corrected
# crop without waiting for a batch backfill.
def predict_and_persist_one(
    *,
    store,
    asset_id: str,
    crop_path: Path,
    target_country: str | None = None,
    anchors_kind: str = "2eur_commemo",
) -> DinoPredictionRow | None:
    """Encode one crop, match against the anchor bank, upsert the prediction.

    Reuses the process-wide encoder + bank singletons (same path as the
    batch backfill → identical format). Returns the persisted row, or None
    if the bank is missing or the crop can't be encoded. Scope is NOT
    enforced here: a human re-crop is an explicit action and the caller
    owns the decision to run Dino (the V1 bank is 2€ commémo anchors).
    """
    bank = _get_bank(anchors_kind)
    if bank is None:
        logger.warning(
            "predict_and_persist_one: anchor bank %s missing — skipping",
            anchors_kind,
        )
        return None
    encoder, device, transform = _get_encoder_singleton()
    prediction = _predict_one(
        asset_id=asset_id,
        crop_path=crop_path,
        bank=bank,
        encoder=encoder,
        device=device,
        transform=transform,
        anchors_kind=anchors_kind,
        target_country=target_country,
    )
    if prediction is None:
        return None
    store.upsert_dino_predictions([prediction])
    return prediction


def _run_inner(
    *,
    conn: sqlite3.Connection,
    candidates: list,
    bank: AnchorBank,
    anchors_kind: str,
    force: bool,
    store=None,
) -> AutoValidateResult:
    n_predicted = 0
    n_existing = 0
    n_no_anchor = 0
    n_oos = 0
    n_errors = 0
    predicted_ids: list[str] = []  # assets re-prédits → re-route lane post-Dino

    in_scope: list = []
    for r in candidates:
        if anchors_kind == "2eur_commemo":
            if not (r["face_value"] and float(r["face_value"]) == 2.0 and r["is_commemorative"]):
                n_oos += 1
                continue
        in_scope.append(r)

    if not in_scope:
        return AutoValidateResult(0, 0, 0, n_oos, 0)

    encoder, device, transform = _get_encoder_singleton()

    asset_ids = [r["asset_id"] for r in in_scope]
    skip = (
        _existing_keys(conn, asset_ids, bank.encoder_version, anchors_kind)
        if not force
        else set()
    )

    rows_to_write: list[DinoPredictionRow] = []
    for r in in_scope:
        aid = r["asset_id"]
        if aid in skip:
            n_existing += 1
            continue
        # Target country from the parent eBay query (source_images.target_eurio_id).
        # First 2 chars of the eurio_id = ISO2. NULL if no target — fall back to
        # global top-K only.
        target_eid = r["target_eurio_id"]
        target_country = (
            target_eid[:2].lower() if target_eid and len(target_eid) >= 2 else None
        )
        # storage_path is the S3 key in enrichment-crops. local_path()
        # does read-through cache (no-op if cached by same-run detect_crop).
        from storage.local_cache import local_path as _local_path
        try:
            crop_p = _local_path("enrichment-crops", r["storage_path"])
        except FileNotFoundError as exc:
            logger.error("auto_validate: missing crop in MinIO asset=%s key=%s: %s",
                         aid, r["storage_path"], exc)
            n_errors += 1
            continue
        try:
            prediction = _predict_one(
                asset_id=aid,
                crop_path=crop_p,
                bank=bank,
                encoder=encoder,
                device=device,
                transform=transform,
                anchors_kind=anchors_kind,
                target_country=target_country,
            )
        except Exception as exc:  # broad on purpose — pipeline must keep moving
            logger.exception("auto_validate: failed on asset=%s: %s", aid, exc)
            n_errors += 1
            continue
        if prediction is None:
            n_errors += 1
            continue
        rows_to_write.append(prediction)
        predicted_ids.append(aid)
        n_predicted += 1
        if len(rows_to_write) >= 32:
            _flush(conn, store, rows_to_write)
            rows_to_write.clear()

    if rows_to_write:
        _flush(conn, store, rows_to_write)
        rows_to_write.clear()

    # Re-route post-Dino : pour les items DÉJÀ en queue (cas backfill — en run
    # normal l'enqueue vient APRÈS et pose la lane lui-même), recalcule la lane
    # des items open NON épinglés humain à partir de la prédiction qu'on vient
    # d'écrire. Source de vérité = foundation/review_lanes. Les items
    # lane_source='human' (déplacés à la main) ne sont JAMAIS re-routés.
    n_relane = 0
    for aid in predicted_ids:
        rq = conn.execute(
            "SELECT id, lane FROM review_queue "
            "WHERE image_asset_id=? AND status='open' AND lane_source='auto'",
            (aid,),
        ).fetchone()
        if rq is None:
            continue
        _v, lane = compute_lane(conn, aid)
        if lane != rq["lane"]:
            conn.execute(
                "UPDATE review_queue SET lane=? WHERE id=? AND lane_source='auto'",
                (lane, rq["id"]),
            )
            n_relane += 1
    if n_relane:
        logger.info("auto_validate: re-routed %d review lanes (post-Dino)", n_relane)

    logger.info(
        "auto_validate: predicted=%d existing=%d no_anchor=%d "
        "out_of_scope=%d errors=%d",
        n_predicted, n_existing, n_no_anchor, n_oos, n_errors,
    )
    return AutoValidateResult(
        n_predicted=n_predicted,
        n_skipped_existing=n_existing,
        n_skipped_no_anchor=n_no_anchor,
        n_skipped_out_of_scope=n_oos,
        n_errors=n_errors,
    )


def _flush(conn: sqlite3.Connection, store, rows: list[DinoPredictionRow]) -> None:
    """Persist a batch of predictions. Uses Store helper when available
    (orchestrator path), falls back to a direct SQL upsert (run from a
    raw connection — tests / standalone backfill before Store is
    plumbed)."""
    if not rows:
        return
    if store is not None:
        store.upsert_dino_predictions(rows)
        return
    # Direct path — reproduces the SQL of Store.upsert_dino_predictions
    import json as _json
    conn.executemany(
        """
        INSERT INTO image_asset_dino_predictions (
          asset_id, encoder_version, anchors_kind, anchors_count,
          top_k_json, top1_eurio_id, top1_sim, top2_eurio_id,
          top2_sim, spread,
          target_country, country_anchors_count, top_k_country_json,
          top1_country_eurio_id, top1_country_sim,
          top2_country_eurio_id, top2_country_sim, country_spread,
          computed_at, duration_ms
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                  ?, ?, ?, ?, ?, ?, ?, ?,
                  datetime('now'), ?)
        ON CONFLICT(asset_id, encoder_version, anchors_kind) DO UPDATE SET
          anchors_count          = excluded.anchors_count,
          top_k_json             = excluded.top_k_json,
          top1_eurio_id          = excluded.top1_eurio_id,
          top1_sim               = excluded.top1_sim,
          top2_eurio_id          = excluded.top2_eurio_id,
          top2_sim               = excluded.top2_sim,
          spread                 = excluded.spread,
          target_country         = excluded.target_country,
          country_anchors_count  = excluded.country_anchors_count,
          top_k_country_json     = excluded.top_k_country_json,
          top1_country_eurio_id  = excluded.top1_country_eurio_id,
          top1_country_sim       = excluded.top1_country_sim,
          top2_country_eurio_id  = excluded.top2_country_eurio_id,
          top2_country_sim       = excluded.top2_country_sim,
          country_spread         = excluded.country_spread,
          duration_ms            = excluded.duration_ms,
          computed_at            = datetime('now')
        """,
        [
            (
                r.asset_id, r.encoder_version, r.anchors_kind, r.anchors_count,
                _json.dumps(r.top_k),
                r.top1_eurio_id, r.top1_sim, r.top2_eurio_id, r.top2_sim,
                r.spread,
                r.target_country, r.country_anchors_count,
                _json.dumps(r.top_k_country) if r.top_k_country is not None else None,
                r.top1_country_eurio_id, r.top1_country_sim,
                r.top2_country_eurio_id, r.top2_country_sim, r.country_spread,
                r.duration_ms,
            )
            for r in rows
        ],
    )
