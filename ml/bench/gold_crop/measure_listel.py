"""Combien large est la bande lisse du bord d'une pièce de 2 € ?

`JUGE.md` propose `d = 0,08·a` comme largeur de bande du Boundary IoU, au motif
que « c'est ~la largeur du listel » — et marque explicitement cette prémisse
**non vérifiée**. Ce module la vérifie sur le parc canonique BCE.

**La mesure directe du relief ne marche pas, et il faut savoir pourquoi** : sur
une photo ou un rendu 3D, le listel n'est *pas* une zone lisse. C'est l'arête la
plus contrastée de l'image (reflet spéculaire + ombre portée). Toute statistique
de texture le classe donc comme « du dessin ». Trois tentatives ont échoué
ainsi avant celle-ci.

Ce qui marche : **les 12 étoiles sont un motif 12-périodique en angle.** Ni le
bord, ni l'éclairage, ni l'ombre ne le sont — ils vivent dans les harmoniques
basses. On suit donc l'amplitude de l'harmonique 12 du dépliage polaire, et on
appelle « bande lisse » ce qui sépare la fin de l'anneau d'étoiles du bord.

**Le biais, et son sens** — mesuré sur pièce de synthèse
(`tests/test_measure_listel.py`, étoiles de demi-taille 0,05·R) : la
demi-hauteur de l'harmonique tombe entre le *centre* de l'étoile et sa pointe,
donc la mesure place la fin du dessin trop à l'intérieur et **surestime la bande
lisse d'environ 0,023·a**. Toute lecture du chiffre du parc doit soustraire ce
biais, jamais l'ajouter. Le biais dépend de la taille des étoiles ; 0,023 vaut
pour la synthèse, pas au centième pour le parc.

Seconde réserve : l'ellipse ajustée est légèrement généreuse sur certains rendus
(le halo doux autour de la pièce), ce qui joue dans le même sens.

La mesure est donc un ordre de grandeur honnête, pas une valeur au centième.
C'est suffisant pour trancher `d`.

    python -m bench.gold_crop.measure_listel --plate /tmp/listel.png
"""

from __future__ import annotations

import argparse
import glob
import json
from dataclasses import dataclass

import cv2
import numpy as np

# Demi-diamètre nominal d'une pièce de 2 €, en millimètres (25,75 mm de diamètre).
RAYON_MM = 12.875

N_ANG = 720
HARMONIQUE = 12                       # les 12 étoiles de l'anneau extérieur
VOISINES = (7, 8, 9, 10, 13, 14, 15, 16, 17)   # bruit de fond du spectre
SNR_MIN = 3.0
PIC_LO, PIC_HI = 0.78, 0.99


@dataclass
class Ellipse:
    cx: float
    cy: float
    a: float          # demi-grand axe
    b: float          # demi-petit axe
    theta: float      # radians, orientation du grand axe


def _fit_ellipse_lsq(x: np.ndarray, y: np.ndarray) -> Ellipse | None:
    """Ajustement algébrique direct (Fitzgibbon) sur un nuage de points de bord."""
    mx, my = float(x.mean()), float(y.mean())
    x, y = x - mx, y - my                      # recentrage : conditionnement
    D = np.column_stack([x * x, x * y, y * y, x, y, np.ones_like(x)])
    _, _, V = np.linalg.svd(D, full_matrices=False)
    A, B, C, Dc, E, F = V[-1]
    M = np.array([[A, B / 2], [B / 2, C]])
    if np.linalg.det(M) <= 0:                  # hyperbole ou parabole
        return None
    cen = np.linalg.solve(2 * M, [-Dc, -E])
    val = A * cen[0] ** 2 + B * cen[0] * cen[1] + C * cen[1] ** 2 + Dc * cen[0] + E * cen[1] + F
    if val == 0:
        return None
    ev, evec = np.linalg.eigh(M / (-val))
    if np.any(ev <= 0):
        return None
    axes = 1.0 / np.sqrt(ev)
    i = int(np.argmax(axes))
    return Ellipse(cx=float(cen[0] + mx), cy=float(cen[1] + my),
                   a=float(axes[i]), b=float(axes[1 - i]),
                   theta=float(np.arctan2(evec[1, i], evec[0, i])))


