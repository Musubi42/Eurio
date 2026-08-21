"""Quel signal décide, par classe — la famille de signal (O5), stdlib-only.

POURQUOI UNE « FAMILLE » ET PAS UNE RÈGLE UNIQUE
-----------------------------------------------
Le signal qui tranche l'identité d'un crop n'est pas le même partout, et le
traiter comme s'il l'était garantit une erreur structurelle sur une famille
entière. Mesuré le 2026-08-21 sur les 219 crops labellisés des émissions
communes (`docs/work-in-progress/pipeline-propre/outils/O5-familles-de-signal.md`) :
le top-1 DINO trouve le bon DESSIN à 97,7 % et le bon PAYS à 64,4 %. Le seul
écart entre un Erasmus autrichien et un Erasmus chypriote est une inscription
illisible à 224 px : c'est une propriété de la pièce, aucun crop de plus ne la
corrige.

LES TROIS FAMILLES
------------------
    nationale          commémorative propre à un pays — l'IMAGE décide
    portrait_standard  courante à effigie (is_commemorative=0, face_value=2.0)
                       — image + PAYS (l'image ne sépare pas les portraits)
    emission_commune   membre d'un design_group_id frappé par plusieurs pays
                       — TEXTE / PAYS ; l'image ne fait que confirmer le dessin

LA MAILLE, ET LE PIÈGE
----------------------
La famille se calcule sur le grain BANQUE : `dino_class_references.class_id`,
c'est-à-dire l'`eurio_id` du représentant (VISION §V4). Une émission commune
frappée par 18 pays donne donc 18 classes `emission_commune`, jamais une seule
— l'app doit rendre le pays, et le référentiel a raison de les distinguer.

Un membre non-représentant d'une ère courante (`it-2008-…` pour une banque qui
indexe `it-2002-…`) a la même famille que son représentant : la famille ne
dépend que de `design_group_id`, `is_commemorative` et `face_value`, partagés
par toute l'ère. On accepte donc n'importe quel `eurio_id` en entrée.

Ce module n'est PAS une fusion de classes ni un changement de banque : c'est une
lecture, aucune ancre ne bouge.

Contrat d'import : **stdlib uniquement** (sqlite3), comme `shared/bank_classes`.
L'image lean du VPS doit pouvoir l'importer sans tirer numpy ni torch.
"""
from __future__ import annotations

import sqlite3
from typing import Final

__all__ = [
    "FAMILIES",
    "NATIONALE",
    "PORTRAIT_STANDARD",
    "EMISSION_COMMUNE",
    "class_family",
    "emission_commune_group_ids",
    "families_for_bank",
    "family_from_coin",
]

NATIONALE: Final = "nationale"
PORTRAIT_STANDARD: Final = "portrait_standard"
EMISSION_COMMUNE: Final = "emission_commune"

#: Les seules valeurs que `class_family` renvoie — l'écran peut les énumérer.
FAMILIES: Final[tuple[str, ...]] = (NATIONALE, PORTRAIT_STANDARD, EMISSION_COMMUNE)

#: La valeur faciale des courantes à effigie. Comparée en flottant exact :
#: `coins.face_value` est un REAL écrit depuis `2.0`, jamais calculé.
_PORTRAIT_FACE_VALUE: Final = 2.0


def emission_commune_group_ids(conn: sqlite3.Connection) -> set[str]:
    """Les `design_group_id` frappés par plus d'un pays.

    Sur la réplique du 2026-08-21 : `eu-erasmus-2022` (19 pays),
    `eu-eu-flag-2015` (19), `eu-euro-cash-2012` (18), `eu-emu-2009` (16),
    `eu-rome-2007` (13) — 87 pièces.
    """
    rows = conn.execute(
        "SELECT design_group_id FROM coins "
        " WHERE design_group_id IS NOT NULL "
        " GROUP BY design_group_id HAVING COUNT(DISTINCT country) > 1",
    ).fetchall()
    return {r[0] for r in rows}


def family_from_coin(
    design_group_id: str | None,
    is_commemorative: int | bool,
    face_value: float,
    ec_groups: set[str],
) -> str:
    """La règle, pure, sur les trois colonnes de `coins` qui la portent.

    L'ordre compte : une émission commune est aussi commémorative, elle doit
    sortir en `emission_commune` avant que la règle « le reste » ne la range en
    `nationale`.
    """
    if design_group_id is not None and design_group_id in ec_groups:
        return EMISSION_COMMUNE
    if not is_commemorative and float(face_value) == _PORTRAIT_FACE_VALUE:
        return PORTRAIT_STANDARD
    return NATIONALE


def class_family(conn: sqlite3.Connection, class_id: str) -> str:
    """La famille d'une classe de banque — ou de n'importe quel membre.

    `class_id` est un `eurio_id` (le représentant, ou un membre de son ère :
    ils partagent les colonnes dont la famille dépend). Une pièce inconnue
    lève `LookupError` : rendre `nationale` par défaut ferait passer une faute
    de saisie pour une commémorative, sans un mot.
    """
    row = conn.execute(
        "SELECT design_group_id, is_commemorative, face_value "
        "  FROM coins WHERE eurio_id = ?",
        (class_id,),
    ).fetchone()
    if row is None:
        raise LookupError(f"classe inconnue du référentiel : {class_id!r}")
    return family_from_coin(row[0], row[1], row[2], emission_commune_group_ids(conn))


def families_for_bank(
    conn: sqlite3.Connection, anchors_kind: str = "2eur_all"
) -> dict[str, str]:
    """La famille de chaque `class_id` de la banque, en une passe.

    Clés : les `class_id` distincts de `dino_class_references` pour ce
    `anchors_kind`. Une classe de banque absente de `coins` lève, pour la
    même raison que `class_family` — sur la réplique du 2026-08-21 il n'y en
    a aucune (671 classes, 671 trouvées).
    """
    ec_groups = emission_commune_group_ids(conn)
    rows = conn.execute(
        "SELECT r.class_id, c.design_group_id, c.is_commemorative, c.face_value "
        "  FROM (SELECT DISTINCT class_id FROM dino_class_references "
        "         WHERE anchors_kind = ?) r "
        "  LEFT JOIN coins c ON c.eurio_id = r.class_id "
        " ORDER BY r.class_id",
        (anchors_kind,),
    ).fetchall()
    out: dict[str, str] = {}
    missing: list[str] = []
    for class_id, dgid, is_commemo, face_value in rows:
        if face_value is None and is_commemo is None:
            missing.append(class_id)
            continue
        out[class_id] = family_from_coin(dgid, is_commemo, face_value, ec_groups)
    if missing:
        raise LookupError(
            f"{len(missing)} classe(s) de la banque {anchors_kind!r} absente(s) "
            f"de `coins` : {', '.join(missing[:5])}"
            + (" …" if len(missing) > 5 else "")
        )
    return out
