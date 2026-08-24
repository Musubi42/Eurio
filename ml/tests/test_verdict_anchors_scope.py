"""Verrou du scope d'ancres lu par le VERDICT de review.

Le verdict lit `image_asset_dino_predictions` par le couple
`(anchors_kind, encoder_version)` de `shared/verdict_scope.py`. Ce couple
décide **quels crops peuvent devenir `auto_candidate`**, donc quels crops
entrent au training sans qu'un humain les regarde. Le changer déplace le verdict
de milliers d'items de la file — c'est une décision produit, jamais un détail
d'implémentation.

Ces tests ne jugent pas la valeur : ils exigent qu'elle ne bouge pas **par
accident**, et qu'aucun module ne rebrode le littéral dans son coin.

"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from shared.verdict_scope import (
    VERDICT_ANCHORS_KIND,
    VERDICT_ENCODER_VERSION,
    VERDICT_ENCODER_VERSION_FOR_KIND,
)

ML_DIR = Path(__file__).resolve().parent.parent

# Les modules qui lisent la prédiction DINO du verdict, et qui doivent tous
# passer par la constante — cf. le docstring de `shared/verdict_scope.py`.
VERDICT_MODULES = (
    "training/foundation/auto_validate.py",
    "review/review_lanes.py",
    "review/review_queue_routes.py",
    "review/peer_arbitration_routes.py",
    "review/publish_cli.py",
    "serving/review_queue/repository.py",
    # Ajoutés le 2026-08-24 : les trois qui rebrodaient le littéral HORS de ce
    # verrou, et que la bascule a donc failli laisser sur l'ancienne banque.
    # `experts.py` est le pire des trois — c'est le chemin de routage LIVE
    # (`sources/_base/steps/enqueue.py` l'appelle sans kwargs, puis écrit la
    # lane), donc la bascule aurait été à moitié faite sans une seule erreur.
    "review/validation/experts.py",
    "review/validation/replay.py",
    "serving/review_queue/service.py",
    "training/foundation/anchors.py",
)


def test_verdict_scope_default_is_2eur_all() -> None:
    """Défaut verrouillé. Le changer est une DÉCISION PRODUIT : mesurer
    l'impact sur la file avant, et mettre ce test à jour sciemment.

    Basculé de `2eur_commemo`/vits14 vers `2eur_all`/vitl14 le 2026-08-24. Ce
    qui l'a autorisé, sur le gold hors banque (464 crops) : 104 auto-accepts à
    100 % contre **185 à 99,5 %**, et top-1 exact 58,2 % → 92,6 %. Le protocole
    et les réserves sont dans le docstring de `shared/verdict_scope.py`."""
    assert VERDICT_ANCHORS_KIND == "2eur_all"
    assert VERDICT_ENCODER_VERSION == "dinov2-vitl14"


def test_verdict_encoder_matches_kind() -> None:
    """Le couple doit rester cohérent : un encoder qui ne correspond pas au
    kind fait un LEFT JOIN qui ne ramène RIEN — panne parfaitement muette."""
    assert (
        VERDICT_ENCODER_VERSION
        == VERDICT_ENCODER_VERSION_FOR_KIND[VERDICT_ANCHORS_KIND]
    )


def test_consensus_kind_is_an_alias_not_a_second_decision() -> None:
    """`CONSENSUS_ANCHORS_KIND` doit SUIVRE le verdict, pas vivre sa vie.

    Elle portait son propre littéral jusqu'au 2026-08-24, alors que
    `review_queue_routes` et `sources/_base/steps/auto_validate` s'en servent en
    production : deux constantes pour une seule décision, c'est une divergence
    programmée — et muette, puisque chacune reste plausible isolément."""
    from training.foundation.anchors import CONSENSUS_ANCHORS_KIND

    assert CONSENSUS_ANCHORS_KIND == VERDICT_ANCHORS_KIND


def test_encoder_map_keeps_every_bank_even_unread_ones() -> None:
    """La table encodeur-par-banque dit un FAIT, pas le périmètre du verdict.

    `2eur_commemo` doit y rester après la bascule : ses 7 780 prédictions sont
    toujours en base et restent lisibles. Si la clé disparaissait,
    `encoder_version_for_kind('2eur_commemo')` rendrait vits14 par le DÉFAUT de
    la fonction — la bonne valeur, mais par accident, et le jour où le défaut
    change la lecture devient fausse sans que rien ne bouge autour."""
    from training.foundation.anchors import ENCODER_VERSION_FOR_KIND

    assert ENCODER_VERSION_FOR_KIND["2eur_commemo"] == "dinov2-vits14"
    assert ENCODER_VERSION_FOR_KIND["2eur_all"] == "dinov2-vitl14"


def test_verdict_scope_mirrors_foundation_encoder_map() -> None:
    """`shared/verdict_scope` est un miroir stdlib-pur (l'image lean du VPS n'a
    ni numpy ni torch) de `training.foundation.anchors`. Interdire la dérive."""
    from training.foundation.anchors import (
        ENCODER_VERSION_FOR_KIND,
        VERDICT_ANCHORS_KIND as FOUNDATION_KIND,
        VERDICT_ENCODER_VERSION as FOUNDATION_ENCODER,
    )

    assert FOUNDATION_KIND == VERDICT_ANCHORS_KIND
    assert FOUNDATION_ENCODER == VERDICT_ENCODER_VERSION
    for kind, encoder in VERDICT_ENCODER_VERSION_FOR_KIND.items():
        assert ENCODER_VERSION_FOR_KIND[kind] == encoder, kind


@pytest.mark.parametrize("relpath", VERDICT_MODULES)
def test_no_hardcoded_anchors_kind_on_verdict_path(relpath: str) -> None:
    """Aucun module du chemin du verdict ne réécrit le littéral en dur.

    C'est ce test qui rend la bascule faisable en UN point : sans lui, un
    `AND p.anchors_kind = '2eur_commemo'` réintroduit ailleurs redeviendrait
    invisible et la bascule serait partielle (donc incohérente).
    """
    src = (ML_DIR / relpath).read_text()
    offenders = []
    for line in src.splitlines():
        stripped = line.strip()
        # Les COMMENTAIRES sont hors sujet : ils citent des requêtes d'exemple,
        # et les documenter avec une banque nommée est exactement ce qu'il faut
        # faire. Un détecteur qui crie sur un commentaire apprend à être ignoré,
        # et c'est comme ça qu'un vrai rebrode finit par passer.
        if stripped.startswith("#"):
            continue
        if (re.search(r"anchors_kind\s*[=:]\s*['\"]2eur_", line)
                or re.search(r"encoder_version\s*[=:]\s*['\"]dinov2-", line)):
            offenders.append(stripped)
    assert not offenders, (
        f"{relpath} rebrode le scope du verdict en dur : {offenders}. "
        "Importer VERDICT_ANCHORS_KIND / VERDICT_ENCODER_VERSION depuis "
        "shared.verdict_scope."
    )


def test_repository_sql_joins_on_the_constant() -> None:
    """Le SQL rendu à l'exécution (lean VPS) porte bien le scope courant."""
    from serving.review_queue import repository

    for sql in (repository._LIST_SELECT_SQL,):
        assert f"p.anchors_kind = '{VERDICT_ANCHORS_KIND}'" in sql
        assert f"p.encoder_version = '{VERDICT_ENCODER_VERSION}'" in sql


