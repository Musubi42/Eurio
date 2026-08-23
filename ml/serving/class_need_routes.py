"""Le besoin par classe, servi au front — image lean canonique (VPS).

Façade HTTP de ``shared.class_need`` (O1) et ``shared.dino_scope`` (O4c). Ce
module ne calcule **rien** : tout chiffre qu'il rend vient de l'un des deux, et
c'est la seule raison pour laquelle l'écran peut être vérifié contre la base.

POURQUOI CETTE ROUTE EST LÉGÈRE, ET POURQUOI C'EST DÉLIBÉRÉ
-----------------------------------------------------------
Le calcul du besoin est du SQL pur sur le canonique : pas de ``:8042``, pas de
cv2, pas de torch. Elle est donc montée **inconditionnellement** sur l'image
lean, et la page ``/besoin`` n'est **pas** ``meta.heavy``. Savoir ce qui manque,
et ce que ça coûterait, n'a pas à dépendre d'un Mac allumé (O2 §Où elle vit).
Seuls les GESTES qu'elle propose sont lourds, et ils se grisent tout seuls.

LE BLOC ``build`` N'EST PAS DÉCORATIF
------------------------------------
C'est lui qui rend la page vérifiable. La banque a été rebâtie **deux fois**
pendant la seule session de design du 2026-08-22, et 14 classes ont changé de
verdict sans qu'un seul crop soit tranché. Sans ce bloc, deux personnes lisent
deux vérités et se croient en désaccord ; avec lui, elles comparent des builds.

⚠️ ``anchors_kind`` et ``encoder_version`` sont indissociables et **obligatoires
en pratique** : ``2eur_all`` n'existe qu'en ``dinov2-vitl14``. Un couple
inexistant rend **409**, jamais 671 classes en ``scrape`` — c'est le refus n°2
de ``shared/class_need.py`` (« il ne devine pas ``anchors_kind`` »), et une
banque vide qui se lirait « tout est à scraper » est exactement la panne muette
que ce dépôt collectionne.

Monté sur ``server_serve`` (lean/VPS) ET sur ``server.py`` (workstation) : c'est
une LECTURE, donc elle marche des deux côtés — la workstation lit sa réplique.
"""
from __future__ import annotations

import sqlite3
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from serving.auth_principal import Principal, require_scope
from serving.deps import db_connection
from shared.class_need import all_needs
from shared.dino_scope import build_dino_scope

router = APIRouter(tags=["besoin"])

ConnDep = Annotated[sqlite3.Connection, Depends(db_connection)]
ReadDep = Annotated[Principal, Depends(require_scope("lab:read"))]


class BuildInfo(BaseModel):
    """Quelle banque a été lue. Sans ça, aucun chiffre de cette page n'est
    reproductible — cf. l'en-tête du module."""

    anchors_kind: str
    encoder_version: str
    build_id: str | None
    built_at: str | None
    n_anchors: int


class Parked(BaseModel):
    """Les crops ouverts que le besoin met HORS travail (D2/D3).

    Deux causes, jamais confondues : ``full_class`` (la classe est à sa cible)
    et ``no_prediction`` (aucun top-1 dans cette banque — on ignore où le crop
    tombe, donc on ne peut pas dire qu'il manque quelque part). Les additionner
    en un seul nombre ferait perdre la seule information actionnable : la
    seconde population se répare par un backfill, pas par du tri.
    """

    full_class: int
    no_prediction: int


class Totals(BaseModel):
    n_classes: int
    #: Palier 1 (D7) : classes à ``have >= 1``. Porte les +10,8 pts de l'A/B
    #: médoïde ; c'est le premier exemplaire qui vaut, pas le huitième.
    coverage: int
    #: Palier 2 (D7) : Σ ``need``, ce qui manque À LA BANQUE.
    sum_need: int
    #: Σ ``min(need, pending_scoped)`` — ce que la file peut RÉELLEMENT poser.
    #: Très différent de ``sum_need`` : le reste est à aller chercher.
    sum_reachable: int
    #: Σ ``accepted_pending`` (D8) et ce qu'un rebuild poserait vraiment.
    accepted_pending: int
    rebuild_would_place: int
    n_open: int
    by_bottleneck: dict[str, int]


class ClassNeedRow(BaseModel):
    class_id: str
    label: str
    country: str | None
    family: str
    have: int
    cap: int
    target: int
    need: int
    pending: int
    pending_scoped: int
    best_margin: float | None
    bottleneck: str
    n_train_eligible: int
    accepted_pending: int
    #: O4c — le filtre pays s'est-il retiré parce qu'il ne laissait rien ?
    #: L'écran DOIT le lire : sinon il annonce « pays LU » au-dessus d'une file
    #: qui sert tous les pays, et le lien qu'il propose sert zéro.
    country_disarmed: bool
    n_hidden_by_country: int


