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
(`SUGGESTIONS_ANCHORS_KIND` / `SUGGESTIONS_ENCODER_VERSION`).

Cette règle existait parce que le verdict lisait `2eur_commemo`, qui ne contient
aucune étiquette de pièce courante (0 sur 508 au rebuild du 2026-08-19) : un
périmètre bâti dessus était vide pour toute classe standard, sans la moindre
erreur pour le dire. Depuis le 2026-08-24 les deux constantes désignent la MÊME
banque (`2eur_all`/vitl14), donc la distinction ne mord plus — on garde
`SUGGESTIONS_*` ici parce que c'est bien de suggestions qu'il s'agit, et parce
que rien ne garantit que les deux resteront confondues.

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
    "DEFAULT_MIN_DENOM",
    "DINO_RANKS",
    "ERA_OPEN",
    "DinoScope",
    "build_dino_scope",
    "class_country",
    "class_era",
    "suggestions_join_sql",
]

#: Les seuls rangs offerts à l'opérateur. Trois paliers, pas un curseur : le
#: rang n'est pas une grandeur continue et un champ libre inviterait à demander
#: un top-20 dont la précision n'a jamais été mesurée.
DINO_RANKS: tuple[int, ...] = (1, 3, 5)

#: La borne haute d'une ère encore ouverte (aucun type suivant frappé). Un
#: entier plutôt que `None` : l'ère est un INTERVALLE, et un intervalle
#: half-open codé par un `None` se serait propagé jusque dans le SQL, où il se
#: compare silencieusement à faux.
ERA_OPEN: int = 9999

#: Le seuil proposé pour la porte dénomination quand un opérateur l'arme (O4b).
#: **Ce n'est pas un défaut** : `build_dino_scope(min_denom=None)` laisse la
#: porte ouverte, parce qu'elle coûte ~5 % de vrais positifs (mesuré sur 513
#: crops labellisés : elle garde 95,3 % des 2 €). C'est un choix d'opérateur,
#: pas une règle — cf. O4 §b et le tableau des réglages par défaut.
DEFAULT_MIN_DENOM: float = 0.4


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


def class_country(conn: sqlite3.Connection, class_id: str) -> str | None:
    """Le pays d'une classe (ISO2), ou `None` si on ne peut pas trancher.

    `None` DÉSACTIVE le filtre pays chez l'appelant plutôt que de le rendre
    vide : une classe dont on ignore le pays doit être servie entière, pas
    silencieusement réduite à zéro.

    🔴 **DEUX GRAINS, DEUX LECTURES — c'est le défaut V4, et il mordait ici.**
    Cette fonction reçoit tantôt un `design_group_id` (grain `coins` : la pêche
    saisie à la main, `it-2euro-standard-t1`), tantôt l'`eurio_id` du
    représentant (grain BANQUE : tout ce qui vient de `class_need` et de
    `dino_class_references`, `be-2014-2eur-standard-philippe`).

    La seule requête `WHERE COALESCE(design_group_id, eurio_id) = ?` ne servait
    que le premier grain : pour une pièce QUI A un `design_group_id`, le
    COALESCE rend ce groupe, donc chercher par son `eurio_id` ne matchait
    jamais. Mesuré le 2026-08-23 sur la réplique : **52 des 293 classes en
    besoin** rendaient `None` — donc filtre pays entièrement désactivé, en
    silence, sur des pièces dont `coins.country` est parfaitement renseigné
    (`be-2014-…philippe` → BE).

    On résout donc PAR GRAIN, et l'ordre compte :

    1. `eurio_id` exact — une pièce précise porte SON pays. Indispensable pour
       les émissions communes : `de-2012-…euro-cash` appartient au groupe
       `eu-euro-cash-2012` frappé par 18 pays, et passer par le groupe rendrait
       le pays MAJORITAIRE, c'est-à-dire faux 17 fois sur 18.
    2. sinon `design_group_id` — le grain `coins`, majorité (inchangé).

    Les deux espaces de noms sont disjoints (vérifié le 2026-08-23 : 0 `eurio_id`
    n'est un `design_group_id`), donc l'ordre ne peut pas se retourner.
    """
    def _one(sql: str) -> str | None:
        row = conn.execute(sql, (class_id,)).fetchone()
        if row is None:
            return None
        return row[0] if not isinstance(row, sqlite3.Row) else row["country"]

    # 1. grain BANQUE : la pièce elle-même.
    direct = _one(
        "SELECT country FROM coins WHERE eurio_id = ? AND country IS NOT NULL",
    )
    if direct:
        return direct
    # 2. grain `coins` : le groupe, par majorité.
    return _one(
        "SELECT country FROM coins "
        " WHERE COALESCE(design_group_id, eurio_id) = ? AND country IS NOT NULL "
        " GROUP BY country ORDER BY COUNT(*) DESC LIMIT 1",
    )


