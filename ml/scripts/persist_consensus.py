"""Backfill SHADOW de la table ``consensus_verdicts`` (auto-validation C3).

Calcule + persiste le verdict de consensus (``review/validation/persist.py``)
sur un set d'assets, **sans toucher la décision de routage live** (review_queue,
discarded_listings). C'est l'étape « persister » du redesign : la table existe et
se peuple, mais le pipeline n'en dépend pas encore (câblage = chunk suivant).

Dry-run par défaut (compte les outcomes, n'écrit rien) ; ``--apply`` pour écrire.
Idempotent : REPLACE sur ``(image_asset_id, rule_version)``.

    python scripts/persist_consensus.py --scope dino           # preview (2eur_commemo)
    python scripts/persist_consensus.py --scope gold --apply    # écrit le gold (501)
    python scripts/persist_consensus.py --scope contradict      # ex-contradicts tués

Scopes :
  - ``dino``       : tous les assets avec une prédiction DINO 2eur_commemo
                     (population verdict-calculable, = baseline shadow/gold).
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
from review.validation.experts import collect_signals
from review.validation.persist import upsert_consensus_verdict
from review.validation.replay import DEFAULT_GOLD, load_gold

_DB = Path(__file__).resolve().parents[1] / "state" / "eurio.db"

_SCOPE_SQL = {
    "dino": (
        "SELECT DISTINCT asset_id FROM image_asset_dino_predictions "
        "WHERE anchors_kind='2eur_commemo'"
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
    return [r[0] for r in conn.execute(_SCOPE_SQL[scope])]


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--db", type=Path, default=_DB)
    ap.add_argument("--scope", choices=["dino", "gold", "contradict"], default="dino")
    ap.add_argument("--gold", type=Path, default=DEFAULT_GOLD)
    ap.add_argument("--apply", action="store_true", help="écrit (sinon dry-run)")
    args = ap.parse_args()

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

    for aid in asset_ids:
        signals = collect_signals(conn, aid)
        if not signals:
            n_no_signal += 1
            continue
        cv = consensus_verdict(signals)
        outcomes[cv.outcome] += 1
        by_rule[cv.rule] += 1
        if args.apply:
            upsert_consensus_verdict(
                conn, aid, signals=signals, verdict=cv, commit=False
            )
            n_written += 1
    if args.apply:
        conn.commit()

    mode = "APPLY" if args.apply else "DRY-RUN"
    print(f"=== persist_consensus [{mode}] scope={args.scope} rule_version={RULE_VERSION} ===")
    print(f"  assets ciblés      : {len(asset_ids)}")
    print(f"  sans signal (skip) : {n_no_signal}")
    print(f"  outcomes           : {dict(outcomes)}")
    print(f"  par règle          : {dict(by_rule)}")
    if args.apply:
        total = conn.execute(
            "SELECT COUNT(*) FROM consensus_verdicts WHERE rule_version=?",
            (RULE_VERSION,),
        ).fetchone()[0]
        print(f"  rows écrites       : {n_written}")
        print(f"  total en table     : {total} (rule_version={RULE_VERSION})")
    else:
        print("  (dry-run — rien écrit ; --apply pour persister)")


if __name__ == "__main__":
    main()