class ClassNeedResponse(BaseModel):
    build: BuildInfo
    totals: Totals
    parked: Parked
    classes: list[ClassNeedRow]


#: Les champs recopiés tels quels depuis `ClassNeed`. Énumérés plutôt que
#: `dataclasses.asdict` : ajouter un champ au dataclass ne doit pas l'exposer
#: silencieusement à l'API — le contrat HTTP se décide, il ne se subit pas.
ClassNeed_FIELDS = (
    "class_id", "label", "country", "family", "have", "cap", "target",
    "need", "pending", "pending_scoped", "best_margin", "bottleneck",
    "n_train_eligible", "accepted_pending",
)


def _build_info(
    conn: sqlite3.Connection, anchors_kind: str, encoder_version: str,
) -> BuildInfo:
    row = conn.execute(
        "SELECT build_id, MAX(built_at) AS built_at, COUNT(*) AS n "
        "  FROM dino_class_references "
        " WHERE anchors_kind = ? AND encoder_version = ?",
        (anchors_kind, encoder_version),
    ).fetchone()
    n = int(row["n"] or 0) if row is not None else 0
    return BuildInfo(
        anchors_kind=anchors_kind,
        encoder_version=encoder_version,
        build_id=row["build_id"] if row is not None else None,
        built_at=row["built_at"] if row is not None else None,
        n_anchors=n,
    )


@router.get("/class-need", response_model=ClassNeedResponse)
def get_class_need(
    principal: ReadDep,
    conn: ConnDep,
    anchors_kind: str = Query(default="2eur_all"),
    encoder_version: str = Query(default="dinov2-vitl14"),
) -> ClassNeedResponse:
    """Le besoin de toutes les classes de la banque, avec l'effet des filtres.

    Les classes **pleines ne sont pas masquées** : c'est l'information la plus
    utile de l'outil (refus n°3 de ``class_need``). Le tri est laissé à l'écran
    — la liste sort triée par ``class_id``, stable.
    """
    build = _build_info(conn, anchors_kind, encoder_version)
    if build.n_anchors == 0:
        # Jamais 671 classes en `scrape` : une banque introuvable est une
        # ERREUR d'appel, pas un catalogue à scraper.
        raise HTTPException(
            status_code=409,
            detail=(
                f"aucune ancre pour ({anchors_kind!r}, {encoder_version!r}) — "
                "le couple (banque, encodeur) est indissociable : '2eur_all' "
                "n'existe qu'en 'dinov2-vitl14'."
            ),
        )

    needs = all_needs(
        conn, anchors_kind=anchors_kind, encoder_version=encoder_version,
    )

    rows: list[ClassNeedRow] = []
    for n in needs:
        # ⛔ On passe par `build_dino_scope`, jamais par une requête d'effet
        # pays réécrite ici : deux rédactions de la même règle divergeraient, et
        # la page annoncerait un désarmement que la pêche n'applique pas.
        scope = build_dino_scope(
            conn, dino_class=n.class_id, country_only=True,
        )
        rows.append(ClassNeedRow(
            **{f: getattr(n, f) for f in ClassNeed_FIELDS},
            country_disarmed=scope.country_disarmed,
            n_hidden_by_country=scope.n_hidden_by_country,
        ))

    n_open = int(conn.execute(
        "SELECT COUNT(*) AS n FROM review_queue WHERE status = 'open'",
    ).fetchone()["n"])
    full_class = sum(n.pending for n in needs if n.bottleneck == "pleine")
    # `no_prediction` par SOUSTRACTION : tout crop ouvert que `class_need` ne
    # rattache à aucune classe de cette banque. Le compter par une seconde
    # requête risquerait de ne pas retomber sur le même total.
    no_prediction = max(n_open - sum(n.pending for n in needs), 0)

    by_bottleneck: dict[str, int] = {}
    for n in needs:
        by_bottleneck[n.bottleneck] = by_bottleneck.get(n.bottleneck, 0) + 1

    totals = Totals(
        n_classes=len(needs),
        coverage=sum(1 for n in needs if n.have >= 1),
        sum_need=sum(n.need for n in needs),
        sum_reachable=sum(min(n.need, n.pending_scoped) for n in needs),
        accepted_pending=sum(n.accepted_pending for n in needs),
        rebuild_would_place=sum(min(n.need, n.accepted_pending) for n in needs),
        n_open=n_open,
        by_bottleneck=by_bottleneck,
    )
    return ClassNeedResponse(
        build=build, totals=totals,
        parked=Parked(full_class=full_class, no_prediction=no_prediction),
        classes=rows,
    )
