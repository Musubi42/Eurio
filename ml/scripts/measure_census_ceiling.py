"""measure_census_ceiling.py — plafond SANS ENTRAÎNEMENT du census de pièces.

Compare des proposeurs OFF-THE-SHELF (aucun entraînement) sur le bench v0
(`ml/state/coin_census_bench/bench_v0.json`, 110 raws labellisés vision) pour
chiffrer **combien des 55 % zéro-crop on récupère** et le **faux-single rate**,
AVANT d'investir dans un détecteur entraîné. Bench-first, R0.

C'est un script LOCAL DÉTERMINISTE (inférence de modèles déjà présents) —
aucun agent LLM, ~0 coût token.

Le bench labellise des COMPTES (`n_coins`, `n_disks_visible`), pas des boîtes →
toutes les métriques sont au niveau du compte (= ce dont lot/single a besoin).

Proposeurs (chacun → `n_pred` par image, après son propre dedup) :
  - baseline_prod : `n_crops` du détecteur de prod (YOLO+Hough+filtres stricts), lu du bench.
                    C'est la baseline (c) « ce qu'on a aujourd'hui ». NB : le multi-Hough NU
                    plein-cadre a été écarté — pathologiquement lent (3-20 s/img à param2 bas,
                    livelock) ET inutile : le bench établit déjà que compter des cercles bruts
                    sur-compte (anneau bimétal / capsule / fenêtre coincard = FP) — principe n°1.
  - yolo_low      : `coin_detector` existant à conf BASSE, compte les bboxes, SANS les
                    post-filtres stricts de prod (rmin 0.08 / low_structure / off_edge).
                    Test diagnostique : le modèle VOIT-il déjà les pièces emballées ?
  - sam2_dino     : SAM2 everything (haut rappel, OBJET pas cercle) → bbox des masques →
                    is-coin (sweep géométrie + DINO sim-to-anchors). 2 points : propose-recall
                    (pré-filtre = plafond pur) et count post-verify (sweep du seuil).

Usage (depuis ml/, PYTHONPATH=.):
  .venv/bin/python scripts/measure_census_ceiling.py --proposers yolo,hough        # rapide, 0 download
  .venv/bin/python scripts/measure_census_ceiling.py --proposers sam --sam-model sam2_b.pt
  .venv/bin/python scripts/measure_census_ceiling.py --proposers all --limit 5     # probe
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from typing import Any, Callable

import cv2
import numpy as np

# OpenCV multi-thread + HoughCircles à param2 bas = livelock (20 min CPU observé).
# On force le mono-thread : ces opérations sont déjà rapides à params sains, et
# le déterminisme prime sur le throughput pour une mesure.
cv2.setNumThreads(1)

ML_DIR = Path(__file__).resolve().parents[1]
BENCH_PATH = ML_DIR / "state" / "coin_census_bench" / "bench_v0.json"
OUT_DIR = ML_DIR / "state" / "coin_census_bench"


# ---------------------------------------------------------------------------
# Chargement du bench
# ---------------------------------------------------------------------------

def load_bench() -> list[dict[str, Any]]:
    items = json.loads(BENCH_PATH.read_text())
    out = []
    for it in items:
        p = Path(it["raw_path"])
        if not p.exists():
            print(f"  ⚠️  raw absent, skip: {p}")
            continue
        out.append(it)
    return out


def _short_side(bgr: np.ndarray) -> int:
    return min(bgr.shape[:2])


# ---------------------------------------------------------------------------
# Proposeur (a) — YOLO coin_detector à conf basse (compte les bboxes)
# ---------------------------------------------------------------------------

_yolo_model: Any = None
_YOLO_DEVICE = "cpu"
_YOLO_IMGSZ = 640


def _pick_device() -> str:
    import torch
    if torch.cuda.is_available():
        return "cuda"
    if torch.backends.mps.is_available():
        return "mps"
    return "cpu"


def _get_yolo() -> Any:
    global _yolo_model
    if _yolo_model is None:
        from ultralytics import YOLO
        from scan.normalize_snap import _YOLO_MODEL_PATH
        _yolo_model = YOLO(str(_YOLO_MODEL_PATH))
    return _yolo_model


def yolo_low_counts(bgr: np.ndarray, confs: list[float],
                    r_floor_frac: float) -> dict[str, int]:
    """Compte les bboxes du coin_detector existant à plusieurs seuils de conf.

    `r_floor_frac` : plancher de rayon (frac du petit côté) pour couper le bruit
    « lettre O / motif » que YOLO confond avec une pièce lointaine. Plus bas que
    le 0.08 strict de prod (on cherche le PLAFOND de rappel). NMS déjà appliqué
    par ultralytics (iou=0.45). Renvoie {f"conf{c}": n}.
    """
    model = _get_yolo()
    short = _short_side(bgr)
    r_floor = r_floor_frac * short
    out: dict[str, int] = {}
    # Une seule passe au conf min, puis on re-seuille en Python (cohérent, rapide).
    cmin = min(confs)
    res = model.predict(bgr, imgsz=_YOLO_IMGSZ, conf=cmin, iou=0.45,
                        device=_YOLO_DEVICE, verbose=False)
    boxes = []
    if res and res[0].boxes is not None and len(res[0].boxes):
        xyxy = res[0].boxes.xyxy.cpu().numpy()
        cf = res[0].boxes.conf.cpu().numpy()
        for i in range(len(cf)):
            x1, y1, x2, y2 = xyxy[i].tolist()
            r = min(x2 - x1, y2 - y1) / 2.0
            boxes.append((r, float(cf[i])))
    for c in confs:
        out[f"conf{c:g}"] = sum(1 for r, cf in boxes if cf >= c and r >= r_floor)
    return out


# ---------------------------------------------------------------------------
# Proposeur (b) — SAM2 everything → is-coin (géométrie + DINO sim-to-anchors)
# ---------------------------------------------------------------------------

_sam_model: Any = None
_SAM_DEVICE = "cpu"
_dino: dict[str, Any] = {}
_anchor_mat: np.ndarray | None = None


def _is_fastsam(sam_model: str) -> bool:
    return "fastsam" in sam_model.lower()


def _get_sam(sam_model: str) -> Any:
    """Charge le proposeur-objet. FastSAM (YOLOv8-seg, 1 passe, ~0.3 s/img CPU) si
    le nom contient 'FastSAM' ; sinon SAM/SAM2/MobileSAM (everything-mode, ~25-40 s/img
    CPU/MPS — réserver au GPU CUDA)."""
    global _sam_model
    if _sam_model is None:
        if _is_fastsam(sam_model):
            from ultralytics import FastSAM
            _sam_model = FastSAM(sam_model)
        else:
            from ultralytics import SAM
            _sam_model = SAM(sam_model)
    return _sam_model


def _get_dino():
    if not _dino:
        from foundation.encoder import load_encoder, build_transform
        enc, dev = load_encoder()
        _dino["enc"], _dino["dev"], _dino["tf"] = enc, dev, build_transform()
    return _dino["enc"], _dino["dev"], _dino["tf"]


def _get_anchors() -> np.ndarray | None:
    global _anchor_mat
    if _anchor_mat is None:
        from foundation.anchors import load_anchors
        bank = load_anchors("2eur_commemo")
        _anchor_mat = bank.matrix if bank is not None else np.zeros((0, 0), np.float32)
    return _anchor_mat if _anchor_mat.size else None


def _mask_geometry(mask: np.ndarray) -> dict[str, float] | None:
    """bbox + métriques de forme d'un masque booléen. None si dégénéré."""
    ys, xs = np.nonzero(mask)
    if xs.size == 0:
        return None
    x0, x1 = int(xs.min()), int(xs.max())
    y0, y1 = int(ys.min()), int(ys.max())
    bw, bh = (x1 - x0 + 1), (y1 - y0 + 1)
    if bw < 2 or bh < 2:
        return None
    area = float(xs.size)
    bbox_area = float(bw * bh)
    r_equiv = float(np.sqrt(area / np.pi))
    return {
        "x0": x0, "y0": y0, "x1": x1, "y1": y1, "bw": bw, "bh": bh,
        "area": area, "fill": area / bbox_area,          # disque inscrit ≈ 0.785
        "axis_ratio": min(bw, bh) / max(bw, bh),
        "r_equiv": r_equiv,
    }


