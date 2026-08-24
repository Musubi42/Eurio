"""Défauts des seuils DINO — stdlib-only, lisibles par l'image lean du VPS.

POURQUOI CE MODULE EXISTE, ET PAS SEULEMENT `training/foundation/thresholds.py`
------------------------------------------------------------------------------
Les valeurs vivaient là-bas. Le fichier lui-même n'importe que `typing`, mais
il est sous `training/foundation/`, dont le `__init__.py` tire `anchors` →
numpy et torch. L'image lean du VPS ne peut donc pas l'importer, et c'est
justement elle qui sert la file de review. Même raison que
`shared/verdict_scope.py`.

CE QUE CES VALEURS SONT, ET NE SONT PAS
---------------------------------------
Ce sont des **défauts** : la valeur qui s'applique est résolue en base
(`store/dino_thresholds.py`), par couple `(banque, encodeur)`. Elles restent le
filet — l'image lean et le préflight doivent démarrer sur une base qui n'a pas
encore reçu la migration 0008.

LE POINT QUI COMPTE : UN SEUIL APPARTIENT À UN ENCODEUR
-------------------------------------------------------
Les similarités de `dinov2-vits14` et de `dinov2-vitl14` ne sont pas sur la
même échelle. Un seuil de 0,55 calibré sur la première ne veut rien dire pour
la seconde. C'est pourquoi la clé est ici un couple, et pas une simple chaîne :
servir la mauvaise valeur ne lèverait aucune erreur, elle déplacerait
silencieusement le taux de faux positifs.

Cf. docs/work-in-progress/banque-dino/DECISIONS.md §D5.
"""
from __future__ import annotations

from typing import Final

#: Les seules clés acceptées. Une clé libre deviendrait un fourre-tout.
KEYS: Final[tuple[str, ...]] = (
    "top1_country_sim_min",
    "country_spread_min",
    "spread_uncertain_max",
    "spread_confident_min",
    "spread_auto_accept_min",
    # Plancher d'exemplaires : nombre minimum d'exemplaires FPS pour qu'une
    # classe en garde. C'est un COMPTE et non une similarité ; la table 0011
    # le borne à part. Posé à 2 le 2026-08-20 (A1), RAMENÉ À 1 — donc inactif —
    # le même jour après mesure : cf. le commentaire du couple 2eur_all/vitl14.
    "min_exemplars",
)

#: Bornes de bon sens vérifiées à l'écriture. Elles n'encodent pas une
#: doctrine, seulement l'absurde : une similarité au-delà de 1 n'existe pas,
#: un spread de 0,9 n'arriverait jamais et gèlerait l'auto-acceptation.
BOUNDS: Final[dict[str, tuple[float, float]]] = {
    "top1_country_sim_min": (0.0, 1.0),
    "country_spread_min": (0.0, 0.5),
    "spread_uncertain_max": (0.0, 0.5),
    "spread_confident_min": (0.0, 0.5),
    "spread_auto_accept_min": (0.0, 0.5),
    # 0 = plancher désactivé (comportement d'avant A1). La borne haute suit
    # celle du CHECK SQL de 0011 ; au-delà de `exemplars_per_class` le plancher
    # se clampe de toute façon à l'exécution (cf. anchors.build_anchors_2eur_all).
    "min_exemplars": (0.0, 50.0),
}

#: Les clés qui sont des COMPTES, pas des similarités. Une valeur
#: fractionnaire y est refusée à l'écriture : `min_exemplars = 1,9` passait les
#: bornes [0, 50] et rendait `int(1.9) = 1` — un plancher qui a l'air réglé,
#: que `source='db'` certifie, et qui ne vaut pas ce qu'il affiche.
#: Défaut S1, mesuré le 2026-08-20 avant correctif :
#: `pose 1.9 → resolve 1.9 source db → int() 1`. La garde reste utile après le
#: retour à 1 : c'est la troncature silencieuse qui est le défaut, pas la
#: valeur qu'elle produisait.
CLES_ENTIERES: Final[frozenset[str]] = frozenset({"min_exemplars"})

