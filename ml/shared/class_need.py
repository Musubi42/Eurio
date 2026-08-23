"""Le besoin par classe, calculé en UN seul endroit (O1) — stdlib-only.

CE QUE CE MODULE RÉPOND
-----------------------
Pour n'importe quelle classe de la banque : combien lui manque-t-il, et à quoi
tient son manque. Appelé par l'écran (O2), l'entonnoir (O3) et, à terme,
l'allocateur. Spec : `docs/work-in-progress/pipeline-propre/outils/O1-besoin-par-classe.md`,
arbitrages D1–D4 dans `../DECISIONS.md`.

POURQUOI UN MODULE ET PAS UNE REQUÊTE DANS L'ÉCRAN
-------------------------------------------------
Ce calcul existait déjà trois fois, à trois mailles différentes
(`scripts/allocate_ebay_scrape.py` au groupe de découverte, `useCohortFloor.ts`
et `repository.dino_candidates_summary` à la maille `coins`) — et la banque,
elle, indexe à une QUATRIÈME maille : l'`eurio_id` du représentant (VISION
§V4). Une requête écrite avec la convention `coins` rend 2 166 crops « hors
banque » qui y sont pourtant, sans lever quoi que ce soit (défaut Q13).

LA MAILLE
---------
Tout ici est au grain BANQUE : `dino_class_references.class_id`. Pas de
`COALESCE(design_group_id, eurio_id)` pour compter `have` ou `pending` — c'est
le piège Q13. La seule traduction coin → banque passe par
`shared.bank_classes.bank_class_ids` (`need_for`), jamais par un COALESCE
local.

LES DEUX VOIES, ET CELLE QUI COMPTE
----------------------------------
`have`/`need`/`bottleneck` parlent de la voie B : les exemplaires `fps` de la
banque DINO (D1). `n_train_eligible` est la voie A (les crops eBay qui partent
au bake ArcFace) : elle s'AFFICHE, sur sa propre ligne, et n'entre dans aucun
verdict (FLOW-ADMIN §4).

CE QUE LE MODULE REFUSE DE FAIRE
--------------------------------
1. Il n'écrit rien. La connexion est ouverte par l'appelant, en lecture seule
   de préférence ; `tests/test_class_need.py` vérifie qu'aucun ordre SQL
   d'écriture n'apparaît dans ce fichier.
2. Il ne devine pas `anchors_kind`. Le couple `(anchors_kind, encoder_version)`
   est obligatoire : basculer l'un sans l'autre donne un JOIN à zéro ligne et
   tout en `scrape`, sans une erreur.
3. Il ne masque pas les classes pleines : elles sortent avec le verdict
   `pleine` — c'est l'information la plus utile de l'outil.

Contrat d'import : **stdlib uniquement** (sqlite3) + `shared.*`. L'image lean
du VPS doit pouvoir l'importer sans tirer numpy ni torch.
"""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from typing import Final

from shared.bank_classes import bank_class_ids
from shared.class_family import EMISSION_COMMUNE, emission_commune_group_ids, family_from_coin
from shared.verdict_scope import (
    SUGGESTIONS_ANCHORS_KIND,
    SUGGESTIONS_ENCODER_VERSION,
)

__all__ = [
    "BOTTLENECKS",
    "DEFAULT_CAP",
    "DEFAULT_TARGET",
    "TARGET_EMISSION_COMMUNE",
    "ClassNeed",
    "all_needs",
    "bottleneck_for",
    "need_for",
    "target_for_family",
]

#: Plafond dur de la banque : au-delà, `build_anchors_2eur_all` ignore les
#: crops. C'est la valeur de `training.foundation.anchors.DEFAULT_EXEMPLARS_PER_CLASS`,
#: recopiée ici parce que ce module-là tire torch et que l'image lean du VPS
#: doit pouvoir importer celui-ci. `tests/test_class_need.py` verrouille
#: l'égalité des deux ; changer l'un sans l'autre fait rougir le test.
DEFAULT_CAP: Final = 10