def class_era(conn: sqlite3.Connection, class_id: str) -> tuple[int, int] | None:
    """L'ère d'une classe — `(première année, dernière année)`, bornes incluses.

    `None` DÉSACTIVE le filtre d'ère chez l'appelant, exactement comme
    `class_country` rend `None` : une classe dont on ne sait pas dater le design
    doit être servie entière, jamais réduite à zéro par une borne inventée.

    LES DEUX RÈGLES, ET POURQUOI ELLES DIFFÈRENT
    --------------------------------------------
    - **commémorative** : son millésime, `(year, year)`. Une commémorative n'a
      pas d'ère, elle a une date.
    - **courante** : `[première année du groupe, première année du groupe
      SUIVANT du même pays − 1]`. La borne haute ne se lit PAS dans `coins` :
      `coins` ne contient que les millésimes déjà catalogués, donc
      `MAX(year)` d'un type encore frappé serait faux d'autant d'années qu'il
      reste à frapper. Un design court jusqu'à ce que le suivant paraisse.
      Mesuré : `es-2euro-juan-carlos-i-t1` = (1999, 2009), `t2` = (2010, 2014),
      `felipe-vi-t1` = (2015, `ERA_OPEN`).

    LES DEUX GRAINS, ENCORE (cf. `class_country`)
    ---------------------------------------------
    `class_id` est tantôt un `eurio_id` (grain BANQUE : tout ce qui vient de
    `class_need`), tantôt un `design_group_id` (grain `coins` : la pêche saisie
    à la main). On résout l'`eurio_id` d'abord — c'est lui qui porte le
    millésime d'une commémorative d'émission commune, que le groupe noierait
    dans les 18 pays qui l'ont frappée.
    """
    row = conn.execute(
        "SELECT design_group_id, is_commemorative, country, year "
        "  FROM coins WHERE eurio_id = ?",
        (class_id,),
    ).fetchone()
    if row is not None:
        dgid, is_commemo, country, year = row[0], row[1], row[2], row[3]
        if is_commemo:
            return (int(year), int(year)) if year is not None else None
        group = dgid or class_id
    else:
        # Grain `coins` : le groupe. `MIN(is_commemorative)` vaut 1 seulement si
        # TOUS les membres sont commémoratifs — un groupe mixte est traité comme
        # une courante, c'est-à-dire par ère, ce qui est le cas le plus large.
        g = conn.execute(
            "SELECT MIN(year), MAX(year), MIN(is_commemorative), country, COUNT(*) "
            "  FROM coins WHERE COALESCE(design_group_id, eurio_id) = ? "
            " GROUP BY country ORDER BY COUNT(*) DESC LIMIT 1",
            (class_id,),
        ).fetchone()
        if g is None or g[0] is None:
            return None
        if g[2]:
            return (int(g[0]), int(g[1]))
        group, country = class_id, g[3]
    if country is None:
        return None

    lo = conn.execute(
        "SELECT MIN(year) FROM coins "
        " WHERE COALESCE(design_group_id, eurio_id) = ? AND is_commemorative = 0",
        (group,),
    ).fetchone()[0]
    if lo is None:
        return None
    nxt = conn.execute(
        "SELECT MIN(m) FROM ("
        "  SELECT MIN(year) AS m FROM coins "
        "   WHERE country = ? AND face_value = 2.0 AND is_commemorative = 0 "
        "   GROUP BY COALESCE(design_group_id, eurio_id) HAVING m > ?)",
        (country, int(lo)),
    ).fetchone()[0]
    return (int(lo), int(nxt) - 1 if nxt is not None else ERA_OPEN)


