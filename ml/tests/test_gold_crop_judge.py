"""Le juge mesure-t-il ce que `JUGE.md` dit qu'il mesure ?

Deux familles de vérifications, et la distinction compte :

* **analytiques** — deux disques concentriques ont une Boundary IoU en forme
  close. Une implémentation qui s'en écarte est fausse, point. C'est la seule
  partie du chantier où l'on dispose d'une vérité sans annotateur ;
* **de synthèse** — une pièce dont on POSE la géométrie, pour vérifier que C1
  et C2 réagissent (ou non) comme annoncé.

Le test le plus important du fichier est
`test_c2_est_inerte_sur_l_anneau_specifie` : il enregistre un défaut du juge,
pas une propriété. Cf. `DECISIONS.md` §D8.
"""

from __future__ import annotations

import math

import cv2
import numpy as np
import pytest

from bench.gold_crop.geometry import Cercle, Ellipse
from bench.gold_crop.judge import (
    RING_HI,
    RING_LO,
    _arc_coverage,
    c1,
    c2,
    cadre_decoupe,
    juger,
    metriques_de_surface,
)

R = 400.0
CENTRE = (700.0, 660.0)
RAW_HW = (1400, 1500)


def _biou_close(k: float, d_frac: float, ancre_sur_l_or: bool = True) -> float:
    """Forme close : deux disques concentriques, rayons R et kR.

    Les bandes sont deux anneaux ; l'IoU est un rapport d'aires, donc de
    différences de carrés. `ancre_sur_l_or` : la bande du prédit fait-elle
    `d_frac·R` (l'or) ou `d_frac·kR` (sa propre taille) ?
    """
    d_or = d_frac
    d_pred = d_frac if ancre_sur_l_or else d_frac * k
    g0, g1 = 1.0 - d_or, 1.0
    p0, p1 = k - d_pred, k
    i0, i1 = max(g0, p0), min(g1, p1)
    inter = max(0.0, i1 ** 2 - i0 ** 2) if i1 > i0 else 0.0
    aire_g = g1 ** 2 - g0 ** 2
    aire_p = p1 ** 2 - max(p0, 0.0) ** 2
    union = aire_g + aire_p - inter
    return inter / union if union else 0.0


# ─── Boundary IoU : la partie analytique ────────────────────────────────────

@pytest.mark.parametrize("k", [1.0, 0.99, 0.97, 0.94, 0.90, 0.80])
def test_la_boundary_iou_suit_sa_forme_close(k):
    gold = Ellipse.depuis_cercle(*CENTRE, R)
    m = metriques_de_surface(gold, Cercle(*CENTRE, k * R), d_frac=0.08)
    assert m["boundary_iou"] == pytest.approx(_biou_close(k, 0.08), abs=0.01)


@pytest.mark.parametrize("k", [1.0, 0.97, 0.94, 0.90, 0.80])
def test_l_iou_de_masque_vaut_k_carre(k):
    gold = Ellipse.depuis_cercle(*CENTRE, R)
    m = metriques_de_surface(gold, Cercle(*CENTRE, k * R))
    assert m["mask_iou"] == pytest.approx(k ** 2, abs=0.002)


@pytest.mark.parametrize("k", [1.0, 0.97, 0.94, 0.90, 0.80])
def test_hausdorff_vaut_le_rognage(k):
    gold = Ellipse.depuis_cercle(*CENTRE, R)
    m = metriques_de_surface(gold, Cercle(*CENTRE, k * R))
    assert m["hausdorff_frac"] == pytest.approx(1.0 - k, abs=0.005)


def test_la_boundary_iou_est_bien_plus_sensible_que_l_iou_de_masque():
    """L'argument de `JUGE.md` : rogner 6 % fait chuter l'IoU de 11,6 points et
    la Boundary IoU de 85 — un facteur ~7 de sensibilité. C'est CE rapport qui
    justifie de piloter sur la Boundary IoU."""
    gold = Ellipse.depuis_cercle(*CENTRE, R)
    m = metriques_de_surface(gold, Cercle(*CENTRE, 0.94 * R))
    chute_iou = 1.0 - m["mask_iou"]
    chute_biou = 1.0 - m["boundary_iou"]
    assert chute_biou / chute_iou > 6.0


