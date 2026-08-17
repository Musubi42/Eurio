"""Verrou du scope d'ancres lu par le VERDICT de review.

Le verdict lit `image_asset_dino_predictions` par le couple
`(anchors_kind, encoder_version)` de `shared/verdict_scope.py`. Ce couple
décide **quels crops peuvent devenir `auto_candidate`** : `2eur_commemo` ne
contient aucune étiquette de pièce standard, donc tout crop de pièce courante
tombe en `unknown` (règle 1 du verdict). Le basculer sur `2eur_all` change le
verdict de milliers d'items de la file — c'est une décision produit.

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
)


def test_verdict_scope_default_is_2eur_commemo() -> None:
    """Défaut verrouillé. Le changer est une DÉCISION PRODUIT : mesurer
    l'impact sur la file avant, et mettre ce test à jour sciemment."""
    assert VERDICT_ANCHORS_KIND == "2eur_commemo"
    assert VERDICT_ENCODER_VERSION == "dinov2-vits14"


def test_verdict_encoder_matches_kind() -> None:
    """Le couple doit rester cohérent : un encoder qui ne correspond pas au
    kind fait un LEFT JOIN qui ne ramène RIEN — panne parfaitement muette."""
    assert (
        VERDICT_ENCODER_VERSION
        == VERDICT_ENCODER_VERSION_FOR_KIND[VERDICT_ANCHORS_KIND]
    )


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
    offenders = [
        line.strip()
        for line in src.splitlines()
        if re.search(r"anchors_kind\s*[=:]\s*['\"]2eur_", line)
        or re.search(r"encoder_version\s*[=:]\s*['\"]dinov2-", line)
    ]
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