def sam_dino_candidates(bgr: np.ndarray, sam_model: str,
                        rmin_frac: float, rmax_frac: float,
                        bg_area_frac: float) -> list[dict[str, Any]]:
    """SAM2 everything → liste de candidats avec géométrie + score DINO is-coin.

    Chaque candidat : {r_equiv, fill, axis_ratio, dino_max} où `dino_max` = cosinus
    max du crop bbox vs la banque d'ancres (canonical obverses 2€ commémo). On ne
    DÉCIDE pas ici du is-coin : on remonte les signaux, le sweep tranche en aval.
    Pré-filtre minimal = taille plausible (rmin..rmax) et pas le fond entier.
    """
    sam = _get_sam(sam_model)
    H, W = bgr.shape[:2]
    short = min(H, W)
    img_area = float(H * W)
    rmin, rmax = rmin_frac * short, rmax_frac * short

    if _is_fastsam(sam_model):
        res = sam(bgr, verbose=False, device=_SAM_DEVICE,
                  retina_masks=True, imgsz=1024, conf=0.25, iou=0.7)
    else:
        res = sam(bgr, verbose=False, device=_SAM_DEVICE)
    if not res or res[0].masks is None:
        return []
    md = res[0].masks.data  # (N, h, w) tensor, possiblement à une autre résolution
    masks = md.cpu().numpy().astype(bool)

    enc, dev, tf = _get_dino()
    anchors = _get_anchors()
    import torch
    from PIL import Image

    cands: list[dict[str, Any]] = []
    crops_pil: list[Any] = []
    for m in masks:
        if m.shape != (H, W):
            m = cv2.resize(m.astype(np.uint8), (W, H),
                           interpolation=cv2.INTER_NEAREST).astype(bool)
        g = _mask_geometry(m)
        if g is None:
            continue
        if g["area"] / img_area > bg_area_frac:   # masque = fond / carte entière
            continue
        if not (rmin <= g["r_equiv"] <= rmax):    # taille implausible pour une pièce
            continue
        crop = bgr[g["y0"]:g["y1"] + 1, g["x0"]:g["x1"] + 1]
        crops_pil.append(Image.fromarray(cv2.cvtColor(crop, cv2.COLOR_BGR2RGB)))
        cands.append({"r_equiv": g["r_equiv"], "fill": g["fill"],
                      "axis_ratio": g["axis_ratio"], "dino_max": 0.0})

    # DINO is-coin : cosinus max vs ancres (batch).
    if cands and anchors is not None:
        with torch.no_grad():
            t = torch.stack([tf(p) for p in crops_pil]).to(dev)
            feat = enc(t)
            feat = torch.nn.functional.normalize(feat, dim=1).cpu().numpy()
        sims = feat @ anchors.T                       # (N, A)
        for i, c in enumerate(cands):
            c["dino_max"] = float(sims[i].max()) if sims.shape[1] else 0.0
    return cands


