"""Backfill C7 pilier 2 — gate dénomination « 2€ vs junk » sur l'existant.

Calcule ``image_assets.denom`` (+ ``denom_2eur_score`` audit) pour les crops 2€
encore NULL dont la photo source est un **LOT** (même périmètre que le gate live
dans `auto_validate` : titre lot / listing_kind='lot' / >1 crops — la pollution
non-2€ vient des lots, HANDOFF-C7 §1), via la probe DINO (`vision/denom_probe.py`).

**Audit d'abord (défaut)** : AUCUN re-routage — denom + score seulement, pour
inspection dans le funnel/bench. Le rejet terminal se déclenche avec ``--reject``
APRÈS validation PO ; il lit ``denom='not_2eur'`` en base (pas les verdicts du
run courant), donc les deux passes peuvent être des invocations séparées :
  - les ``not_2eur`` encore ``needs_review`` sont REJETÉS (ré-ouvrables, comme
    à l'enqueue) ;
  - ``source_images.route_reason`` est recalculé → bucket « not_2eur » funnel.

Réutilise STRICTEMENT les helpers existants (auto_validate + enqueue + denom_probe)
— aucune logique dupliquée. Idempotent :
  - ``denom`` écrit seulement si NULL (anti-clobber labels humains/Claude) ;
  - rejet seulement si le crop est encore ``needs_review`` ET non /restore humain.

Usage :
    python -m scripts.backfill_denom [--run PREFIX] [--limit N] [--dry] [-v]
    python -m scripts.backfill_denom --reject   # après validation PO

⚠️  MIGRATION VPS-ONLY sous Direction A (docs/work-in-progress/local-sync/
migration-direction-a.md §C7) : ce script écrit le canonique (``UPDATE
image_assets`` non transporté par une route ``/ingest``). Ne PAS le lancer
contre une réplique locale (Mac/PC read-only ou client d'un VPS canonique) —
refuse automatiquement sauf ``--i-know-this-is-canonical``. Dépend de la probe
DINO (torch) : sur une machine GPU non-VPS, pointer ``--db`` vers une copie
synchronisée du canonique puis pousser le résultat (procédure non encore
tranchée, cf. docs/work-in-progress/local-sync/vps-only-migrations.md).
"""

from __future__ import annotations

import argparse
import logging
import sys
import uuid
from pathlib import Path

import cv2

ML_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ML_DIR))