#: Cible d'exemplaires par classe (D1) : 8 et non 10, la courbe
#: références/classe plafonne autour de N=8 (COURBE-REFERENCES).
#:
#: Résolue ici en constante et non depuis `dino_thresholds` : la table n'a pas
#: de clé `target_exemplars` (`shared/dino_threshold_defaults.KEYS`), et en
#: ajouter une est une migration, pas un détail de ce lot. Le jour où la cible
#: devient réglable, c'est `target_for_family` qui lit la base — un seul point.
DEFAULT_TARGET: Final = 8

#: Cible pour la famille `emission_commune` (D4, mesuré le 2026-08-21 sur les
#: 87 classes, `vitl14`, banque scopée au pays) : 90 % à N=0, 97 % dès N=5,
#: plat ensuite. Au-delà, l'image ne sépare plus rien — le pays vient d'ailleurs.
TARGET_EMISSION_COMMUNE: Final = 5

#: Les verdicts, dans l'ordre où ils sont évalués (exclusifs).
BOTTLENECKS: Final[tuple[str, ...]] = ("pleine", "review", "scrape")


@dataclass(frozen=True)
class ClassNeed:
    """Le besoin d'une classe de banque, et ce qui le cause."""

    class_id: str            # maille BANQUE (eurio_id du représentant)
    label: str               # désignation lisible
    country: str | None
    family: str              # cf. class_family : nationale | portrait_standard | emission_commune
    have: int                # exemplaires 'fps' en banque
    cap: int                 # DEFAULT_CAP — plafond dur du builder
    target: int              # target_for_family(family)
    pending: int             # crops en file OUVERTE dont le top-1 tombe ici
    pending_scoped: int      # idem, après les filtres par signaux (O4) — cf. note
    best_margin: float | None  # max COALESCE(country_spread, spread) parmi pending
    need: int                # max(0, target − have) — la BANQUE, cf. note
    bottleneck: str          # pleine | review | scrape
    n_train_eligible: int    # voie A, pour affichage seulement — JAMAIS pour le verdict
    accepted_pending: int    # ACQUIS : validés, pas encore en banque (D8)
    # L'EFFET DE CHAQUE FILTRE, jamais tu (O4). Ces trois comptes sont
    # EMBOÎTÉS dans l'ordre où le WHERE les applique :
    #     pending − n_hidden_by_era − n_hidden_by_country − n_hidden_by_denom
    #       = pending_scoped
    # Les lire comme trois effets indépendants ferait dire à l'écran « 12 + 8
    # masqués » au-dessus d'une file qui en a perdu 15.
    n_hidden_by_era: int = 0
    n_hidden_by_country: int = 0
    n_hidden_by_denom: int = 0
    #: Le filtre pays s'est-il RETIRÉ parce qu'il ne laissait rien (O4c) ? Le
    #: geste que l'écran propose doit alors porter `pays=tous`, sinon il ouvre
    #: une file vide sous un compte non nul.
    country_disarmed: bool = False

    # NOTE `need` vs `bottleneck` : ils ne comptent PAS la même chose, et c'est
    # voulu. `need` est ce qui manque À LA BANQUE (`target − have`) : il alimente
    # le budget (Σ 4 066 exemplaires) et ne bouge qu'au rebuild, parce que la
    # banque, elle, ne bouge qu'au rebuild. `bottleneck` compte en plus les
    # ACQUIS, parce qu'il décide s'il faut encore SERVIR cette classe — et
    # servir une classe déjà remplie est du temps humain perdu (D8).
    # Une classe peut donc légitimement afficher `need = 1` ET `pleine` :
    # « il manque encore un exemplaire en banque, mais il est déjà acquis ».
    # Aligner les deux ferait mentir l'un des deux.

    # NOTE `pending_scoped` : c'est ce que LA FILE SERT, filtres d'O4 compris
    # (ère, pays auto-désarmé, dénomination si l'opérateur l'arme) — le même
    # périmètre que `/review/peche?class=<class_id>&need=1`, calculé par
    # `shared.dino_scope`, jamais par une requête réécrite ici. Deux rédactions
    # de la même règle divergent, et l'écart n'est alors réconciliable qu'à la
    # soustraction.
    #
    # ⚠️ Ce champ décide du verdict `review` : une classe dont TOUS les
    # candidats tombent sous les filtres bascule en `scrape` — c'est voulu,
    # l'envoyer en review serait l'envoyer devant une file vide.
    #
    # Une seule exception, explicite : sur une banque autre que celle des
    # SUGGESTIONS (`shared.verdict_scope`), les filtres n'ont pas de sens — ils
    # lisent les prédictions de cette banque-là — et `pending_scoped` retombe
    # sur `pending` plutôt que de rendre un nombre bâti sur la mauvaise
    # population.


