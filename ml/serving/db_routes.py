"""Endpoint réplique : sert un snapshot cohérent du canonique au compute (Model B / R2).

Remplace le détour MinIO (`canonical_sync` → bucket `eurio-db`, retiré en R2). Le
compute lourd (scrape/crop/dino/dataset) tire sa **réplique read-only** directement
du writer unique via ``GET /db/replica`` (+ ``/db/replica/sha`` pour l'intégrité),
au lieu de lire la copie MinIO. **MinIO ne contient plus la DB.**

Snapshot **cohérent** sous écritures WAL concurrentes : ``VACUUM INTO`` (transaction
de lecture → copie défragmentée intègre, même si eurio-api écrit en parallèle). La
DB fait ~106 Mo → on **streame** le fichier (jamais en RAM) et on **cache** le
snapshot ``EURIO_REPLICA_SNAPSHOT_TTL_S`` secondes pour ne pas VACUUM à chaque pull.

Scope : ``ingest:run`` (le principal compute qui pull la réplique est exactement
celui qui pousse ses runs — pas de scope dédié à minter sur les PAT existants).
"""
from __future__ import annotations

import hashlib
import logging
import os
import sqlite3
import threading
import time
from pathlib import Path

from fastapi import APIRouter, Depends
from fastapi.responses import FileResponse

from serving.auth_principal import require_scope

log = logging.getLogger("eurio-api.db_routes")

router = APIRouter(prefix="/db", tags=["db"])

_DB_PATH = Path(os.environ.get("EURIO_DB_PATH", "/var/lib/eurio/eurio.db"))
_SNAPSHOT_PATH = Path(
    os.environ.get("EURIO_REPLICA_SNAPSHOT_PATH", "/tmp/eurio.replica-snapshot.db")
)
_SNAPSHOT_TTL_S = int(os.environ.get("EURIO_REPLICA_SNAPSHOT_TTL_S", "60"))

_lock = threading.Lock()
# Cache du snapshot courant : (sha, built_at monotonic). Le fichier vit à _SNAPSHOT_PATH.
_cache: dict[str, object] = {"sha": None, "built_at": 0.0}


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _build_snapshot() -> str:
    """Copie cohérente du canonique → _SNAPSHOT_PATH (VACUUM INTO). Retourne le sha."""
    _SNAPSHOT_PATH.parent.mkdir(parents=True, exist_ok=True)
    _SNAPSHOT_PATH.unlink(missing_ok=True)  # VACUUM INTO échoue si la cible existe
    conn = sqlite3.connect(str(_DB_PATH))
    try:
        conn.execute("VACUUM INTO ?", (str(_SNAPSHOT_PATH),))
    finally:
        conn.close()
    return _sha256(_SNAPSHOT_PATH)


def _current_snapshot() -> tuple[Path, str]:
    """Snapshot courant (rebuild si périmé > TTL ou fichier absent). Thread-safe.

    Sur POSIX, un ``unlink`` du fichier pendant qu'un ``FileResponse`` le streame
    est sûr (l'inode reste valide jusqu'à la fermeture du fd) → pas de course.
    """
    with _lock:
        now = time.monotonic()
        fresh = (
            _cache["sha"] is not None
            and _SNAPSHOT_PATH.exists()
            and (now - float(_cache["built_at"])) < _SNAPSHOT_TTL_S
        )
        if not fresh:
            sha = _build_snapshot()
            _cache["sha"] = sha
            _cache["built_at"] = now
            log.info("db_routes: snapshot rebâti (%s…)", sha[:12])
        return _SNAPSHOT_PATH, str(_cache["sha"])


@router.get("/replica", dependencies=[Depends(require_scope("ingest:run"))])
def get_replica() -> FileResponse:
    """Sert un snapshot cohérent du canonique (réplique read-only du compute)."""
    path, sha = _current_snapshot()
    return FileResponse(
        path,
        media_type="application/octet-stream",
        filename="eurio.db",
        headers={"X-Eurio-DB-Sha256": sha},
    )


@router.get("/replica/sha", dependencies=[Depends(require_scope("ingest:run"))])
def get_replica_sha() -> dict:
    """sha256 du snapshot servi par ``GET /db/replica`` (vérif d'intégrité)."""
    _, sha = _current_snapshot()
    return {"sha": sha}
