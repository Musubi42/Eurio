"""Lecture des résultats du banc multi-encodeurs — façade HTTP mince.

Calque de ``serving/dino_thresholds_routes.py`` : toute la logique vit dans
``store.encoder_bench`` (stdlib-only) ; ce module ne fait que traduire.

Le champ ``provisional`` remonte **en tête** de la réponse détaillée. Ce n'est
pas cosmétique : la page admin doit pouvoir afficher « gagnant » et
« provisoire » du même coup d'œil. Tant que P1 et P3 ne sont pas passés, tous
les runs valent 1.

⚠️ Aucun import lourd au niveau module (numpy, torch, cv2, timm) : sur l'image
lean du VPS un import qui échoue fait skipper le routeur ENTIER, en silence.

Le montage sur ``server_serve.py`` est fait ailleurs (agent d'intégration).
"""

from __future__ import annotations

import json
import logging
import sqlite3
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query

from serving.auth_principal import Principal, require_scope
from serving.deps import db_connection
from store import encoder_bench as eb

logger = logging.getLogger(__name__)

router = APIRouter(tags=["lab"])

ConnDep = Annotated[sqlite3.Connection, Depends(db_connection)]
ReadDep = Annotated[Principal, Depends(require_scope("lab:read"))]


@router.get("/lab/encoder-bench/runs")
def list_encoder_bench_runs(
    principal: ReadDep,
    conn: ConnDep,
    anchors_kind: str | None = Query(default=None),
    encoder_version: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=500),
) -> dict:
    """Les runs du banc, du plus récent au plus ancien."""
    runs = eb.list_runs(
        conn,
        anchors_kind=anchors_kind,
        encoder_version=encoder_version,
        limit=limit,
    )
    return {"runs": runs, "n": len(runs)}


@router.get("/lab/encoder-bench/runs/{run_id}")
def get_encoder_bench_run(run_id: str, principal: ReadDep, conn: ConnDep) -> dict:
    """Un run, ``sweep_json`` désérialisé et ``provisional`` en tête.

    ``sweep_error`` est non nul quand la courbe stockée est illisible : sans
    lui, une courbe corrompue était indistinguable d'un run sans balayage —
    côté page admin comme côté logs, puisque le ``except`` était muet.
    """
    run = eb.get_run(conn, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail=f"run inconnu: {run_id}")
    sweep_raw = run.pop("sweep_json", None)
    sweep: list | None = None
    sweep_error: str | None = None
    if sweep_raw:
        try:
            sweep = json.loads(sweep_raw)
        except (TypeError, ValueError) as exc:
            # Une courbe illisible ne doit pas masquer le reste du run — mais
            # elle ne doit pas non plus se faire passer pour une courbe vide :
            # elle se journalise et elle se dit dans la réponse.
            sweep = None
            sweep_error = f"{type(exc).__name__}: {exc}"
            logger.error(
                "run %s : sweep_json illisible (%s) — la courbe est corrompue "
                "en base, le reste du run est rendu tel quel",
                run_id,
                sweep_error,
            )
    return {
        "provisional": bool(run.get("provisional", 1)),
        "provisional_reason": run.get("provisional_reason"),
        "run": run,
        "sweep": sweep,
        "sweep_error": sweep_error,
    }