def fit_coin_edge(img_bgr: np.ndarray, n_ang: int = N_ANG) -> Ellipse | None:
    """Bord de la pièce par gradient radial maximal, puis ellipse aux moindres carrés.

    Le gradient **maximal** (et non un seuil sur le fond) est ce qui distingue
    l'arête de la pièce du halo doux qui l'entoure sur les rendus BCE.
    """
    g = cv2.GaussianBlur(cv2.cvtColor(img_bgr, cv2.COLOR_BGR2GRAY), (0, 0), 1.2).astype(np.float32)
    coins = np.concatenate([g[:4, :4].ravel(), g[:4, -4:].ravel(),
                            g[-4:, :4].ravel(), g[-4:, -4:].ravel()])
    fond = float(np.median(coins))
    m = (np.abs(g - fond) > 30).astype(np.uint8)
    m = cv2.morphologyEx(m, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
    nl, lab, st, _ = cv2.connectedComponentsWithStats(m, 8)
    if nl < 2:
        return None
    i = 1 + int(np.argmax(st[1:, cv2.CC_STAT_AREA]))
    ys, xs = np.nonzero(lab == i)
    cx, cy = float(xs.mean()), float(ys.mean())
    r0 = float(np.sqrt(len(xs) / np.pi))
    if r0 < 20:
        return None

    fs = np.arange(0.85, 1.20, 0.0025)
    phi = np.linspace(0, 2 * np.pi, n_ang, endpoint=False)
    ca, sa = np.cos(phi), np.sin(phi)
    X = (cx + np.outer(fs * r0, ca)).astype(np.float32)
    Y = (cy + np.outer(fs * r0, sa)).astype(np.float32)
    P = cv2.remap(g, X, Y, cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)
    k = np.argmax(np.abs(np.diff(P, axis=0)), axis=0)
    rr = (fs[k] + 0.00125) * r0

    keep = (rr > 0.86 * r0) & (rr < 1.19 * r0)
    if keep.sum() < 8:
        return None
    med = float(np.median(rr[keep]))
    mad = float(np.median(np.abs(rr[keep] - med)))
    # plancher d'un pixel : sur un bord parfaitement circulaire la MAD vaut 0,
    # et « 6·MAD » nu deviendrait un élagage à tolérance nulle.
    tol = max(6 * mad, 1.0)
    keep &= np.abs(rr - med) < tol              # élagage des rayons aberrants
    if keep.sum() < n_ang * 0.6:
        return None
    e = _fit_ellipse_lsq(cx + rr[keep] * ca[keep], cy + rr[keep] * sa[keep])
    if e is None or e.a < 20 or not (0.7 < e.b / e.a <= 1.0):
        return None
    return e


def unwrap(gray: np.ndarray, e: Ellipse, fs: np.ndarray, n_ang: int = N_ANG) -> np.ndarray:
    """Déplie l'anneau en coordonnées elliptiques. Lignes = rayons, colonnes = angles."""
    phi = np.linspace(0, 2 * np.pi, n_ang, endpoint=False)
    u, v = np.cos(phi), np.sin(phi)
    ct, st = np.cos(e.theta), np.sin(e.theta)
    X = e.cx + np.outer(fs * e.a, u) * ct - np.outer(fs * e.b, v) * st
    Y = e.cy + np.outer(fs * e.a, u) * st + np.outer(fs * e.b, v) * ct
    return cv2.remap(gray.astype(np.float32), X.astype(np.float32), Y.astype(np.float32),
                     cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)


def bande_lisse(img_bgr: np.ndarray, e: Ellipse | None = None,
                fs: np.ndarray | None = None) -> dict | None:
    """Largeur de la bande sans dessin, du bord vers l'intérieur, en fraction de `a`.

    Rend `None` si l'anneau d'étoiles n'est pas lisible (SNR harmonique < 3) —
    un revers national sans étoiles, une image trop petite, un dessin au trait.
    """
    if e is None:
        e = fit_coin_edge(img_bgr)
    if e is None:
        return None
    if fs is None:
        fs = np.arange(0.70, 1.0001, 0.0025)
    gray = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2GRAY)
    P = unwrap(gray, e, fs)
    P = P - P.mean(axis=1, keepdims=True)
    F = np.abs(np.fft.rfft(P, axis=1))
    h = F[:, HARMONIQUE]
    bruit = np.median(F[:, list(VOISINES)], axis=1)

    win = np.nonzero((fs >= PIC_LO) & (fs <= PIC_HI))[0]
    if not len(win):
        return None
    ipk = int(win[int(np.argmax(h[win]))])
    snr = float(h[ipk] / (bruit[ipk] + 1e-6))
    if snr < SNR_MIN:
        return None

    demi = 0.5 * h[ipk]
    dehors = np.nonzero((np.arange(len(fs)) > ipk) & (h < demi))[0]
    if not len(dehors):
        return None
    j = int(dehors[0])
    f0, f1, s0, s1 = fs[j - 1], fs[j], h[j - 1], h[j]
    f_out = float(f0 + (s0 - demi) / (s0 - s1) * (f1 - f0)) if s0 > s1 else float(f1)
    return {"f_pic": float(fs[ipk]), "f_out": f_out, "largeur": 1.0 - f_out,
            "snr": snr, "a": e.a, "ba": e.b / e.a}


