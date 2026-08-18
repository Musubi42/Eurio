"""Les trois seuils d'entraînement, résolus en base — stdlib-only.

Pourquoi ce module existe
-------------------------
``m_per_class``, ``min_real`` et ``training_target`` étaient trois constantes
Python. Changer le plancher de 10 à 25 demandait d'éditer ``funnel_constants``,
redéployer l'API locale ET le canonique. C'était un frein direct à la seule
expérience qui compte : *est-ce que 10 photos réelles suffisent ?* Un seuil
qu'on ne peut pas bouger ne peut pas être éprouvé.

Contrat d'import (comme ``store/funnel.py``, servi sur l'image lean du VPS) :
**stdlib uniquement** + ``store.funnel_constants``. Aucun import ``serving.*`` /
``training.*``, sinon on retire numpy/torch sur l'image lean.

L'ordre de résolution
---------------------
::

    scope='class'   (class_id)    ← prévu, jamais alimenté aujourd'hui (D2)
        ↓ sinon
    scope='cohort'  (cohort_id)
        ↓ sinon
    scope='global'
        ↓ sinon
    constante Python              ← le filet, PAS de la dette

Le dernier étage est une précondition de démarrage : le préflight et l'image
lean doivent fonctionner sur une base qui n'a pas encore reçu la migration 0006
(et sur la réplique d'un canonique plus vieux). Toute ``OperationalError``
« no such table » retombe donc silencieusement sur les défauts — c'est le seul
cas où le silence est correct, parce que la valeur servie est *exacte*, juste
non surchargée.

Le décalage qu'il faut annoncer
-------------------------------
La table vit au canonique. Sur Mac/PC, le préflight lit une **réplique**
rafraîchie toutes les 120 s : un seuil qu'on vient de changer met jusqu'à deux
minutes à changer le verdict. ``resolve()`` retourne pour cette raison la
**provenance** de chaque valeur — le front doit l'afficher, sinon l'attente se
lit comme un blocage (cf. VISION.md « aucun écran ne ment en silence »).

Cf. docs/work-in-progress/refacto-page-cohorte/DECISIONS.md §D5.
"""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass

from store.funnel_constants import M_PER_CLASS, MIN_REAL, TRAINING_TARGET

#: Les seules clés acceptées. Toute autre est refusée à l'écriture — une clé
#: libre deviendrait un fourre-tout de configuration sans propriétaire.
KEYS: tuple[str, ...] = ("m_per_class", "min_real", "training_target")

#: Le filet : ce qui s'applique quand la base ne dit rien.
DEFAULTS: dict[str, int] = {
    "m_per_class": M_PER_CLASS,
    "min_real": MIN_REAL,
    "training_target": TRAINING_TARGET,
}

#: Bornes de bon sens, vérifiées à l'écriture. Elles n'encodent pas une
#: doctrine, seulement l'absurde : un plancher à 0 rendrait le préflight muet,
#: une cible à 100 000 ferait exploser le bake.
BOUNDS: dict[str, tuple[int, int]] = {
    "m_per_class": (2, 64),
    "min_real": (1, 5000),
    "training_target": (10, 5000),
}

SCOPES: tuple[str, ...] = ("global", "cohort", "class")


class ThresholdError(ValueError):
    """Refus métier (clé inconnue, valeur hors bornes, scope incohérent).

    Même contrat que ``store.decisions.DecisionError`` : porte un code HTTP que
    la façade traduit, pour que la logique reste hors des routeurs."""

    def __init__(self, status_code: int, detail: str) -> None:
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


@dataclass(frozen=True)
class Thresholds:
    """Les trois valeurs qui s'appliquent, et d'où chacune vient.

    ``source`` ∈ ``'class' | 'cohort' | 'global' | 'code'``. C'est ce qui permet
    à l'écran de dire « plancher 25 (réglage de cette cohorte) » plutôt qu'un
    nombre sans père."""

    m_per_class: int
    min_real: int
    training_target: int
    source: dict[str, str]

    def to_dict(self) -> dict:
        return {
            "m_per_class": self.m_per_class,
            "min_real": self.min_real,
            "training_target": self.training_target,
            "source": dict(self.source),
        }

    def frozen_config(self) -> dict[str, int]:
        """Ce qu'on écrit dans ``experiment_iterations.training_config_json``.

        Sans ce gel, on ne peut plus dire AVEC QUEL plancher un modèle a été
        entraîné, et comparer deux runs n'a plus de sens (cf. D1/D5)."""
        return {
            "m_per_class": self.m_per_class,
            "min_real": self.min_real,
            "training_target": self.training_target,
        }


