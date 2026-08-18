"""Lecture autoritative du funnel « Jeu d'entraînement » — SQL-pure, servie à
l'identique par l'API ML locale lourde (``serving/lab_routes.py``) ET l'image
lean canonique du VPS (``serving/lab_read_routes.py``).

Miroir LECTURE de ``store/decisions.py`` (C2a, les ÉCRITURES funnel). Porte
UNIQUEMENT la moitié ÉTAT-DB-PORTABLE de l'ancien ``_cohort_training_crops``
(``serving/lab_routes.py``) : quels crops, à quel statut, éligibles ou non.
Le DÉRIVÉ (GPU ET filesystem — R@1/confused_with/intrus, has_numista_ref/
n_bce_ref) reste dans ``serving/lab_routes._cohort_training_overlay`` (full
server only, cf. migration-direction-a.md C3) et se merge côté front.

Contrat d'import (comme ``store/decisions.py``) : n'importe QUE
``sqlite3``/stdlib + ``store.funnel_constants`` (stdlib-only) +
``store.class_resolver`` (stdlib-only, ne lit que ``eurio.db``). **Aucun**
import ``serving.*``/``review.*``/``training.*`` — sinon on retraîne
numpy/torch/cv2 sur l'image lean.

Erreurs métier levées en ``store.decisions.DecisionError`` (même contrat que
les écritures) ; les routeurs la traduisent en ``HTTPException``.
"""
from __future__ import annotations

import json
import sqlite3

from store.class_resolver import ClassDescriptor, CoinRef, Resolver
from store.decisions import DecisionError
from store.funnel_constants import TRIAGE_STATUSES
from store.thresholds import resolve as resolve_thresholds

_TRIAGE_MAX_PER_CLASS = 400


def _get_cohort_row(conn: sqlite3.Connection, id_or_name: str) -> sqlite3.Row | None:
    """Miroir de ``store.cohorts.Store.get_cohort`` — id d'abord, puis name —
    mais conn-based (pas de dépendance à la classe Store)."""
    row = conn.execute(
        "SELECT id, name, eurio_ids_json FROM experiment_cohorts WHERE id = ?",
        (id_or_name,),
    ).fetchone()
    if row is None:
        row = conn.execute(
            "SELECT id, name, eurio_ids_json FROM experiment_cohorts WHERE name = ?",
            (id_or_name,),
        ).fetchone()
    return row


def _resolver_from_conn(conn: sqlite3.Connection) -> Resolver:
    """Bâtit le Resolver classe↔pièces depuis la connexion de la requête (pas de
    2e connexion sqlite comme ``class_resolver.build_resolver`` — l'appelant a
    déjà ``conn`` ouverte, lean ou local)."""
    coins = [
        CoinRef(
            eurio_id=r["eurio_id"],
            numista_id=int(r["numista_id"]) if r["numista_id"] is not None else None,
            design_group_id=r["design_group_id"],
        )
        for r in conn.execute(
            "SELECT eurio_id, numista_id, design_group_id FROM coins "
            "WHERE numista_id IS NOT NULL"
        ).fetchall()
    ]
    return Resolver(coins)