def _era_predicate(alias: str, era: tuple[int, int]) -> tuple[str, list[object]]:
    """« le titre de l'annonce ne CONTREDIT pas l'ère de la classe ».

    ⛔ **La sémantique d'intervalle n'est pas un détail d'implémentation.**
    `years_json = [1999, 2012]` est lu comme l'intervalle `[1999 … 2012]`, PAS
    comme l'énumération `{1999, 2012}` : un titre « 1999–2012 » ne contient pas
    littéralement `2004`, et une commémorative de 2004 se ferait écarter à tort.
    La règle est donc, avec `Y = years_json` :

        contradiction  ⇔  NOT (min(Y) <= era_hi AND era_lo <= max(Y))

    Coût mesuré de la confusion : le rappel des lots tombe de 85,4 % à 74,2 %.
    Le test de mutation de `tests/test_dino_scope.py` est exactement celui-là.

    `MIN`/`MAX` plutôt que `Y[0]`/`Y[-1]` : même règle, sans parier sur l'ordre
    d'écriture du tableau.

    Trois façons de NE PAS contredire, et elles passent toutes les trois :
    aucune ligne de signaux, `years_json` vide, ou les deux intervalles se
    recoupent. Le silence n'est pas une contradiction — c'est la règle qui rend
    ce filtre gratuit en vrais positifs.
    """
    return (
        f"NOT EXISTS (SELECT 1 FROM listing_text_signals lts_era"
        f" WHERE lts_era.source_image_id = {alias}.id"
        f"   AND json_array_length(lts_era.years_json) > 0"
        f"   AND NOT ("
        f"(SELECT MIN(CAST(j.value AS INTEGER)) FROM json_each(lts_era.years_json) j) <= ?"
        f" AND "
        f"(SELECT MAX(CAST(j.value AS INTEGER)) FROM json_each(lts_era.years_json) j) >= ?))",
        [era[1], era[0]],
    )


def _denom_predicate(alias: str, min_denom: float) -> tuple[str, list[object]]:
    """« la probe ne dit pas que ce crop n'est pas une 2 € ».

    `IS NULL` passe : la probe ne couvre que 7 910 des 12 454 crops, et écarter
    l'inconnu ferait de cette porte un filtre de couverture déguisé en filtre de
    dénomination. Un signal absent n'est pas un signal négatif — c'est la même
    règle que pour l'ère.
    """
    return (
        f"({alias}.denom_2eur_score IS NULL OR {alias}.denom_2eur_score >= ?)",
        [float(min_denom)],
    )


def _class_predicate(
    alias: str, class_ids: tuple[str, ...], rank: int,
) -> tuple[str, list[object]]:
    """« la prédiction pointe l'une de ces étiquettes », au rang demandé.

    Extrait pour que la SONDE de désarmement (`_probe_country`) et le périmètre
    rendu à l'appelant soient littéralement la même condition. Deux rédactions
    du même prédicat finiraient par diverger, et le désarmement se déciderait
    alors sur une population qui n'est pas celle qu'on sert.
    """
    ph = ",".join("?" * len(class_ids))
    if rank == 1:
        return f"{alias}.top1_eurio_id IN ({ph})", list(class_ids)
    # `j.key` est l'index dans le tableau (json_each sur un array) ; `< rank`
    # garde les `rank` premières positions. top_k_json est trié par sim
    # décroissante à l'écriture (cf. schema.sql).
    return (
        f"EXISTS (SELECT 1 FROM json_each({alias}.top_k_json) j "
        f"WHERE j.key < ? "
        f"AND json_extract(j.value, '$.eurio_id') IN ({ph}))",
        [rank, *class_ids],
    )


