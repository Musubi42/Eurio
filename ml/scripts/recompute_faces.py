"""Recalcule `image_assets.face` depuis la marge déjà stockée — dry-run par défaut.

POURQUOI CE SCRIPT EXISTE
-------------------------
Le seuil de face (`FACE_REVERSE_TAU`) est passé de 0,065 à 0,0 le 2026-08-27,
après re-mesure du banc sur le gold de juin : la marge maximale des 514 avers
confirmés est **−0,0507**, donc l'ancien seuil ne rachetait aucun faux positif
et coûtait 13 points de rappel dur et 20 points de rappel facile.

Mais changer le seuil ne suffit pas : la face n'était écrite qu'une fois
(`WHERE face IS NULL`). Sans cette passe, le nouveau seuil ne vaudrait que pour
les crops FUTURS, et les crops déjà en file garderaient une étiquette décidée
sous l'ancien seuil. C'est cette passe qui convertit le correctif en effet.

CE QU'IL NE FAIT PAS
--------------------
Il ne ré-encode RIEN. `face_margin` est déjà en base
(`image_asset_dino_predictions`), calculée à la prédiction. On relit une
colonne et on ré-applique une comparaison — quelques secondes, pas 40 minutes
de MPS. ⚠️ Corollaire : cette passe ne corrige pas la marge, seulement le
verdict qu'on en tire. Une marge périmée (banque rebâtie depuis la prédiction)
reste périmée ; c'est le backfill de prédictions qui la rafraîchit.

⛔ LES VERDICTS HUMAINS NE SONT JAMAIS TOUCHÉS — `face_source='human'`
(migration 0017). Le prédicat est dans le SQL, pas dans une intention.

USAGE
-----
    python -m scripts.recompute_faces                 # dry-run, ne touche rien
    python -m scripts.recompute_faces --apply         # écrit (Direction A : voir plus bas)

⚠️ DIRECTION A. Sur Mac/PC la base est une RÉPLIQUE read-only : `--apply` y
échouera en « attempt to write a readonly database », et même s'il passait,
l'autopull écraserait l'écriture en moins de deux minutes. Cette passe se joue
**au canonique**, ou via la route d'ingest. Lis `.claude/skills/eurio-data-writes`.
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

from shared.verdict_scope import (  # noqa: E402
    VERDICT_ANCHORS_KIND,
    VERDICT_ENCODER_VERSION,
)
# `shared.face_rule` et pas `steps.auto_validate` : stdlib pure, donc ce script
# tourne AUSSI dans l'image lean du VPS (pas de cv2, pas de torch). C'est là que
# la passe doit se jouer — le canonique est le seul writer.
from shared.face_rule import FACE_REVERSE_TAU, decide_face  # noqa: E402

# On relit la marge telle quelle : `decide_face` prend (reverse_sim,
# obverse_sim) et n'utilise que leur différence. Passer (marge, 0.0) fait
# donc travailler LA fonction de production, pas une copie de sa règle —
# c'est ce qui garantit qu'un changement de règle ne peut pas diverger ici.
_SQL = """
SELECT a.id                AS asset_id,
       a.face              AS face_actuelle,
       a.face_source       AS provenance,
       p.face_margin       AS marge,
       rq.status           AS statut_review
  FROM image_assets a
  JOIN image_asset_dino_predictions p
       ON p.asset_id = a.id
      AND p.encoder_version = ?
      AND p.anchors_kind    = ?
  LEFT JOIN review_queue rq ON rq.image_asset_id = a.id
 WHERE p.face_margin IS NOT NULL
   AND (a.face_source IS NULL OR a.face_source = 'pipeline')
"""


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--apply", action="store_true",
                    help="écrit (défaut : dry-run, aucune écriture)")
    ap.add_argument("--db", default=str(ML_DIR / "state" / "eurio.replica.db"))
    ap.add_argument("--limit", type=int, default=0, help="plafonne (0 = tous)")
    args = ap.parse_args(argv)

    uri = f"file:{args.db}" + ("" if args.apply else "?mode=ro")
    conn = sqlite3.connect(uri, uri=True)
    conn.row_factory = sqlite3.Row

    rows = conn.execute(_SQL, (VERDICT_ENCODER_VERSION, VERDICT_ANCHORS_KIND)).fetchall()
    if args.limit:
        rows = rows[: args.limit]

    transitions: Counter = Counter()
    ouverts_liberes = 0
    a_ecrire: list[tuple[str, str]] = []
    for r in rows:
        neuf = decide_face(float(r["marge"]), 0.0)
        ancien = r["face_actuelle"]
        if neuf == ancien:
            continue
        transitions[(ancien, neuf)] += 1
        if neuf == "reverse" and r["statut_review"] == "open":
            ouverts_liberes += 1
        a_ecrire.append((neuf, r["asset_id"]))

    print(json.dumps({
        "seuil": FACE_REVERSE_TAU,
        "examines": len(rows),
        "a_changer": len(a_ecrire),
        "transitions": {f"{a or 'NULL'}->{b}": n for (a, b), n in transitions.items()},
        "crops_ouverts_qui_sortent_de_la_file": ouverts_liberes,
        "mode": "APPLIQUÉ" if args.apply else "dry-run (rien écrit)",
    }, ensure_ascii=False, indent=1))

    if not args.apply:
        print("\ndry-run — relance avec --apply pour écrire, "
              "et lis d'abord `.claude/skills/eurio-data-writes`.")
        return 0

    conn.executemany(
        "UPDATE image_assets SET face = ?, face_source = 'pipeline' "
        " WHERE id = ? AND (face_source IS NULL OR face_source = 'pipeline')",
        a_ecrire,
    )
    conn.commit()
    print(f"\n{len(a_ecrire)} faces réécrites.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
