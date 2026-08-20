"""Les seuils DINO, résolus en base — stdlib-only.

Frère de ``store/thresholds.py`` (les seuils d'entraînement), avec deux
différences qui justifient une table distincte plutôt qu'une extension :

* les valeurs sont des **flottants**, pas des entiers (l'exception,
  ``min_exemplars``, est un compte stocké en REAL et relu en ``int`` — la
  migration 0011 lui donne sa propre borne SQL plutôt que d'élargir celle des
  similarités) ;
* la portée n'est pas la cohorte mais le couple **(banque, encodeur)**. Un
  seuil de 0,55 calibré sur les similarités de `dinov2-vits14` ne veut rien
  dire pour `dinov2-vitl14` : les deux échelles ne sont pas comparables.
  Servir la mauvaise valeur ne lève aucune erreur — elle déplace le taux de
  faux positifs, en silence.

Contrat d'import : **stdlib uniquement** + ``shared.dino_threshold_defaults``.
L'image lean du VPS sert la file de review et lit ces seuils ; importer
``training.foundation`` y tirerait numpy et torch.

Le filet : couple absent de la table, table absente (canonique pas encore
redéployé, réplique en retard) → les défauts du code. C'est exact, simplement
non surchargé. Comme pour les seuils d'entraînement, on ne tait QUE
« no such table » : un ``database is locked`` avalé ferait passer un défaut
pour une valeur réglée.

Cf. docs/work-in-progress/banque-dino/DECISIONS.md §D5.
"""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass

from shared.dino_threshold_defaults import BOUNDS, CLES_ENTIERES, KEYS, defaults_for


class DinoThresholdError(ValueError):
    """Refus métier, porteur d'un code HTTP que la façade traduit."""

    def __init__(self, status_code: int, detail: str) -> None:
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


@dataclass(frozen=True)
class DinoThresholds:
    """Les valeurs qui s'appliquent à un couple, et d'où chacune vient.

    ``source[key]`` ∈ ``'db' | 'code'`` — l'écran doit pouvoir dire « 0,10
    (réglé le 19 août) » plutôt qu'un nombre orphelin."""

    anchors_kind: str
    encoder_version: str
    values: dict[str, float]
    source: dict[str, str]

    def __getitem__(self, key: str) -> float:
        return self.values[key]

    def to_dict(self) -> dict:
        return {
            "anchors_kind": self.anchors_kind,
            "encoder_version": self.encoder_version,
            "values": dict(self.values),
            "source": dict(self.source),
        }


def _table_missing(exc: sqlite3.OperationalError) -> bool:
    """Le SEUL cas où le silence est correct — cf. store/thresholds."""
    return "no such table" in str(exc).lower()


def _rows(
    conn: sqlite3.Connection, anchors_kind: str, encoder_version: str
) -> dict[str, float]:
    try:
        cur = conn.execute(
            "SELECT key, value FROM dino_thresholds "
            " WHERE anchors_kind = ? AND encoder_version = ?",
            (anchors_kind, encoder_version),
        )
    except sqlite3.OperationalError as exc:
        if not _table_missing(exc):
            raise
        return {}
    return {r[0]: float(r[1]) for r in cur.fetchall() if r[0] in KEYS}


def resolve(
    conn: sqlite3.Connection, *, anchors_kind: str, encoder_version: str
) -> DinoThresholds:
    """Les seuils du couple : la base d'abord, les défauts du code ensuite."""
    values = defaults_for(anchors_kind, encoder_version)
    source = {k: "code" for k in values}
    for key, value in _rows(conn, anchors_kind, encoder_version).items():
        values[key] = value
        source[key] = "db"
    return DinoThresholds(anchors_kind, encoder_version, values, source)


def read_state(
    conn: sqlite3.Connection, *, anchors_kind: str, encoder_version: str
) -> dict:
    """Tout ce qu'un écran de réglage doit savoir."""
    resolved = resolve(conn, anchors_kind=anchors_kind, encoder_version=encoder_version)
    return {
        "effective": resolved.to_dict(),
        "defaults": defaults_for(anchors_kind, encoder_version),
        "bounds": {k: list(v) for k, v in BOUNDS.items()},
        "overrides": _rows(conn, anchors_kind, encoder_version),
        "history": read_history(
            conn, anchors_kind=anchors_kind, encoder_version=encoder_version
        ),
    }


def read_history(
    conn: sqlite3.Connection,
    *,
    anchors_kind: str,
    encoder_version: str,
    limit: int = 20,
) -> list[dict]:
    """Changements récents, le plus récent d'abord.

    Pas décoratif : bouger un seuil reclasse des milliers d'items entre
    `auto_accept` et `manual`, ce qui se lit comme une régression sans la
    ligne qui l'explique."""
    try:
        cur = conn.execute(
            "SELECT key, old_value, new_value, note, changed_by, changed_at "
            "  FROM dino_threshold_changes "
            " WHERE anchors_kind = ? AND encoder_version = ? "
            " ORDER BY changed_at DESC, id DESC LIMIT ?",
            (anchors_kind, encoder_version, int(limit)),
        )
    except sqlite3.OperationalError as exc:
        if not _table_missing(exc):
            raise
        return []
    return [
        {
            "key": r[0], "old_value": r[1], "new_value": r[2],
            "note": r[3], "changed_by": r[4], "changed_at": r[5],
        }
        for r in cur.fetchall()
    ]


def _require_table(conn: sqlite3.Connection) -> None:
    """La LECTURE se dégrade en silence ; pas l'ÉCRITURE."""
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='dino_thresholds'",
    ).fetchone()
    if row is None:
        raise DinoThresholdError(
            503,
            "La table des seuils DINO n'existe pas sur cette base : la migration "
            "0008 n'a pas encore été appliquée au canonique. Les valeurs "
            "affichées sont les défauts du code — justes, mais pas réglables.",
        )


