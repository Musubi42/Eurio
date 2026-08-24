"""Sous quel identifiant la banque d'ancres indexe une pièce — stdlib-only.

LE PIÈGE QUE CE MODULE EXISTE POUR ÉVITER
-----------------------------------------
La banque `2eur_all` n'indexe PAS une pièce courante sous son `eurio_id`, ni
sous son `design_group_id` : elle l'indexe sous l'eurio_id du **représentant**
de son groupe de dessin, c'est-à-dire le membre au millésime le plus ancien
(`training/foundation/anchors._select_2eur_standard_groups`, tri
``year ASC, eurio_id ASC``).

Mesuré le 2026-08-19 sur les groupes multi-membres :

    be-2euro-albert-ii-t1   be-1999… DANS LA BANQUE   be-2007… absent
    fr-2euro-standard-t1    fr-1999… DANS LA BANQUE   fr-2007… absent
    it-2euro-standard-t1    it-2002… DANS LA BANQUE   it-2008… absent

Conséquence : un filtre naïf ``WHERE top1_eurio_id = :eurio_id`` renvoie **zéro
ligne** pour toute pièce courante qui n'est pas la plus ancienne de son ère —
et rien ne le signale, c'est une liste vide parfaitement plausible. D'où ce
module, et d'où sa duplication de la convention de tri : elle doit rester en
miroir de `anchors.py`, ce que verrouille `tests/test_bank_classes.py`.

Contrat d'import : **stdlib uniquement** (sqlite3). Il est appelé aussi bien par
l'image lean du VPS que par l'API locale lourde ; importer
`training.foundation` y tirerait numpy et torch.
"""
from __future__ import annotations

import sqlite3


def bank_class_ids(conn: sqlite3.Connection, eurio_id: str) -> list[str]:
    """Les identifiants sous lesquels la banque peut indexer cette pièce.

    Renvoie toujours l'``eurio_id`` lui-même (cas commémorative : une pièce =
    une classe, indexée sous son propre identifiant) et, si la pièce est une
    courante appartenant à un groupe de dessin, le représentant de ce groupe.
    Les deux, sans brancher : une liste de un ou deux éléments, à passer tels
    quels dans un ``IN (…)``.

    Une pièce inconnue renvoie ``[eurio_id]`` — le filtre ne ramènera rien,
    ce qui est le comportement correct, mais l'appelant n'a pas à distinguer.
    """
    row = conn.execute(
        "SELECT COALESCE(design_group_id, eurio_id) AS class_id, is_commemorative "
        "  FROM coins WHERE eurio_id = ?",
        (eurio_id,),
    ).fetchone()
    if row is None:
        return [eurio_id]

    class_id = row[0] if not isinstance(row, sqlite3.Row) else row["class_id"]
    is_commemo = row[1] if not isinstance(row, sqlite3.Row) else row["is_commemorative"]
    if is_commemo:
        return [eurio_id]

    # Même tri que `_select_2eur_standard_groups` : le plus ancien millésime
    # du groupe porte l'ancre. Changer ce tri ici sans le changer là-bas
    # rendrait le filtre silencieusement vide.
    rep = conn.execute(
        "SELECT eurio_id FROM coins "
        " WHERE COALESCE(design_group_id, eurio_id) = ? "
        "   AND is_commemorative = 0 AND canonical_eurio_id IS NULL "
        " ORDER BY year ASC, eurio_id ASC LIMIT 1",
        (class_id,),
    ).fetchone()
    if rep is None:
        return [eurio_id]
    rep_id = rep[0] if not isinstance(rep, sqlite3.Row) else rep["eurio_id"]
    return [eurio_id] if rep_id == eurio_id else [eurio_id, rep_id]


def bank_class_ids_for_many(
    conn: sqlite3.Connection, eurio_ids: list[str]
) -> list[str]:
    """Union dédupliquée de `bank_class_ids` sur plusieurs pièces (cohorte)."""
    out: list[str] = []
    seen: set[str] = set()
    for eid in eurio_ids:
        for cid in bank_class_ids(conn, eid):
            if cid not in seen:
                seen.add(cid)
                out.append(cid)
    return out


