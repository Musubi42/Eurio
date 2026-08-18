"""Réglage des seuils d'entraînement — image lean canonique (VPS).

Un seuil est un fait de configuration, donc de l'état : il vit là où vit l'état,
au canonique. Toute la logique est dans ``store.thresholds`` (stdlib-only,
partagée avec le préflight et le funnel) ; ce module n'est qu'une **façade
HTTP** — dep ``db_connection``, ``conn.commit()`` explicite, traduction
``ThresholdError → HTTPException``. Même patron que ``funnel_writes.py``.

⚠️ Monté UNIQUEMENT sur ``server_serve.py`` (lean/VPS), comme
``lab_read_routes``. Sur Mac/PC l'API lit une **réplique en lecture seule** :
y exposer l'écriture ne produirait qu'un ``readonly database`` déguisé. Le front
écrit donc au canonique (``eurioApi``), ce qui est aussi la seule façon d'avoir
un effet immédiat sur ce qu'il affiche.

LE DÉCALAGE, QU'IL FAUT ANNONCER
--------------------------------
Le front voit le nouveau seuil tout de suite (il lit ici). Le **préflight**, lui,
tourne sur la machine locale, qui lit une réplique rafraîchie toutes les 120 s :
son verdict peut mettre jusqu'à deux minutes à changer. C'est pourquoi
``funnel-status`` et ``training-readiness`` renvoient les seuils qu'ILS ont
utilisés — le front compare, et le dit. Sans ça, on aurait exactement la panne
muette que VISION.md interdit.

Cf. docs/work-in-progress/refacto-page-cohorte/DECISIONS.md §D5.
"""
from __future__ import annotations

import sqlite3
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from serving.auth_principal import Principal, require_scope
from serving.deps import db_connection
from store import thresholds as th

router = APIRouter(tags=["lab"])

ConnDep = Annotated[sqlite3.Connection, Depends(db_connection)]
ReadDep = Annotated[Principal, Depends(require_scope("lab:read"))]
WriteDep = Annotated[Principal, Depends(require_scope("lab:write"))]


class ThresholdPayload(BaseModel):
    """``value = null`` sur une cohorte = retirer la surcharge (la cohorte
    retombe sur le défaut global, y compris quand celui-ci bougera ensuite)."""

    key: str = Field(description="m_per_class | min_real | training_target")
    value: int | None = None
    note: str | None = None


def _who(principal: Principal) -> str | None:
    return getattr(principal, "user_id", None)


def _apply(conn: sqlite3.Connection, work) -> dict:
    conn.execute("PRAGMA busy_timeout=5000")
    try:
        result = work()
        conn.commit()
        return result
    except th.ThresholdError as exc:
        conn.rollback()
        raise HTTPException(status_code=exc.status_code, detail=exc.detail)
    except Exception:
        conn.rollback()
        raise


@router.get("/lab/thresholds")
def get_thresholds(principal: ReadDep, conn: ConnDep) -> dict:
    """Les défauts globaux, l'effectif, et l'historique des changements."""
    return th.read_state(conn)


@router.put("/lab/thresholds")
def put_threshold(payload: ThresholdPayload, principal: WriteDep, conn: ConnDep) -> dict:
    """Change un défaut global. Il n'y a rien à « retirer » ici : le global EST
    le dernier étage réglable (en dessous, la constante Python)."""
    if payload.value is None:
        raise HTTPException(
            status_code=400,
            detail="Le défaut global se change, il ne se retire pas — donne une valeur.",
        )
    changed = _apply(
        conn,
        lambda: th.set_threshold(
            conn, payload.key, payload.value,
            scope="global", note=payload.note, changed_by=_who(principal),
        ),
    )
    return {**changed, "state": th.read_state(conn)}


def _resolve_cohort(conn: sqlite3.Connection, id_or_name: str) -> str:
    """id d'abord, puis name — comme le reste des routes lab.

    Résoudre des DEUX côtés (lecture ET écriture) est ce qui évite le pire des
    bugs possibles ici : une cohorte ouverte par son nom écrirait sa surcharge
    sous l'id et la relirait sous le nom, donc afficherait « aucune surcharge »
    juste après en avoir posé une."""
    row = conn.execute(
        "SELECT id FROM experiment_cohorts WHERE id = ? OR name = ?",
        (id_or_name, id_or_name),
    ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Cohort introuvable")
    return row[0]


@router.get("/lab/cohorts/{cohort_id}/thresholds")
def get_cohort_thresholds(cohort_id: str, principal: ReadDep, conn: ConnDep) -> dict:
    """Ce qui s'applique à CETTE cohorte, et d'où chaque valeur vient."""
    return th.read_state(conn, cohort_id=_resolve_cohort(conn, cohort_id))


@router.put("/lab/cohorts/{cohort_id}/thresholds")
def put_cohort_threshold(
    cohort_id: str, payload: ThresholdPayload, principal: WriteDep, conn: ConnDep,
) -> dict:
    """Surcharge (ou libère) un seuil pour une cohorte — une cohorte d'essai
    peut viser plus haut sans changer la règle générale."""
    resolved_id = _resolve_cohort(conn, cohort_id)

    if payload.value is None:
        changed = _apply(
            conn,
            lambda: th.clear_threshold(
                conn, payload.key, scope="cohort", scope_id=resolved_id,
                note=payload.note, changed_by=_who(principal),
            ),
        )
    else:
        changed = _apply(
            conn,
            lambda: th.set_threshold(
                conn, payload.key, payload.value, scope="cohort",
                scope_id=resolved_id, note=payload.note, changed_by=_who(principal),
            ),
        )
    return {**changed, "state": th.read_state(conn, cohort_id=resolved_id)}