def test_les_deux_conventions_de_bande(recwarn):
    """⚠️ La table de `JUGE.md` a été calculée avec une bande proportionnelle à
    CHAQUE forme ; le juge ancre `d` sur l'or.

    Le juge doit ancrer sur l'or : une bande qui suivrait le rayon PRÉDIT serait
    une grandeur calculée sur la sortie de la méthode — exactement ce que la
    règle fondatrice interdit. L'écart est < 0,01 et ne change aucun classement,
    mais il doit être dit plutôt que découvert.
    """
    assert _biou_close(0.97, 0.08, ancre_sur_l_or=False) == pytest.approx(0.464, abs=0.001)
    assert _biou_close(0.94, 0.08, ancre_sur_l_or=False) == pytest.approx(0.148, abs=0.001)
    assert _biou_close(0.97, 0.08, ancre_sur_l_or=True) == pytest.approx(0.4545, abs=0.001)
    assert _biou_close(0.94, 0.08, ancre_sur_l_or=True) == pytest.approx(0.1429, abs=0.001)


def test_deux_formes_disjointes_donnent_zero():
    gold = Ellipse.depuis_cercle(*CENTRE, R)
    m = metriques_de_surface(gold, Cercle(CENTRE[0] + 3 * R, CENTRE[1], R))
    assert m["boundary_iou"] == 0.0 and m["mask_iou"] == 0.0


# ─── le cadre, et sa fidélité à la prod ─────────────────────────────────────

@pytest.mark.parametrize("cx,cy,r", [
    (700.0, 660.0, 400.0),      # bien au centre
    (120.0, 660.0, 400.0),      # clampé à gauche
    (700.0, 90.0, 300.0),       # clampé en haut
    (1420.0, 1350.0, 350.0),    # clampé en bas à droite
])
def test_le_cadre_du_juge_est_celui_de_la_prod(cx, cy, r):
    """Le juge ne peut pas SE FAIRE une idée du cadre : il doit répliquer
    `_crop_mask_resize_float`, y compris son clamp asymétrique au bord."""
    from vision.normalize_snap import CropConfig, _crop_mask_resize_float

    raw = np.full((*RAW_HW, 3), 128, np.uint8)
    res = _crop_mask_resize_float(raw, cx, cy, r, "t", config=CropConfig())
    cadre = cadre_decoupe(Cercle(cx, cy, r), RAW_HW[1], RAW_HW[0])
    assert int(round(cadre.x1 - cadre.x0)) == res.debug["crop_side"]


def test_un_cadre_rogne_par_le_bord_se_signale():
    loin = cadre_decoupe(Cercle(700, 660, 400), RAW_HW[1], RAW_HW[0])
    au_bord = cadre_decoupe(Cercle(80, 660, 400), RAW_HW[1], RAW_HW[0])
    assert not loin.tronque and au_bord.tronque


# ─── C1 ─────────────────────────────────────────────────────────────────────

def test_une_detection_parfaite_donne_exactement_la_marge_promise_au_cadre():
    """`r = a` : le carré a un demi-côté `1,02·a`, donc la marge au CADRE vaut
    exactement `COIN_MARGIN`. C'est le sens de « le juge exige ce que le code
    promet ». Mais le masque circulaire, lui, coupe pile sur le listel — la
    marge RETENUE est nulle. Les deux lectures divergent, et il faut le voir."""
    gold = Ellipse.depuis_cercle(*CENTRE, R)
    m = c1(gold, Cercle(*CENTRE, R), RAW_HW[1], RAW_HW[0])
    assert m["C1_cadre_marge_min_frac"] == pytest.approx(0.02, abs=0.002)
    assert m["C1_marge_min_frac"] == pytest.approx(0.0, abs=0.002)


def test_deux_pour_cent_de_rayon_en_plus_satisfont_la_marge_retenue():
    gold = Ellipse.depuis_cercle(*CENTRE, R)
    m = c1(gold, Cercle(*CENTRE, 1.02 * R), RAW_HW[1], RAW_HW[0])
    assert m["C1_marge_min_frac"] == pytest.approx(0.02, abs=0.002)


