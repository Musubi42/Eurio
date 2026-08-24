"""Relancer la banque d'ancres depuis l'écran — routes LOURDES (workstation).

Montées sur ``serving/server.py`` **seulement**. Le VPS porte l'image lean : ni
torch, ni banque, ni les 6 Go d'images à réencoder. La carte de l'accueil, elle,
s'affiche partout (l'écart est du SQL pur, cf. ``dino_drift_routes``) ; c'est le
BOUTON qui se grise en hébergé, jamais le chiffre.

Le pattern est celui du scan d'entraînement (``lab_routes.start_training_scan``)
et il n'est pas réinventé ici : **202 + subprocess détaché + état en base locale
+ GET status + poll**. Ce qu'il achète, dans l'ordre où on l'a payé :

* `start_new_session=True` — torch hors du worker uvicorn, et le job survit à un
  `--reload` en plein rebuild ;
* l'état en base plutôt qu'en mémoire — il survit au restart, et deux onglets
  voient la même chose ;
* un reaper au boot — sans lui, un job tué laisse une ligne 'running' éternelle,
  la garde 409 refuse alors TOUT rebuild ultérieur, et l'écran affiche « en
  cours » sur un processus mort. Cette panne-là ressemble à de la patience.
"""
from __future__ import annotations

import logging
import os
import subprocess
import sys
from pathlib import Path
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from shared.verdict_scope import (
    VERDICT_ANCHORS_KIND,
    VERDICT_ENCODER_VERSION_FOR_KIND,
)
from store import local_state_store
from store.dino_rebuild_jobs import (
    latest_rebuild,
    reap_orphan_rebuilds,
    rebuild_set_pid,
    rebuild_start,
)

logger = logging.getLogger(__name__)
router = APIRouter(tags=["dino"])

_ML_DIR = Path(__file__).resolve().parents[1]

# ⛔ PAS de dépendance de principal ici, et c'est délibéré — corrigé en revue
# le 2026-08-24 après avoir posé `require_scope("review:arbitrate")`.
#
# Cette API-ci est `:8042`, la workstation. Elle n'a pas de session : le front
# l'appelle en `fetch` nu (aucun autre appel `ML_API` du front ne porte
# d'en-tête), et le PAT qu'il détient vaut pour le CANONIQUE, pas pour elle.
# Exiger un scope rendait donc les deux routes inatteignables — le bouton aurait
# rendu 401 à chaque clic et le statut serait resté nul, c'est-à-dire un bouton
# mort livré avec sa propre excuse.
#
# Ce qui protège réellement : l'API n'écoute que la machine de l'opérateur, et
# le bouton n'est DESSINÉ que pour un arbitre (`showHeavyGesture`). C'est la
# posture de toute la surface lourde — cf. `lab_routes.start_training_scan`,
# qui lance un job de même nature sans dépendance de principal.


class RebuildStatus(BaseModel):
    """`idle` si aucun rebuild n'a jamais tourné sur cette machine."""

    status: str                      # idle | running | done | failed
    job_id: str | None = None
    step: str | None = None          # anchors | predictions | done
    anchors_kind: str | None = None
    encoder_version: str | None = None
    build_id: str | None = None
    n_anchors: int | None = None
    n_predictions: int | None = None
    started_at: str | None = None
    finished_at: str | None = None
    error: str | None = None


def _local_conn():
    # Base LOCALE : inscriptible même sous le flip Direction A, où le canonique
    # local est une réplique read-only. L'état d'un job ne doit pas dépendre du
    # sens du flip pour pouvoir s'écrire.
    return local_state_store()._connection()  # noqa: SLF001


def _to_status(row) -> RebuildStatus:
    return RebuildStatus(
        status=row["status"], job_id=row["id"], step=row["step"],
        anchors_kind=row["anchors_kind"], encoder_version=row["encoder_version"],
        build_id=row["build_id"], n_anchors=row["n_anchors"],
        n_predictions=row["n_predictions"], started_at=row["started_at"],
        finished_at=row["finished_at"], error=row["error"],
    )


