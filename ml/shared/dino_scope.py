"""Le périmètre « ce que DINO reconnaît » — stdlib-only, un seul endroit.

LA BASCULE QUE CE MODULE INCARNE
--------------------------------
Une file de review a toujours été définie par **ce que le scrape visait**
(`source_images.target_eurio_id`). Pour une classe courante c'est le mauvais
périmètre : le scrape eBay cherche « 2 euro Italia », route ses crops dans un
pool ambigu pays, et la file sert 57 items dont 2 sont la classe. Ici on définit
le périmètre par **la prédiction** : tout crop que la banque estampille de cette
classe, quels que soient le pays de l'annonce, la cible du scrape et le `kind`.

Mesuré le 2026-08-20 sur `it-2euro-standard-t1`, crops ouverts :

    /review-queue?eurio_id=it-2002-…                        57 items
                            + order=dino&dino_top1_only     2 items
    périmètre par prédiction, top1                        139 items
                              top3                        321
                              top5                        485

CE QUI SE LIT, ET CE QUI NE SE LIT PAS
--------------------------------------
La jointure porte TOUJOURS sur la banque des **suggestions**
(`SUGGESTIONS_ANCHORS_KIND` / `SUGGESTIONS_ENCODER_VERSION`), jamais sur celle
du verdict — `2eur_commemo` ne contient aucune étiquette de pièce courante (0
sur 508 au rebuild du 2026-08-19), donc un périmètre bâti dessus serait
vide pour toute classe standard, sans la moindre erreur pour le dire.

⛔ `anchors_kind` et `encoder_version` sont indissociables : `2eur_all` n'existe
qu'en `dinov2-vitl14`. Basculer le seul kind donne un JOIN à zéro ligne.

LA MARGE, PAS LA SIMILARITÉ
---------------------------
`top1_sim` ne sépare rien (médiane hors-scope 0,834 ≈ médiane des top1 corrects
0,836). C'est le SPREAD qui sépare, et le service le lit avec repli :
``COALESCE(country_spread, spread)`` — un filtre sur la seule colonne country
écarte en silence des crops que le verdict, lui, évalue.

Précision du top-1 confrontée aux labels humains, maille CLASSE, le 2026-08-20 :

    standards  marge ≥ 0,10 : 95,4 % (n=217)  ·  0,05–0,10 : 85,5 %  ·  < 0,05 : 84,1 %
    commémos   marge ≥ 0,10 : 99,9 % (n=1352) ·  0,05–0,10 : 94,5 %  ·  < 0,05 : 55,2 %

    -- la requête, pour la rejouer (eurio.replica.db) :
    -- with truth as (select a.id aid, coalesce(c.design_group_id,a.eurio_id) cls,
    --                       c.is_commemorative
    --                  from image_assets a join coins c on c.eurio_id=a.eurio_id
    --                 where a.resolution_status='manual' and a.eurio_id is not null),
    --      pred as (select p.asset_id aid,
    --                      coalesce(cp.design_group_id,p.top1_eurio_id) pcls,
    --                      coalesce(p.country_spread,p.spread) m
    --                 from image_asset_dino_predictions p
    --                 left join coins cp on cp.eurio_id=p.top1_eurio_id
    --                where p.anchors_kind='2eur_all')
    -- select t.is_commemorative, count(*), 100.0*sum(t.cls=pred.pcls)/count(*)
    --   from truth t join pred on pred.aid=t.aid group by 1;

1 crop sur 20 est faux sur une courante : ce périmètre alimente une file où un
humain regarde, jamais un auto-accept.

CONTRAT D'IMPORT
----------------
**stdlib uniquement** (sqlite3). Appelé par l'image lean du VPS comme par l'API
locale lourde ; importer `training.foundation` y tirerait numpy et torch. Même
raison d'être que `shared/verdict_scope.py`.
"""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass

from shared.verdict_scope import (
    SUGGESTIONS_ANCHORS_KIND,
    SUGGESTIONS_ENCODER_VERSION,
)

__all__ = [
    "DINO_RANKS",
    "DinoScope",
    "build_dino_scope",
    "suggestions_join_sql",
]

