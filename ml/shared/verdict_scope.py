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

⚠️ Défaut historique : `2eur_commemo` / `dinov2-vits14`.
Cette banque d'ancres ne contient **aucune** étiquette de pièce standard
(0 / 446 le 2026-08-17 ; `2eur_all` en a 18 / 378). Conséquence mesurée :
aucun crop de pièce courante ne peut être `auto_candidate` — le LEFT JOIN ne
ramène rien, et la règle 1 du verdict le classe `unknown`. Les prédictions
existent pourtant, sous `2eur_all` (66/66 sur `fr-2euro-standard-t1`).

Basculer `VERDICT_ANCHORS_KIND` sur `2eur_all` allumerait le verdict pour les
standards — mais c'est une **décision produit**, pas un correctif : les seuils
C0–C5 (`training/foundation/thresholds.py`) sont calibrés sur les sims vits14
de `2eur_commemo`, et `2eur_all` tourne en vitl14. Re-replay gold requis.

Le défaut est verrouillé par `tests/test_verdict_anchors_scope.py`.
"""

from __future__ import annotations

from typing import Final

#: `anchors_kind` de la prédiction DINO que lit le verdict de review.
VERDICT_ANCHORS_KIND: Final[str] = "2eur_commemo"

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
