"""Réglage des seuils DINO — image lean canonique (VPS).

Calque de ``serving/thresholds_routes.py`` (les seuils d'entraînement) : toute
la logique vit dans ``store.dino_thresholds`` (stdlib-only, partagé avec le
verdict et la file de review) ; ce module n'est qu'une façade HTTP.

La différence tient en un mot : la **portée**. Un seuil DINO appartient à un
couple `(banque, encodeur)`, pas à une cohorte — 0,55 calibré sur vits14 ne
veut rien dire pour vitl14. Les deux paramètres sont donc obligatoires, et
l'écran doit les afficher : un seuil sans son encodeur est un nombre sans père.

⚠️ Monté UNIQUEMENT sur ``server_serve.py`` (lean/VPS). Sur Mac/PC l'API lit une
réplique en lecture seule ; y exposer l'écriture ne produirait qu'un
``readonly database`` déguisé.

Cf. docs/work-in-progress/banque-dino/DECISIONS.md §D5.
"""
from __future__ import annotations

import sqlite3
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from serving.auth_principal import Principal, require_scope
from serving.deps import db_connection
from store import dino_thresholds as dt

router = APIRouter(tags=["lab"])

ConnDep = Annotated[sqlite3.Connection, Depends(db_connection)]
ReadDep = Annotated[Principal, Depends(require_scope("lab:read"))]
WriteDep = Annotated[Principal, Depends(require_scope("training:run"))]


class DinoThresholdPayload(BaseModel):
    """``value = null`` retire la surcharge : le couple retombe sur le défaut
    du code, y compris si celui-ci change plus tard."""

    anchors_kind: str
    encoder_version: str
    key: str = Field(description=" | ".join(dt.KEYS))
    value: float | None = None
    #: Sur quoi la valeur a été calibrée. Ce n'est pas décoratif : sans lui,
    #: personne n'ose bouger un nombre dont il ignore l'origine.
    calibrated_on: str | None = None
    precision_at: float | None = None
    n_samples: int | None = None
    note: str | None = None


def _who(principal: Principal) -> str | None:
    return getattr(principal, "user_id", None)


def _apply(conn: sqlite3.Connection, work) -> dict:
    conn.execute("PRAGMA busy_timeout=5000")
    try:
        result = work()
        conn.commit()
        return result
    except dt.DinoThresholdError as exc:
        conn.rollback()
        raise HTTPException(status_code=exc.status_code, detail=exc.detail)
    except Exception:
        conn.rollback()
        raise


@router.get("/lab/dino-thresholds")
def get_dino_thresholds(
    principal: ReadDep,
    conn: ConnDep,
    anchors_kind: str = Query(default="2eur_all"),
    encoder_version: str = Query(default="dinov2-vitl14"),
) -> dict:
    """Les seuils effectifs d'un couple, leur provenance et leur historique."""
    return dt.read_state(
        conn, anchors_kind=anchors_kind, encoder_version=encoder_version,
    )


@router.put("/lab/dino-thresholds")
def put_dino_threshold(
    payload: DinoThresholdPayload, principal: WriteDep, conn: ConnDep,
) -> dict:
    """Pose (ou retire) un seuil pour un couple (banque, encodeur)."""
    if payload.value is None:
        changed = _apply(
            conn,
            lambda: dt.clear_threshold(
                conn, payload.key,
                anchors_kind=payload.anchors_kind,
                encoder_version=payload.encoder_version,
                note=payload.note, changed_by=_who(principal),
            ),
        )
    else:
        changed = _apply(
            conn,
            lambda: dt.set_threshold(
                conn, payload.key, payload.value,
                anchors_kind=payload.anchors_kind,
                encoder_version=payload.encoder_version,
                calibrated_on=payload.calibrated_on,
                precision_at=payload.precision_at,
                n_samples=payload.n_samples,
                note=payload.note, changed_by=_who(principal),
            ),
        )
    return {
        **changed,
        "state": dt.read_state(
            conn,
            anchors_kind=payload.anchors_kind,
            encoder_version=payload.encoder_version,
        ),
    }
