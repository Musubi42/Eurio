"""La mesure de la bande lisse tient-elle sur une pièce dont on connaît la géométrie ?

Le module qu'on teste sert à trancher un seuil du juge (`d = 0,08·a`). Le
vérifier sur les canoniques ne prouve rien : on n'y connaît pas la vérité. On
fabrique donc une pièce de synthèse dont on **pose** le rayon et la pointe des
étoiles, et on demande à la mesure de les retrouver.
"""

from __future__ import annotations

import cv2
import numpy as np
import pytest

from bench.gold_crop.measure_listel import bande_lisse, fit_coin_edge

TAILLE = 700
CENTRE = (350.0, 348.0)
RAYON = 280.0


def _piece(n_etoiles: int = 12, f_pointe: float = 0.90, aplati: float = 1.0,
           rot_deg: float = 0.0) -> np.ndarray:
    """Disque gris sur fond blanc, avec `n_etoiles` dont la pointe atteint `f_pointe·R`."""
    img = np.full((TAILLE, TAILLE, 3), 250, np.uint8)
    cx, cy = CENTRE
    b = RAYON * aplati
    cv2.ellipse(img, (int(cx), int(cy)), (int(RAYON), int(b)), 0, 0, 360, (150, 150, 150), -1)
    # un motif central quelconque : le dessin national
    cv2.circle(img, (int(cx), int(cy)), int(0.55 * RAYON), (95, 95, 95), -1)
    if n_etoiles:
        taille = 0.05 * RAYON                        # demi-taille d'une étoile
        r_centre = f_pointe * RAYON - taille         # pour que la pointe atteigne f_pointe·R
        for k in range(n_etoiles):
            a0 = 2 * np.pi * k / n_etoiles
            ex, ey = cx + r_centre * np.cos(a0), cy + r_centre * aplati * np.sin(a0)
            pts = []
            for j in range(10):                      # une étoile à 5 branches
                rr = taille if j % 2 == 0 else taille * 0.45
                aa = -np.pi / 2 + j * np.pi / 5
                pts.append([ex + rr * np.cos(aa), ey + rr * np.sin(aa)])
            cv2.fillPoly(img, [np.array(pts, np.int32)], (60, 60, 60))
    if rot_deg:
        M = cv2.getRotationMatrix2D(CENTRE, rot_deg, 1.0)
        img = cv2.warpAffine(img, M, (TAILLE, TAILLE), borderValue=(250, 250, 250))
    return cv2.GaussianBlur(img, (0, 0), 1.2)        # un rendu réel n'a pas d'arête crénelée


def test_le_bord_est_retrouve_au_pourcent():
    e = fit_coin_edge(_piece())
    assert e is not None
    assert abs(e.a - RAYON) / RAYON < 0.02
    assert abs(e.cx - CENTRE[0]) < 0.02 * RAYON
    assert abs(e.cy - CENTRE[1]) < 0.02 * RAYON
    assert e.b / e.a > 0.98


def test_le_bord_tient_sur_un_cercle_parfait():
    """MAD nulle sur un bord parfaitement circulaire : sans plancher d'élagage,
    « 6·MAD » rejette la totalité des points de bord et l'ajustement se tait."""
    yy, xx = np.mgrid[0:TAILLE, 0:TAILLE]
    d = np.hypot(xx - CENTRE[0], yy - CENTRE[1])
    # disque analytique : le bord est exactement circulaire, donc la MAD est nulle
    v = np.clip(250 - 110 * np.clip(RAYON + 0.5 - d, 0, 1), 0, 255).astype(np.uint8)
    img = np.dstack([v, v, v])
    e = fit_coin_edge(img)
    assert e is not None and abs(e.a - RAYON) / RAYON < 0.02


@pytest.mark.parametrize("f_pointe", [0.85, 0.88, 0.90, 0.92, 0.95])
def test_la_mesure_surestime_la_bande_d_environ_2_points(f_pointe):
    """Le SENS du biais est ce qui compte pour trancher `d`.

    La demi-hauteur de l'harmonique tombe entre le centre de l'étoile et sa
    pointe : la mesure place donc la fin du dessin **plus à l'intérieur** que la
    pointe réelle, et la bande lisse ressort **plus large** qu'elle n'est. Toute
    lecture du chiffre du parc doit soustraire ce biais, pas l'ajouter.
    """
    m = bande_lisse(_piece(f_pointe=f_pointe))
    assert m is not None
    vraie = 1.0 - f_pointe
    assert m["largeur"] > vraie
    assert m["largeur"] - vraie == pytest.approx(0.023, abs=0.025)


def test_la_mesure_suit_la_pointe():
    etroite = bande_lisse(_piece(f_pointe=0.95))
    large = bande_lisse(_piece(f_pointe=0.85))
    assert etroite is not None and large is not None
    assert large["largeur"] - etroite["largeur"] == pytest.approx(0.10, abs=0.03)


def test_sans_anneau_12_periodique_la_mesure_se_tait():
    """Un revers sans étoiles ne doit pas produire un chiffre au jugé."""
    assert bande_lisse(_piece(n_etoiles=0)) is None


def test_huit_etoiles_ne_sont_pas_lues_comme_douze():
    assert bande_lisse(_piece(n_etoiles=8)) is None


def test_une_piece_oblique_est_mesuree_dans_ses_propres_coordonnees():
    """L'ellipse, pas le cercle : une pièce vue de biais garde la même bande."""
    droite = bande_lisse(_piece(f_pointe=0.90))
    assert droite is not None
    for aplati, rot in ((0.90, 0.0), (0.85, 30.0), (0.80, 55.0), (0.75, 110.0)):
        oblique = bande_lisse(_piece(f_pointe=0.90, aplati=aplati, rot_deg=rot))
        assert oblique is not None, (aplati, rot)
        assert oblique["ba"] == pytest.approx(aplati, abs=0.015)
        # déplier sur un CERCLE au lieu de l'ellipse mélangerait les rayons et
        # étalerait l'anneau : la largeur dériverait avec l'obliquité.
        assert abs(oblique["largeur"] - droite["largeur"]) < 0.006, (aplati, rot)
