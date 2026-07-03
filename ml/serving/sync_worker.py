"""Worker de sync automatique (local-sync) — thread démon du serveur ML local.

Boucle toutes les ``_POLL_S`` secondes sur ``sync_outbox`` :
- sync déclenchée quand le plus ancien op pending a ≥ ``EURIO_SYNC_DEBOUNCE_S``
  (défaut 600 s) — latence bornée à ~10 min sous travail continu, zéro requête
  réseau quand rien n'a changé ;
- pull-only périodique à la même cadence même sans pending (une machine passive
  doit recevoir les writes VPS / autre machine) ;
- ``trigger()`` (bouton du badge, ``POST /sync/trigger``) court-circuite tout ;
- backoff exponentiel 60 s → 900 s après échec (offline-friendly : l'outbox
  tamponne, la reconnexion rattrape).

Pas d'état in-memory critique : tout vit dans ``sync_outbox``/``sync_state``
→ le ``--reload`` d'uvicorn qui tue le thread est inoffensif (il renaît au
startup suivant). Singleton par process (garde ``_worker``).
"""
from __future__ import annotations

import logging
import os
import threading
import time
from datetime import datetime, timezone

from client.sync import run_sync_cycle, sync_enabled
from store import Store, machine_id

logger = logging.getLogger(__name__)

_POLL_S = 30
_BACKOFF_BASE_S = 60
_BACKOFF_CAP_S = 900


def _debounce_s() -> int:
    return int(os.environ.get("EURIO_SYNC_DEBOUNCE_S", "600"))


class SyncWorker(threading.Thread):
    def __init__(self, store: Store) -> None:
        super().__init__(name="sync-worker", daemon=True)
        self._store = store
        self._wake = threading.Event()
        self._stop = threading.Event()
        self._lock = threading.Lock()
        # État observable (le détail durable vit dans sync_state).
        self.syncing = False
        self.consecutive_failures = 0
        self.next_retry_at: float | None = None
        self.last_pull_only_at: float = 0.0

    # ── Commandes ──────────────────────────────────────────────────────────

    def trigger(self) -> None:
        """Sync immédiate (bouton badge / fin de session)."""
        self.next_retry_at = None
        self._wake.set()

    def stop(self) -> None:
        self._stop.set()
        self._wake.set()

    # ── Boucle ─────────────────────────────────────────────────────────────

    def run(self) -> None:  # noqa: D102
        if not sync_enabled():
            logger.info("[sync-worker] EURIO_API_URL absent — worker inactif")
            return
        logger.info(
            "[sync-worker] démarré (debounce %ss, poll %ss)", _debounce_s(), _POLL_S,
        )
        while not self._stop.is_set():
            triggered = self._wake.wait(timeout=_POLL_S)
            self._wake.clear()
            if self._stop.is_set():
                return
            try:
                if triggered or self._due():
                    self._cycle()
            except Exception:  # noqa: BLE001 — le worker ne meurt jamais
                logger.exception("[sync-worker] itération en échec")

    def _due(self) -> bool:
        now = time.time()
        if self.next_retry_at is not None:
            return now >= self.next_retry_at
        conn = self._store._connection()  # noqa: SLF001
        row = conn.execute(
            "SELECT COUNT(*) AS n, "
            "  CAST((julianday('now') - julianday(MIN(created_at))) * 86400 AS REAL) AS age_s "
            "FROM sync_outbox WHERE status='pending'"
        ).fetchone()
        if row["n"] and (row["age_s"] or 0) >= _debounce_s():
            return True
        # Pull-only périodique : récupérer le travail des autres même sans
        # mutation locale.
        return (now - self.last_pull_only_at) >= _debounce_s()

    def _cycle(self) -> None:
        with self._lock:
            self.syncing = True
        try:
            conn = self._store._connection()  # noqa: SLF001
            report = run_sync_cycle(conn)
            if report.ok:
                self.consecutive_failures = 0
                self.next_retry_at = None
                self.last_pull_only_at = time.time()
                logger.info(
                    "[sync-worker] cycle ok — push=%d pull=%d purge=%d",
                    report.pushed,
                    report.pulled_events + report.pulled_tombstones,
                    report.purged,
                )
            else:
                self.consecutive_failures += 1
                delay = min(
                    _BACKOFF_BASE_S * (2 ** (self.consecutive_failures - 1)),
                    _BACKOFF_CAP_S,
                )
                self.next_retry_at = time.time() + delay
                logger.warning(
                    "[sync-worker] échec #%d (%s) — retry dans %ds",
                    self.consecutive_failures, report.error, delay,
                )
        finally:
            with self._lock:
                self.syncing = False

    # ── Statut (consommé par /sync/status) ────────────────────────────────

    def status(self) -> dict:
        conn = self._store._connection()  # noqa: SLF001

        def kv(key: str) -> str | None:
            row = conn.execute(
                "SELECT value FROM sync_state WHERE key=?", (key,)
            ).fetchone()
            return row[0] if row is not None else None

        pending = conn.execute(
            "SELECT COUNT(*) AS n, MIN(created_at) AS oldest "
            "FROM sync_outbox WHERE status='pending'"
        ).fetchone()
        if not sync_enabled():
            state = "disabled"
        elif self.syncing:
            state = "syncing"
        elif self.next_retry_at is not None or kv("last_sync_ok") == "0":
            state = "error"
        elif pending["n"]:
            state = "pending"
        else:
            state = "ok"
        deadline = None
        if pending["n"] and pending["oldest"]:
            oldest = datetime.fromisoformat(pending["oldest"]).replace(
                tzinfo=timezone.utc,
            )
            deadline = oldest.timestamp() + _debounce_s()
        return {
            "state": state,
            "machine_id": machine_id(conn),
            "pending_events": pending["n"],
            "last_sync_at": kv("last_sync_at"),
            "last_sync_ok": kv("last_sync_ok") == "1",
            "last_error": kv("last_error"),
            "last_push_count": int(kv("last_push_count") or 0),
            "last_pull_count": int(kv("last_pull_count") or 0),
            "debounce_seconds": _debounce_s(),
            "debounce_deadline": deadline,
            "next_retry_at": self.next_retry_at,
            "consecutive_failures": self.consecutive_failures,
            "api_url": os.environ.get("EURIO_API_URL") or None,
        }


_worker: SyncWorker | None = None


def start_worker(store: Store) -> SyncWorker:
    """Démarre le singleton (appelé au startup FastAPI ; idempotent)."""
    global _worker
    if _worker is None or not _worker.is_alive():
        _worker = SyncWorker(store)
        _worker.start()
    return _worker


def get_worker() -> SyncWorker | None:
    return _worker