def _table_missing(exc: sqlite3.OperationalError) -> bool:
    """La table n'existe pas encore — le SEUL cas où le silence est correct.

    ``sqlite3.OperationalError`` couvre aussi ``database is locked``, ``disk I/O
    error`` et ``database disk image is malformed``. Les avaler rendrait le
    défaut du code pour une valeur réglée : le préflight jugerait 40 classes à
    10 pendant que la base dit 25, et l'écran l'annoncerait comme un fait. On
    ne tait donc QUE la table manquante ; tout le reste remonte."""
    return "no such table" in str(exc).lower()


def _rows(conn: sqlite3.Connection, scope: str, scope_id: str) -> dict[str, int]:
    """Les surcharges d'un scope, ou rien si la table n'existe pas encore."""
    try:
        cur = conn.execute(
            "SELECT key, value FROM training_thresholds "
            "WHERE scope = ? AND scope_id = ?",
            (scope, scope_id),
        )
    except sqlite3.OperationalError as exc:
        # Base antérieure à la migration 0006 (ou réplique d'un canonique plus
        # vieux). On sert les défauts — exacts, simplement non surchargés.
        if not _table_missing(exc):
            raise
        return {}
    return {r[0]: int(r[1]) for r in cur.fetchall() if r[0] in KEYS}


def resolve(
    conn: sqlite3.Connection,
    *,
    cohort_id: str | None = None,
    class_id: str | None = None,
) -> Thresholds:
    """Les seuils qui s'appliquent ici et maintenant, avec leur provenance.

    ``class_id`` est accepté dès aujourd'hui alors qu'aucune ligne
    ``scope='class'`` n'est jamais écrite : c'est le point d'accroche de D2 (un
    seuil par classe, le jour où le benchmark dira laquelle est difficile).
    L'activer coûtera des lignes en base, pas une refonte des appelants.
    """
    layers: list[tuple[str, dict[str, int]]] = [("global", _rows(conn, "global", ""))]
    if cohort_id:
        layers.append(("cohort", _rows(conn, "cohort", cohort_id)))
    if class_id:
        layers.append(("class", _rows(conn, "class", class_id)))

    values = dict(DEFAULTS)
    source = {k: "code" for k in KEYS}
    for scope, overrides in layers:  # du plus général au plus précis
        for key, value in overrides.items():
            values[key] = value
            source[key] = scope

    return Thresholds(
        m_per_class=values["m_per_class"],
        min_real=values["min_real"],
        training_target=values["training_target"],
        source=source,
    )


def read_state(conn: sqlite3.Connection, *, cohort_id: str | None = None) -> dict:
    """Tout ce qu'un écran de réglage doit savoir : l'effectif, les défauts, les
    surcharges posées, et l'historique récent.

    L'historique n'est pas décoratif : quand le plancher monte, des classes
    déjà prêtes redeviennent incomplètes (D1). Sans la ligne « plancher 10 → 50
    le 3 septembre », ça se lit comme une régression."""
    return {
        "effective": resolve(conn, cohort_id=cohort_id).to_dict(),
        "defaults": dict(DEFAULTS),
        "bounds": {k: list(v) for k, v in BOUNDS.items()},
        "global": _rows(conn, "global", ""),
        "cohort": _rows(conn, "cohort", cohort_id) if cohort_id else {},
        "cohort_id": cohort_id,
        "history": read_history(conn, cohort_id=cohort_id),
    }


def read_history(
    conn: sqlite3.Connection, *, cohort_id: str | None = None, limit: int = 20
) -> list[dict]:
    """Changements récents, le plus récent d'abord. Global + (si demandé) la
    cohorte : ce sont les deux qui peuvent déplacer la ligne d'arrivée."""
    sql = (
        "SELECT scope, scope_id, key, old_value, new_value, changed_at, note "
        "FROM training_threshold_changes WHERE scope = 'global'"
    )
    params: list[str] = []
    if cohort_id:
        sql += " OR (scope = 'cohort' AND scope_id = ?)"
        params.append(cohort_id)
    sql += " ORDER BY changed_at DESC, rowid DESC LIMIT ?"
    params.append(str(int(limit)))
    try:
        cur = conn.execute(sql, params)
    except sqlite3.OperationalError as exc:
        if not _table_missing(exc):
            raise
        return []
    return [
        {
            "scope": r[0],
            "scope_id": r[1] or None,
            "key": r[2],
            "old_value": r[3],
            "new_value": r[4],
            "changed_at": r[5],
            "note": r[6],
        }
        for r in cur.fetchall()
    ]


