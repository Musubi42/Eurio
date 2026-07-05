"""Mesure LABEL-FREE du « rim over-fit » (le crop accroche un motif interne au
lieu du rebord) sur un run eBay — par étage du pipeline de détection.

Insight : la bbox YOLO borne la pièce ENTIÈRE (modèle entraîné sur des pièces),
donc son rayon inscrit `r_bbox = min(bw, bh)/2` est une référence du « vrai rayon ».
Un crop qui sur-ajuste un motif interne a `r_final / r_bbox` nettement < 1.

Contrairement à `measure_fragment_gate` (qui mesure le SYMPTÔME aval = scores du
gate vs τ et exige un œil humain pour juger le crop), ce script mesure la CAUSE
directement et sans label :

  - distribution de `r_final / r_bbox` (taux d'undercrop, seuil configurable) ;
  - décomposition par ÉTAGE (bbox → hough refine → polish → rim-refine) : à quel
    étage le rayon s'effondre, et de combien (médiane du ratio inter-étage) ;
  - corrélation undercrop ↔ score du gate (un crop tronqué doit scorer bas) ;
  - montage avant/après pour vérif visuelle des pires undercrops.

LECTURE SEULE sur la DB. Utilise le VRAI chemin de prod (`detect_circles_multi`
avec son hook `trace`), donc aucune dérive vis-à-vis du pipeline réel.

Usage : .venv/bin/python -m scripts.measure_crop_undercrop --run <run_id>
        [--max-imgs N] [--undercrop 0.85] [--min-bbox-frac 0.0] [--no-score]
"""

from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path

import numpy as np

ML_DIR = Path(__file__).resolve().parent.parent

from store import resolve_db_path  # noqa: E402

DB_PATH = resolve_db_path(ML_DIR / "state" / "eurio.db")
OUT_DIR = ML_DIR / "state" / "crop_undercrop"