#: Les seuls rangs offerts à l'opérateur. Trois paliers, pas un curseur : le
#: rang n'est pas une grandeur continue et un champ libre inviterait à demander
#: un top-20 dont la précision n'a jamais été mesurée.
DINO_RANKS: tuple[int, ...] = (1, 3, 5)


def suggestions_join_sql(alias: str = "ps") -> str:
    """Le LEFT JOIN vers la banque des suggestions, littéral et sans paramètre.

    Les deux constantes sont interpolées plutôt que passées en args : elles
    viennent de `shared/verdict_scope`, jamais d'une entrée utilisateur, et
    l'interpolation garde le fragment composable avec des `WHERE` paramétrés
    (l'ordre des `?` reste celui du seul appelant).
    """
    return (
        f"LEFT JOIN image_asset_dino_predictions {alias}\n"
        f"       ON {alias}.asset_id = a.id\n"
        f"      AND {alias}.encoder_version = '{SUGGESTIONS_ENCODER_VERSION}'\n"
        f"      AND {alias}.anchors_kind = '{SUGGESTIONS_ANCHORS_KIND}'"
    )


@dataclass(frozen=True)
class DinoScope:
    """Un périmètre par prédiction, prêt à coller dans un WHERE.

    `sql` est vide quand le périmètre ne contraint rien (ni classe ni marge) :
    l'appelant peut le concaténer sans brancher.
    """

    sql: str
    args: tuple[object, ...]
    #: Les étiquettes sous lesquelles la banque indexe la classe demandée.
    #: Vide si aucune classe n'a été demandée.
    class_ids: tuple[str, ...]
    rank: int

    @property
    def is_empty(self) -> bool:
        return not self.sql


def build_dino_scope(
    conn: sqlite3.Connection,
    *,
    dino_class: str | None,
    rank: int = 1,
    min_spread: float | None = None,
    alias: str = "ps",
) -> DinoScope:
    """Construit « la prédiction pointe cette classe », en SQL.

    `dino_class` est un **class_id** : un `design_group_id` pour une courante,
    un `eurio_id` pour une commémorative. Il est traduit en étiquettes de banque
    par `shared.bank_classes` — la banque indexe une courante sous le plus
    ancien millésime de son ère, et un filtre naïf sur l'identifiant demandé
    renverrait zéro ligne sans que rien ne le signale.

    `rank = 1` teste `top1_eurio_id` (indexé). `rank ∈ {3, 5}` descend dans
    `top_k_json` : la classe compte si elle apparaît dans les `rank` premières
    positions. Un rang hors `DINO_RANKS` lève `ValueError` — le silence sur un
    rang inconnu donnerait un périmètre plausible et faux.

    `min_spread` filtre sur `COALESCE(country_spread, spread)`, la grandeur que
    le verdict utilise réellement.
    """
    if rank not in DINO_RANKS:
        raise ValueError(
            f"dino_rank={rank!r} hors des paliers offerts {DINO_RANKS}."
        )

    bits: list[str] = []
    args: list[object] = []
    class_ids: tuple[str, ...] = ()

    if dino_class:
        from shared.bank_classes import bank_class_ids_for_class

        class_ids = tuple(bank_class_ids_for_class(conn, dino_class))
        ph = ",".join("?" * len(class_ids))
        if rank == 1:
            bits.append(f"{alias}.top1_eurio_id IN ({ph})")
            args.extend(class_ids)
        else:
            # `j.key` est l'index dans le tableau (json_each sur un array) ;
            # `< rank` garde les `rank` premières positions. top_k_json est
            # trié par sim décroissante à l'écriture (cf. schema.sql).
            bits.append(
                f"EXISTS (SELECT 1 FROM json_each({alias}.top_k_json) j "
                f"WHERE j.key < ? "
                f"AND json_extract(j.value, '$.eurio_id') IN ({ph}))"
            )
            args.append(rank)
            args.extend(class_ids)

    if min_spread is not None:
        bits.append(
            f"COALESCE({alias}.country_spread, {alias}.spread) >= ?"
        )
        args.append(float(min_spread))

    return DinoScope(
        sql=" AND ".join(bits),
        args=tuple(args),
        class_ids=class_ids,
        rank=rank,
    )
