"""Backfill C7 — détection de face (avers vs revers commun 2€) sur l'existant.

Calcule ``image_assets.face`` pour les crops 2€ encore NULL, via le détecteur
zéro-training (sim aux 2 ancres du revers commun vs banque avers ``2eur_all``,
seuil ``FACE_REVERSE_TAU``). Puis, pour les crops détectés ``reverse`` :
  - les REJETTE (rejet terminal ré-ouvrable, comme à l'enqueue) ;
  - recalcule ``source_images.route_reason`` des listings touchés → le bucket
    « revers commun 2€ » apparaît dans le funnel bench.

Réutilise STRICTEMENT les helpers existants (auto_validate + enqueue) — aucune
logique dupliquée. Idempotent :
  - ``face`` écrit seulement si NULL (ne clobbe pas les labels humains/Claude) ;
  - rejet seulement si le crop est encore ``needs_review`` ET non /restore humain ;
  - recompute route_reason déterministe.

Usage :
    .venv/bin/python -m scripts.backfill_face [--limit N] [--dry] [-v]

⚠️  MIGRATION VPS-ONLY sous Direction A (docs/work-in-progress/local-sync/
migration-direction-a.md §C7) : ce script écrit le canonique (``UPDATE
image_assets`` non transporté par une route ``/ingest``). Ne PAS le lancer
contre une réplique locale (Mac/PC read-only ou client d'un VPS canonique) —
refuse automatiquement sauf ``--i-know-this-is-canonical``. Dépend de
torch/DINO (encodeur ArcFace) : sur une machine GPU non-VPS, pointer ``--db``
vers une copie synchronisée du canonique puis pousser le résultat (procédure
non encore tranchée, cf. docs/work-in-progress/local-sync/vps-only-migrations.md).
"""

from __future__ import annotations

import argparse
import logging
import sys
import time
import uuid
from pathlib import Path

import numpy as np

ML_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ML_DIR))

from scripts._vps_only_guard import guard_vps_only  # noqa: E402
from sources._base.steps.auto_validate import (  # noqa: E402
    SUGGESTIONS_ANCHORS_KIND,
    _decide_face,
    _get_bank,
    _get_encoder_singleton,
    _get_reverse_bank,
)
from sources._base.steps.enqueue import (  # noqa: E402
    _FACE_ENGINE_VERSION,
    _kind_for_source_image,
    _reject_crop_terminal,
    _route_decision_for_source_image,
)
from review.review_lanes import DEFAULT_LANE  # noqa: E402
from training.foundation import SUGGESTIONS_ENCODER_VERSION, encode_image  # noqa: E402
from shared.storage.local_cache import local_path  # noqa: E402
from store import Store  # noqa: E402