def target_for_family(family: str) -> int:
    """La cible d'exemplaires selon la famille de signal (D1, D4)."""
    return TARGET_EMISSION_COMMUNE if family == EMISSION_COMMUNE else DEFAULT_TARGET


def bottleneck_for(
    *, have: int, target: int, pending_scoped: int, accepted_pending: int = 0,
) -> str:
    """Le verdict. L'ordre compte, il est exclusif, et il est le cœur de l'outil.

    1. have + accepted_pending ≥ target → 'pleine'
    2. pending_scoped > 0               → 'review'  (il y a de quoi trancher)
    3. sinon                            → 'scrape'  (aller chercher)

    ⛔ `pending_scoped`, pas `pending` : une classe dont tous les candidats
    disparaissent une fois les filtres appliqués doit dire `scrape`, sinon
    l'écran envoie l'opérateur vers une file vide.

    ⛔ `have + accepted_pending`, pas `have` seul (D8) — et c'est ce qui rend
    l'exigence du PO réalisable. `have` ne bouge qu'au `build_dino_anchors`
    suivant : pendant une session de review il est FIGÉ, donc un verdict
    calculé sur lui seul continue de servir une classe qu'on vient de remplir.
    C'est l'arête que FLOW-ADMIN §3 signale comme n'existant « sous aucune
    forme ». `need_only` seul ne suffit pas à la fermer.

    La cible reste la CIBLE (8, ou 5 en émission commune), jamais le plafond 10
    du builder — celui-ci reste exposé en `ClassNeed.cap` pour l'affichage.
    """
    if have + accepted_pending >= target:
        return "pleine"
    if pending_scoped > 0:
        return "review"
    return "scrape"


# ── Lectures ─────────────────────────────────────────────────────────────────


def _have_by_class(
    conn: sqlite3.Connection, anchors_kind: str, encoder_version: str
) -> dict[str, int]:
    """Grain banque, `method='fps'`. Définit aussi l'ensemble des classes."""
    rows = conn.execute(
        "SELECT class_id, SUM(method = 'fps') "
        "  FROM dino_class_references "
        " WHERE anchors_kind = ? AND encoder_version = ? "
        " GROUP BY class_id",
        (anchors_kind, encoder_version),
    ).fetchall()
    return {r[0]: int(r[1] or 0) for r in rows}


def _pending_by_class(
    conn: sqlite3.Connection, anchors_kind: str, encoder_version: str
) -> dict[str, tuple[int, float | None]]:
    """Crops en file OUVERTE dont le top-1 tombe dans la classe, et la
    meilleure marge parmi eux.

    `status = 'open'` exactement, jamais `IN ('open','in_progress')` : c'est ce
    que `list_queue` sert, et deux populations pour un même fait produisent un
    badge qui annonce 4 au-dessus d'une file qui en sert 3.

    `top1_eurio_id` porte déjà le grain banque (vérifié sur la réplique du
    2026-08-21 : 6 659 crops ouverts, 0 top-1 hors `dino_class_references`) —
    aucune traduction ici.
    """
    rows = conn.execute(
        "SELECT p.top1_eurio_id, COUNT(*), MAX(COALESCE(p.country_spread, p.spread)) "
        "  FROM review_queue rq "
        "  JOIN image_asset_dino_predictions p ON p.asset_id = rq.image_asset_id "
        " WHERE rq.status = 'open' "
        "   AND p.anchors_kind = ? AND p.encoder_version = ? "
        "   AND p.top1_eurio_id IS NOT NULL "
        " GROUP BY p.top1_eurio_id",
        (anchors_kind, encoder_version),
    ).fetchall()
    return {r[0]: (int(r[1]), (float(r[2]) if r[2] is not None else None)) for r in rows}


