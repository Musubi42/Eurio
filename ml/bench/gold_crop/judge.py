"""Le juge — C1, C2, Boundary IoU. Rien ici ne lit ce que la méthode « pense ».

Toute grandeur part de `E_gold` et de la géométrie que la méthode propose
(`cx, cy, r`). Aucune ne part d'un score que la méthode calcule sur sa propre
sortie : c'est ce qui a manqué aux sept chantiers (cf. `PROBLEME.md`).

⚠️ **C2 est inerte sur ce format, et c'est mesuré** — cf. `mesurer_c2_par_k()`
et `DECISIONS.md` §D8. Elle reste calculée et journalisée : RE-3 interdit de
retirer un critère sans amendement daté. Elle n'entre pas dans
`amputation_rate` tant que le PO n'a pas tranché.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field

import cv2
import numpy as np

from bench.gold_crop.geometry import Cercle, Ellipse, bande_de_bord
from vision.normalize_snap import COIN_MARGIN

# Les seuils de `JUGE.md`, à figer par le PO (RE-1).
M_MARGE = 0.02          # C1 — la marge que `normalize_snap.COIN_MARGIN` promet
ARC_MIN = 11 / 12       # C2 — un secteur de tolérance
D_FRAC = 0.08           # Boundary IoU — la médiane mesurée du listel nu (D4)

# Sur QUELLE région C1 mesure-t-elle la marge ? Les trois sont journalisées ;
# celle-ci décide de `C1_ok`. Cf. `DECISIONS.md` §D9 — question ouverte au PO.
#   "retenu" : disque(r) ∩ cadre — ce qui reste réellement après le masque dur
#   "cadre"  : le carré seul — la lettre de `JUGE.md` §C1
#   "disque" : le masque seul
REGION_C1 = "retenu"

# L'anneau de C2, repris de `measure_tilt` (`crop_detectors.py:321-322`).
RING_LO, RING_HI = 0.70, 1.15
N_SECTEURS = 12
JUGE_VERSION = 1


@dataclass
class Cadre:
    """Le carré effectivement découpé par `_crop_mask_resize_float`."""

    x0: float
    y0: float
    x1: float
    y1: float
    tronque: bool           # le bord de l'image a rogné le cadre demandé


def cadre_decoupe(pred: Cercle, largeur: int, hauteur: int,
                  marge_frac: float = COIN_MARGIN) -> Cadre:
    """Réplique EXACTE des bornes de `vision/normalize_snap._crop_mask_resize_float`.

    Le juge ne peut pas se contenter du cercle demandé : la prod **clampe** le
    cadre sur le bord de l'image puis le rend carré **en l'ancrant en haut à
    gauche** (`x1 = x0 + side`). Une pièce près du bord reçoit donc un cadre
    décentré — un défaut de cadrage que seul ce calcul rend visible.

    `ml/tests/test_gold_crop_judge.py` compare ce cadre au `crop_side` que la
    prod journalise : si l'un dérive, le test tombe.
    """
    half = pred.r * (1.0 + marge_frac)
    x0 = max(0.0, pred.cx - half)
    y0 = max(0.0, pred.cy - half)
    x1 = min(float(largeur), pred.cx + half)
    y1 = min(float(hauteur), pred.cy + half)
    side = min(x1 - x0, y1 - y0)
    demande = 2.0 * half
    return Cadre(x0, y0, x0 + side, y0 + side, tronque=side < demande - 1e-6)


def c1(gold: Ellipse, pred: Cercle, largeur: int, hauteur: int,
       n_directions: int = 360, marge_frac: float = COIN_MARGIN) -> dict:
    """La marge intérieure, dans les deux lectures possibles — et elles diffèrent.

    Pour chacun des `n_directions` points du contour d'or, on mesure sa distance
    signée au bord de ce qui est **conservé**. Deux régions candidates :

    * `retenu` = disque(cx, cy, r) ∩ cadre — ce qui **reste réellement** dans le
      crop, le masque circulaire dur ayant noirci le dehors du disque ;
    * `cadre` = le carré seul — la lettre de `JUGE.md` §C1.

    Elles ne coïncident pas : le carré a un demi-côté `1,02·r`, donc il est plus
    permissif que le disque dans les diagonales (jusqu'à 44 %). Une pièce peut
    tenir dans le carré et être **amputée par le masque**. Inversement, une
    détection parfaite (`r = a`) satisfait exactement `cadre ≥ 0,02·a` mais rend
    `retenu = 0` : le masque coupe pile sur le listel.

    Les deux sont journalisées. Laquelle porte `C1_ok` est un choix de seuil,
    donc du PO (RE-1) : `ok` suit `retenu`, qui est celle qui compte des pixels.
    """
    cadre = cadre_decoupe(pred, largeur, hauteur, marge_frac)
    P = gold.contour(n_directions)
    dx, dy = P[:, 0] - pred.cx, P[:, 1] - pred.cy
    d_disque = pred.r - np.hypot(dx, dy)
    d_cadre = np.minimum.reduce([P[:, 0] - cadre.x0, cadre.x1 - P[:, 0],
                                 P[:, 1] - cadre.y0, cadre.y1 - P[:, 1]])
    d_retenu = np.minimum(d_disque, d_cadre)
    return {
        "C1_marge_min_frac": float(d_retenu.min() / gold.a),
        "C1_cadre_marge_min_frac": float(d_cadre.min() / gold.a),
        "C1_disque_marge_min_frac": float(d_disque.min() / gold.a),
        "C1_cadre_tronque": cadre.tronque,
    }


def _arc_coverage(image: np.ndarray, gold_dans_image: Ellipse,
                  ring_lo: float, ring_hi: float) -> dict:
    """Les 12 secteurs de `measure_tilt`, recalculés sur l'image de sortie.

    Seuils Canny adaptatifs (médiane ± 0,5×médiane) comme dans le code existant :
    neutres vis-à-vis du cadrage.
    """
    gris = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY) if image.ndim == 3 else image
    med = float(np.median(gris))
    bords = cv2.Canny(gris, max(0.0, med * 0.5), min(255.0, med * 1.5))
    ys, xs = np.nonzero(bords)
    if not len(xs):
        return {"arc_coverage": 0.0, "n_ring": 0}
    rho = gold_dans_image.rayon_elliptique(xs, ys)
    dans = (rho >= ring_lo) & (rho <= ring_hi)
    n = int(dans.sum())
    if n == 0:
        return {"arc_coverage": 0.0, "n_ring": 0}
    ang = np.degrees(np.arctan2(ys[dans] - gold_dans_image.cy,
                                xs[dans] - gold_dans_image.cx)) % 360.0
    # `% 360.0` rend EXACTEMENT 360.0 pour un angle négatif infinitésimal, d'où
    # un 13ᵉ secteur et une couverture de 13/12. Le `% N_SECTEURS` le referme.
    # ⚠️ `measure_tilt` (`crop_detectors.py:415`) porte le même défaut latent ;
    # là-bas il ne fait que rendre la garde plus permissive. Ici il casserait
    # la borne supérieure de C2.
    occupes = len(set((ang // (360.0 / N_SECTEURS)).astype(int) % N_SECTEURS))
    return {"arc_coverage": occupes / N_SECTEURS, "n_ring": n}


def c2(sortie_224: np.ndarray, gold: Ellipse, cadre: Cadre,
       ring_lo: float = RING_LO, ring_hi: float = RING_HI) -> dict:
    """C2 sur l'image de sortie, l'anneau étant défini par `E_gold` REPROJETÉE.

    Le centre et le rayon de l'anneau viennent de l'or, jamais d'un `fitEllipse`
    refait sur le candidat — sinon la méthode déplacerait l'ellipse pour remplir
    ses secteurs.

    ⚠️ **Mesuré inerte** : l'anneau `[0,70 ; 1,15]` englobe la jonction
    bimétallique (ρ ≈ 0,735, cf. SUIVI « rapport de rayons réel 0,735 »), un
    cercle de contraste toujours présent qui remplit les 12 secteurs quel que
    soit le cadrage. `arc_coverage` vaut 1,000 jusqu'à 25 % d'amputation.
    """
    x0i, y0i = int(round(cadre.x0)), int(round(cadre.y0))
    x1i = int(round(cadre.x1))
    cote = max(1, x1i - x0i)
    echelle = sortie_224.shape[0] / cote
    return _arc_coverage(sortie_224, gold.mise_a_l_echelle(echelle, (x0i, y0i)),
                         ring_lo, ring_hi)


def _grille(gold: Ellipse, pred: Cercle, marge_px: float) -> tuple[tuple, tuple, float]:
    """Fenêtre commune aux deux formes, en pixels natifs (pas de sous-échantillonnage)."""
    xs = [gold.cx - gold.a, gold.cx + gold.a, pred.cx - pred.r, pred.cx + pred.r]
    ys = [gold.cy - gold.a, gold.cy + gold.a, pred.cy - pred.r, pred.cy + pred.r]
    x0, y0 = min(xs) - marge_px, min(ys) - marge_px
    w = int(math.ceil(max(xs) - x0 + marge_px))
    h = int(math.ceil(max(ys) - y0 + marge_px))
    return (h, w), (x0, y0), 1.0


def metriques_de_surface(gold: Ellipse, pred: Cercle,
                         d_frac: float = D_FRAC) -> dict:
    """Boundary IoU (principale), IoU de masque (log) et Hausdorff (diagnostic).

    **`d` est ancré sur l'or : `d = d_frac · a_gold`, en pixels, identique pour
    les deux formes.** C'est la règle fondatrice appliquée à la métrique : une
    bande dont la largeur suivrait le rayon PRÉDIT serait une grandeur calculée
    sur la sortie de la méthode, et une méthode qui rétrécit rétrécirait sa
    propre bande.

    ⚠️ La table de `JUGE.md` (0,464 à 3 %, 0,148 à 6 %) a été calculée avec une
    bande proportionnelle à CHAQUE forme. Avec `d` ancré sur l'or, on lit 0,454
    et 0,143 — l'écart est inférieur à 0,01 et ne change aucun classement, mais
    la convention doit être dite. Verrouillé par
    `test_gold_crop_judge.py::test_les_deux_conventions_de_bande`.
    """
    d_px = d_frac * gold.a
    forme, origine, _ = _grille(gold, pred, marge_px=d_px + 4.0)
    mg = gold.masque(forme, 1.0, origine)
    mp = pred.masque(forme, 1.0, origine)
    bg = bande_de_bord(mg, d_px)
    bp = bande_de_bord(mp, d_px)
    inter_b = int(np.count_nonzero(bg & bp))
    union_b = int(np.count_nonzero(bg | bp))
    inter_m = int(np.count_nonzero((mg > 0) & (mp > 0)))
    union_m = int(np.count_nonzero((mg > 0) | (mp > 0)))
    return {
        "boundary_iou": inter_b / union_b if union_b else 0.0,
        "mask_iou": inter_m / union_m if union_m else 0.0,
        "hausdorff_frac": _hausdorff_frac(gold, pred),
    }


def _hausdorff_frac(gold: Ellipse, pred: Cercle, n: int = 720) -> float:
    """Distance de Hausdorff entre les deux contours, en fraction de `a_gold`.

    **Diagnostic seulement.** C'est un maximum : un seul point aberrant la fait
    exploser. Utile pour voir *où* ça dérape, jamais pour classer.
    """
    P = gold.contour(n)
    t = np.linspace(0.0, 2 * np.pi, n, endpoint=False)
    Q = np.column_stack([pred.cx + pred.r * np.cos(t), pred.cy + pred.r * np.sin(t)])
    d = np.hypot(P[:, None, 0] - Q[None, :, 0], P[:, None, 1] - Q[None, :, 1])
    return float(max(d.min(axis=1).max(), d.min(axis=0).max()) / gold.a)


@dataclass
class Verdict:
    asset_id: str
    strate: str
    strate_confirmee: str | None
    verdict_humain: str
    gold: dict
    pred: dict
    mesures: dict = field(default_factory=dict)
    C1_ok: bool = False
    C2_ok: bool = False
    ampute: bool = False

    def a_plat(self) -> dict:
        d = asdict(self)
        d.update(d.pop("mesures"))
        return d


_CLE_REGION = {"retenu": "C1_marge_min_frac", "cadre": "C1_cadre_marge_min_frac",
               "disque": "C1_disque_marge_min_frac"}


def juger(gold: Ellipse, pred: Cercle, raw_hw: tuple[int, int],
          sortie_224: np.ndarray | None = None, *,
          m: float = M_MARGE, arc_min: float = ARC_MIN, d_frac: float = D_FRAC,
          c2_compte: bool = False, region: str = REGION_C1) -> dict:
    """Toutes les grandeurs d'un cas. `c2_compte` : C2 entre-t-elle dans `ampute` ?

    Elle n'y entre pas par défaut — cf. D8 : mesurée inerte, en attente
    d'amendement PO. La journaliser sans la faire compter est la seule façon
    honnête de tenir RE-3 sans laisser un critère mort décider.
    """
    h, w = raw_hw
    # `m` est le seuil du JUGE ; `COIN_MARGIN` est la marge que la PROD applique
    # au cadre. Les deux valent 0,02 aujourd'hui et ce n'est pas une coïncidence
    # (« le juge exige ce que le code promet ») — mais ce sont deux réglages
    # distincts, et les confondre ferait bouger le cadre quand on bouge le seuil.
    mes = c1(gold, pred, w, h)
    mes.update(metriques_de_surface(gold, pred, d_frac))
    if region not in _CLE_REGION:
        raise ValueError(f"région C1 inconnue : {region!r} "
                         f"(attendu : {sorted(_CLE_REGION)})")
    mes["C1_region"] = region
    # tolérance de bruit flottant : une détection EXACTE (`r = a`, cercle
    # parfait) rend une marge de −1e-13 au lieu de 0, et `m = 0` la déclarerait
    # amputée. 1e-9 en fraction de `a`, soit 4e-7 px sur une pièce de 400 px :
    # ça n'absorbe que du bruit, jamais un pixel.
    C1_ok = mes[_CLE_REGION[region]] >= m - 1e-9
    C2_ok = True
    if sortie_224 is not None:
        mes.update(c2(sortie_224, gold, cadre_decoupe(pred, w, h)))
        C2_ok = mes["arc_coverage"] >= arc_min - 1e-9
    mes["C1_ok"] = C1_ok
    mes["C2_ok"] = C2_ok
    mes["ampute"] = (not C1_ok) or (c2_compte and not C2_ok)
    return mes
