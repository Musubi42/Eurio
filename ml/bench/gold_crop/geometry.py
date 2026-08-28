"""L'ellipse d'or et ce qu'on en dérive. **Rien ici ne lit la sortie d'une méthode.**

C'est la règle fondatrice de `JUGE.md` : toute grandeur du juge se calcule à
partir de `E_gold`. Un module qui n'a accès qu'à l'or ne peut pas être
optimisé par ce qu'on lui compare.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import cv2
import numpy as np


@dataclass(frozen=True)
class Ellipse:
    """Demi-axes en pixels natifs. `theta` = orientation du GRAND axe, radians."""

    cx: float
    cy: float
    a: float          # demi-grand axe
    b: float          # demi-petit axe
    theta: float

    @classmethod
    def depuis_degres(cls, cx, cy, a, b, angle_deg) -> "Ellipse":
        if b > a:                                  # on garde a ≥ b, quoi qu'il arrive
            a, b, angle_deg = b, a, angle_deg + 90.0
        return cls(float(cx), float(cy), float(a), float(b),
                   math.radians(float(angle_deg)))

    @classmethod
    def depuis_cercle(cls, cx, cy, r) -> "Ellipse":
        return cls(float(cx), float(cy), float(r), float(r), 0.0)

    def contour(self, n: int = 360) -> np.ndarray:
        """`n` points du contour, échantillonnés à pas d'angle PARAMÉTRIQUE constant.

        ⚠️ Ce n'est pas un pas angulaire constant vu du centre : sur une ellipse
        très aplatie les deux diffèrent. C1 échantillonne « 360 directions » —
        le paramétrique couvre le contour uniformément en longueur d'arc bien
        mieux que l'angle polaire, qui se concentre sur le petit axe.
        """
        t = np.linspace(0.0, 2 * np.pi, n, endpoint=False)
        ct, st = math.cos(self.theta), math.sin(self.theta)
        u, v = self.a * np.cos(t), self.b * np.sin(t)
        return np.column_stack([self.cx + u * ct - v * st,
                                self.cy + u * st + v * ct])

    def rayon_elliptique(self, x, y) -> np.ndarray:
        """ρ = 1 sur le contour, < 1 dedans. C'est le repère de l'anneau de C2."""
        ct, st = math.cos(self.theta), math.sin(self.theta)
        dx, dy = np.asarray(x) - self.cx, np.asarray(y) - self.cy
        u = dx * ct + dy * st
        v = -dx * st + dy * ct
        return np.hypot(u / self.a, v / self.b)

    def masque(self, forme: tuple[int, int], echelle: float = 1.0,
               origine: tuple[float, float] = (0.0, 0.0)) -> np.ndarray:
        """Masque binaire de l'ellipse, éventuellement mise à l'échelle.

        `origine` puis `echelle` : le point natif `p` tombe en
        `(p - origine) * echelle`. Sert à reprojeter `E_gold` dans le crop 224.
        """
        h, w = forme
        cx = (self.cx - origine[0]) * echelle
        cy = (self.cy - origine[1]) * echelle
        m = np.zeros((h, w), np.uint8)
        cv2.ellipse(m, (int(round(cx)), int(round(cy))),
                    (max(1, int(round(self.a * echelle))),
                     max(1, int(round(self.b * echelle)))),
                    math.degrees(self.theta), 0, 360, 1, -1)
        return m

    def mise_a_l_echelle(self, echelle: float,
                         origine: tuple[float, float] = (0.0, 0.0)) -> "Ellipse":
        return Ellipse((self.cx - origine[0]) * echelle,
                       (self.cy - origine[1]) * echelle,
                       self.a * echelle, self.b * echelle, self.theta)


@dataclass(frozen=True)
class Cercle:
    """La sortie d'une méthode : le format n'autorise qu'un cercle (ADR-017)."""

    cx: float
    cy: float
    r: float

    def masque(self, forme: tuple[int, int], echelle: float = 1.0,
               origine: tuple[float, float] = (0.0, 0.0)) -> np.ndarray:
        h, w = forme
        m = np.zeros((h, w), np.uint8)
        rr = max(1, int(round(self.r * echelle)))
        # `cv2.ellipse` et non `cv2.circle` : les deux rastérisent différemment,
        # et la bande de bord est assez fine pour que l'écart s'y voie (1,4 %
        # de Boundary IoU sur deux formes IDENTIQUES). Le juge compare un
        # disque à une ellipse : il leur faut le même rastériseur.
        cv2.ellipse(m, (int(round((self.cx - origine[0]) * echelle)),
                        int(round((self.cy - origine[1]) * echelle))),
                    (rr, rr), 0.0, 0, 360, 1, -1)
        return m


def bande_de_bord(masque: np.ndarray, d_px: float) -> np.ndarray:
    """Les pixels du masque à moins de `d_px` de son bord.

    C'est `G_d ∩ G` de Cheng et al. (CVPR 2021), calculé par transformée de
    distance — strictement équivalent à l'érosion par un disque de rayon `d`,
    et sans le biais d'un élément structurant carré.
    """
    if d_px <= 0:
        return masque.astype(bool)
    bordé = cv2.copyMakeBorder(masque.astype(np.uint8), 1, 1, 1, 1,
                               cv2.BORDER_CONSTANT, value=0)
    dist = cv2.distanceTransform(bordé, cv2.DIST_L2, 5)[1:-1, 1:-1]
    return (masque > 0) & (dist < d_px)