def _train_key(eurio_id: str, design_group_id: str | None, is_commemorative) -> str:
    """La classe du BAKE (voie A) pour une pièce.

    Même règle que le préflight (`serving/lab_routes.py`, `class_eids`) : une
    courante groupée compte avec toute son ère, une commémorative compte seule
    — même quand elle porte un `design_group_id` (émission commune), parce que
    le bake l'entraîne sous son propre label.
    """
    if is_commemorative:
        return eurio_id
    return design_group_id or eurio_id


def _accepted_pending_by_class(
    conn: sqlite3.Connection, anchors_kind: str, encoder_version: str
) -> dict[str, int]:
    """Les ACQUIS : validés par un humain, pas encore entrés en banque (D8).

    Grain BANQUE, via `top1_eurio_id` — la même clé que `_pending_by_class`.

    CE QUE CE COMPTE RÉPARE
    -----------------------
    Accepter un crop écrit `training_eligible = 1`. Ça n'ajoute AUCUN
    exemplaire : `have` ne bouge qu'au `build_dino_anchors` suivant. Sans ce
    champ, `have` et `bottleneck` sont figés pendant toute une session de
    review, et la file ressert une classe qu'on vient de remplir.

    LES QUATRE CONDITIONS, ET POURQUOI CHACUNE
    ------------------------------------------
    `training_eligible = 1`   : validé par un humain.
    `storage_status='present'`: le fichier existe encore.
    `face != 'reverse'`       : le revers commun n'apprend rien, le builder
                                l'ignore — le compter promettrait un exemplaire
                                qui n'arrivera jamais.
    `asset_id NOT IN (banque)`: PAS ENCORE bâti. C'est tout l'objet du champ ;
                                sans cette clause on recompterait ce que `have`
                                compte déjà, et une classe pleine paraîtrait
                                doublement pleine.

    Mesuré le 2026-08-22 (banque a55e6594) : 1 451 crops acceptés hors banque,
    dont 76 seulement poseraient un exemplaire — le reste tombe dans des
    classes déjà à leur cible. Ce rapport EST la mesure de la sur-review.
    """
    rows = conn.execute(
        "SELECT p.top1_eurio_id, COUNT(*) "
        "  FROM image_assets a "
        "  JOIN image_asset_dino_predictions p ON p.asset_id = a.id "
        " WHERE a.training_eligible = 1 "
        "   AND a.storage_status = 'present' "
        "   AND (a.face IS NULL OR a.face != 'reverse') "
        "   AND p.anchors_kind = ? AND p.encoder_version = ? "
        "   AND p.top1_eurio_id IS NOT NULL "
        "   AND a.id NOT IN (SELECT asset_id FROM dino_class_references "
        "                     WHERE anchors_kind = ? AND asset_id IS NOT NULL) "
        " GROUP BY p.top1_eurio_id",
        (anchors_kind, encoder_version, anchors_kind),
    ).fetchall()
    return {r[0]: int(r[1]) for r in rows}


