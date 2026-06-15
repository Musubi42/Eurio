"""Primitifs partagés du banc crop-recovery : chemins, chargement raw, crop, score
(probe GELÉE), IoU. Aucune stratégie n'importe ailleurs que d'ici + iface.py.
"""

from __future__ import annotations

import math
from pathlib import Path

import cv2
import numpy as np

ML_DIR = Path(__file__).resolve().parents[2]
DB_PATH = ML_DIR / "state" / "eurio.db"
STATE_DIR = ML_DIR / "state" / "crop_recovery"
RUN_ID = "fa8a9af939ce43e6a3eee6842ecae170"
TAU = 0.55  # seuil probe gelé, figé pour tout le chantier

_RAW_BUCKET = "enrichment-raws"


def load_raw(key_or_path: str) -> np.ndarray | None:
    """Charge un raw : clé bucket `enrichment-raws` OU chemin local absolu
    (fragments synthétiques D3b). Retourne BGR ou None."""
    p = Path(key_or_path)
    if p.is_absolute() and p.exists():
        return cv2.imread(str(p), cv2.IMREAD_COLOR)
    from shared.storage.local_cache import local_path
    try:
        return cv2.imread(str(local_path(_RAW_BUCKET, key_or_path)), cv2.IMREAD_COLOR)
    except Exception:
        return None


def crop_candidate(raw_bgr: np.ndarray, cx: float, cy: float, r: float) -> np.ndarray | None:
    """Crop 224 masque dur, EXACTEMENT le format prod (`_crop_mask_resize_int`)."""
    from vision.normalize_snap import CropConfig, _crop_mask_resize_int
    res = _crop_mask_resize_int(raw_bgr, int(round(cx)), int(round(cy)), int(round(r)),
                                method="bench", config=CropConfig())
    return res.image


def score_crops(imgs: list[np.ndarray]) -> list[float]:
    """Probe GELÉE (oracle). P(face entière) par crop 224 BGR."""
    if not imgs:
        return []
    from vision.census import face_scores
    return face_scores(imgs)


def detect_hint(raw_bgr: np.ndarray) -> dict | None:
    """Détection prod = point de départ des stratégies. Renvoie le hint de la pièce
    dominante {cx, cy, r_final, r_bbox} ou None si rien d'exploitable."""
    from vision.normalize_snap import detect_circles_multi
    H, W = raw_bgr.shape[:2]
    short = min(H, W)
    trace: list[dict] = []
    detect_circles_multi(raw_bgr, census=True, trace=trace)
    cand = [t for t in trace if t["accepted"] and t["r_bbox"] > 0]
    if not cand:
        # fallback : la plus grosse détection même rejetée par rayon
        cand = [t for t in trace if t["r_bbox"] > 0]
    if not cand:
        return None
    t = max(cand, key=lambda x: x["r_bbox"])
    return {"cx": float(t["cx"]), "cy": float(t["cy"]),
            "r_final": float(t["r_final"]), "r_bbox": float(t["r_bbox"]),
            "short": short}


def iou_circles(c1: tuple[float, float, float], c2: tuple[float, float, float]) -> float:
    """IoU de deux disques (cx, cy, r). Forme fermée."""
    (x1, y1, r1), (x2, y2, r2) = c1, c2
    if r1 <= 0 or r2 <= 0:
        return 0.0
    d = math.hypot(x1 - x2, y1 - y2)
    if d >= r1 + r2:
        return 0.0
    if d <= abs(r1 - r2):
        rmin, rmax = (r1, r2) if r1 < r2 else (r2, r1)
        return (rmin * rmin) / (rmax * rmax)
    r1s, r2s, ds = r1 * r1, r2 * r2, d * d
    a1 = math.acos((ds + r1s - r2s) / (2 * d * r1))
    a2 = math.acos((ds + r2s - r1s) / (2 * d * r2))
    inter = r1s * (a1 - math.sin(2 * a1) / 2) + r2s * (a2 - math.sin(2 * a2) / 2)
    union = math.pi * (r1s + r2s) - inter
    return float(inter / union) if union > 0 else 0.0


def circle_from_bbox(bbox: dict) -> tuple[float, float, float]:
    """Cercle inscrit du rectangle humain {x, y, w, h} → (cx, cy, r) natif."""
    x, y, w, h = bbox["x"], bbox["y"], bbox["w"], bbox["h"]
    return (x + w / 2.0, y + h / 2.0, min(w, h) / 2.0)