from scripts._vps_only_guard import guard_vps_only  # noqa: E402
from sources._base.steps.auto_validate import (  # noqa: E402
    SUGGESTIONS_ANCHORS_KIND,
    _get_bank,
    _get_encoder_singleton,
    _is_lot_source,
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
from store import Store, resolve_db_path  # noqa: E402
from vision.denom_probe import decide_denom, denom_score, denom_threshold  # noqa: E402

# Défaut résolu par `store.resolve_db_path` : la base que le RESTE de la
# machine lit (`EURIO_DB_PATH` — la réplique sous Direction A, le canonique
# sur le VPS), jamais un chemin codé en dur. Mesuré le 2026-08-19 :
# `state/eurio.db` porte 6205 `image_assets` (5466 prédictions `2eur_all`)
# contre 12454 / 12454 dans `state/eurio.replica.db` — la banque `2eur_all`
# avait été bâtie dessus pendant des semaines.
# Repli hors devShell : `state/eurio.replica.db`. La règle et son arbitrage
# (2026-08-19) sont dans la docstring de `store.resolve_db_path`.
DB_PATH = resolve_db_path(ML_DIR / "state" / "eurio.replica.db")
logger = logging.getLogger("backfill_denom")


def _score_phase(store, *, run_prefix: str | None, limit: int | None,
                 dry: bool) -> int:
    """Phase audit : score + verdict denom sur les crops lot encore NULL."""
    conn = store._connection()  # noqa: SLF001
    all_bank = _get_bank(SUGGESTIONS_ANCHORS_KIND)
    if all_bank is None:
        sys.exit("Banque 2eur_all absente — go-task ml:dino-anchors:build -- --kind 2eur_all")
    enc, dev, tf = _get_encoder_singleton(SUGGESTIONS_ENCODER_VERSION)

    sql = """
        SELECT a.id AS asset_id, a.source_image_id, a.storage_path,
               s.is_lot_suspected
          FROM image_assets a
          JOIN source_images s ON s.id = a.source_image_id
          JOIN coins c ON c.eurio_id = s.target_eurio_id
         WHERE a.denom IS NULL
           AND a.storage_status = 'present'
           AND a.storage_path IS NOT NULL
           AND c.face_value = 2.0
    """
    params: list = []
    if run_prefix:
        sql += " AND s.run_id LIKE ?"
        params.append(f"{run_prefix}%")
    sql += " ORDER BY a.fetched_at ASC"
    if limit:
        sql += f" LIMIT {int(limit)}"
    rows = conn.execute(sql, params).fetchall()

    # Périmètre LOT uniquement — même garde que le gate live (auto_validate).
    lot_cache: dict[str, bool] = {}
    lot_rows = [
        r for r in rows
        if _is_lot_source(
            conn, source_image_id=r["source_image_id"],
            is_lot_suspected=r["is_lot_suspected"], cache=lot_cache,
        )
    ]
    logger.info(
        "backfill_denom : %d crops lot à scorer (%d denom IS NULL, %d single skip)",
        len(lot_rows), len(rows), len(rows) - len(lot_rows),
    )

    # ── Phase 1 : score denom (vec vitl14 + bimétal) ─────────────────────
    verdicts: list[tuple[str, str, float]] = []  # (asset_id, denom, score)
    n_err = 0
    for i, r in enumerate(lot_rows):
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
            logger.info("  %d/%d scorés", i + 1, len(lot_rows))

    n_junk = sum(1 for _, d, _ in verdicts if d == "not_2eur")
    print(f"\nÉvalués : {len(verdicts)} crops lot (erreurs {n_err}) → "
          f"{n_junk} not_2eur / {len(verdicts) - n_junk} 2eur")

    if dry:
        print("DRY — rien écrit.")
        return 0

    # ── Phase 2 : écritures AUDIT (denom + score) — pas de re-routage ────
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
    print(f"Écrit : denom + denom_2eur_score sur {len(verdicts)} crops "
          f"[denom IS NULL only — routes inchangées]")
    return 0


def _reject_phase(store, *, run_prefix: str | None, dry: bool) -> int:
    """Phase rejet (post-validation PO) : rejette les ``denom='not_2eur'``
    encore ``needs_review`` et re-route les listings touchés. Lit l'état DB,
    pas les verdicts d'un run de scoring — rejouable indépendamment."""
    conn = store._connection()  # noqa: SLF001
    sql = """
        SELECT a.id AS asset_id, a.source_image_id, s.is_lot_suspected
          FROM image_assets a
          JOIN source_images s ON s.id = a.source_image_id
         WHERE a.denom = 'not_2eur'
           AND a.resolution_status = 'needs_review'
    """
    params: list = []
    if run_prefix:
        sql += " AND s.run_id LIKE ?"
        params.append(f"{run_prefix}%")
    rows = conn.execute(sql, params).fetchall()
    print(f"Rejet : {len(rows)} crops not_2eur encore needs_review")
    if dry:
        print("DRY — rien écrit.")
        return 0

    lot_suspected_by_sid = {r["source_image_id"]: bool(r["is_lot_suspected"])
                            for r in rows}
    affected_sids: set[str] = set()
    n_rejected = 0
    with store._writing() as wconn:  # noqa: SLF001
        for r in rows:
            aid, sid = r["asset_id"], r["source_image_id"]
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
                    wconn, source_image_id=sid,
                    is_lot_suspected=lot_suspected_by_sid[sid])
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
            is_lot = lot_suspected_by_sid[sid]
            kind = _kind_for_source_image(
                wconn, source_image_id=sid, is_lot_suspected=is_lot)
            decision, reason = _route_decision_for_source_image(
                wconn, source_image_id=sid, kind=kind, is_lot_suspected=is_lot)
            wconn.execute(
                "UPDATE source_images SET route_decision=?, route_reason=? WHERE id=?",
                (decision, reason, sid),
            )
            n_reroute += 1

    print(f"Écrit : {n_rejected} not_2eur rejetés (ré-ouvrables) · "
          f"{n_reroute} listings re-routés")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--run", default=None, help="préfixe run_id (filtre source_images)")
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--reject", action="store_true",
                    help="rejette les denom='not_2eur' + re-route les listings "
                         "(post-validation PO ; défaut = audit seul)")
    ap.add_argument("--dry", action="store_true", help="Calcule + affiche, n'écrit rien.")
    ap.add_argument("--db", default=str(DB_PATH))
    ap.add_argument("--verbose", "-v", action="store_true")
    ap.add_argument(
        "--i-know-this-is-canonical", action="store_true", dest="allow_non_vps",
        help="Bypass le garde-fou VPS-only (Direction A) — --db pointe une copie canonique.",
    )
    args = ap.parse_args()
    guard_vps_only("backfill_denom", allow=args.allow_non_vps)

    logging.basicConfig(
        level=logging.INFO if args.verbose else logging.WARNING,
        format="%(asctime)s %(levelname)-7s %(name)s %(message)s",
    )
    logging.getLogger("backfill_denom").setLevel(logging.INFO)

    if denom_threshold() is None:
        sys.exit("Probe denom absente — state/denom_probe.npz (scripts.train_denom_probe --save)")
    print(f"seuil denom = {denom_threshold():.4f}")

    store = Store(Path(args.db))
    if args.reject:
        return _reject_phase(store, run_prefix=args.run, dry=args.dry)
    rc = _score_phase(store, run_prefix=args.run, limit=args.limit, dry=args.dry)
    if rc == 0 and not args.dry:
        print("(audit only — relancer avec --reject après validation PO pour "
              "rejeter les not_2eur et re-router les listings)")
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