def _scoped_pending(
    conn: sqlite3.Connection, class_id: str, *, min_denom: float | None,
) -> tuple[int, int, int, int, bool]:
    """Ce que la file SERT pour cette classe, et ce que chaque filtre lui retire.

    Rend `(pending_scoped, n_hidden_by_era, n_hidden_by_country,
    n_hidden_by_denom, country_disarmed)`.

    ⛔ Le périmètre est construit par `shared.dino_scope.build_dino_scope`, avec
    exactement les réglages que la pêche applique par défaut (rang 1, ère active,
    pays actif et auto-désarmé). Récrire ces filtres ici ferait de `/besoin` un
    second calcul du même fait : la page annoncerait N, la file en servirait M,
    et l'écart ne serait réconciliable qu'à la soustraction. C'est précisément la
    dette que ce lot ferme.

    Le compte se fait sur la même population que `_pending_by_class` —
    `review_queue.status = 'open'` — parce que c'est elle que `list_queue` sert.
    """
    from shared.dino_scope import build_dino_scope

    scope = build_dino_scope(
        conn, dino_class=class_id, rank=1, country_only=True,
        min_denom=min_denom,
    )
    if scope.is_empty:
        return 0, 0, 0, 0, False
    n = int(conn.execute(
        f"""
        SELECT COUNT(*) FROM review_queue rq
          JOIN image_assets a ON a.id = rq.image_asset_id
          JOIN source_images si ON si.id = a.source_image_id
          {_suggestions_join()}
         WHERE rq.status = 'open' AND {scope.sql}
        """,
        scope.args,
    ).fetchone()[0] or 0)
    return (
        n, scope.n_hidden_by_era, scope.n_hidden_by_country,
        scope.n_hidden_by_denom, scope.country_disarmed,
    )


def _suggestions_join() -> str:
    from shared.dino_scope import suggestions_join_sql

    return suggestions_join_sql("ps")


def _train_eligible_by_key(conn: sqlite3.Connection) -> dict[str, int]:
    """Voie A, avec les QUATRE conditions du bake, à la maille `coins`.

    Reproduire ces quatre conditions n'est pas du zèle : un compteur qui dirait
    8 là où l'écran de cohorte dit 6 ferait douter des deux.
    """
    rows = conn.execute(
        "SELECT c.eurio_id, c.design_group_id, c.is_commemorative, COUNT(*) "
        "  FROM image_assets a "
        "  JOIN source_images si ON si.id = a.source_image_id "
        "  JOIN coins c ON c.eurio_id = a.eurio_id "
        " WHERE si.source = 'ebay' "
        "   AND a.training_eligible = 1 "
        "   AND a.storage_status = 'present' "
        "   AND (a.face IS NULL OR a.face != 'reverse') "
        " GROUP BY c.eurio_id",
    ).fetchall()
    out: dict[str, int] = {}
    for eurio_id, dgid, is_commemo, n in rows:
        key = _train_key(eurio_id, dgid, is_commemo)
        out[key] = out.get(key, 0) + int(n)
    return out


def _coins_for(conn: sqlite3.Connection, class_ids: list[str]) -> dict[str, tuple]:
    """Les colonnes de `coins` (+ désignation de l'ère) dont le besoin dépend."""
    out: dict[str, tuple] = {}
    # Par paquets : la liste peut dépasser la limite de variables de SQLite.
    for i in range(0, len(class_ids), 500):
        chunk = class_ids[i : i + 500]
        ph = ",".join("?" * len(chunk))
        rows = conn.execute(
            "SELECT c.eurio_id, c.design_group_id, c.is_commemorative, c.face_value, "
            "       c.country, c.country_name, c.year, c.theme, dg.designation "
            "  FROM coins c LEFT JOIN design_groups dg ON dg.id = c.design_group_id "
            f" WHERE c.eurio_id IN ({ph})",
            tuple(chunk),
        ).fetchall()
        for r in rows:
            out[r[0]] = tuple(r)
    return out


def _label(row: tuple) -> str:
    eurio_id, _dgid, is_commemo, _fv, country, country_name, year, theme, designation = row
    if not is_commemo and designation:
        return str(designation)
    if theme:
        return f"{country_name or country} {year} — {str(theme).rstrip(';').strip()}"
    return str(designation or eurio_id)


