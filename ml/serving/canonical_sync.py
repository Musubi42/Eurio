"""Sync du canonique VPS → MinIO (Model B / C8 cutover).

Le VPS est le **writer unique** (Model B : seul `/ingest/run` + les écritures
review écrivent le canonique `/var/lib/eurio/eurio.db`). Mais `client.replica.
pull_replica()` tire la réplique depuis **MinIO** (bucket `eurio-db`, cf.
`store.lease`). Pour que la réplique que le compute pull reflète l'état FRAIS du
canonique (et non le snapshot Model A périmé), ce module pousse périodiquement le
canonique VPS vers MinIO (objet `eurio.db` + sha `eurio.db.sha256`).

Snapshot **cohérent** sous écritures concurrentes : `VACUUM INTO` (transaction de
lecture WAL → copie défragmentée intègre, même si eurio-api écrit en parallèle).
Garde par sha : si le canonique n'a pas changé depuis le dernier push, no-op.

Pose aussi le **lock MinIO** au nom du VPS (`eurio.db.lock`) → un `go-task
ml:db:acquire` Model A accidentel est REFUSÉ (lease devient secours : `steal
--force`). `pull_replica` ne touche jamais le lock → le compute Model B n'est pas
gêné.

Usage :
    python -m serving.canonical_sync            # one-shot (cron / manuel)
    python -m serving.canonical_sync --force    # ignore la garde sha
La boucle de fond est démarrée par le startup de `server_serve.py`.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import socket
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from store.lease import (
    BUCKET,
    DB_KEY,
    LOCK_KEY,
    SHA_KEY,
    _get_text,
    _s3,
    _sha256,
)

log = logging.getLogger("eurio-api.canonical_sync")

_DB_PATH = Path(os.environ.get("EURIO_DB_PATH", "/var/lib/eurio/eurio.db"))
_SYNC_INTERVAL_S = int(os.environ.get("EURIO_CANONICAL_SYNC_INTERVAL_S", "600"))


def _snapshot(dest: Path) -> None:
    """Copie cohérente du canonique (VACUUM INTO — intègre sous écritures WAL)."""
    dest.unlink(missing_ok=True)  # VACUUM INTO échoue si la cible existe
    conn = sqlite3.connect(str(_DB_PATH))
    try:
        conn.execute("VACUUM INTO ?", (str(dest),))
    finally:
        conn.close()


def _vps_lock_payload() -> bytes:
    return json.dumps({
        "holder_host": socket.gethostname(),
        "pid": os.getpid(),
        "acquired_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "note": "VPS canonical (Model B) — ne PAS acquire ; secours: db:steal --force",
    }).encode()


def sync_canonical(*, force: bool = False) -> dict:
    """Pousse le canonique VPS → MinIO si son sha a changé. Pose/rafraîchit le lock.

    Retourne ``{"synced": bool, "sha": <hex|None>, "reason": str}``.
    """
    if not _DB_PATH.exists():
        return {"synced": False, "sha": None, "reason": f"{_DB_PATH} introuvable"}

    client = _s3()
    snap = _DB_PATH.with_suffix(".db.minio-snapshot")
    try:
        _snapshot(snap)
        sha = _sha256(snap)
        remote_sha = None
        try:
            remote_sha = _get_text(client, SHA_KEY)
        except Exception:  # noqa: BLE001 — distant illisible → on pousse quand même
            pass
        if not force and remote_sha == sha:
            return {"synced": False, "sha": sha, "reason": "déjà à jour (sha identique)"}

        client.upload_file(str(snap), BUCKET, DB_KEY)
        client.put_object(Bucket=BUCKET, Key=SHA_KEY, Body=sha.encode())
        # Lock VPS (overwrite idempotent) → bloque un acquire Model A accidentel.
        client.put_object(Bucket=BUCKET, Key=LOCK_KEY, Body=_vps_lock_payload())
        log.info("canonical_sync: poussé eurio.db (%s…) → %s/%s", sha[:12], BUCKET, DB_KEY)
        return {"synced": True, "sha": sha, "reason": "poussé"}
    finally:
        snap.unlink(missing_ok=True)


async def _loop(interval_s: int) -> None:
    log.info("canonical_sync: boucle de fond démarrée (intervalle %ds)", interval_s)
    while True:
        try:
            await asyncio.to_thread(sync_canonical)
        except Exception as exc:  # noqa: BLE001 — best-effort, ne jamais crasher l'API
            log.warning("canonical_sync: échec (réessai au prochain tick) : %s", exc)
        await asyncio.sleep(interval_s)


def start_background_sync(interval_s: int | None = None) -> asyncio.Task:
    """Démarre la boucle de sync en tâche asyncio (appelée au startup FastAPI)."""
    return asyncio.create_task(_loop(interval_s or _SYNC_INTERVAL_S))


def main(argv: list[str] | None = None) -> int:
    import argparse

    logging.basicConfig(level=logging.INFO, format="%(message)s")
    p = argparse.ArgumentParser(prog="python -m serving.canonical_sync")
    p.add_argument("--force", action="store_true", help="ignore la garde sha")
    args = p.parse_args(argv)
    res = sync_canonical(force=args.force)
    print(f"sync_canonical → {res}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
