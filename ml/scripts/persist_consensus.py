"""Backfill SHADOW de la table ``consensus_verdicts`` (auto-validation C3).

Calcule + persiste le verdict de consensus (``review/validation/persist.py``)
sur un set d'assets, **sans toucher la décision de routage live** (review_queue,
discarded_listings). C'est l'étape « persister » du redesign : la table existe et
se peuple, mais le pipeline n'en dépend pas encore (câblage = chunk suivant).

Dry-run par défaut (compte les outcomes, n'écrit rien) ; ``--apply`` pour écrire.
Idempotent : REPLACE sur ``(image_asset_id, rule_version)``.

    python scripts/persist_consensus.py --scope dino            # preview (banque du verdict)
    python scripts/persist_consensus.py --scope open            # preview des ouverts
    python scripts/persist_consensus.py --scope gold --apply    # écrit le gold (501)
    python scripts/persist_consensus.py --scope contradict      # ex-contradicts tués

Scopes :
  - ``dino``       : tous les assets avec une prédiction DINO dans la banque du
                     VERDICT (population verdict-calculable, = baseline
                     shadow/gold).
  - ``open``       : les items de review encore ouverts, et eux seuls.
  - ``gold``       : les assets du gold de replay (verdict_gold.jsonl).
  - ``contradict`` : les crops des listings tués pour text_contradict_* (cf.
                     scripts/contradict_rescue.py — rescue mesuré).
"""

from __future__ import annotations

import argparse
import sqlite3
from collections import Counter
from pathlib import Path

from review.validation.consensus import RULE_VERSION, consensus_verdict
from shared.verdict_scope import VERDICT_ANCHORS_KIND
from review.validation.experts import collect_signals
from client.ingest import push_consensus
from review.validation.persist import _signals_json, upsert_consensus_verdict
from review.validation.replay import DEFAULT_GOLD, load_gold
from store import resolve_db_path

_DB = resolve_db_path(Path(__file__).resolve().parents[1] / "state" / "eurio.db")

_SCOPE_SQL = {
    # ⛔ Portait `'2eur_commemo'` en dur jusqu'au 2026-08-24 : le scope « tous
    # les assets verdict-calculables » désignait alors la banque que le verdict
    # ne lit plus, donc une population qui n'a plus rien à voir. Quatrième site
    # de la même famille, cf. `shared/verdict_scope.py`.
    "dino": (
        "SELECT DISTINCT asset_id FROM image_asset_dino_predictions "
        "WHERE anchors_kind = :kind"
    ),
    # B3 de la bascule : les items encore OUVERTS, et eux seuls. Les items déjà
    # tranchés gardent leur verdict d'alors — c'est la trace de ce que le modèle
    # disait au moment où un humain a décidé, et la réécrire serait réécrire
    # l'histoire.
    "open": (
        "SELECT DISTINCT rq.image_asset_id FROM review_queue rq "
        "  JOIN image_asset_dino_predictions p "
        "    ON p.asset_id = rq.image_asset_id AND p.anchors_kind = :kind "
        " WHERE rq.status = 'open'"
    ),
    "contradict": (
        "SELECT DISTINCT ia.id "
        "  FROM discarded_listings d "
        "  JOIN source_images si ON si.source=d.source AND si.source_ref=d.source_ref "
        "  JOIN image_assets ia ON ia.source_image_id=si.id "
        " WHERE d.reason LIKE 'text_contradict_%'"
    ),
}