def bank_class_ids_for_class(
    conn: sqlite3.Connection, class_id: str
) -> list[str]:
    """Les identifiants sous lesquels la banque peut indexer CETTE CLASSE.

    Entrée : un `class_id` — c'est-à-dire un `design_group_id` (courante) ou un
    `eurio_id` (commémorative), la maille à laquelle le préflight, le bake et la
    banque raisonnent tous. Les deux surfaces qui appellent cette fonction (la
    file cohorte et la page pêche) tiennent un `class_id`, pas un `eurio_id` :
    passer par `bank_class_ids` obligerait chaque appelant à choisir un membre
    au hasard — et un membre non-représentant renvoie zéro ligne sans rien dire.

    Renvoie l'union des étiquettes de tous les membres, `class_id` inclus quand
    il désigne lui-même une pièce. Une classe inconnue renvoie ``[class_id]`` :
    le filtre ne ramènera rien, ce qui est correct, et l'appelant n'a pas à
    distinguer.
    """
    rows = conn.execute(
        "SELECT eurio_id FROM coins "
        " WHERE COALESCE(design_group_id, eurio_id) = ? "
        " ORDER BY eurio_id ASC",
        (class_id,),
    ).fetchall()
    members = [
        (r[0] if not isinstance(r, sqlite3.Row) else r["eurio_id"]) for r in rows
    ]
    if not members:
        return [class_id]
    return bank_class_ids_for_many(conn, members)


def builder_class_key_by_eurio_id(conn: sqlite3.Connection) -> dict[str, str]:
    """Sous quel ``class_id`` le BUILDER rangera un crop, pièce par pièce.

    C'est la fonction inverse de `bank_class_ids` : celle-ci part d'une pièce
    (l'étiquette HUMAINE d'un crop, ``image_assets.eurio_id``) et rend la classe
    de banque qui recevra l'exemplaire — commémorative : elle-même ; courante :
    le représentant de son groupe de dessin.

    ⛔ POURQUOI ELLE NE PEUT PAS ÊTRE REMPLACÉE PAR ``top1_eurio_id``.
    La banque ne range pas un crop là où le MODÈLE le voit, mais là où l'HUMAIN
    l'a mis (`training/foundation/anchors._candidate_crops_for_class` filtre sur
    ``image_assets.eurio_id IN members``). Compter des acquis sur le top-1
    promet des exemplaires à une classe qui n'en recevra aucun : mesuré le
    2026-08-24, `lu-2025-…-throne-hologram` annonçait « +6 acquis » avec ZÉRO
    crop à son nom (`/coins/…-hologram/assets` → `total: 0`), assez pour la
    déclarer *pleine* et la sortir du travail.

    Une pièce absente du dictionnaire est une pièce dont le builder ne fait
    AUCUNE classe : une courante doublon (``canonical_eurio_id`` non nul), que
    ``_select_2eur_standard_groups`` écarte de ses membres. Ses crops ne
    deviendront jamais des exemplaires — les compter serait la même promesse
    creuse.

    Une commémorative se rend toujours elle-même, même sans ``numista_id``.
    Le builder n'en ferait pas de spec, mais une classe absente de la banque
    n'est de toute façon lue par personne (`class_need._build` n'itère que sur
    ce que ``dino_class_references`` contient) : ajouter la condition ici ne
    ferait que créer un écart de plus entre deux modules.

    Miroir de ``anchors._class_specs_2eur_all`` — même WHERE, même tri. Les
    deux doivent changer ensemble ; `tests/test_class_need.py` verrouille
    l'essentiel (un membre d'ère rend son représentant) et
    `BUILDER_VALIDATED_STATUSES` verrouille les statuts.
    """
    # Le représentant de chaque groupe standard : même WHERE et même ORDER BY
    # que `_select_2eur_standard_groups`, donc même premier membre.
    reps: dict[str, str] = {}
    for row in conn.execute(
        "SELECT COALESCE(design_group_id, eurio_id) AS grp, eurio_id "
        "  FROM coins "
        " WHERE face_value = 2.0 AND is_commemorative = 0 "
        "   AND canonical_eurio_id IS NULL "
        " ORDER BY year ASC, eurio_id ASC"
    ):
        grp = row[0] if not isinstance(row, sqlite3.Row) else row["grp"]
        eid = row[1] if not isinstance(row, sqlite3.Row) else row["eurio_id"]
        reps.setdefault(grp, eid)

    out: dict[str, str] = {}
    for row in conn.execute(
        "SELECT eurio_id, COALESCE(design_group_id, eurio_id) AS grp, "
        "       is_commemorative, numista_id, canonical_eurio_id "
        "  FROM coins WHERE face_value = 2.0"
    ):
        vals = tuple(row)
        eid, grp, is_commemo, _numista_id, canonical_eid = vals[:5]
        if is_commemo:
            out[eid] = eid
            continue
        if canonical_eid is not None:
            continue
        rep = reps.get(grp)
        if rep is not None:
            out[eid] = rep
    return out