def test_le_carre_est_plus_permissif_que_le_masque_dans_les_diagonales():
    """LE point qui sépare les deux lectures de C1. Une ellipse orientée à 45°
    peut tenir dans le carré et être **amputée par le masque circulaire** : le
    carré atteint `1,44·r` dans ses coins, le disque s'arrête à `r`.

    Un juge qui ne regarde que le carré déclare ce cas sain. Il ne l'est pas.
    """
    gold = Ellipse.depuis_degres(*CENTRE, 1.25 * R, 0.5 * R, 45.0)
    m = c1(gold, Cercle(*CENTRE, R), RAW_HW[1], RAW_HW[0])
    assert m["C1_cadre_marge_min_frac"] > 0.0          # le carré dit « ça passe »
    assert m["C1_marge_min_frac"] < -0.15             # le masque dit « amputé »


def test_un_cadre_clampe_par_le_bord_ampute_meme_si_le_disque_ne_le_fait_pas():
    """L'autre moitié de C1 : près du bord de l'image, la prod rend le cadre
    carré **en l'ancrant en haut à gauche**. Le carré devient plus petit que
    demandé et décentré — il coupe la pièce alors que le masque circulaire, lui,
    la contient entièrement. Un juge qui ne regarderait que le disque
    déclarerait ce cas sain.
    """
    gold = Ellipse.depuis_cercle(90.0, 660.0, 380.0)
    pred = Cercle(90.0, 660.0, 400.0)
    m = c1(gold, pred, RAW_HW[1], RAW_HW[0])
    assert m["C1_disque_marge_min_frac"] > 0.05      # le disque dit « ça passe »
    assert m["C1_cadre_marge_min_frac"] < 0.0        # le cadre clampé coupe
    assert m["C1_marge_min_frac"] == pytest.approx(m["C1_cadre_marge_min_frac"])
    assert m["C1_cadre_tronque"]


def test_le_rognage_fait_basculer_c1():
    gold = Ellipse.depuis_cercle(*CENTRE, R)
    sain = juger(gold, Cercle(*CENTRE, 1.05 * R), RAW_HW, m=0.02)
    casse = juger(gold, Cercle(*CENTRE, 0.94 * R), RAW_HW, m=0.02)
    assert sain["C1_ok"] and not sain["ampute"]
    assert not casse["C1_ok"] and casse["ampute"]


# ─── C2 : le défaut, enregistré ─────────────────────────────────────────────

