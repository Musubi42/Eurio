"""Rail `jobs/` — jobs longs en subprocess détaché, survivant au `--reload`.

Voir `docs/refacto-ml/adr.md` D1. API publique :

  - `launch(conn, kind=…, cmd=…)`     → lance un job détaché, retourne {job_id, pid, log_path}
  - `job_progress / job_finish`        → le child met à jour son cycle de vie
  - `job_get / job_latest`             → l'API lit le statut
  - `reap_orphans(conn)`               → reaper boot (hook startup serving)
"""

from .conn import connection
from .db import (
    job_by_param,
    job_finish,
    job_get,
    job_latest,
    job_progress,
    job_set_pid,
    job_start,
)
from .reaper import _pid_alive, reap_orphans
from .runner import job_id_from_argv, launch, proc_dead, stop_process_group

__all__ = [
    "_pid_alive",
    "connection",
    "job_by_param",
    "job_finish",
    "job_get",
    "job_id_from_argv",
    "job_latest",
    "job_progress",
    "job_set_pid",
    "job_start",
    "launch",
    "proc_dead",
    "reap_orphans",
    "stop_process_group",
]