def _probe(
    conn: sqlite3.Connection,
    *,
    bits: list[str],
    args: list[object],
    gate_sql: str,
    gate_args: list[object],
    country: str | None,
) -> tuple[int, int, int]:
    """Ce qu'un filtre retire, sur la file OUVERTE — en une requête.

    `gate_sql` est la condition dont on mesure l'effet : l'ère au premier
    passage, la porte dénomination au second (elle se compte alors sur ce qui a
    déjà survécu à l'ère et au pays, d'où deux appels et non deux colonnes).

    Rend `(brut, apres_gate, apres_gate_et_pays)`. Les trois comptes sont
    **emboîtés**, dans l'ordre où le WHERE les applique : ère d'abord (elle ne
    coûte aucun vrai positif), pays ensuite (il en coûte ~5 %). Les compter
    séparément donnerait deux effets qui ne s'additionnent pas, et un écran qui
    annonce « 12 masqués par l'ère + 8 par le pays » au-dessus d'une file qui en
    a perdu 15.

    C'est aussi ce qui décide le désarmement du pays : il se décide sur le pool
    APRÈS ère, seul pool que la file servira réellement.

    LA POPULATION SONDÉE, ET POURQUOI CELLE-LÀ
    ------------------------------------------
    La file de review OUVERTE (`review_queue.status = 'open'`), exactement comme
    `class_need._pending_by_class` et `dino_candidates_summary`. Le désarmement
    est une propriété de **la classe**, calculée une fois — pas de l'item, ni de
    la requête de l'appelant. C'est ce qui le distingue du repli automatique
    écarté en D1 de `peche-dino` : là-bas le périmètre dépendait de l'item et
    deux crops voisins étaient servis par deux règles ; ici la bascule est
    calculée une fois et elle est AFFICHÉE.

    Conséquence assumée : un appelant qui restreint par ailleurs (un run, une
    cohorte) hérite du désarmement décidé sur la classe entière. C'est
    volontaire — sinon le même mot dirait deux choses selon l'écran.

    MESURE QUI JUSTIFIE CE CODE (réplique du 2026-08-22, banque a55e6594)
    --------------------------------------------------------------------
        classes 'review'                            293
          que le filtre pays viderait ENTIÈREMENT   147  (50 %)
          crops rendus inatteignables               558
        et 120 des 147 classes du palier 1 (82 %)

    Les pays touchés sont exactement les plus pauvres en ancres : LU 14, PT 13,
    GR 12, VA 12, MC 10, FI 9, LT 9, SM 9, LV 8, MT 8. Cause racine :
    `listing_country` n'est pas le pays de l'annonce mais celui que la recherche
    VISAIT (`sources/ebay/adapter.py:601`) — là où on n'a jamais scrapé, il ne
    reste rien (VISION §V3).
    """
    where = " AND ".join(bits) if bits else "1"
    era_ok = gate_sql or "1"
    pays_ok = "si.listing_country = ?" if country else "1"
    row = conn.execute(
        f"""
        SELECT COUNT(*) AS brut,
               SUM(CASE WHEN {era_ok} THEN 1 ELSE 0 END) AS apres_gate,
               SUM(CASE WHEN ({era_ok}) AND ({pays_ok}) THEN 1 ELSE 0 END) AS apres_pays
          FROM review_queue rq
          JOIN image_assets a ON a.id = rq.image_asset_id
          JOIN source_images si ON si.id = a.source_image_id
          {suggestions_join_sql("ps")}
         WHERE rq.status = 'open' AND {where}
        """,
        (*gate_args, *gate_args, *([country] if country else []), *args),
    ).fetchone()
    return (
        int(row[0] or 0), int(row[1] or 0), int(row[2] or 0),
    )


@dataclass(frozen=True)
class DinoScope:
    """Un périmètre par prédiction, prêt à coller dans un WHERE.

    `sql` est vide quand le périmètre ne contraint rien (ni classe ni marge) :
    l'appelant peut le concaténer sans brancher.

    ⚠️ **La requête de l'appelant DOIT joindre `source_images`** sous le nom
    passé en `source_alias` : depuis O4a le périmètre par défaut porte le filtre
    d'ère, qui lit l'annonce. Sans la jointure, `no such column: si.id` — une
    panne bruyante, préférable de loin à un filtre qui s'évanouit en silence.
    """

    sql: str
    args: tuple[object, ...]
    #: Les étiquettes sous lesquelles la banque indexe la classe demandée.
    #: Vide si aucune classe n'a été demandée.
    class_ids: tuple[str, ...]
    rank: int
    #: Le pays sur lequel le filtre a mordu, ou `None` s'il ne s'applique pas
    #: (désactivé, ou classe sans pays résoluble). L'écran doit pouvoir dire
    #: qu'il filtre, et sur quoi.
    country: str | None = None
    #: Le filtre pays s'est-il RETIRÉ parce qu'il ne laissait rien ? Quand c'est
    #: vrai, `country` nomme toujours le pays visé (l'écran doit pouvoir dire
    #: lequel il a renoncé à appliquer) mais `sql` ne le contraint plus.
    #: ⚠️ Un écran qui lit `country` sans lire ce drapeau annoncera « pays LU »
    #: au-dessus d'une file qui sert tous les pays.
    country_disarmed: bool = False
    #: Ce que le filtre pays masque effectivement (0 s'il est désarmé, puisqu'il
    #: ne masque alors plus rien). Un filtre actif par défaut qui tait son effet
    #: ment par omission.
    n_hidden_by_country: int = 0
    #: L'ère de la classe, `(première, dernière)` bornes incluses, ou `None`
    #: quand elle ne se résout pas — auquel cas le filtre d'ère ne s'applique
    #: pas, comme `country=None` désactive le filtre pays.
    era: tuple[int, int] | None = None
    #: Ce que la contradiction d'ère écarte, sur la file ouverte de la classe.
    #: Compté AVANT le filtre pays : les trois comptes sont emboîtés dans
    #: l'ordre du WHERE, jamais additionnables autrement (cf. `_probe`).
    n_hidden_by_era: int = 0
    #: Ce que la porte dénomination écarterait en plus, une fois l'ère et le
    #: pays appliqués. Reste 0 quand la porte n'est pas armée (`min_denom=None`,
    #: le défaut) : un compteur qui parlerait d'un filtre inactif ferait croire
    #: à une perte qui n'a pas lieu.
    n_hidden_by_denom: int = 0

    @property
    def is_empty(self) -> bool:
        return not self.sql

    @property
    def country_active(self) -> bool:
        """Le filtre pays mord-il réellement sur cette requête ?"""
        return self.country is not None and not self.country_disarmed


