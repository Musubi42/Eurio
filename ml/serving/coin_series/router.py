"""Routes HTTP du domaine `coin_series` — thin layer (auth, errors).

Pas de SQL ni de logique métier ici (délégué à `repository.py`).

URLs (D2 data-layer-unification) :
- ``GET /coin-series``              — liste complète (picker série studio-local)
- ``GET /coin-series/{series_id}``  — détail d'une série

Scope `coins:read` (cf. ARCHITECTURE.md §3.4).
"""
from __future__ import annotations

import sqlite3
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException

from serving.auth_principal import Principal, require_scope
from serving.deps import db_connection

from . import repository
from .models import CoinSeries

router = APIRouter(tags=["coin-series"])

_require_read = require_scope("coins:read")

ConnDep = Annotated[sqlite3.Connection, Depends(db_connection)]
PrincipalDep = Annotated[Principal, Depends(_require_read)]


@router.get("/coin-series", response_model=list[CoinSeries])
def list_coin_series(principal: PrincipalDep, conn: ConnDep) -> list[CoinSeries]:
    return repository.list_series(conn)


@router.get("/coin-series/{series_id}", response_model=CoinSeries)
def get_coin_series(series_id: str, principal: PrincipalDep, conn: ConnDep) -> CoinSeries:
    try:
        return repository.get_series(conn, series_id)
    except repository.SeriesNotFound:
        raise HTTPException(status_code=404, detail=f"coin_series not found: {series_id}")