def test_engine_version_porte_la_banque_pas_seulement_les_seuils() -> None:
    """La trace d'une auto-acceptation doit dire SOUS QUELLE BANQUE elle a été prise.

    `decision_engine_version` est la trace canonique de la calibration en
    vigueur au moment de l'écriture — et la banque en fait partie autant que les
    seuils. Jusqu'au 2026-08-24 la chaîne ne portait que `s{sim}-d{spread}` :
    la bascule `2eur_commemo`/vits14 → `2eur_all`/vitl14 laissant les deux
    seuils identiques, les décisions d'avant et d'après auraient porté
    **exactement la même trace**.

    Ce n'est pas cosmétique : ces décisions posent des étiquettes
    d'entraînement que plus aucun humain ne relit. Ne pas pouvoir dire, dans six
    mois, quelle banque a produit quel label, c'est perdre la seule prise qu'on
    aurait pour rattraper une calibration qui s'avérerait mauvaise.
    """
    from review.review_queue_routes import _AUTO_DINO_ENGINE_VERSION

    assert _AUTO_DINO_ENGINE_VERSION.startswith("auto_dino@")
    assert VERDICT_ANCHORS_KIND in _AUTO_DINO_ENGINE_VERSION
    assert VERDICT_ENCODER_VERSION in _AUTO_DINO_ENGINE_VERSION