def planche(rows: list[dict], chemin: str, quantiles=(0.05, 0.25, 0.50, 0.75, 0.95)) -> None:
    """Planche de contrôle : sans elle, on croit un chiffre qu'on n'a pas vu."""
    rows = sorted(rows, key=lambda m: m["largeur"])
    n = len(rows)
    TS = 440
    tuiles = []
    for m in (rows[int(q * (n - 1))] for q in quantiles):
        img = cv2.imread(m["path"])
        e = fit_coin_edge(img)
        if e is None:
            continue
        s = TS / (0.34 * e.a)
        M = np.float32([[s, 0, TS / 2 - s * e.cx], [0, s, TS * 0.13 - s * (e.cy - e.a)]])
        t = cv2.warpAffine(img, M, (TS, TS), borderValue=(255, 255, 255))
        c = (int(TS / 2), int(TS * 0.13 + s * e.a))
        for f, col in ((1.0, (0, 220, 0)), (0.92, (0, 0, 255)), (m["f_out"], (0, 220, 255))):
            cv2.circle(t, c, int(round(s * e.a * f)), col, 1)
        hdr = np.full((40, TS, 3), 255, np.uint8)
        cv2.putText(hdr, f'bande lisse {m["largeur"] * 100:.1f}% de a', (4, 15),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.44, (0, 0, 0), 1, cv2.LINE_AA)
        cv2.putText(hdr, m["path"].split("/")[-2][:36], (4, 32),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.36, (90, 90, 90), 1, cv2.LINE_AA)
        tuiles.append(np.vstack([hdr, t]))
    if not tuiles:
        return
    leg = np.full((22, TS * len(tuiles), 3), 255, np.uint8)
    cv2.putText(leg, "vert = bord ajuste (1,00 a)   rouge = 1 - 0,08 a (bande du Boundary IoU)"
                     "   jaune = fin mesuree de l'anneau d'etoiles",
                (6, 15), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0, 0, 0), 1, cv2.LINE_AA)
    cv2.imwrite(chemin, np.vstack([leg, np.hstack(tuiles)]))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--glob", default="canonical_images/*/obverse_bce.webp")
    ap.add_argument("--json", help="écrit les mesures par image")
    ap.add_argument("--plate", help="écrit la planche de contrôle")
    a = ap.parse_args(argv)

    chemins = sorted(glob.glob(a.glob))
    rows, vus = [], 0
    for p in chemins:
        vus += 1
        img = cv2.imread(p)
        if img is None:
            continue
        try:
            m = bande_lisse(img)
        except Exception:
            m = None
        if m:
            rows.append({"path": p, **m})
    if not rows:
        print(f"aucune mesure exploitable sur {vus} images")
        return 1

    w = np.array([m["largeur"] for m in rows])
    print(f"n = {len(rows)} / {vus} images (anneau d'étoiles lisible, SNR ≥ {SNR_MIN})")
    print(f"  pic de l'anneau : médiane f = {np.median([m['f_pic'] for m in rows]):.3f}")
    print("  bande lisse extérieure, en fraction du demi-grand axe :")
    for q in (5, 10, 25, 50, 75, 90, 95):
        v = float(np.percentile(w, q))
        print(f"    p{q:<3d}  {v:.4f} a   ({v * RAYON_MM:.2f} mm)")
    print(f"    moyenne {w.mean():.4f}   écart-type {w.std():.4f}")
    print(f"  part des dessins où la bande lisse est < 0,08 a : {(w < 0.08).mean() * 100:.1f} %")

    if a.json:
        json.dump(rows, open(a.json, "w"), indent=1)
    if a.plate:
        planche(rows, a.plate)
        print(f"  planche → {a.plate}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
