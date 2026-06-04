"""Backfill : re-extrait listing_kind (vocabulaire multilingue enrichi) et
re-route les annonces dont le kind passe single→lot.

Quick win cohort-pipeline (cf. docs/cohort-pipeline/coin-census-bench.md) : la
règle lot/single route désormais via listing_kind (KMS/Satz/cofre/N valores/
≥2 pays/plage 1cent-2euro). Ce script applique la nouvelle classification aux
annonces déjà ingérées + corrige la file de review existante.

Idempotent. Dry-run par défaut ; --apply pour écrire.

Usage:
    PYTHONPATH=. .venv/bin/python scripts/backfill_listing_kind_routing.py [--cohort ID] [--apply]
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ML_DIR = Path(__file__).resolve().parent.parent
if str(ML_DIR) not in sys.path:
    sys.path.insert(0, str(ML_DIR))

from sources._base.steps.enqueue import (  # noqa: E402
    _kind_for_source_image,
    _route_decision_for_source_image,
)
from sources.text_signals.extractor import extract_listing_text_signals  # noqa: E402
from state import Store  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cohort", default="b0299ca0252b")
    ap.add_argument("--apply", action="store_true", help="écrire (sinon dry-run)")
    args = ap.parse_args()

    store = Store(ML_DIR / "state" / "eurio.db")
    conn = store._connection()  # noqa: SLF001

    eids = [
        r[0] for r in conn.execute(
            "SELECT value FROM json_each((SELECT eurio_ids_json FROM "
            "experiment_cohorts WHERE id = ?))", (args.cohort,)
        )
    ]
    if not eids:
        print(f"cohorte {args.cohort} introuvable / vide"); return
    ph = ",".join("?" * len(eids))
    rows = conn.execute(
        f"SELECT id, listing_title, is_lot_suspected, route_decision, route_reason "
        f"FROM source_images WHERE target_eurio_id IN ({ph})", eids
    ).fetchall()

    n_kind_changed = n_route_flipped = n_rq_updated = 0
    flips = []
    for r in rows:
        sid = r["id"]
        new_lk = extract_listing_text_signals(r["listing_title"]).listing_kind
        old_lk_row = conn.execute(
            "SELECT listing_kind FROM listing_text_signals WHERE source_image_id = ?", (sid,)
        ).fetchone()
        old_lk = old_lk_row["listing_kind"] if old_lk_row else None
        if old_lk != new_lk:
            n_kind_changed += 1
            if args.apply and old_lk_row is not None:
                conn.execute(
                    "UPDATE listing_text_signals SET listing_kind = ? WHERE source_image_id = ?",
                    (new_lk, sid),
                )

        # Re-route avec la nouvelle logique (lit listing_kind à jour si --apply ;
        # en dry-run on simule en passant par le kind recalculé).
        kind = _kind_for_source_image(
            conn, source_image_id=sid, is_lot_suspected=bool(r["is_lot_suspected"])
        ) if args.apply else (
            "lot" if (bool(r["is_lot_suspected"]) or new_lk == "lot"
                      or (conn.execute("SELECT COUNT(*) c FROM image_assets WHERE source_image_id=?", (sid,)).fetchone()["c"] or 0) > 1)
            else "single"
        )
        decision, reason = _route_decision_for_source_image(
            conn, source_image_id=sid, kind=kind, is_lot_suspected=bool(r["is_lot_suspected"])
        )
        if decision != r["route_decision"]:
            n_route_flipped += 1
        # Chirurgical : on ne RE-ROUTE que le cas qui nous intéresse — un single
        # déjà en review qui devient lot avec la nouvelle classification. On NE
        # touche PAS aux pending ni au drift pending↔review (hors périmètre).
        if r["route_decision"] == "review_single" and decision == "review_lot":
            flips.append((sid, r["listing_title"]))
            if args.apply:
                conn.execute(
                    "UPDATE source_images SET route_decision=?, route_reason=? WHERE id=?",
                    (decision, reason, sid),
                )
                # Aligner review_queue.kind sur le nouveau kind (run_enqueue ne
                # met pas à jour les rows déjà en file → on le fait ici).
                cur = conn.execute(
                    "UPDATE review_queue SET kind=? WHERE image_asset_id IN "
                    "(SELECT id FROM image_assets WHERE source_image_id=?)",
                    (kind, sid),
                )
                n_rq_updated += cur.rowcount

    if args.apply:
        conn.commit()

    print(f"cohorte {args.cohort} — {len(rows)} annonces")
    print(f"  listing_kind recalculé (changé) : {n_kind_changed}")
    print(f"  route_decision flippé            : {n_route_flipped}")
    print(f"  dont review_single -> review_lot : {len(flips)}")
    print(f"  review_queue.kind mis à jour     : {n_rq_updated}")
    print(f"  mode : {'APPLY (écrit)' if args.apply else 'DRY-RUN'}")
    for sid, title in flips[:15]:
        print(f"    {sid[:10]} :: {(title or '')[:62]}")


if __name__ == "__main__":
    main()
