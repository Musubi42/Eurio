"""``GET /me/review-stats`` — les deux compteurs personnels d'un reviewer.

POURQUOI CETTE ROUTE EXISTE
---------------------------
C'est la SEULE donnée que la page d'accueil d'un ami ne trouve pas déjà dans
``GET /class-need`` (cf. ``docs/work-in-progress/review-collaborative-v2/ACCUEIL-AMI.md``
§3). Tout le reste — la liste des pièces à trier, leur cible, la barre du but
commun — vient de là-bas, qui abstrait déjà le rebuild de la banque. Ici, on ne
répond qu'à « ce que CETTE personne a fait ».

DEUX COMPTEURS, ET JAMAIS UN SEUL (§4)
--------------------------------------
``n_sorted``  — SON EFFORT. Bouge à chaque décision, immédiatement.
``n_classes_completed`` — SON EFFET. Bouge après arbitrage, puis rebuild.

Les séparer est ce qui rend les chiffres honnêtes sans être décourageants : un
ami travaille en quarantaine, sa décision attend un arbitrage et la banque ne
bouge qu'au rebuild. Un compteur unique adossé au RÉSULTAT resterait à zéro
pendant une semaine après une soirée de tri — l'inverse exact de l'effet
recherché.

⛔ LES COMPTEURS NE REDESCENDENT JAMAIS (§4, tranché avec le PO le 2026-08-24)
-----------------------------------------------------------------------------
``arbitration_status`` n'apparaît NULLE PART dans ce module, et c'est une
décision produit, pas un oubli : un rejet d'arbitrage ne retire rien à personne.

* L'EFFORT lit ``peer_review_decisions`` **quel que soit** le statut — la ligne
  reste, donc le compte ne bouge pas quand l'arbitrage tranche.
* L'EFFET lit ``review_queue.decided_by``, où l'arbitrage n'écrit son identité
  qu'en APPROUVANT : une décision rejetée n'y entre jamais, donc n'en sort pas
  non plus. Monotone par construction, sans consulter l'issue.

Conséquence assumée : si beaucoup de ses décisions étaient rejetées, son écran
serait plus flatteur que la réalité. C'est un compteur de CONTRIBUTION, pas un
bulletin de notes.

⛔ « CONTRIBUÉ À », PAS « AJOUTÉ » (§4)
---------------------------------------
Une pièce se complète à plusieurs, et avec les crops validés avant lui. Le
compte dit à combien de pièces complétées il a contribué — deux amis peuvent
compter la même, et c'est correct. Un compteur qui s'approprierait la pièce
mentirait dès le deuxième ami, et se contredirait entre leurs deux écrans.

LE VERDICT « COMPLÉTÉE » N'EST PAS RÉÉCRIT ICI
----------------------------------------------
``needs_for_classes`` est le ``_build`` d'``all_needs``, restreint aux classes de
la personne : même SQL, même ``bottleneck_for``, donc « pleine » veut dire ici
exactement ce qu'il veut dire sur ``/besoin`` et dans la liste de l'accueil. Une
seconde rédaction du seuil ferait dire « 6 pièces complétées » à un écran
pendant que l'autre en montrerait 5, sans que rien ne soit faux nulle part.

Route LÉGÈRE (SQL pur sur le canonique, stdlib) → montée sur l'image lean.
"""
from __future__ import annotations

import sqlite3
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel

from serving.auth_principal import Principal, require_scope
from serving.deps import db_connection
from shared.class_need import needs_for_classes
from shared.verdict_scope import (
    SUGGESTIONS_ANCHORS_KIND,
    SUGGESTIONS_ENCODER_VERSION,
)

router = APIRouter(tags=["me"])

ConnDep = Annotated[sqlite3.Connection, Depends(db_connection)]
#: ``review:read`` : voir ce qu'on a fait soi-même n'est pas arbitrer. Un ami
#: l'a, un arbitre aussi — la route sert les deux, avec le même calcul.
ReadDep = Annotated[Principal, Depends(require_scope("review:read"))]


class MeReviewStats(BaseModel):
    """Ce que l'accueil affiche de LUI. Deux nombres, et de quoi les dater."""

    #: SON EFFORT — images triées, tous statuts d'arbitrage confondus.
    n_sorted: int
    #: SON EFFET — pièces complétées auxquelles il a contribué.
    n_classes_completed: int
    #: Les pièces qu'il a nourries, complétées ou non. Sert à écrire
    #: « 6 pièces complétées sur les 23 que tu as nourries » sans réagréger
    #: quoi que ce soit côté écran.
    n_classes_touched: int
    #: La banque lue. Sans elle, `n_classes_completed` n'est pas reproductible :
    #: la banque a été rebâtie deux fois pendant une seule session de design.
    anchors_kind: str
    encoder_version: str


