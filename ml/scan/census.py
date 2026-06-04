"""Census ladder — ramène le sur-comptage du proposeur haut-rappel (YOLO-low).

Le bench (docs/cohort-pipeline/coin-census-bench.md §5) a montré : YOLO-low@~0.10
résout le rappel (faux-single 0 %) mais sur-compte (faux-lot ~69 %). Caractérisation
des boîtes en trop : 8 % concentriques (doublon/anneau bimétal), 69 % non-pièce
(texte/fenêtre coincard/fond), 22 % coin-like séparées (avers/revers ou 2e objet).

Cet étage applique, sur les boîtes YOLO :
  ① nms_concentric : fusionne les boîtes dont l'une contient le centre de l'autre
                     ou IoU > seuil — garde la plus grande (rim externe).
  ② is_coin        : garde « pièce, toute dénomination/face » via sim DINO max à la
                     banque coin-ness (avers+revers, build_coinness_bank.py) ≥ τ,
                     avec un pré-filtre structure-guard cheap (mean|Laplacian|).

③ fusion d'identité (avers/revers, exemplaires identiques) = repoussée (bench
front/back trop mince). Cf. census-detector-design.md.

Découplé du crop. Toutes les boîtes sont (x1, y1, x2, y2) en pixels natifs.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import cv2
import numpy as np

ML_DIR = Path(__file__).resolve().parents[1]
COINNESS_BANK_PATH = ML_DIR / "state" / "foundation_coinness.npz"

Box = tuple[float, float, float, float]

# Structure-guard : mean(|Laplacian|) min pour un crop « pièce » (relief/design).
# Repris de la calibration normalize_snap (_STRUCTURE_MIN_LAP_MEANABS=32 ; on prend
# un plancher plus bas ici car le crop boîte n'est pas masqué/centré pareil — c'est
# un pré-filtre cheap contre les crops quasi-uniformes, pas le juge principal).
_STRUCT_MIN_LAP = 18.0


# ---------------------------------------------------------------------------
# ① NMS-concentrique
# ---------------------------------------------------------------------------

def _iou(a: Box, b: Box) -> float:
    ix1, iy1 = max(a[0], b[0]), max(a[1], b[1])
    ix2, iy2 = min(a[2], b[2]), min(a[3], b[3])
    iw, ih = max(0.0, ix2 - ix1), max(0.0, iy2 - iy1)
    inter = iw * ih
    ua = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / ua if ua > 0 else 0.0


def _center_in(small: Box, big: Box) -> bool:
    cx, cy = (small[0] + small[2]) / 2.0, (small[1] + small[3]) / 2.0
    return big[0] <= cx <= big[2] and big[1] <= cy <= big[3]


def _area(z: Box) -> float:
    return (z[2] - z[0]) * (z[3] - z[1])


def _touches_edge(box: Box, w: int, h: int, frac: float = 0.01) -> bool:
    m = frac * min(w, h)
    return box[0] <= m or box[1] <= m or box[2] >= w - m or box[3] >= h - m


def nms_concentric(boxes: list[Box], iou_thr: float = 0.30,
                   absorb_ratio: float = 0.70,
                   img_wh: tuple[int, int] | None = None) -> list[Box]:
    """Fusionne les boîtes concentriques/contenues, garde la plus grande.

    Une boîte candidate est absorbée par une boîte déjà gardée si :
      - son centre est DANS la gardée **ET** elle est nettement plus petite
        (`aire < absorb_ratio × aire gardée`) → vrai fragment / anneau bimétal interne ;
      - OU l'IoU dépasse `iou_thr` (doublon partiel).
    Deux gardes contre la fusion de **2 pièces distinctes d'un lot** (asymétrie de
    coût : un faux-single = poison, un faux-lot = review → dans le doute on ne fusionne
    pas) :
      - **taille** : un candidat de taille comparable (≥ `absorb_ratio`) n'est jamais
        absorbé par `_center_in` ;
      - **bord** (si `img_wh` fourni) : un candidat qui touche le bord d'image est une
        pièce potentiellement coupée/partielle, pas un fragment → jamais absorbé.
        Couvre le cas audité `172ac301` (2 boîtes larges débordantes, IoU 0.41).
    Glouton par aire décroissante (la plus grande = rim externe). Pur géométrique.
    """
    kept: list[Box] = []
    for b in sorted(boxes, key=_area, reverse=True):
        if img_wh is not None and _touches_edge(b, img_wh[0], img_wh[1]):
            kept.append(b)
            continue
        ab = _area(b)
        absorbed = False
        for k in kept:
            if (_center_in(b, k) and ab < absorb_ratio * _area(k)) or _iou(b, k) > iou_thr:
                absorbed = True
                break
        if not absorbed:
            kept.append(b)
    return kept


# ---------------------------------------------------------------------------
# ② is_coin (sim DINO vs banque coin-ness + structure-guard)
# ---------------------------------------------------------------------------

_bank_cache: dict[str, Any] = {}
_dino_cache: dict[str, Any] = {}


def load_coinness_bank(path: Path | str = COINNESS_BANK_PATH) -> np.ndarray:
    """Matrice (N, D) L2-normalisée de la banque coin-ness.

    Lève `RuntimeError` si la banque est absente — l'étage ② en dépend, et un
    fallback silencieux (banque vide → 0 pièce partout → tout routé single) serait
    une dette cachée interdite par R0.
    """
    key = str(path)
    if key not in _bank_cache:
        p = Path(path)
        if not p.exists():
            raise RuntimeError(
                f"Banque coin-ness absente: {p}. La générer via "
                "`scripts/build_coinness_bank.py` (étage ② is_coin requis)."
            )
        npz = np.load(p, allow_pickle=False)
        _bank_cache[key] = np.asarray(npz["matrix"], dtype=np.float32)
    return _bank_cache[key]


def _get_dino():
    if not _dino_cache:
        from foundation.encoder import build_transform, load_encoder
        enc, dev = load_encoder()
        _dino_cache["enc"], _dino_cache["dev"], _dino_cache["tf"] = enc, dev, build_transform()
    return _dino_cache["enc"], _dino_cache["dev"], _dino_cache["tf"]


def _box_structure(bgr: np.ndarray, box: Box) -> float:
    """mean(|Laplacian|) sur le crop boîte — proxy cheap de « relief/design »."""
    x1, y1, x2, y2 = (int(round(v)) for v in box)
    x1, y1 = max(0, x1), max(0, y1)
    crop = bgr[y1:y2, x1:x2]
    if crop.size == 0 or min(crop.shape[:2]) < 4:
        return 0.0
    gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
    return float(np.abs(cv2.Laplacian(gray, cv2.CV_32F, ksize=3)).mean())


def coinness_scores(bgr: np.ndarray, boxes: list[Box],
                    bank: np.ndarray | None = None) -> list[float]:
    """Sim DINO max à la banque coin-ness, par boîte (batch). [] si banque vide."""
    if bank is None:
        bank = load_coinness_bank()
    if not boxes:
        return []
    import torch
    from PIL import Image
    enc, dev, tf = _get_dino()
    crops = []
    for b in boxes:
        x1, y1, x2, y2 = (int(round(v)) for v in b)
        x1, y1 = max(0, x1), max(0, y1)
        crop = bgr[y1:y2, x1:x2]
        if crop.size == 0:
            crop = np.zeros((8, 8, 3), np.uint8)
        crops.append(Image.fromarray(cv2.cvtColor(crop, cv2.COLOR_BGR2RGB)))
    with torch.no_grad():
        t = torch.stack([tf(c) for c in crops]).to(dev)
        feat = torch.nn.functional.normalize(enc(t), dim=1).cpu().numpy()
    sims = feat @ bank.T
    return [float(sims[i].max()) for i in range(len(boxes))]


def coin_signals(bgr: np.ndarray, boxes: list[Box],
                 bank: np.ndarray | None = None) -> tuple[list[float], list[float]]:
    """(sims DINO, structures) par boîte — signaux bruts pour calibrer τ (bench)."""
    sims = coinness_scores(bgr, boxes, bank=bank)
    structs = [_box_structure(bgr, b) for b in boxes]
    return sims, structs


def is_coin_mask(bgr: np.ndarray, boxes: list[Box], tau: float,
                 bank: np.ndarray | None = None,
                 struct_min: float = _STRUCT_MIN_LAP) -> list[bool]:
    """True par boîte si « pièce » : structure-guard passé ET sim DINO ≥ τ."""
    scores = coinness_scores(bgr, boxes, bank=bank)
    out = []
    for b, s in zip(boxes, scores):
        out.append(s >= tau and _box_structure(bgr, b) >= struct_min)
    return out


# ---------------------------------------------------------------------------
# Ladder complet → compte
# ---------------------------------------------------------------------------

def census_count(bgr: np.ndarray, yolo_boxes: list[Box], tau: float,
                 bank: np.ndarray | None = None,
                 iou_thr: float = 0.30) -> int:
    """① nms_concentric → ② is_coin → nombre de pièces distinctes."""
    h, w = bgr.shape[:2]
    deduped = nms_concentric(yolo_boxes, iou_thr=iou_thr, img_wh=(w, h))
    keep = is_coin_mask(bgr, deduped, tau, bank=bank)
    return sum(keep)
