"""Récupère les `zero_crops` d'un run eBay par crop score-guided (stratégie A).

Réutilise INTÉGRALEMENT le chemin d'écriture de prod : on rappelle `run_detect_crop` sur les
source_images en `crop_status='zero_crops'`, avec la passe de secours `EURIO_CENSUS_RECOVER=1`
active (cf. `vision/score_recover.py` + `normalize_listing_with_detections`). Les crops
récupérés sont persistés (image_assets + crop MinIO + phash/dedup + state events +
`crop_status='success'`) comme n'importe quel crop — aucune écriture SQL custom.

Usage (depuis ml/, venv) ::

    .venv/bin/python -m scripts.recrop_zero_score_guided --dry          # aperçu
    .venv/bin/python -m scripts.recrop_zero_score_guided                # exécute
    .venv/bin/python -m scripts.recrop_zero_score_guided --limit 20     # test sur N
    .venv/bin/python -m scripts.recrop_zero_score_guided --run <run_id> # autre run

Coût = K appels probe / image (Mac CPU : ~quelques s/image). Les images non récupérables
(coincard/proof/tilt) restent `zero_crops` (pas de dégradation). Écriture DIRECTE en DB
(décision PO) : les ~4% de faux d'A (fragments forcés ≥ τ) sont à nettoyer en review ensuite.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

_ML_DIR = Path(__file__).resolve().parents[1]
if str(_ML_DIR) not in sys.path:
    sys.path.insert(0, str(_ML_DIR))

from sources._base.run_logger import start_run  # noqa: E402
from sources._base.steps.detect_crop import run_detect_crop  # noqa: E402
from store import Store  # noqa: E402

_SOURCE_ID = "ebay"
_DEFAULT_RUN = "fa8a9af939ce43e6a3eee6842ecae170"  # dernier run (cf. banc crop-recovery)


def _list_zero_crops(conn, run_id: str) -> dict[str, str]:
    rows = conn.execute(
        """
        SELECT id, source_ref FROM source_images
         WHERE source = ? AND run_id = ? AND crop_status = 'zero_crops'
           AND download_status = 'success' AND storage_path IS NOT NULL
         ORDER BY fetched_at ASC
        """,
        (_SOURCE_ID, run_id),
    ).fetchall()
    return {r["source_ref"]: r["id"] for r in rows}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", default=_DEFAULT_RUN, help="run_id à traiter")
    ap.add_argument("--dry", action="store_true", help="aperçu, aucune écriture")
    ap.add_argument("--limit", type=int, default=None, help="traiter au plus N source_images")
    args = ap.parse_args()

    db_path = _ML_DIR / "state" / "eurio.db"
    if not db_path.is_file():
        print(f"ERROR: DB introuvable: {db_path}", file=sys.stderr)
        return 1

    store = Store(db_path)
    conn = store._connection()

    targets = _list_zero_crops(conn, args.run)
    if args.limit is not None:
        targets = dict(list(targets.items())[: args.limit])

    print(f"[recover] run={args.run[:12]}… · {len(targets)} zero_crops à tenter")
    if not targets:
        print("[recover] rien à faire.")
        return 0
    if args.dry:
        for sref in list(targets)[:10]:
            print(f"  would recover: {sref}")
        if len(targets) > 10:
            print(f"  … et {len(targets) - 10} de plus")
        return 0

    # Active la passe de secours score-guided (OFF en prod par défaut, R0).
    os.environ["EURIO_CENSUS_RECOVER"] = "1"

    with start_run(conn, source=_SOURCE_ID, kind="reset",
                   filters={"reason": "score-guided zero_crops recovery",
                            "n_targets": len(targets), "src_run": args.run}) as run:
        run.set_step("detect")
        result = run_detect_crop(conn=conn, run=run, source_id=_SOURCE_ID,
                                 source_image_ids=targets)
        run.end("success")

    # Récupérées = parmi les cibles, celles qui ne sont plus en zero_crops.
    remaining = set(_list_zero_crops(conn, args.run).values())
    recovered = sum(1 for sid in targets.values() if sid not in remaining)
    print(f"\n[recover] done · crops_added={result.n_crops_added} errors={result.n_errors} "
          f"auto_phash={result.n_auto_phash}")
    print(f"[recover] récupérées = {recovered}/{len(targets)} cibles "
          f"({100 * recovered / len(targets):.0f}%) · zero_crops restants sur le run = "
          f"{len(remaining)} (non récupérables : coincard/proof/tilt)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