def _require_table(conn: sqlite3.Connection) -> None:
    """La LECTURE se dégrade en silence sur une base sans la migration ; pas
    l'ÉCRITURE. Sans ce garde-fou, l'INSERT partirait quand même et l'appelant
    recevrait un 500 nu sur exactement le cas que ce module promet de dégrader
    proprement."""
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'training_thresholds'",
    ).fetchone()
    if row is None:
        raise ThresholdError(
            503,
            "La table des seuils n'existe pas sur cette base : la migration 0006 "
            "n'a pas encore été appliquée au canonique. Les valeurs affichées sont "
            "les défauts du code — elles sont justes, simplement pas réglables.",
        )


def _check(key: str, scope: str, scope_id: str) -> None:
    if key not in KEYS:
        raise ThresholdError(400, f"Seuil inconnu : {key!r} (attendu : {', '.join(KEYS)})")
    if scope not in SCOPES:
        raise ThresholdError(400, f"Scope inconnu : {scope!r}")
    if scope == "global" and scope_id:
        raise ThresholdError(400, "Le scope 'global' ne porte pas d'identifiant")
    if scope != "global" and not scope_id:
        raise ThresholdError(400, f"Le scope {scope!r} exige un identifiant")


def set_threshold(
    conn: sqlite3.Connection,
    key: str,
    value: int,
    *,
    scope: str = "global",
    scope_id: str = "",
    note: str | None = None,
    changed_by: str | None = None,
) -> dict:
    """Pose (ou remplace) une surcharge, et journalise le changement.

    N'écrit RIEN si la valeur est déjà celle en place — sinon l'historique se
    remplirait de non-événements et on ne verrait plus les vrais changements.
    L'appelant commit (contrat de ``store.decisions``)."""
    _check(key, scope, scope_id)
    value = int(value)
    lo, hi = BOUNDS[key]
    if not lo <= value <= hi:
        raise ThresholdError(400, f"{key} = {value} hors bornes [{lo}, {hi}]")

    before = _rows(conn, scope, scope_id).get(key)
    if before == value:
        return {"key": key, "value": value, "changed": False, "previous": before}

    _require_table(conn)
    conn.execute(
        "INSERT INTO training_thresholds (scope, scope_id, key, value, note, "
        "updated_at, updated_by) VALUES (?, ?, ?, ?, ?, datetime('now'), ?) "
        "ON CONFLICT(scope, scope_id, key) DO UPDATE SET "
        "value = excluded.value, note = excluded.note, "
        "updated_at = excluded.updated_at, updated_by = excluded.updated_by",
        (scope, scope_id, key, value, note, changed_by),
    )
    _log_change(conn, scope, scope_id, key, before, value, note, changed_by)
    return {"key": key, "value": value, "changed": True, "previous": before}


def clear_threshold(
    conn: sqlite3.Connection,
    key: str,
    *,
    scope: str,
    scope_id: str,
    note: str | None = None,
    changed_by: str | None = None,
) -> dict:
    """Retire une surcharge — la valeur retombe à l'étage du dessus.

    Retirer n'est pas « remettre 10 » : c'est rendre la cohorte à la règle
    générale, y compris quand celle-ci changera plus tard."""
    _check(key, scope, scope_id)
    if scope == "global":
        raise ThresholdError(400, "Le défaut global se change, il ne se retire pas")
    before = _rows(conn, scope, scope_id).get(key)
    if before is None:
        return {"key": key, "value": None, "changed": False, "previous": None}
    _require_table(conn)
    conn.execute(
        "DELETE FROM training_thresholds WHERE scope = ? AND scope_id = ? AND key = ?",
        (scope, scope_id, key),
    )
    _log_change(conn, scope, scope_id, key, before, None, note, changed_by)
    return {"key": key, "value": None, "changed": True, "previous": before}


def _log_change(
    conn: sqlite3.Connection,
    scope: str,
    scope_id: str,
    key: str,
    old: int | None,
    new: int | None,
    note: str | None,
    changed_by: str | None,
) -> None:
    conn.execute(
        "INSERT INTO training_threshold_changes "
        "(scope, scope_id, key, old_value, new_value, note, changed_by, changed_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, datetime('now'))",
        (scope, scope_id, key, old, new, note, changed_by),
    )