# ---------------------------------------------------------------------------
# Métriques (au niveau du compte)
# ---------------------------------------------------------------------------

def aggregate(preds: dict[str, int], bench: list[dict],
              subset: list[dict] | None = None) -> dict[str, Any]:
    """preds : source_image_id -> n_pred. Renvoie les métriques agrégées."""
    items = subset if subset is not None else bench
    items = [it for it in items if it["source_image_id"] in preds]
    n = len(items)
    if n == 0:
        return {"n": 0}

    def frac(cond: Callable[[dict, int], bool], pool: list[dict]) -> tuple[int, int]:
        hits = sum(1 for it in pool if cond(it, preds[it["source_image_id"]]))
        return hits, len(pool)

    zero_pool = [it for it in items if it["n_crops"] == 0 and it["n_coins"] >= 1]
    lot_pool = [it for it in items if it["n_coins"] >= 2]
    single_pool = [it for it in items if it["n_coins"] == 1]

    zr = frac(lambda it, p: p >= 1, zero_pool)
    fs = frac(lambda it, p: p <= 1, lot_pool)          # faux-single (poison)
    fl = frac(lambda it, p: p >= 2, single_pool)       # faux-lot
    ex_c = frac(lambda it, p: p == it["n_coins"], items)
    p1_c = frac(lambda it, p: abs(p - it["n_coins"]) <= 1, items)
    ex_d = frac(lambda it, p: p == (it.get("n_disks_visible") or 0), items)
    p1_d = frac(lambda it, p: abs(p - (it.get("n_disks_visible") or 0)) <= 1, items)

    def pct(t: tuple[int, int]) -> str:
        h, d = t
        return f"{h}/{d}={100*h/d:.0f}%" if d else "—"

    return {
        "n": n,
        "zero_recovery": pct(zr),
        "exact_coins": pct(ex_c), "pm1_coins": pct(p1_c),
        "exact_disks": pct(ex_d), "pm1_disks": pct(p1_d),
        "false_single": pct(fs), "false_lot": pct(fl),
        "_raw": {"zero_recovery": zr, "false_single": fs, "false_lot": fl,
                 "exact_coins": ex_c, "pm1_coins": p1_c,
                 "exact_disks": ex_d, "pm1_disks": p1_d},
    }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--proposers", default="all",
                    help="csv parmi yolo,hough,sam ou 'all'")
    ap.add_argument("--sam-model", default="FastSAM-s.pt",
                    help="FastSAM-s.pt (Mac, ~0.3s/img) | sam2_b.pt/mobile_sam.pt (GPU CUDA only)")
    ap.add_argument("--limit", type=int, default=0, help="probe N images (0=tout)")
    ap.add_argument("--yolo-confs", default="0.05,0.10,0.15")
    ap.add_argument("--yolo-rfloor", type=float, default=0.04)
    ap.add_argument("--device", default="auto", help="cpu|mps|cuda|auto")
    ap.add_argument("--imgsz", type=int, default=640)
    ap.add_argument("--sam-rmin", type=float, default=0.04)
    ap.add_argument("--sam-rmax", type=float, default=0.55)
    ap.add_argument("--sam-bg-area", type=float, default=0.65)
    ap.add_argument("--out", default=str(OUT_DIR / "ceiling_v0.json"))
    args = ap.parse_args()

    which = ({"yolo", "sam"} if args.proposers == "all"
             else set(s.strip() for s in args.proposers.split(",")))
    confs = [float(x) for x in args.yolo_confs.split(",")]

    global _YOLO_DEVICE, _YOLO_IMGSZ, _SAM_DEVICE
    _YOLO_DEVICE = _pick_device() if args.device == "auto" else args.device
    _SAM_DEVICE = _YOLO_DEVICE
    _YOLO_IMGSZ = args.imgsz
    print(f"Device: {_YOLO_DEVICE} | imgsz YOLO: {_YOLO_IMGSZ} | sam-model: {args.sam_model}")

    bench = load_bench()
    if args.limit:
        bench = bench[: args.limit]
    print(f"Bench: {len(bench)} raws | proposeurs: {sorted(which)}")

    # Collecte des prédictions par proposeur-variante.
    preds: dict[str, dict[str, int]] = {}
    cand_dump: dict[str, list[dict]] = {}   # pour le sweep SAM

    # baseline_prod (gratuit, lu du bench)
    preds["baseline_prod_ncrops"] = {it["source_image_id"]: it["n_crops"] for it in bench}

    t0 = time.time()
    for idx, it in enumerate(bench):
        sid = it["source_image_id"]
        bgr = cv2.imread(it["raw_path"], cv2.IMREAD_COLOR)
        if bgr is None:
            continue

        if "yolo" in which:
            yc = yolo_low_counts(bgr, confs, args.yolo_rfloor)
            for k, v in yc.items():
                preds.setdefault(f"yolo_{k}", {})[sid] = v

        if "sam" in which:
            cands = sam_dino_candidates(bgr, args.sam_model,
                                        args.sam_rmin, args.sam_rmax, args.sam_bg_area)
            cand_dump[sid] = cands
            # propose-recall = nb de candidats passant le pré-filtre taille (pur rappel)
            preds.setdefault("sam_propose", {})[sid] = len(cands)

        if (idx + 1) % 10 == 0 or idx + 1 == len(bench):
            dt = time.time() - t0
            print(f"  {idx+1}/{len(bench)}  ({dt:.0f}s, {dt/(idx+1):.1f}s/img)")

    # --- Sweep SAM is-coin (géométrie + DINO) ---
    if "sam" in which and cand_dump:
        # géométrie : candidat "coin-like" = fill∈[lo,hi] & axis_ratio≥ar
        for fill_lo, fill_hi, ar in [(0.60, 0.95, 0.70)]:
            key = f"sam_geom(fill{fill_lo}-{fill_hi},ar{ar})"
            preds[key] = {
                sid: sum(1 for c in cs
                         if fill_lo <= c["fill"] <= fill_hi and c["axis_ratio"] >= ar)
                for sid, cs in cand_dump.items()
            }
        # DINO : candidat "coin" = dino_max ≥ τ (sweep)
        for tau in [0.30, 0.40, 0.45, 0.50, 0.55, 0.60]:
            preds[f"sam_dino(τ{tau:g})"] = {
                sid: sum(1 for c in cs if c["dino_max"] >= tau)
                for sid, cs in cand_dump.items()
            }

    # --- Agrégation + impression ---
    report: dict[str, Any] = {}
    cols = ["n", "zero_recovery", "exact_coins", "pm1_coins",
            "exact_disks", "pm1_disks", "false_single", "false_lot"]
    print("\n" + "=" * 110)
    print(f"{'proposeur':<34} " + " ".join(f"{c:>13}" for c in cols[1:]))
    print("-" * 110)
    for name, pd in preds.items():
        agg = aggregate(pd, bench)
        report[name] = agg
        print(f"{name:<34} " + " ".join(f"{str(agg.get(c,'—')):>13}" for c in cols[1:]))
    print("=" * 110)
    print("Pools: zero_recovery=61 zéro-crop · false_single=27 vrais lots · false_lot=80 vrais singles")

    out_p = Path(args.out)
    out_p.write_text(json.dumps({
        "bench_n": len(bench),
        "proposers": sorted(which),
        "report": report,
        "preds": preds,
    }, ensure_ascii=False, indent=2))
    print(f"\n→ {out_p}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
