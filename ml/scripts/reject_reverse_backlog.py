"""Rejette les crops de la file OUVERTE déjà étiquetés `face='reverse'`.

POURQUOI, ET POURQUOI SÉPARÉMENT DE `recompute_faces`
------------------------------------------------------
`recompute_faces.py` corrige l'ÉTIQUETTE. Il ne touche pas au ROUTAGE : le rejet
`face_reverse` se fait à l'enqueue, jamais rétroactivement
(`sources/_base/steps/auto_validate.py`, en toutes lettres), et `list_queue`
n'a aucun prédicat sur `face`. Mesuré au canonique le 2026-08-27, juste après la
passe : **1 052 crops ouverts étiquetés `reverse`**, file totale **inchangée** —
ils étaient toujours servis à l'humain. Un revers commun ne ressemble à aucun
avers national : le trancher est du temps perdu à coup sûr.

CE QU'IL RÉUTILISE, ET CE QU'IL NE RÉÉCRIT PAS
-----------------------------------------------
`store.review_routing` — les trois helpers de `steps/enqueue`, descendus là le
2026-08-27 précisément pour être atteignables depuis l'image lean du VPS. Aucune
règle de rejet n'est réécrite ici : ce serait une seconde copie, libre de
diverger.

LES DEUX STICKY QU'IL ÉPARGNE, ET C'EST LE CŒUR DE SA PRUDENCE
----------------------------------------------------------------
  · un crop dont `resolution_status` n'est plus `needs_review` — déjà tranché
    par un humain ou par le consensus ;
  · un crop dont la row review_queue porte `decision_notes = 'restored'` —
    ré-ouvert À LA MAIN. Mesuré : 8 au canonique. Les écraser effacerait un
    geste humain délibéré, c'est-à-dire la seule donnée qu'aucun calcul ne
    régénère.

Le rejet est **ré-ouvrable** (`/restore`), comme celui de l'enqueue.

USAGE
-----
    python -m scripts.reject_reverse_backlog                 # dry-run
    python -m scripts.reject_reverse_backlog --apply

⚠️ DIRECTION A — se joue AU CANONIQUE. Sur Mac/PC la base est une réplique
read-only et l'autopull écraserait l'écriture. Lis `.claude/skills/eurio-data-writes`.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from collections import Counter
from pathlib import Path

ML_DIR = Path(__file__).resolve().parents[1]
if str(ML_DIR) not in sys.path:
    sys.path.insert(0, str(ML_DIR))

from store.review_routing import (  # noqa: E402
    kind_for_source_image,
    reject_crop_terminal,
    route_decision_for_source_image,
)

_ENGINE_VERSION = "face_backlog@tau0.0-2026-08-27"

_SQL = """
SELECT rq.id                 AS review_id,
       a.id                  AS asset_id,
       a.source_image_id     AS sid,
       a.resolution_status   AS statut,
       rq.decision_notes     AS notes,
       si.is_lot_suspected   AS lot_suspecte
  FROM review_queue rq
  JOIN image_assets a   ON a.id = rq.image_asset_id
  JOIN source_images si ON si.id = a.source_image_id
 WHERE rq.status = 'open'
   AND a.face = 'reverse'
"""


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--apply", action="store_true",
                    help="écrit (défaut : dry-run, aucune écriture)")
    ap.add_argument("--db", default=str(ML_DIR / "state" / "eurio.replica.db"))
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args(argv)

    uri = f"file:{args.db}" + ("" if args.apply else "?mode=ro")
    conn = sqlite3.connect(uri, uri=True)
    conn.row_factory = sqlite3.Row

    rows = conn.execute(_SQL).fetchall()
    epargnes: Counter = Counter()
    a_rejeter = []
    for r in rows:
        if r["statut"] != "needs_review":
            epargnes[f"deja_tranche({r['statut']})"] += 1
            continue
        if (r["notes"] or "") == "restored":
            epargnes["restaure_a_la_main"] += 1
            continue
        a_rejeter.append(r)
    if args.limit:
        a_rejeter = a_rejeter[: args.limit]

    sids = {r["sid"] for r in a_rejeter}
    print(json.dumps({
        "ouverts_reverse": len(rows),
        "a_rejeter": len(a_rejeter),
        "epargnes": dict(epargnes),
        "listings_a_rerouter": len(sids),
        "mode": "APPLIQUÉ" if args.apply else "dry-run (rien écrit)",
    }, ensure_ascii=False, indent=1))

    if not args.apply:
        print("\ndry-run — relance avec --apply.")
        return 0

    for r in a_rejeter:
        reject_crop_terminal(
            conn, asset_id=r["asset_id"], review_id=r["review_id"],
            quality_reason="face_reverse", decided_by="pipeline",
            state_reason="face_reverse", engine_version=_ENGINE_VERSION,
            decision_payload={"reason": "face_reverse", "backlog": True},
            target_eurio_id=None, run_id=None,
        )
    n_reroute = 0
    for sid in sids:
        kind = kind_for_source_image(
            conn, source_image_id=sid, is_lot_suspected=False)
        decision, reason = route_decision_for_source_image(
            conn, source_image_id=sid, kind=kind, is_lot_suspected=False)
        conn.execute(
            "UPDATE source_images SET route_decision=?, route_reason=? WHERE id=?",
            (decision, reason, sid),
        )
        n_reroute += 1
    conn.commit()
    print(f"\n{len(a_rejeter)} crops rejetés, {n_reroute} listings re-routés.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
