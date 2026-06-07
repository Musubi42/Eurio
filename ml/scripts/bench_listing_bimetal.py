"""Bench visuel ciblé bimétal — qualité crop sur 2€ commémoratives.

Complément du `bench_listing_detection.py` (golden set 8 lots fixes, 2026-05-04).
Celui-ci échantillonne ~25 image_assets 2€ commémo réels depuis la DB,
télécharge les raws depuis MinIO, re-tourne `detect_circles_multi`, et
sort un diagnostic visuel + summary quantifiant le sous-crop bimétal.

Voir `docs/operations/crop-bimetal-undercrop.md` pour le contexte.

Sortie : `ml/state/listing_bimetal_bench/`
  - `{country}-{year}-{slug-court}_{i}.jpg` — overlay raw + crop stored + crop reco
  - `summary.md` — table récap + métriques agrégées

Usage :
    cd ml
    .venv/bin/python -m scripts.bench_listing_bimetal [--n 25] [--seed 0]

Le bench est read-only : pas d'écriture DB, pas de MinIO, pas de modèle
modifié. Strictement un atelier visuel.
"""
from __future__ import annotations

import argparse
import datetime as _dt
import shutil
import sqlite3
import sys
from pathlib import Path

import cv2
import numpy as np

_ML_DIR = Path(__file__).resolve().parents[1]
if str(_ML_DIR) not in sys.path:
    sys.path.insert(0, str(_ML_DIR))

from vision.normalize_snap import (  # noqa: E402
    _LISTING_RMIN_FRAC_STRICT,
    _YOLO_BBOX_MIN_RADIUS_FRAC,
    _crop_mask_resize_int,
    _yolo_detect_bboxes,
    detect_circles_multi,
)
from shared.storage.local_cache import local_path  # noqa: E402


_DB = _ML_DIR / "state" / "eurio.db"
_OUT = _ML_DIR / "state" / "listing_bimetal_bench"
_BG_COLOR = (24, 24, 24)
_OVERLAY_MAX_DIM = 700
_CROP_DISPLAY = 224

# Probe undercrop : on lance une 2e détection Otsu+contour (= studio pipeline)
# pour estimer le "vrai" rim de la pièce, puis on compare au rayon que la
# pipeline production a choisi. Si pipeline_r < 0.85 × probe_r → undercrop.
# 0.85 = 15% de tolérance (margin polish, jitter Hough).
_UNDERCROP_TOLERANCE = 0.85


