"""Isole la/les pièce(s) d'une image BCE.

Constat empirique (survey 22 images, années 2004→2024) :
- Toutes les images BCE sont carrées (270×270 pré-2015, 540×540 sinon).
- Une seule pièce par image (le national side / obverse), remplissant
  92-99 % du cadre — il reste typiquement 1-8 % de marge blanche.
- Le scénario "2 disques côte-à-côte" évoqué dans le kickoff n'a pas
  été observé. On garde cependant un fallback aspect-ratio pour ne pas
  perdre une éventuelle évolution future du format BCE.

Tight-crop par Hough du disque central : pour standardiser à un cadre
exactement à la taille du rim (+ petit padding) on évite que les
canoniques BCE traînent une marge variable selon le millésime.

Sortie : ``list[BceCrop]`` — typiquement 1 entrée ``role="obverse"``.
La normalisation finale (resize 400 / 120 + encode WebP) est faite par
``canonical_image_local.write_variants``, qui prend ces bytes en entrée.
"""

from __future__ import annotations

import io
from dataclasses import dataclass

import cv2
import numpy as np

# Si AR (w/h) sort de cette plage on suspecte une image multi-coins :
# au-delà de 1.4 on tente de splitter en deux moitiés gauche/droite.
_SQUARE_AR_TOLERANCE = 0.20  # AR ∈ [0.83, 1.20] = "carré-ish"
_WIDE_AR_THRESHOLD = 1.40    # ≥ 1.4 → côte-à-côte horizontal
_TALL_AR_THRESHOLD = 0.70    # ≤ 0.7 → empilé vertical (jamais vu, mais symétrique)

# Hough tight-crop : padding autour du rim détecté (en fraction du rayon).
# 3 % garde une fine marge pour ne pas couper un rim arrondi par compression.
_TIGHT_CROP_PADDING = 0.03

# Bornes Hough en fraction du côté court de l'image. Une pièce BCE
# remplit 70-99% du cadre → r ∈ [0.35 × short, 0.50 × short].
_HOUGH_R_MIN_FRAC = 0.35
_HOUGH_R_MAX_FRAC = 0.50


@dataclass
class BceCrop:
    role: str            # 'obverse' | 'reverse'
    image_bytes: bytes   # JPEG bytes — passable à `encode_webp` direct
    width: int
    height: int


def _encode_jpeg(bgr: np.ndarray, quality: int = 92) -> bytes:
    ok, buf = cv2.imencode(".jpg", bgr, [int(cv2.IMWRITE_JPEG_QUALITY), quality])
    if not ok:
        raise ValueError("cv2.imencode JPEG failed")
    return buf.tobytes()


def _tight_crop_disc(bgr: np.ndarray, *, padding: float = _TIGHT_CROP_PADDING) -> np.ndarray:
    """Retourne le sous-carré centré sur le disque détecté par Hough.

    Pas de cercle trouvé → on rend l'image inchangée (les bytes sont
    perdus de toute façon, c'est le caller qui décide quoi en faire).
    """
    h, w = bgr.shape[:2]
    short = min(h, w)
    gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
    blurred = cv2.medianBlur(gray, 5)
    circles = cv2.HoughCircles(
        blurred, cv2.HOUGH_GRADIENT, dp=1.0,
        minDist=max(1, short // 2),
        param1=80, param2=40,
        minRadius=int(short * _HOUGH_R_MIN_FRAC),
        maxRadius=int(short * _HOUGH_R_MAX_FRAC),
    )
    if circles is None or len(circles[0]) == 0:
        return bgr
    cx, cy, r = (int(v) for v in circles[0][0])
    rr = r + int(round(r * padding))
    x0 = max(0, cx - rr)
    y0 = max(0, cy - rr)
    x1 = min(w, cx + rr)
    y1 = min(h, cy + rr)
    crop = bgr[y0:y1, x0:x1]
    if crop.size == 0:
        return bgr
    return crop


def crop_coins_from_bytes(image_bytes: bytes) -> list[BceCrop]:
    """Décode l'image BCE et retourne 1 ou 2 BceCrop.

    Une image carrée → 1 crop ``obverse`` (bytes intacts pour préserver
    la qualité originale, pas de re-encode inutile). Une image large
    (côte-à-côte) → 2 crops ``obverse`` puis ``reverse`` (split médian).

    Lève ``ValueError`` si l'image est non décodable ou vide.
    """
    if not image_bytes:
        raise ValueError("empty image bytes")
    arr = np.frombuffer(image_bytes, dtype=np.uint8)
    bgr = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    if bgr is None or bgr.size == 0:
        raise ValueError("cv2.imdecode failed (not an image?)")
    h, w = bgr.shape[:2]
    ar = w / h

    # Cas commun : image carrée. Tight-crop Hough centré sur le disque
    # détecté, puis ré-encode en JPEG. Si Hough rate (très rare en
    # pratique), on tombe sur les bytes originaux.
    if 1 - _SQUARE_AR_TOLERANCE <= ar <= 1 + _SQUARE_AR_TOLERANCE:
        tight = _tight_crop_disc(bgr)
        out_bytes = (
            _encode_jpeg(tight) if tight.shape != bgr.shape else image_bytes
        )
        return [BceCrop(role="obverse", image_bytes=out_bytes,
                        width=tight.shape[1], height=tight.shape[0])]

    # Cas large : 2 pièces côte-à-côte horizontales. obverse=gauche.
    # On tight-crop chaque moitié séparément.
    if ar >= _WIDE_AR_THRESHOLD:
        mid = w // 2
        left = _tight_crop_disc(bgr[:, :mid])
        right = _tight_crop_disc(bgr[:, mid:])
        return [
            BceCrop(role="obverse", image_bytes=_encode_jpeg(left),
                    width=left.shape[1], height=left.shape[0]),
            BceCrop(role="reverse", image_bytes=_encode_jpeg(right),
                    width=right.shape[1], height=right.shape[0]),
        ]

    # Cas haut : 2 pièces empilées (jamais observé, symétrie défensive).
    if ar <= _TALL_AR_THRESHOLD:
        mid = h // 2
        top = _tight_crop_disc(bgr[:mid, :])
        bot = _tight_crop_disc(bgr[mid:, :])
        return [
            BceCrop(role="obverse", image_bytes=_encode_jpeg(top),
                    width=top.shape[1], height=top.shape[0]),
            BceCrop(role="reverse", image_bytes=_encode_jpeg(bot),
                    width=bot.shape[1], height=bot.shape[0]),
        ]

    # AR atypique mais pas franchement non plus (entre 1.20 et 1.40 ou
    # entre 0.70 et 0.83) : on traite comme un single coin en l'état
    # plutôt que de splitter un cadre limite. Rare en pratique.
    tight = _tight_crop_disc(bgr)
    out_bytes = _encode_jpeg(tight) if tight.shape != bgr.shape else image_bytes
    return [BceCrop(role="obverse", image_bytes=out_bytes,
                    width=tight.shape[1], height=tight.shape[0])]
