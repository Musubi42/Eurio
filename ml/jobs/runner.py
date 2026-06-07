"""Lanceur de jobs longs en subprocess DÉTACHÉ (refacto-ml ADR D1).

Généralise le pattern éprouvé du recrop cohorte (`lab_routes.recrop_zero_coin`) :

  - `start_new_session=True` → le child sort du process-group du worker uvicorn,
    donc il **survit au `--reload`** (un save de fichier back-end ne tue plus le job).
  - stdout+stderr redirigés vers un **fichier de log** sous `state/job_logs/` — l'API
    ne lit jamais `proc.stdout` dans son thread (découplage du cycle de vie serving).
  - le PID est persisté en table (`job_set_pid`) → le reaper boot peut distinguer un
    job vivant d'un orphelin réel (`os.kill(pid, 0)`).

L'API appelante ne fait que `launch()` (enqueue) puis lit le statut via `jobs.db`.
"""

from __future__ import annotations

import logging
import os
import signal
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Callable, Sequence

from . import db
from .reaper import _pid_alive

logger = logging.getLogger(__name__)

# ml/ (ce fichier vit dans ml/jobs/runner.py)
ML_DIR = Path(__file__).resolve().parent.parent
LOG_DIR = ML_DIR / "state" / "job_logs"


def launch(
    conn,
    *,
    kind: str,
    cmd_builder: Callable[[str], Sequence[str]],
    cwd: Path | str | None = None,
    n_total: int | None = None,
    params: dict[str, Any] | None = None,
    env_extra: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Ouvre un job et lance la commande construite par `cmd_builder` en subprocess détaché.

    `conn`        : connexion SQLite autocommit (typiquement `store._connection()`).
    `cmd_builder` : `job_id -> argv`. Le job est créé d'abord (pour générer l'id),
                    puis `cmd_builder(job_id)` construit l'argv — le child reçoit
                    ainsi toujours son `--job-id` (cf. pattern cohorte).

    Retourne `{job_id, pid, log_path}`.

    Le child possède le cycle de vie du job : c'est à LUI d'appeler `job_progress`
    / `job_finish` via sa propre connexion. Un crash réel laisse le job `running`
    sans PID vivant → le reaper boot le clôt en `failed`.
    """
    job_id = db.job_start(conn, kind=kind, n_total=n_total, params=params)
    cmd = list(cmd_builder(job_id))

    LOG_DIR.mkdir(parents=True, exist_ok=True)
    log_path = LOG_DIR / f"{kind}-{job_id}.log"

    env = dict(os.environ)
    existing = env.get("PYTHONPATH", "")
    # ml/ sur le PYTHONPATH du child (imports `state`, `jobs`, … en absolu).
    env["PYTHONPATH"] = str(ML_DIR) + (os.pathsep + existing if existing else "")
    if env_extra:
        env.update(env_extra)

    logf = log_path.open("w")
    try:
        proc = subprocess.Popen(
            cmd,
            cwd=str(cwd or ML_DIR),
            env=env,
            stdout=logf,
            stderr=subprocess.STDOUT,
            start_new_session=True,  # détache du process-group du worker --reload
        )
    finally:
        logf.close()  # le child garde son propre fd ouvert

    db.job_set_pid(conn, job_id, proc.pid)
    # log_path persisté pour que l'UI/API puisse pointer le fichier sans le recalculer.
    conn.execute("UPDATE jobs SET log_path=? WHERE id=?", (str(log_path), job_id))

    logger.info("[jobs] %s spawned subprocess pid=%s job=%s log=%s",
                kind, proc.pid, job_id, log_path)
    return {"job_id": job_id, "pid": proc.pid, "log_path": str(log_path)}


def proc_dead(pid: int) -> bool:
    """True si le process est mort. Robuste au cas zombie : un subprocess détaché
    est l'enfant du lanceur → à sa mort il devient zombie et `os.kill(pid, 0)` le
    voit encore « vivant ». On le `waitpid`-reap (WNOHANG) ; s'il a été reparenté
    (le lanceur a redémarré), il n'est plus notre enfant → fallback `kill(0)`."""
    try:
        wpid, _ = os.waitpid(pid, os.WNOHANG)
        return wpid == pid  # reapé → mort ; 0 → encore vivant
    except ChildProcessError:
        return not _pid_alive(pid)  # pas (plus) notre enfant
    except OSError:
        return not _pid_alive(pid)


def stop_process_group(pid: int, *, graceful_timeout: float = 30.0) -> str:
    """SIGTERM puis (au timeout) SIGKILL le **groupe** d'un job détaché.

    Un job lancé par `launch` est leader de session (`start_new_session`) → son
    PGID == PID ; signaler le groupe propage aux enfants (train_embedder, export,
    benchmark…). Retourne ``'graceful'``, ``'forced'`` ou ``'idle'``."""
    try:
        pgid = os.getpgid(pid)
    except ProcessLookupError:
        return "idle"
    try:
        os.killpg(pgid, signal.SIGTERM)
    except ProcessLookupError:
        return "idle"
    deadline = time.time() + graceful_timeout
    while time.time() < deadline:
        if proc_dead(pid):
            return "graceful"
        time.sleep(0.2)
    try:
        os.killpg(pgid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError):
        return "graceful"  # mort entre-temps
    return "forced"


# Helper de confort pour les scripts enfants : argv standard `--job-id <id>`.
def job_id_from_argv(argv: Sequence[str] | None = None) -> str | None:
    """Extrait `--job-id <id>` d'argv (ou sys.argv). None si absent."""
    args = list(argv if argv is not None else sys.argv[1:])
    for i, a in enumerate(args):
        if a == "--job-id" and i + 1 < len(args):
            return args[i + 1]
        if a.startswith("--job-id="):
            return a.split("=", 1)[1]
    return None