def _class_state(conn: sqlite3.Connection, d: ClassDescriptor, min_real: int) -> dict:
    """État-DB-portable d'une classe : crops (statut/éligibilité/routage) +
    compteurs purement dérivés de ces colonnes. AUCUN champ GPU/FS (overlay).

    ``min_real`` est le plancher RÉSOLU pour la cohorte (store/thresholds), pas
    la constante : ``underfed`` doit répondre à la règle en vigueur, sinon deux
    écrans donnent deux verdicts sur la même classe."""
    members = list(d.eurio_ids)
    if not members:
        return {
            "class_id": d.class_id, "class_kind": d.class_kind,
            "member_eurio_ids": members,
            "n_eligible": 0, "n_unknown_face": 0, "n_reverse_flagged": 0,
            "n_rejected": 0, "n_review_unrouted": 0, "n_obverse": 0,
            "underfed": True, "crops": [],
        }

    member_ph = ",".join("?" for _ in members)
    status_ph = ",".join("?" for _ in TRIAGE_STATUSES)
    rows = conn.execute(
        f"""
        SELECT a.id, a.eurio_id, a.face, a.denom, a.quality_score,
               a.training_eligible, a.resolution_status, s.source,
               EXISTS(
                 SELECT 1 FROM review_queue rq
                  WHERE rq.image_asset_id = a.id AND rq.status = 'open'
               ) AS routed
          FROM image_assets a
          JOIN source_images s ON s.id = a.source_image_id
         WHERE a.eurio_id IN ({member_ph})
           AND a.resolution_status IN ({status_ph})
           AND a.storage_status = 'present'
         ORDER BY
           CASE WHEN a.face = 'obverse' THEN 1 ELSE 0 END ASC,
           CASE WHEN a.denom = 'not_2eur' THEN 0 ELSE 1 END ASC,
           a.quality_score ASC,
           a.id
         LIMIT ?
        """,
        (*members, *TRIAGE_STATUSES, _TRIAGE_MAX_PER_CLASS),
    ).fetchall()

    crops = [
        {
            "asset_id": r["id"],
            "source": r["source"],
            "file_url": f"/sources/{r['source']}/assets/{r['id']}/file",
            "eurio_id": r["eurio_id"],
            "face": r["face"],
            "denom": r["denom"],
            "quality_score": r["quality_score"],
            "training_eligible": bool(r["training_eligible"]),
            "resolution_status": r["resolution_status"],
            "routed": bool(r["routed"]),
        }
        for r in rows
    ]

    n_eligible = sum(
        1 for c in crops if c["training_eligible"] and c["face"] != "reverse"
    )
    n_unknown = sum(
        1 for c in crops
        if c["training_eligible"] and c["face"] in (None, "unknown")
    )
    n_reverse = sum(
        1 for c in crops if c["training_eligible"] and c["face"] == "reverse"
    )
    n_obverse = sum(
        1 for c in crops if c["training_eligible"] and c["face"] == "obverse"
    )
    n_rejected = sum(1 for c in crops if c["resolution_status"] == "rejected")
    n_review_unrouted = sum(
        1 for c in crops
        if c["resolution_status"] == "needs_review" and not c["routed"]
    )

    return {
        "class_id": d.class_id, "class_kind": d.class_kind,
        "member_eurio_ids": members,
        "n_eligible": n_eligible, "n_unknown_face": n_unknown,
        "n_reverse_flagged": n_reverse, "n_rejected": n_rejected,
        "n_review_unrouted": n_review_unrouted, "n_obverse": n_obverse,
        "underfed": n_eligible < min_real,
        "crops": crops,
    }


def list_training_crops(conn: sqlite3.Connection, cohort_id: str) -> dict:
    """État-DB-portable du funnel d'une cohorte : par classe design_group, les
    crops (statut/éligibilité/routage) + compteurs purement dérivés de ces
    colonnes. AUCUN champ dérivé GPU (r_at_1/confused_with/intruder_*) ni FS
    (has_numista_ref/n_bce_ref) — ceux-ci vivent dans l'overlay LOCAL
    (``serving/lab_routes._cohort_training_overlay``, full server only).

    Lève ``DecisionError(404)`` si la cohorte est inconnue (id ou name)."""
    cohort_row = _get_cohort_row(conn, cohort_id)
    if cohort_row is None:
        raise DecisionError(404, "Cohort introuvable")

    eurio_ids = json.loads(cohort_row["eurio_ids_json"])

    resolver = _resolver_from_conn(conn)
    descriptors, _unresolved = resolver.classes_for_eurio_ids(eurio_ids)

    thresholds = resolve_thresholds(conn, cohort_id=cohort_row["id"])
    classes = [_class_state(conn, d, thresholds.min_real) for d in descriptors]

    return {
        "cohort_id": cohort_row["id"],
        "cohort_name": cohort_row["name"],
        "min_real": thresholds.min_real,
        # Les trois seuils AVEC leur provenance : l'écran doit pouvoir dire
        # « plancher 25 (réglage de cette cohorte) » et non un nombre orphelin.
        "thresholds": thresholds.to_dict(),
        "classes": classes,
    }
