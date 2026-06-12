"""Backfill C7 pilier 2 — gate dénomination « 2€ vs junk » sur l'existant.

Calcule ``image_assets.denom`` (+ ``denom_2eur_score`` audit) pour les crops 2€
encore NULL, via la probe DINO+bimétal (`vision/denom_probe.py`). Puis, pour les
crops ``not_2eur`` (cent/médaille/mire/1€/set) encore ``needs_review`` :
  - les REJETTE (rejet terminal ré-ouvrable, comme à l'enqueue) ;
  - recalcule ``source_images.route_reason`` → bucket « not_2eur » dans le funnel.

Réutilise STRICTEMENT les helpers existants (auto_validate + enqueue + denom_probe)
— aucune logique dupliquée. Idempotent :
  - ``denom`` écrit seulement si NULL (anti-clobber labels humains/Claude) ;
  - rejet seulement si le crop est encore ``needs_review`` ET non /restore humain.

Usage :
    python -m scripts.backfill_denom [--run PREFIX] [--limit N] [--dry] [-v]
"""

from __future__ import annotations

import argparse
import logging
import sys
import uuid
from pathlib import Path

import cv2
import numpy as np

ML_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ML_DIR))

from sources._base.steps.auto_validate import (  # noqa: E402
    SUGGESTIONS_ANCHORS_KIND,
    _get_bank,
    _get_encoder_singleton,
)
from sources._base.steps.enqueue import (  # noqa: E402
    _DENOM_ENGINE_VERSION,
    _kind_for_source_image,
    _reject_crop_terminal,
    _route_decision_for_source_image,
)
from review.review_lanes import DEFAULT_LANE  # noqa: E402
from training.foundation import SUGGESTIONS_ENCODER_VERSION, encode_image  # noqa: E402
from shared.storage.local_cache import local_path  # noqa: E402
from store import Store  # noqa: E402
from vision.denom_probe import decide_denom, denom_score, denom_threshold  # noqa: E402

