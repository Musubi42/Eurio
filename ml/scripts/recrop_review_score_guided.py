"""Re-crop score-guided des crops de la FILE DE REVIEW (lane manual) mal cadrés.

Beaucoup de crops en review manuelle sont sous-croppés (bimétal : la détection accroche le
motif central). Cette passe repart du cercle stocké (bbox actuelle) comme HINT et cherche, par
balayage de rayon scoré par la probe gelée (stratégie A, `vision/score_recover.search_best_crop`),
le crop pièce-entière. On **remplace seulement si c'est franchement mieux** : le crop courant
sert de baseline → un crop déjà bon n'est pas touché. Re-Dino les crops changés (suggestions
à jour).

Réutilise le chemin de remplacement de `recrop_ebay_refine` (overwrite même storage_path :
cache + MinIO + DB bbox/method/phash ; eurio_id / resolution_status PRÉSERVÉS).

Gardes : SAUTE les images multi-pièces (lots → recrop_lots_per_coin), saute `score_recover`
(déjà bons), ne remplace que si `score ≥ floor` ET `score − baseline ≥ margin`.

Usage (depuis ml/, venv) ::
    .venv/bin/python -m scripts.recrop_review_score_guided                 # DRY-RUN (compte)
    .venv/bin/python -m scripts.recrop_review_score_guided --limit 30      # dry sur N
    .venv/bin/python -m scripts.recrop_review_score_guided --commit        # écrit
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import cv2

_ML = Path(__file__).resolve().parents[1]
if str(_ML) not in sys.path:
    sys.path.insert(0, str(_ML))

from sources._base.phash import compute_phash  # noqa: E402
from store import Store  # noqa: E402
from vision.score_recover import search_best_crop  # noqa: E402

_CACHE = Path.home() / ".cache" / "eurio"
_REPLACE_FLOOR = 0.55   # le crop retenu doit passer le gate (pièce entière valide)
_REPLACE_MARGIN = 0.12  # et battre le crop courant d'au moins ça (sinon on n'y touche pas)


def _hint_from_bbox(bbox_json: str) -> dict | None:
    try:
        b = json.loads(bbox_json)
        return {"cx": b["x"] + b["w"] / 2.0, "cy": b["y"] + b["h"] / 2.0,
                "r_final": min(b["w"], b["h"]) / 2.0}
    except (json.JSONDecodeError, KeyError, TypeError):
        return None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--commit", action="store_true", help="Écrit (sinon dry-run).")
    ap.add_argument("--limit", type=int, default=0, help="Max assets (0 = tous).")
    ap.add_argument("--lane", default="manual", help="Lane review_queue ciblée (défaut manual).")
    ap.add_argument("--margin", type=float, default=_REPLACE_MARGIN)
    ap.add_argument("--floor", type=float, default=_REPLACE_FLOOR)
    args = ap.parse_args()

    from shared.storage.local_cache import local_path, upload_through

    store = Store(_ML / "state" / "eurio.db")
    conn = store._connection()
    rows = conn.execute(
        """
        SELECT a.id aid, a.storage_path crop_sp, a.bbox_json, a.detection_method method0,
               si.storage_path raw_key
          FROM review_queue rq
          JOIN image_assets a   ON a.id = rq.image_asset_id
          JOIN source_images si ON si.id = a.source_image_id
         WHERE rq.status = 'open' AND rq.lane = ?
           AND si.source = 'ebay' AND a.storage_status = 'present'
           AND a.detection_method <> 'score_recover'
           AND a.bbox_json IS NOT NULL AND si.storage_path IS NOT NULL
           -- garde multi-pièces : ne jamais grossir un crop de lot/coffret
           AND (SELECT COUNT(*) FROM image_assets a2
                 WHERE a2.source_image_id = a.source_image_id
                   AND a2.storage_status = 'present') < 2
         ORDER BY a.id
        """,
        (args.lane,),
    ).fetchall()

    n = {"seen": 0, "skip_noraw": 0, "skip_nohint": 0, "skip_nocrop": 0,
         "kept_good": 0, "replaced": 0, "minio_fail": 0, "redino": 0}
    deltas = []
    t0 = time.time()
    changed_paths: list[tuple[str, Path]] = []

    for r in rows:
        if args.limit and n["seen"] >= args.limit:
            break
        n["seen"] += 1
        hint = _hint_from_bbox(r["bbox_json"])
        if hint is None:
            n["skip_nohint"] += 1
            continue
        try:
            raw_p = local_path("enrichment-raws", r["raw_key"])
        except Exception:
            n["skip_noraw"] += 1
            continue
        bgr = cv2.imread(str(raw_p))
        if bgr is None:
            n["skip_noraw"] += 1
            continue
        best = search_best_crop(bgr, hint)
        if best is None or best["result"].image is None:
            n["skip_nocrop"] += 1
            continue
        improved = (best["score"] >= args.floor
                    and best["score"] - best["baseline_score"] >= args.margin)
        if not improved:
            n["kept_good"] += 1
            continue
        n["replaced"] += 1
        deltas.append(round(best["score"] - best["baseline_score"], 3))
        if not args.commit:
            continue

        res = best["result"]
        cp = _CACHE / "enrichment-crops" / r["crop_sp"]
        cp.parent.mkdir(parents=True, exist_ok=True)
        ok, buf = cv2.imencode(".png", res.image)
        if not ok:
            n["skip_nocrop"] += 1
            continue
        cp.write_bytes(buf.tobytes())
        try:
            upload_through("enrichment-crops", r["crop_sp"], buf.tobytes())
        except Exception:
            n["minio_fail"] += 1
        bbox = {"x": float(res.cx - res.r), "y": float(res.cy - res.r),
                "w": float(2 * res.r), "h": float(2 * res.r)}
        method0 = r["method0"] or ""
        new_method = method0 + "+scorerefine" if "scorerefine" not in method0 else method0
        conn.execute(
            "UPDATE image_assets SET bbox_json=?, detection_method=?, width=?, height=?, "
            "phash=? WHERE id=?",
            (json.dumps(bbox), new_method, res.image.shape[1], res.image.shape[0],
             compute_phash(res.image), r["aid"]),
        )
        changed_paths.append((r["aid"], cp))
        if n["replaced"] % 50 == 0:
            print(f"  {n['replaced']} remplacés ({time.time() - t0:.0f}s)", flush=True)

    # Re-Dino les crops changés (suggestions à jour pour la review).
    if args.commit and changed_paths:
        from sources._base.steps.auto_validate import predict_and_persist_one
        print(f"\n[redino] {len(changed_paths)} crops changés…", flush=True)
        for aid, cp in changed_paths:
            try:
                if predict_and_persist_one(store=store, asset_id=aid, crop_path=cp,
                                           anchors_kind="2eur_all") is not None:
                    n["redino"] += 1
            except Exception:
                pass

    mode = "COMMIT" if args.commit else "DRY-RUN"
    import statistics as st
    med = st.median(deltas) if deltas else 0.0
    print(f"\n[{mode}] {n}")
    print(f"améliorations (score−baseline) : n={len(deltas)} médiane=+{med:.3f}")
    print(f"durée {time.time() - t0:.0f}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