def _n_sorted(conn: sqlite3.Connection, user_id: str) -> int:
    """Combien d'images cette personne a triées, une image comptée une fois.

    L'UNION dédoublonne, et ce n'est pas une précaution : quand l'arbitrage
    APPROUVE la décision d'un ami, il écrit `review_queue.decided_by` avec
    l'identité de l'AMI (lot 8) — la ligne de quarantaine, elle, reste. Sans
    dédoublonnage, chaque décision approuvée compterait deux fois, et le
    compteur d'un ami bondirait le jour où le PO arbitre alors qu'il n'a rien
    fait de plus.

    Les deux sources sont là parce qu'un arbitre n'a AUCUNE ligne en
    quarantaine (ses décisions écrivent le canonique directement) : sans la
    seconde, son propre accueil afficherait zéro.

    Le `skip` ne compte pas : il n'entre ni dans `peer_review_decisions`
    (lot 3) ni dans `decided_by`. Passer son tour n'est pas trier.
    """
    return int(conn.execute(
        "SELECT COUNT(*) FROM ("
        "  SELECT image_asset_id FROM peer_review_decisions WHERE reviewer_token = ?"
        "  UNION"
        "  SELECT image_asset_id FROM review_queue WHERE decided_by = ?"
        ")",
        (user_id, user_id),
    ).fetchone()[0] or 0)


def _classes_touched(
    conn: sqlite3.Connection, user_id: str, *, anchors_kind: str, encoder_version: str,
) -> set[str]:
    """Les classes qu'il a nourries — maille BANQUE, via ``top1_eurio_id``.

    Les quatre conditions sont celles d'``_accepted_pending_by_class``
    (``shared/class_need``) : validé par un humain, fichier présent, revers
    exclu — le builder l'ignore, le compter promettrait un exemplaire qui
    n'arrivera jamais.

    UNE clause de moins, délibérément : ``asset_id NOT IN (banque)``. Là-bas
    elle sert à ne pas recompter ce que ``have`` compte déjà ; ici, un crop
    DÉJÀ bâti en banque est la contribution la plus forte qui soit — l'exclure
    ferait disparaître le travail d'un ami au moment précis où il porte ses
    fruits.

    ``decided_by`` et non ``peer_review_decisions`` : c'est ce qui distingue
    l'EFFET de l'EFFORT. Une décision en quarantaine n'a encore rien produit.
    """
    rows = conn.execute(
        "SELECT DISTINCT p.top1_eurio_id "
        "  FROM review_queue rq "
        "  JOIN image_assets a ON a.id = rq.image_asset_id "
        "  JOIN image_asset_dino_predictions p ON p.asset_id = a.id "
        " WHERE rq.decided_by = ? "
        "   AND a.training_eligible = 1 "
        "   AND a.storage_status = 'present' "
        "   AND (a.face IS NULL OR a.face != 'reverse') "
        "   AND p.anchors_kind = ? AND p.encoder_version = ? "
        "   AND p.top1_eurio_id IS NOT NULL",
        (user_id, anchors_kind, encoder_version),
    ).fetchall()
    return {r[0] for r in rows}


@router.get("/me/review-stats", response_model=MeReviewStats)
def get_me_review_stats(
    principal: ReadDep,
    conn: ConnDep,
    anchors_kind: str = Query(default=SUGGESTIONS_ANCHORS_KIND),
    encoder_version: str = Query(default=SUGGESTIONS_ENCODER_VERSION),
) -> MeReviewStats:
    """Ce que cette personne a fait, et à quoi ça a servi.

    Défauts alignés sur la banque des SUGGESTIONS — la même que ``/class-need``
    et que la pêche. Les deux appels de l'accueil doivent lire la MÊME banque,
    sinon « 6 pièces complétées » et la liste des pièces à trier parlent de deux
    mondes.

    Pas de 409 sur banque introuvable, contrairement à ``/class-need`` : là-bas
    une banque vide se lirait « 671 classes à scraper », ici elle ne peut donner
    que 0 pièce complétée — ce qui est exact. L'effort, lui, ne dépend d'aucune
    banque et reste juste.
    """
    touched = _classes_touched(
        conn, principal.user_id,
        anchors_kind=anchors_kind, encoder_version=encoder_version,
    )
    needs = needs_for_classes(
        conn, touched, anchors_kind=anchors_kind, encoder_version=encoder_version,
    )
    return MeReviewStats(
        n_sorted=_n_sorted(conn, principal.user_id),
        n_classes_completed=sum(1 for n in needs if n.bottleneck == "pleine"),
        n_classes_touched=len(touched),
        anchors_kind=anchors_kind,
        encoder_version=encoder_version,
    )