DB_PATH = ML_DIR / "state" / "eurio.db"
logger = logging.getLogger("backfill_face")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--dry", action="store_true", help="Calcule + affiche, n'écrit rien.")
    ap.add_argument("--db", default=str(DB_PATH))
    ap.add_argument("--verbose", "-v", action="store_true")
    ap.add_argument(
        "--i-know-this-is-canonical", action="store_true", dest="allow_non_vps",
        help="Bypass le garde-fou VPS-only (Direction A) — --db pointe une copie canonique.",
    )
    args = ap.parse_args()
    guard_vps_only("backfill_face", allow=args.allow_non_vps)

    logging.basicConfig(
        level=logging.INFO if args.verbose else logging.WARNING,
        format="%(asctime)s %(levelname)-7s %(name)s %(message)s",
    )
    for n in ("backfill_face", "training.foundation", "sources._base.steps.auto_validate"):
        logging.getLogger(n).setLevel(logging.INFO)

    store = Store(Path(args.db))
    conn = store._connection()  # noqa: SLF001

    rev_bank = _get_reverse_bank()
    all_bank = _get_bank(SUGGESTIONS_ANCHORS_KIND)
    if rev_bank is None or all_bank is None:
        sys.exit("Banque revers ou 2eur_all absente — go-task ml:dino-anchors:build "
                 "-- --kind reverse_2eur (et --kind 2eur_all)")
    enc, dev, tf = _get_encoder_singleton(SUGGESTIONS_ENCODER_VERSION)

    # Crops 2€ sans face décidée, présents sur disque.
    sql = """
        SELECT a.id AS asset_id, a.source_image_id, a.storage_path,
               p.top1_sim AS all_top1_sim
          FROM image_assets a
          JOIN source_images s ON s.id = a.source_image_id
          JOIN coins c ON c.eurio_id = s.target_eurio_id
     LEFT JOIN image_asset_dino_predictions p
            ON p.asset_id = a.id AND p.anchors_kind = ?
         WHERE a.face IS NULL
           AND a.storage_status = 'present'
           AND a.storage_path IS NOT NULL
           AND c.face_value = 2.0
         ORDER BY a.fetched_at ASC
    """
    if args.limit:
        sql += f" LIMIT {int(args.limit)}"
    rows = conn.execute(sql, (SUGGESTIONS_ANCHORS_KIND,)).fetchall()
    logger.info("backfill_face : %d crops face IS NULL à évaluer", len(rows))

    # ── Phase 1 : calcul face (+ reverse_sim/face_margin) ────────────────
    faces: list[tuple[str, str, float, float]] = []  # (asset_id, face, rev_sim, margin)
    n_err = 0
    for i, r in enumerate(rows):
        try:
            vec = encode_image(local_path("enrichment-crops", r["storage_path"]),
                               encoder=enc, device=dev, transform=tf)
        except Exception as exc:  # noqa: BLE001
            logger.warning("encode failed asset=%s: %s", r["asset_id"], exc)
            n_err += 1
            continue
        rev_sim = float(np.max(rev_bank.matrix @ vec))
        obv_sim = r["all_top1_sim"]
        if obv_sim is None:  # pas de prédiction 2eur_all → recompute top1 ici
            obv_sim = float(np.max(all_bank.matrix @ vec))
        faces.append((r["asset_id"], _decide_face(rev_sim, obv_sim),
                      rev_sim, rev_sim - float(obv_sim)))
        if (i + 1) % 200 == 0:
            logger.info("  %d/%d encodés", i + 1, len(rows))

    n_reverse = sum(1 for _, f, _, _ in faces if f == "reverse")
    sid_by_asset = {r["asset_id"]: r["source_image_id"] for r in rows}
    print(f"\nÉvalués : {len(faces)} (erreurs {n_err}) → "
          f"{n_reverse} reverse / {len(faces) - n_reverse} obverse")

    if args.dry:
        print("DRY — rien écrit.")
        return 0

    # ── Phase 2 : écritures (face, audit sims, rejets, reroute) ──────────
    affected_sids: set[str] = set()
    n_rejected = 0
    with store._writing() as wconn:  # noqa: SLF001
        # face (garde IS NULL) + audit reverse_sim/face_margin sur la row 2eur_all
        wconn.executemany(
            "UPDATE image_assets SET face=? WHERE id=? AND face IS NULL",
            [(f, aid) for aid, f, _, _ in faces],
        )
        wconn.executemany(
            "UPDATE image_asset_dino_predictions SET reverse_sim=?, face_margin=? "
            "WHERE asset_id=? AND anchors_kind=?",
            [(rs, m, aid, SUGGESTIONS_ANCHORS_KIND) for aid, _, rs, m in faces],
        )

        # rejet des reverse encore needs_review et non /restore humain
        for aid, face, _, _ in faces:
            if face != "reverse":
                continue
            sid = sid_by_asset[aid]
            cur = wconn.execute(
                "SELECT resolution_status FROM image_assets WHERE id=?", (aid,),
            ).fetchone()
            if cur is None or cur["resolution_status"] != "needs_review":
                continue  # déjà tranché (humain/consensus) → ne pas clobber
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
                quality_reason="face_reverse", decided_by="pipeline",
                state_reason="face_reverse", engine_version=_FACE_ENGINE_VERSION,
                decision_payload={"reason": "face_reverse", "backfill": True},
                target_eurio_id=None, run_id=None,
            )
            affected_sids.add(sid)
            n_rejected += 1

        # reroute listing-level route_reason des listings touchés
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

    print(f"Écrit : face sur {len(faces)} crops · {n_rejected} reverse rejetés · "
          f"{n_reroute} listings re-routés")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