def _build(
    conn: sqlite3.Connection,
    *,
    anchors_kind: str,
    encoder_version: str,
    only: set[str] | None,
    min_denom: float | None = None,
) -> list[ClassNeed]:
    have = _have_by_class(conn, anchors_kind, encoder_version)
    class_ids = sorted(have if only is None else (set(have) & only))
    if not class_ids:
        return []
    pending = _pending_by_class(conn, anchors_kind, encoder_version)
    accepted = _accepted_pending_by_class(conn, anchors_kind, encoder_version)
    train = _train_eligible_by_key(conn)
    coins = _coins_for(conn, class_ids)
    ec_groups = emission_commune_group_ids(conn)
    is_suggestions_bank = (
        anchors_kind == SUGGESTIONS_ANCHORS_KIND
        and encoder_version == SUGGESTIONS_ENCODER_VERSION
    )

    missing = [c for c in class_ids if c not in coins]
    if missing:
        raise LookupError(
            f"{len(missing)} classe(s) de la banque {anchors_kind!r} absente(s) "
            f"de `coins` : {', '.join(missing[:5])}"
        )

    out: list[ClassNeed] = []
    for class_id in class_ids:
        row = coins[class_id]
        _eid, dgid, is_commemo, face_value, country, *_ = row
        family = family_from_coin(dgid, is_commemo, face_value, ec_groups)
        h = have[class_id]
        n_pending, best_margin = pending.get(class_id, (0, None))
        # Les filtres d'O4 lisent les prédictions de la banque des SUGGESTIONS.
        # Sur une autre banque ils porteraient sur une population qui n'est pas
        # celle qu'on compte : on retombe alors sur `pending`, sans rien
        # prétendre filtrer (cf. la note sur le champ).
        if n_pending and is_suggestions_bank:
            (pending_scoped, n_era, n_country, n_denom,
             disarmed) = _scoped_pending(conn, class_id, min_denom=min_denom)
        else:
            pending_scoped, n_era, n_country, n_denom, disarmed = (
                n_pending, 0, 0, 0, False,
            )
        target = target_for_family(family)
        n_accepted = accepted.get(class_id, 0)
        out.append(ClassNeed(
            class_id=class_id,
            label=_label(row),
            country=country,
            family=family,
            have=h,
            cap=DEFAULT_CAP,
            target=target,
            pending=n_pending,
            pending_scoped=pending_scoped,
            best_margin=best_margin,
            need=max(0, target - h),
            bottleneck=bottleneck_for(
                have=h, target=target, pending_scoped=pending_scoped,
                accepted_pending=n_accepted,
            ),
            n_train_eligible=train.get(_train_key(class_id, dgid, is_commemo), 0),
            accepted_pending=n_accepted,
            n_hidden_by_era=n_era,
            n_hidden_by_country=n_country,
            n_hidden_by_denom=n_denom,
            country_disarmed=disarmed,
        ))
    return out


def all_needs(
    conn: sqlite3.Connection, *, anchors_kind: str, encoder_version: str,
    min_denom: float | None = None,
) -> list[ClassNeed]:
    """Le besoin de TOUTES les classes de la banque `(anchors_kind, encoder_version)`.

    Une classe par `class_id` de `dino_class_references`, les pleines comprises.
    Triées par `class_id` — l'écran réordonne.
    """
    return _build(
        conn, anchors_kind=anchors_kind, encoder_version=encoder_version,
        only=None, min_denom=min_denom,
    )


def need_for(
    conn: sqlite3.Connection,
    eurio_id: str,
    *,
    anchors_kind: str,
    encoder_version: str,
) -> ClassNeed | None:
    """Le besoin de la classe de banque qui indexe CETTE pièce.

    Un membre non-représentant (`it-2008-2eur-standard-2nd-map`) et son
    représentant (`it-2002-…`) rendent le MÊME `ClassNeed` : la traduction
    passe par `shared.bank_classes.bank_class_ids`, jamais par un COALESCE
    local. `None` si la pièce n'est indexée sous aucune classe de cette banque.
    """
    candidates = set(bank_class_ids(conn, eurio_id))
    needs = _build(
        conn, anchors_kind=anchors_kind, encoder_version=encoder_version, only=candidates,
    )
    if not needs:
        return None
    if len(needs) > 1:
        # `bank_class_ids` renvoie [membre, représentant] ; seul le représentant
        # porte la classe. Deux classes distinctes pour une même pièce serait
        # une banque incohérente — on le dit plutôt que d'en choisir une.
        raise RuntimeError(
            f"{eurio_id!r} est indexée sous {len(needs)} classes de la banque "
            f"{anchors_kind!r} : {[n.class_id for n in needs]}"
        )
    return needs[0]