def _pct(a: np.ndarray) -> str:
    return (f"p10={np.percentile(a, 10):.2f} p25={np.percentile(a, 25):.2f} "
            f"p50={np.percentile(a, 50):.2f} p75={np.percentile(a, 75):.2f} "
            f"p90={np.percentile(a, 90):.2f}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", required=True)
    ap.add_argument("--max-imgs", type=int, default=None)
    ap.add_argument("--undercrop", type=float, default=0.85,
                    help="seuil r_final/r_bbox sous lequel on compte un undercrop")
    ap.add_argument("--min-bbox-frac", type=float, default=0.0,
                    help="ne garder que les bboxes dont r_bbox/short ≥ ce seuil "
                         "(filtre le bruit texte/motif ; 0 = tout garder)")
    ap.add_argument("--status", default="zero_crops",
                    help="crop_status à analyser ('zero_crops' | 'success' | 'all')")
    ap.add_argument("--no-score", action="store_true",
                    help="ne pas calculer le score du gate (plus rapide, pas de corrélation)")
    ap.add_argument("--counterfactual", action="store_true", default=True,
                    help="scorer AUSSI un crop plein-rebord (r=r_bbox, centre bbox) pour "
                         "tester si un bon crop ferait repasser le gate (thèse du handoff)")
    ap.add_argument("--no-counterfactual", dest="counterfactual", action="store_false",
                    help="désactiver le contrefactuel plein-rebord (2× plus rapide)")
    ap.add_argument("--montage", default=str(OUT_DIR / "_worst_undercrop.png"))
    ap.add_argument("--debug-pairs", type=int, default=0,
                    help="sauver N lignes [raw+cercle | crop détecté (score) | crop plein (score)] "
                         "pour valider visuellement que le crop plein-rebord est bon")
    ap.add_argument("--dump", default=None, help="chemin JSON pour persister les records bruts")
    args = ap.parse_args()

    import cv2

    from shared.storage.local_cache import local_path
    from vision.census import face_scores
    from vision.normalize_snap import (
        CropConfig,
        _census_fragment_tau,
        _crop_mask_resize_int,
        detect_circles_multi,
    )

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    tau = _census_fragment_tau()
    cfg = CropConfig()

    conn = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    q = ("SELECT id, storage_path, listing_title, source_url, crop_status "
         "FROM source_images WHERE source='ebay' AND run_id=? AND storage_path IS NOT NULL")
    if args.status != "all":
        q += " AND crop_status=?"
        rows = conn.execute(q, (args.run, args.status)).fetchall()
    else:
        rows = conn.execute(q, (args.run,)).fetchall()
    if args.max_imgs:
        rows = rows[: args.max_imgs]
    print(f"{len(rows)} images ({args.status}) à analyser · τ_gate={tau} · "
          f"undercrop si r_final/r_bbox < {args.undercrop}\n")

    records: list[dict] = []
    worst_imgs: list[tuple[float, np.ndarray]] = []  # (ratio, crop) pour le montage
    debug_rows: list[np.ndarray] = []  # lignes [raw | détecté | plein] pour --debug-pairs

    for i, row in enumerate(rows):
        try:
            bgr = cv2.imread(str(local_path("enrichment-raws", row["storage_path"])), cv2.IMREAD_COLOR)
        except Exception:
            continue
        if bgr is None:
            continue
        short = min(bgr.shape[:2])
        trace: list[dict] = []
        detect_circles_multi(bgr, census=True, trace=trace)

        # Score du gate, par bbox ACCEPTÉE (passe le filtre rayon → atteint le gate).
        # On note DEUX crops du MÊME coin : (a) le crop de prod au r détecté, (b) le
        # crop contrefactuel plein-rebord (centre bbox, r=r_bbox). Comparaison pairée
        # = test direct de « un bon crop ferait-il repasser le gate ? ».
        score_det: dict[int, float] = {}
        score_full: dict[int, float] = {}
        if not args.no_score:
            crops, keys, kinds = [], [], []
            for k, t in enumerate(trace):
                if not t["accepted"]:
                    continue
                rd = _crop_mask_resize_int(bgr, t["cx"], t["cy"], int(t["r_final"]),
                                           method=t["method"], config=cfg)
                if rd.image is not None:
                    crops.append(rd.image); keys.append(k); kinds.append("det")
                if args.counterfactual and t["r_bbox"] > 0:
                    rfu = _crop_mask_resize_int(bgr, t["bcx"], t["bcy"], int(round(t["r_bbox"])),
                                                method="full_bbox", config=cfg)
                    if rfu.image is not None:
                        crops.append(rfu.image); keys.append(k); kinds.append("full")
            if crops:
                sc = face_scores(crops)
                for k, kind, s in zip(keys, kinds, sc):
                    (score_det if kind == "det" else score_full)[k] = float(s)

        # --- Montage de validation [raw+cercle | crop détecté | crop plein] ---
        if args.debug_pairs and len(debug_rows) < args.debug_pairs:
            big = [(k, t) for k, t in enumerate(trace)
                   if t["accepted"] and t["r_bbox"] / short > 0.18]
            if big:
                k, t = max(big, key=lambda kt: kt[1]["r_bbox"])  # le coin dominant
                cell = 200
                raw_th = cv2.resize(bgr, (cell, cell))
                cv2.circle(raw_th, (int(t["cx"] * cell / bgr.shape[1]),
                                    int(t["cy"] * cell / bgr.shape[0])),
                           max(2, int(t["r_final"] * cell / bgr.shape[1])), (0, 0, 255), 2)
                cv2.circle(raw_th, (int(t["bcx"] * cell / bgr.shape[1]),
                                    int(t["bcy"] * cell / bgr.shape[0])),
                           max(2, int(t["r_bbox"] * cell / bgr.shape[1])), (0, 255, 0), 2)
                rd = _crop_mask_resize_int(bgr, t["cx"], t["cy"], int(t["r_final"]),
                                           method=t["method"], config=cfg)
                rfu = _crop_mask_resize_int(bgr, t["bcx"], t["bcy"], int(round(t["r_bbox"])),
                                            method="full_bbox", config=cfg)
                det_th = cv2.resize(rd.image, (cell, cell)) if rd.image is not None else np.zeros((cell, cell, 3), np.uint8)
                full_th = cv2.resize(rfu.image, (cell, cell)) if rfu.image is not None else np.zeros((cell, cell, 3), np.uint8)
                sd_v = score_det.get(k); sf_v = score_full.get(k)
                cv2.putText(det_th, f"det r/bbox={t['r_final']/t['r_bbox']:.2f} s={sd_v:.2f}" if sd_v is not None else "det",
                            (4, 16), cv2.FONT_HERSHEY_SIMPLEX, 0.42, (0, 0, 255), 1)
                cv2.putText(full_th, f"full s={sf_v:.2f}" if sf_v is not None else "full",
                            (4, 16), cv2.FONT_HERSHEY_SIMPLEX, 0.42, (0, 255, 0), 1)
                debug_rows.append(np.hstack([raw_th, det_th, full_th]))

        for k, t in enumerate(trace):
            if t["r_bbox"] <= 0:
                continue
            if t["r_bbox"] / short < args.min_bbox_frac:
                continue
            rec = {
                **t,
                "img_id": row["id"],
                "short": short,
                "bbox_frac": round(t["r_bbox"] / short, 4),
                "ratio_final": round(t["r_final"] / t["r_bbox"], 4),
                "ratio_hough": round(t["r_hough"] / t["r_bbox"], 4),
                "ratio_polish_step": round(t["r_polish"] / max(1e-6, t["r_hough"]), 4),
                "ratio_rim_step": round(t["r_rim"] / max(1e-6, t["r_polish"]), 4),
                "score": score_det.get(k),
                "score_full": score_full.get(k),
                "listing_title": row["listing_title"],
                "source_url": row["source_url"],
            }
            records.append(rec)
            # Garder un crop des pires undercrops « gros » pour le montage.
            if (not args.no_score and rec["ratio_final"] < args.undercrop
                    and t["accepted"] and len(worst_imgs) < 48 and t["r_bbox"] / short > 0.12):
                res = _crop_mask_resize_int(bgr, t["cx"], t["cy"], int(t["r_final"]),
                                            method=t["method"], config=cfg)
                if res.image is not None:
                    worst_imgs.append((rec["ratio_final"], res.image))

        if (i + 1) % 25 == 0:
            print(f"  …{i + 1}/{len(rows)}  ({len(records)} bboxes)")

    if not records:
        print("Aucune bbox détectée — rien à mesurer.")
        return 0

    # ---- Agrégats -----------------------------------------------------------
    rf = np.array([r["ratio_final"] for r in records])
    rh = np.array([r["ratio_hough"] for r in records])
    rp = np.array([r["ratio_polish_step"] for r in records])
    rr = np.array([r["ratio_rim_step"] for r in records])
    bf = np.array([r["bbox_frac"] for r in records])
    n = len(records)

    print(f"\n{'='*68}\n{n} bboxes mesurées (sur {len(rows)} images)\n{'='*68}")
    print(f"\nr_final / r_bbox (1.0 = crop plein-rebord) :\n  {_pct(rf)}")
    print(f"  undercrop (<{args.undercrop}) : {int((rf < args.undercrop).sum())}/{n} "
          f"({100*(rf < args.undercrop).mean():.0f} %)")
    print(f"  sévère    (<0.70)         : {int((rf < 0.70).sum())}/{n} "
          f"({100*(rf < 0.70).mean():.0f} %)")

    print(f"\nDécomposition par étage (ratio appliqué à CHAQUE étage, médiane) :")
    print(f"  bbox → hough   r_hough/r_bbox        : {_pct(rh)}")
    print(f"  hough → polish r_polish/r_hough      : {_pct(rp)}")
    print(f"  polish → rim   r_rim/r_polish        : {_pct(rr)}")

    # Attribution : pour les undercrops, quel étage a le plus rétréci ?
    under = [r for r in records if r["ratio_final"] < args.undercrop]
    if under:
        def _shrink(key_a, key_b, recs):
            # part moyenne de rétrécissement (1 - ratio) attribuable à l'étape
            return np.mean([max(0.0, 1.0 - r[key_b] / max(1e-6, r[key_a])) for r in recs])
        sh_hough = np.mean([max(0.0, 1.0 - r["r_hough"] / r["r_bbox"]) for r in under])
        sh_polish = np.mean([max(0.0, 1.0 - r["r_polish"] / max(1e-6, r["r_hough"])) for r in under])
        sh_rim = np.mean([max(0.0, 1.0 - r["r_rim"] / max(1e-6, r["r_polish"])) for r in under])
        tot = sh_hough + sh_polish + sh_rim or 1.0
        print(f"\nParmi les {len(under)} undercrops — part du rétrécissement par étage :")
        print(f"  bbox→hough  : {100*sh_hough/tot:4.0f} %  (rétréci en moyenne {100*sh_hough:.0f} %)")
        print(f"  hough→polish: {100*sh_polish/tot:4.0f} %  (rétréci en moyenne {100*sh_polish:.0f} %)")
        print(f"  polish→rim  : {100*sh_rim/tot:4.0f} %  (rétréci en moyenne {100*sh_rim:.0f} %)")

    # Corrélation undercrop ↔ score du gate.
    scored = [r for r in records if r.get("score") is not None]
    if scored:
        sc = np.array([r["score"] for r in scored])
        rfs = np.array([r["ratio_final"] for r in scored])
        good = rfs >= args.undercrop
        bad = ~good
        print(f"\nCorrélation crop ↔ score du gate (n={len(scored)} crops acceptés, τ={tau}) :")
        if good.sum():
            print(f"  crops PLEINS (ratio≥{args.undercrop}) : score {_pct(sc[good])}  "
                  f"· passent gate {100*(sc[good] >= tau).mean():.0f} %")
        if bad.sum():
            print(f"  crops UNDERCROP (<{args.undercrop})  : score {_pct(sc[bad])}  "
                  f"· passent gate {100*(sc[bad] >= tau).mean():.0f} %")
        if len(sc) > 2 and sc.std() > 0 and rfs.std() > 0:
            print(f"  Pearson r(ratio, score) = {np.corrcoef(rfs, sc)[0,1]:+.3f} "
                  f"(positif = un meilleur crop ⇒ meilleur score)")

    # ---- CONTREFACTUEL : crop plein-rebord (r=r_bbox) du MÊME coin ----------
    # Teste la thèse du handoff : « un crop plein-rebord remonterait le score et
    # ferait repasser le gate ». Comparaison PAIRÉE sur les mêmes détections.
    paired = [r for r in records if r.get("score") is not None and r.get("score_full") is not None]
    if paired:
        sd = np.array([r["score"] for r in paired])
        sfu = np.array([r["score_full"] for r in paired])
        rfp = np.array([r["ratio_final"] for r in paired])
        und = rfp < args.undercrop  # détections actuellement undercroppées
        print(f"\n{'-'*68}\nCONTREFACTUEL — crop plein-rebord (r=r_bbox) vs crop détecté "
              f"(n={len(paired)} paires) :\n{'-'*68}")
        print(f"  score crop DÉTECTÉ  : médiane {np.median(sd):.3f} · passent gate {100*(sd >= tau).mean():.0f} %")
        print(f"  score crop PLEIN    : médiane {np.median(sfu):.3f} · passent gate {100*(sfu >= tau).mean():.0f} %")
        print(f"  Δ médian (plein−détecté) = {np.median(sfu - sd):+.3f}")
        if und.sum():
            print(f"\n  Sur les {int(und.sum())} détections UNDERCROPPÉES (ratio<{args.undercrop}) :")
            print(f"    plein-rebord récupère (passe gate alors que détecté non) : "
                  f"{int(((sfu[und] >= tau) & (sd[und] < tau)).sum())}")
            print(f"    plein-rebord passe gate : {100*(sfu[und] >= tau).mean():.0f} %  "
                  f"(vs {100*(sd[und] >= tau).mean():.0f} % au crop détecté)")
        recovered = int(((sfu >= tau) & (sd < tau)).sum())
        print(f"\n  VERDICT : crop plein-rebord récupère {recovered}/{len(paired)} crops "
              f"que le gate éjectait ({100*recovered/len(paired):.0f} %).")

    # ---- Montage des pires undercrops --------------------------------------
    if worst_imgs:
        from PIL import Image
        worst_imgs.sort(key=lambda t: t[0])  # pires (plus petits ratios) d'abord
        imgs = worst_imgs[:48]
        cols = 8
        rows_n = (len(imgs) + cols - 1) // cols
        cell = 160
        canvas = Image.new("RGB", (cols * cell, rows_n * cell), (15, 15, 15))
        for k, (ratio, img) in enumerate(imgs):
            rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
            canvas.paste(Image.fromarray(rgb).resize((cell, cell)),
                         ((k % cols) * cell, (k // cols) * cell))
        Path(args.montage).parent.mkdir(parents=True, exist_ok=True)
        canvas.save(args.montage)
        print(f"\nMontage des {len(imgs)} pires undercrops : {args.montage}")

    if debug_rows:
        from PIL import Image
        h = max(r.shape[0] for r in debug_rows)
        w = max(r.shape[1] for r in debug_rows)
        canvas = np.zeros((h * len(debug_rows), w, 3), np.uint8)
        for k, r in enumerate(debug_rows):
            canvas[k*h:k*h+r.shape[0], :r.shape[1]] = r
        pairs_path = str(OUT_DIR / "_debug_pairs.png")
        Image.fromarray(cv2.cvtColor(canvas, cv2.COLOR_BGR2RGB)).save(pairs_path)
        print(f"\nMontage de validation [raw | détecté | plein] : {pairs_path}")

    # ---- Dump JSON (ré-analyse / A-B sans re-run) --------------------------
    dump_path = args.dump or str(OUT_DIR / f"{args.run}.json")
    Path(dump_path).parent.mkdir(parents=True, exist_ok=True)
    Path(dump_path).write_text(json.dumps({
        "run": args.run, "status": args.status, "undercrop_thr": args.undercrop,
        "tau": tau, "n": n, "records": records,
    }))
    print(f"\nRecords bruts → {dump_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
