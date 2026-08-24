"""Scope de la prédiction DINO lue par le VERDICT de review — point unique.

Toute la chaîne du verdict lit la ligne `image_asset_dino_predictions` par le
COUPLE `(anchors_kind, encoder_version)` défini ici, et **nulle part ailleurs** :

  - `training/foundation/auto_validate.py`  (moteur du verdict, défauts kwargs)
  - `review/review_lanes.py`                (verdict → lane)
  - `review/review_queue_routes.py`         (API lourde locale :8042, 4 JOIN)
  - `serving/review_queue/repository.py`    (API lean VPS, 2 JOIN)
  - `review/peer_arbitration_routes.py`, `review/publish_cli.py` (affichage)

Ce module est **sans dépendance** (stdlib pure) exprès : il est importé par
l'image lean du VPS, où `training.foundation` (numpy + torch) n'existe pas.
`training/foundation/anchors.py` le ré-exporte pour garder une seule valeur.

✅ **Basculé sur `2eur_all` / `dinov2-vitl14` le 2026-08-24**, après mesure.
L'ancien défaut `2eur_commemo` / `dinov2-vits14` ne contenait **aucune**
étiquette de pièce standard : tout crop de pièce courante tombait en `unknown`
par la règle 1 du verdict, faute de ligne à joindre — alors que la prédiction
existait, sous `2eur_all`. La moitié de la file de review n'avait donc pas de
verdict du tout : **4 237 items ouverts sur 8 496 avaient une prédiction sous
`2eur_commemo`, contre 8 495 sous `2eur_all`** (réplique, 2026-08-24 18:10).

Ce qui a autorisé la bascule — les deux banques rejouées sur le MÊME gold, dans
le même processus, base identique (`scripts/verdict_gold.py`, gold de 1009
entrées dont 811 labellisées) :

| gold labellisé, hors banque (464) | `2eur_commemo`/vits14 | `2eur_all`/vitl14 |
|---|---:|---:|
| auto-accepts produits | 104 | **185** |
| dont justes | 104 | 184 |
| précision | 100 % | **99,5 %** |
| top-1 exact (in-scope) | 58,2 % | **92,6 %** |

« Hors banque » = crops qui ne sont pas eux-mêmes des ancres (347 des 811 le
sont ; les inclure surestimerait `2eur_all`).

⚠️ **Les seuils n'ont PAS été recalibrés, et la mesure dit que ce n'est pas
nécessaire.** `shared/dino_threshold_defaults.py` sert les mêmes nombres aux
deux couples ; ceux du verdict (`top1_country_sim_min` 0,55,
`country_spread_min` 0,05) viennent de la confusion map vits14. L'unique
auto-accept faux se situe à **spread = 0,1036**, en plein milieu de la
distribution — 30 auto-accepts ont un spread PLUS BAS et sont tous justes.
Le supprimer demanderait un seuil ≥ 0,15, qui coûte 41 % du volume (185 → 110)
pour racheter une erreur. Les seuils hérités sont donc à un bon point de
fonctionnement, pas grossièrement mal placés. Une calibration propre reste
souhaitable ; elle n'est pas un prérequis.

⛔ Trois modules rebrodaient le littéral hors de portée de ce point unique, et
ont été corrigés le même jour — `review/validation/experts.py` (le chemin de
routage **LIVE** : `sources/_base/steps/enqueue.py` l'appelle sans kwargs puis
écrit la lane), `review/validation/replay.py`, et
`training/foundation/anchors.py::CONSENSUS_ANCHORS_KIND`. Sans eux la bascule
aurait été à moitié faite, en silence. Ils sont désormais dans le paramétrage de
`tests/test_verdict_anchors_scope.py`.

Le défaut est verrouillé par `tests/test_verdict_anchors_scope.py`.
"""

from __future__ import annotations

from typing import Final

#: `anchors_kind` de la prédiction DINO que lit le verdict de review.
VERDICT_ANCHORS_KIND: Final[str] = "2eur_all"

#: Encodeur correspondant. Miroir de
#: `training.foundation.anchors.ENCODER_VERSION_FOR_KIND` — le couple doit
#: rester cohérent (2eur_commemo→vits14, 2eur_all→vitl14), sinon le JOIN ne
#: ramène RIEN et tout le monde tombe en `unknown` sans la moindre erreur.
VERDICT_ENCODER_VERSION_FOR_KIND: Final[dict[str, str]] = {
    "2eur_commemo": "dinov2-vits14",
    "2eur_standard": "dinov2-vits14",
    "2eur_all": "dinov2-vitl14",
}

VERDICT_ENCODER_VERSION: Final[str] = VERDICT_ENCODER_VERSION_FOR_KIND[
    VERDICT_ANCHORS_KIND
]

# ── La banque des SUGGESTIONS, distincte de celle du verdict ────────────────
#
# `2eur_all` est la seule banque qui contienne des pièces COURANTES (38 des 56
# au 2026-08-19 ; `2eur_commemo` en a zéro). C'est elle qui alimente les
# suggestions de review — et c'est elle qu'il faut joindre pour TRIER une file
# par ce que le modèle reconnaît : trier sur la banque du verdict ne trierait
# sur rien dès qu'on travaille une pièce courante.
#
# Ces constantes vivent ICI et pas dans `training.foundation.anchors` (qui les
# définit aussi) parce que ce module-ci est stdlib-only : l'image lean du VPS
# l'importe, et `training.foundation` y tirerait numpy et torch. Le miroir
# entre les deux est verrouillé par `tests/test_verdict_anchors_scope.py`.
SUGGESTIONS_ANCHORS_KIND: Final[str] = "2eur_all"

SUGGESTIONS_ENCODER_VERSION: Final[str] = VERDICT_ENCODER_VERSION_FOR_KIND[
    SUGGESTIONS_ANCHORS_KIND
]
