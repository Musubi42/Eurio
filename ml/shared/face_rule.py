"""La règle de FACE — seuil et décision. Stdlib pure, aucune dépendance.

POURQUOI CE MODULE EXISTE, ET PAS SEULEMENT DANS `auto_validate`
----------------------------------------------------------------
La règle vivait dans `sources/_base/steps/auto_validate.py`, qui importe
`cv2`, `numpy` et `torch` au niveau module. L'image lean du VPS ne les a pas
(cf. `infra/eurio-api/Dockerfile`), et `ml/scripts/` n'y est même pas copié :
**toute passe corrective jouée au canonique était donc obligée de réécrire la
règle**, en SQL ou ailleurs — c'est-à-dire d'en créer une seconde copie, libre
de diverger en silence.

`shared/` EST copié dans l'image lean. La règle vit donc ici, et
`auto_validate` l'importe. Il n'y a qu'une définition ; un correctif ne peut
pas n'en corriger que la moitié. Même intention que le port lean de
`serving/review_queue/service.py`, en mieux : pas de miroir à tenir.
"""

from __future__ import annotations

from typing import Literal

# ⚠️ CE SEUIL DÉRIVE TOUT SEUL — ne le lis pas sans lire ceci. La marge est
# `max cos sur 34 ancres de revers − max cos sur la banque des AVERS`
# (`steps/auto_validate`, `_decide_face(rev_sim, all_pred.top1_sim)`). Un max
# sur PLUS de vecteurs est plus haut par construction : **chaque rebuild qui
# agrandit la banque des avers rabote la marge et rend le détecteur plus
# aveugle, à τ constant.** Entre le 2026-06-13 et le 2026-08-27 la banque est
# passée d'environ 1 250 à 2 062 ancres (+65 %) sans que personne rejoue le banc.
#
# Calibration d'origine (2026-06-13, τ = 0,065) : FP 0/566 avers confirmés,
# rappel revers durs 73,3 %, revers faciles 100 %.
# Re-mesure du 2026-08-27, MÊME gold, MÊME τ, banque des avers à 2 062 —
# `python -m scripts.bench_face_recall --taus=-0.055:0.02:0.005` :
#
#     τ        FP (514 avers)   revers durs   revers faciles
#   -0,050         0,0 %           93,3 %         100 %
#    0,000         0,0 %           53,3 %         100 %   ← retenu
#   +0,065         0,0 %           40,0 %          80,0 %  ← l'ancien
#
# La marge MAXIMALE des 514 avers confirmés est **−0,0507** : aucun n'atteint
# zéro. Les 0,065 ne rachetaient donc aucun faux positif — ils coûtaient
# 13 points de rappel dur et 20 points de rappel facile pour rien.
#
# Pourquoi 0,000 et pas −0,050 (qui rendrait 93,3 %) : −0,050 collerait au
# MAXIMUM observé du jeu de contrôle, statistique instable sur 514 points, et
# un faux « reverse » jetterait un avers identifiable — l'asymétrie de coût qui
# fondait la prudence de juin reste vraie. Zéro garde 0,05 de marge de sécurité
# ET n'est pas une constante calibrée : c'est la frontière naturelle « ce crop
# ressemble plus au revers commun qu'à n'importe quel avers national ». Un
# seuil qui a un sens survit mieux à la dérive qu'un nombre.
#
# 🔁 REJOUE `scripts/bench_face_recall.py` APRÈS CHAQUE REBUILD de la banque
# des avers — `training/foundation/anchors.py` le rappelle à la fin de son build.
FACE_REVERSE_TAU: float = 0.0

Face = Literal["obverse", "reverse"]


def decide_face(reverse_sim: float, obverse_sim: float) -> Face:
    """Verdict de face depuis la marge « reverse-ness − obverse-ness » (C7)."""
    return "reverse" if (reverse_sim - obverse_sim) >= FACE_REVERSE_TAU else "obverse"
