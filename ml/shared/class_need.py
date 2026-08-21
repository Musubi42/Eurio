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
    need: int                # max(0, target − have)
    bottleneck: str          # pleine | review | scrape
    n_train_eligible: int    # voie A, pour affichage seulement — JAMAIS pour le verdict

    # NOTE `pending_scoped` : les filtres par signaux d'O4 ne sont pas
    # implémentés dans ce lot ; `pending_scoped == pending` jusque-là. Le champ
    # existe dès maintenant pour que le verdict lise la bonne grandeur le jour
    # où les filtres arrivent — sans que l'écran change.


def target_for_family(family: str) -> int:
    """La cible d'exemplaires selon la famille de signal (D1, D4)."""
    return TARGET_EMISSION_COMMUNE if family == EMISSION_COMMUNE else DEFAULT_TARGET


def bottleneck_for(*, have: int, target: int, pending_scoped: int) -> str:
    """Le verdict. L'ordre compte, il est exclusif, et il est le cœur de l'outil.

    1. have ≥ target        → 'pleine'  (on arrête de servir, D2 : « une classe
                                          à ≥ 8 en banque ne reçoit plus de
                                          travail » — la CIBLE, pas le plafond
                                          10 du builder, qui reste `cap` pour
                                          l'affichage)
    2. pending_scoped > 0   → 'review'  (il y a de quoi trancher)
    3. sinon                → 'scrape'  (rien à trancher : aller chercher)

    ⛔ `pending_scoped`, pas `pending` : une classe dont tous les candidats
    disparaissent une fois les filtres appliqués doit dire `scrape`, sinon
    l'écran envoie l'opérateur vers une file vide.
    """
    if have >= target:
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
) -> list[ClassNeed]:
    have = _have_by_class(conn, anchors_kind, encoder_version)
    class_ids = sorted(have if only is None else (set(have) & only))
    if not class_ids:
        return []
    pending = _pending_by_class(conn, anchors_kind, encoder_version)
    train = _train_eligible_by_key(conn)
    coins = _coins_for(conn, class_ids)
    ec_groups = emission_commune_group_ids(conn)

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
        pending_scoped = n_pending  # O4 non implémenté : cf. note sur le champ
        target = target_for_family(family)
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
            bottleneck=bottleneck_for(have=h, target=target, pending_scoped=pending_scoped),
            n_train_eligible=train.get(_train_key(class_id, dgid, is_commemo), 0),
        ))
    return out


def all_needs(
    conn: sqlite3.Connection, *, anchors_kind: str, encoder_version: str
) -> list[ClassNeed]:
    """Le besoin de TOUTES les classes de la banque `(anchors_kind, encoder_version)`.

    Une classe par `class_id` de `dino_class_references`, les pleines comprises.
    Triées par `class_id` — l'écran réordonne.
    """
    return _build(conn, anchors_kind=anchors_kind, encoder_version=encoder_version, only=None)


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