def _piece(taille=900, r=380.0, rho_bimetal=0.735):
    """Pièce de synthèse avec sa jonction bimétallique — ρ ≈ 0,735 mesuré."""
    img = np.full((taille, taille, 3), 240, np.uint8)
    c = (taille // 2, taille // 2)
    cv2.circle(img, c, int(r), (150, 150, 150), -1)
    cv2.circle(img, c, int(r * rho_bimetal), (95, 95, 95), -1)     # le disque intérieur
    for k in range(12):                                            # les 12 étoiles
        a = 2 * math.pi * k / 12
        cv2.circle(img, (int(c[0] + 0.86 * r * math.cos(a)),
                         int(c[1] + 0.86 * r * math.sin(a))), int(0.05 * r), (60, 60, 60), -1)
    return cv2.GaussianBlur(img, (0, 0), 1.2), c, r


def _c2_pour(k: float, ring=None):
    from vision.normalize_snap import CropConfig, _crop_mask_resize_float

    img, c, r = _piece()
    gold = Ellipse.depuis_cercle(c[0], c[1], r)
    pred = Cercle(c[0], c[1], k * r)
    sortie = _crop_mask_resize_float(img, pred.cx, pred.cy, pred.r, "t",
                                     config=CropConfig()).image
    cadre = cadre_decoupe(pred, img.shape[1], img.shape[0])
    # `ring=None` → on laisse le module choisir : c'est SON anneau qu'on teste,
    # pas une copie de ses constantes dans le test.
    args = () if ring is None else ring
    return c2(sortie, gold, cadre, *args)["arc_coverage"]


@pytest.mark.parametrize("k", [1.02, 1.00, 0.95, 0.90, 0.85, 0.75])
def test_c2_est_inerte_sur_l_anneau_specifie(k):
    """🔴 **C2 ne bouge pas, même à 25 % d'amputation.**

    L'anneau `[0,70 ; 1,15]` de `measure_tilt` englobe la jonction bimétallique
    (ρ ≈ 0,735) : un cercle de contraste **intrinsèque à la pièce**, présent
    dans les 12 secteurs quel que soit le cadrage. `arc_coverage` sature à 1,0.

    La monotonie par inclusion de `JUGE.md` est vraie et **vide** : elle dit que
    rogner ne peut pas AUGMENTER la couverture, pas qu'elle la fait baisser.

    Ce test enregistre le défaut. Le retirer sans amendement daté violerait RE-3.
    """
    assert (RING_LO, RING_HI) == (0.70, 1.15)      # l'anneau de `measure_tilt`
    assert _c2_pour(k) == pytest.approx(1.0, abs=1e-9)


@pytest.mark.parametrize("k,attendu", [(1.00, 1.0), (0.95, 1.0), (0.85, 0.0)])
def test_un_anneau_etroit_ne_mesure_plus_que_la_geometrie(k, attendu):
    """Resserrer l'anneau rend C2 discriminante — mais pour rien.

    À `k = 0,85`, le masque dur a noirci tout au-delà de `0,85·a` : l'anneau
    `[0,95 ; 1,05]` est entièrement noir, donc zéro point de Canny. C2 répond
    alors « `r` est-il ≥ ~0,95·a ? » — une question purement géométrique, que
    C1 tranche déjà, plus finement et de façon continue.
    """
    assert _c2_pour(k, ring=(0.95, 1.05)) == pytest.approx(attendu, abs=1e-9)


def test_c2_ne_compte_pas_dans_l_amputation_par_defaut():
    """Journalisée (RE-3), mais elle ne décide pas tant que le PO n'a pas tranché."""
    gold = Ellipse.depuis_cercle(*CENTRE, R)
    img = np.full((224, 224, 3), 0, np.uint8)            # sortie vide → arc = 0
    v = juger(gold, Cercle(*CENTRE, 1.05 * R), RAW_HW, img)
    assert not v["C2_ok"] and v["C1_ok"]
    assert v["ampute"] is False
    dur = juger(gold, Cercle(*CENTRE, 1.05 * R), RAW_HW, img, c2_compte=True)
    assert dur["ampute"] is True


def test_l_anneau_de_c2_vient_de_l_or_pas_du_candidat():
    """Garde-fou de `JUGE.md` : sinon la méthode déplace l'ellipse pour remplir
    ses secteurs. On le vérifie en bougeant l'or : la couverture doit changer,
    alors que la sortie, elle, n'a pas bougé d'un pixel."""
    img, c, r = _piece()
    gris = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    centre = _arc_coverage(gris, Ellipse.depuis_cercle(c[0], c[1], r), 0.95, 1.05)["arc_coverage"]
    decale = _arc_coverage(gris, Ellipse.depuis_cercle(c[0] + 0.6 * r, c[1], r), 0.95, 1.05)["arc_coverage"]
    assert centre > decale


@pytest.mark.parametrize("n_occupes", [1, 3, 6, 11, 12])
def test_les_douze_secteurs_sont_bien_douze(n_occupes):
    """La machinerie des secteurs, testée hors de C2 — qui sature et masquerait
    un compte faux. On pose des points de bord dans `n_occupes` secteurs sur 12
    et on relit la fraction."""
    from bench.gold_crop.judge import N_SECTEURS

    assert N_SECTEURS == 12
    n = 400
    img = np.zeros((n, n), np.uint8)
    c, rr = n / 2, 0.4 * n
    for k in range(n_occupes):
        a = math.radians(15 + k * 30)      # milieu du secteur k
        cv2.circle(img, (int(c + rr * math.cos(a)), int(c + rr * math.sin(a))),
                   4, 255, -1)
    gold = Ellipse.depuis_cercle(c, c, rr)
    cov = _arc_coverage(img, gold, 0.70, 1.15)["arc_coverage"]
    assert cov == pytest.approx(n_occupes / 12, abs=1e-9)


def test_la_region_de_c1_change_le_verdict_et_doit_etre_choisie():
    """⚠️ D9 — question ouverte au PO. Le MÊME cas est amputé ou sain selon la
    région retenue, et l'écart n'est pas marginal.

    Ellipse à 45° dans un cercle trop petit : le carré la contient (ses coins
    portent à `1,44·r`), le masque circulaire la coupe. Ce n'est pas un réglage
    de confort — c'est le choix entre « la prod tient-elle sa promesse de
    padding » et « la prod perd-elle des pixels de la pièce ».
    """
    gold = Ellipse.depuis_degres(*CENTRE, 1.25 * R, 0.5 * R, 45.0)
    pred = Cercle(*CENTRE, R)
    assert juger(gold, pred, RAW_HW, region="cadre", m=0.02)["C1_ok"] is True
    assert juger(gold, pred, RAW_HW, region="retenu", m=0.02)["C1_ok"] is False
    with pytest.raises(ValueError, match="région C1 inconnue"):
        juger(gold, pred, RAW_HW, region="inventée")


def test_le_plafond_mecanique_ne_peut_pas_tenir_la_marge_sur_la_region_retenue():
    """🔴 Conséquence géométrique, vraie pour TOUT or : `gold_replay` prend
    `r = a` (le plus petit cercle contenant l'ellipse), donc le masque coupe
    pile sur le listel et la marge retenue est **nulle**. Avec `m = 0,02`, le
    plafond du banc est à 100 % d'amputation — et un tableau dont le plafond
    est au plancher est illisible.

    Trois issues, toutes légitimes, toutes au PO (D9) : C1 sur le cadre ;
    `m = 0` sur la région retenue ; ou `gold_replay` à `r = 1,02·a`.
    """
    gold = Ellipse.depuis_cercle(*CENTRE, R)
    replay = Cercle(gold.cx, gold.cy, gold.a)          # ce que fait `gold_replay`
    assert juger(gold, replay, RAW_HW, region="retenu", m=0.02)["C1_ok"] is False
    assert juger(gold, replay, RAW_HW, region="retenu", m=0.0)["C1_ok"] is True
    assert juger(gold, replay, RAW_HW, region="cadre", m=0.02)["C1_ok"] is True
    dilate = Cercle(gold.cx, gold.cy, 1.02 * gold.a)
    assert juger(gold, dilate, RAW_HW, region="retenu", m=0.02)["C1_ok"] is True


def test_un_crop_complet_mais_serre_n_est_pas_un_crop_casse():
    """D9, l'autre moitié : les deux questions doivent pouvoir répondre
    DIFFÉREMMENT, sinon les séparer n'aurait servi à rien.

    Pièce près du bord gauche : la prod clampe le cadre à `x0 = 0` puis le rend
    carré, donc le padding tombe à 1,3 % — sous la promesse. Mais **rien n'est
    coupé** : le disque contient la pièce entière. C'est un crop serré, pas un
    crop cassé, et `ampute` doit le dire.
    """
    gold = Ellipse.depuis_cercle(385.0, 660.0, 380.0)
    v = juger(gold, Cercle(385.0, 660.0, 400.0), RAW_HW)
    assert v["C1_cadre_marge_min_frac"] == pytest.approx(0.0132, abs=0.002)
    assert v["marge_promise_ok"] is False       # la promesse de 2 % n'est pas tenue
    assert v["ampute"] is False                 # …et pourtant rien n'est amputé
    assert v["C1_cadre_tronque"] is True

    # 7 px plus à gauche, le cadre coupe pour de bon : là, c'est une amputation
    plus_bord = juger(Ellipse.depuis_cercle(378.0, 660.0, 380.0),
                      Cercle(378.0, 660.0, 400.0), RAW_HW)
    assert plus_bord["ampute"] is True