def set_threshold(
    conn: sqlite3.Connection,
    key: str,
    value: float,
    *,
    anchors_kind: str,
    encoder_version: str,
    calibrated_on: str | None = None,
    precision_at: float | None = None,
    n_samples: int | None = None,
    note: str | None = None,
    changed_by: str | None = None,
) -> dict:
    """Pose une valeur pour un couple, et journalise le changement.

    N'écrit rien si la valeur est déjà celle en place — sinon l'historique se
    remplit de non-événements. L'appelant commit."""
    if key not in KEYS:
        raise DinoThresholdError(400, f"Seuil inconnu : {key!r} (attendu : {', '.join(KEYS)})")
    value = float(value)
    lo, hi = BOUNDS[key]
    if not lo <= value <= hi:
        raise DinoThresholdError(400, f"{key} = {value} hors bornes [{lo}, {hi}]")
    if key in CLES_ENTIERES and value != int(value):
        # S1 : ce seuil est un COMPTE, relu en `int()` par le builder. 1,9
        # franchissait les bornes et rendait un plancher effectif de 1 — le
        # régime que le plancher interdit — avec `source='db'` pour caution.
        raise DinoThresholdError(
            400,
            f"{key} = {value} : ce seuil est un COMPTE d'exemplaires, il doit "
            "être entier. Le builder le relit en int() : 1.9 poserait un "
            "plancher effectif de 1, soit le régime N=1 (50,1 % held-out) que "
            "ce plancher existe pour interdire. Pose 2 (ou 0 pour désarmer).",
        )

    before = _rows(conn, anchors_kind, encoder_version).get(key)
    if before is not None and abs(before - value) < 1e-12:
        return {"key": key, "value": value, "changed": False, "previous": before}

    _require_table(conn)
    try:
        _insert(conn, anchors_kind, encoder_version, key, value, calibrated_on,
                precision_at, n_samples, note, changed_by)
    except sqlite3.IntegrityError as exc:
        # La table d'avant la migration 0011 refuse `min_exemplars` (CHECK sur
        # `key`) et refuse une valeur > 1 (CHECK sur `value`, écrit pour des
        # similarités). Sans ce garde, le message brut de SQLite — « CHECK
        # constraint failed » — n'oriente vers rien.
        raise DinoThresholdError(
            503,
            f"La base refuse {key} = {value} : « {exc} ». Si la clé est "
            "'min_exemplars', c'est la forme d'avant la migration 0011 "
            "(serving/migrations/0011_dino_thresholds_min_exemplars.sql) — au "
            "canonique, c'est le redémarrage de eurio-api qui l'applique ; une "
            "base locale déjà créée doit être migrée à la main "
            "(CREATE TABLE IF NOT EXISTS ne reconstruit rien).",
        ) from exc
    _log(conn, anchors_kind, encoder_version, key, before, value, note, changed_by)
    return {"key": key, "value": value, "changed": True, "previous": before}


def _insert(
    conn: sqlite3.Connection,
    anchors_kind: str,
    encoder_version: str,
    key: str,
    value: float,
    calibrated_on: str | None,
    precision_at: float | None,
    n_samples: int | None,
    note: str | None,
    changed_by: str | None,
) -> None:
    conn.execute(
        "INSERT INTO dino_thresholds (anchors_kind, encoder_version, key, value, "
        " calibrated_on, precision_at, n_samples, note, updated_at, updated_by) "
        "VALUES (?,?,?,?,?,?,?,?,datetime('now'),?) "
        "ON CONFLICT(anchors_kind, encoder_version, key) DO UPDATE SET "
        " value = excluded.value, calibrated_on = excluded.calibrated_on, "
        " precision_at = excluded.precision_at, n_samples = excluded.n_samples, "
        " note = excluded.note, updated_at = excluded.updated_at, "
        " updated_by = excluded.updated_by",
        (anchors_kind, encoder_version, key, value, calibrated_on, precision_at,
         n_samples, note, changed_by),
    )


def clear_threshold(
    conn: sqlite3.Connection,
    key: str,
    *,
    anchors_kind: str,
    encoder_version: str,
    note: str | None = None,
    changed_by: str | None = None,
) -> dict:
    """Retire une surcharge — la valeur retombe sur le défaut du code."""
    if key not in KEYS:
        raise DinoThresholdError(400, f"Seuil inconnu : {key!r}")
    before = _rows(conn, anchors_kind, encoder_version).get(key)
    if before is None:
        return {"key": key, "value": None, "changed": False, "previous": None}
    _require_table(conn)
    conn.execute(
        "DELETE FROM dino_thresholds "
        " WHERE anchors_kind = ? AND encoder_version = ? AND key = ?",
        (anchors_kind, encoder_version, key),
    )
    _log(conn, anchors_kind, encoder_version, key, before, None, note, changed_by)
    return {"key": key, "value": None, "changed": True, "previous": before}


def _log(
    conn: sqlite3.Connection,
    anchors_kind: str,
    encoder_version: str,
    key: str,
    old: float | None,
    new: float | None,
    note: str | None,
    changed_by: str | None,
) -> None:
    conn.execute(
        "INSERT INTO dino_threshold_changes (anchors_kind, encoder_version, key, "
        " old_value, new_value, note, changed_by, changed_at) "
        "VALUES (?,?,?,?,?,?,?,datetime('now'))",
        (anchors_kind, encoder_version, key, old, new, note, changed_by),
    )