@router.post("/dino/rebuild", status_code=202, response_model=RebuildStatus)
def start_rebuild(
    anchors_kind: str = Query(default=VERDICT_ANCHORS_KIND),
) -> RebuildStatus:
    """Rebâtit la banque PUIS recalcule les prédictions. ~20 min sur MPS.

    Les deux étapes sont un seul job, délibérément : n'en faire qu'une laisse
    les prédictions répondre sur une banque qui n'existe plus, sans que rien ne
    le dise. 409 si un rebuild tourne déjà.
    """
    encoder = VERDICT_ENCODER_VERSION_FOR_KIND.get(anchors_kind)
    if encoder is None:
        # Un couple inventé donnerait un JOIN à zéro ligne partout en aval,
        # sans erreur. On refuse tôt plutôt que de produire une banque orpheline.
        raise HTTPException(
            status_code=400,
            detail=f"banque inconnue : {anchors_kind} — "
                   f"connues : {sorted(VERDICT_ENCODER_VERSION_FOR_KIND)}",
        )

    # Sans `EURIO_API_URL`, la trace n'a nulle part où aller : le build
    # retomberait sur la sonde d'écriture locale et mourrait au démarrage. On
    # refuse ICI, avec la cause — plutôt que de laisser l'écran afficher un
    # « failed » quatre secondes plus tard.
    from client.http import sync_enabled

    if not sync_enabled():
        raise HTTPException(
            status_code=409,
            detail="EURIO_API_URL absent de l'environnement de l'API : la trace "
                   "de la banque n'aurait aucune destination et le build "
                   "échouerait au démarrage. Relance l'API depuis le devShell.",
        )

    conn = _local_conn()
    reap_orphan_rebuilds(conn)
    running = latest_rebuild(conn, status="running")
    if running is not None:
        raise HTTPException(
            status_code=409,
            detail={"code": "dino_rebuild_already_running", "job_id": running["id"]},
        )

    log_dir = _ML_DIR / "state" / "job_logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    job_id = rebuild_start(
        conn, anchors_kind=anchors_kind, encoder_version=encoder)
    log_path = log_dir / f"dino-rebuild-{job_id}.log"
    conn.execute("UPDATE dino_rebuild_jobs SET log_path=? WHERE id=?",
                 (str(log_path), job_id))
    conn.commit()

    env = dict(os.environ)
    existing = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = str(_ML_DIR) + (os.pathsep + existing if existing else "")
    # ⛔ NE PAS toucher à `EURIO_DB_READONLY`. Le premier jet le VIDAIT, en
    # croyant lever un garde-fou : le build trace sa sélection en base, et
    # `ml/tasks.yml` prévient qu'il « refuse de démarrer » sous le flip. Vidé,
    # `Store` tente d'ouvrir la RÉPLIQUE en écriture et la refuse pour la raison
    # INVERSE — le job mourait en une seconde. Vécu le 2026-08-24 depuis l'écran.
    #
    # La vérité est que sous Direction A ce build n'a besoin d'AUCUNE base
    # inscriptible : `preflight_db_traceability` voit que le push est actif et
    # envoie la trace au canonique par `POST /ingest/dino-references`. La note
    # de `tasks.yml` est antérieure à ce chemin-là.

    with log_path.open("w") as logf:
        proc = subprocess.Popen(
            [sys.executable, "-m", "scripts.rebuild_dino_bank",
             "--kind", anchors_kind, "--job-id", job_id],
            cwd=str(_ML_DIR), env=env,
            stdout=logf, stderr=subprocess.STDOUT,
            start_new_session=True,
        )
    # Immédiatement après Popen, avant tout retour au client : la fenêtre sans
    # PID doit être aussi courte que possible. `STARTUP_GRACE_SEC` couvre le
    # reste (un crash entre l'INSERT et ici).
    rebuild_set_pid(conn, job_id, proc.pid)
    logger.info("[dino-rebuild] job=%s pid=%s kind=%s log=%s",
                job_id, proc.pid, anchors_kind, log_path)
    return _to_status(latest_rebuild(conn))


@router.get("/dino/rebuild/status", response_model=RebuildStatus)
def rebuild_status() -> RebuildStatus:
    """Dernier rebuild de CETTE machine (persisté, survit au restart)."""
    conn = _local_conn()
    reap_orphan_rebuilds(conn)
    row = latest_rebuild(conn)
    if row is None:
        return RebuildStatus(status="idle")
    return _to_status(row)