DB_PATH = ML_DIR / "state" / "eurio.db"
logger = logging.getLogger("backfill_denom")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--run", default=None, help="préfixe run_id (filtre source_images)")
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--dry", action="store_true", help="Calcule + affiche, n'écrit rien.")
    ap.add_argument("--db", default=str(DB_PATH))
    ap.add_argument("--verbose", "-v", action="store_true")
    args = ap.parse_args()

    logging.basicConfig(
        level=logging.INFO if args.verbose else logging.WARNING,
        format="%(asctime)s %(levelname)-7s %(name)s %(message)s",
    )
    logging.getLogger("backfill_denom").setLevel(logging.INFO)

    if denom_threshold() is None:
        sys.exit("Probe denom absente — state/denom_probe.npz (scripts.train_denom_probe --save)")
    print(f"seuil denom = {denom_threshold():.4f}")

    store = Store(Path(args.db))
    conn = store._connection()  # noqa: SLF001
    all_bank = _get_bank(SUGGESTIONS_ANCHORS_KIND)
    if all_bank is None:
        sys.exit("Banque 2eur_all absente — go-task ml:dino-anchors:build -- --kind 2eur_all")
    enc, dev, tf = _get_encoder_singleton(SUGGESTIONS_ENCODER_VERSION)

    sql = """
        SELECT a.id AS asset_id, a.source_image_id, a.storage_path
          FROM image_assets a
          JOIN source_images s ON s.id = a.source_image_id
          JOIN coins c ON c.eurio_id = s.target_eurio_id
         WHERE a.denom IS NULL
           AND a.storage_status = 'present'
           AND a.storage_path IS NOT NULL
           AND c.face_value = 2.0
    """
    params: list = []
    if args.run:
        sql += " AND s.run_id LIKE ?"
        params.append(f"{args.run}%")
    sql += " ORDER BY a.fetched_at ASC"
    if args.limit:
        sql += f" LIMIT {int(args.limit)}"
    rows = conn.execute(sql, params).fetchall()
    logger.info("backfill_denom : %d crops denom IS NULL à évaluer", len(rows))

    # ── Phase 1 : score denom (vec vitl14 + bimétal) ─────────────────────
    verdicts: list[tuple[str, str, float]] = []  # (asset_id, denom, score)
    n_err = 0
    for i, r in enumerate(rows):
        try:
            p = local_path("enrichment-crops", r["storage_path"])
            vec = encode_image(p, encoder=enc, device=dev, transform=tf)
            bgr = cv2.imread(str(p))
            if bgr is None:
                raise ValueError("cv2.imread None")
        except Exception as exc:  # noqa: BLE001
            logger.warning("encode/read failed asset=%s: %s", r["asset_id"], exc)
            n_err += 1
            continue
        s = denom_score(vec, bgr)
        verdicts.append((r["asset_id"], decide_denom(s), float(s)))
        if (i + 1) % 200 == 0:
            logger.info("  %d/%d scorés", i + 1, len(rows))

    n_junk = sum(1 for _, d, _ in verdicts if d == "not_2eur")
    sid_by_asset = {r["asset_id"]: r["source_image_id"] for r in rows}
    print(f"\nÉvalués : {len(verdicts)} (erreurs {n_err}) → "
          f"{n_junk} not_2eur / {len(verdicts) - n_junk} 2eur")

    if args.dry:
        print("DRY — rien écrit.")
        return 0

    # ── Phase 2 : écritures (denom, audit score, rejets, reroute) ────────
    affected_sids: set[str] = set()
    n_rejected = 0
    with store._writing() as wconn:  # noqa: SLF001
        wconn.executemany(
            "UPDATE image_assets SET denom=? WHERE id=? AND denom IS NULL",
            [(d, aid) for aid, d, _ in verdicts],
        )
        wconn.executemany(
            "UPDATE image_asset_dino_predictions SET denom_2eur_score=? "
            "WHERE asset_id=? AND anchors_kind=?",
            [(s, aid, SUGGESTIONS_ANCHORS_KIND) for aid, _, s in verdicts],
        )

        for aid, denom, _ in verdicts:
            if denom != "not_2eur":
                continue
            sid = sid_by_asset[aid]
            cur = wconn.execute(
                "SELECT resolution_status FROM image_assets WHERE id=?", (aid,),
            ).fetchone()
            if cur is None or cur["resolution_status"] != "needs_review":
                continue  # déjà tranché (humain/consensus/face_reverse) → ne pas clobber
            rq = wconn.execute(
                "SELECT id, status, decision_notes FROM review_queue "
                "WHERE image_asset_id=?", (aid,),
            ).fetchone()
            if rq is not None and (rq["status"] != "open"
                                   or rq["decision_notes"] == "restored"):
                continue  # décidé ou ré-ouvert à la main → sticky
            if rq is None:
                review_id = uuid.uuid4().hex
                kind = _kind_for_source_image(
                    wconn, source_image_id=sid, is_lot_suspected=False)
                wconn.execute(
                    "INSERT INTO review_queue (id, image_asset_id, priority, "
                    "candidate_eurio_ids_json, kind, lane) VALUES (?, ?, ?, ?, ?, ?)",
                    (review_id, aid, 100, None, kind, DEFAULT_LANE),
                )
            else:
                review_id = rq["id"]
            _reject_crop_terminal(
                wconn, asset_id=aid, review_id=review_id,
                quality_reason="not_2eur", decided_by="pipeline",
                state_reason="not_2eur", engine_version=_DENOM_ENGINE_VERSION,
                decision_payload={"reason": "not_2eur", "backfill": True},
                target_eurio_id=None, run_id=None,
            )
            affected_sids.add(sid)
            n_rejected += 1

        n_reroute = 0
        for sid in affected_sids:
            kind = _kind_for_source_image(wconn, source_image_id=sid, is_lot_suspected=False)
            decision, reason = _route_decision_for_source_image(
                wconn, source_image_id=sid, kind=kind, is_lot_suspected=False)
            wconn.execute(
                "UPDATE source_images SET route_decision=?, route_reason=? WHERE id=?",
                (decision, reason, sid),
            )
            n_reroute += 1

    print(f"Écrit : denom sur {len(verdicts)} crops · {n_rejected} not_2eur rejetés · "
          f"{n_reroute} listings re-routés")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
