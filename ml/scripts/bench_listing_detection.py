"""Bench visuel reproductible pour la détection listing.

Objectif : à chaque itération sur `ml/scan/normalize_snap.py`, écraser et
régénérer les images de diagnostic d'un golden set figé, pour comparer
côte à côte état avant/après et éviter la dégradation invisible.

Sortie : `ml/state/listing_bench/`
  - `{source_ref}_img{n}.jpg` — diagnostic combiné (overlay + crops)
  - `summary.md` — table récap

Usage :
    cd ml
    .venv/bin/python -m scripts.bench_listing_detection

Le bench est complètement isolé de la DB : pas d'`image_assets`, pas de
recrop. C'est un atelier, pas un déploiement.

Voir `docs/sources-refacto/listing-crop-roadmap.md` pour le contexte et
le suivi des itérations.
"""
from __future__ import annotations

import datetime as _dt
import shutil
import sys
from pathlib import Path

import cv2
import numpy as np

_ML_DIR = Path(__file__).resolve().parents[1]
if str(_ML_DIR) not in sys.path:
    sys.path.insert(0, str(_ML_DIR))

from vision.normalize_snap import (  # noqa: E402
    CircleDetection,
    _LISTING_RMIN_FRAC_STRICT,
    _YOLO_BBOX_MIN_RADIUS_FRAC,
    _crop_mask_resize_int,
    _yolo_detect_bboxes,
    detect_circles_multi,
)


# Format : (source_ref, particularité). source_ref = la partie centrale du
# listing_key `ebay_v1|<source_ref>|<image_index>`.
GOLDEN_LOTS: list[tuple[str, str]] = [
    ("114573231478", "coincard texte+motifs, 1 pièce — baseline propre"),
    ("115143970168", "coincard arches concentriques (Meritxell)"),
    ("114573235985", "2 coincards côte à côte — multi-coin petit r/short"),
    ("117142786358", "coincard recto+verso + hologramme (problème C)"),
    ("168045333862", "4 pièces sur cuir — multi-coin propre"),
    ("136929255254", "pièce libre support transparent (recall miss)"),
    ("146492050953", "composite 2 coincards"),
    ("168215792107", "coincard Pirineus capsule + ciel"),
]


_RAW_ROOT = _ML_DIR / "state" / "sources" / "ebay" / "raw"
_OUT = _ML_DIR / "state" / "listing_bench"

_OVERLAY_MAX_DIM = 900   # raw redimensionné pour qu'une image entre dans une vue
_CROP_STRIP_HEIGHT = 224
_BG_COLOR = (24, 24, 24)


def _find_raws(source_ref: str) -> list[Path]:
    return sorted(_RAW_ROOT.rglob(f"*|{source_ref}|*"))


def _draw_overlay(bgr: np.ndarray,
                   yolo_bboxes: list[tuple[float, float, float, float, float]],
                   dets: list[CircleDetection],
                   bbox_min_r: float) -> np.ndarray:
    """Annote la raw : bboxes YOLO qui ont passé le pre-filter en jaune, cercles
    finals en vert (accepted) ou rouge (rejected) avec label method/reject_reason.

    Les bboxes filtrées (sub-rim_strict, = bruit text/motifs) ne sont **pas**
    affichées — elles polluent l'image diagnostic sans valeur."""
    img = bgr.copy()
    for x1, y1, x2, y2, conf in yolo_bboxes:
        if min(x2 - x1, y2 - y1) / 2.0 < bbox_min_r:
            continue
        cv2.rectangle(img, (int(x1), int(y1)), (int(x2), int(y2)),
                      (0, 200, 220), 1)  # jaune
        cv2.putText(img, f"yolo {conf:.2f}", (int(x1), max(0, int(y1) - 5)),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 200, 220), 1)
    for d in dets:
        accepted = d.accepted
        color = (0, 220, 0) if accepted else (0, 0, 220)
        thick = 3 if accepted else 2
        cv2.circle(img, (d.cx, d.cy), d.r, color, thick)
        cv2.circle(img, (d.cx, d.cy), 3, color, -1)
        if accepted:
            label = f"r={d.r} {d.method}"
        else:
            label = f"REJ:{d.reject_reason} r={d.r}"
        ty = max(20, d.cy - d.r - 8)
        cv2.putText(img, label, (max(0, d.cx - 80), ty),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, color, 2)

    h, w = img.shape[:2]
    long_side = max(h, w)
    if long_side > _OVERLAY_MAX_DIM:
        scale = _OVERLAY_MAX_DIM / long_side
        img = cv2.resize(img, (int(w * scale), int(h * scale)),
                          interpolation=cv2.INTER_AREA)
    return img


