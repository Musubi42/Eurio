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