def _asset_ids(conn: sqlite3.Connection, scope: str, gold_path: Path) -> list[str]:
    if scope == "gold":
        return [g.asset_id for g in load_gold(gold_path)]
    return [r[0] for r in conn.execute(
        _SCOPE_SQL[scope], {"kind": VERDICT_ANCHORS_KIND})]


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--db", type=Path, default=_DB)
    ap.add_argument(
        "--scope", choices=["dino", "open", "gold", "contradict"], default="dino")
    ap.add_argument("--gold", type=Path, default=DEFAULT_GOLD)
    ap.add_argument("--apply", action="store_true", help="écrit (sinon dry-run)")
    ap.add_argument(
        "--no-push", action="store_true",
        help="écrit dans la base LOCALE au lieu de pousser au canonique "
             "(n'a de sens que sur le host canonique)")
    ap.add_argument(
        "--batch", type=int, default=500,
        help="taille des lots poussés (défaut 500)")
    args = ap.parse_args()

    # ── Où atterrissent les lignes ──────────────────────────────────────────
    #
    # Sous Direction A, l'écriture locale est impossible (réplique read-only) et
    # le VPS ne peut pas calculer (l'image lean n'embarque pas `training/`). Le
    # calcul reste donc ICI et les lignes partent par POST — le même chemin que
    # les crops, les faces et les prédictions Dino.
    #
    # C'est ce qui bloquait le lot B3 de la bascule de banque : sans cette voie,
    # un recalcul de consensus n'avait aucun endroit où atterrir.
    from store import resolve_db_readonly

    push = False
    if args.apply:
        if args.no_push and resolve_db_readonly():
            raise SystemExit(
                "DB en lecture seule (réplique Direction A) et --no-push : "
                "aucune destination. Retire --no-push pour pousser au canonique, "
                "ou lance ceci sur le host canonique avec EURIO_DB_READONLY=0."
            )
        if not args.no_push:
            from client.http import sync_enabled

            if not sync_enabled():
                raise SystemExit(
                    "EURIO_API_URL absent : impossible de pousser au canonique. "
                    "Charge le devShell, ou ajoute --no-push pour écrire en local."
                )
            push = True

    # Garantit que ``consensus_verdicts`` existe (bootstrap schema, idempotent) —
    # la table est nouvelle, la DB live ne l'a pas tant qu'aucun Store n'a démarré.
    from store import StoreBase

    StoreBase(args.db)

    conn = sqlite3.connect(args.db)
    conn.row_factory = sqlite3.Row  # _resolve_signals lit les colonnes par nom
    asset_ids = _asset_ids(conn, args.scope, args.gold)

    outcomes: Counter = Counter()
    by_rule: Counter = Counter()
    n_written = 0
    n_no_signal = 0
    a_pousser: list[dict] = []
    manquants: list[str] = []

    def _flush(lot: list[dict]) -> int:
        """Pousse un lot et RETIENT les refus. Un `missing` non lu, c'est une
        écriture qu'on croit faite — la faute que ce dépôt collectionne."""
        if not lot:
            return 0
        res = push_consensus(lot) or {}
        manquants.extend(res.get("missing") or [])
        n = int(res.get("written") or 0)
        print(f"  … poussé {n}/{len(lot)}", flush=True)
        lot.clear()
        return n

    for aid in asset_ids:
        signals = collect_signals(conn, aid)
        if not signals:
            n_no_signal += 1
            continue
        cv = consensus_verdict(signals)
        outcomes[cv.outcome] += 1
        by_rule[cv.rule] += 1
        if not args.apply:
            continue
        if push:
            a_pousser.append({
                "image_asset_id": aid,
                "rule_version": RULE_VERSION,
                "outcome": cv.outcome,
                "lane": cv.lane,
                "confidence": cv.confidence,
                "reason": cv.reason,
                "rule": cv.rule,
                "signals_json": _signals_json(signals),
            })
            if len(a_pousser) >= args.batch:
                n_written += _flush(a_pousser)
        else:
            upsert_consensus_verdict(
                conn, aid, signals=signals, verdict=cv, commit=False
            )
            n_written += 1

    if args.apply:
        if push:
            n_written += _flush(a_pousser)
        else:
            conn.commit()

    mode = "APPLY" if args.apply else "DRY-RUN"
    print(f"=== persist_consensus [{mode}] scope={args.scope} rule_version={RULE_VERSION} ===")
    print(f"  assets ciblés      : {len(asset_ids)}")
    print(f"  sans signal (skip) : {n_no_signal}")
    print(f"  outcomes           : {dict(outcomes)}")
    print(f"  par règle          : {dict(by_rule)}")
    if args.apply:
        dest = "canonique (POST /ingest/consensus)" if push else "base locale"
        print(f"  destination        : {dest}")
        print(f"  rows écrites       : {n_written}")
        if manquants:
            print(f"  ⚠️  REFUSÉS (assets inconnus du canonique) : {len(manquants)}")
            print(f"      {manquants[:5]}{' …' if len(manquants) > 5 else ''}")
        if not push:
            total = conn.execute(
                "SELECT COUNT(*) FROM consensus_verdicts WHERE rule_version=?",
                (RULE_VERSION,),
            ).fetchone()[0]
            print(f"  total en table     : {total} (rule_version={RULE_VERSION})")
    else:
        print("  (dry-run — rien écrit ; --apply pour persister)")


if __name__ == "__main__":
    main()