#: Défauts par couple (banque, encodeur).
#:
#: `2eur_commemo`/vits14 : valeurs historiques du verdict, calibrées sur les
#: sims vits14 (cf. training/foundation/thresholds.py). Le verdict ne lit plus
#: cette banque depuis le 2026-08-24 ; l'entrée reste pour ses 7 780 prédictions.
#: `2eur_all`/vitl14 : seuils d'abstention des suggestions, calibrés en juin sur
#: 478 crops ; `spread_auto_accept_min` = 0,10, mesuré le 2026-08-19 sur 1 952
#: crops étiquetés (97,1 % de précision du top-1 au-dessus de ce palier).
#:
#: ⚠️ **`top1_country_sim_min` et `country_spread_min` portent les MÊMES nombres
#: pour les deux couples, et ceux-là viennent de vits14.** Depuis que le verdict
#: lit `2eur_all`/vitl14, ce sont donc des seuils hérités. Mesuré le 2026-08-24
#: sur le gold hors banque (464 crops) : ils tiennent — 185 auto-accepts, 184
#: justes, 99,5 %. L'unique faux est à spread 0,1036, au MILIEU de la
#: distribution (30 auto-accepts justes ont un spread plus bas) : le racheter
#: demanderait un seuil ≥ 0,15, qui coûte 41 % du volume. Une calibration propre
#: sur vitl14 reste souhaitable ; ce n'est pas une urgence, et surtout ce n'est
#: pas parce que les nombres sont identiques qu'ils ont été mesurés deux fois.
DEFAULTS: Final[dict[tuple[str, str], dict[str, float]]] = {
    ("2eur_commemo", "dinov2-vits14"): {
        "top1_country_sim_min": 0.55,
        "country_spread_min": 0.05,
        "spread_uncertain_max": 0.02,
        "spread_confident_min": 0.05,
        "spread_auto_accept_min": 0.10,
        # Même plancher que la banque des suggestions, pour la même raison —
        # et le résultat qui l'a fait retomber à 1 a été mesuré sur les DEUX
        # encodeurs (cf. ci-dessous).
        "min_exemplars": 1,
    },
    ("2eur_all", "dinov2-vitl14"): {
        "top1_country_sim_min": 0.55,
        "country_spread_min": 0.05,
        "spread_uncertain_max": 0.02,
        "spread_confident_min": 0.05,
        "spread_auto_accept_min": 0.10,
        # 1 = PLANCHER INACTIF. Il a valu 2 pendant une journée ; le mécanisme
        # reste en place, la valeur est revenue à 1. L'histoire vaut d'être
        # gardée, c'est une croyance renversée par la mesure.
        #
        # CE QU'ON CROYAIT (posé le 2026-08-20) : « un exemplaire unique est
        # PIRE que pas d'exemplaire du tout ». Preuve invoquée : la courbe
        # held-out agrégée, N=0 à 53,1 % contre N=1 à 50,1 % (vits14).
        #
        # LA FAUTE DE RAISONNEMENT : ce point N=1 décrit une banque où TOUTES
        # les classes sont plafonnées à 1. On en a tiré une règle PAR CLASSE
        # (« cette classe-ci, seule, est mieux sans son exemplaire »), qui n'y
        # est pas. Et l'écart n'avait jamais été testé : rejoué sur la banque
        # courante (build 365dcab2, 1495 ancres, 1179 crops held-out), il vaut
        # 53,2 % → 52,1 %, +55/−68 paires discordantes, McNemar p = 0,279 sur
        # vits14 — du bruit.
        #
        # CE QUI A ÉTÉ MESURÉ (2026-08-20, `scripts.bench_refs_curve`
        # --bank-classes / --gold-classes, banque 365dcab2, gold 0ecbb1d70e3c) :
        #
        # 1. Donner à 57 classes exactement UN exemplaire, le reste de la banque
        #    intact, améliore les crops DE CES CLASSES :
        #      vitl14  67,6 % → 69,1 %  (+37/−21, p = 0,048, 1073 crops)
        #      vits14  41,6 % → 45,5 %  (+46/−4,  p = 4,5e-10, 1073 crops)
        #    La prémisse du plancher est donc fausse dans le sens qu'elle
        #    affirmait : un exemplaire unique AIDE sa propre classe.
        # 2. Ce que coûte l'exemplaire des AUTRES classes (67 classes plafonnées
        #    à 1, notation sur les 1073 crops des 57 riches) : −0,6 pt
        #    (+0/−6, p = 0,031) sur les deux encodeurs, et −1,0 pt à N=2 : c'est
        #    un coût de CONCURRENCE qui croît avec le nombre d'ancres, pas un
        #    effet du « un seul ».
        # 3. Le vrai coupable du creux agrégé est l'ORDRE du FPS, pas le compte.
        #    À nombre d'ancres identique (795 lignes, un exemplaire par classe),
        #    garder le rang FPS le moins diversifiant au lieu du plus
        #    diversifiant donne, sur les 1179 crops held-out :
        #      vitl14  73,8 % (rang 1) → 77,8 % (dernier rang), contre 76,2 % à N=0
        #      vits14  52,1 % (rang 1) → 58,6 % (dernier rang), contre 53,2 % à N=0
        #    Le creux disparaît. Le plancher soignait donc un symptôme du
        #    « premier pick FPS = le crop le plus atypique » en supprimant des
        #    données ; le levier est l'amorce du FPS (H : amorcer au médoïde),
        #    pas un compte minimum.
        #
        # CE QUI N'A PAS PU ÊTRE MESURÉ, et pourquoi ce n'est pas un oubli :
        # les 68 classes que le plancher a réellement ramenées au canonique seul
        # ont, ensemble, 77 crops dans le gold — dont 61 sont précisément le crop
        # qui deviendrait leur exemplaire. Il reste 16 crops held-out pour 68
        # classes. Une classe qui n'a qu'un crop éligible met ce crop en banque
        # et n'a plus rien sur quoi être évaluée : la population cible du
        # plancher est, par construction, presque inévaluable. Le point 1 est
        # donc un PROXY (classes riches plafonnées à 1) — conservateur, puisque
        # leur rang 1 est choisi dans un pool de dix et sort donc plus atypique
        # que l'unique crop d'une classe pauvre.
        #
        # Repasser à 2 se fait en une ligne dans `dino_thresholds` (D5) ; le
        # mécanisme est resté en place pour ça.
        "min_exemplars": 1,
    },
}

#: Le filet du filet : couple inconnu (un encodeur candidat en cours d'essai).
#: Servir les valeurs de vitl14 plutôt que rien, et le DIRE côté appelant —
#: elles ne valent pour lui que le temps de sa calibration.
FALLBACK: Final[dict[str, float]] = DEFAULTS[("2eur_all", "dinov2-vitl14")]


def defaults_for(anchors_kind: str, encoder_version: str) -> dict[str, float]:
    """Défauts du couple, ou ceux de la banque des suggestions à défaut."""
    return dict(DEFAULTS.get((anchors_kind, encoder_version), FALLBACK))