def build_dino_scope(
    conn: sqlite3.Connection,
    *,
    dino_class: str | None,
    rank: int = 1,
    min_spread: float | None = None,
    alias: str = "ps",
    country_only: bool = False,
    era_only: bool = True,
    min_denom: float | None = None,
    source_alias: str = "si",
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

    `source_alias` est l'alias de `source_images` DANS LA REQUÊTE DE L'APPELANT
    — `si` ici, `s` dans `list_queue`. Les deux filtres qui lisent l'annonce
    (pays et ère) s'y accrochent. Se tromper d'alias donne un `no such column`
    bruyant, et c'est voulu : un filtre qui rate en silence sert le pool entier
    en croyant l'avoir restreint.

    `country_only` restreint aux annonces du PAYS DE LA CLASSE
    (`{source_alias}.listing_country`). Mesuré le 2026-08-20 sur les crops déjà
    tranchés par un humain, à la maille classe :

        courantes       precision 91,3 % (n=392)  -> 99,1 %   vrais gardés 340/358 = 95,0 %
        commémoratives  precision 94,6 % (n=1759) -> 98,4 %   vrais gardés 1587/1664 = 95,4 %

    Il coupe ~91 % des faux positifs pour ~5 % de vrais — et les 5 % perdus ont
    un profil identifiable : des coffrets multi-pays (13 des 18 crops perdus
    venaient d'annonces belges). D'où un réglage, et non une règle en dur.

    🔴 **Et il SE DÉSARME quand il ne laisse rien** (O4c, D10). Le « 5 % de
    vrais positifs perdus » ci-dessus est un AGRÉGAT, et il vaut 100 % pour un
    cinquième du catalogue : mesuré le 2026-08-22, le filtre viderait
    entièrement **147 des 293 classes en besoin** (558 crops) et **82 % des
    classes du palier 1**. Quand le pool filtré tombe à zéro alors que le pool
    brut ne l'est pas, le filtre se retire, `country_disarmed` passe à `True`,
    et **l'écran doit le dire**. C'est la même règle que `class_country` ci-dessus,
    étendue du cas « pays inconnu » au cas « pays connu mais jamais scrapé » —
    parce que les deux produisent la même panne muette : zéro ligne, qui se lit
    « rien à trancher », plausible et faux.

    ⛔ Ce n'est PAS le repli automatique écarté en D1 de `peche-dino` : là-bas le
    périmètre dépendait de l'**item**, ici la bascule dépend de la **classe**,
    elle est calculée une fois, et elle est affichée. Cf. `_probe`.

    `era_only` (**actif par défaut**, O4a) écarte les crops dont le titre
    CONTREDIT l'ère de la classe — intervalle contre intervalle, jamais une
    énumération (cf. `_era_predicate`). Il est actif par défaut parce qu'il ne
    coûte aucun vrai positif en mesure : lots/courantes 47 servis à 91,5 % →
    45 à 95,6 %, lots/commémos strictement inchangés, singles/courantes
    299 → 296 à 100 %. Son premier effet visible est de retirer de la tête de la
    file belge le lot « 14 Stück (1999–2012) » : 9 crops marqués Philippe dans
    une annonce où aucune pièce ne peut l'être (ère 2014+).

    `min_denom` (**inactif par défaut**, O4b) est un seuil sur
    `{alias}.denom_2eur_score`. `DEFAULT_MIN_DENOM = 0,4` garde 95,3 % des 2 €
    labellisées : il coûte donc ~5 % de vrais positifs, ce qui en fait un choix
    d'opérateur et non une règle. Ne PAS l'armer par défaut est la décision ; le
    scope dit `n_hidden_by_denom` pour que l'écran puisse la proposer avec son
    prix.

    ⛔ **Ne pas confondre avec le top-1 SCOPÉ PAYS** (`top1_country_eurio_id`,
    déjà en base). Mesuré le même jour : il ne gagne que 1,2 point (91,3 →
    92,5 %) et sa couverture est trouée — `target_country` dérive de
    `target_eurio_id`, NULL sur tout le pool ambigu, soit 2254 des 6651 crops
    ouverts et la moitié du pool des classes standard. Piste écartée APRÈS
    mesure ; ne pas la rouvrir sans en refaire une.
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
        bit, bit_args = _class_predicate(alias, class_ids, rank)
        bits.append(bit)
        args.extend(bit_args)

    if min_spread is not None:
        bits.append(
            f"COALESCE({alias}.country_spread, {alias}.spread) >= ?"
        )
        args.append(float(min_spread))

    # Les conditions de la SONDE : les mêmes que le périmètre, mais avec les
    # alias qu'elle contrôle (`ps` / `si`) — ceux de l'appelant n'existent pas
    # dans sa requête. Construites une fois, relues par chaque filtre.
    probe_bits: list[str] = []
    probe_args: list[object] = []
    if class_ids:
        _b, _a = _class_predicate("ps", class_ids, rank)
        probe_bits.append(_b)
        probe_args.extend(_a)
    if min_spread is not None:
        probe_bits.append("COALESCE(ps.country_spread, ps.spread) >= ?")
        probe_args.append(float(min_spread))

    # L'ÈRE (O4a). Elle se calcule avant le pays parce que le désarmement du
    # pays se décide sur le pool que la file servira, c'est-à-dire après ère.
    era: tuple[int, int] | None = None
    era_sql, era_args = "", []
    if era_only and dino_class:
        era = class_era(conn, dino_class)
        if era is not None:
            era_sql, era_args = _era_predicate(source_alias, era)
            bits.append(era_sql)
            args.extend(era_args)

    country: str | None = None
    disarmed = False
    n_hidden_era = 0
    n_hidden_country = 0
    if (era is not None) or (country_only and dino_class):
        country = (
            class_country(conn, dino_class) if country_only and dino_class else None
        )
        probe_era_sql = _era_predicate("si", era)[0] if era is not None else ""
        brut, apres_ere, apres_pays = _probe(
            conn, bits=probe_bits, args=probe_args,
            gate_sql=probe_era_sql, gate_args=list(era_args), country=country,
        )
        n_hidden_era = max(brut - apres_ere, 0)
        if country:
            # La règle, telle qu'elle est déjà écrite pour `class_country` : le
            # filtre se retire plutôt que de rendre zéro. Un pool vide AVANT lui
            # n'est PAS un désarmement — il n'y a simplement rien à trancher, et
            # c'est un sujet de scrape.
            disarmed = apres_ere > 0 and apres_pays == 0
            if disarmed:
                n_hidden_country = 0
            else:
                n_hidden_country = max(apres_ere - apres_pays, 0)
                bits.append(f"{source_alias}.listing_country = ?")
                args.append(country)

    # LA PORTE DÉNOMINATION (O4b) — inactive par défaut, en dernier parce
    # qu'elle se compte sur ce qui reste une fois l'ère et le pays passés.
    n_hidden_denom = 0
    if min_denom is not None:
        denom_sql, denom_args = _denom_predicate(alias, min_denom)
        if dino_class:
            probe_bits2 = list(probe_bits)
            probe_args2 = list(probe_args)
            if era is not None:
                probe_bits2.append(_era_predicate("si", era)[0])
                probe_args2.extend(era_args)
            if country and not disarmed:
                probe_bits2.append("si.listing_country = ?")
                probe_args2.append(country)
            base, reste, _ = _probe(
                conn, bits=probe_bits2, args=probe_args2,
                gate_sql=_denom_predicate("ps", min_denom)[0],
                gate_args=list(denom_args), country=None,
            )
            n_hidden_denom = max(base - reste, 0)
        bits.append(denom_sql)
        args.extend(denom_args)

    return DinoScope(
        sql=" AND ".join(bits),
        args=tuple(args),
        class_ids=class_ids,
        rank=rank,
        country=country,
        country_disarmed=disarmed,
        n_hidden_by_country=n_hidden_country,
        era=era,
        n_hidden_by_era=n_hidden_era,
        n_hidden_by_denom=n_hidden_denom,
    )