def _build_crop_strip(bgr: np.ndarray,
                       dets: list[CircleDetection]) -> np.ndarray:
    """Strip horizontal des 224×224 crops accepted. Si aucun, placeholder."""
    crops: list[np.ndarray] = []
    for d in dets:
        if not d.accepted:
            continue
        result = _crop_mask_resize_int(bgr, d.cx, d.cy, d.r, method=d.method)
        if result.image is None:
            continue
        crops.append(result.image)
    if not crops:
        ph = np.full((_CROP_STRIP_HEIGHT, _CROP_STRIP_HEIGHT, 3), 32, dtype=np.uint8)
        cv2.putText(ph, "no accepted", (16, _CROP_STRIP_HEIGHT // 2),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 2)
        return ph
    # Sépare visuellement les crops par 4 px de fond.
    sep = np.full((_CROP_STRIP_HEIGHT, 4, 3), _BG_COLOR, dtype=np.uint8)
    pieces = []
    for i, c in enumerate(crops):
        if i:
            pieces.append(sep)
        pieces.append(c)
    return np.concatenate(pieces, axis=1)


def _stack_overlay_and_crops(overlay: np.ndarray,
                              crops_strip: np.ndarray) -> np.ndarray:
    """Pad les deux à la même largeur sur fond sombre, empile vertical."""
    target_w = max(overlay.shape[1], crops_strip.shape[1])

    def pad_w(img: np.ndarray) -> np.ndarray:
        h, w = img.shape[:2]
        if w == target_w:
            return img
        pad = np.full((h, target_w - w, 3), _BG_COLOR, dtype=np.uint8)
        return np.concatenate([img, pad], axis=1)

    sep = np.full((6, target_w, 3), _BG_COLOR, dtype=np.uint8)
    return np.concatenate([pad_w(overlay), sep, pad_w(crops_strip)], axis=0)


def _process_raw(raw_path: Path, source_ref: str, img_index: int) -> dict:
    bgr = cv2.imread(str(raw_path), cv2.IMREAD_COLOR)
    if bgr is None or bgr.size == 0:
        return {"source_ref": source_ref, "img": img_index,
                "error": "raw unreadable", "n_yolo": 0,
                "n_accepted": 0, "n_rejected": 0, "methods": [],
                "r_over_short": []}
    h, w = bgr.shape[:2]
    short = float(min(h, w))
    yolo_bboxes = _yolo_detect_bboxes(bgr)
    dets = detect_circles_multi(bgr)

    rmin_strict = short * _LISTING_RMIN_FRAC_STRICT
    bbox_min_r = _YOLO_BBOX_MIN_RADIUS_FRAC * rmin_strict
    overlay = _draw_overlay(bgr, yolo_bboxes, dets, bbox_min_r)
    strip = _build_crop_strip(bgr, dets)
    stacked = _stack_overlay_and_crops(overlay, strip)

    out_path = _OUT / f"{source_ref}_img{img_index}.jpg"
    cv2.imwrite(str(out_path), stacked, [cv2.IMWRITE_JPEG_QUALITY, 88])

    accepted = [d for d in dets if d.accepted]
    rejected = [d for d in dets if not d.accepted]
    return {
        "source_ref": source_ref,
        "img": img_index,
        "raw_size": f"{w}x{h}",
        "n_yolo": len(yolo_bboxes),
        "n_accepted": len(accepted),
        "n_rejected": len(rejected),
        "methods": [d.method for d in accepted],
        "reject_reasons": [d.reject_reason for d in rejected],
        "r_over_short": [round(d.r / short, 3) for d in dets if d.accepted],
    }


def _write_summary(rows: list[dict], when: str) -> None:
    out = _OUT / "summary.md"
    with out.open("w") as f:
        f.write(f"# Bench detection listing — {when}\n\n")
        f.write("Voir `docs/sources-refacto/listing-crop-roadmap.md` pour le contexte.\n\n")
        f.write("Légende : YOLO bboxes (jaune) + cercles finals (vert=accepted, rouge=rejected). "
                "Strip 224×224 = crops finals acceptés (= input ArcFace).\n\n")
        f.write("| lot.img | size | YOLO | acc | rej | methods accepted | reject reasons | r/short accepted |\n")
        f.write("|---|---|---|---|---|---|---|---|\n")
        for r in rows:
            if "error" in r:
                f.write(f"| {r['source_ref']}.{r['img']} | — | — | — | — | "
                        f"**{r['error']}** | — | — |\n")
                continue
            methods = ", ".join(r["methods"]) if r["methods"] else "—"
            rej = ", ".join(x or "?" for x in r["reject_reasons"]) if r["reject_reasons"] else "—"
            rs = ", ".join(f"{x:.3f}" for x in r["r_over_short"]) if r["r_over_short"] else "—"
            f.write(f"| {r['source_ref']}.{r['img']} | {r['raw_size']} | "
                    f"{r['n_yolo']} | {r['n_accepted']} | {r['n_rejected']} | "
                    f"{methods} | {rej} | {rs} |\n")


def main() -> None:
    if _OUT.exists():
        shutil.rmtree(_OUT)
    _OUT.mkdir(parents=True, exist_ok=True)

    when = _dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    rows: list[dict] = []
    for source_ref, _descr in GOLDEN_LOTS:
        raws = _find_raws(source_ref)
        if not raws:
            rows.append({"source_ref": source_ref, "img": "*",
                         "error": "no raw on disk"})
            continue
        for i, raw in enumerate(raws):
            print(f"  {source_ref} img{i}: {raw.name}")
            rows.append(_process_raw(raw, source_ref, i))

    _write_summary(rows, when)
    print(f"\n→ {_OUT}/")
    print(f"  summary.md + {sum(1 for r in rows if 'error' not in r)} jpg(s)")


if __name__ == "__main__":
    main()