def _probe_true_rim(bgr: np.ndarray, hint_cx: int, hint_cy: int,
                     hint_r: int) -> float | None:
    """Estime le rayon "vrai" du rim métallique autour du point (hint_cx,hint_cy).
    Utilisé comme oracle indépendant pour flagger les undercrops.

    Méthode : crop ROI 3×r autour du hint, Otsu inverse (silver/gold sur fond
    clair OU sombre — on prend la classe majoritaire centrale), garde le
    contour connexe contenant le centre, minEnclosingCircle. Retourne None si
    Otsu collapse ou contour non centré."""
    h, w = bgr.shape[:2]
    pad = int(hint_r * 2.5) + 8
    x0 = max(0, hint_cx - pad)
    y0 = max(0, hint_cy - pad)
    x1 = min(w, hint_cx + pad)
    y1 = min(h, hint_cy + pad)
    roi = bgr[y0:y1, x0:x1]
    if roi.size == 0:
        return None
    gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
    gray = cv2.GaussianBlur(gray, (5, 5), 0)
    # Double tentative : Otsu direct + inverse, on garde celui dont le contour
    # central donne le rayon le plus cohérent avec le hint (>0.7×hint, <2×hint)
    candidates = []
    for inv in (False, True):
        flag = cv2.THRESH_BINARY_INV if inv else cv2.THRESH_BINARY
        _, bw = cv2.threshold(gray, 0, 255, flag | cv2.THRESH_OTSU)
        bw = cv2.morphologyEx(bw, cv2.MORPH_CLOSE,
                                cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5)))
        cx_local = hint_cx - x0
        cy_local = hint_cy - y0
        contours, _ = cv2.findContours(bw, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        for cnt in contours:
            if cv2.pointPolygonTest(cnt, (cx_local, cy_local), False) < 0:
                continue
            area = cv2.contourArea(cnt)
            if area < (hint_r * 0.5) ** 2 * np.pi:
                continue
            (_, _), r_enc = cv2.minEnclosingCircle(cnt)
            fill = area / max(1.0, np.pi * r_enc * r_enc)
            if fill < 0.65:  # collapse en U/L shape → reject
                continue
            if 0.7 * hint_r <= r_enc <= 2.0 * hint_r:
                candidates.append((float(r_enc), fill))
    if not candidates:
        return None
    # Garde le rayon max (= rim externe, signature bimétal complet)
    candidates.sort(key=lambda t: -t[0])
    return candidates[0][0]


def _slugify(s: str, max_len: int = 30) -> str:
    out = "".join(c if c.isalnum() else "-" for c in (s or "").lower())
    while "--" in out:
        out = out.replace("--", "-")
    return out.strip("-")[:max_len] or "unknown"


def _select_samples(n: int, seed: int) -> list[dict]:
    """Échantillonne `n` image_assets 2€ commémo diversifiés.
    Source : image_assets soit auto-acceptés (eurio_id direct), soit en review
    queue ouverte (target via source_images.target_eurio_id).
    Stratégie : 1 par (country, year, theme) si possible, complété au hasard."""
    con = sqlite3.connect(str(_DB))
    con.row_factory = sqlite3.Row
    rows = con.execute("""
        SELECT a.id AS asset_id,
               a.storage_path AS crop_key,
               a.detection_method,
               si.storage_path AS raw_key,
               COALESCE(a.eurio_id, si.target_eurio_id) AS eurio_id,
               c.country, c.year, c.theme
        FROM image_assets a
        JOIN source_images si ON si.id = a.source_image_id
        JOIN coins c ON c.eurio_id = COALESCE(a.eurio_id, si.target_eurio_id)
        WHERE c.face_value = 2.0
          AND c.is_commemorative = 1
          AND si.storage_status = 'present'
          AND a.storage_status = 'present'
        ORDER BY a.id
    """).fetchall()
    con.close()

    import random
    rng = random.Random(seed)
    seen_keys: set[tuple] = set()
    picked: list[dict] = []
    # Premier passage : 1 par triplet unique (country, year, theme)
    shuffled = list(rows)
    rng.shuffle(shuffled)
    for r in shuffled:
        key = (r["country"], r["year"], r["theme"])
        if key in seen_keys:
            continue
        seen_keys.add(key)
        picked.append(dict(r))
        if len(picked) >= n:
            break
    # Si besoin de compléter
    if len(picked) < n:
        picked_ids = {p["asset_id"] for p in picked}
        for r in shuffled:
            if r["asset_id"] in picked_ids:
                continue
            picked.append(dict(r))
            if len(picked) >= n:
                break
    return picked


def _draw_overlay(bgr: np.ndarray, dets, bbox_min_r: float,
                   yolo_bboxes) -> np.ndarray:
    img = bgr.copy()
    for x1, y1, x2, y2, conf in yolo_bboxes:
        if min(x2 - x1, y2 - y1) / 2.0 < bbox_min_r:
            continue
        cv2.rectangle(img, (int(x1), int(y1)), (int(x2), int(y2)),
                       (0, 200, 220), 1)
    for d in dets:
        color = (0, 220, 0) if d.accepted else (0, 0, 220)
        thick = 3 if d.accepted else 2
        cv2.circle(img, (d.cx, d.cy), d.r, color, thick)
        cv2.circle(img, (d.cx, d.cy), 4, color, -1)
        label = f"r={d.r} {d.method}" if d.accepted else f"REJ:{d.reject_reason}"
        cv2.putText(img, label, (max(0, d.cx - 80), max(20, d.cy - d.r - 8)),
                     cv2.FONT_HERSHEY_SIMPLEX, 0.55, color, 2)
    h, w = img.shape[:2]
    long_side = max(h, w)
    if long_side > _OVERLAY_MAX_DIM:
        scale = _OVERLAY_MAX_DIM / long_side
        img = cv2.resize(img, (int(w * scale), int(h * scale)),
                          interpolation=cv2.INTER_AREA)
    return img


def _label_strip(text: str, w: int, h: int = 22) -> np.ndarray:
    strip = np.full((h, w, 3), _BG_COLOR, dtype=np.uint8)
    cv2.putText(strip, text, (6, h - 6), cv2.FONT_HERSHEY_SIMPLEX,
                 0.5, (255, 255, 255), 1)
    return strip


def _compose(overlay: np.ndarray, stored_crop: np.ndarray,
              recomputed: np.ndarray, header: str, footer: str) -> np.ndarray:
    target_w = max(overlay.shape[1], _CROP_DISPLAY * 2 + 8)

    def pad_w(img: np.ndarray) -> np.ndarray:
        h, w = img.shape[:2]
        if w >= target_w:
            return img
        pad = np.full((h, target_w - w, 3), _BG_COLOR, dtype=np.uint8)
        return np.concatenate([img, pad], axis=1)

    # Strip crops: stored | recomputed côte à côte
    sep_h = np.full((_CROP_DISPLAY, 8, 3), _BG_COLOR, dtype=np.uint8)
    if recomputed is None:
        recomputed = np.full((_CROP_DISPLAY, _CROP_DISPLAY, 3), 40, dtype=np.uint8)
        cv2.putText(recomputed, "no detect", (12, _CROP_DISPLAY // 2),
                     cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)
    if stored_crop is None:
        stored_crop = np.full((_CROP_DISPLAY, _CROP_DISPLAY, 3), 40, dtype=np.uint8)
        cv2.putText(stored_crop, "missing", (12, _CROP_DISPLAY // 2),
                     cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)
    crops_row = np.concatenate([stored_crop, sep_h, recomputed], axis=1)
    crops_labels = np.concatenate([
        _label_strip("STORED (en DB)", _CROP_DISPLAY),
        np.full((22, 8, 3), _BG_COLOR, dtype=np.uint8),
        _label_strip("RECOMPUTED (pipeline live)", _CROP_DISPLAY),
    ], axis=1)
    crops_stack = np.concatenate([crops_labels, crops_row], axis=0)

    sep_v = np.full((6, target_w, 3), _BG_COLOR, dtype=np.uint8)
    return np.concatenate([
        _label_strip(header, target_w, 28),
        pad_w(overlay),
        sep_v,
        pad_w(crops_stack),
        _label_strip(footer, target_w, 22),
    ], axis=0)


def _process_sample(row: dict) -> dict:
    raw_key = row["raw_key"]
    crop_key = row["crop_key"]
    eurio = row["eurio_id"]
    try:
        raw_path = local_path("enrichment-raws", raw_key)
    except FileNotFoundError as e:
        return {"eurio_id": eurio, "error": f"raw missing: {e}"}
    bgr = cv2.imread(str(raw_path), cv2.IMREAD_COLOR)
    if bgr is None:
        return {"eurio_id": eurio, "error": "raw unreadable"}
    h, w = bgr.shape[:2]
    short = float(min(h, w))

    # Stored crop (ce qui est actuellement en DB → ce que le user voit)
    try:
        stored_path = local_path("enrichment-crops", crop_key)
        stored_crop = cv2.imread(str(stored_path), cv2.IMREAD_COLOR)
    except FileNotFoundError:
        stored_crop = None

    # Re-run pipeline
    yolo_bboxes = _yolo_detect_bboxes(bgr)
    dets = detect_circles_multi(bgr)
    accepted = [d for d in dets if d.accepted]
    rmin_strict = short * _LISTING_RMIN_FRAC_STRICT
    bbox_min_r = _YOLO_BBOX_MIN_RADIUS_FRAC * rmin_strict
    overlay = _draw_overlay(bgr, dets, bbox_min_r, yolo_bboxes)

    # Pick the first accepted detection as "the" recomputed crop (closest match
    # to what would be stored)
    if accepted:
        d = accepted[0]
        res = _crop_mask_resize_int(bgr, d.cx, d.cy, d.r, method=d.method)
        recomputed_crop = res.image if res is not None else None
        r_over_short = round(d.r / short, 3)
        true_r = _probe_true_rim(bgr, d.cx, d.cy, d.r)
        if true_r is not None:
            ratio_to_true = d.r / true_r
            suspect = ratio_to_true < _UNDERCROP_TOLERANCE
        else:
            ratio_to_true = None
            suspect = False
    else:
        recomputed_crop = None
        r_over_short = None
        true_r = None
        ratio_to_true = None
        suspect = False

    slug = f"{row['country']}-{row['year']}-{_slugify(row['theme'])}"
    header = (f"{slug}  |  raw {w}x{h}  |  short={int(short)}  |  "
              f"n_acc={len(accepted)} n_rej={len(dets) - len(accepted)}")
    if r_over_short is not None:
        flag = "  ⚠ SUSPECT UNDERCROP" if suspect else "  ✓"
        rtxt = (f"r_pipe/r_probe={ratio_to_true:.2f}"
                if ratio_to_true is not None else "probe=n/a")
        footer = (f"r_pipe={accepted[0].r}  probe_r={int(true_r) if true_r else 'n/a'}  "
                  f"{rtxt}{flag}  method={accepted[0].method}")
    else:
        footer = "(aucune détection acceptée)"

    composed = _compose(overlay, stored_crop, recomputed_crop, header, footer)
    out_name = f"{slug[:50]}_{row['asset_id'][:8]}.jpg"
    cv2.imwrite(str(_OUT / out_name), composed, [cv2.IMWRITE_JPEG_QUALITY, 88])

    return {
        "eurio_id": eurio,
        "asset_id": row["asset_id"],
        "country": row["country"],
        "year": row["year"],
        "theme": row["theme"],
        "raw_size": f"{w}x{h}",
        "n_accepted": len(accepted),
        "n_rejected": len(dets) - len(accepted),
        "method": accepted[0].method if accepted else None,
        "r_pipe": accepted[0].r if accepted else None,
        "true_r": int(true_r) if true_r else None,
        "ratio_to_true": round(ratio_to_true, 3) if ratio_to_true else None,
        "r_over_short": r_over_short,
        "suspect_undercrop": suspect,
        "out_file": out_name,
    }


def _write_summary(rows: list[dict], when: str, n: int, seed: int) -> None:
    out = _OUT / "summary.md"
    valid = [r for r in rows if "error" not in r and r["r_over_short"] is not None]
    n_suspect = sum(1 for r in valid if r["suspect_undercrop"])
    n_err = sum(1 for r in rows if "error" in r)
    n_probe_failed = sum(1 for r in valid if r.get("ratio_to_true") is None)
    ratios_true = [r["ratio_to_true"] for r in valid if r.get("ratio_to_true") is not None]
    with out.open("w") as f:
        f.write(f"# Bench bimétal — qualité crop 2€ commémoratives\n\n")
        f.write(f"Échantillon : {n} demandés, seed={seed}, généré {when}\n\n")
        f.write(f"- Crops avec détection valide : **{len(valid)}**\n")
        f.write(f"- Crops suspects d'undercrop "
                f"(r_pipe/r_probe < {_UNDERCROP_TOLERANCE}) : "
                f"**{n_suspect} ({100*n_suspect/max(1,len(valid)):.0f} %)**\n")
        f.write(f"- Probe Otsu n'a pas pu se prononcer : **{n_probe_failed}**\n")
        f.write(f"- Erreurs (raw missing / unreadable) : **{n_err}**\n\n")
        if ratios_true:
            arr = np.array(ratios_true)
            f.write(f"**r_pipe/r_probe stats** : "
                    f"min={arr.min():.3f}  p25={np.percentile(arr,25):.3f}  "
                    f"med={np.median(arr):.3f}  p75={np.percentile(arr,75):.3f}  "
                    f"max={arr.max():.3f}\n\n")
        f.write("Légende : `r_pipe` = rayon choisi par la pipeline. `probe_r` = "
                "rayon Otsu+contour autour du même centre (oracle indépendant). "
                "Ratio < 0.85 → la pipeline a sous-cropé (typique bimétal : "
                "Hough vote anneau interne or au lieu du rim externe argent).\n\n")
        f.write("| country | year | theme | r_pipe/probe | r_pipe | probe_r | method | suspect | file |\n")
        f.write("|---|---|---|---|---|---|---|---|---|\n")
        # Tri : suspects en premier, puis ratio croissant
        def sort_key(r):
            if "error" in r:
                return (2, 0)
            if r.get("ratio_to_true") is None:
                return (1, 0)
            return (0 if r["suspect_undercrop"] else 1, r["ratio_to_true"])
        for r in sorted(rows, key=sort_key):
            if "error" in r:
                f.write(f"| ? | ? | ? | — | — | — | — | err | {r['error']} |\n")
                continue
            ratio = (f"{r['ratio_to_true']:.2f}" if r.get('ratio_to_true') is not None
                     else "n/a")
            rp = r.get('r_pipe') or '—'
            pr = r.get('true_r') or '—'
            sus = "⚠" if r["suspect_undercrop"] else ""
            f.write(f"| {r['country']} | {r['year']} | "
                    f"{(r['theme'] or '')[:40]} | {ratio} | {rp} | {pr} | "
                    f"{r['method'] or '—'} | {sus} | `{r['out_file']}` |\n")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--n", type=int, default=25)
    parser.add_argument("--seed", type=int, default=0)
    args = parser.parse_args()

    if _OUT.exists():
        shutil.rmtree(_OUT)
    _OUT.mkdir(parents=True, exist_ok=True)

    when = _dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    samples = _select_samples(args.n, args.seed)
    print(f"Sélectionnés : {len(samples)} image_assets 2€ commémo")
    rows = []
    for i, s in enumerate(samples, 1):
        print(f"  [{i}/{len(samples)}] {s['country']}-{s['year']} "
               f"{(s['theme'] or '')[:40]}")
        rows.append(_process_sample(s))
    _write_summary(rows, when, args.n, args.seed)
    print(f"\n→ {_OUT}/")
    valid = [r for r in rows if "error" not in r and r.get('r_over_short') is not None]
    n_sus = sum(1 for r in valid if r.get('suspect_undercrop'))
    print(f"  {len(valid)} détections valides, {n_sus} undercrops suspects, "
          f"{sum(1 for r in rows if 'error' in r)} erreurs")


if __name__ == "__main__":
    main()
